"""Forecast weather contract (meteo_forecast.v1).

A forecast hour is never an observation. It carries the model run time
(``issued_at``) so the feature builder can enforce ``issued_at <= t``: a row
scored at time ``t`` may only see forecasts that already existed at ``t``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from aeropulse_contracts.observation import Location, Provenance, Quality


class MeteoForecast(BaseModel):
    """One forecast valid hour at one site from one model run."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["meteo_forecast.v1"] = "meteo_forecast.v1"
    forecast_id: str
    source_id: str
    region_id: str | None = None
    site_id: str
    issued_at: datetime
    valid_at: datetime
    location: Location
    grid_id: str | None = None
    wind_u_10m: float | None = None
    wind_v_10m: float | None = None
    wind_u_100m: float | None = None
    wind_v_100m: float | None = None
    temperature: float | None = None
    humidity: float | None = None
    precipitation: float | None = None
    boundary_layer_height: float | None = None
    cloud_cover: float | None = Field(default=None, ge=0.0, le=100.0)
    #: CAMS PM2.5 forecast for the same valid hour (ug/m3). Model output: a
    #: feature and a baseline, never a label.
    cams_pm25: float | None = None
    quality: Quality
    provenance: Provenance
    dedup_key: str | None = None

    @property
    def lead_hours(self) -> float:
        """Hours between the model run and the valid hour."""
        return (self.valid_at - self.issued_at).total_seconds() / 3600.0

    @model_validator(mode="after")
    def _valid_not_before_issue(self) -> MeteoForecast:
        if self.valid_at < self.issued_at:
            raise ValueError("valid_at must not precede issued_at")
        return self
