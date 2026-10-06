"""Copilot orchestration: ask Gemini, validate, or fall back.

The contract this enforces:

* an answer is only returned with ``llm_used=True`` when a real model call
  happened and its numbers passed grounding;
* a grounding failure gets one corrective retry, then falls back to
  deterministic retrieval rather than shipping an unvalidated number;
* a missing key or an upstream error degrades to the same deterministic path
  the platform had before Gemini existed.

``llm_used`` therefore always describes what actually happened. The previous
implementation set it true whenever an env var was present, with no call.
"""

from __future__ import annotations

from dataclasses import dataclass
from inspect import signature
from typing import Any, Protocol

from aeropulse_observability.logging import get_logger

from aeropulse_copilot.gemini import GeminiUnavailableError
from aeropulse_copilot.grounding import GroundingResult, validate_answer
from aeropulse_copilot.tools import ToolContext, ToolLedger

logger = get_logger("aeropulse.copilot")


class AnsweringModel(Protocol):
    """What the service needs from a model client.

    A protocol rather than :class:`GeminiCopilot` so a recorded or scripted
    client can stand in without subclassing the real one.
    """

    @property
    def available(self) -> bool: ...

    def answer(
        self,
        question: str,
        ctx: ToolContext,
        *,
        history: list[dict[str, str]] | None = ...,
        extra_instruction: str | None = ...,
    ) -> Any: ...


@dataclass
class CopilotAnswer:
    """What the API layer renders.

    Attributes:
        answer: Prose for the user.
        llm_used: True only when a model produced this text.
        tool_calls: Names and arguments of the tools consulted.
        evidence: Source/time citations gathered from tool results.
        limitations: Caveats that apply to this answer.
        grounded: Whether numeric validation passed.
        model: Model id, when one was used.
        degraded_reason: Why the deterministic path was used, if it was.
    """

    answer: str
    llm_used: bool = False
    tool_calls: list[dict[str, Any]] = None  # type: ignore[assignment]
    evidence: list[dict[str, str]] = None  # type: ignore[assignment]
    limitations: list[str] = None  # type: ignore[assignment]
    grounded: bool = True
    model: str | None = None
    degraded_reason: str | None = None

    def __post_init__(self) -> None:
        self.tool_calls = self.tool_calls or []
        self.evidence = self.evidence or []
        self.limitations = self.limitations or []


BASE_LIMITATIONS = [
    "Numbers come from AeroPulse tool lookups, never from model recall.",
    "Air quality bands follow the CPCB National Air Quality Index (India).",
]


class CopilotService:
    """Answers questions with Gemini when possible, deterministically otherwise.

    Args:
        gemini: Any client satisfying :class:`AnsweringModel`, or None when
            no credential is present.
        fallback: Callable returning a deterministic answer for a question.
    """

    def __init__(
        self,
        gemini: AnsweringModel | None = None,
        *,
        fallback: Any | None = None,
    ) -> None:
        self._gemini = gemini
        self._fallback = fallback

    @property
    def llm_enabled(self) -> bool:
        """Whether a model call is possible at all."""
        return self._gemini is not None and self._gemini.available

    def ask(
        self,
        question: str,
        ctx: ToolContext,
        *,
        history: list[dict[str, str]] | None = None,
    ) -> CopilotAnswer:
        """Answer one question.

        Args:
            question: The user's question.
            ctx: Readers the tools resolve data through.
            history: Prior conversation turns.

        Returns:
            A :class:`CopilotAnswer` whose ``llm_used`` reflects reality.
        """
        if not self.llm_enabled:
            return self._deterministic(question, "no Gemini credential configured", ctx)

        assert self._gemini is not None
        try:
            attempt = self._gemini.answer(question, ctx, history=history)
            verdict = validate_answer(attempt.text, attempt.ledger)

            if not verdict.grounded:
                logger.warning(
                    "copilot.grounding_failed",
                    ungrounded=verdict.ungrounded_values,
                    attempt=1,
                )
                attempt = self._gemini.answer(
                    question,
                    ctx,
                    history=history,
                    extra_instruction=verdict.failure_note(),
                )
                verdict = validate_answer(attempt.text, attempt.ledger)

            if not verdict.grounded:
                logger.error("copilot.grounding_failed_final", ungrounded=verdict.ungrounded_values)
                return self._deterministic(
                    question,
                    "the model produced figures that did not match any tool result",
                    ctx,
                )
        except GeminiUnavailableError as exc:
            return self._deterministic(question, str(exc), ctx)
        except Exception as exc:
            logger.exception("copilot.gemini_failed")
            return self._deterministic(question, f"Gemini request failed: {exc}", ctx)

        return CopilotAnswer(
            answer=attempt.text,
            llm_used=True,
            tool_calls=[{"name": c.name, "arguments": c.arguments} for c in attempt.ledger.calls],
            evidence=attempt.ledger.sources(),
            limitations=list(BASE_LIMITATIONS),
            grounded=True,
            model=attempt.model,
        )

    def _deterministic(
        self, question: str, reason: str, ctx: ToolContext | None = None
    ) -> CopilotAnswer:
        """Answer without a model, saying plainly that none was used."""
        logger.info("copilot.deterministic", reason=reason)
        if self._fallback is None:
            return CopilotAnswer(
                answer=(
                    "The language model is unavailable, so I cannot answer this in prose. "
                    "The dashboard shows the underlying measurements."
                ),
                llm_used=False,
                limitations=[*BASE_LIMITATIONS, f"Language model not used: {reason}."],
                degraded_reason=reason,
            )
        result = self._call_fallback(question, ctx)
        answer = getattr(result, "answer", None) or str(result)
        return CopilotAnswer(
            answer=answer,
            llm_used=False,
            evidence=list(getattr(result, "evidence", []) or []),
            limitations=[
                *BASE_LIMITATIONS,
                f"Language model not used: {reason}.",
                "Answer assembled by deterministic retrieval over stored evidence.",
            ],
            degraded_reason=reason,
        )

    def _call_fallback(self, question: str, ctx: ToolContext | None) -> Any:
        """Invoke a one- or two-argument fallback without breaking older tests."""
        fallback = self._fallback
        if fallback is None:
            raise TypeError("CopilotService has no deterministic fallback")
        try:
            params = signature(fallback).parameters
        except (TypeError, ValueError):
            return fallback(question)
        if len(params) >= 2:
            return fallback(question, ctx)
        return fallback(question)


def ledger_to_evidence(ledger: ToolLedger) -> list[dict[str, str]]:
    """Expose a ledger's citations, for callers building their own response."""
    return ledger.sources()


def grounding_summary(result: GroundingResult) -> dict[str, Any]:
    """Render a validator verdict for API transparency."""
    return {
        "grounded": result.grounded,
        "numbers_checked": result.checked,
        "ungrounded_values": result.ungrounded_values,
    }
