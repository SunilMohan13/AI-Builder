"""Timescale-backed API event reader contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aeropulse_api.demo_seed import HERO_EVENT_ID, seed_replay_episode
from aeropulse_api.event_store import (
    InMemoryEventReader,
    ReplayFallbackEventReader,
    TimescaleEventReader,
    reset_event_store,
)
from aeropulse_contracts.event import EventSeverity, EventStatus, PollutionEvent

NOW = datetime(2026, 9, 14, 5, 0, tzinfo=UTC)


def _event() -> PollutionEvent:
    return PollutionEvent(
        event_id="evt_test",
        status=EventStatus.ACTIVE,
        severity=EventSeverity.HIGH,
        created_at=NOW,
        updated_at=NOW,
        grid_ids=["grid_a"],
        detection_confidence=0.9,
        source_confidence=0.7,
        forecast_confidence=0.8,
        impact_confidence=0.6,
        overall_confidence=0.82,
        evidence_ids=["evd_1"],
        model_versions=["baseline-idw-0.1"],
        evidence_freshness=0.95,
        sensor_coverage=0.8,
    )


class _Cursor:
    def __init__(self, responses: dict[str, list[tuple[Any, ...]]]) -> None:
        self.responses = responses
        self.rows: list[tuple[Any, ...]] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: Any) -> None:
        normalized = " ".join(sql.split())
        for marker, rows in self.responses.items():
            if marker in normalized:
                self.rows = rows
                return
        raise AssertionError(f"unexpected SQL: {normalized}")

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class _Connection:
    def __init__(self, responses: dict[str, list[tuple[Any, ...]]]) -> None:
        self.responses = responses

    def cursor(self) -> _Cursor:
        return _Cursor(self.responses)


def test_timescale_reader_reconstructs_all_event_contracts() -> None:
    payload = _event().model_dump(mode="json")
    responses = {
        "SELECT count(*) FROM pollution_event": [(1,)],
        "SELECT payload FROM pollution_event WHERE status": [(payload,)],
        "SELECT payload FROM pollution_event WHERE event_id": [(payload,)],
        "FROM event_evidence": [
            ("evd_1", "cpcb_anomaly", "obs_1", "grid_a", "High PM2.5", 0.9, NOW)
        ],
        "FROM forecast_value": [
            (NOW, "grid_a", "grid_a", 0, 180.0, 0.9, "wind-advection-0.1", False),
            (NOW, "grid_a", "grid_b", 3, 160.0, 0.8, "wind-advection-0.1", False),
        ],
        "FROM evidence_edge": [
            ("edge_1", "supports", "evd_1", "evt_test", 0.9, ["evd_1"], "baseline-idw-0.1", NOW)
        ],
    }
    reader = TimescaleEventReader(_Connection(responses))

    events, total = reader.list_events(EventStatus.ACTIVE, limit=10, offset=0)
    event = reader.get_event("evt_test")
    evidence = reader.get_evidence("evt_test")
    forecast = reader.get_forecast("evt_test")
    graph = reader.get_graph("evt_test")

    assert total == 1
    assert events == [_event()]
    assert event == _event()
    assert evidence[0].evidence_id == "evd_1"
    assert evidence[0].created_at == NOW
    assert forecast is not None
    assert forecast.horizons == [3]
    assert [cell.grid_id for cell in forecast.grid_predictions] == ["grid_a", "grid_b"]
    assert graph is not None
    assert graph.edges[0].edge_id == "edge_1"
    assert {vertex.id for vertex in graph.vertices} == {"evd_1", "evt_test"}


def test_timescale_reader_returns_none_for_missing_related_records() -> None:
    reader = TimescaleEventReader(
        _Connection(
            {
                "SELECT payload FROM pollution_event WHERE event_id": [],
                "FROM forecast_value": [],
                "FROM evidence_edge": [],
            }
        )
    )

    assert reader.get_event("missing") is None
    assert reader.get_forecast("missing") is None
    assert reader.get_graph("missing") is None


class _EmptyTimescale:
    """Timescale stand-in whose events table has no rows."""

    def list_events(
        self, status: EventStatus | None, limit: int | None, offset: int
    ) -> tuple[list[PollutionEvent], int]:
        return [], 0

    def get_event(self, event_id: str) -> PollutionEvent | None:
        return None

    def get_evidence(self, event_id: str) -> list:
        return []

    def get_forecast(self, event_id: str):
        return None

    def get_graph(self, event_id: str):
        return None


def test_replay_fallback_serves_hero_when_timescale_is_empty() -> None:
    reset_event_store()
    seed_replay_episode()
    reader = ReplayFallbackEventReader(_EmptyTimescale(), InMemoryEventReader())

    items, total = reader.list_events(None, 10, 0)
    assert total >= 5
    assert {event.event_id for event in items} >= {HERO_EVENT_ID}
    assert reader.get_event(HERO_EVENT_ID) is not None
    assert reader.get_evidence(HERO_EVENT_ID)
    assert reader.get_forecast(HERO_EVENT_ID) is not None


def test_replay_fallback_keeps_timescale_when_it_has_events() -> None:
    payload = _event()
    primary = TimescaleEventReader(
        _Connection(
            {
                "SELECT count(*) FROM pollution_event": [(1,)],
                "SELECT payload FROM pollution_event ORDER": [(payload.model_dump(mode="json"),)],
                "SELECT payload FROM pollution_event WHERE event_id": [
                    (payload.model_dump(mode="json"),)
                ],
            }
        )
    )
    reset_event_store()
    seed_replay_episode()
    reader = ReplayFallbackEventReader(primary, InMemoryEventReader())

    items, total = reader.list_events(None, 10, 0)
    assert total == 1
    assert items[0].event_id == "evt_test"
    assert {event.event_id for event in items} == {"evt_test"}
    assert reader.get_event("evt_test") is not None
