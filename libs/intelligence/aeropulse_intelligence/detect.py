"""Run Phase 3 scoring over a feature snapshot."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

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
    model_derived_sources: Iterable[str] = MODEL_DERIVED_SOURCES,
) -> list[PollutionEvent]:
    """Build features, score, and evaluate events for every cell with PM2.5.

    Args:
        snapshot: Current observations.
        store: Mutable event store.
        history_by_grid: Prior PM2.5 series per cell, oldest first. Without it
            the anomaly score has no baseline to compare against.
        model_derived_sources: Sources that are model output (CAMS and
            similar); they never enter the station interpolation.

    Returns:
        Events created or updated in this pass.
    """
    history = history_by_grid or {}
    model_derived = frozenset(model_derived_sources)
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
        candidate = (obs.source_id not in model_derived, obs.observed_at)
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
            model_derived_sources=model_derived,
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
                    cams_pm25=_cams_pm25(snapshot, grid_id, ts, model_derived),
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
            alert = alert_from_event(
                event,
                store.evidence.get(event.event_id, []),
                now=store.clock(),
                alert_id=store.ids("al", event.event_id),
            )
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


def _cams_pm25(
    snapshot: FeatureSnapshot,
    grid_id: str,
    ts: datetime,
    model_derived: frozenset[str],
) -> float | None:
    """Model PM2.5 for this cell and hour, or None; never "the last value anywhere".

    A raster reduced to this cell wins, then one whose footprint covers the
    cell centre, then a model-derived point value in the same cell-hour.
    """
    lat, lon = h3.cell_to_latlng(grid_id)
    rasters: list[RasterObservation] = [
        r for r in snapshot.rasters_at(ts) if r.sample_pm25 is not None
    ]
    for raster in rasters:
        if raster.grid_id == grid_id:
            return raster.sample_pm25
    for raster in rasters:
        west, south, east, north = raster.bbox
        if raster.grid_id is None and west <= lon <= east and south <= lat <= north:
            return raster.sample_pm25
    modelled = [
        o
        for o in snapshot.air_quality_at(grid_id, ts)
        if o.measurement.parameter == "pm25" and o.source_id in model_derived
    ]
    if not modelled:
        return None
    return max(modelled, key=lambda o: o.observed_at).measurement.value
