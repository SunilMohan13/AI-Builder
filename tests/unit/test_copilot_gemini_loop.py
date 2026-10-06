"""The Gemini tool loop, driven against a fake client.

Automatic function calling is disabled on purpose: the SDK would execute
tools itself and never show us the results, leaving the grounding validator
with nothing to check. These tests pin that the loop executes tools, feeds
results back, and records every one in the ledger.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aeropulse_contracts.feature import GridFeature
from aeropulse_copilot.gemini import MAX_TOOL_ROUNDS, GeminiCopilot, system_prompt
from aeropulse_copilot.tools import ToolContext

NOW = datetime(2026, 9, 8, 6, 0, tzinfo=UTC)
DELHI_GRID = "883da11463fffff"


class FakeGridReader:
    def latest_feature(self, grid_id: str) -> GridFeature | None:
        if grid_id != DELHI_GRID:
            return None
        return GridFeature(
            grid_id=DELHI_GRID,
            timestamp=NOW,
            center_lat=28.6139,
            center_lon=77.2090,
            pm25=186.4,
            pm10=298.2,
        )


class FakeCall:
    def __init__(self, name: str, args: dict[str, Any]) -> None:
        self.name = name
        self.args = args


class FakeResponse:
    """Either a set of tool calls, or final text."""

    def __init__(self, *, calls: list[FakeCall] | None = None, text: str = "") -> None:
        self.function_calls = calls or None
        self.text = text
        self.candidates = []


class FakeClient:
    """Replays scripted responses and records what it was sent."""

    def __init__(self, *responses: FakeResponse) -> None:
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.models = self

    def generate_content(self, *, model: str, contents: Any, config: Any) -> FakeResponse:
        # Snapshot: the caller appends to this list between rounds, so keeping
        # the reference would make every recorded request alias the last one.
        self.requests.append({"model": model, "contents": list(contents), "config": config})
        return self._responses.pop(0) if self._responses else FakeResponse(text="done")


def _ctx() -> ToolContext:
    return ToolContext(grid=FakeGridReader(), now=lambda: NOW)


def test_the_loop_executes_a_requested_tool_and_records_it() -> None:
    client = FakeClient(
        FakeResponse(calls=[FakeCall("get_air_quality", {"place": "Delhi"})]),
        FakeResponse(text="Delhi is at 186.4 ug/m3 PM2.5, measured just now."),
    )
    copilot = GeminiCopilot(client=client, model="fake")

    answer = copilot.answer("What is the air quality in Delhi?", _ctx())

    assert answer.rounds == 1
    assert len(answer.ledger.calls) == 1
    call = answer.ledger.calls[0]
    assert call.name == "get_air_quality"
    assert call.arguments == {"place": "Delhi"}
    assert call.result["pm25_ug_m3"] == 186.4
    assert "186.4" in answer.text


def test_tool_results_are_fed_back_to_the_model() -> None:
    client = FakeClient(
        FakeResponse(calls=[FakeCall("get_air_quality", {"place": "Delhi"})]),
        FakeResponse(text="ok"),
    )
    GeminiCopilot(client=client, model="fake").answer("q", _ctx())

    # Two requests: the question, then the question plus the tool response.
    assert len(client.requests) == 2
    assert len(client.requests[1]["contents"]) > len(client.requests[0]["contents"])


def test_several_tools_in_one_round_are_all_recorded() -> None:
    client = FakeClient(
        FakeResponse(
            calls=[
                FakeCall("get_air_quality", {"place": "Delhi"}),
                FakeCall("get_wind", {"place": "Delhi"}),
            ]
        ),
        FakeResponse(text="ok"),
    )
    answer = GeminiCopilot(client=client, model="fake").answer("q", _ctx())

    assert [c.name for c in answer.ledger.calls] == ["get_air_quality", "get_wind"]


def test_an_answer_with_no_tool_calls_returns_immediately() -> None:
    client = FakeClient(FakeResponse(text="AeroPulse monitors northern India."))
    answer = GeminiCopilot(client=client, model="fake").answer("what are you?", _ctx())

    assert answer.rounds == 0
    assert answer.ledger.calls == []


def test_an_unknown_tool_name_is_reported_to_the_model_not_raised() -> None:
    client = FakeClient(
        FakeResponse(calls=[FakeCall("get_stock_price", {"ticker": "X"})]),
        FakeResponse(text="I cannot do that."),
    )
    answer = GeminiCopilot(client=client, model="fake").answer("q", _ctx())

    assert answer.ledger.calls[0].result["status"] == "unknown_tool"


def test_bad_arguments_are_reported_to_the_model_not_raised() -> None:
    client = FakeClient(
        FakeResponse(calls=[FakeCall("get_air_quality", {"wrong_arg": 1})]),
        FakeResponse(text="retry"),
    )
    answer = GeminiCopilot(client=client, model="fake").answer("q", _ctx())

    assert answer.ledger.calls[0].result["status"] == "bad_arguments"


def test_a_runaway_tool_loop_is_bounded() -> None:
    """A model stuck calling tools must not spend unbounded budget."""
    looping = [
        FakeResponse(calls=[FakeCall("get_air_quality", {"place": "Delhi"})])
        for _ in range(MAX_TOOL_ROUNDS + 3)
    ]
    client = FakeClient(*looping)
    answer = GeminiCopilot(client=client, model="fake").answer("q", _ctx())

    assert answer.rounds == MAX_TOOL_ROUNDS
    assert "could not complete" in answer.text.lower()


def test_history_is_sent_as_prior_turns() -> None:
    client = FakeClient(FakeResponse(text="ok"))
    GeminiCopilot(client=client, model="fake").answer(
        "and Ludhiana?",
        _ctx(),
        history=[
            {"role": "user", "text": "air quality in Delhi?"},
            {"role": "assistant", "text": "186.4 ug/m3"},
        ],
    )

    contents = client.requests[0]["contents"]
    assert len(contents) == 3
    assert [c.role for c in contents] == ["user", "model", "user"]


def test_automatic_function_calling_is_disabled() -> None:
    """If the SDK ran tools itself, the ledger would be empty and the
    validator would have nothing to check against."""
    client = FakeClient(FakeResponse(text="ok"))
    GeminiCopilot(client=client, model="fake").answer("q", _ctx())

    config = client.requests[0]["config"]
    assert config.automatic_function_calling.disable is True


def test_the_system_prompt_states_the_grounding_and_index_rules() -> None:
    prompt = system_prompt("v1")
    assert "CPCB" in prompt
    assert "Never state a number that a tool did not return" in prompt
    assert "not a clinician" in prompt
