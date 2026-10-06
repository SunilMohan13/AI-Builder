"""Run Phase 3 scoring over a feature snapshot."""

from __future__ import annotations

from datetime import UTC, datetime

import h3
from aeropulse_contracts.event import PollutionEvent
from aeropulse_contracts.raster import RasterObservation
from aeropulse_geospatial.grid import neighbors, to_grid_id
from aeropulse_observability.logging import get_logger

from aeropulse_intelligence.alerts import alert_from_event
from aeropulse_intelligence.anomaly import detect_anomaly
from aeropulse_intelligence.engine import EventStore, evaluate_cell
from aeropulse_intelligence.estimator import estimate_pm25
from aeropulse_intelligence.features import build_features
from aeropulse_intelligence.forecast import forecast_event
from aeropulse_intelligence.geometry import haversine_km
from aeropulse_intelligence.likelihood import score_sources
from aeropulse_intelligence.lineage import build_graph

# MODEL_DERIVED_SOURCES lives in the snapshot, where per-cell-hour fusion
# happens. Detect applies the same precedence when choosing a cell's
# representative timestamp, and re-exports it for callers.
from aeropulse_intelligence.snapshot import MODEL_DERIVED_SOURCES, FeatureSnapshot

logger = get_logger("aeropulse.intelligence")

NEARBY_STATION_KM = 25.0


def process_snapshot(
    snapshot: FeatureSnapshot,
    store: EventStore,
    *,
    history_by_grid: dict[str, list[float]] | None = None,
) -> list[PollutionEvent]:
    """Build features, score, and evaluate events for every cell with PM2.5.

    Args:
        snapshot: Current observations.
        store: Mutable event store.
        history_by_grid: Optional prior PM2.5 series per cell.

    Returns:
        Events created or updated in this pass.
    """
    history = history_by_grid or {}
    cells: dict[str, tuple[float, float]] = {}
    timestamps = {}
    # (is_ground_truth, observed_at) per cell, so the winner is deterministic
    # rather than whichever observation the iteration happened to reach last.
    ranking: dict[str, tuple[bool, object]] = {}
    for obs in snapshot.air_quality:
        if obs.measurement.parameter != "pm25":
            continue
        grid_id = obs.grid_id or to_grid_id(obs.location.lat, obs.location.lon)
        obs.grid_id = grid_id
        candidate = (obs.source_id not in MODEL_DERIVED_SOURCES, obs.observed_at)
        if grid_id in ranking and candidate <= ranking[grid_id]:
            continue
        ranking[grid_id] = candidate
        cells[grid_id] = (obs.location.lat, obs.location.lon)
        timestamps[grid_id] = obs.observed_at

    results: list[PollutionEvent] = []
    for grid_id, _ in cells.items():
        center_lat, center_lon = h3.cell_to_latlng(grid_id)
        ts = timestamps[grid_id]
        feature = build_features(
            grid_id,
            ts,
            snapshot,
            center_lat=center_lat,
            center_lon=center_lon,
        )
        prediction = estimate_pm25(
            grid_id,
            ts,
            center_lat,
            center_lon,
            snapshot.air_quality,
        )
        if prediction is not None:
            feature.pm25_estimate = prediction.pm25_estimate
            feature.estimate_confidence = prediction.confidence
        anomaly = detect_anomaly(
            grid_id,
            ts,
            feature.pm25,
            history.get(grid_id, []),
            quality_score=feature.quality_score,
        )
        feature.anomaly_score = anomaly.anomaly_score
        likelihood = score_sources(feature)
        feature.source_likelihood = likelihood
        # Every processed cell gets its feature/prediction persisted, independent
        # of whether it triggered an event (grid_feature/grid_prediction, LLD §13/§20).
        store.latest_features[grid_id] = feature
        if prediction is not None:
            store.latest_predictions[grid_id] = prediction
        extra = _has_nearby_station(center_lat, center_lon, snapshot, grid_id)
        event = evaluate_cell(
            feature,
            anomaly,
            likelihood,
            prediction,
            store,
            neighbors=neighbors(grid_id, 1),
            extra_station=extra,
        )
        if event is not None:
            store.features[event.event_id] = feature
            if feature.pm25 is not None:
                forecast = forecast_event(
                    event,
                    origin_grid_id=grid_id,
                    origin_lat=center_lat,
                    origin_lon=center_lon,
                    pm25=feature.pm25,
                    wind_u=feature.wind_u,
                    wind_v=feature.wind_v,
                    boundary_layer_height=feature.boundary_layer_height,
                    cams_pm25=_cams_pm25(snapshot, grid_id, ts),
                )
                store.forecasts[event.event_id] = forecast
                # Reuses the forecast module's own per-cell confidence (LLD §21.3),
                # previously computed and discarded.
                downwind = [p.confidence for p in forecast.grid_predictions[1:]]
                if downwind:
                    event.forecast_confidence = round(sum(downwind) / len(downwind), 4)
            if feature.estimate_confidence is not None:
                event.impact_confidence = feature.estimate_confidence
            store.graphs[event.event_id] = build_graph(
                event,
                store.evidence.get(event.event_id, []),
                origin_grid_id=grid_id,
            )
            alert = alert_from_event(event, store.evidence.get(event.event_id, []))
            if alert is not None:
                store.alerts[alert.alert_id] = alert
            logger.info(
                "event.transitioned",
                **{"event.id": event.event_id, "grid.id": grid_id, "status": event.status.value},
            )
            results.append(event)
    return results


def _has_nearby_station(lat: float, lon: float, snapshot: FeatureSnapshot, grid_id: str) -> bool:
    stations = {
        (o.location.lat, o.location.lon)
        for o in snapshot.air_quality
        if o.measurement.parameter == "pm25"
        and (o.grid_id or to_grid_id(o.location.lat, o.location.lon)) != grid_id
    }
    return any(haversine_km(lat, lon, slat, slon) <= NEARBY_STATION_KM for slat, slon in stations)


def _cams_pm25(snapshot: FeatureSnapshot, grid_id: str, timestamp: datetime) -> float | None:
    """Return CAMS PM2.5 for this cell-hour, never the last value in the snapshot."""
    hour = _floor_hour(timestamp)
    rasters: list[RasterObservation] = getattr(snapshot, "rasters", [])
    matches = [
        raster.sample_pm25
        for raster in rasters
        if raster.sample_pm25 is not None
        and raster.source_id in MODEL_DERIVED_SOURCES
        and _raster_grid(raster) == grid_id
        and _raster_hour(raster) == hour
    ]
    if not matches:
        return None
    return matches[-1]


def _raster_grid(raster: RasterObservation) -> str | None:
    if raster.grid_id:
        return raster.grid_id
    min_lon, min_lat, max_lon, max_lat = raster.bbox
    return to_grid_id((min_lat + max_lat) / 2.0, (min_lon + max_lon) / 2.0)


def _raster_hour(raster: RasterObservation) -> datetime:
    return _floor_hour(raster.acquisition_time)


def _floor_hour(timestamp: datetime) -> datetime:
    aware = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=UTC)
    return aware.replace(minute=0, second=0, microsecond=0)
