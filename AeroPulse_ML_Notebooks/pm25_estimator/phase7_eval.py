"""Shared evaluation contract for the Phase-7 PM2.5 notebooks (06, 07, 08).

`rolling_origin_folds`, `regression_metrics`, `regime_metrics` and `event_metrics` are
lifted verbatim in behaviour from `03_pm25_phase5_baseline_model_comparison.ipynb` so
that Phase-7 numbers are comparable with the Phase-5 baselines they are meant to beat.
They live here rather than being pasted into three notebooks because a split rule that
drifts between notebooks silently invalidates every comparison drawn across them.

Nothing in this module fits anything. It only splits and scores.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    mean_absolute_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
    root_mean_squared_error,
)

# Pollution regimes, identical to Phase 2 and Phase 5 so a regime row means the
# same thing in every table this project produces.
REGIME_BINS = [-np.inf, 30, 60, 90, 150, np.inf]
REGIME_LABELS = ["normal", "moderate", "high", "very_high", "extreme"]
EXTREME_THRESHOLD = 150.0

# Tail weights by target concentration (roadmap section 18, experiment E2).
# Rationale: 1.1% of rows are extreme, so an unweighted squared-error fit spends
# ~99% of its gradient on air nobody needs a warning about. These multipliers
# buy the tail attention proportional to how much the miss costs.
TAIL_WEIGHT_BANDS = [(30.0, 1.0), (60.0, 1.5), (90.0, 2.0),
                     (150.0, 4.0), (250.0, 8.0), (np.inf, 12.0)]


def rolling_origin_folds(timestamps, n_splits=5, test_frac=0.12,
                         purge_hours=1, embargo_hours=48):
    """Yield (train_idx, test_idx, cut, test_end) for purged expanding-window folds.

    Each fold trains on everything up to a cut and tests on the block after it, so
    every fold lands in a different part of the year while causality is preserved.
    A random K-fold is forbidden here (LLD section 19): rows are hourly and
    autoregressive, so a shuffled test row's answer sits in the training set as an
    ordinary feature of its neighbour.

    PURGE + EMBARGO. The target at t is PM2.5 at t+h, so training rows in the last h
    hours before the cut describe times inside the test block. Those are purged, and
    the embargo removes a further margin so a rolling window straddling the boundary
    cannot leak either.

    Args:
        timestamps: tz-aware datetime array, one entry per row of the design matrix.
        n_splits: number of expanding-window folds.
        test_frac: fraction of the total span used by each test block.
        purge_hours: forecast horizon; rows this close to the cut are dropped.
        embargo_hours: extra margin dropped on top of the purge.

    Yields:
        (train_idx, test_idx, cut, test_end) with integer positional indices.
    """
    ts = pd.DatetimeIndex(timestamps)
    order = np.argsort(ts.to_numpy())
    ts_sorted = ts[order]
    t_min, t_max = ts_sorted[0], ts_sorted[-1]
    span = t_max - t_min
    test_len = span * test_frac
    first_cut = t_min + span * (1 - test_frac * n_splits)
    gap = pd.Timedelta(hours=purge_hours + embargo_hours)

    for k in range(n_splits):
        cut = first_cut + test_len * k
        test_end = cut + test_len
        train_idx = order[ts_sorted < cut - gap]
        test_idx = order[(ts_sorted >= cut) & (ts_sorted < test_end)]
        if len(train_idx) < 500 or len(test_idx) < 100:
            continue
        yield train_idx, test_idx, cut, test_end


def tail_weights(y, bands=None):
    """Sample weights that escalate with the target concentration.

    Weighting by the TARGET is legitimate in training: y_train is known when the
    model is fitted. It would only be leakage if a weight were needed at inference.
    """
    bands = bands or TAIL_WEIGHT_BANDS
    y = np.asarray(y, dtype="float64")
    w = np.full(y.shape, bands[-1][1], dtype="float64")
    prev = -np.inf
    for upper, weight in bands:
        w[(y > prev) & (y <= upper)] = weight
        prev = upper
    return w


def regression_metrics(y, p):
    """Overall accuracy. Reported for completeness, not as the headline."""
    y, p = np.asarray(y, "float64"), np.asarray(p, "float64")
    return {
        "MAE": float(mean_absolute_error(y, p)),
        "RMSE": float(root_mean_squared_error(y, p)),
        "R2": float(r2_score(y, p)),
        "bias": float(np.mean(p - y)),
    }


def regime_metrics(y, p):
    """Accuracy by pollution level.

    A model can look good overall and be useless during severe episodes, because
    severe episodes are rare. This is the table where that shows up.
    """
    y, p = np.asarray(y, "float64"), np.asarray(p, "float64")
    regime = pd.cut(y, bins=REGIME_BINS, labels=REGIME_LABELS)
    rows = []
    for r in REGIME_LABELS:
        m = np.asarray(regime == r)
        if m.sum():
            rows.append({
                "regime": r, "count": int(m.sum()),
                "MAE": float(mean_absolute_error(y[m], p[m])),
                "RMSE": float(root_mean_squared_error(y[m], p[m])),
                "bias": float(np.mean(p[m] - y[m])),
            })
    return pd.DataFrame(rows)


def extreme_bias(y, p, threshold=EXTREME_THRESHOLD):
    """Mean signed error on hazardous rows. THE headline metric for Phase 7.

    Negative means the model underpredicts exactly when a warning matters. Phase 5
    measured -103 ug/m3 here, and every experiment in notebook 06 is ranked on
    moving this number toward zero rather than on RMSE - a model can improve RMSE
    by hedging harder toward the mean, which makes this metric worse.
    """
    y, p = np.asarray(y, "float64"), np.asarray(p, "float64")
    m = y >= threshold
    return float(np.mean(p[m] - y[m])) if m.sum() else np.nan


def event_metrics(y, p, threshold=EXTREME_THRESHOLD):
    """Treat the regression as an alarm: did it fire when it should have?

    Recall is what matters for a public-health warning - a missed episode costs
    far more than a false alarm.
    """
    yt = np.asarray(y, "float64") >= threshold
    yp = np.asarray(p, "float64") >= threshold
    return {
        "threshold": threshold,
        "extreme_precision": float(precision_score(yt, yp, zero_division=0)),
        "extreme_recall": float(recall_score(yt, yp, zero_division=0)),
        "extreme_f1": float(f1_score(yt, yp, zero_division=0)),
        "extreme_bias": extreme_bias(y, p, threshold),
        "actual_events": int(yt.sum()),
        "predicted_events": int(yp.sum()),
    }


def persistence(current_pm25):
    """The honest baseline: the next hours look like this one.

    AGENTS.md requires every metric be reported against this. Phase 5 found it beat
    every model on extreme recall, because a model that regresses toward the mean
    loses episodes that persistence keeps.
    """
    return np.asarray(current_pm25, dtype="float64")


def skill_score(model_rmse, baseline_rmse):
    """Fraction of baseline error removed. Negative means worse than the baseline."""
    return float(1.0 - model_rmse / baseline_rmse) if baseline_rmse else np.nan


def classification_metrics(y_true, prob, threshold=0.5):
    """Hazard-classifier scores. PR-AUC leads because the positive class is rare."""
    y_true = np.asarray(y_true, "float64")
    prob = np.asarray(prob, "float64")
    pred = (prob >= threshold).astype("float64")
    out = {
        "threshold": float(threshold),
        "precision": float(precision_score(y_true, pred, zero_division=0)),
        "recall": float(recall_score(y_true, pred, zero_division=0)),
        "f1": float(f1_score(y_true, pred, zero_division=0)),
        "pr_auc": float(average_precision_score(y_true, prob)),
        "brier": float(brier_score_loss(y_true, prob)),
        "positives": int(y_true.sum()),
        "predicted_positives": int(pred.sum()),
        "base_rate": float(y_true.mean()),
    }
    # ROC-AUC is undefined on a single-class slice, which happens on short folds.
    out["roc_auc"] = (float(roc_auc_score(y_true, prob))
                      if len(np.unique(y_true)) > 1 else np.nan)
    return out


def majority_class_baseline(y_true):
    """Honest classification baseline: always predict the majority class."""
    y_true = np.asarray(y_true, "float64")
    const = 1.0 if y_true.mean() > 0.5 else 0.0
    pred = np.full(y_true.shape, const)
    return {
        "precision": float(precision_score(y_true, pred, zero_division=0)),
        "recall": float(recall_score(y_true, pred, zero_division=0)),
        "f1": float(f1_score(y_true, pred, zero_division=0)),
        "brier": float(brier_score_loss(y_true, np.full(y_true.shape, y_true.mean()))),
    }


def calibration_error(y_true, prob, n_bins=10):
    """Expected calibration error: |predicted probability - observed rate|, weighted.

    A hazard model whose 0.8 means 0.3 in practice cannot be given a threshold that
    an operator can reason about, however good its ranking is.
    """
    y_true = np.asarray(y_true, "float64")
    prob = np.asarray(prob, "float64")
    edges = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(prob, edges[1:-1]), 0, n_bins - 1)
    total, err = len(prob), 0.0
    for b in range(n_bins):
        m = idx == b
        if m.sum():
            err += m.sum() / total * abs(prob[m].mean() - y_true[m].mean())
    return float(err)


def breakdown(meta, y, p, by, min_rows=200):
    """Per-group metrics, for the seasonal and spatial views the roadmap requires.

    A single aggregate can hide that the model works in the monsoon and fails in the
    burning season, which is the season the product exists for.
    """
    frame = meta.copy()
    frame["_y"], frame["_p"] = np.asarray(y, "float64"), np.asarray(p, "float64")
    rows = []
    for key, g in frame.groupby(by, observed=True):
        if len(g) < min_rows:
            continue
        rows.append({by: key, "rows": len(g),
                     **regression_metrics(g["_y"], g["_p"]),
                     "extreme_recall": event_metrics(g["_y"], g["_p"])["extreme_recall"],
                     "extreme_bias": extreme_bias(g["_y"], g["_p"])})
    return pd.DataFrame(rows)
