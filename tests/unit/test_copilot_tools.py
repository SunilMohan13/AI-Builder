"""Grounded copilot: tools, the numeric validator, and the fallback path.

No network. Gemini is replaced by a scripted fake so the properties that
matter — a model cannot state a number no tool returned, and llm_used never
lies — are tested deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aeropulse_contracts.event import EventStatus
from aeropulse_contracts.feature import GridFeature
from aeropulse_copilot.grounding import validate_answer
from aeropulse_copilot.service import CopilotService
from aeropulse_copilot.tools import (
    ToolContext,
    ToolLedger,
    cpcb_band,
    describe_tools,
    get_active_fires,
    get_air_quality,
    get_wind,
    list_active_events,
)

NOW = datetime(2026, 9, 8, 6, 0, tzinfo=UTC)
DELHI_GRID = "883da11463fffff"


def _feature(grid_id: str, *, pm25: float | None, observed_at: datetime) -> GridFeature:
    return GridFeature(
        grid_id=grid_id,
        timestamp=observed_at,
        center_lat=28.6139,
        center_lon=77.2090,
        pm25=pm25,
        pm10=None if pm25 is None else pm25 * 1.6,
        wind_speed=2.4,
        wind_direction=315.0,
        boundary_layer_height=640.0,
    )


class FakeGridReader:
    def __init__(self, features: dict[str, GridFeature]) -> None:
        self._features = features

    def latest_feature(self, grid_id: str) -> GridFeature | None:
        return self._features.get(grid_id)


class FakeMapReader:
    def __init__(self, fires: list[dict[str, Any]] | None = None) -> None:
        self._fires = fires or []

    def air_quality(self, bbox, limit):
        return []

    def fire(self, bbox, limit):
        return self._fires

    def weather(self, bbox, limit):
        return []


def _ctx(**kwargs: Any) -> ToolContext:
    features = kwargs.pop(
        "features", {DELHI_GRID: _feature(DELHI_GRID, pm25=186.4, observed_at=NOW)}
    )
    return ToolContext(
        grid=FakeGridReader(features),
        map=FakeMapReader(kwargs.pop("fires", [])),
        now=lambda: NOW,
        **kwargs,
    )


# --- CPCB index ---


@pytest.mark.parametrize(
    ("pm25", "band"),
    [
        (10, "Good"),
        (45, "Satisfactory"),
        (75, "Moderate"),
        (105, "Poor"),
        (186.4, "Very Poor"),
        (300, "Severe"),
    ],
)
def test_cpcb_bands_use_the_indian_scale(pm25: float, band: str) -> None:
    """US EPA would call 186 'Unhealthy'; CPCB calls it Very Poor."""
    assert cpcb_band(pm25) == band


class _RecordingEvents:
    def __init__(self) -> None:
        self.seen: EventStatus | None = None
        self.called = False

    def list_events(
        self, status: EventStatus | None, limit: int, offset: int
    ) -> tuple[list[Any], int]:
        self.called = True
        self.seen = status
        return [], 7

    def get_event(self, event_id: str) -> Any:
        return None

    def get_evidence(self, event_id: str) -> list[Any]:
        return []


def test_list_active_events_passes_an_enum_not_a_string() -> None:
    """The Timescale reader reads status.value; a raw string crashes that lookup."""
    reader = _RecordingEvents()
    result = list_active_events("active", ctx=ToolContext(events=reader))
    assert reader.seen is EventStatus.ACTIVE
    assert result["status"] == "ok"
    assert result["total"] == 7


def test_list_active_events_rejects_an_unknown_status() -> None:
    reader = _RecordingEvents()
    result = list_active_events("OPEN", ctx=ToolContext(events=reader))
    assert reader.called is False
    assert result["status"] == "bad_arguments"


# --- tools ---


def test_air_quality_answers_for_a_known_city() -> None:
    result = get_air_quality("Delhi", ctx=_ctx())
    assert result["status"] == "ok"
    assert result["place"] == "Delhi"
    assert result["pm25_ug_m3"] == 186.4
    assert result["cpcb_band"] == "Very Poor"
    assert result["stale"] is False


def test_air_quality_resolves_a_place_inside_a_sentence() -> None:
    assert get_air_quality("air quality in Delhi right now", ctx=_ctx())["status"] == "ok"


def test_an_unknown_city_is_reported_never_guessed() -> None:
    """Answering about the wrong city confidently is the failure to avoid."""
    result = get_air_quality("Mumbai", ctx=_ctx())
    assert result["status"] == "unknown_location"
    assert "pm25_ug_m3" not in result
    assert "Mumbai" in result["message"]


def test_a_stale_reading_is_flagged() -> None:
    old = _feature(DELHI_GRID, pm25=140.0, observed_at=NOW - timedelta(hours=5))
    result = get_air_quality("Delhi", ctx=_ctx(features={DELHI_GRID: old}))
    assert result["stale"] is True
    assert result["age_minutes"] == 300.0


def test_missing_data_is_reported_as_no_data() -> None:
    result = get_air_quality("Amritsar", ctx=_ctx(features={}))
    assert result["status"] == "no_data"


def test_wind_reports_direction_and_speed() -> None:
    result = get_wind("Delhi", ctx=_ctx())
    assert result["wind_speed_ms"] == 2.4
    assert result["wind_from_degrees"] == 315.0
    assert result["wind_towards_degrees"] == 135.0


def test_fires_are_filtered_by_radius() -> None:
    fires = [
        {
            "geometry": {"coordinates": [75.71, 30.12]},
            "properties": {"frp": 14.7, "confidence": 0.6, "observed_at": NOW.isoformat()},
        },
        {
            "geometry": {"coordinates": [88.36, 22.57]},  # Kolkata: far outside
            "properties": {"frp": 90.0, "confidence": 0.9, "observed_at": NOW.isoformat()},
        },
    ]
    result = get_active_fires("Ludhiana", radius_km=150.0, ctx=_ctx(fires=fires))
    assert result["fire_count"] == 1
    assert result["total_frp_mw"] == 14.7


def test_every_tool_is_declared_to_the_model() -> None:
    declared = {tool["name"] for tool in describe_tools()}
    assert "get_air_quality" in declared
    for tool in describe_tools():
        assert tool["description"]
        assert tool["parameters"]["type"] == "object"


# --- grounding validator ---


def _ledger_with(result: Any) -> ToolLedger:
    ledger = ToolLedger()
    ledger.record("get_air_quality", {"place": "Delhi"}, result)
    return ledger


def test_an_answer_using_tool_numbers_is_grounded() -> None:
    ledger = _ledger_with({"pm25_ug_m3": 186.4, "observed_at": NOW.isoformat()})
    verdict = validate_answer("Delhi is at 186.4 ug/m3 PM2.5.", ledger)
    assert verdict.grounded is True


def test_an_invented_number_is_rejected() -> None:
    """The property the whole design exists to guarantee."""
    ledger = _ledger_with({"pm25_ug_m3": 186.4})
    verdict = validate_answer("Delhi is at 243.8 ug/m3 PM2.5.", ledger)
    assert verdict.grounded is False
    assert 243.8 in verdict.ungrounded_values


def test_a_rounded_rendering_of_a_tool_value_is_accepted() -> None:
    ledger = _ledger_with({"pm25_ug_m3": 186.4})
    assert validate_answer("Delhi is around 186 ug/m3.", ledger).grounded is True


def test_prose_without_numbers_is_grounded() -> None:
    assert validate_answer("Air quality is poor today.", ToolLedger()).grounded is True


def test_years_are_not_treated_as_measurements() -> None:
    assert validate_answer("The 2026 stubble season began early.", ToolLedger()).grounded is True


def test_the_failure_note_names_the_offending_values() -> None:
    ledger = _ledger_with({"pm25_ug_m3": 186.4})
    verdict = validate_answer("It is 243.8 ug/m3.", ledger)
    assert "243.8" in verdict.failure_note()


# --- service orchestration ---


@dataclass
class FakeGeminiAnswer:
    text: str
    ledger: ToolLedger
    rounds: int = 1
    model: str = "fake-model"


class FakeGemini:
    """Scripted model. Returns each queued answer in turn."""

    def __init__(self, *answers: str, ledger_result: Any = None) -> None:
        self._answers = list(answers)
        self._ledger_result = ledger_result or {"pm25_ug_m3": 186.4}
        self.available = True
        self.calls: list[dict[str, Any]] = []

    def answer(self, question, ctx, *, history=None, extra_instruction=None):
        self.calls.append({"question": question, "extra_instruction": extra_instruction})
        ledger = ToolLedger()
        ledger.record("get_air_quality", {"place": "Delhi"}, self._ledger_result)
        text = self._answers.pop(0) if self._answers else "No answer."
        return FakeGeminiAnswer(text=text, ledger=ledger)


def test_a_grounded_model_answer_is_returned_with_llm_used_true() -> None:
    service = CopilotService(FakeGemini("Delhi is at 186.4 ug/m3."))
    result = service.ask("What is the air quality in Delhi?", _ctx())

    assert result.llm_used is True
    assert result.grounded is True
    assert result.model == "fake-model"
    assert result.tool_calls[0]["name"] == "get_air_quality"


def test_an_ungrounded_answer_triggers_one_corrective_retry() -> None:
    gemini = FakeGemini("It is 243.8 ug/m3.", "Delhi is at 186.4 ug/m3.")
    result = CopilotService(gemini).ask("q", _ctx())

    assert len(gemini.calls) == 2
    assert gemini.calls[1]["extra_instruction"] is not None
    assert result.llm_used is True


def test_persistent_ungrounding_falls_back_instead_of_shipping_the_number() -> None:
    gemini = FakeGemini("It is 243.8 ug/m3.", "Actually it is 999.1 ug/m3.")
    captured: list[str] = []

    def fallback(question: str):
        captured.append(question)
        return type("R", (), {"answer": "Deterministic answer.", "evidence": []})()

    result = CopilotService(gemini, fallback=fallback).ask("q", _ctx())

    assert result.llm_used is False
    assert "243.8" not in result.answer
    assert "999.1" not in result.answer
    assert captured == ["q"]


def test_no_credential_degrades_to_deterministic_retrieval() -> None:
    """The old behaviour set llm_used from an env var with no call at all."""
    service = CopilotService(
        None, fallback=lambda q: type("R", (), {"answer": "det", "evidence": []})()
    )
    result = service.ask("q", _ctx())

    assert result.llm_used is False
    assert result.degraded_reason == "no Gemini credential configured"
    assert any("Language model not used" in limit for limit in result.limitations)


def test_a_model_exception_degrades_rather_than_failing_the_request() -> None:
    class Exploding:
        available = True

        def answer(self, *args, **kwargs):
            raise RuntimeError("upstream 503")

    service = CopilotService(
        Exploding(), fallback=lambda q: type("R", (), {"answer": "det", "evidence": []})()
    )
    result = service.ask("q", _ctx())

    assert result.llm_used is False
    assert "upstream 503" in (result.degraded_reason or "")
