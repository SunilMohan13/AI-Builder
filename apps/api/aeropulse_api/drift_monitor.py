"""Periodic feature and prediction distribution drift monitor.

The scheduling half of drift monitoring: a long-running process that sweeps
every whitelisted signal on an interval. The sweep itself is
:func:`aeropulse_ml.drift_monitor.evaluate_drift` — this module deliberately
does not reimplement it. Two copies of "compare a recent window against a
reference window" would disagree the first time either changed, and the
comparison geometry is exactly the kind of detail that drifts apart
unnoticed.

`aeropulse-ml drift` runs the same sweep once, for an operator who wants an
answer now rather than on the hour.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from aeropulse_common.settings import Settings, get_settings
from aeropulse_ml.drift_monitor import evaluate_drift
from aeropulse_observability.logging import configure_logging, get_logger

from aeropulse_api.drift_store import DRIFT_SIGNALS, DriftReader, TimescaleDriftReader

logger = get_logger("aeropulse.drift_monitor")


def monitor_once(
    reader: DriftReader, settings: Settings, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Evaluate every supported signal once and log actionable shifts.

    Args:
        reader: Source of windowed signal values.
        settings: Supplies the window geometry and sample bounds.
        now: End of the current window. Defaults to the wall clock.

    Returns:
        One record per signal, carrying the status and the full metric
        payload. Returned as plain dicts so the shape stays stable for
        whatever consumes the log stream.
    """
    report = evaluate_drift(
        reader,
        list(DRIFT_SIGNALS),
        now=now or datetime.now(UTC),
        current_hours=settings.drift_monitor_current_hours,
        reference_hours=settings.drift_monitor_reference_hours,
        limit=settings.drift_monitor_max_samples,
        min_samples=settings.drift_monitor_min_samples,
    )

    results: list[dict[str, Any]] = []
    for finding in report.findings:
        record = {"signal": finding.signal, "status": finding.status, **finding.detail}
        results.append(record)
        if finding.alerting:
            logger.warning("drift.monitor.alert", **record)
        elif finding.status == "INSUFFICIENT_DATA":
            logger.info("drift.monitor.insufficient_data", **record)
        else:
            logger.info("drift.monitor.stable", **record)
    return results


def main() -> None:
    """Run drift scans at the configured interval while the process is alive."""
    settings = get_settings()
    settings.service_name = "aeropulse-drift-monitor"  # type: ignore[misc]
    configure_logging(settings)
    if not settings.database_url:
        logger.error("drift.monitor.database_not_configured")
        return
    while True:
        try:
            import psycopg

            with psycopg.connect(settings.database_url) as connection:
                monitor_once(TimescaleDriftReader(connection), settings)
        except Exception:
            # A failed scan must not kill the daemon: the next interval may
            # well succeed, and an exited monitor is a silent monitor.
            logger.exception("drift.monitor.failed")
        time.sleep(settings.drift_monitor_interval_seconds)
