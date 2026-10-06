"""Copilot APIs (LLD section 25.4).

Gemini answers by calling AeroPulse tools; it is never handed raw data and
cannot state a number a tool did not return. A grounding check runs before
anything reaches the caller, and a failure degrades to deterministic
retrieval rather than shipping an unvalidated figure. ``llm_used`` therefore
reports what actually happened.

This supersedes ADR-0006's "llm_used is always false", but keeps its
requirement: the validator that rejects ungrounded numbers is what makes the
model safe to put in front of this data. The event-detection path remains
deterministic and LLM-free.
"""

from aeropulse_auth.jwt import TokenClaims
from aeropulse_contracts.copilot import (
    CopilotGrounding,
    CopilotResponse,
    CopilotToolCall,
)
from aeropulse_intelligence.copilot import explain_event
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from aeropulse_api.copilot_service import build_tool_context, get_copilot_service
from aeropulse_api.deps import get_claims
from aeropulse_api.event_store import get_event_reader
from aeropulse_api.grid_store import get_grid_reader
from aeropulse_api.map_store import get_map_reader

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])


class CopilotTurn(BaseModel):
    """One prior message, so a follow-up question has context."""

    model_config = {"extra": "forbid"}

    role: str = Field(..., pattern="^(user|assistant)$")
    text: str = Field(..., min_length=1)


class CopilotQuery(BaseModel):
    """Natural-language question, optionally with conversation history."""

    question: str = Field(..., min_length=1, max_length=2000)
    history: list[CopilotTurn] = Field(default_factory=list, max_length=20)


class ExplainBody(BaseModel):
    """Explain a stored event by id."""

    event_id: str


def _answer(body: CopilotQuery, grid, map_reader, events) -> CopilotResponse:
    service = get_copilot_service()
    ctx = build_tool_context(grid, map_reader, events)
    result = service.ask(
        body.question,
        ctx,
        history=[{"role": t.role, "text": t.text} for t in body.history],
    )
    return CopilotResponse(
        answer=result.answer,
        evidence=result.evidence,
        limitations=result.limitations,
        llm_used=result.llm_used,
        model=result.model,
        tool_calls=[
            CopilotToolCall(name=c["name"], arguments=c["arguments"]) for c in result.tool_calls
        ],
        grounding=CopilotGrounding(grounded=result.grounded),
        degraded_reason=result.degraded_reason,
    )


@router.post("/query", response_model=CopilotResponse)
def copilot_query(
    body: CopilotQuery,
    _claims: TokenClaims = Depends(get_claims),
    grid=Depends(get_grid_reader),
    map_reader=Depends(get_map_reader),
    events=Depends(get_event_reader),
) -> CopilotResponse:
    """Answer a question using tool lookups over live intelligence."""
    return _answer(body, grid, map_reader, events)


@router.post("/investigate", response_model=CopilotResponse)
def copilot_investigate(
    body: CopilotQuery,
    _claims: TokenClaims = Depends(get_claims),
    grid=Depends(get_grid_reader),
    map_reader=Depends(get_map_reader),
    events=Depends(get_event_reader),
) -> CopilotResponse:
    """Same grounded path as query, kept for the investigate intent."""
    return _answer(body, grid, map_reader, events)


@router.post("/explain-event", response_model=CopilotResponse)
def copilot_explain(
    body: ExplainBody,
    _claims: TokenClaims = Depends(get_claims),
    events=Depends(get_event_reader),
) -> CopilotResponse:
    """Explain one event from stored evidence, forecast and confidence.

    Deterministic by design: this endpoint restates what the event engine
    recorded, so there is nothing for a model to add and no reason to pay
    for one. Reads the same EventReader as query/investigate (Timescale when
    configured), not the in-memory seed.
    """
    return explain_event(events, body.event_id)
