"""Copilot must not invent numbers (LLD section 24.3)."""

from datetime import UTC, datetime

from aeropulse_contracts.event import EventSeverity, EventStatus, PollutionEvent
from aeropulse_intelligence.copilot import explain_event, query_store
from aeropulse_intelligence.engine import EventStore


def test_explain_unknown_event() -> None:
    store = EventStore()
    result = explain_event(store, "missing")
    assert result.llm_used is False
    assert "No event found" in result.answer
    assert result.observed_facts == []


def test_explain_copies_event_confidence() -> None:
    store = EventStore()
    event = PollutionEvent(
        event_id="evt_c",
        status=EventStatus.ACTIVE,
        severity=EventSeverity.HIGH,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        grid_ids=["g1"],
        detection_confidence=0.81,
        source_confidence=0.44,
        forecast_confidence=0.0,
        impact_confidence=0.0,
        overall_confidence=0.6,
        evidence_freshness=1.0,
        sensor_coverage=0.5,
        model_versions=["baseline-idw-0.1"],
    )
    store.events[event.event_id] = event
    result = explain_event(store, "evt_c")
    assert result.confidence.detection == 0.81
    assert result.confidence.source == 0.44
    assert result.llm_used is False
    assert any(
        "causality" in line.lower() or "likelihood" in line.lower() for line in result.limitations
    )


def test_query_empty_store() -> None:
    result = query_store(EventStore(), "what is happening?")
    assert result.llm_used is False
    assert "No pollution events" in result.answer


class _Reader:
    def __init__(self, event: PollutionEvent) -> None:
        self._event = event

    def list_events(self, status, limit, offset):
        return [self._event], 1

    def get_event(self, event_id: str) -> PollutionEvent | None:
        return self._event if event_id == self._event.event_id else None

    def get_evidence(self, event_id: str) -> list:
        return []

    def get_forecast(self, event_id: str):
        return None


def test_explain_event_reads_an_event_reader_not_only_the_in_memory_store() -> None:
    event = PollutionEvent(
        event_id="evt_live",
        status=EventStatus.ACTIVE,
        severity=EventSeverity.HIGH,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        grid_ids=["g1"],
        detection_confidence=0.7,
        source_confidence=0.5,
        forecast_confidence=0.4,
        impact_confidence=0.0,
        overall_confidence=0.6,
        evidence_freshness=1.0,
        sensor_coverage=0.5,
        model_versions=["baseline-idw-0.1"],
    )
    result = explain_event(_Reader(event), "evt_live")
    assert "evt_live" in result.answer
    assert result.confidence.detection == 0.7
