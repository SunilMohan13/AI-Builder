"""Servable feature families added in integration plan Phases 1-2.

Two things are worth testing here and nothing else is: that each new feature
computes the quantity its name claims, and that the ones derived from the
current hour cannot reach a model whose target is that same hour.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest
from aeropulse_contracts import feature_spec
from aeropulse_contracts.feature_spec import (
    DERIVED_FROM,
    PM25_ESTIMATOR,
    PROPAGATION_FORECAST,
    FeatureSet,
    calendar_encodings,
)
from aeropulse_contracts.meteo import MeteorologicalObservation
from aeropulse_contracts.observation import (
    Location,
    Measurement,
    Observation,
    Provenance,
    Quality,
)
from aeropulse_geospatial.grid import to_grid_id
from aeropulse_intelligence.features import VENTILATION_REFERENCE, build_features
from aeropulse_intelligence.snapshot import FeatureSnapshot

BASE = datetime(2026, 9, 8, tzinfo=UTC)
LAT, LON = 28.6, 77.2


def _obs(hour: int, value: float, lat: float = LAT, lon: float = LON) -> Observation:
    ts = BASE + timedelta(hours=hour)
    return Observation(
        observation_id=f"o-{lat}-{lon}-{hour}",
        source_id="test",
        source_record_id=f"{lat}-{lon}-{hour}",
        observed_at=ts,
        received_at=ts,
        location=Location(lat=lat, lon=lon),
        measurement=Measurement(parameter="pm25", value=value, unit="ug/m3"),
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=Provenance(provider="test", connector_version="1.0.0"),
    )


def _weather(hour: int, *, wind_u: float, wind_v: float, blh: float) -> MeteorologicalObservation:
    ts = BASE + timedelta(hours=hour)
    return MeteorologicalObservation(
        observation_id=f"w-{hour}",
        source_id="test",
        source_record_id=f"w-{hour}",
        observed_at=ts,
        received_at=ts,
        location=Location(lat=LAT, lon=LON),
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=Provenance(provider="test", connector_version="1.0.0"),
        wind_u=wind_u,
        wind_v=wind_v,
        boundary_layer_height=blh,
    )


def _build(observations, weather=(), hour: int = 6):
    snapshot = FeatureSnapshot(air_quality=list(observations), weather=list(weather))
    return build_features(
        to_grid_id(LAT, LON),
        BASE + timedelta(hours=hour),
        snapshot,
        center_lat=LAT,
        center_lon=LON,
    )


# --- Trailing history extensions -----------------------------------------


def test_rolling_max_takes_the_window_maximum_excluding_now() -> None:
    """The current hour must not enter its own trailing window."""
    values = [10.0, 90.0, 20.0, 30.0, 40.0, 50.0, 999.0]
    feature = _build([_obs(h, v) for h, v in enumerate(values)], hour=6)

    # Hours 0..5 precede hour 6; the 999.0 at hour 6 is the current value.
    assert feature.pm25 == pytest.approx(999.0)
    assert feature.pm25_roll_max_6h == pytest.approx(90.0)


def test_trend_uses_lags_only_so_it_is_safe_for_the_estimator() -> None:
    """`pm25_trend_3h` is lag_1h - lag_3h, never a function of pm25(t)."""
    values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 500.0]
    feature = _build([_obs(h, v) for h, v in enumerate(values)], hour=6)

    assert feature.pm25_lag_1h == pytest.approx(60.0)
    assert feature.pm25_lag_3h == pytest.approx(40.0)
    assert feature.pm25_trend_3h == pytest.approx(20.0)
    # The current value is enormous and must not move the trend at all.
    assert feature.pm25_trend_3h == pytest.approx(60.0 - 40.0)


def test_delta_and_percentile_read_the_current_hour() -> None:
    """These two are forecast-only inputs, and must reflect pm25(t)."""
    values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 100.0]
    feature = _build([_obs(h, v) for h, v in enumerate(values)], hour=6)

    assert feature.pm25_delta_1h == pytest.approx(40.0)
    # 100 exceeds every trailing value, so it ranks at the top of the window.
    assert feature.pm25_pct_rank_24h == pytest.approx(1.0)


def test_rolling_std_needs_two_points() -> None:
    """A single observation has no dispersion; None beats a fabricated 0.0."""
    one_point = _build([_obs(0, 50.0), _obs(1, 60.0)], hour=1)
    assert one_point.pm25_roll_std_24h is None

    several = _build([_obs(h, 50.0 + 10 * h) for h in range(5)], hour=4)
    assert several.pm25_roll_std_24h is not None
    assert several.pm25_roll_std_24h > 0


# --- Dispersion -----------------------------------------------------------


def test_ventilation_index_is_wind_speed_times_mixing_height() -> None:
    """The classic dispersion product, not an invented composite."""
    observations = [_obs(h, 50.0) for h in range(3)]
    weather = [_weather(2, wind_u=3.0, wind_v=4.0, blh=1000.0)]

    feature = _build(observations, weather, hour=2)

    assert feature.wind_speed == pytest.approx(5.0)
    assert feature.ventilation_index == pytest.approx(5000.0)


def test_stagnation_is_the_bounded_inverse_of_ventilation() -> None:
    """Stagnation must stay on [0, 1] at both extremes."""
    observations = [_obs(h, 50.0) for h in range(3)]

    calm = _build(observations, [_weather(2, wind_u=0.0, wind_v=0.1, blh=100.0)], hour=2)
    assert calm.stagnation_score is not None
    assert calm.stagnation_score > 0.99

    gale = _build(
        observations,
        [_weather(2, wind_u=30.0, wind_v=30.0, blh=VENTILATION_REFERENCE)],
        hour=2,
    )
    assert gale.stagnation_score == pytest.approx(0.0)


def test_dispersion_is_null_without_weather() -> None:
    """A missing input must produce an explicit null, never a zero."""
    feature = _build([_obs(h, 50.0) for h in range(3)], hour=2)

    assert feature.ventilation_index is None
    assert feature.stagnation_score is None


# --- Neighbour field ------------------------------------------------------


def test_neighbour_field_summarises_other_cells_not_this_one() -> None:
    """The cell's own value must be excluded, or the estimator sees its target."""
    own = [_obs(2, 100.0)]
    # ~30 km east and ~60 km north, both inside the 100 km neighbour radius.
    others = [
        _obs(2, 200.0, lat=LAT, lon=LON + 0.3),
        _obs(2, 400.0, lat=LAT + 0.55, lon=LON),
    ]

    feature = _build(own + others, hour=2)

    assert feature.neighbor_count == 2
    assert feature.neighbor_pm25_max == pytest.approx(400.0)
    assert feature.neighbor_pm25_mean == pytest.approx(300.0)
    # 100.0 is this cell's own reading and must not be averaged in.
    assert feature.neighbor_pm25_mean != pytest.approx((100.0 + 200.0 + 400.0) / 3)


def test_neighbour_field_is_empty_without_neighbours() -> None:
    """One station in range means no neighbour field, reported as null."""
    feature = _build([_obs(2, 100.0)], hour=2)

    assert feature.neighbor_count == 0
    assert feature.neighbor_pm25_mean is None
    assert feature.upwind_pm25 is None


def test_upwind_neighbour_is_chosen_by_wind_direction() -> None:
    """The upwind cell is the one the wind arrives from, not the nearest."""
    # Wind blowing toward the east (u>0) arrives from the west.
    weather = [_weather(2, wind_u=5.0, wind_v=0.0, blh=800.0)]
    west = _obs(2, 300.0, lat=LAT, lon=LON - 0.4)
    east = _obs(2, 900.0, lat=LAT, lon=LON + 0.4)

    feature = _build([_obs(2, 100.0), west, east], weather, hour=2)

    assert feature.upwind_pm25 == pytest.approx(300.0)


# --- Fire rings -----------------------------------------------------------


def test_fire_rings_are_nested_counts() -> None:
    """A 25 km fire is also inside 50 km; the rings must be cumulative."""
    from aeropulse_contracts.fire import FireObservation, FireProperties

    def fire(name: str, lat: float, lon: float, frp: float) -> FireObservation:
        ts = BASE + timedelta(hours=2)
        return FireObservation(
            observation_id=name,
            source_id="firms",
            source_record_id=name,
            observed_at=ts,
            received_at=ts,
            location=Location(lat=lat, lon=lon),
            quality=Quality(quality_flag="valid", quality_score=1.0),
            provenance=Provenance(provider="firms", connector_version="1.0.0"),
            fire=FireProperties(frp=frp, confidence=0.9, sensor="VIIRS"),
        )

    snapshot = FeatureSnapshot(
        air_quality=[_obs(2, 100.0)],
        fires=[
            fire("near", LAT + 0.1, LON, 10.0),  # ~11 km
            fire("mid", LAT + 0.35, LON, 20.0),  # ~39 km
            fire("far", LAT + 0.8, LON, 40.0),  # ~89 km
        ],
    )
    feature = build_features(
        to_grid_id(LAT, LON),
        BASE + timedelta(hours=2),
        snapshot,
        center_lat=LAT,
        center_lon=LON,
    )

    assert feature.fire_count_25km == 1
    assert feature.fire_count_50km == 2
    assert feature.fire_count == 3
    assert feature.fire_frp_50km == pytest.approx(30.0)


# --- Calendar -------------------------------------------------------------


def test_calendar_flags_mark_weekend_and_stubble_season() -> None:
    """Both are pure functions of the timestamp, so they are derived not stored."""
    # 2026-11-07 is a Saturday in the post-paddy burning window.
    autumn_weekend = calendar_encodings(datetime(2026, 11, 7, tzinfo=UTC))
    assert autumn_weekend == {"is_weekend": 1.0, "is_stubble_season": 1.0}

    # 2026-01-07 is a Wednesday outside the residue windows.
    winter_weekday = calendar_encodings(datetime(2026, 1, 7, tzinfo=UTC))
    assert winter_weekday == {"is_weekend": 0.0, "is_stubble_season": 0.0}


# --- Leakage safety -------------------------------------------------------


def test_current_hour_derivations_are_absent_from_the_estimator() -> None:
    """The estimator predicts pm25(t); anything computed from it must be out."""
    for name in ("pm25_delta_1h", "pm25_pct_rank_24h"):
        assert name not in PM25_ESTIMATOR.names
        assert "pm25" in DERIVED_FROM[name]


def test_current_hour_derivations_are_present_for_the_forecast() -> None:
    """The forecast target lies in the future, so pm25(t) is a valid input."""
    assert "pm25" in PROPAGATION_FORECAST.names
    for name in ("pm25_delta_1h", "pm25_pct_rank_24h"):
        assert name in PROPAGATION_FORECAST.names


def test_a_feature_derived_from_the_target_is_refused_at_import() -> None:
    """Name-level exclusion is not enough; the derivation graph is walked."""
    bad = FeatureSet(
        name="leaky_by_derivation",
        # `pm25_delta_1h` is pm25 - pm25_lag_1h, so handing it to a model
        # predicting pm25 reveals the answer exactly.
        names=("pm25_delta_1h", "temperature"),
        target="pm25",
    )
    original = dict(feature_spec.FEATURE_SETS)
    feature_spec.FEATURE_SETS["leaky_by_derivation"] = bad
    try:
        with pytest.raises(AssertionError, match="derived from its target"):
            feature_spec._assert_no_target_leakage()
    finally:
        feature_spec.FEATURE_SETS.clear()
        feature_spec.FEATURE_SETS.update(original)


def test_every_shipped_feature_set_passes_the_leakage_check() -> None:
    """The real sets must satisfy the rule they are checked against."""
    feature_spec._assert_no_target_leakage()


def test_neighbour_count_is_finite_and_numeric_in_the_vector() -> None:
    """Counts enter the model as floats, so NaN handling stays uniform."""
    feature = _build([_obs(2, 100.0), _obs(2, 200.0, lon=LON + 0.3)], hour=2)
    flat = feature_spec.to_feature_dict(feature)

    assert isinstance(flat["neighbor_count"], float)
    assert math.isfinite(flat["neighbor_count"])
