"""Scheduled drift sweep (LLD §46, gap analysis P1-12).

On-demand drift already existed. What was missing is the thing that runs when
nobody is looking, so these tests focus on the sweep's operational
properties: it must not be stopped by one unreadable signal, and it must not
report "stable" for a signal it could not actually evaluate.
"""

from __future__ import annotations

from datetime import UTC, datetime

from aeropulse_ml.drift_monitor import (
    ALERTING_STATUSES,
    DriftFinding,
    evaluate_drift,
)

NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)


class _SimpleReader:
    """Explicit two-window reader, avoiding date arithmetic in the stub."""

    def __init__(self, reference: list[float], current: list[float]) -> None:
        self.reference = reference
        self.current = current
        self.seen: list[str] = []

    def values(self, signal, start, end, grid_id, model_version, limit):  # type: ignore[no-untyped-def]
        self.seen.append(signal)
        # First call per signal is the reference window, second the current.
        return self.reference if self.seen.count(signal) == 1 else self.current


def test_a_stable_signal_raises_no_alert() -> None:
    """Identical distributions must not page anyone."""
    values = [50.0 + (i % 10) for i in range(200)]
    reader = _SimpleReader(values, list(values))

    report = evaluate_drift(reader, ["feature.pm25"], now=NOW)

    assert report.findings[0].status == "STABLE"
    assert report.alerts == []


def test_a_shifted_distribution_alerts() -> None:
    """A feed that changes units or scale must be caught."""
    reference = [50.0 + (i % 10) for i in range(200)]
    current = [500.0 + (i % 10) for i in range(200)]
    reader = _SimpleReader(reference, current)

    report = evaluate_drift(reader, ["feature.pm25"], now=NOW)

    finding = report.findings[0]
    assert finding.status in ALERTING_STATUSES
    assert finding.alerting is True
    assert report.alerts == [finding]


def test_insufficient_data_is_not_reported_as_stable() -> None:
    """A signal that stopped flowing must not look healthy."""
    reader = _SimpleReader([1.0, 2.0], [3.0, 4.0])

    report = evaluate_drift(reader, ["feature.pm25"], now=NOW)

    finding = report.findings[0]
    assert finding.status == "INSUFFICIENT_DATA"
    assert finding.alerting is False
    # Surfaced separately so it cannot be mistaken for a clean result.
    assert report.unevaluated == [finding]
    assert report.to_dict()["unevaluated"] == 1


def test_one_unreadable_signal_does_not_abort_the_sweep() -> None:
    """Otherwise a single bad column hides drift in every other."""
    values = [50.0 + (i % 10) for i in range(200)]
    drifted = [900.0 + (i % 10) for i in range(200)]

    class _PartlyBroken:
        def __init__(self) -> None:
            self.seen: list[str] = []

        def values(self, signal, start, end, grid_id, model_version, limit):  # type: ignore[no-untyped-def]
            if signal == "feature.pm10":
                raise RuntimeError("column does not exist")
            self.seen.append(signal)
            return values if self.seen.count(signal) == 1 else drifted

    report = evaluate_drift(
        _PartlyBroken(),
        ["feature.pm10", "feature.pm25", "feature.wind_speed"],
        now=NOW,
    )

    assert len(report.findings) == 3
    broken = next(f for f in report.findings if f.signal == "feature.pm10")
    assert broken.status == "INSUFFICIENT_DATA"
    assert "RuntimeError" in broken.detail["error"]
    # The other two were still evaluated, and their drift was found.
    assert {f.signal for f in report.alerts} == {"feature.pm25", "feature.wind_speed"}


def test_windows_are_adjacent_and_non_overlapping() -> None:
    """Overlapping windows would compare a period against itself."""
    reader = _SimpleReader([1.0] * 100, [1.0] * 100)

    report = evaluate_drift(
        reader, ["feature.pm25"], now=NOW, current_hours=24, reference_hours=168
    )

    ref_start, ref_end = report.reference_window
    cur_start, cur_end = report.current_window
    assert ref_end == cur_start
    assert cur_end == NOW
    assert (cur_end - cur_start).total_seconds() == 24 * 3600
    assert (ref_end - ref_start).total_seconds() == 168 * 3600


def test_report_states_its_own_limitations() -> None:
    """Distribution drift is not error drift, and the payload must say so."""
    reader = _SimpleReader([1.0] * 100, [1.0] * 100)

    payload = evaluate_drift(reader, ["feature.pm25"], now=NOW).to_dict()

    assert any("error drift" in line for line in payload["limitations"])
    assert any("seasonality" in line for line in payload["limitations"])


def test_finding_alerting_flag_matches_the_status_set() -> None:
    for status in ("STABLE", "INSUFFICIENT_DATA"):
        assert not DriftFinding(
            signal="s", status=status, psi=None, ks_statistic=None, reference_n=0, current_n=0
        ).alerting
    for status in ("WARNING", "DRIFT"):
        assert DriftFinding(
            signal="s", status=status, psi=1.0, ks_statistic=1.0, reference_n=99, current_n=99
        ).alerting
