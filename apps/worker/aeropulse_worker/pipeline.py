"""In-memory processing pipeline used by the worker and unit tests.

Kafka I/O is thin in ``main.py``; this module is deterministic and side-effect
free except for the optional repository callbacks.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Protocol

from aeropulse_common.hashing import dedup_key
from aeropulse_connector_sdk.quality import evaluate_observation
from aeropulse_contracts.fire import FireObservation
from aeropulse_contracts.meteo import MeteorologicalObservation
from aeropulse_contracts.observation import Observation
from aeropulse_contracts.raster import RasterObservation
from aeropulse_geospatial.grid import to_grid_id
from aeropulse_intelligence.detect import process_snapshot
from aeropulse_intelligence.engine import EventStore
from aeropulse_intelligence.snapshot import FeatureSnapshot
from aeropulse_observability.logging import get_logger
from aeropulse_observability.metrics import (
    EVENTS_TRANSITIONED,
    FEATURES_MATERIALIZED,
    INGESTED_OBSERVATIONS,
    QUALITY_REJECTIONS,
    QUALITY_SCORE,
)

logger = get_logger("aeropulse.worker")


class ObservationRepository(Protocol):
    """Persistence port for normalized observations."""

    def upsert_air_quality(self, observation: Observation) -> bool:
        """Insert or ignore an air-quality row. Returns True if inserted."""
        ...

    def upsert_fire(self, observation: FireObservation) -> bool:
        """Insert or ignore a fire row. Returns True if inserted."""
        ...

    def upsert_weather(self, observation: MeteorologicalObservation) -> bool:
        """Insert or ignore a weather row. Returns True if inserted."""
        ...

    def record_dlq(self, source_id: str, payload: dict[str, Any], error: str) -> None:
        """Record a quality-rejected payload. Optional on implementations."""
        ...


class InMemoryRepository:
    """Test double that enforces dedup_key uniqueness.

    Also serves as the worker's live feature snapshot, which is why it carries
    a retention window: under a scheduler this object is long-lived and would
    otherwise accumulate every observation the process has ever seen.
    """

    def __init__(self, retention_hours: int | None = None) -> None:
        """Create a repository, optionally bounded by observation age.

        Args:
            retention_hours: Drop observations older than this many hours,
                measured against the newest observation seen. ``None`` keeps
                everything, which is what unit tests want.
        """
        self.air_quality: dict[str, Observation] = {}
        self.fires: dict[str, FireObservation] = {}
        self.weather: dict[str, MeteorologicalObservation] = {}
        self.rasters: list[RasterObservation] = []
        self.dlq: list[dict[str, Any]] = []
        self.event_store = EventStore()
        self.retention_hours = retention_hours
        self._newest_seen: datetime | None = None

    def upsert_air_quality(self, observation: Observation) -> bool:
        """Store air quality if the dedup key is new."""
        key = observation.dedup_key or observation.observation_id
        if key in self.air_quality:
            return False
        self.air_quality[key] = observation
        self._evict(observation.observed_at)
        return True

    def upsert_fire(self, observation: FireObservation) -> bool:
        """Store fire if the dedup key is new."""
        key = observation.dedup_key or observation.observation_id
        if key in self.fires:
            return False
        self.fires[key] = observation
        self._evict(observation.observed_at)
        return True

    def upsert_weather(self, observation: MeteorologicalObservation) -> bool:
        """Store weather if the dedup key is new."""
        key = observation.dedup_key or observation.observation_id
        if key in self.weather:
            return False
        self.weather[key] = observation
        self._evict(observation.observed_at)
        return True

    def record_dlq(self, source_id: str, payload: dict[str, Any], error: str) -> None:
        """Keep rejected payloads for operator replay."""
        self.dlq.append({"source_id": source_id, "error": error, "payload": payload})

    def add_raster(self, raster: RasterObservation) -> None:
        """Keep raster metadata in the snapshot."""
        self.rasters.append(raster)
        self._evict(raster.acquisition_time)

    def _evict(self, observed_at: datetime) -> None:
        """Drop observations that fall outside the retention window.

        The cutoff tracks the newest observation seen rather than wall-clock
        now, so a backfill replaying historical data does not evict itself on
        arrival.
        """
        if self.retention_hours is None:
            return
        if self._newest_seen is None or observed_at > self._newest_seen:
            self._newest_seen = observed_at
        cutoff = self._newest_seen - timedelta(hours=self.retention_hours)
        self.air_quality = {k: v for k, v in self.air_quality.items() if v.observed_at >= cutoff}
        self.fires = {k: v for k, v in self.fires.items() if v.observed_at >= cutoff}
        self.weather = {k: v for k, v in self.weather.items() if v.observed_at >= cutoff}
        self.rasters = [r for r in self.rasters if r.acquisition_time >= cutoff]


def process_air_quality(
    observation: Observation,
    repository: ObservationRepository,
) -> dict[str, Any]:
    """Quality-score, grid-map, and persist an air-quality observation.

    Args:
        observation: Canonical observation.v1.
        repository: Persistence adapter.

    Returns:
        Result dict with ``status`` of ``persisted``, ``duplicate``, or ``rejected``.
    """
    qc = evaluate_observation(
        parameter=observation.measurement.parameter,
        value=observation.measurement.value,
        lat=observation.location.lat,
        lon=observation.location.lon,
        observed_at=observation.observed_at,
        received_at=observation.received_at,
    )
    observation.quality.quality_flag = qc.quality_flag
    observation.quality.quality_score = qc.quality_score
    if qc.quality_flag == "invalid":
        logger.warning(
            "quality.rejected",
            source_id=observation.source_id,
            reasons=qc.reasons,
        )
        _record_rejection(observation.source_id, "air_quality", qc.reasons)
        if hasattr(repository, "record_dlq"):
            repository.record_dlq(
                observation.source_id,
                observation.model_dump(mode="json"),
                ",".join(qc.reasons),
            )
        return {"status": "rejected", "reasons": qc.reasons}

    observation.grid_id = to_grid_id(observation.location.lat, observation.location.lon)
    observation.dedup_key = dedup_key(
        observation.source_id,
        observation.source_record_id,
        _iso(observation.observed_at),
        observation.measurement.parameter,
    )
    inserted = repository.upsert_air_quality(observation)
    _record_accepted(observation.source_id, "air_quality", inserted, qc.quality_score)
    return {"status": "persisted" if inserted else "duplicate", "grid_id": observation.grid_id}


def process_fire(
    observation: FireObservation,
    repository: ObservationRepository,
) -> dict[str, Any]:
    """Grid-map and persist a fire observation."""
    qc = evaluate_observation(
        parameter="frp",
        value=observation.fire.frp,
        lat=observation.location.lat,
        lon=observation.location.lon,
        observed_at=observation.observed_at,
        received_at=observation.received_at,
    )
    observation.quality.quality_flag = qc.quality_flag
    observation.quality.quality_score = qc.quality_score
    if qc.quality_flag == "invalid":
        _record_rejection(observation.source_id, "fire", qc.reasons)
        if hasattr(repository, "record_dlq"):
            repository.record_dlq(
                observation.source_id,
                observation.model_dump(mode="json"),
                ",".join(qc.reasons),
            )
        return {"status": "rejected", "reasons": qc.reasons}
    observation.grid_id = to_grid_id(observation.location.lat, observation.location.lon)
    observation.dedup_key = dedup_key(
        observation.source_id,
        observation.source_record_id,
        _iso(observation.observed_at),
        "frp",
    )
    inserted = repository.upsert_fire(observation)
    _record_accepted(observation.source_id, "fire", inserted, qc.quality_score)
    return {"status": "persisted" if inserted else "duplicate", "grid_id": observation.grid_id}


def process_weather(
    observation: MeteorologicalObservation,
    repository: ObservationRepository,
) -> dict[str, Any]:
    """Grid-map and persist a meteorological observation."""
    humidity = observation.humidity if observation.humidity is not None else 50.0
    qc = evaluate_observation(
        parameter="humidity" if observation.humidity is not None else "weather",
        value=humidity,
        lat=observation.location.lat,
        lon=observation.location.lon,
        observed_at=observation.observed_at,
        received_at=observation.received_at,
    )
    observation.quality.quality_flag = qc.quality_flag
    observation.quality.quality_score = qc.quality_score
    if qc.quality_flag == "invalid":
        _record_rejection(observation.source_id, "weather", qc.reasons)
        if hasattr(repository, "record_dlq"):
            repository.record_dlq(
                observation.source_id,
                observation.model_dump(mode="json"),
                ",".join(qc.reasons),
            )
        return {"status": "rejected", "reasons": qc.reasons}
    observation.grid_id = to_grid_id(observation.location.lat, observation.location.lon)
    observation.dedup_key = dedup_key(
        observation.source_id,
        observation.source_record_id,
        _iso(observation.observed_at),
        "weather",
    )
    inserted = repository.upsert_weather(observation)
    _record_accepted(observation.source_id, "weather", inserted, qc.quality_score)
    return {"status": "persisted" if inserted else "duplicate", "grid_id": observation.grid_id}


def run_detection(repository: InMemoryRepository) -> dict[str, Any]:
    """Materialize features and evaluate events from persisted observations."""
    snapshot = FeatureSnapshot(
        air_quality=list(repository.air_quality.values()),
        fires=list(repository.fires.values()),
        weather=list(repository.weather.values()),
        rasters=list(getattr(repository, "rasters", [])),
    )
    events = process_snapshot(snapshot, repository.event_store)
    FEATURES_MATERIALIZED.inc(len(repository.event_store.latest_features))
    for event in events:
        EVENTS_TRANSITIONED.labels(status=event.status.value, severity=event.severity.value).inc()
    return {
        "events": len(events),
        "open": len(repository.event_store.open_by_grid),
        "event_ids": [e.event_id for e in events],
    }


def _record_accepted(
    source_id: str, observation_type: str, inserted: bool, quality_score: float
) -> None:
    """Count an accepted observation and record its quality score.

    Args:
        source_id: Connector that supplied the record.
        observation_type: ``air_quality``, ``fire`` or ``weather``.
        inserted: False when the dedup key already existed.
        quality_score: Score the quality engine assigned.
    """
    INGESTED_OBSERVATIONS.labels(
        source_id=source_id,
        observation_type=observation_type,
        outcome="persisted" if inserted else "duplicate",
    ).inc()
    QUALITY_SCORE.labels(source_id=source_id).observe(quality_score)


def _record_rejection(source_id: str, observation_type: str, reasons: list[str]) -> None:
    """Count a quality rejection against each rule that failed.

    Rule names come from a fixed vocabulary in the quality engine, so the
    label stays bounded; the raw message is deliberately not used as a label.

    Args:
        source_id: Connector that supplied the record.
        observation_type: ``air_quality``, ``fire`` or ``weather``.
        reasons: Failing rule identifiers.
    """
    INGESTED_OBSERVATIONS.labels(
        source_id=source_id,
        observation_type=observation_type,
        outcome="rejected",
    ).inc()
    for reason in reasons or ["unspecified"]:
        QUALITY_REJECTIONS.labels(source_id=source_id, reason=reason).inc()


def _iso(value: datetime) -> str:
    return value.isoformat()
