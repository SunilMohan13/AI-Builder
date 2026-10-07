"""Evaluation strategies, metrics, baselines and local time (LLD APAC 7.5)."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from aeropulse_ml.baselines import AboveThreshold, ColumnBaseline, HourOfWeekClimatology
from aeropulse_ml.evaluation import (
    CalibrationSplit,
    Fold,
    LeaveRegionOut,
    PurgedRollingOrigin,
    SeasonCheck,
    Unavailable,
    alert_metrics,
    choose_operating_threshold,
    expected_calibration_error,
    interval_coverage,
    skill,
)
from aeropulse_ml.features.local_time import local_hour, local_hour_of_week
from aeropulse_ml.training import aggregate

START = pd.Timestamp("2026-01-01T00:00Z")


def _frame(hours: int, regions: tuple[str, ...] = ("a",), horizon: float | None = 24.0):
    rows = []
    for region in regions:
        for k in range(hours):
            rows.append(
                {
                    "region_id": region,
                    "cell": f"{region}-1",
                    "t": START + pd.Timedelta(hours=k),
                    "y": float(k % 2),
                    **({"horizon_hours": horizon} if horizon is not None else {}),
                }
            )
    return pd.DataFrame(rows)


def _folds(items: list[Fold | Unavailable]) -> list[Fold]:
    return [f for f in items if isinstance(f, Fold)]


# --- strategies ------------------------------------------------------------


def test_rolling_origin_trains_strictly_before_test_minus_purge() -> None:
    frame = _frame(24 * 30)
    folds = _folds(PurgedRollingOrigin(n_folds=5).folds(frame))
    assert len(folds) == 5
    for fold in folds:
        train_end = frame.loc[fold.fit, "t"].max()
        test_start = frame.loc[fold.test, "t"].min()
        assert train_end < test_start - pd.Timedelta(hours=24)
        assert not set(fold.fit) & set(fold.test)
    starts = [frame.loc[f.test, "t"].min() for f in folds]
    assert starts == sorted(starts)


def test_rolling_origin_purge_follows_the_longest_label_horizon() -> None:
    frame = _frame(24 * 30, horizon=48.0)
    fold = _folds(PurgedRollingOrigin(n_folds=3).folds(frame))[0]
    gap = frame.loc[fold.test, "t"].min() - frame.loc[fold.fit, "t"].max()
    assert gap > pd.Timedelta(hours=48)


def test_rolling_origin_reports_unavailable_on_empty_rows() -> None:
    items = PurgedRollingOrigin().folds(_frame(0))
    assert isinstance(items[0], Unavailable)


def test_calibration_slice_sits_between_fit_and_test() -> None:
    frame = _frame(24 * 30)
    strategy = PurgedRollingOrigin(n_folds=3, calibration=CalibrationSplit(purge_hours=24))
    for fold in _folds(strategy.folds(frame)):
        assert len(fold.calibration) > 0
        fit_end = frame.loc[fold.fit, "t"].max()
        cal = frame.loc[fold.calibration, "t"]
        test_start = frame.loc[fold.test, "t"].min()
        assert fit_end < cal.min() - pd.Timedelta(hours=24)
        assert cal.max() < test_start - pd.Timedelta(hours=24)


def test_leave_region_out_needs_two_regions_with_labels() -> None:
    items = LeaveRegionOut().folds(_frame(48, regions=("a",)))
    assert isinstance(items[0], Unavailable)
    assert items[0].reason == "only one region has ground truth"
    folds = _folds(LeaveRegionOut().folds(_frame(48, regions=("a", "b"))))
    assert [f.regions for f in folds] == [("a",), ("b",)]
    frame = _frame(48, regions=("a", "b"))
    for fold in folds:
        assert set(frame.loc[fold.test, "region_id"]) == set(fold.regions)
        assert not set(frame.loc[fold.fit, "region_id"]) & set(fold.regions)


def test_season_check_holds_out_the_latest_season_with_purge_and_embargo() -> None:
    frame = _frame(24 * 120)  # Jan..Apr
    check = SeasonCheck({"a": frozenset({2})}, {"a": "UTC"}, purge_hours=24, embargo_hours=48)
    fold = _folds(check.folds(frame))[0]
    test_t = frame.loc[fold.test, "t"]
    assert set(test_t.dt.month) == {2}
    fit_t = frame.loc[fold.fit, "t"]
    assert not (
        (fit_t >= test_t.min() - pd.Timedelta(hours=24))
        & (fit_t <= test_t.max() + pd.Timedelta(hours=48))
    ).any()
    assert (fit_t > test_t.max()).any()


def test_season_check_is_unavailable_when_history_is_all_season() -> None:
    frame = _frame(24 * 10)
    items = SeasonCheck({"a": frozenset({1})}, {"a": "UTC"}).folds(frame)
    assert isinstance(items[0], Unavailable)
    assert "outside the season" in items[0].reason
    items = SeasonCheck({}, {"a": "UTC"}).folds(frame)
    assert isinstance(items[0], Unavailable)
    assert items[0].reason == "region has no seasonal prior"


# --- metrics ---------------------------------------------------------------


def test_ece_is_zero_when_scores_match_frequencies() -> None:
    y = np.array([0] * 50 + [1] * 50)
    assert expected_calibration_error(y, np.full(100, 0.5)) == pytest.approx(0.0)
    assert expected_calibration_error(y, np.r_[np.zeros(50), np.ones(50)]) == pytest.approx(0.0)
    assert expected_calibration_error(y, np.full(100, 0.9)) == pytest.approx(0.4)


def test_operating_threshold_maximises_recall_within_the_false_alert_limit() -> None:
    rng = np.random.default_rng(0)
    y = np.r_[np.zeros(400), np.ones(100)]
    score = np.r_[rng.uniform(0, 0.7, 400), rng.uniform(0.3, 1.0, 100)]
    threshold = choose_operating_threshold(y, score, max_false_alert_rate=0.1)
    assert threshold is not None
    at = alert_metrics(y, score, threshold)
    assert at["false_alert_rate"] <= 0.1
    lower = score[score < threshold].max()
    assert alert_metrics(y, score, lower)["false_alert_rate"] > 0.1


def test_operating_threshold_is_none_for_a_single_class() -> None:
    assert (
        choose_operating_threshold(np.zeros(10), np.linspace(0, 1, 10), max_false_alert_rate=0.1)
        is None
    )


def test_coverage_and_skill() -> None:
    assert interval_coverage([1, 2, 3, 10], [0, 0, 0, 0], [5, 5, 5, 5]) == 0.75
    assert skill(8.0, 10.0) == 0.2
    assert skill(None, 10.0) is None
    assert skill(1.0, 0.0) is None


def test_aggregate_reports_mean_std_and_fold_count() -> None:
    folds = [
        {"h=1": {"model": {"rmse": 1.0, "skill": None}}},
        {"h=1": {"model": {"rmse": 3.0}}},
    ]
    out = aggregate(folds)
    assert out["h=1"]["_folds"] == 2
    assert out["h=1"]["model"]["rmse"] == 2.0
    assert out["h=1"]["model"]["rmse_std"] == pytest.approx(1.414214)
    assert "skill" not in out["h=1"]["model"]


# --- baselines -------------------------------------------------------------


def _encoded(times: pd.Series, tz: str) -> pd.DataFrame:
    local = times.dt.tz_convert(tz)
    hour = local.dt.hour + local.dt.minute / 60.0
    dow = local.dt.dayofweek
    tau = 2 * np.pi
    return pd.DataFrame(
        {
            "sin_hour_local": np.sin(tau * hour / 24),
            "cos_hour_local": np.cos(tau * hour / 24),
            "sin_dow_local": np.sin(tau * dow / 7),
            "cos_dow_local": np.cos(tau * dow / 7),
        }
    )


def test_local_time_round_trips_through_the_cyclic_features() -> None:
    times = pd.Series(pd.date_range("2026-10-05T06:00Z", periods=200, freq="h"))
    for tz in ("Asia/Kolkata", "Australia/Sydney", "Asia/Singapore"):
        enc = _encoded(times, tz)
        local = times.dt.tz_convert(tz)
        expected_hour = local.dt.hour + local.dt.minute / 60.0
        assert np.allclose(local_hour(enc), expected_hour)
        expected_how = local.dt.dayofweek * 24 + local.dt.hour
        assert np.array_equal(local_hour_of_week(enc), expected_how.to_numpy(dtype=float))


def test_climatology_is_fitted_on_training_rows_only() -> None:
    times = pd.Series(pd.date_range("2026-01-05T00:00Z", periods=24 * 35, freq="h"))
    frame = _encoded(times, "UTC")
    frame["region_id"], frame["cell"], frame["t"] = "a", "a-1", times
    frame["horizon_hours"] = 1.0
    # The label of row t is the value at t + 1h: a spike every local midnight.
    frame["pm25_target"] = np.where((times + pd.Timedelta(hours=1)).dt.hour == 0, 100.0, 10.0)
    train, test = frame.iloc[: 24 * 28], frame.iloc[24 * 28 :].copy()
    fitted = HourOfWeekClimatology().fit(train)
    before = fitted.predict(test)
    test["pm25_target"] = -1.0
    assert np.array_equal(fitted.predict(test), before)
    # Valid hour = t + 1h, so rows at 23:00 forecast the 00:00 spike.
    assert np.allclose(before[test["t"].dt.hour.to_numpy() == 23], 100.0)


def test_column_and_threshold_baselines() -> None:
    frame = pd.DataFrame(
        {
            "pm25": [10.0, np.nan, 80.0],
            "pm25_roll_24h": [50.0, 70.0, np.nan],
            "region_threshold_ugm3": [60.0, 60.0, 60.0],
        }
    )
    assert np.allclose(
        ColumnBaseline("p", "pm25").predict(frame), [10.0, np.nan, 80.0], equal_nan=True
    )
    above = AboveThreshold("a", "pm25_roll_24h").predict(frame)
    assert above[0] == 0.0 and above[1] == 1.0 and np.isnan(above[2])


def test_timezones_are_used_for_season_months() -> None:
    # 2026-02-28T20:00Z is already March in Sydney.
    frame = pd.DataFrame(
        {
            "region_id": "a",
            "cell": "a-1",
            "t": pd.date_range(datetime(2026, 1, 1, tzinfo=UTC), periods=24 * 90, freq="h"),
            "horizon_hours": 1.0,
        }
    )
    check = SeasonCheck({"a": frozenset({3})}, {"a": "Australia/Sydney"}, purge_hours=1)
    fold = _folds(check.folds(frame))[0]
    first = frame.loc[fold.test, "t"].min()
    assert first.tz_convert("Australia/Sydney").month == 3
    assert first.month == 2
