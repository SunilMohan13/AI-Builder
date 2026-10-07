"""Canonical records -> the hourly tables the feature pipeline reads.

All times are UTC ``pandas.Timestamp``s. Hour buckets are hour-ending
(``(tau - 1h, tau]``, see :func:`hour_ending`), so a bucket is knowable at
its own ``tau``.
"""

from __future__ import annotations

from dataclasses import dataclass

import h3
import pandas as pd
from aeropulse_geospatial import to_grid_id

from aeropulse_ml.preprocessing import PreprocessContext, RecordBatch, hour_ending
from aeropulse_ml.preprocessing.steps import label_observations

S5P_PRODUCT = "s5p_aer_ai"


def site_key(lat: float, lon: float) -> str:
    return f"{lat:.4f},{lon:.4f}"


def _frame(rows: list[dict[str, object]], columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=columns)


def utc_ns(series: pd.Series) -> pd.Series:
    """UTC, nanosecond timestamps: merge keys must share one dtype."""
    return pd.to_datetime(series, utc=True).astype("datetime64[ns, UTC]")


@dataclass(frozen=True)
class FeatureTables:
    stations: pd.DataFrame  # cell, tau, value
    cams: pd.DataFrame  # site, lat, lon, tau, value
    weather: pd.DataFrame  # site, lat, lon, tau, wind_u, wind_v, blh, temperature, ...
    forecasts: pd.DataFrame  # site, lat, lon, issued_at, valid_at, <vars>
    fires: pd.DataFrame  # lat, lon, observed_at, frp
    rasters: pd.DataFrame  # cell, resolution, processing_time, aerosol_index, valid_fraction


WEATHER_COLUMNS = [
    "wind_u",
    "wind_v",
    "boundary_layer_height",
    "temperature",
    "humidity",
    "precipitation",
]
FORECAST_COLUMNS = [
    "wind_u_10m",
    "wind_v_10m",
    "wind_u_100m",
    "wind_v_100m",
    "boundary_layer_height",
    "temperature",
    "humidity",
    "precipitation",
    "cams_pm25",
]


def build_tables(batch: RecordBatch, context: PreprocessContext) -> FeatureTables:
    stations = _frame(
        [
            {
                "cell": o.grid_id or to_grid_id(o.location.lat, o.location.lon),
                "tau": hour_ending(o.observed_at),
                "value": o.measurement.value,
            }
            for o in label_observations(batch, context, parameter="pm25")
        ],
        ["cell", "tau", "value"],
    )
    stations["tau"] = utc_ns(stations["tau"])
    stations = stations.groupby(["cell", "tau"], as_index=False)["value"].mean()

    cams = _frame(
        [
            {
                "site": site_key(o.location.lat, o.location.lon),
                "lat": o.location.lat,
                "lon": o.location.lon,
                "tau": hour_ending(o.observed_at),
                "value": o.measurement.value,
            }
            for o in batch.observations
            if o.measurement.parameter == "pm25" and context.is_model_derived(o)
        ],
        ["site", "lat", "lon", "tau", "value"],
    )
    cams["tau"] = utc_ns(cams["tau"])
    cams = cams.groupby(["site", "lat", "lon", "tau"], as_index=False)["value"].mean()

    weather = _frame(
        [
            {
                "site": site_key(w.location.lat, w.location.lon),
                "lat": w.location.lat,
                "lon": w.location.lon,
                "tau": hour_ending(w.observed_at),
                "wind_u": w.wind_u,
                "wind_v": w.wind_v,
                "boundary_layer_height": w.boundary_layer_height,
                "temperature": w.temperature,
                "humidity": w.humidity,
                "precipitation": w.rainfall,
            }
            for w in batch.weather
        ],
        ["site", "lat", "lon", "tau", *WEATHER_COLUMNS],
    )
    weather["tau"] = utc_ns(weather["tau"])
    weather[WEATHER_COLUMNS] = weather[WEATHER_COLUMNS].astype(float)
    weather = weather.groupby(["site", "lat", "lon", "tau"], as_index=False)[WEATHER_COLUMNS].mean()

    forecasts = _frame(
        [
            {
                "site": site_key(f.location.lat, f.location.lon),
                "lat": f.location.lat,
                "lon": f.location.lon,
                "issued_at": f.issued_at,
                "valid_at": f.valid_at,
                "wind_u_10m": f.wind_u_10m,
                "wind_v_10m": f.wind_v_10m,
                "wind_u_100m": f.wind_u_100m,
                "wind_v_100m": f.wind_v_100m,
                "boundary_layer_height": f.boundary_layer_height,
                "temperature": f.temperature,
                "humidity": f.humidity,
                "precipitation": f.precipitation,
                "cams_pm25": f.cams_pm25,
            }
            for f in batch.forecasts
        ],
        ["site", "lat", "lon", "issued_at", "valid_at", *FORECAST_COLUMNS],
    )
    forecasts["issued_at"] = utc_ns(forecasts["issued_at"])
    forecasts["valid_at"] = utc_ns(forecasts["valid_at"])
    forecasts[FORECAST_COLUMNS] = forecasts[FORECAST_COLUMNS].astype(float)
    forecasts = forecasts.drop_duplicates(["site", "issued_at", "valid_at"], keep="last")

    fires = _frame(
        [
            {
                "lat": f.location.lat,
                "lon": f.location.lon,
                "observed_at": f.observed_at,
                "frp": f.fire.frp,
            }
            for f in batch.fires
        ],
        ["lat", "lon", "observed_at", "frp"],
    )
    fires["observed_at"] = utc_ns(fires["observed_at"])

    rasters = _frame(
        [
            {
                "cell": r.grid_id,
                "resolution": h3.get_resolution(r.grid_id),
                "processing_time": r.processing_time,
                "aerosol_index": r.sample_aerosol_index,
                "valid_fraction": r.valid_pixel_fraction,
            }
            for r in batch.rasters
            if r.product_id == S5P_PRODUCT and r.grid_id
        ],
        ["cell", "resolution", "processing_time", "aerosol_index", "valid_fraction"],
    )
    rasters["processing_time"] = utc_ns(rasters["processing_time"])
    rasters[["aerosol_index", "valid_fraction"]] = rasters[
        ["aerosol_index", "valid_fraction"]
    ].astype(float)

    return FeatureTables(stations, cams, weather, forecasts, fires, rasters)
