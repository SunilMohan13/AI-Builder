"""Honest baselines per family (LLD APAC 7.1). A model must beat them.

Each baseline is fitted on training rows only (most need no fitting) and
returns NaN where it has nothing to say, so a skill figure is computed only on
rows where both the model and the baseline answered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd

from aeropulse_ml.features.local_time import local_hour_of_week

#: A climatology bin needs this many training values before it is used;
#: otherwise the next coarser bin answers.
MIN_CLIMATOLOGY_ROWS = 3


class Baseline(Protocol):
    name: str

    def fit(self, train: pd.DataFrame) -> Baseline: ...

    def predict(self, frame: pd.DataFrame) -> np.ndarray: ...


def _column(frame: pd.DataFrame, name: str) -> np.ndarray:
    if name not in frame.columns:
        return np.full(len(frame), np.nan)
    return pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)


@dataclass(frozen=True)
class ColumnBaseline:
    """A baseline that reads one feature column as its answer."""

    name: str
    column: str

    def fit(self, train: pd.DataFrame) -> ColumnBaseline:
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return _column(frame, self.column)


@dataclass(frozen=True)
class AboveThreshold:
    """1 when ``column`` is already at or above the region threshold."""

    name: str
    column: str

    def fit(self, train: pd.DataFrame) -> AboveThreshold:
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        value = _column(frame, self.column)
        threshold = _column(frame, "region_threshold_ugm3")
        out = (value >= threshold).astype(float)
        out[np.isnan(value) | np.isnan(threshold)] = np.nan
        return out


@dataclass
class HourOfWeekClimatology:
    """Mean target by local hour of week of the valid time, per cell.

    Falls back to the region's hour-of-week mean, then the region mean, when a
    bin holds fewer than :data:`MIN_CLIMATOLOGY_ROWS` training values.
    """

    target: str = "pm25_target"
    name: str = "climatology_hour_of_week"
    _cell: dict[tuple[str, float], float] = field(default_factory=dict)
    _region_how: dict[tuple[str, float], float] = field(default_factory=dict)
    _region: dict[str, float] = field(default_factory=dict)

    def _valid_how(self, frame: pd.DataFrame) -> np.ndarray:
        offset = _column(frame, "horizon_hours") if "horizon_hours" in frame.columns else 0
        return local_hour_of_week(frame, offset_hours=np.nan_to_num(offset))

    def fit(self, train: pd.DataFrame) -> HourOfWeekClimatology:
        data = pd.DataFrame(
            {
                "region_id": train["region_id"].to_numpy(),
                "cell": train["cell"].to_numpy(),
                "how": self._valid_how(train),
                "y": _column(train, self.target),
            }
        )
        if "horizon_hours" in train.columns:
            valid = pd.to_datetime(train["t"], utc=True) + pd.to_timedelta(
                np.nan_to_num(_column(train, "horizon_hours")), unit="h"
            )
            # One target value appears once per horizon; count it once.
            data["valid"] = valid.to_numpy()
            data = data.drop_duplicates(["cell", "valid"])
        data = data.dropna(subset=["y", "how"])
        fitted = HourOfWeekClimatology(self.target, self.name)
        fitted._cell = _means(data, ["cell", "how"])
        fitted._region_how = _means(data, ["region_id", "how"])
        fitted._region = {
            str(k): float(v) for k, v in data.groupby("region_id")["y"].mean().items()
        }
        return fitted

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        how = self._valid_how(frame)
        out = np.full(len(frame), np.nan)
        for i, (region, cell, h) in enumerate(
            zip(frame["region_id"].to_numpy(), frame["cell"].to_numpy(), how, strict=True)
        ):
            value = self._cell.get((cell, h))
            if value is None:
                value = self._region_how.get((region, h))
            if value is None:
                value = self._region.get(region)
            if value is not None:
                out[i] = value
        return out


def _means(data: pd.DataFrame, keys: list[str]) -> dict[tuple[str, float], float]:
    grouped = data.groupby(keys)["y"].agg(["mean", "count"])
    grouped = grouped[grouped["count"] >= MIN_CLIMATOLOGY_ROWS]
    return {(str(k[0]), float(k[1])): float(v) for k, v in grouped["mean"].items()}


def forecast_baselines() -> list[Baseline]:
    """Persistence, raw CAMS for the same valid hour, hour-of-week climatology."""
    return [
        ColumnBaseline("persistence", "pm25"),
        ColumnBaseline("cams_forecast", "cams_pm25_at_h"),
        HourOfWeekClimatology(),
    ]


def hazard_baselines() -> list[Baseline]:
    """Current PM2.5 as a score, persistence of "already above", max CAMS 24 h."""
    return [
        ColumnBaseline("current_pm25", "pm25"),
        AboveThreshold("already_above_threshold", "pm25_roll_24h"),
        ColumnBaseline("cams_max_24h", "cams_pm25_max_24h"),
    ]


def anomaly_baselines() -> list[Baseline]:
    """Today's absolute-threshold rule, at the region's own threshold."""
    return [AboveThreshold("absolute_threshold_rule", "pm25")]
