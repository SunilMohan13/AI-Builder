"""Peak and hazard trainers, and the gates that hold them back.

The gate is the load-bearing part. A trainer that produces a model is easy; a
trainer whose output is refused when it would mislead is the thing worth
testing, so most of this file is about blocking rather than about fitting.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from aeropulse_contracts.feature_spec import PM25_HAZARD_24H, PM25_PEAK_24H
from aeropulse_ml.registry import ModelRegistry
from aeropulse_ml.train import (
    CPCB_VERY_POOR_PM25,
    MAX_HAZARD_FALSE_ALERT_RATE,
    MIN_PEAK_EXTREME_RECALL,
    PEAK_HORIZON_HOURS,
    TrainingResult,
    build_peak_frame,
    dataset_fingerprint,
    evaluate_promotion_gate,
)


def _frame(hours: int = 120, *, pm25: list[float] | None = None) -> pd.DataFrame:
    """Build a minimal feature frame with the columns the trainers read."""
    base = datetime(2026, 9, 1, tzinfo=UTC)
    values = pm25 or [60.0 + 40.0 * np.sin(h / 6.0) for h in range(hours)]
    rows = []
    for hour, value in enumerate(values):
        rows.append(
            {
                "grid_id": "cell-a" if hour % 2 == 0 else "cell-b",
                "timestamp": base + timedelta(hours=hour),
                "pm25": value,
                **{name: float(hour % 7) for name in PM25_PEAK_24H.names if name != "pm25"},
            }
        )
    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame


# --- Target construction --------------------------------------------------


def test_peak_target_is_the_forward_maximum_excluding_now() -> None:
    """The current hour must not be inside the window it predicts."""
    values = [10.0] * 60
    values[30] = 500.0
    frame = _frame(60, pm25=values)
    # One cell only, so the forward window is contiguous.
    frame["grid_id"] = "cell-a"

    built = build_peak_frame(frame, horizon_hours=4)

    timestamps = list(frame["timestamp"])
    row_27 = built[built["timestamp"] == timestamps[27]]
    row_30 = built[built["timestamp"] == timestamps[30]]
    # Hour 27's window covers 28..31 and therefore contains the spike.
    assert list(row_27["pm25_peak_24h_target"]) == [pytest.approx(500.0)]
    # Hour 30 IS the spike; its own window is 31..34 and must not include it.
    assert list(row_30["pm25_peak_24h_target"]) == [pytest.approx(10.0)]


def test_partial_forward_windows_are_dropped_not_filled() -> None:
    """A maximum over 3 of 24 hours is a different quantity."""
    frame = _frame(30)
    frame["grid_id"] = "cell-a"

    built = build_peak_frame(frame, horizon_hours=PEAK_HORIZON_HOURS)

    # Only rows with all 24 forward hours survive: 30 - 24 = 6.
    assert len(built) == 6
    assert bool(built["pm25_peak_24h_target"].notna().all())


def test_hazard_label_uses_the_reconciled_cpcb_threshold() -> None:
    """One threshold, 121, not the 150 the other pipeline used."""
    values = [10.0] * 40 + [200.0] * 10 + [10.0] * 10
    frame = _frame(60, pm25=values)
    frame["grid_id"] = "cell-a"

    built = build_peak_frame(frame, horizon_hours=4)

    hazardous = built[built["hazard_extreme_24h"] == 1]
    assert not hazardous.empty
    assert (hazardous["pm25_peak_24h_target"] >= CPCB_VERY_POOR_PM25).all()
    quiet = built[built["hazard_extreme_24h"] == 0]
    assert (quiet["pm25_peak_24h_target"] < CPCB_VERY_POOR_PM25).all()


# --- Gates ---------------------------------------------------------------


def _peak_result(**temporal: object) -> TrainingResult:
    metrics = {
        "temporal": {
            "evaluated": True,
            "skill_vs_persistence": 0.5,
            "extreme_rows": 20.0,
            "extreme_recall": 0.9,
            "extreme_bias": -2.0,
            **temporal,
        }
    }
    return TrainingResult(model_name="pm25_peak_24h", version="v", algorithm="a", metrics=metrics)


def test_peak_gate_passes_a_good_model() -> None:
    assert evaluate_promotion_gate(_peak_result()) == []


def test_peak_gate_blocks_low_extreme_recall() -> None:
    """Missing episodes is the failure that matters for an alerting model."""
    failures = evaluate_promotion_gate(_peak_result(extreme_recall=0.2))

    assert any("extreme recall" in f for f in failures)
    assert any(str(MIN_PEAK_EXTREME_RECALL) in f for f in failures)


def test_peak_gate_blocks_severe_under_prediction() -> None:
    """Under-predicting an episode is the dangerous direction."""
    failures = evaluate_promotion_gate(_peak_result(extreme_bias=-70.6))

    assert any("under-predicts episodes" in f for f in failures)


def test_peak_gate_blocks_a_model_with_no_episodes_to_judge() -> None:
    """Unmeasured is not the same as passed."""
    failures = evaluate_promotion_gate(
        _peak_result(extreme_rows=0.0, extreme_recall=None, extreme_bias=None)
    )

    assert any("no rows above the CPCB Very Poor breakpoint" in f for f in failures)


def test_peak_gate_blocks_poor_spatial_generalisation() -> None:
    """The product claims prediction for cells with no station of their own."""
    result = _peak_result()
    result.metrics["spatial"] = {
        "evaluated": True,
        "extreme_rows": 24.0,
        "extreme_recall": 0.0,
    }

    failures = evaluate_promotion_gate(result)

    assert any("held-out cells" in f for f in failures)
    assert any("does not generalise" in f for f in failures)


def _hazard_result(**temporal: object) -> TrainingResult:
    metrics = {
        "temporal": {
            "evaluated": True,
            "model": {"pr_auc": 0.60},
            "current_pm25_baseline": {"pr_auc": 0.20},
            "detection_at_0.5": {"false_alert_rate": 0.02},
            **temporal,
        }
    }
    return TrainingResult(model_name="pm25_hazard_24h", version="v", algorithm="a", metrics=metrics)


def test_hazard_gate_passes_a_good_model() -> None:
    assert evaluate_promotion_gate(_hazard_result()) == []


def test_hazard_gate_blocks_a_model_that_only_matches_current_pm25() -> None:
    """If reading the current concentration does as well, serve nothing."""
    failures = evaluate_promotion_gate(
        _hazard_result(model={"pr_auc": 0.21}, current_pm25_baseline={"pr_auc": 0.20})
    )

    assert any("does not beat the current-pm25 baseline" in f for f in failures)


def test_hazard_gate_blocks_an_alert_storm() -> None:
    """A detector operators learn to ignore has negative value."""
    failures = evaluate_promotion_gate(
        _hazard_result(**{"detection_at_0.5": {"false_alert_rate": 0.9}})
    )

    assert any("false-alert rate" in f for f in failures)
    assert any(str(MAX_HAZARD_FALSE_ALERT_RATE) in f for f in failures)


def test_hazard_gate_blocks_an_unevaluable_holdout() -> None:
    """A single-class holdout proves nothing and must not pass."""
    result = TrainingResult(
        model_name="pm25_hazard_24h",
        version="v",
        algorithm="a",
        metrics={"temporal": {"evaluated": False, "reason": "single class"}},
    )

    assert evaluate_promotion_gate(result) == ["temporal holdout was not evaluable"]


# --- Provenance ----------------------------------------------------------


def test_dataset_fingerprint_is_stable_and_content_sensitive() -> None:
    """Two runs on identical rows must be identifiable as such."""
    frame = _frame(40)

    assert dataset_fingerprint(frame) == dataset_fingerprint(frame.copy())

    changed = frame.copy()
    changed.loc[0, "pm25"] = changed.loc[0, "pm25"] + 1.0
    assert dataset_fingerprint(changed) != dataset_fingerprint(frame)

    assert dataset_fingerprint(frame.iloc[0:0]) == "empty"


# --- End to end ----------------------------------------------------------


def test_trainers_produce_contract_valid_artifacts(tmp_path: Path) -> None:
    """The artifact must be loadable by the runtime that will serve it."""
    import joblib
    from aeropulse_ml.inference import validate_feature_contract
    from aeropulse_ml.train import train_pm25_hazard_24h, train_pm25_peak_24h

    registry = ModelRegistry(tmp_path / "models")
    # Quiet stretches must exceed the 24-hour horizon, or every forward window
    # catches an episode and the label collapses to a single class.
    values = ([20.0] * 60 + [200.0] * 12) * 4
    frame = _frame(len(values), pm25=values)
    frame["grid_id"] = "cell-a"

    peak = train_pm25_peak_24h(frame, registry)
    hazard = train_pm25_hazard_24h(frame, registry)

    for result, feature_set in (
        (peak, PM25_PEAK_24H),
        (hazard, PM25_HAZARD_24H),
    ):
        assert result.artifact_path is not None
        # Trusted input: the trainer wrote this file into tmp_path moments ago.
        bundle = joblib.load(result.artifact_path)
        # Raises on any mismatch; the assertion is that it does not.
        validate_feature_contract(result.model_name, bundle)
        assert result.feature_names == list(feature_set.names)
        assert result.primary_horizon_h == PEAK_HORIZON_HOURS

    assert hazard.calibration == "none", "uncalibrated scores must say so"
