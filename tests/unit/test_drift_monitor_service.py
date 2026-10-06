"""The scheduled drift-monitor service (`aeropulse-drift-monitor`).

Covers the daemon wrapper only. The sweep logic it delegates to lives in
`aeropulse_ml.drift_monitor` and is tested in `test_drift_monitor.py`;
duplicating those assertions here would mean two suites guarding one
behaviour and disagreeing the first time it changes.
"""

from datetime import UTC, datetime

from aeropulse_api.drift_monitor import monitor_once
from aeropulse_common.settings import Settings


class _ShiftedReader:
    """Returns one distribution before 14 Sept and a shifted one after."""

    def values(self, signal, start, end, grid_id, model_version, limit):  # type: ignore[no-untyped-def]
        values = range(100) if start.day < 14 else range(100, 200)
        return [float(value) for value in values]


def test_monitor_once_reports_actionable_drift_for_each_signal() -> None:
    settings = Settings(drift_monitor_reference_hours=168, drift_monitor_current_hours=24)

    results = monitor_once(_ShiftedReader(), settings, datetime(2026, 9, 15, tzinfo=UTC))

    assert len(results) == 11
    assert {result["status"] for result in results} == {"DRIFT"}
    assert all(result["reference_n"] == 100 and result["current_n"] == 100 for result in results)


def test_monitor_once_honours_the_configured_windows() -> None:
    """The service's settings must actually reach the sweep.

    A daemon that silently used the sweep's defaults instead of the operator's
    configuration would look healthy while monitoring the wrong period.
    """
    captured: list[tuple] = []

    class _RecordingReader:
        def values(self, signal, start, end, grid_id, model_version, limit):  # type: ignore[no-untyped-def]
            captured.append((start, end, limit))
            return [float(v) for v in range(100)]

    settings = Settings(
        drift_monitor_reference_hours=48,
        drift_monitor_current_hours=6,
        drift_monitor_max_samples=250,
    )
    now = datetime(2026, 9, 15, 12, tzinfo=UTC)

    monitor_once(_RecordingReader(), settings, now)

    reference_start, reference_end, limit = captured[0]
    current_start, current_end, _ = captured[1]
    assert limit == 250
    assert (current_end - current_start).total_seconds() == 6 * 3600
    assert (reference_end - reference_start).total_seconds() == 48 * 3600
    # Adjacent, not overlapping: the reference must end where current begins.
    assert reference_end == current_start
