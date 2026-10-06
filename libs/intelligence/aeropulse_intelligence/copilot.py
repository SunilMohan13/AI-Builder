"""Evidence-grounded copilot. Does not call an LLM (LLD section 24.3)."""

from __future__ import annotations

from typing import cast

from aeropulse_contracts.copilot import CopilotConfidence, CopilotResponse
from aeropulse_contracts.event import EventEvidence, PollutionEvent
from aeropulse_contracts.forecast import ForecastResult

from aeropulse_intelligence.engine import EventStore

LIMITATIONS = [
    "AOD is not treated as surface PM2.5.",
    "Source scores are independent likelihoods, not proven causality.",
    "Forecast is kinematic wind-advection-0.1; CAMS is not applied.",
    "Copilot did not use an LLM; all numbers come from retrieved evidence.",
    "Citizen reports cannot independently create a HIGH event.",
]


def _lookup_event(store: object, event_id: str) -> PollutionEvent | None:
    """Read one event from an EventStore or EventReader."""
    getter = getattr(store, "get_event", None)
    if callable(getter):
        return cast(PollutionEvent | None, getter(event_id))
    events = getattr(store, "events", None)
    if isinstance(events, dict):
        return cast(PollutionEvent | None, events.get(event_id))
    return None


def _lookup_evidence(store: object, event_id: str) -> list[EventEvidence]:
    """Read evidence from an EventStore or EventReader."""
    getter = getattr(store, "get_evidence", None)
    if callable(getter):
        return list(cast(list[EventEvidence], getter(event_id) or []))
    evidence = getattr(store, "evidence", None)
    if isinstance(evidence, dict):
        return list(cast(list[EventEvidence], evidence.get(event_id, [])))
    return []


def _lookup_forecast(store: object, event_id: str) -> ForecastResult | None:
    """Read a forecast from an EventStore or EventReader."""
    getter = getattr(store, "get_forecast", None)
    if callable(getter):
        return cast(ForecastResult | None, getter(event_id))
    forecasts = getattr(store, "forecasts", None)
    if isinstance(forecasts, dict):
        return cast(ForecastResult | None, forecasts.get(event_id))
    return None


def _list_events(store: object) -> list[PollutionEvent]:
    """List events from an EventStore or EventReader."""
    lister = getattr(store, "list_events", None)
    if callable(lister):
        items, _total = cast(tuple[list[PollutionEvent], int], lister(None, None, 0))
        return list(items)
    events = getattr(store, "events", None)
    if isinstance(events, dict):
        return list(cast(dict[str, PollutionEvent], events).values())
    return []


def explain_event(store: EventStore | object, event_id: str) -> CopilotResponse:
    """Build a copilot.v1 payload strictly from stored event/forecast/evidence.

    Accepts the in-memory ``EventStore`` or an ``EventReader`` (Timescale).
    """
    event = _lookup_event(store, event_id)
    if event is None:
        return CopilotResponse(
            answer=f"No event found for id {event_id}.",
            limitations=LIMITATIONS,
            llm_used=False,
        )
    evidence = _lookup_evidence(store, event_id)
    forecast = _lookup_forecast(store, event_id)
    facts = _observed_facts(event, evidence)
    predicted = _predicted(forecast)
    sources = _sources(event)
    actions = _actions(event)
    answer = (
        f"Event {event.event_id} is {event.status.value} ({event.severity.value}). "
        f"Detection confidence {event.detection_confidence:.2f}; "
        f"source likelihood confidence {event.source_confidence:.2f}; "
        f"overall {event.overall_confidence:.2f}."
    )
    payload = CopilotResponse(
        answer=answer,
        observed_facts=facts,
        predicted_conditions=predicted,
        likely_sources=sources,
        confidence=CopilotConfidence(
            detection=event.detection_confidence,
            source=event.source_confidence,
            forecast=event.forecast_confidence,
            overall=event.overall_confidence,
        ),
        evidence=[e.model_dump(mode="json") for e in evidence],
        recommended_actions=actions,
        limitations=LIMITATIONS,
        llm_used=False,
    )
    return payload


def query_store(store: EventStore | object, question: str) -> CopilotResponse:
    """Retrieve events matching keywords; never invent readings."""
    q = question.lower()
    events = _list_events(store)
    if not events:
        return CopilotResponse(
            answer="No pollution events are currently in the store.",
            limitations=LIMITATIONS,
        )
    if "explain" in q or "event" in q:
        event_id = events[0].event_id
        for item in events:
            if item.event_id.lower() in q:
                event_id = item.event_id
                break
        return explain_event(store, event_id)
    open_events = [e for e in events if e.status.value not in {"RESOLVED", "REJECTED"}]
    answer = f"{len(open_events)} open event(s) in the store. Ask to explain a specific event_id."
    return CopilotResponse(
        answer=answer,
        observed_facts=[f"{e.event_id}:{e.status.value}" for e in open_events],
        limitations=LIMITATIONS,
        llm_used=False,
    )


def _observed_facts(event: PollutionEvent, evidence: list[EventEvidence]) -> list[str]:
    facts = [
        f"status={event.status.value}",
        f"severity={event.severity.value}",
        f"grid_ids={','.join(event.grid_ids)}",
        f"pollutants={','.join(event.pollutants)}",
        f"feature_version={event.feature_version}",
        f"model_versions={','.join(event.model_versions)}",
    ]
    facts.extend(f"{item.evidence_type}: {item.summary}" for item in evidence)
    return facts


def _predicted(forecast: ForecastResult | None) -> list[str]:
    if forecast is None:
        return []
    out = [f"model={forecast.model_version}", f"cams_applied={forecast.cams_applied}"]
    for cell in forecast.grid_predictions[:6]:
        out.append(f"grid={cell.grid_id} pm25={cell.pm25} confidence={cell.confidence}")
    return out


def _sources(event: PollutionEvent) -> list[dict]:
    return [
        {
            "note": "Independent likelihoods from source-likelihood-0.1; not causality.",
            "source_confidence": event.source_confidence,
        }
    ]


def _actions(event: PollutionEvent) -> list[str]:
    if event.severity.value in {"HIGH", "CRITICAL"}:
        return [
            "Investigate corroborating CPCB stations and FIRMS detections in the evidence list.",
            "Do not treat source likelihood as proven causation.",
        ]
    return ["Continue monitoring source freshness and quality scores."]
