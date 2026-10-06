"""Baseline inverse-distance PM2.5 estimator (baseline-idw-0.1).

AOD is never treated as surface PM2.5 (LLD §18.1, §65).
"""

from __future__ import annotations

from datetime import UTC, datetime

from aeropulse_contracts.observation import Observation
from aeropulse_contracts.prediction import GridPrediction

from aeropulse_intelligence.geometry import haversine_km
from aeropulse_intelligence.snapshot import MODEL_DERIVED_SOURCES

ESTIMATOR_VERSION = "baseline-idw-0.1"
POWER = 2.0
MAX_DISTANCE_KM = 80.0


def estimate_pm25(
    grid_id: str,
    timestamp: datetime,
    center_lat: float,
    center_lon: float,
    stations: list[Observation],
) -> GridPrediction | None:
    """IDW interpolate CPCB PM2.5 onto a cell center.

    Args:
        grid_id: Target H3 cell.
        timestamp: Estimate time.
        center_lat: Cell latitude.
        center_lon: Cell longitude.
        stations: PM2.5 observations (any grid).

    Returns:
        Prediction with interval widened by distance, or None if no stations.
    """
    samples: list[tuple[float, float, float]] = []
    hour = _hour(timestamp)
    for obs in stations:
        if obs.measurement.parameter != "pm25":
            continue
        if obs.source_id in MODEL_DERIVED_SOURCES:
            continue
        if _hour(obs.observed_at) != hour:
            continue
        dist = max(haversine_km(center_lat, center_lon, obs.location.lat, obs.location.lon), 0.1)
        if dist > MAX_DISTANCE_KM:
            continue
        samples.append((obs.measurement.value, dist, obs.quality.quality_score))
    if not samples:
        return None

    weights = [(value, (1.0 / (dist**POWER)) * quality) for value, dist, quality in samples]
    weight_sum = sum(w for _, w in weights)
    if weight_sum <= 0:
        return None
    estimate = sum(value * w for value, w in weights) / weight_sum
    min_dist = min(dist for _, dist, _ in samples)
    mean_q = sum(q for _, _, q in samples) / len(samples)
    confidence = max(0.15, min(0.95, mean_q * (1.0 - min(min_dist / MAX_DISTANCE_KM, 0.85))))
    half_width = max(8.0, estimate * (0.08 + (1.0 - confidence) * 0.4))
    return GridPrediction(
        grid_id=grid_id,
        timestamp=timestamp,
        model_version=ESTIMATOR_VERSION,
        pm25_estimate=round(estimate, 2),
        prediction_interval_low=round(max(0.0, estimate - half_width), 2),
        prediction_interval_high=round(estimate + half_width, 2),
        confidence=round(confidence, 4),
    )


def _hour(ts: datetime) -> datetime:
    """Floor a timestamp to the UTC hour."""
    aware = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    return aware.replace(minute=0, second=0, microsecond=0)
