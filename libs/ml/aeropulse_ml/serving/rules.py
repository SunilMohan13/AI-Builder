"""Deterministic answers when no model is served (``degraded=true``).

Each rule returns the same columns as its family's plugin, so one
post-processing path turns either into contracts. They are the baselines the
models must beat, served under a ``persistence-*`` / ``absolute-threshold-*``
version so a reader can tell no model was involved.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from aeropulse_ml.models.base import column

FORECAST_RULE_VERSION = "persistence-forecast-1.0"
HAZARD_RULE_VERSION = "persistence-hazard-1.0"
ANOMALY_RULE_VERSION = "absolute-threshold-1.0"

RULE_VERSIONS: dict[str, str] = {
    "pm25_forecast": FORECAST_RULE_VERSION,
    "pm25_hazard_24h": HAZARD_RULE_VERSION,
    "anomaly": ANOMALY_RULE_VERSION,
}

#: Settings: the hazard ramp starts at this fraction of the region threshold
#: (the legacy rule ramped from 30 to 121 ug/m3). The output is a rank, never a
#: probability.
HAZARD_RAMP_FLOOR_FRACTION = 0.25


def forecast_rule(frame: pd.DataFrame) -> pd.DataFrame:
    """Persistence: P50 is the latest observation; no interval is claimed."""
    pm25 = column(frame, "pm25")
    empty = np.full(len(frame), np.nan)
    return pd.DataFrame({"p10": empty, "p50": pm25, "p90": empty.copy()}, index=frame.index)


def hazard_rule(frame: pd.DataFrame) -> pd.DataFrame:
    """Linear ramp of the current value up to the region threshold."""
    pm25 = column(frame, "pm25")
    threshold = column(frame, "region_threshold_ugm3")
    floor = threshold * HAZARD_RAMP_FLOOR_FRACTION
    with np.errstate(invalid="ignore", divide="ignore"):
        score = np.clip((pm25 - floor) / (threshold - floor), 0.0, 1.0)
    score[~(np.isfinite(pm25) & np.isfinite(threshold) & (threshold > 0))] = np.nan
    return pd.DataFrame({"score": score}, index=frame.index)


def anomaly_rule(frame: pd.DataFrame) -> pd.DataFrame:
    """Flag a value at or above the region threshold; the threshold is the expected high."""
    pm25 = column(frame, "pm25")
    threshold = column(frame, "region_threshold_ugm3")
    known = np.isfinite(pm25) & np.isfinite(threshold)
    flag = (pm25 >= threshold).astype(float)
    flag[~known] = np.nan
    empty = np.full(len(frame), np.nan)
    return pd.DataFrame(
        {
            "p10": empty,
            "p50": empty.copy(),
            "p90": threshold,
            "basis": "absolute_threshold",
            "is_anomaly": flag,
        },
        index=frame.index,
    )
