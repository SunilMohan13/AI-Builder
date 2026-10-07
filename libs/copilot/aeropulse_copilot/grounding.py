"""Reject answers containing numbers no tool returned.

ADR-0006 allowed an LLM to wrap the copilot only behind "a validator that
rejects ungrounded numbers". This is that validator.

The check is deliberately one-directional: every numeric claim in the prose
must trace to a tool result. It does not require the model to use every
number it was given. A model that invents a plausible PM2.5 reading is the
failure this platform cannot ship; a model that omits one is merely terse.

A second check (LLD APAC 11.4) rejects a sentence that uses measurement
wording ("measured", "recorded", "detected by station") for a number whose
only sources in the ledger are AI-observation, simulated or heuristic values.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from aeropulse_copilot.context import ToolLedger

#: Provenance classes that must never be presented as a measurement.
NOT_MEASURED = frozenset({"ai_observation", "simulated", "heuristic"})

_MEASUREMENT_WORDING = re.compile(
    r"\b(measured|recorded|detected by (?:a |the )?(?:ground )?stations?)\b", re.IGNORECASE
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")

#: Numbers that carry no factual claim on their own.
_ALWAYS_ALLOWED = {0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 12.0, 24.0, 100.0}

#: Relative tolerance for matching a rendered number to a stored one, so
#: "186.4" matches 186.40000000000003 and "186" matches 186.4 after rounding.
_RELATIVE_TOLERANCE = 0.005

_NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])")


@dataclass
class GroundingResult:
    """Outcome of validating one answer.

    Attributes:
        grounded: True when every numeric claim traced to a tool result and
            none was presented as a measurement it is not.
        ungrounded_values: The numbers that could not be traced.
        checked: How many numeric tokens were examined.
        mislabelled_values: Numbers only an AI-observation, simulated or
            heuristic result supports, written with measurement wording.
    """

    grounded: bool
    ungrounded_values: list[float] = field(default_factory=list)
    checked: int = 0
    mislabelled_values: list[float] = field(default_factory=list)

    def failure_note(self) -> str:
        """A corrective instruction for a regeneration attempt."""
        notes = []
        if self.ungrounded_values:
            values = ", ".join(str(v) for v in self.ungrounded_values)
            notes.append(
                f"The previous answer contained numbers not present in any tool result: "
                f"{values}. Rewrite it using only values the tools returned, or omit the "
                "figure entirely."
            )
        if self.mislabelled_values:
            values = ", ".join(str(v) for v in self.mislabelled_values)
            notes.append(
                f"The previous answer described {values} as measured or recorded, but the "
                "tools returned it as a simulated, heuristic or AI-observation value. Label "
                "it with its provenance (simulated, heuristic score, AI observation) instead."
            )
        return " ".join(notes)


def collect_numbers(payload: Any) -> set[float]:
    """Return every numeric value anywhere in a tool result."""
    found: set[float] = set()
    if isinstance(payload, bool):
        return found
    if isinstance(payload, (int, float)):
        found.add(float(payload))
    elif isinstance(payload, str):
        for match in _NUMBER.finditer(payload):
            found.add(float(match.group(1)))
    elif isinstance(payload, dict):
        for key, value in payload.items():
            found |= collect_numbers(key)
            found |= collect_numbers(value)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            found |= collect_numbers(item)
    return found


def _same(value: float, candidate: float) -> bool:
    if value == candidate:
        return True
    scale = max(abs(value), abs(candidate), 1.0)
    if abs(value - candidate) <= scale * _RELATIVE_TOLERANCE:
        return True
    # A rendered figure is often the rounded form of a stored one.
    return any(round(candidate, digits) == value for digits in (0, 1, 2))


def _matches(value: float, allowed: Iterable[float]) -> bool:
    return any(_same(value, candidate) for candidate in allowed)


def _classes(raw: Any) -> frozenset[str] | None:
    if isinstance(raw, str):
        return frozenset({raw})
    if isinstance(raw, (list, tuple)) and raw and all(isinstance(c, str) for c in raw):
        return frozenset(raw)
    return None


def collect_classified(
    payload: Any,
    inherited: frozenset[str] = frozenset(),
    out: dict[float, set[str]] | None = None,
) -> dict[float, set[str]]:
    """Every number in a tool result, with the provenance classes it was returned under.

    A dict's own ``provenance_class`` applies to its scalar values and is
    inherited by nested values that do not declare one. A number with no
    class anywhere above it is recorded as ``unclassified``.
    """
    found: dict[float, set[str]] = defaultdict(set) if out is None else out
    if isinstance(payload, bool):
        return found
    if isinstance(payload, (int, float)):
        found[float(payload)] |= set(inherited) or {"unclassified"}
    elif isinstance(payload, dict):
        own = _classes(payload.get("provenance_class"))
        scope = own if own is not None else inherited
        for value in payload.values():
            collect_classified(value, scope, found)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            collect_classified(item, inherited, found)
    return found


def _mislabelled(answer: str, ledger: ToolLedger) -> list[float]:
    classified: dict[float, set[str]] = defaultdict(set)
    for call in ledger.calls:
        collect_classified(call.result, out=classified)
    flagged: set[float] = set()
    for sentence in _SENTENCE.split(answer or ""):
        if not _MEASUREMENT_WORDING.search(sentence):
            continue
        for match in _NUMBER.finditer(sentence):
            value = float(match.group(1))
            if value in _ALWAYS_ALLOWED or _is_year(value):
                continue
            classes = set().union(
                *(c for candidate, c in classified.items() if _same(value, candidate))
            )
            if classes and classes <= NOT_MEASURED:
                flagged.add(value)
    return sorted(flagged)


def validate_answer(answer: str, ledger: ToolLedger) -> GroundingResult:
    """Check that every number in ``answer`` came from a tool result.

    Args:
        answer: The model's prose.
        ledger: Every tool call made while producing it.

    Returns:
        A :class:`GroundingResult`. Callers must not surface an answer whose
        result is not ``grounded``.
    """
    allowed: set[float] = set(_ALWAYS_ALLOWED)
    for call in ledger.calls:
        allowed |= collect_numbers(call.result)
        allowed |= collect_numbers(call.arguments)

    ungrounded: list[float] = []
    checked = 0
    for match in _NUMBER.finditer(answer or ""):
        checked += 1
        value = float(match.group(1))
        if _is_year(value) or _matches(value, allowed):
            continue
        ungrounded.append(value)

    mislabelled = _mislabelled(answer, ledger)
    return GroundingResult(
        grounded=not ungrounded and not mislabelled,
        ungrounded_values=sorted(set(ungrounded)),
        checked=checked,
        mislabelled_values=mislabelled,
    )


def _is_year(value: float) -> bool:
    """Treat a bare four-digit year as prose, not a measurement."""
    return value.is_integer() and 1900 <= value <= 2100
