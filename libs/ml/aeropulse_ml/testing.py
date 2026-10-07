"""Deterministic synthetic records for tests and the parity check.

TEST DATA ONLY. Every record is stamped ``provider="synthetic-test"``. Values
are generated from a seeded random walk, are not measurements, and must
never reach a snapshot, the API, or a model promoted for serving. They exist
so that the feature, parity and training mechanics can be exercised on a
multi-day history that the committed single-snapshot fixtures cannot give.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import h3
import numpy as np
from aeropulse_common.hashing import dedup_key
from aeropulse_contracts import (
    FireObservation,
    Location,
    Measurement,
    MeteoForecast,
    MeteorologicalObservation,
    Observation,
    Provenance,
    ProvenanceClass,
    Quality,
    RasterObservation,
)
from aeropulse_contracts.fire import FireProperties
from aeropulse_geospatial import to_grid_id

from aeropulse_ml.preprocessing import RecordBatch

SYNTHETIC_PROVIDER = "synthetic-test"


@dataclass(frozen=True)
class SyntheticPlace:
    lat: float
    lon: float


#: Points inside each shipped region's display area. Positions only.
SYNTHETIC_PLACES: dict[str, tuple[tuple[SyntheticPlace, ...], tuple[SyntheticPlace, ...]]] = {
    # (stations, wind sites)
    "in-north": (
        (SyntheticPlace(28.61, 77.21), SyntheticPlace(30.90, 75.85), SyntheticPlace(30.34, 76.39)),
        (SyntheticPlace(28.70, 77.10), SyntheticPlace(30.70, 76.00)),
    ),
    "sg-singapore": (
        (SyntheticPlace(1.35, 103.82), SyntheticPlace(1.30, 103.95)),
        (SyntheticPlace(1.36, 103.85),),
    ),
    "au-nsw": (
        (SyntheticPlace(-33.87, 151.21), SyntheticPlace(-33.80, 150.90)),
        (SyntheticPlace(-33.85, 151.05),),
    ),
}


def _prov(cls: ProvenanceClass) -> Provenance:
    return Provenance(provider=SYNTHETIC_PROVIDER, connector_version="0", provenance_class=cls)


def _quality() -> Quality:
    return Quality(quality_flag="valid", quality_score=1.0)


def synthetic_batch(
    region_id: str = "in-north",
    *,
    start: datetime = datetime(2026, 10, 1, tzinfo=UTC),
    hours: int = 24 * 5,
    seed: int = 7,
    forecast_every_hours: int = 6,
    forecast_lead_hours: int = 30,
    station_source: str = "openaq",
) -> RecordBatch:
    """A multi-day history for one region: stations, weather, CAMS, forecasts, fires, S5P."""
    rng = np.random.default_rng(seed)
    stations, sites = SYNTHETIC_PLACES[region_id]
    times = [start + timedelta(hours=k) for k in range(hours)]
    diurnal = 1.0 + 0.3 * np.cos(2 * np.pi * (np.arange(hours) % 24 - 6) / 24)

    observations: list[Observation] = []
    for i, place in enumerate(stations):
        level = 60.0 + 20.0 * i
        walk = level + np.cumsum(rng.normal(0.0, 4.0, hours))
        values = np.clip(walk * diurnal, 5.0, 400.0)
        for k, at in enumerate(times):
            if rng.random() < 0.05:
                continue  # a missing hour
            rid = f"st{i}_{at:%Y%m%d%H}"
            observations.append(
                Observation(
                    observation_id=f"obs_{rid}",
                    source_id=station_source,
                    source_record_id=rid,
                    observed_at=at,
                    received_at=at + timedelta(minutes=15),
                    location=Location(lat=place.lat, lon=place.lon),
                    measurement=Measurement(
                        parameter="pm25", value=round(float(values[k]), 2), unit="ug/m3"
                    ),
                    quality=_quality(),
                    provenance=_prov(ProvenanceClass.MEASURED),
                    region_id=region_id,
                    grid_id=to_grid_id(place.lat, place.lon),
                    dedup_key=dedup_key(station_source, rid, at.isoformat(), "pm25"),
                )
            )

    weather: list[MeteorologicalObservation] = []
    forecasts: list[MeteoForecast] = []
    wind_u = 2.0 + np.cumsum(rng.normal(0.0, 0.3, hours + forecast_lead_hours))
    wind_v = -1.0 + np.cumsum(rng.normal(0.0, 0.3, hours + forecast_lead_hours))
    blh = np.clip(
        600 + 400 * np.cos(2 * np.pi * (np.arange(hours + forecast_lead_hours) - 9) / 24), 80, None
    )
    for j, site in enumerate(sites):
        for k, at in enumerate(times):
            rid = f"ws{j}_{at:%Y%m%d%H}"
            weather.append(
                MeteorologicalObservation(
                    observation_id=f"met_{rid}",
                    source_id="openmeteo",
                    source_record_id=rid,
                    observed_at=at,
                    received_at=at + timedelta(minutes=5),
                    location=Location(lat=site.lat, lon=site.lon),
                    parameter="weather",
                    wind_u=round(float(wind_u[k]), 3),
                    wind_v=round(float(wind_v[k]), 3),
                    temperature=round(25.0 + 5.0 * float(diurnal[k] - 1.0), 2),
                    humidity=round(55.0 + 10.0 * float(np.sin(k / 7.0)), 2),
                    pressure=1005.0,
                    rainfall=0.0,
                    boundary_layer_height=round(float(blh[k]), 1),
                    quality=_quality(),
                    provenance=_prov(ProvenanceClass.MODEL_DERIVED),
                    region_id=region_id,
                    grid_id=to_grid_id(site.lat, site.lon),
                )
            )
            observations.append(
                Observation(
                    observation_id=f"cams_{rid}",
                    source_id="openmeteo",
                    source_record_id=f"{rid}_pm25",
                    observed_at=at,
                    received_at=at + timedelta(minutes=5),
                    location=Location(lat=site.lat, lon=site.lon),
                    measurement=Measurement(
                        parameter="pm25",
                        value=round(float(50.0 * diurnal[k] + rng.normal(0, 3)), 2),
                        unit="ug/m3",
                    ),
                    quality=_quality(),
                    provenance=_prov(ProvenanceClass.MODEL_DERIVED),
                    region_id=region_id,
                    grid_id=to_grid_id(site.lat, site.lon),
                )
            )
        for k in range(0, hours, forecast_every_hours):
            issued = times[k]
            for lead in range(1, forecast_lead_hours + 1):
                idx = k + lead
                forecasts.append(
                    MeteoForecast(
                        forecast_id=f"fc{j}_{issued:%Y%m%d%H}_{lead}",
                        source_id="openmeteo",
                        site_id=f"site{j}",
                        issued_at=issued,
                        valid_at=issued + timedelta(hours=lead),
                        location=Location(lat=site.lat, lon=site.lon),
                        wind_u_10m=round(float(wind_u[idx] + rng.normal(0, 0.5)), 3),
                        wind_v_10m=round(float(wind_v[idx] + rng.normal(0, 0.5)), 3),
                        wind_u_100m=round(float(1.4 * wind_u[idx]), 3),
                        wind_v_100m=round(float(1.4 * wind_v[idx]), 3),
                        temperature=25.0,
                        humidity=55.0,
                        precipitation=0.0,
                        boundary_layer_height=round(float(blh[idx]), 1),
                        cams_pm25=round(float(50.0 + rng.normal(0, 5)), 2),
                        quality=_quality(),
                        provenance=_prov(ProvenanceClass.MODEL_DERIVED),
                        region_id=region_id,
                    )
                )

    fires: list[FireObservation] = []
    anchor = stations[0]
    for k in range(0, hours, 3):
        if rng.random() < 0.5:
            continue
        lat = anchor.lat + float(rng.uniform(-0.4, 0.4))
        lon = anchor.lon + float(rng.uniform(-0.4, 0.4))
        at = times[k]
        rid = f"fire_{at:%Y%m%d%H}"
        fires.append(
            FireObservation(
                observation_id=rid,
                source_id="firms",
                source_record_id=rid,
                observed_at=at,
                received_at=at + timedelta(hours=3),
                location=Location(lat=lat, lon=lon),
                fire=FireProperties(
                    frp=round(float(rng.uniform(5, 60)), 1), confidence=0.8, sensor="VIIRS"
                ),
                quality=_quality(),
                provenance=_prov(ProvenanceClass.MEASURED),
                region_id=region_id,
                grid_id=to_grid_id(lat, lon),
            )
        )

    rasters: list[RasterObservation] = []
    parent_cells = sorted({h3.cell_to_parent(to_grid_id(p.lat, p.lon), 5) for p in stations})
    for day in range(hours // 24):
        acquired = start + timedelta(days=day, hours=8)
        processed = acquired + timedelta(hours=12)
        for cell in parent_cells:
            lat, lon = h3.cell_to_latlng(cell)
            rasters.append(
                RasterObservation(
                    observation_id=f"ras_{cell}_{day}",
                    source_id="earthengine",
                    source_record_id=f"s5p_aer_ai_{acquired:%Y%m%d}_{cell}",
                    product_id="s5p_aer_ai",
                    acquisition_time=acquired,
                    processing_time=processed,
                    bbox=(lon, lat, lon, lat),
                    resolution="h3r5",
                    object_uri="",
                    checksum="",
                    quality=_quality(),
                    provenance=_prov(ProvenanceClass.MEASURED),
                    region_id=region_id,
                    grid_id=cell,
                    sample_aerosol_index=round(float(rng.normal(1.0, 0.5)), 3),
                    valid_pixel_fraction=round(float(rng.uniform(0.3, 1.0)), 3),
                )
            )

    return RecordBatch(
        observations=tuple(observations),
        weather=tuple(weather),
        forecasts=tuple(forecasts),
        fires=tuple(fires),
        rasters=tuple(rasters),
    )
