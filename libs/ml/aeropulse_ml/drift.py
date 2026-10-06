"""Feature and prediction distribution drift metrics (LLD §46)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def distribution_drift(
    reference: list[float],
    current: list[float],
    *,
    min_samples: int = 30,
    bins: int = 10,
) -> dict[str, Any]:
    """Compute PSI and two-sample KS drift with explicit sample-size gates."""
    ref = np.asarray(reference, dtype=float)
    cur = np.asarray(current, dtype=float)
    ref = ref[np.isfinite(ref)]
    cur = cur[np.isfinite(cur)]
    result: dict[str, Any] = {
        "reference_n": int(ref.size),
        "current_n": int(cur.size),
        "minimum_samples": min_samples,
    }
    if ref.size < min_samples or cur.size < min_samples:
        return {
            **result,
            "status": "INSUFFICIENT_DATA",
            "psi": None,
            "ks_statistic": None,
            "ks_critical_value": None,
        }

    psi = _psi(ref, cur, bins)
    ks = _ks_statistic(ref, cur)
    critical = 1.36 * math.sqrt((ref.size + cur.size) / (ref.size * cur.size))
    status = "DRIFT" if psi >= 0.25 or ks > critical else "WARNING" if psi >= 0.10 else "STABLE"
    return {
        **result,
        "status": status,
        "psi": round(psi, 6),
        "ks_statistic": round(ks, 6),
        "ks_critical_value": round(critical, 6),
        "reference_mean": round(float(ref.mean()), 6),
        "current_mean": round(float(cur.mean()), 6),
        "reference_std": round(float(ref.std()), 6),
        "current_std": round(float(cur.std()), 6),
    }


def _psi(reference: np.ndarray, current: np.ndarray, bins: int) -> float:
    quantiles = np.linspace(0.0, 1.0, bins + 1)
    edges = np.unique(np.quantile(reference, quantiles))
    if edges.size < 2:
        value = float(edges[0])
        edges = np.array([value - 0.5, value + 0.5])
    edges[0], edges[-1] = -np.inf, np.inf
    ref_counts, _ = np.histogram(reference, bins=edges)
    cur_counts, _ = np.histogram(current, bins=edges)
    epsilon = 1e-6
    ref_share = np.clip(ref_counts / reference.size, epsilon, None)
    cur_share = np.clip(cur_counts / current.size, epsilon, None)
    return float(np.sum((cur_share - ref_share) * np.log(cur_share / ref_share)))


def _ks_statistic(reference: np.ndarray, current: np.ndarray) -> float:
    values = np.sort(np.unique(np.concatenate((reference, current))))
    ref_cdf = np.searchsorted(np.sort(reference), values, side="right") / reference.size
    cur_cdf = np.searchsorted(np.sort(current), values, side="right") / current.size
    return float(np.max(np.abs(ref_cdf - cur_cdf)))
