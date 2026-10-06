"""Forecast meteorology contract (meteo_forecast.v1).

Future hours from a weather model are not observations. Training and the plume
may use them only when ``issued_at`` is at or before the scoring time.
"""

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, model_validator

from aeropulse_contracts.observation import Location, Provenance


class MeteoForecast(BaseModel):
    """One issued forecast hour. Never a stand-in for a weather observation."""

    model_config = {"extra": "forbid"}

    forecast_id: str
    source_id: str
    source_record_id: str
    schema_version: Literal["meteo_forecast.v1"] = "meteo_forecast.v1"
    issued_at: datetime
    valid_at: datetime
    location: Location
    wind_u_10m: float | None = None
    wind_v_10m: float | None = None
    wind_u_100m: float | None = None
    wind_v_100m: float | None = None
    boundary_layer_height: float | None = None
    temperature: float | None = None
    humidity: float | None = None
    precipitation: float | None = None
    #: CAMS PM2.5 valid at this hour. A feature only, never a label.
    cams_pm25: float | None = None
    provenance: Provenance
    grid_id: str | None = None
    dedup_key: str | None = None

    @model_validator(mode="after")
    def issued_not_after_valid(self) -> Self:
        """A forecast cannot be issued after the hour it claims to describe."""
        if self.issued_at > self.valid_at:
            raise ValueError("issued_at must be <= valid_at")
        return self
