"""Alerts must reach the API.

The event engine raised alerts into the worker's in-process store, and the
API read its own store, which nothing populates. `GET /api/v1/alerts`
therefore returned an empty list in every deployment and the UI notification
drawer was permanently empty in Live.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from aeropulse_api.alert_store import (
    InMemoryAlertReader,
    ReplayFallbackAlertReader,
    TimescaleAlertReader,
)
from aeropulse_api.demo_seed import seed_replay_episode
from aeropulse_api.event_store import current_store
from aeropulse_contracts.alert import Alert
from aeropulse_intelligence.engine import EventStore

NOW = datetime(2026, 9, 8, 6, 0, tzinfo=UTC)


def _alert(alert_id: str, *, created_at: datetime, severity: str = "high") -> Alert:
    return Alert(
        alert_id=alert_id,
        event_id="EVT-1024",
        severity=severity,
        message=f"{severity.upper()} pollution event",
        created_at=created_at,
    )


class _Cursor:
    def __init__(self, rows: list[tuple[Any, ...]], calls: list[tuple[str, Any]]) -> None:
        self._rows = rows
        self._calls = calls
        self._last = ""

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self._last = sql
        self._calls.append((sql, params))

    def fetchone(self):
        return (len(self._rows),)

    def fetchall(self):
        return self._rows


class _Connection:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, Any]] = []

    def cursor(self):
        return _Cursor(self.rows, self.calls)


class _Exploding:
    """Stands in for a database where migration 0006 has not run."""

    def list_alerts(self, limit: int | None, offset: int):
        raise RuntimeError('relation "alert" does not exist')


# --- the seed populates alerts ---


def test_demo_seed_raises_alerts_for_high_severity_events() -> None:
    store = EventStore()
    seed_replay_episode(store)

    assert store.alerts, "seeded HIGH/CRITICAL events must raise alerts"
    severities = {a.severity for a in store.alerts.values()}
    assert severities <= {"high", "critical"}


def test_in_memory_reader_returns_newest_first() -> None:
    seed_replay_episode()
    store = current_store()
    reader = InMemoryAlertReader()

    alerts, total = reader.list_alerts(None, 0)

    assert total == len(store.alerts)
    assert total > 0
    times = [a.created_at for a in alerts]
    assert times == sorted(times, reverse=True)


def test_in_memory_reader_paginates() -> None:
    seed_replay_episode()
    reader = InMemoryAlertReader()

    _, total = reader.list_alerts(None, 0)
    first, _ = reader.list_alerts(1, 0)
    second, _ = reader.list_alerts(1, 1)

    assert len(first) == 1
    if total > 1:
        assert first[0].alert_id != second[0].alert_id


# --- Timescale reader ---


def test_timescale_reader_maps_rows_to_alerts() -> None:
    connection = _Connection(
        [
            (
                "al_1",
                "EVT-1024",
                "critical",
                "operators",
                "pollution_event_high",
                "CRITICAL pollution event",
                [{"evidence_id": "ev_1", "type": "cpcb_anomaly"}],
                "log",
                NOW,
                NOW + timedelta(hours=12),
            )
        ]
    )

    alerts, total = TimescaleAlertReader(connection).list_alerts(10, 0)

    assert total == 1
    assert alerts[0].alert_id == "al_1"
    assert alerts[0].severity == "critical"
    assert alerts[0].evidence[0]["type"] == "cpcb_anomaly"
    assert "ORDER BY created_at DESC" in connection.calls[1][0]


# --- fallback policy ---


def test_fallback_is_used_when_the_database_has_no_alerts() -> None:
    seed_replay_episode()
    reader = ReplayFallbackAlertReader(TimescaleAlertReader(_Connection([])), InMemoryAlertReader())

    _, total = reader.list_alerts(None, 0)

    assert total > 0, "an empty table must fall back to the seeded store"


def test_an_unmigrated_database_degrades_instead_of_raising() -> None:
    """Migration 0006 only runs against an empty volume, so this happens."""
    reader = ReplayFallbackAlertReader(_Exploding(), InMemoryAlertReader())

    alerts, total = reader.list_alerts(None, 0)

    assert isinstance(alerts, list)
    assert total >= 0


def test_persisted_alerts_win_over_the_seed() -> None:
    connection = _Connection(
        [
            (
                "al_live",
                "EVT-9001",
                "high",
                "operators",
                "pollution_event_high",
                "live alert",
                [],
                "log",
                NOW,
                None,
            )
        ]
    )
    reader = ReplayFallbackAlertReader(TimescaleAlertReader(connection), InMemoryAlertReader())

    alerts, _ = reader.list_alerts(10, 0)

    assert alerts[0].alert_id == "al_live"
