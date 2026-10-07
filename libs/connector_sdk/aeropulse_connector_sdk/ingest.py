"""The one ingest path every plugin goes through.

configured? -> fetch -> archive raw -> normalize (per record) -> keep inside
the domain -> stamp region, H3 cell, provenance class, dedup key -> dedup.

Quality control is not here: it is a preprocessing step, shared with
training and replay, so ingest and evaluation can never disagree on it.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from aeropulse_common.hashing import dedup_key
from aeropulse_contracts import (
    CanonicalRecord,
    FireObservation,
    MeteoForecast,
    MeteorologicalObservation,
    Observation,
    ProvenanceClass,
    RasterObservation,
    SourceHealth,
    SourceState,
)
from aeropulse_geospatial import to_grid_id
from aeropulse_observability.logging import get_logger

from aeropulse_connector_sdk.plugin import ConnectorContext, ConnectorPlugin, ConnectorResult

logger = get_logger("aeropulse.ingest")

#: ``archive(key, body) -> uri``. Must raise on failure; never soft-fail.
RawArchiver = Callable[[str, bytes], str]


@dataclass
class Rejection:
    source_record_id: str
    reason: str


@dataclass
class IngestOutcome:
    source_id: str
    region_id: str
    records: list[CanonicalRecord] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)
    health: SourceHealth | None = None
    raw_uri: str | None = None


def _observed_at(record: CanonicalRecord) -> datetime:
    if isinstance(record, RasterObservation):
        return record.acquisition_time
    if isinstance(record, MeteoForecast):
        return record.valid_at
    return record.observed_at


def _parameter(record: CanonicalRecord) -> str:
    if isinstance(record, Observation):
        return record.measurement.parameter
    if isinstance(record, FireObservation):
        return "frp"
    if isinstance(record, MeteorologicalObservation):
        return record.parameter
    if isinstance(record, MeteoForecast):
        return f"forecast@{record.issued_at.isoformat()}"
    return record.product_id


def _inside(bbox: tuple[float, float, float, float], lat: float, lon: float) -> bool:
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


def _stamp(
    record: CanonicalRecord,
    context: ConnectorContext,
    provenance_class: ProvenanceClass,
) -> CanonicalRecord | None:
    provenance = record.provenance.model_copy(update={"provenance_class": provenance_class})
    if isinstance(record, RasterObservation):
        return record.model_copy(update={"region_id": context.region_id, "provenance": provenance})
    lat, lon = record.location.lat, record.location.lon
    if not _inside(context.bbox, lat, lon):
        return None
    record_id = record.site_id if isinstance(record, MeteoForecast) else record.source_record_id
    key = dedup_key(
        record.source_id, record_id, _observed_at(record).isoformat(), _parameter(record)
    )
    return record.model_copy(
        update={
            "region_id": context.region_id,
            "grid_id": to_grid_id(lat, lon),
            "provenance": provenance,
            "dedup_key": key,
        }
    )


def _identity(record: CanonicalRecord) -> str:
    if isinstance(record, RasterObservation):
        return f"raster|{record.source_id}|{record.source_record_id}"
    return record.dedup_key or ""


class IngestPipeline:
    """Run one plugin for one region.

    Args:
        archiver: Raw payload archive. ``None`` skips archiving (tests).

    ``run(..., provenance_override=...)`` takes the region-level class:
    ``measured`` for the pack's ground-truth sources, ``model_derived`` for
    model-derived ones.
    """

    def __init__(self, archiver: RawArchiver | None = None) -> None:
        self.archiver = archiver

    def run(
        self,
        plugin: ConnectorPlugin,
        context: ConnectorContext,
        *,
        provenance_override: ProvenanceClass | None = None,
    ) -> IngestOutcome:
        outcome = IngestOutcome(source_id=plugin.source_id, region_id=context.region_id)
        issue = plugin.configuration_issue(context)
        if issue is not None:
            outcome.health = self._health(context, plugin, SourceState.NOT_CONFIGURED, issue)
            return outcome

        started = time.perf_counter()
        try:
            result = plugin.fetch(context)
        except Exception as exc:
            # Source isolation: one provider failing must not stop the cycle.
            # The type name is recorded, never the message, which can carry a
            # credential-bearing URL.
            logger.warning(
                "ingest.fetch_failed",
                source_id=plugin.source_id,
                region_id=context.region_id,
                error=type(exc).__name__,
            )
            outcome.health = self._health(
                context, plugin, SourceState.UNAVAILABLE, f"fetch failed: {type(exc).__name__}"
            )
            return outcome
        if result.state not in (SourceState.HEALTHY, SourceState.REPLAY):
            outcome.health = self._health(context, plugin, result.state, result.reason)
            return outcome
        if context.mode == "replay":
            # A replayed cycle fetches at its own cycle time. The wall clock
            # would date every record after ``as_of`` and the cut-off would
            # drop it.
            result.records = [
                r.model_copy(update={"fetched_at": context.now}) for r in result.records
            ]
            result.fetched_at = context.now

        if self.archiver is not None and result.records:
            outcome.raw_uri = self._archive(result, context)
            for raw in result.records:
                raw.raw_uri = outcome.raw_uri

        provenance_class = provenance_override or plugin.provenance_class
        seen: set[str] = set()
        for raw in result.records:
            single = ConnectorResult(
                source_id=result.source_id, records=[raw], fetched_at=result.fetched_at
            )
            try:
                normalized = plugin.normalize(single, context)
            except (ValueError, KeyError, TypeError) as exc:
                outcome.rejected.append(Rejection(raw.source_record_id, type(exc).__name__))
                continue
            for record in normalized:
                stamped = _stamp(record, context, provenance_class)
                if stamped is None:
                    outcome.rejected.append(Rejection(raw.source_record_id, "outside_domain"))
                    continue
                identity = _identity(stamped)
                if identity in seen:
                    continue
                seen.add(identity)
                outcome.records.append(stamped)

        latency_ms = (time.perf_counter() - started) * 1000.0
        watermark = max((_observed_at(r) for r in outcome.records), default=None)
        state = SourceState.HEALTHY if context.is_network else SourceState.REPLAY
        reason = None
        if not outcome.records and outcome.rejected:
            state, reason = SourceState.DEGRADED, "every record was rejected"
        outcome.health = SourceHealth(
            source_id=plugin.source_id,
            region_id=context.region_id,
            state=state,
            reason=reason,
            records=len(outcome.records),
            rejected=len(outcome.rejected),
            last_success_at=result.fetched_at if outcome.records else None,
            watermark=watermark,
            latency_ms=round(latency_ms, 3),
        )
        return outcome

    def _archive(self, result: ConnectorResult, context: ConnectorContext) -> str:
        assert self.archiver is not None
        key = (
            f"raw/{context.region_id}/{result.source_id}/"
            f"{result.fetched_at:%Y/%m/%d}/{context.run_id}.json"
        )
        body = json.dumps(
            [
                {"source_record_id": r.source_record_id, "payload": r.payload}
                for r in result.records
            ],
            default=str,
        ).encode("utf-8")
        return self.archiver(key, body)

    @staticmethod
    def _health(
        context: ConnectorContext,
        plugin: ConnectorPlugin,
        state: SourceState,
        reason: str | None,
    ) -> SourceHealth:
        return SourceHealth(
            source_id=plugin.source_id, region_id=context.region_id, state=state, reason=reason
        )
