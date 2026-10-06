"""Stateful pollution event engine (LLD §21)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from aeropulse_common.ids import new_ulid
from aeropulse_contracts.alert import Alert
from aeropulse_contracts.citizen import CitizenReport
from aeropulse_contracts.event import (
    EventEvidence,
    EventSeverity,
    EventStatus,
    PollutionEvent,
)
from aeropulse_contracts.feature import FEATURE_VERSION, GridFeature, SourceLikelihood
from aeropulse_contracts.forecast import ForecastResult
from aeropulse_contracts.lineage import EvidenceGraph
from aeropulse_contracts.prediction import AnomalyResult, GridPrediction

from aeropulse_intelligence.anomaly import ANOMALY_VERSION
from aeropulse_intelligence.estimator import ESTIMATOR_VERSION
from aeropulse_intelligence.likelihood import LIKELIHOOD_VERSION

MIN_EVIDENCE = 2
MIN_QUALITY = 0.5
MODEL_VERSIONS = [ESTIMATOR_VERSION, ANOMALY_VERSION, LIKELIHOOD_VERSION]


@dataclass
class EventStore:
    """In-memory event store with clustering by H3 cell (tests + worker)."""

    events: dict[str, PollutionEvent] = field(default_factory=dict)
    evidence: dict[str, list[EventEvidence]] = field(default_factory=dict)
    open_by_grid: dict[str, str] = field(default_factory=dict)
    forecasts: dict[str, ForecastResult] = field(default_factory=dict)
    graphs: dict[str, EvidenceGraph] = field(default_factory=dict)
    features: dict[str, GridFeature] = field(default_factory=dict)
    alerts: dict[str, Alert] = field(default_factory=dict)
    citizen_reports: dict[str, CitizenReport] = field(default_factory=dict)
    #: Latest materialized feature/prediction per cell, for every cell processed
    #: this pass — regardless of whether it triggered an event (LLD §13/§20:
    #: `grid_feature`/`grid_prediction` must be persisted independent of events).
    latest_features: dict[str, GridFeature] = field(default_factory=dict)
    latest_predictions: dict[str, GridPrediction] = field(default_factory=dict)


def evaluate_cell(
    feature: GridFeature,
    anomaly: AnomalyResult,
    likelihood: SourceLikelihood,
    prediction: GridPrediction | None,
    store: EventStore,
    *,
    neighbors: list[str] | None = None,
    extra_station: bool = False,
) -> PollutionEvent | None:
    """Create or update a pollution event for one grid cell.

    Creation rule (LLD §21.2): anomaly trigger AND evidence_count >= 2
    AND quality_score >= minimum.

    Args:
        feature: Materialized grid-hour features.
        anomaly: Anomaly detector output.
        likelihood: Independent source scores.
        prediction: Optional PM2.5 estimate.
        store: Event store (mutated).
        neighbors: H3 k-ring cells used to merge clusters.
        extra_station: True when a second CPCB station corroborates.

    Returns:
        The affected event, or None if no event was warranted.
    """
    quality = feature.quality_score if feature.quality_score is not None else 0.0
    evidence = _collect_evidence(feature, anomaly, extra_station)
    now = datetime.now(UTC)

    existing = _find_open(store, feature.grid_id, neighbors or [])
    if existing and existing.status not in {EventStatus.RESOLVED, EventStatus.REJECTED}:
        return _update_existing(existing, feature, anomaly, likelihood, evidence, store, now)

    if not anomaly.event_trigger or quality < MIN_QUALITY or len(evidence) < MIN_EVIDENCE:
        if anomaly.event_trigger and len(evidence) < MIN_EVIDENCE:
            return _reject(feature, anomaly, likelihood, evidence, store, now)
        return None

    status = EventStatus.DETECTED
    if len(evidence) >= 3 and anomaly.anomaly_score >= 0.7:
        status = EventStatus.ACTIVE
    elif len(evidence) >= 3:
        status = EventStatus.CONFIRMED

    conf = _confidence(anomaly, likelihood, evidence, feature)
    event = PollutionEvent(
        event_id=new_ulid("evt"),
        status=status,
        severity=_severity(feature.pm25, anomaly.anomaly_score),
        created_at=now,
        updated_at=now,
        grid_ids=[feature.grid_id],
        pollutants=["PM2.5"],
        detection_confidence=conf["detection"],
        source_confidence=conf["source"],
        forecast_confidence=0.0,
        impact_confidence=0.0,
        overall_confidence=conf["overall"],
        evidence_ids=[e.evidence_id for e in evidence],
        model_versions=list(MODEL_VERSIONS),
        feature_version=FEATURE_VERSION,
        evidence_freshness=conf["freshness"],
        sensor_coverage=conf["coverage"],
        geometry=f"POINT({feature.center_lon} {feature.center_lat})",
    )
    if prediction:
        event.model_versions = [*event.model_versions]
    store.events[event.event_id] = event
    store.evidence[event.event_id] = evidence
    store.open_by_grid[feature.grid_id] = event.event_id
    return event


def _update_existing(
    event: PollutionEvent,
    feature: GridFeature,
    anomaly: AnomalyResult,
    likelihood: SourceLikelihood,
    evidence: list[EventEvidence],
    store: EventStore,
    now: datetime,
) -> PollutionEvent:
    if feature.grid_id not in event.grid_ids:
        event.grid_ids = [*event.grid_ids, feature.grid_id]
    merged = {e.evidence_id: e for e in store.evidence.get(event.event_id, [])}
    for item in evidence:
        merged[item.evidence_id] = item
    store.evidence[event.event_id] = list(merged.values())
    event.evidence_ids = [e.evidence_id for e in store.evidence[event.event_id]]

    lag = feature.pm25_lag_1h
    if (
        lag is not None
        and feature.pm25 is not None
        and feature.pm25 < lag * 0.85
        and event.status in {EventStatus.ACTIVE, EventStatus.CONFIRMED, EventStatus.DETECTED}
    ):
        event.status = EventStatus.DECLINING
    if feature.pm25 is not None and feature.pm25 < 60 and event.status == EventStatus.DECLINING:
        event.status = EventStatus.RESOLVED
    elif (
        event.status == EventStatus.DETECTED
        and len(event.evidence_ids) >= 3
        and anomaly.anomaly_score >= 0.7
    ):
        event.status = EventStatus.ACTIVE

    conf = _confidence(anomaly, likelihood, store.evidence[event.event_id], feature)
    event.detection_confidence = conf["detection"]
    event.source_confidence = conf["source"]
    event.overall_confidence = conf["overall"]
    event.evidence_freshness = conf["freshness"]
    event.sensor_coverage = conf["coverage"]
    event.severity = _severity(feature.pm25, anomaly.anomaly_score)
    event.updated_at = now
    store.open_by_grid[feature.grid_id] = event.event_id
    if event.status in {EventStatus.RESOLVED, EventStatus.REJECTED}:
        store.open_by_grid.pop(feature.grid_id, None)
    return event


def _reject(
    feature: GridFeature,
    anomaly: AnomalyResult,
    likelihood: SourceLikelihood,
    evidence: list[EventEvidence],
    store: EventStore,
    now: datetime,
) -> PollutionEvent:
    conf = _confidence(anomaly, likelihood, evidence, feature)
    event = PollutionEvent(
        event_id=new_ulid("evt"),
        status=EventStatus.REJECTED,
        severity=EventSeverity.LOW,
        created_at=now,
        updated_at=now,
        grid_ids=[feature.grid_id],
        detection_confidence=conf["detection"],
        source_confidence=conf["source"],
        forecast_confidence=0.0,
        impact_confidence=0.0,
        overall_confidence=conf["overall"],
        evidence_ids=[e.evidence_id for e in evidence],
        model_versions=list(MODEL_VERSIONS),
        feature_version=FEATURE_VERSION,
        evidence_freshness=conf["freshness"],
        sensor_coverage=conf["coverage"],
    )
    store.events[event.event_id] = event
    store.evidence[event.event_id] = evidence
    return event


def _find_open(store: EventStore, grid_id: str, neighbors: list[str]) -> PollutionEvent | None:
    for cell in [grid_id, *neighbors]:
        event_id = store.open_by_grid.get(cell)
        if event_id and event_id in store.events:
            event = store.events[event_id]
            if event.status not in {EventStatus.RESOLVED, EventStatus.REJECTED}:
                return event
    return None


def _collect_evidence(
    feature: GridFeature,
    anomaly: AnomalyResult,
    extra_station: bool,
) -> list[EventEvidence]:
    items: list[EventEvidence] = []
    if anomaly.event_trigger:
        items.append(
            EventEvidence(
                evidence_id=new_ulid("evd"),
                evidence_type="cpcb_anomaly",
                grid_id=feature.grid_id,
                summary=f"PM2.5 {feature.pm25} ug/m3 anomaly_score={anomaly.anomaly_score}",
                quality_score=feature.quality_score,
            )
        )
    if extra_station:
        items.append(
            EventEvidence(
                evidence_id=new_ulid("evd"),
                evidence_type="nearby_station",
                grid_id=feature.grid_id,
                summary="Second CPCB station corroborates elevated PM2.5",
                quality_score=feature.quality_score,
            )
        )
    if feature.fire_count > 0:
        items.append(
            EventEvidence(
                evidence_id=new_ulid("evd"),
                evidence_type="fire_detection",
                grid_id=feature.grid_id,
                summary=f"{feature.fire_count} fires FRP={feature.fire_frp:.1f} MW",
                quality_score=feature.fire_confidence,
            )
        )
    if feature.upwind_fire_score >= 0.4 and feature.wind_speed is not None:
        items.append(
            EventEvidence(
                evidence_id=new_ulid("evd"),
                evidence_type="wind_consistency",
                grid_id=feature.grid_id,
                summary=f"Upwind fire alignment {feature.upwind_fire_score}",
                quality_score=feature.quality_score,
            )
        )
    return items


def _confidence(
    anomaly: AnomalyResult,
    likelihood: SourceLikelihood,
    evidence: list[EventEvidence],
    feature: GridFeature,
) -> dict[str, float]:
    detection = anomaly.anomaly_score
    source = max(likelihood.biomass_burning, likelihood.regional_transport)
    freshness = 1.0
    if feature.data_freshness_seconds is not None:
        freshness = max(0.2, 1.0 - feature.data_freshness_seconds / 86400.0)
    coverage = min(1.0, feature.source_count / 3.0)
    overall = round(0.45 * detection + 0.25 * source + 0.15 * freshness + 0.15 * coverage, 4)
    return {
        "detection": round(detection, 4),
        "source": round(source, 4),
        "freshness": round(freshness, 4),
        "coverage": round(coverage, 4),
        "overall": overall,
    }


def _severity(pm25: float | None, anomaly_score: float) -> EventSeverity:
    value = pm25 if pm25 is not None else anomaly_score * 250
    if value >= 250:
        return EventSeverity.CRITICAL
    if value >= 150:
        return EventSeverity.HIGH
    if value >= 100:
        return EventSeverity.MEDIUM
    return EventSeverity.LOW
