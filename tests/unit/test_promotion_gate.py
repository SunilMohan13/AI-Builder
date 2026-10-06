"""The promotion gate must be able to block a release.

Metrics are only worth computing if a bad one prevents serving. These tests pin
the specific failures observed on real data: a forecast horizon that loses to
persistence, and a classifier whose headline accuracy hides a dead class.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from aeropulse_ml.registry import ModelRegistry, ModelStage
from aeropulse_ml.train import (
    MIN_DETECTION_F1,
    TrainingResult,
    evaluate_promotion_gate,
    register_result,
)


def _result(model_name: str, metrics: dict[str, Any]) -> TrainingResult:
    return TrainingResult(
        model_name=model_name,
        version=f"{model_name}-test",
        algorithm="test",
        metrics=metrics,
        feature_names=["a"],
    )


# --- pm25 estimator ---


def _estimator_pass_metrics() -> dict[str, Any]:
    return {
        "temporal": {"evaluated": True, "skill_vs_baseline": 0.43, "r2": 0.97},
        "spatial": {"evaluated": True, "skill_vs_baseline": 0.31, "r2": 0.8},
        "seasonal": {"evaluated": True, "skill_vs_baseline": 0.18, "r2": 0.7},
    }


def test_estimator_passes_with_positive_skill() -> None:
    result = _result("pm25_estimator", _estimator_pass_metrics())
    assert evaluate_promotion_gate(result) == []


def test_estimator_blocked_when_it_loses_to_persistence() -> None:
    metrics = _estimator_pass_metrics()
    metrics["temporal"]["skill_vs_baseline"] = -0.05
    result = _result("pm25_estimator", metrics)
    failures = evaluate_promotion_gate(result)
    assert any("skill vs persistence" in f for f in failures)


def test_estimator_blocked_on_negative_r2() -> None:
    metrics = _estimator_pass_metrics()
    metrics["temporal"]["r2"] = -0.3
    result = _result("pm25_estimator", metrics)
    failures = evaluate_promotion_gate(result)
    assert any("R2" in f for f in failures)


def test_estimator_blocked_when_holdout_not_evaluable() -> None:
    result = _result("pm25_estimator", {"temporal": {"evaluated": False, "reason": "too small"}})
    assert any("not evaluable" in f for f in evaluate_promotion_gate(result))


def test_estimator_blocked_when_seasonal_holdout_declines() -> None:
    """A 3-day fixture spans one month; that must not reach PRODUCTION."""
    metrics = _estimator_pass_metrics()
    metrics["seasonal"] = {
        "evaluated": False,
        "reason": "single month in data (2026-09); seasonal holdout not evaluable",
    }
    failures = evaluate_promotion_gate(_result("pm25_estimator", metrics))
    assert any("seasonal holdout was not evaluable" in f for f in failures)


# --- anomaly detector ---


def test_anomaly_blocked_on_low_detection_f1() -> None:
    """Observed on real data: recall 0.046 with precision 0.6."""
    result = _result(
        "anomaly_detector",
        {
            "temporal": {
                "evaluated": True,
                "detection_vs_cpcb_very_poor": {
                    "f1": 0.0857,
                    "recall": 0.0462,
                    "precision": 0.6,
                },
            }
        },
    )
    failures = evaluate_promotion_gate(result)
    assert any("detection F1" in f for f in failures)
    assert any("most exceedances are missed" in f for f in failures)


def test_anomaly_passes_above_threshold() -> None:
    result = _result(
        "anomaly_detector",
        {
            "temporal": {
                "evaluated": True,
                "detection_vs_cpcb_very_poor": {"f1": MIN_DETECTION_F1 + 0.1, "recall": 0.5},
            }
        },
    )
    assert evaluate_promotion_gate(result) == []


# --- source likelihood ---


def test_source_blocked_on_dead_class() -> None:
    """Observed on real data: traffic F1 = 0.0 with 25 supporting rows."""
    result = _result(
        "source_likelihood",
        {
            "temporal": {
                "evaluated": True,
                "macro_f1": 0.607,
                "per_class": {
                    "mixed_unknown": {"f1": 0.985, "support": 2038.0},
                    "regional_transport": {"f1": 0.836, "support": 122.0},
                    "traffic": {"f1": 0.0, "support": 25.0},
                },
            }
        },
    )
    failures = evaluate_promotion_gate(result)
    assert any("never predicted correctly" in f and "traffic" in f for f in failures)


def test_source_ignores_absent_classes() -> None:
    """A class with no support cannot fail; it simply was not present."""
    result = _result(
        "source_likelihood",
        {
            "temporal": {
                "evaluated": True,
                "macro_f1": 0.9,
                "per_class": {
                    "mixed_unknown": {"f1": 0.99, "support": 100.0},
                    "dust": {"f1": 0.0, "support": 0.0},
                },
            }
        },
    )
    assert evaluate_promotion_gate(result) == []


# --- forecast ---


def test_forecast_blocked_when_any_horizon_loses_to_persistence() -> None:
    """Observed on real data: 24h temporal skill -0.119."""
    result = _result(
        "propagation_forecast",
        {
            "3h": {"temporal": {"evaluated": True, "skill_vs_persistence": 0.167}},
            "24h": {"temporal": {"evaluated": True, "skill_vs_persistence": -0.119}},
        },
    )
    failures = evaluate_promotion_gate(result)
    assert any("24h" in f for f in failures)


def test_forecast_passes_when_all_horizons_beat_persistence() -> None:
    result = _result(
        "propagation_forecast",
        {
            "3h": {"temporal": {"evaluated": True, "skill_vs_persistence": 0.17}},
            "6h": {"temporal": {"evaluated": True, "skill_vs_persistence": 0.25}},
        },
    )
    assert evaluate_promotion_gate(result) == []


# --- registry integration ---


@pytest.fixture
def registry(tmp_path: Path) -> ModelRegistry:
    return ModelRegistry(tmp_path / "models")


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"timestamp": pd.to_datetime(["2026-09-08T00:00:00Z"], utc=True), "grid_id": ["c0"]}
    )


def test_failing_model_is_held_at_validation(registry: ModelRegistry) -> None:
    """A blocked model stays inspectable but must never serve."""
    result = _result(
        "pm25_estimator",
        {"temporal": {"evaluated": True, "skill_vs_baseline": -0.5, "r2": 0.1}},
    )
    record, failures = register_result(result, registry, {}, frame=_frame(), promote=True)
    assert failures
    assert record.stage is ModelStage.VALIDATION
    assert registry.champion("pm25_estimator") is None


def test_failure_reasons_are_recorded_on_the_record(registry: ModelRegistry) -> None:
    """A later reader must see why the model was held back."""
    result = _result(
        "pm25_estimator",
        {"temporal": {"evaluated": True, "skill_vs_baseline": -0.5, "r2": 0.1}},
    )
    record, _ = register_result(result, registry, {}, frame=_frame(), promote=True)
    assert "PROMOTION GATE FAILED" in record.notes


def test_passing_model_reaches_production(registry: ModelRegistry) -> None:
    result = _result("pm25_estimator", _estimator_pass_metrics())
    record, failures = register_result(result, registry, {}, frame=_frame(), promote=True)
    assert failures == []
    assert record.stage is ModelStage.PRODUCTION


def test_force_overrides_the_gate_but_keeps_the_warning(registry: ModelRegistry) -> None:
    """Drills need an override; the record must still carry the reason."""
    result = _result(
        "pm25_estimator",
        {"temporal": {"evaluated": True, "skill_vs_baseline": -0.5, "r2": 0.1}},
    )
    record, failures = register_result(
        result, registry, {}, frame=_frame(), promote=True, force=True
    )
    assert failures
    assert record.stage is ModelStage.PRODUCTION
    assert "PROMOTION GATE FAILED" in record.notes


def test_no_promotion_requested_leaves_model_in_training(registry: ModelRegistry) -> None:
    result = _result("pm25_estimator", _estimator_pass_metrics())
    record, _ = register_result(result, registry, {}, frame=_frame(), promote=False)
    assert record.stage is ModelStage.TRAINING
