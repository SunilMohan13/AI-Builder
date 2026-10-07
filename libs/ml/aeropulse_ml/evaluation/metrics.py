"""Metrics for the APAC families (LLD APAC 7.5).

Every function returns ``{}`` or ``None`` when its inputs cannot support the
number, rather than a zero that reads as a measurement.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from aeropulse_ml.evaluation.holdouts import ranking_metrics, regression_metrics

#: Bins for expected calibration error. Equal-width bins over [0, 1].
ECE_BINS = 10


def _finite(*arrays: Any) -> tuple[np.ndarray, ...]:
    values = [np.asarray(a, dtype=float) for a in arrays]
    mask = np.ones(values[0].shape, dtype=bool)
    for v in values:
        mask &= np.isfinite(v)
    return tuple(v[mask] for v in values)


def brier_score(y_true: Any, prob: Any) -> float | None:
    """Mean squared error of a probability against a 0/1 label."""
    true, p = _finite(y_true, prob)
    if true.size == 0:
        return None
    return round(float(np.mean((p - true) ** 2)), 6)


def expected_calibration_error(y_true: Any, prob: Any, *, bins: int = ECE_BINS) -> float | None:
    """Bin-size-weighted gap between mean score and observed frequency."""
    true, p = _finite(y_true, prob)
    if true.size == 0:
        return None
    edges = np.linspace(0.0, 1.0, bins + 1)
    index = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    total = 0.0
    for b in range(bins):
        sel = index == b
        if sel.any():
            total += sel.sum() * abs(float(p[sel].mean()) - float(true[sel].mean()))
    return round(total / true.size, 6)


def interval_coverage(y_true: Any, low: Any, high: Any) -> float | None:
    """Share of observations inside ``[low, high]``."""
    true, lo, hi = _finite(y_true, low, high)
    if true.size == 0:
        return None
    return round(float(np.mean((true >= lo) & (true <= hi))), 6)


def extreme_recall(y_true: Any, y_pred: Any, threshold: Any) -> dict[str, float]:
    """Recall of rows at or above a per-row threshold.

    ``threshold`` may be NaN for rows whose region has no confirmed standard;
    those rows are not extreme rows, not misses.
    """
    true, pred, thr = _finite(y_true, y_pred, threshold)
    extreme = true >= thr
    rows = int(extreme.sum())
    if rows == 0:
        return {"extreme_rows": 0.0}
    hits = int(np.sum(pred[extreme] >= thr[extreme]))
    return {"extreme_rows": float(rows), "extreme_recall": round(hits / rows, 6)}


def alert_metrics(y_true: Any, score: Any, threshold: float) -> dict[str, float]:
    """Recall and false-alert share at one operating threshold."""
    true, s = _finite(y_true, score)
    if true.size == 0:
        return {}
    pred = s >= threshold
    positive = true >= 0.5
    tp = int(np.sum(pred & positive))
    fp = int(np.sum(pred & ~positive))
    fn = int(np.sum(~pred & positive))
    tn = int(np.sum(~pred & ~positive))
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "threshold": round(float(threshold), 6),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "false_alert_rate": round(fp / (fp + tn), 6) if (fp + tn) else 0.0,
        # Share of alerts that were wrong: what an operator experiences.
        "false_alert_share": round(fp / (tp + fp), 6) if (tp + fp) else 0.0,
    }


def choose_operating_threshold(
    y_true: Any, score: Any, *, max_false_alert_rate: float
) -> float | None:
    """Highest-recall threshold whose false-alert rate stays within the limit.

    Chosen on the calibration slice only; the test slice never picks it.
    ``None`` when the slice cannot support a choice (one class, no rows).
    """
    true, s = _finite(y_true, score)
    positive = true >= 0.5
    negatives = int((~positive).sum())
    if true.size == 0 or negatives == 0 or not positive.any():
        return None
    order = np.argsort(-s, kind="stable")
    ranked = s[order]
    false_alerts = np.cumsum(~positive[order])
    # Alerting at threshold ranked[i] alerts on every row scored >= it, so a
    # tie group is admitted only as a whole: take the last index of each group.
    last_of_group = np.r_[ranked[1:] != ranked[:-1], True]
    admissible = last_of_group & (false_alerts / negatives <= max_false_alert_rate)
    if not admissible.any():
        return None
    # Recall only grows as the threshold falls, so the lowest admissible
    # threshold has the highest recall.
    return float(ranked[np.flatnonzero(admissible)[-1]])


def forecast_metrics(
    y_true: Any,
    p50: Any,
    *,
    p10: Any | None = None,
    p90: Any | None = None,
    threshold: Any | None = None,
) -> dict[str, Any]:
    """MAE/RMSE/bias of the median, interval coverage, extreme recall."""
    out: dict[str, Any] = dict(regression_metrics(y_true, p50))
    if not out:
        return {}
    if p10 is not None and p90 is not None:
        out["coverage_p10_p90"] = interval_coverage(y_true, p10, p90)
    if threshold is not None:
        out.update(extreme_recall(y_true, p50, threshold))
    return out


def hazard_metrics(y_true: Any, score: Any, *, operating_threshold: float | None) -> dict[str, Any]:
    """PR-AUC, ROC-AUC, Brier, ECE and alerting at the chosen threshold."""
    true, s = _finite(y_true, score)
    out: dict[str, Any] = dict(ranking_metrics(true, s))
    if not out:
        return {}
    out["brier"] = brier_score(true, s)
    out["ece"] = expected_calibration_error(true, s)
    if operating_threshold is not None:
        out["at_operating_point"] = alert_metrics(true, s, operating_threshold)
    return out


def skill(model_error: float | None, baseline_error: float | None) -> float | None:
    """Fractional error reduction against a baseline; ``None`` if undefined."""
    if model_error is None or baseline_error is None or baseline_error <= 0:
        return None
    return round((baseline_error - model_error) / baseline_error, 6)
