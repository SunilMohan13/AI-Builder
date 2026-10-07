"""Recover local calendar positions from the cyclic local-time features.

Rows carry ``sin/cos_hour_local`` and ``sin/cos_dow_local`` computed in the
region pack's timezone, so a baseline or a statistical model can group by
local hour of week without knowing the timezone again.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

HOURS_PER_WEEK = 168
#: Absorbs float error from the sin/cos round trip before flooring.
_EPS = 1e-6


def _position(frame: pd.DataFrame, stem: str, period: int) -> np.ndarray:
    sin = frame[f"sin_{stem}_local"].to_numpy(dtype=float)
    cos = frame[f"cos_{stem}_local"].to_numpy(dtype=float)
    angle = np.mod(np.arctan2(sin, cos), 2 * np.pi)
    return np.mod(angle * period / (2 * np.pi) + _EPS, period)


def local_hour(frame: pd.DataFrame) -> np.ndarray:
    """Local clock hour as a float (11.5 at 11:30); NaN where missing."""
    return np.floor(_position(frame, "hour", 24) * 60.0) / 60.0


def local_hour_of_week(frame: pd.DataFrame, *, offset_hours: object = 0) -> np.ndarray:
    """Local hour-of-week bucket 0..167, optionally shifted (e.g. to ``t + h``)."""
    dow = np.floor(_position(frame, "dow", 7))
    how = dow * 24 + _position(frame, "hour", 24) + np.asarray(offset_hours, dtype=float)
    return np.floor(np.mod(how, HOURS_PER_WEEK))
