"""Canonical forecast contract (forecast.v1, LLD section 22.3)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

FORECAST_VERSION = "wind-advection-0.1"


class GridCellForecast(BaseModel):
    """Predicted PM2.5 for one H3 cell at one horizon.

    ``pm25`` is the point forecast. ``p90`` exists because a squared-error
    point forecast is the wrong quantity to alert on: minimising aggregate
    loss means predicting "no episode", which is why the research pipeline
    measured exceedance recall collapsing from 0.434 at 1 h to 0.020 at 6 h
    while aggregate MAE still improved. Alerting on the upper quantile
    recovered recall to 0.209 at 6 h for a 0.7% false-alarm cost. Both are
    carried so a consumer can alert on ``p90`` and display ``pm25``, rather
    than having to pick one and be wrong for the other purpose.
    """

    model_config = {"extra": "forbid"}

    grid_id: str
    pm25: float
    confidence: float = Field(..., ge=0.0, le=1.0)
    center_lat: float | None = None
    center_lon: float | None = None
    #: Upper-decile forecast, for alert thresholding. None when the serving
    #: model produces only a point estimate, which is the deterministic case.
    p90: float | None = None
    #: Lower-decile forecast, carried with p90 so the interval is symmetric
    #: in availability rather than implying a one-sided uncertainty.
    p10: float | None = None


class ForecastResult(BaseModel):
    """Event-scoped advection forecast. CAMS is not applied in this version."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["forecast.v1"] = "forecast.v1"
    model_version: str = FORECAST_VERSION
    event_id: str | None = None
    origin_grid_id: str
    generated_at: datetime
    cams_applied: bool = False
    horizons: list[int] = Field(default_factory=lambda: [3, 6, 12, 24, 48])
    grid_predictions: list[GridCellForecast] = Field(default_factory=list)
    horizon_hours: int | None = None
