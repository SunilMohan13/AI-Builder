"""Ask AeroPulse v2 tools and grounding (LLD APAC 11.2, 11.4).

The tools read a real in-north cycle through the API's ``PlatformRegionData``;
Singapore and NSW have no snapshot and must say so, never borrow in-north.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest
from aeropulse_api.copilot_regions import PlatformRegionData
from aeropulse_contracts import RegionSnapshot
from aeropulse_copilot import TOOLS, ToolContext, ToolLedger, describe_tools, validate_answer
from aeropulse_copilot.gemini import system_prompt
from aeropulse_copilot.region_tools import (
    PLUME_LABEL,
    explain_incident,
    get_citizen_reports,
    get_current_aqi,
    get_plume,
    get_pm25_trend,
    get_region_context,
    get_satellite_signal,
    get_source_likelihood,
    get_weather,
    list_incidents,
    query_trends,
    region_facts,
)
from aeropulse_copilot.tools import get_air_quality, list_active_events
from region_cycle import T0, platform_for


@pytest.fixture
def ctx(cycled: tuple[Path, RegionSnapshot]) -> ToolContext:
    platform = platform_for(cycled[0])
    return ToolContext(
        regions=PlatformRegionData(platform),
        region_id="in-north",
        now=lambda: T0 + timedelta(minutes=10),
    )


def test_every_tool_is_declared_and_every_declaration_is_a_tool() -> None:
    assert {d["name"] for d in describe_tools()} == set(TOOLS)
    assert len(TOOLS) == 20


def test_current_aqi_uses_the_cycles_band_and_never_bands_an_hourly_value(
    ctx: ToolContext,
) -> None:
    delhi = get_current_aqi("Delhi", ctx=ctx)
    assert delhi["status"] == "ok" and delhi["region_id"] == "in-north"
    assert delhi["provenance_class"] == "measured" and delhi["pm25_ug_m3"] is not None
    assert "CPCB" in delhi["aqi_standard"]
    assert delhi["aqi_band"] is None and "24 h" in delhi["aqi_band_reason"]

    region = get_current_aqi("North India", ctx=ctx)
    assert region["scope"] == "region" and region["aqi_band"] is None
    assert region["cells_with_value"] >= 1

    legacy = get_air_quality("Delhi", ctx=ctx)
    assert legacy["cycle_id"] == delhi["cycle_id"], "the old tool answers from the snapshot"


def test_regions_without_a_snapshot_say_so_and_unknown_places_are_refused(
    ctx: ToolContext,
) -> None:
    singapore = get_current_aqi("Singapore", ctx=ctx)
    assert singapore["status"] == "not_configured" and singapore["region_id"] == "sg-singapore"
    sydney = get_air_quality("Sydney", ctx=ctx)
    assert sydney["status"] == "not_configured" and sydney["region_id"] == "au-nsw"

    unknown = get_current_aqi("Atlantis", ctx=ctx)
    assert unknown["status"] == "unknown_location"
    assert {r["region_id"] for r in unknown["covered_regions"]} == {
        "in-north",
        "sg-singapore",
        "au-nsw",
    }
    assert get_current_aqi("Delhi", region_id="xx-nowhere", ctx=ctx)["status"] == "unknown_region"
    events = list_active_events(region_id="sg-singapore", ctx=ctx)
    assert events["status"] == "not_configured"


def test_region_context_lists_sources_and_served_models(ctx: ToolContext) -> None:
    north = get_region_context(ctx=ctx)
    assert north["region_id"] == "in-north" and north["snapshot"] is not None
    assert {m["family"] for m in north["served_models"]} >= {"pm25_forecast"}
    assert all("state" in s for s in north["sources"])
    singapore = get_region_context("sg-singapore", ctx=ctx)
    assert singapore["snapshot"] is None and singapore["snapshot_reason"]


def test_trend_reads_stored_history_and_query_trends_is_allow_listed(ctx: ToolContext) -> None:
    trend = get_pm25_trend("Delhi", hours=6, ctx=ctx)
    assert trend["status"] == "ok" and trend["series"]
    assert trend["provenance_class"] == ["measured"]
    assert trend["last_pm25_ug_m3"] - trend["first_pm25_ug_m3"] == pytest.approx(
        trend["change_ug_m3"], abs=0.11
    )

    start, end = (T0 - timedelta(hours=6)).isoformat(), (T0 + timedelta(minutes=10)).isoformat()
    rows = query_trends("pm25_hourly", "Delhi", start, end, ctx=ctx)
    assert rows["status"] == "ok" and rows["template_id"] == "pm25_hourly"
    assert query_trends("raw_sql", "Delhi", start, end, ctx=ctx)["status"] == "bad_arguments"
    too_long = (T0 - timedelta(days=30)).isoformat()
    assert query_trends("pm25_hourly", "Delhi", too_long, end, ctx=ctx)["status"] == (
        "bad_arguments"
    )


def test_weather_and_satellite_report_what_is_and_is_not_served(ctx: ToolContext) -> None:
    weather = get_weather("Delhi", ctx=ctx)
    assert weather["status"] == "ok" and weather["now"]["wind_speed_ms"] is not None
    assert weather["humidity"] is None
    assert {f["field"] for f in weather["field_status"]} >= {"humidity"}
    satellite = get_satellite_signal("Delhi", ctx=ctx)
    assert satellite["status"] == "unavailable" and satellite["reason"]


def test_incident_tools_bundle_labelled_evidence(
    ctx: ToolContext, cycled: tuple[Path, RegionSnapshot]
) -> None:
    listed = list_incidents(ctx=ctx)
    assert listed["total"] == len(cycled[1].incidents) >= 1
    incident_id = listed["incidents"][0]["incident_id"]

    bundle = explain_incident(incident_id, ctx=ctx)
    assert bundle["status"] == "ok" and bundle["region_id"] == "in-north"
    assert bundle["satellite"]["status"] == "unavailable"
    assert bundle["source_likelihood"]["provenance_class"] == "heuristic"
    assert bundle["source_likelihood"]["calibrated"] is False
    for key in ("plumes", "back_trajectory"):
        for plume in bundle[key]["plumes"]:
            assert plume["provenance_class"] == "simulated" and plume["experimental"]
            assert plume["label"] == PLUME_LABEL
    backward = bundle["back_trajectory"]["plumes"]
    assert backward and "not proof" in backward[0]["interpretation"]
    assert bundle["citizen_reports"]["status"] == "no_data"

    both = get_plume(place="Delhi", incident_id=incident_id, ctx=ctx)
    assert both["status"] == "bad_arguments"
    assert get_citizen_reports(ctx=ctx)["status"] == "bad_arguments"
    assert explain_incident("inc_missing", ctx=ctx)["status"] == "not_found"


def test_source_likelihood_is_a_ranking_not_a_probability(ctx: ToolContext) -> None:
    result = get_source_likelihood("North India", ctx=ctx)
    assert result["status"] == "ok" and result["calibrated"] is False
    assert "not percentages" in result["interpretation"]
    ranking = result["cells"][0]["ranking"]
    assert [r["score"] for r in ranking] == sorted((r["score"] for r in ranking), reverse=True)


def test_region_facts_name_the_region_and_carry_no_figures(ctx: ToolContext) -> None:
    facts = region_facts(ctx)
    assert facts is not None and "CPCB" in facts and "in-north" in facts
    assert "sg-singapore" in facts, "other covered regions are named"
    assert not re.search(r"\d", facts.replace("in-north", "")), "no number reaches the prompt"
    prompt = system_prompt()
    assert "provenance_class" in prompt and "experimental" in prompt


def _ledger(result: dict) -> ToolLedger:
    ledger = ToolLedger()
    ledger.record("tool", {}, result)
    return ledger


def test_grounding_rejects_a_simulated_value_written_as_measured() -> None:
    plume = {
        "provenance_class": "simulated",
        "arrivals": [{"name": "Delhi", "probability": 0.42, "eta_hours_median": 7.5}],
    }
    bad = validate_answer("Smoke was measured reaching Delhi at 0.42 probability.", _ledger(plume))
    assert not bad.grounded and bad.mislabelled_values == [0.42] and not bad.ungrounded_values
    assert "simulated" in bad.failure_note()

    good = validate_answer(
        "Simulated transport reaches Delhi with footprint probability 0.42 in 7.5 hours.",
        _ledger(plume),
    )
    assert good.grounded


def test_grounding_allows_measurement_wording_for_a_measured_value() -> None:
    ledger = _ledger({"provenance_class": "measured", "pm25_ug_m3": 186.4})
    ledger.record("plume", {}, {"provenance_class": "simulated", "population_p90": 186.4})
    assert validate_answer("PM2.5 measured 186.4 µg/m³ at the station.", ledger).grounded

    heuristic = _ledger({"provenance_class": "heuristic", "cells": [{"score": 0.71}]})
    verdict = validate_answer("Stations recorded a score of 0.71 for crop burning.", heuristic)
    assert verdict.mislabelled_values == [0.71]
    observed = _ledger({"provenance_class": "ai_observation", "report_count": 17})
    assert not validate_answer("17 reports were detected by station.", observed).grounded
