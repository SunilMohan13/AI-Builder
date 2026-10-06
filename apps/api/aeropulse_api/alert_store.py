"""Read alerts raised by the event engine.

Alerts are produced worker-side and were previously only ever held in that
process's ``EventStore``. The API read its *own* in-process store, which
nothing populates, so ``GET /api/v1/alerts`` returned an empty list in every
deployment and the UI notification drawer was permanently empty in Live.

This follows the same reader + replay-fallback shape as ``grid_store`` and
``map_store``: Timescale when it has rows, the seeded in-memory store
otherwise, so the demo keeps working with no database.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any, Protocol

from aeropulse_common.settings import get_settings
from aeropulse_contracts.alert import Alert
from aeropulse_observability.logging import get_logger
from fastapi import HTTPException

from aeropulse_api.event_store import current_store

logger = get_logger("aeropulse.api.alerts")

SELECT_ALERTS = """
SELECT alert_id, event_id, severity, recipient_group, message_template,
       message, evidence, channel, created_at, expires_at
FROM alert
ORDER BY created_at DESC
LIMIT %s OFFSET %s
"""

COUNT_ALERTS = "SELECT count(*) FROM alert"


class AlertReader(Protocol):
    """Read contract for raised alerts."""

    def list_alerts(self, limit: int | None, offset: int) -> tuple[list[Alert], int]: ...


class InMemoryAlertReader:
    """Reads the process-global store the demo seed populates."""

    def list_alerts(self, limit: int | None, offset: int) -> tuple[list[Alert], int]:
        """Return a page of alerts, newest first."""
        alerts = sorted(current_store().alerts.values(), key=lambda a: a.created_at, reverse=True)
        total = len(alerts)
        window = alerts[offset : offset + limit] if limit is not None else alerts[offset:]
        return window, total


class TimescaleAlertReader:
    """Reads alerts the worker persisted."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def list_alerts(self, limit: int | None, offset: int) -> tuple[list[Alert], int]:
        """Return a page of persisted alerts, newest first."""
        with self.connection.cursor() as cursor:
            cursor.execute(COUNT_ALERTS)
            row = cursor.fetchone()
            total = int(row[0]) if row else 0
            cursor.execute(SELECT_ALERTS, (limit if limit is not None else total or 1, offset))
            rows = cursor.fetchall()
        return [_to_alert(r) for r in rows], total


def _to_alert(row: Any) -> Alert:
    return Alert(
        alert_id=row[0],
        event_id=row[1],
        severity=row[2],
        recipient_group=row[3],
        message_template=row[4],
        message=row[5],
        evidence=row[6] or [],
        channel=row[7],
        created_at=row[8],
        expires_at=row[9],
    )


class ReplayFallbackAlertReader:
    """Serves Timescale when it holds alerts, the seeded store otherwise."""

    def __init__(self, primary: AlertReader, fallback: AlertReader) -> None:
        self.primary = primary
        self.fallback = fallback
        self._use_fallback: bool | None = None

    def _source(self) -> AlertReader:
        if self._use_fallback is None:
            try:
                _, total = self.primary.list_alerts(1, 0)
            except Exception as exc:
                # The alert table arrived in migration 0006, and
                # docker-entrypoint-initdb.d only runs against an empty
                # volume. An un-migrated database must degrade to the seeded
                # store, not 500 the notification drawer.
                logger.warning("alerts.primary_unavailable", error=str(exc))
                self._use_fallback = True
            else:
                self._use_fallback = total == 0
        return self.fallback if self._use_fallback else self.primary

    def list_alerts(self, limit: int | None, offset: int) -> tuple[list[Alert], int]:
        """Delegate to whichever source actually has alerts."""
        return self._source().list_alerts(limit, offset)


def get_alert_reader() -> Generator[AlertReader, None, None]:
    """Provide the request-scoped alert reader."""
    database_url = get_settings().database_url
    if not database_url:
        yield InMemoryAlertReader()
        return
    try:
        import psycopg

        connection = psycopg.connect(database_url)
    except Exception as exc:
        logger.warning("alerts.database_unavailable", error=str(exc))
        raise HTTPException(status_code=503, detail="Alert database unavailable") from exc
    try:
        yield ReplayFallbackAlertReader(TimescaleAlertReader(connection), InMemoryAlertReader())
    finally:
        connection.close()
