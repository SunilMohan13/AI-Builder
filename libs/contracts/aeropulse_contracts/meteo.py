"""Canonical meteorological observation contract (meteo.v1)."""

from typing import Literal

from aeropulse_contracts.observation import PointObservationBase


class MeteorologicalObservation(PointObservationBase):
    """Canonical weather observation (observed or analysis hours only).

    Forecast hours travel as :class:`aeropulse_contracts.meteo_forecast.MeteoForecast`
    so that a feature builder can enforce ``issued_at <= t``.
    """

    schema_version: Literal["meteo.v1"] = "meteo.v1"
    parameter: Literal["wind", "temperature", "humidity", "pressure", "blh", "weather"] = "weather"
    wind_u: float | None = None
    wind_v: float | None = None
    temperature: float | None = None
    humidity: float | None = None
    pressure: float | None = None
    rainfall: float | None = None
    boundary_layer_height: float | None = None
