"""Ask AeroPulse without a language model answers from the region tools.

Every answer must pass the same grounding check the Gemini path does, and a
region with no snapshot must say so rather than borrow another region's data.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from aeropulse_api.copilot_regions import PlatformRegionData
from aeropulse_api.copilot_service import _deterministic_fallback
from aeropulse_contracts import RegionSnapshot
from aeropulse_copilot import CopilotService, ToolContext, validate_answer
from aeropulse_copilot.deterministic import region_answer
from region_cycle import T0, platform_for

INCIDENT = "inc_fd6ec2096981a3d3e14fb1a6"


def _ctx(root: Path, region_id: str | None) -> ToolContext:
    return ToolContext(
        regions=PlatformRegionData(platform_for(root)),
        region_id=region_id,
        now=lambda: T0 + timedelta(minutes=10),
    )


@pytest.mark.parametrize(
    ("question", "tool", "expected"),
    [
        (
            "What is the air quality in North India (Punjab, Haryana, Delhi) right now?",
            "get_current_aqi",
            "Median hourly PM2.5 across 6 cells",
        ),
        ("What is the air quality in Delhi?", "get_current_aqi", "142.3 µg/m³, measured by cpcb"),
        ("Which pollution events are active?", "list_active_events", "4 open event(s)"),
        ("Are there active fires?", "get_active_fires", "2 fire cluster(s)"),
        ("Any incidents today?", "list_incidents", INCIDENT),
        (
            f"Explain this incident. (Selected incident: {INCIDENT})",
            "explain_incident",
            "Predicted smoke transport — experimental (simulated",
        ),
        ("hello", "get_region_context", "CPCB National AQI (India)"),
    ],
)
def test_each_intent_answers_from_its_tool_and_is_grounded(
    cycled: tuple[Path, RegionSnapshot], question: str, tool: str, expected: str
) -> None:
    answer = region_answer(question, _ctx(cycled[0], "in-north"))

    assert answer is not None
    assert [c["name"] for c in answer.tool_calls] == [tool]
    assert expected in answer.answer
    grounding = validate_answer(answer.answer, answer.ledger)
    assert grounding.grounded, grounding


def test_a_topic_question_beats_the_selected_incident(cycled: tuple[Path, RegionSnapshot]) -> None:
    ctx = _ctx(cycled[0], "in-north")
    asked = region_answer(f"Are there active fires? (Selected incident: {INCIDENT})", ctx)
    explained = region_answer(f"Explain this. (Selected incident: {INCIDENT})", ctx)

    assert asked is not None and explained is not None
    assert [c["name"] for c in asked.tool_calls] == ["get_active_fires"]
    assert [c["name"] for c in explained.tool_calls] == ["explain_incident"]


def test_the_band_is_a_dash_with_the_standards_reason(cycled: tuple[Path, RegionSnapshot]) -> None:
    answer = region_answer("What is the air quality in Delhi?", _ctx(cycled[0], "in-north"))

    assert answer is not None
    assert "band: — (" in answer.answer
    assert "24 h mean" in answer.answer


def test_a_region_without_a_snapshot_says_so(cycled: tuple[Path, RegionSnapshot]) -> None:
    answer = region_answer(
        "What is the air quality in Singapore right now?", _ctx(cycled[0], "sg-singapore")
    )

    assert answer is not None
    assert "not_configured" in answer.answer
    assert "µg/m³" not in answer.answer


def test_no_region_context_falls_back_to_the_caller(cycled: tuple[Path, RegionSnapshot]) -> None:
    assert region_answer("What is the air quality?", _ctx(cycled[0], None)) is None


def test_the_service_reports_how_many_figures_it_checked(
    cycled: tuple[Path, RegionSnapshot],
) -> None:
    result = CopilotService(None, fallback=_deterministic_fallback).ask(
        "Are there active fires?", _ctx(cycled[0], "in-north")
    )

    assert not result.llm_used
    assert result.grounded
    assert result.numbers_checked > 0
