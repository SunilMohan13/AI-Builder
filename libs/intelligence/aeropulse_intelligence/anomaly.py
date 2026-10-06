"""Quantile / threshold anomaly detector (quantile-baseline-0.1)."""

from __future__ import annotations

from datetime import datetime

from aeropulse_contracts.prediction import AnomalyResult

ANOMALY_VERSION = "quantile-baseline-0.1"
ABSOLUTE_TRIGGER_UG = 100.0
MIN_HISTORY = 8


def detect_anomaly(
    grid_id: str,
    timestamp: datetime,
    observed_pm25: float | None,
    history: list[float],
    *,
    quality_score: float | None = 1.0,
) -> AnomalyResult:
    """Score a PM2.5 observation against history or an operational threshold.

    With fewer than ``MIN_HISTORY`` points, uses ``ABSOLUTE_TRIGGER_UG`` so the
    Punjab/NCR fixture demo can still create events.

    Args:
        grid_id: H3 cell.
        timestamp: Observation time.
        observed_pm25: Current PM2.5 or None.
        history: Prior PM2.5 values for the cell (may be empty).
        quality_score: Observation quality; low quality cannot trigger.

    Returns:
        Anomaly result with ``event_trigger``.
    """
    q = 1.0 if quality_score is None else quality_score
    if observed_pm25 is None or q < 0.5:
        return AnomalyResult(
            grid_id=grid_id,
            timestamp=timestamp,
            observed_pm25=observed_pm25,
            baseline_pm25=None,
            residual=None,
            anomaly_score=0.0,
            event_trigger=False,
            model_version=ANOMALY_VERSION,
        )

    if len(history) >= MIN_HISTORY:
        baseline = _percentile(history, 75)
        residual = observed_pm25 - baseline
        score = _clip((residual / max(baseline, 20.0) + 0.2) / 1.4)
        trigger = residual > 0 and score >= 0.55
    else:
        baseline = ABSOLUTE_TRIGGER_UG
        residual = observed_pm25 - baseline
        score = _clip(observed_pm25 / 250.0)
        trigger = observed_pm25 >= ABSOLUTE_TRIGGER_UG

    return AnomalyResult(
        grid_id=grid_id,
        timestamp=timestamp,
        observed_pm25=observed_pm25,
        baseline_pm25=round(baseline, 2),
        residual=round(residual, 2),
        anomaly_score=round(score, 4),
        event_trigger=trigger,
        model_version=ANOMALY_VERSION,
    )


def _percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    k = (len(ordered) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    frac = k - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))
