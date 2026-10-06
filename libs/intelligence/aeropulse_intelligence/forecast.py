"""Kinematic wind-advection forecast (wind-advection-0.1).

CAMS residual correction is not applied. Label ``cams_applied=False``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import h3
from aeropulse_contracts.event import PollutionEvent
from aeropulse_contracts.forecast import FORECAST_VERSION, ForecastResult, GridCellForecast
from aeropulse_observability.logging import get_logger

from aeropulse_intelligence.geometry import cosine_alignment, wind_direction_to, wind_speed

logger = get_logger("aeropulse.forecast")

HORIZONS_H = (3, 6, 12, 24, 48)
CELL_KM = 0.93
FORECAST_MODEL = FORECAST_VERSION


def forecast_event(
    event: PollutionEvent,
    *,
    origin_grid_id: str,
    origin_lat: float,
    origin_lon: float,
    pm25: float,
    wind_u: float | None,
    wind_v: float | None,
    boundary_layer_height: float | None = None,
    cams_pm25: float | None = None,
) -> ForecastResult:
    """Advect origin PM2.5 along the wind vector onto neighboring H3 cells.

    Args:
        event: Event being forecast.
        origin_grid_id: Source H3 cell.
        origin_lat: Cell latitude.
        origin_lon: Cell longitude.
        pm25: Current PM2.5 at origin.
        wind_u: Eastward wind (m/s).
        wind_v: Northward wind (m/s).
        boundary_layer_height: Optional BLH (m); deeper mixing dilutes more.
        cams_pm25: Optional CAMS background PM2.5; blended at 20% when present.

    Returns:
        ``forecast.v1`` with one prediction per horizon (downwind cell).
    """
    now = datetime.now(UTC)
    u = wind_u if wind_u is not None else 0.0
    v = wind_v if wind_v is not None else 0.0
    speed = wind_speed(u, v)
    toward = wind_direction_to(u, v) if speed > 0.05 else None
    predictions: list[GridCellForecast] = [
        GridCellForecast(
            grid_id=origin_grid_id,
            pm25=round(pm25, 2),
            confidence=0.9,
            center_lat=origin_lat,
            center_lon=origin_lon,
        )
    ]
    for hours in HORIZONS_H:
        cell = _advect_cell(origin_grid_id, toward, speed, hours)
        lat, lon = h3.cell_to_latlng(cell)
        dilution = 1.0 / (1.0 + 0.08 * hours)
        if boundary_layer_height and boundary_layer_height > 800:
            dilution *= 0.85
        confidence = max(0.2, 0.88 - 0.012 * hours)
        if toward is None:
            confidence *= 0.5
        advected = pm25 * dilution
        if cams_pm25 is not None:
            advected = 0.8 * advected + 0.2 * cams_pm25
            confidence = min(1.0, confidence + 0.05)
        predictions.append(
            GridCellForecast(
                grid_id=cell,
                pm25=round(advected, 2),
                confidence=round(confidence, 4),
                center_lat=lat,
                center_lon=lon,
            )
        )
        logger.info(
            "forecast.horizon",
            event_id=event.event_id,
            horizon_hours=hours,
            grid_id=cell,
        )
    return ForecastResult(
        event_id=event.event_id,
        origin_grid_id=origin_grid_id,
        generated_at=now,
        cams_applied=cams_pm25 is not None,
        model_version=FORECAST_MODEL,
        horizons=list(HORIZONS_H),
        grid_predictions=predictions,
    )


def _advect_cell(origin: str, toward_deg: float | None, speed_ms: float, hours: int) -> str:
    if toward_deg is None or speed_ms < 0.05:
        return origin
    km = speed_ms * 3.6 * hours
    steps = max(1, min(int(km / CELL_KM), 40))
    current = origin
    for _ in range(steps):
        nxt = _best_neighbor(current, toward_deg)
        if nxt == current:
            break
        current = nxt
    return current


def _best_neighbor(grid_id: str, toward_deg: float) -> str:
    origin = h3.cell_to_latlng(grid_id)
    best = grid_id
    best_score = -1.0
    for cell in h3.grid_disk(grid_id, 1):
        if cell == grid_id:
            continue
        lat, lon = h3.cell_to_latlng(cell)
        bearing = _bearing(origin[0], origin[1], lat, lon)
        score = cosine_alignment(toward_deg, bearing)
        if score > best_score:
            best_score = score
            best = cell
    return best


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from aeropulse_intelligence.geometry import bearing_deg

    return bearing_deg(lat1, lon1, lat2, lon2)
