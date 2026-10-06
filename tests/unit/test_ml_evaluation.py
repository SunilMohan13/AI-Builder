"""Holdout and metric guards.

LLD §19 forbids random splits on this data. These tests pin the properties that
make the reported numbers trustworthy rather than merely present.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from aeropulse_ml.evaluation import (
    classification_metrics,
    detection_metrics,
    regression_metrics,
    seasonal_split,
    skill_score,
    spatial_split,
    temporal_split,
)


def _frame(cells: int = 3, hours: int = 40, start: str = "2026-09-01") -> pd.DataFrame:
    rows = []
    for cell in range(cells):
        for hour in range(hours):
            rows.append(
                {
                    "grid_id": f"cell{cell}",
                    "timestamp": pd.Timestamp(start, tz="UTC") + pd.Timedelta(hours=hour),
                    "pm25": 50.0 + hour + cell * 10,
                }
            )
    return pd.DataFrame(rows)


# --- temporal ---


def test_temporal_split_puts_test_strictly_in_the_future() -> None:
    """Any overlap would leak adjacent-hour correlation into the score."""
    split = temporal_split(_frame())
    assert split.usable
    assert split.train["timestamp"].max() < split.test["timestamp"].min()


def test_temporal_split_keeps_every_row() -> None:
    """A split must partition, not sample."""
    frame = _frame()
    split = temporal_split(frame)
    assert len(split.train) + len(split.test) == len(frame)


# --- spatial ---


def test_spatial_split_shares_no_cell_between_sides() -> None:
    """The point of a spatial holdout is unseen locations."""
    split = spatial_split(_frame())
    assert split.usable
    overlap = set(split.train["grid_id"]) & set(split.test["grid_id"])
    assert overlap == set()


def test_spatial_split_reports_when_it_cannot_evaluate() -> None:
    """With one cell there is no spatial holdout; that must be stated."""
    split = spatial_split(_frame(cells=1))
    assert not split.usable
    assert "insufficient groups" in split.detail


def test_spatial_split_is_deterministic() -> None:
    """Comparable metrics across retrains require a stable cut."""
    first = spatial_split(_frame())
    second = spatial_split(_frame())
    assert list(first.test["grid_id"].unique()) == list(second.test["grid_id"].unique())


# --- seasonal ---


def test_seasonal_split_declines_on_a_single_month() -> None:
    """Reporting a seasonal holdout from one month would be a false claim."""
    split = seasonal_split(_frame(hours=24))
    assert not split.usable
    assert "single month" in split.detail


def test_seasonal_split_holds_out_the_last_month() -> None:
    """With multiple months the newest becomes the holdout."""
    early = _frame(hours=24, start="2026-07-01")
    late = _frame(hours=24, start="2026-08-01")
    split = seasonal_split(pd.concat([early, late], ignore_index=True))
    assert split.usable
    assert split.test["timestamp"].dt.month.unique().tolist() == [8]


# --- regression metrics ---


def test_perfect_prediction_scores_zero_error() -> None:
    """Sanity anchor for the metric implementation."""
    metrics = regression_metrics([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert metrics["mae"] == 0.0
    assert metrics["r2"] == 1.0


def test_metrics_ignore_nan_pairs() -> None:
    """Missing observations must not be scored as zero error."""
    metrics = regression_metrics([1.0, np.nan, 3.0], [1.0, 100.0, 3.0])
    assert metrics["n"] == 2.0
    assert metrics["mae"] == 0.0


def test_empty_input_returns_no_metrics_rather_than_zero() -> None:
    """A zero MAE on no data would read as a perfect model."""
    assert regression_metrics([], []) == {}


def test_bias_reports_direction() -> None:
    """Systematic under-prediction must be visible, not hidden by MAE."""
    metrics = regression_metrics([10.0, 10.0], [5.0, 5.0])
    assert metrics["bias"] == -5.0
    assert metrics["mae"] == 5.0


# --- skill ---


@pytest.mark.parametrize(
    ("model", "baseline", "expected"),
    [(5.0, 10.0, 0.5), (10.0, 10.0, 0.0), (20.0, 10.0, -1.0)],
)
def test_skill_score_signs(model: float, baseline: float, expected: float) -> None:
    """Positive means better than baseline; negative means worse."""
    assert skill_score(model, baseline) == expected


def test_skill_score_handles_degenerate_baseline() -> None:
    """A zero-error baseline must not divide by zero."""
    assert skill_score(1.0, 0.0) == 0.0


# --- detection ---


def test_detection_metrics_expose_false_alert_rate() -> None:
    """LLD 45 asks for it: high recall with constant alerting is useless."""
    truth = [True, False, False, False]
    predicted = [True, True, True, True]
    metrics = detection_metrics(truth, predicted)
    assert metrics["recall"] == 1.0
    assert metrics["false_alert_rate"] == 1.0
    assert metrics["alert_rate"] == 1.0


def test_detection_metrics_on_a_silent_detector() -> None:
    """Never alerting must score zero recall, not undefined."""
    metrics = detection_metrics([True, True], [False, False])
    assert metrics["recall"] == 0.0
    assert metrics["false_alert_rate"] == 0.0


# --- classification ---


def test_classification_report_includes_calibration_metrics() -> None:
    """LLD 45 asks for calibration on source classification."""
    truth = ["a", "b", "a", "b"]
    predicted = ["a", "b", "b", "b"]
    proba = [[0.9, 0.1], [0.2, 0.8], [0.4, 0.6], [0.3, 0.7]]
    report = classification_metrics(truth, predicted, probabilities=proba, classes=["a", "b"])
    assert report.log_loss is not None
    assert report.brier is not None
    assert 0.0 <= report.macro_f1 <= 1.0
    assert set(report.confusion) == {"a", "b"}


def test_confident_wrong_predictions_are_penalised() -> None:
    """Log loss must punish confident errors harder than hedged ones."""
    confident = classification_metrics(
        ["a"], ["b"], probabilities=[[0.01, 0.99]], classes=["a", "b"]
    )
    hedged = classification_metrics(["a"], ["b"], probabilities=[[0.45, 0.55]], classes=["a", "b"])
    assert confident.log_loss is not None and hedged.log_loss is not None
    assert confident.log_loss > hedged.log_loss
