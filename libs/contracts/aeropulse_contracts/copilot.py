"""Copilot response contract (LLD section 24.2). Numbers must be evidence-grounded."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class CopilotConfidence(BaseModel):
    """Split confidence copied from the event, never invented."""

    model_config = {"extra": "forbid"}

    detection: float | None = None
    source: float | None = None
    forecast: float | None = None
    overall: float | None = None


class CopilotToolCall(BaseModel):
    """One tool the copilot consulted to answer.

    Surfaced so a reader can see what was actually looked up rather than
    trusting the prose. The old UI faked this with a scripted spinner naming
    four sources regardless of what ran.
    """

    model_config = {"extra": "forbid"}

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class CopilotGrounding(BaseModel):
    """Verdict from the numeric grounding check.

    ``grounded`` false must never reach a user: the service falls back to
    deterministic retrieval instead.
    """

    model_config = {"extra": "forbid"}

    grounded: bool = True
    numbers_checked: int = 0
    ungrounded_values: list[float] = Field(default_factory=list)


class CopilotResponse(BaseModel):
    """Structured copilot answer. Empty lists mean no retrieved evidence."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["copilot.v2"] = "copilot.v2"
    answer: str
    observed_facts: list[str] = Field(default_factory=list)
    predicted_conditions: list[str] = Field(default_factory=list)
    likely_sources: list[dict[str, Any]] = Field(default_factory=list)
    confidence: CopilotConfidence = Field(default_factory=CopilotConfidence)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    #: True only when a model actually produced this text and its numbers
    #: passed grounding. Never set from the mere presence of an API key.
    llm_used: bool = False
    model: str | None = None
    tool_calls: list[CopilotToolCall] = Field(default_factory=list)
    grounding: CopilotGrounding = Field(default_factory=CopilotGrounding)
    #: Why the deterministic path answered, when it did.
    degraded_reason: str | None = None
