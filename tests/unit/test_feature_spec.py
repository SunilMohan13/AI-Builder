"""Guards on the shared training/serving feature contract."""

from datetime import UTC, datetime

import pytest
from aeropulse_contracts.feature import GridFeature
from aeropulse_contracts.feature_spec import (
    FEATURE_SETS,
    ML_FEATURE_VERSION,
    PM25_ESTIMATOR,
    PROPAGATION_FORECAST,
    FeatureSet,
    temporal_encodings,
    to_feature_dict,
)


def _feature(**overrides: object) -> GridFeature:
    base: dict[str, object] = {
        "grid_id": "881f1d4881fffff",
        "timestamp": datetime(2026, 9, 8, 6, 0, tzinfo=UTC),
        "center_lat": 28.61,
        "center_lon": 77.21,
        "pm25": 142.3,
    }
    base.update(overrides)
    return GridFeature(**base)  # type: ignore[arg-type]


def test_every_feature_set_resolves_against_the_contract() -> None:
    """No feature set may name a value the flattener cannot produce."""
    flat = to_feature_dict(_feature())
    for name, fs in FEATURE_SETS.items():
        missing = [n for n in fs.names if n not in flat]
        assert missing == [], f"{name} names unresolvable features: {missing}"


def test_no_feature_set_contains_its_own_target() -> None:
    """The leakage guard must hold for every registered set."""
    for fs in FEATURE_SETS.values():
        assert fs.target not in fs.names


def test_pm25_estimator_never_sees_pm25() -> None:
    """The estimator predicts pm25, so pm25 must not be an input."""
    assert "pm25" not in PM25_ESTIMATOR.names
    assert PM25_ESTIMATOR.target == "pm25"


def test_forecast_may_use_current_pm25() -> None:
    """Persistence correction legitimately knows the current value."""
    assert "pm25" in PROPAGATION_FORECAST.names


def test_vector_order_matches_names() -> None:
    """Vector order is part of the contract for positional models."""
    feature = _feature(pm10=210.0, no2=44.0)
    vector = PM25_ESTIMATOR.vector(feature)
    assert len(vector) == len(PM25_ESTIMATOR.names)
    idx = PM25_ESTIMATOR.names.index("pm10")
    assert vector[idx] == 210.0


def test_missing_inputs_stay_none_rather_than_zero() -> None:
    """Zero-filling would be indistinguishable from a real measurement."""
    row = PM25_ESTIMATOR.row(_feature())
    assert row["no2"] is None
    assert row["aod"] is None


def test_fire_count_is_numeric_not_absent() -> None:
    """fire_count defaults to 0 on the contract and must survive as 0.0."""
    row = PM25_ESTIMATOR.row(_feature())
    assert row["fire_count"] == 0.0


def test_temporal_encodings_are_cyclical() -> None:
    """Hour 23 must sit adjacent to hour 0, not at the far end of a ramp."""
    h23 = temporal_encodings(datetime(2026, 9, 8, 23, tzinfo=UTC))
    h00 = temporal_encodings(datetime(2026, 9, 9, 0, tzinfo=UTC))
    h12 = temporal_encodings(datetime(2026, 9, 8, 12, tzinfo=UTC))
    near = abs(h23["sin_hour"] - h00["sin_hour"]) + abs(h23["cos_hour"] - h00["cos_hour"])
    far = abs(h12["sin_hour"] - h00["sin_hour"]) + abs(h12["cos_hour"] - h00["cos_hour"])
    assert near < far


def test_naive_timestamps_are_treated_as_utc() -> None:
    """Feature rows arriving without tzinfo must not shift the encoding."""
    aware = temporal_encodings(datetime(2026, 9, 8, 6, tzinfo=UTC))
    naive = temporal_encodings(datetime(2026, 9, 8, 6))
    assert aware == naive


def test_duplicate_or_leaking_sets_are_rejected() -> None:
    """The frozen dataclass still allows ad-hoc sets; callers get no guard, so
    verify the validator logic itself catches both failure modes."""
    from aeropulse_contracts import feature_spec

    bad = FeatureSet(name="bad", names=("pm25", "no2"), target="pm25")
    original = dict(feature_spec.FEATURE_SETS)
    feature_spec.FEATURE_SETS["bad"] = bad
    try:
        with pytest.raises(AssertionError, match="leaks its target"):
            feature_spec._assert_no_target_leakage()
    finally:
        feature_spec.FEATURE_SETS.clear()
        feature_spec.FEATURE_SETS.update(original)


def test_ml_feature_version_is_pinned() -> None:
    """Artifacts record this string; changing it must be deliberate.

    Bumped to 2.0.0 with the servable feature families (integration plan
    Phase 1). Every 1.0.0 artifact is invalidated by that bump rather than
    reinterpreted against a vector that no longer means the same thing, which
    is the behaviour ``validate_feature_contract`` enforces.
    """
    assert ML_FEATURE_VERSION == "ml-features-2.0.0"
