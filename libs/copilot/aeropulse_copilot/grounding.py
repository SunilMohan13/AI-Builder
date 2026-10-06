"""Reject answers containing numbers no tool returned.

ADR-0006 allowed an LLM to wrap the copilot only behind "a validator that
rejects ungrounded numbers". This is that validator.

The check is deliberately one-directional: every numeric claim in the prose
must trace to a tool result. It does not require the model to use every
number it was given. A model that invents a plausible PM2.5 reading is the
failure this platform cannot ship; a model that omits one is merely terse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from aeropulse_copilot.tools import ToolLedger

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
        grounded: True when every numeric claim traced to a tool result.
        ungrounded_values: The numbers that could not be traced.
        checked: How many numeric tokens were examined.
    """

    grounded: bool
    ungrounded_values: list[float] = field(default_factory=list)
    checked: int = 0

    def failure_note(self) -> str:
        """A corrective instruction for a regeneration attempt."""
        values = ", ".join(str(v) for v in self.ungrounded_values)
        return (
            f"The previous answer contained numbers not present in any tool result: {values}. "
            "Rewrite it using only values the tools returned, or omit the figure entirely."
        )


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


def _matches(value: float, allowed: set[float]) -> bool:
    for candidate in allowed:
        if value == candidate:
            return True
        scale = max(abs(value), abs(candidate), 1.0)
        if abs(value - candidate) <= scale * _RELATIVE_TOLERANCE:
            return True
        # A rendered figure is often the rounded form of a stored one.
        for digits in (0, 1, 2):
            if round(candidate, digits) == value:
                return True
    return False


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

    return GroundingResult(
        grounded=not ungrounded,
        ungrounded_values=sorted(set(ungrounded)),
        checked=checked,
    )


def _is_year(value: float) -> bool:
    """Treat a bare four-digit year as prose, not a measurement."""
    return value.is_integer() and 1900 <= value <= 2100
