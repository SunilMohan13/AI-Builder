"""Shadow serving guards (integration plan Phase 4).

The property that matters most here is negative: nothing a challenger does may
change, delay or break the answer that serves. These tests assert that, and
assert that a challenger's failure is *recorded* rather than swallowed, since
a silently absent challenger is indistinguishable from an unregistered one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pytest
from aeropulse_contracts.feature import GridFeature
from aeropulse_contracts.feature_spec import ML_FEATURE_VERSION, PM25_ESTIMATOR
from aeropulse_ml.registry import ModelRecord, ModelRegistry, ModelStage
from aeropulse_ml.shadow import (
    ShadowScorer,
    comparison_report,
    feature_vector_hash,
)


class _ConstantModel:
    """Deterministic stand-in so assertions are about plumbing, not fit."""

    def __init__(self, value: float = 42.0) -> None:
        self.value = value

    def predict(self, matrix: Any) -> Any:
        return np.full(len(matrix), self.value)


class _ExplodingModel:
    """A challenger that fails at inference time."""

    def predict(self, matrix: Any) -> Any:
        raise RuntimeError("challenger exploded")


def _feature(grid_id: str = "8842492739fffff", pm25: float = 100.0) -> GridFeature:
    return GridFeature(
        grid_id=grid_id,
        timestamp=datetime(2026, 9, 8, 12, tzinfo=UTC),
        center_lat=28.6,
        center_lon=77.2,
        pm25=pm25,
        pm10=140.0,
        no2=30.0,
        so2=8.0,
        co=0.9,
        o3=20.0,
        station_distance=2.0,
        aod=0.4,
        wind_u=1.5,
        wind_v=-2.0,
        wind_speed=2.5,
        temperature=24.0,
        humidity=55.0,
        pressure=1005.0,
        rainfall=0.0,
        boundary_layer_height=800.0,
        pm25_lag_1h=95.0,
        pm25_lag_3h=90.0,
        pm25_lag_6h=88.0,
        pm25_lag_24h=80.0,
        pm25_roll_6h=91.0,
        pm25_roll_24h=85.0,
        pm25_roll_max_6h=99.0,
        pm25_roll_max_24h=105.0,
        pm25_roll_std_24h=7.5,
        pm25_trend_3h=5.0,
        pm25_trend_24h=15.0,
        pm25_delta_1h=5.0,
        pm25_pct_rank_24h=0.8,
        ventilation_index=2000.0,
        stagnation_score=0.667,
        neighbor_pm25_mean=97.0,
        neighbor_pm25_max=120.0,
        neighbor_count=3,
        upwind_pm25=118.0,
    )


def _register_shadow(
    registry: ModelRegistry,
    model: Any,
    *,
    family: str = "pm25_estimator",
    version: str = "shadow-1",
) -> ModelRecord:
    """Write an artifact and register it at SHADOW."""
    registry.root.mkdir(parents=True, exist_ok=True)
    path = registry.root / f"{version}.joblib"
    joblib.dump(
        {
            "model": model,
            "feature_names": list(PM25_ESTIMATOR.names),
            "target": PM25_ESTIMATOR.target,
            "ml_feature_version": ML_FEATURE_VERSION,
            "residual_std": 5.0,
        },
        path,
    )
    record = ModelRecord(
        model_id=version,
        model_name=family,
        version=version,
        stage=ModelStage.SHADOW,
        artifact_uri=str(path),
        training_time=datetime(2026, 9, 8, tzinfo=UTC),
    )
    registry.register(record)
    return record


@pytest.fixture
def registry(tmp_path: Path) -> ModelRegistry:
    return ModelRegistry(tmp_path / "models")


def test_no_challengers_scores_nothing(registry: ModelRegistry) -> None:
    """An empty registry is the normal case and must not be an error."""
    scorer = ShadowScorer(registry)
    assert scorer.warm() == {}
    assert scorer.challengers == {}
    assert scorer.score(_feature()) == []


def test_shadow_model_is_scored_but_never_promoted(registry: ModelRegistry) -> None:
    """A challenger produces rows while the champion stays unset."""
    _register_shadow(registry, _ConstantModel(42.0))
    scorer = ShadowScorer(registry)
    scorer.warm()

    rows = scorer.score(_feature(), champion_values={"pm25_estimator": 100.0})

    assert len(rows) == 1
    assert rows[0].shadow_value == pytest.approx(42.0)
    assert rows[0].champion_value == pytest.approx(100.0)
    assert rows[0].stage == ModelStage.SHADOW.value
    # The decisive assertion: scoring in shadow did not make it the champion.
    assert registry.champion("pm25_estimator") is None


def test_a_raising_challenger_is_recorded_not_propagated(registry: ModelRegistry) -> None:
    """A challenger exception must never reach the serving path."""
    _register_shadow(registry, _ExplodingModel())
    scorer = ShadowScorer(registry)
    scorer.warm()

    rows = scorer.score(_feature(), champion_values={"pm25_estimator": 100.0})

    assert len(rows) == 1
    assert rows[0].shadow_value is None
    assert "challenger exploded" in (rows[0].error or "")
    # The champion's value survives on the row, so the comparison is not lost.
    assert rows[0].champion_value == pytest.approx(100.0)


def test_corrupt_artifact_is_isolated_at_warm_time(registry: ModelRegistry) -> None:
    """An unloadable artifact degrades to no challenger, not to a crash."""
    registry.root.mkdir(parents=True, exist_ok=True)
    corrupt = registry.root / "corrupt.joblib"
    corrupt.write_bytes(b"not a joblib payload")
    registry.register(
        ModelRecord(
            model_id="corrupt",
            model_name="pm25_estimator",
            version="corrupt",
            stage=ModelStage.SHADOW,
            artifact_uri=str(corrupt),
            training_time=datetime(2026, 9, 8, tzinfo=UTC),
        )
    )

    scorer = ShadowScorer(registry)
    errors = scorer.warm()

    assert "pm25_estimator" in errors
    assert scorer.challengers == {}
    assert scorer.score(_feature()) == []


def test_feature_contract_mismatch_refuses_the_challenger(registry: ModelRegistry) -> None:
    """A stale artifact must not be scored against a changed feature spec."""
    registry.root.mkdir(parents=True, exist_ok=True)
    path = registry.root / "stale.joblib"
    joblib.dump(
        {
            "model": _ConstantModel(),
            "feature_names": list(PM25_ESTIMATOR.names),
            "ml_feature_version": "ml-features-0.9.0",
        },
        path,
    )
    registry.register(
        ModelRecord(
            model_id="stale",
            model_name="pm25_estimator",
            version="stale",
            stage=ModelStage.SHADOW,
            artifact_uri=str(path),
            training_time=datetime(2026, 9, 8, tzinfo=UTC),
        )
    )

    scorer = ShadowScorer(registry)
    errors = scorer.warm()

    assert "ml_feature_version" in errors["pm25_estimator"]
    assert scorer.challengers == {}


def test_feature_hash_pins_the_exact_inputs() -> None:
    """Identical features hash alike; a changed input changes the hash."""
    assert feature_vector_hash(_feature()) == feature_vector_hash(_feature())
    assert feature_vector_hash(_feature(pm25=100.0)) != feature_vector_hash(_feature(pm25=101.0))


def test_comparison_report_counts_failures_separately(registry: ModelRegistry) -> None:
    """A challenger that produced nothing must be visible as such."""
    _register_shadow(registry, _ExplodingModel())
    scorer = ShadowScorer(registry)
    scorer.warm()
    rows = scorer.score(_feature(), champion_values={"pm25_estimator": 100.0})

    report = comparison_report(rows)

    summary = report["models"]["pm25_estimator"]
    assert summary["rows"] == 1
    assert summary["scored"] == 0
    assert summary["failed"] == 1
    assert summary["error_rate"] == 1.0
    assert summary["mean_abs_diff_vs_champion"] is None


def test_comparison_report_measures_divergence_from_champion(
    registry: ModelRegistry,
) -> None:
    """The report states how far the challenger sits from the incumbent."""
    _register_shadow(registry, _ConstantModel(90.0))
    scorer = ShadowScorer(registry)
    scorer.warm()
    rows = scorer.score(_feature(), champion_values={"pm25_estimator": 100.0})

    summary = comparison_report(rows)["models"]["pm25_estimator"]

    assert summary["paired_with_champion"] == 1
    assert summary["mean_abs_diff_vs_champion"] == pytest.approx(10.0)
