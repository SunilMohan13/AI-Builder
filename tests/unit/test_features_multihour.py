"""Regression tests for time selection in the grid feature builder.

The builder previously filtered candidate observations by grid cell only, with
no hour filter, so a snapshot spanning several hours collapsed to whichever
record happened to be last in the list. Every feature row for a cell then
carried an identical pollutant value while the lag columns varied correctly.

This was invisible in production because the live detection path passes a
single-hour snapshot, and invisible in tests because every fixture held one
hour. It corrupts any backfill, replay or training window, and it manufactures
a perfect-looking model score: a constant target is trivially predictable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aeropulse_common.ids import new_ulid
from aeropulse_contracts.meteo import MeteorologicalObservation
from aeropulse_contracts.observation import (
    Location,
    Measurement,
    Observation,
    Provenance,
    Quality,
)
from aeropulse_geospatial.grid import to_grid_id
from aeropulse_intelligence.features import build_features
from aeropulse_intelligence.snapshot import FeatureSnapshot

LAT, LON = 28.61, 77.21
BASE = datetime(2026, 9, 8, 0, tzinfo=UTC)


def _observation(hour: int, value: float, parameter: str = "pm25") -> Observation:
    stamp = BASE + timedelta(hours=hour)
    return Observation(
        observation_id=new_ulid("obs"),
        source_id="test",
        source_record_id=f"test_{hour}_{parameter}",
        observed_at=stamp,
        received_at=stamp,
        location=Location(lat=LAT, lon=LON),
        measurement=Measurement(parameter=parameter, value=value, unit="ug/m3"),
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=Provenance(provider="test", connector_version="1.0.0"),
    )


def _weather(hour: int, temperature: float) -> MeteorologicalObservation:
    stamp = BASE + timedelta(hours=hour)
    return MeteorologicalObservation(
        observation_id=new_ulid("met"),
        source_id="test",
        source_record_id=f"wx_{hour}",
        observed_at=stamp,
        received_at=stamp,
        location=Location(lat=LAT, lon=LON),
        temperature=temperature,
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=Provenance(provider="test", connector_version="1.0.0"),
    )


def _snapshot(hours: int = 6) -> FeatureSnapshot:
    return FeatureSnapshot(
        air_quality=[_observation(h, 100.0 + 10.0 * h) for h in range(hours)],
        weather=[_weather(h, 20.0 + h) for h in range(hours)],
    )


def _grid() -> str:
    return to_grid_id(LAT, LON)


def test_each_hour_selects_its_own_observation() -> None:
    """The whole point of a grid-hour feature: pm25 must track the hour."""
    snapshot = _snapshot()
    grid_id = _grid()
    values = [
        build_features(
            grid_id,
            BASE + timedelta(hours=h),
            snapshot,
            center_lat=LAT,
            center_lon=LON,
        ).pm25
        for h in range(6)
    ]
    assert values == [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]


def test_pm25_is_not_constant_across_a_window() -> None:
    """Guards the exact symptom of the original defect."""
    snapshot = _snapshot()
    grid_id = _grid()
    values = {
        build_features(
            grid_id, BASE + timedelta(hours=h), snapshot, center_lat=LAT, center_lon=LON
        ).pm25
        for h in range(6)
    }
    assert len(values) == 6, "a multi-hour window collapsed to a single value"


def test_weather_is_selected_by_time_not_only_distance() -> None:
    """Co-located weather must be matched to the requested hour."""
    snapshot = _snapshot()
    grid_id = _grid()
    feature = build_features(
        grid_id, BASE + timedelta(hours=2), snapshot, center_lat=LAT, center_lon=LON
    )
    assert feature.temperature == 22.0


def test_stale_weather_is_dropped_rather_than_attached() -> None:
    """Meteorology far from the feature hour must not be borrowed."""
    snapshot = FeatureSnapshot(
        air_quality=[_observation(20, 150.0)],
        weather=[_weather(0, 20.0)],
    )
    feature = build_features(
        _grid(),
        BASE + timedelta(hours=20),
        snapshot,
        center_lat=LAT,
        center_lon=LON,
    )
    assert feature.temperature is None


def test_absent_hour_yields_null_pm25() -> None:
    """A gap in the series must stay a gap, not inherit a neighbour."""
    snapshot = _snapshot(hours=3)
    feature = build_features(
        _grid(),
        BASE + timedelta(hours=10),
        snapshot,
        center_lat=LAT,
        center_lon=LON,
    )
    assert feature.pm25 is None


def test_lag_and_rolling_windows_exclude_the_current_hour() -> None:
    """Point-in-time safety: a window must never contain its own target."""
    snapshot = _snapshot()
    feature = build_features(
        _grid(),
        BASE + timedelta(hours=3),
        snapshot,
        center_lat=LAT,
        center_lon=LON,
    )
    assert feature.pm25 == 130.0
    assert feature.pm25_lag_1h == 120.0
    assert feature.pm25_lag_3h == 100.0
    # Hours 0,1,2 -> (100+110+120)/3
    assert feature.pm25_roll_6h == 110.0
    assert feature.pm25_roll_6h != feature.pm25


def test_co_pollutants_also_respect_the_hour() -> None:
    """The defect affected every pollutant, not just pm25."""
    snapshot = FeatureSnapshot(
        air_quality=[
            _observation(0, 10.0, "no2"),
            _observation(1, 20.0, "no2"),
            _observation(0, 100.0),
            _observation(1, 200.0),
        ],
    )
    feature = build_features(
        _grid(), BASE + timedelta(hours=1), snapshot, center_lat=LAT, center_lon=LON
    )
    assert feature.no2 == 20.0
    assert feature.pm25 == 200.0
