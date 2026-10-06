"""Canonical meteorological observation contract (meteo.v1)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from aeropulse_contracts.observation import Location, Provenance, Quality


class MeteorologicalObservation(BaseModel):
    """Canonical weather observation used by fusion and forecast later."""

    model_config = {"extra": "forbid"}

    observation_id: str
    source_id: str
    source_record_id: str
    schema_version: Literal["meteo.v1"] = "meteo.v1"
    observed_at: datetime
    received_at: datetime
    location: Location
    parameter: Literal["wind", "temperature", "humidity", "pressure", "blh", "weather"] = "weather"
    wind_u: float | None = None
    wind_v: float | None = None
    temperature: float | None = None
    humidity: float | None = None
    pressure: float | None = None
    rainfall: float | None = None
    boundary_layer_height: float | None = None
    quality: Quality
    provenance: Provenance
    grid_id: str | None = None
    dedup_key: str | None = None
