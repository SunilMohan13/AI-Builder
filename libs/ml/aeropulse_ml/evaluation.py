"""Holdout construction and metrics.

LLD §19 is explicit: *"Models must be evaluated using spatial and temporal
holdouts. Avoid random splits because nearby locations and adjacent time
periods are correlated."* A shuffled split on this data leaks a cell's 07:00
reading into the training set while scoring its 08:00 reading, which inflates
every metric. Only the split functions here should be used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

DEFAULT_TRAIN_FRACTION = 0.8


@dataclass(frozen=True)
class Split:
    """One train/test partition.

    Attributes:
        name: Holdout strategy label, recorded in metrics.
        train: Training rows.
        test: Held-out rows.
        detail: Human-readable description of the cut.
    """

    name: str
    train: pd.DataFrame
    test: pd.DataFrame
    detail: str = ""

    @property
    def usable(self) -> bool:
        """Return True when both sides have rows."""
        return not self.train.empty and not self.test.empty


def temporal_split(
    frame: pd.DataFrame,
    *,
    train_fraction: float = DEFAULT_TRAIN_FRACTION,
    time_column: str = "timestamp",
) -> Split:
    """Split on a time boundary so the test set lies strictly in the future.

    Args:
        frame: Training frame.
        train_fraction: Quantile of the time axis used as the cut point.
        time_column: Timestamp column name.

    Returns:
        A temporal :class:`Split`.
    """
    if frame.empty:
        return Split("temporal", frame, frame, "empty frame")
    cut = frame[time_column].quantile(train_fraction)
    train = frame[frame[time_column] < cut]
    test = frame[frame[time_column] >= cut]
    return Split("temporal", train, test, f"cut at {cut}")


def spatial_split(
    frame: pd.DataFrame,
    *,
    group_column: str = "grid_id",
    holdout_groups: int = 1,
) -> Split:
    """Hold out entire grid cells so no test cell appears in training.

    This answers a different question from the temporal split: whether the model
    generalises to *unseen locations* rather than to future time.

    Args:
        frame: Training frame.
        group_column: Column identifying a location group.
        holdout_groups: Number of groups to hold out.

    Returns:
        A spatial :class:`Split`. Unusable when the frame has too few groups,
        which callers must report rather than silently skip.
    """
    if frame.empty:
        return Split("spatial", frame, frame, "empty frame")
    groups = sorted(frame[group_column].unique())
    if len(groups) <= holdout_groups:
        return Split(
            "spatial",
            frame,
            frame.iloc[0:0],
            f"insufficient groups: {len(groups)} available, need > {holdout_groups}",
        )
    # Deterministic choice keeps runs comparable across retrains.
    held = set(groups[-holdout_groups:])
    train = frame[~frame[group_column].isin(held)]
    test = frame[frame[group_column].isin(held)]
    return Split("spatial", train, test, f"held out {sorted(held)}")


def seasonal_split(
    frame: pd.DataFrame,
    *,
    time_column: str = "timestamp",
) -> Split:
    """Hold out the latest calendar month present.

    LLD §45 asks for season holdouts. With a short observation window this
    degrades to a month holdout and reports itself as unusable when the frame
    spans a single month, rather than pretending to a seasonal test.

    Args:
        frame: Training frame.
        time_column: Timestamp column name.

    Returns:
        A seasonal :class:`Split`.
    """
    if frame.empty:
        return Split("seasonal", frame, frame, "empty frame")
    # strftime rather than to_period: the latter drops tz info and warns.
    months = frame[time_column].dt.strftime("%Y-%m")
    unique = sorted(months.unique())
    if len(unique) < 2:
        return Split(
            "seasonal",
            frame,
            frame.iloc[0:0],
            f"single month in data ({unique[0] if unique else 'none'}); "
            "seasonal holdout not evaluable",
        )
    held = unique[-1]
    return Split(
        "seasonal",
        frame[months != held],
        frame[months == held],
        f"held out {held}",
    )


# --- metrics ---


def regression_metrics(y_true: Any, y_pred: Any) -> dict[str, float]:
    """Return MAE, RMSE, R2, bias and MAPE for a regression prediction.

    Args:
        y_true: Observed values.
        y_pred: Predicted values.

    Returns:
        Metric name to value. Empty input yields an empty mapping rather than
        a misleading zero.
    """
    true = np.asarray(y_true, dtype=float)
    pred = np.asarray(y_pred, dtype=float)
    mask = ~(np.isnan(true) | np.isnan(pred))
    true, pred = true[mask], pred[mask]
    if true.size == 0:
        return {}
    error = pred - true
    ss_res = float(np.sum(error**2))
    ss_tot = float(np.sum((true - true.mean()) ** 2))
    metrics = {
        "n": float(true.size),
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "bias": float(np.mean(error)),
        "r2": float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float("nan"),
    }
    nonzero = np.abs(true) > 1e-9
    if nonzero.any():
        metrics["mape"] = float(
            np.mean(np.abs(error[nonzero] / true[nonzero])) * 100.0,
        )
    return {k: round(v, 6) for k, v in metrics.items()}


def skill_score(model_mae: float, baseline_mae: float) -> float:
    """Return fractional error reduction against a baseline.

    A hybrid model that cannot beat persistence is not production-ready
    (LLD §45), so this number gates promotion rather than decorating a report.

    Args:
        model_mae: Candidate model MAE.
        baseline_mae: Baseline MAE.

    Returns:
        Positive when the model improves on the baseline; negative when it is
        worse. Returns 0.0 when the baseline is degenerate.
    """
    if baseline_mae <= 0:
        return 0.0
    return round((baseline_mae - model_mae) / baseline_mae, 6)


@dataclass
class ClassificationReport:
    """Per-class and aggregate classification metrics.

    Attributes:
        per_class: Class label to precision/recall/f1/support.
        macro_f1: Unweighted mean F1 across present classes.
        log_loss: Probabilistic loss, when probabilities were supplied.
        brier: Multiclass Brier score, when probabilities were supplied.
        confusion: Nested true-label to predicted-label counts.
    """

    per_class: dict[str, dict[str, float]] = field(default_factory=dict)
    macro_f1: float = 0.0
    log_loss: float | None = None
    brier: float | None = None
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view."""
        return {
            "per_class": self.per_class,
            "macro_f1": round(self.macro_f1, 6),
            "log_loss": None if self.log_loss is None else round(self.log_loss, 6),
            "brier": None if self.brier is None else round(self.brier, 6),
            "confusion": self.confusion,
        }


def classification_metrics(
    y_true: Any,
    y_pred: Any,
    *,
    probabilities: Any | None = None,
    classes: Any | None = None,
) -> ClassificationReport:
    """Compute precision/recall/F1, confusion, log loss and Brier score.

    Args:
        y_true: True labels.
        y_pred: Predicted labels.
        probabilities: Optional predicted probability matrix.
        classes: Column order of ``probabilities``.

    Returns:
        A :class:`ClassificationReport`.
    """
    true = np.asarray(y_true)
    pred = np.asarray(y_pred)
    report = ClassificationReport()
    if true.size == 0:
        return report

    labels = sorted(set(true.tolist()) | set(pred.tolist()))
    f1s: list[float] = []
    for label in labels:
        tp = int(np.sum((true == label) & (pred == label)))
        fp = int(np.sum((true != label) & (pred == label)))
        fn = int(np.sum((true == label) & (pred != label)))
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        report.per_class[str(label)] = {
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "support": float(int(np.sum(true == label))),
        }
        if int(np.sum(true == label)):
            f1s.append(f1)
    report.macro_f1 = float(np.mean(f1s)) if f1s else 0.0

    report.confusion = {
        str(t): {str(p): int(np.sum((true == t) & (pred == p))) for p in labels} for t in labels
    }

    if probabilities is not None and classes is not None:
        proba = np.asarray(probabilities, dtype=float)
        class_list = list(classes)
        index = {c: i for i, c in enumerate(class_list)}
        rows = [i for i, t in enumerate(true.tolist()) if t in index]
        if rows:
            clipped = np.clip(proba[rows], 1e-12, 1.0)
            targets = np.array([index[true.tolist()[i]] for i in rows])
            report.log_loss = float(-np.mean(np.log(clipped[np.arange(len(rows)), targets])))
            onehot = np.zeros_like(clipped)
            onehot[np.arange(len(rows)), targets] = 1.0
            report.brier = float(np.mean(np.sum((clipped - onehot) ** 2, axis=1)))
    return report


def detection_metrics(y_true: Any, y_pred: Any) -> dict[str, float]:
    """Binary event-detection metrics including false-alert rate.

    LLD §45 asks specifically for a false-alert rate: an anomaly detector that
    fires constantly is useless to an operator even at high recall.

    Args:
        y_true: True binary labels.
        y_pred: Predicted binary labels.

    Returns:
        Precision, recall, F1, false-alert rate and support counts.
    """
    true = np.asarray(y_true).astype(bool)
    pred = np.asarray(y_pred).astype(bool)
    if true.size == 0:
        return {}
    tp = int(np.sum(true & pred))
    fp = int(np.sum(~true & pred))
    fn = int(np.sum(true & ~pred))
    tn = int(np.sum(~true & ~pred))
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "n": float(true.size),
        "true_positives": float(tp),
        "false_positives": float(fp),
        "false_negatives": float(fn),
        "true_negatives": float(tn),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        # Fraction of quiet hours that produced an alert.
        "false_alert_rate": round(fp / (fp + tn), 6) if (fp + tn) else 0.0,
        "alert_rate": round(float(np.mean(pred)), 6),
    }


def ranking_metrics(y_true: Any, scores: Any) -> dict[str, float]:
    """Threshold-free quality of a probability score for a rare binary label.

    PR-AUC is reported alongside ROC-AUC and the positive base rate because
    ROC-AUC flatters a rare-event classifier: with 2% positives a model can
    score 0.88 ROC-AUC while its precision at any usable recall is poor.
    PR-AUC against the base rate is the honest comparison, so ``lift`` states
    how many times better than chance the ranking is.

    Args:
        y_true: True binary labels.
        scores: Predicted probability of the positive class.

    Returns:
        ``pr_auc``, ``roc_auc``, ``base_rate``, ``lift`` and ``positives``.
        Empty when the label has only one class, where neither metric is
        defined and returning a number would invent information.
    """
    true = np.asarray(y_true).astype(int)
    score = np.asarray(scores, dtype=float)
    if true.size == 0 or len(set(true.tolist())) < 2:
        return {}
    base_rate = float(np.mean(true))
    pr_auc = float(average_precision_score(true, score))
    return {
        "n": float(true.size),
        "positives": float(int(np.sum(true))),
        "base_rate": round(base_rate, 6),
        "pr_auc": round(pr_auc, 6),
        "roc_auc": round(float(roc_auc_score(true, score)), 6),
        # A PR-AUC equal to the base rate is a coin flip, so lift is the
        # number that says whether the ranking carries information at all.
        "lift": round(pr_auc / base_rate, 6) if base_rate else 0.0,
    }
