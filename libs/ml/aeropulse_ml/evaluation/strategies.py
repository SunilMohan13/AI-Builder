"""Evaluation strategies (LLD APAC 7.5). No random splits.

A strategy turns a labelled, pooled feature frame (``region_id``, ``cell``,
``t``, features, label) into folds of row labels. Every fold keeps training
rows whose label window could overlap a test row out of training (purge), and
the calibration slice sits between training and test, so a threshold or a
calibration map is never fitted on test rows.

A strategy that the data cannot support returns :class:`Unavailable` with a
reason, which the gate report shows as "not available" rather than a number.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import pandas as pd

#: Folds for purged rolling-origin (LLD APAC 7.5, setting).
DEFAULT_FOLDS = 5
#: Notebook setting carried over: rows within this many hours after a held-out
#: block are kept out of training when training data follows the test block.
DEFAULT_EMBARGO_HOURS = 48
#: Share of the training time range set aside for calibration (setting).
DEFAULT_CALIBRATION_FRACTION = 0.2
#: Season occurrences further apart than this are separate seasons.
_SEASON_GAP = pd.Timedelta(days=31)


@dataclass(frozen=True)
class Fold:
    """One train/calibration/test partition, as row labels of the frame."""

    strategy: str
    name: str
    fit: pd.Index
    test: pd.Index
    calibration: pd.Index = field(default_factory=lambda: pd.Index([]))
    #: Regions whose test rows this fold is meant to measure.
    regions: tuple[str, ...] = ()
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "strategy": self.strategy,
            "name": self.name,
            "fit_rows": len(self.fit),
            "calibration_rows": len(self.calibration),
            "test_rows": len(self.test),
            "regions": list(self.regions),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class Unavailable:
    """The data cannot support this strategy; ``reason`` says why."""

    strategy: str
    reason: str
    region_id: str | None = None


@runtime_checkable
class EvaluationStrategy(Protocol):
    name: str

    def folds(self, frame: pd.DataFrame) -> list[Fold | Unavailable]: ...


def label_horizon_hours(frame: pd.DataFrame, default: float = 24.0) -> float:
    """Longest look-ahead of any label in the frame (the purge length)."""
    if "horizon_hours" in frame.columns and frame["horizon_hours"].notna().any():
        return float(frame["horizon_hours"].max())
    return default


def _times(frame: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(frame["t"], utc=True)


@dataclass(frozen=True)
class CalibrationSplit:
    """Carve the latest part of a training range off for calibration.

    ``fit`` ends ``purge_hours`` before the slice starts, so no fitted row's
    label window reaches into the slice.
    """

    fraction: float = DEFAULT_CALIBRATION_FRACTION
    purge_hours: float = 24.0
    name: str = "calibration_slice"

    def carve(self, frame: pd.DataFrame, train: pd.Index) -> tuple[pd.Index, pd.Index]:
        if len(train) == 0 or self.fraction <= 0:
            return train, pd.Index([])
        t = _times(frame.loc[train])
        start, end = t.min(), t.max()
        cut = start + (end - start) * (1.0 - self.fraction)
        calibration = t.index[t >= cut]
        fit = t.index[t < cut - pd.Timedelta(hours=self.purge_hours)]
        if len(fit) == 0 or len(calibration) == 0:
            return train, pd.Index([])
        return fit, calibration


@dataclass(frozen=True)
class PurgedRollingOrigin:
    """Expanding window over time; test blocks move forward fold by fold.

    The time range is cut into ``n_folds + 1`` equal blocks. Fold ``k`` tests
    block ``k`` and trains on everything ending ``purge_hours`` before it.
    Training always precedes test here, so no embargo is needed.
    """

    n_folds: int = DEFAULT_FOLDS
    purge_hours: float | None = None
    calibration: CalibrationSplit | None = None
    name: str = "purged_rolling_origin"

    def folds(self, frame: pd.DataFrame) -> list[Fold | Unavailable]:
        if frame.empty:
            return [Unavailable(self.name, "no labelled rows")]
        purge = pd.Timedelta(hours=self.purge_hours or label_horizon_hours(frame))
        t = _times(frame)
        start, end = t.min(), t.max()
        if end <= start:
            return [Unavailable(self.name, "labelled rows cover a single hour")]
        width = (end - start) / (self.n_folds + 1)
        out: list[Fold | Unavailable] = []
        for k in range(1, self.n_folds + 1):
            lo = start + width * k
            hi = start + width * (k + 1)
            last = k == self.n_folds
            in_test = (t >= lo) & ((t <= hi) if last else (t < hi))
            train = t.index[t < lo - purge]
            test = t.index[in_test]
            name = f"fold-{k}"
            if len(train) == 0 or len(test) == 0:
                out.append(Unavailable(self.name, f"{name}: no training rows {purge} before {lo}"))
                continue
            fit, cal = self._carve(frame, train)
            out.append(
                Fold(
                    self.name,
                    name,
                    fit=fit,
                    calibration=cal,
                    test=test,
                    regions=tuple(sorted(frame.loc[test, "region_id"].unique())),
                    detail=f"test [{lo.isoformat()}, {hi.isoformat()}], purge {purge}",
                )
            )
        return out

    def _carve(self, frame: pd.DataFrame, train: pd.Index) -> tuple[pd.Index, pd.Index]:
        if self.calibration is None:
            return train, pd.Index([])
        return self.calibration.carve(frame, train)


@dataclass(frozen=True)
class LeaveRegionOut:
    """Train on the other regions, test on one: the transfer claim."""

    calibration: CalibrationSplit | None = None
    name: str = "leave_region_out"

    def folds(self, frame: pd.DataFrame) -> list[Fold | Unavailable]:
        regions = sorted(frame["region_id"].unique()) if not frame.empty else []
        if len(regions) < 2:
            reason = "only one region has ground truth" if regions else "no region has ground truth"
            return [Unavailable(self.name, reason)]
        out: list[Fold | Unavailable] = []
        for region in regions:
            is_held = frame["region_id"] == region
            train = frame.index[~is_held]
            fit, cal = (
                self.calibration.carve(frame, train) if self.calibration else (train, pd.Index([]))
            )
            out.append(
                Fold(
                    self.name,
                    f"holdout-{region}",
                    fit=fit,
                    calibration=cal,
                    test=frame.index[is_held],
                    regions=(region,),
                    detail=f"trained on {[r for r in regions if r != region]}",
                )
            )
        return out


@dataclass(frozen=True)
class SeasonCheck:
    """Hold out a region's latest pollution season (local months).

    Training rows from every region within ``purge_hours`` before or
    ``embargo_hours`` after the held-out season are dropped, because the
    season is in the middle of the timeline and training data can follow it.
    """

    season_months: Mapping[str, frozenset[int]]
    timezones: Mapping[str, str]
    purge_hours: float | None = None
    embargo_hours: float = DEFAULT_EMBARGO_HOURS
    calibration: CalibrationSplit | None = None
    name: str = "season_check"

    def folds(self, frame: pd.DataFrame) -> list[Fold | Unavailable]:
        if frame.empty:
            return [Unavailable(self.name, "no labelled rows")]
        purge = pd.Timedelta(hours=self.purge_hours or label_horizon_hours(frame))
        embargo = pd.Timedelta(hours=self.embargo_hours)
        t = _times(frame)
        out: list[Fold | Unavailable] = []
        for region in sorted(frame["region_id"].unique()):
            months = self.season_months.get(region)
            if not months:
                out.append(Unavailable(self.name, "region has no seasonal prior", region))
                continue
            mine = frame["region_id"] == region
            local_month = t[mine].dt.tz_convert(self.timezones[region]).dt.month
            in_season = local_month.isin(sorted(months))
            if not in_season.any():
                out.append(Unavailable(self.name, "history does not cover the season", region))
                continue
            if in_season.all():
                out.append(
                    Unavailable(
                        self.name, "history does not cover months outside the season", region
                    )
                )
                continue
            s0, s1 = _latest_run(t[mine][in_season])
            test = in_season.index[in_season & (t[mine] >= s0) & (t[mine] <= s1)]
            keep = (t < s0 - purge) | (t > s1 + embargo)
            train = frame.index[keep]
            if not (frame.loc[train, "region_id"] == region).any():
                out.append(
                    Unavailable(
                        self.name, "no training rows from this region outside the season", region
                    )
                )
                continue
            fit, cal = (
                self.calibration.carve(frame, train) if self.calibration else (train, pd.Index([]))
            )
            out.append(
                Fold(
                    self.name,
                    f"season-{region}",
                    fit=fit,
                    calibration=cal,
                    test=test,
                    regions=(region,),
                    detail=(
                        f"held out {s0.isoformat()}..{s1.isoformat()} "
                        f"(local months {sorted(months)}), purge {purge}, embargo {embargo}"
                    ),
                )
            )
        return out


def _latest_run(times: pd.Series) -> tuple[pd.Timestamp, pd.Timestamp]:
    ordered = times.sort_values()
    breaks = ordered.diff() > _SEASON_GAP
    run = breaks.cumsum()
    latest = ordered[run == run.iloc[-1]]
    return latest.iloc[0], latest.iloc[-1]


def default_strategies(
    *,
    season_months: Mapping[str, frozenset[int]],
    timezones: Mapping[str, str],
    n_folds: int = DEFAULT_FOLDS,
    calibration: CalibrationSplit | None = None,
) -> Sequence[EvaluationStrategy]:
    """The three strategies of LLD APAC 7.5, sharing one calibration rule."""
    return (
        PurgedRollingOrigin(n_folds=n_folds, calibration=calibration),
        LeaveRegionOut(calibration=calibration),
        SeasonCheck(season_months, timezones, calibration=calibration),
    )
