"""Ask AeroPulse with no language model: pick region tools by intent and print their figures.

This is the degradation path when Gemini is unavailable (and what the Demo
recording captures). Intent is a keyword match, the place is the phrase after
"in" / "near" (else the whole region), and every number in the answer is
copied from a tool result in the ledger. Nothing is estimated here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from aeropulse_copilot.context import ToolContext, ToolLedger
from aeropulse_copilot.region_tools import (
    explain_incident,
    get_current_aqi,
    get_region_context,
    list_incidents,
)
from aeropulse_copilot.tools import get_active_fires, list_active_events

_INCIDENT_ID = re.compile(r"\binc_[0-9a-f]{8,}\b")
_PLACE = re.compile(
    r"\b(?:in|near|around|at|for)\s+(.+?)(?:\s+(?:right now|now|today|currently))?\s*[?.!]*$",
    re.IGNORECASE,
)
_FIRE = re.compile(r"\b(fire|fires|burning|hotspots?|frp)\b", re.IGNORECASE)
_EVENT = re.compile(r"\b(events?|alerts?)\b", re.IGNORECASE)
_INCIDENT = re.compile(r"\b(incidents?|plume|smoke going|transport|trajectory)\b", re.IGNORECASE)
_AIR = re.compile(r"\b(air|aqi|pm2\.?5|pollution|haze|smog)\b", re.IGNORECASE)


@dataclass
class RegionAnswer:
    answer: str
    ledger: ToolLedger
    evidence: list[dict[str, str]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


def _call(ledger: ToolLedger, name: str, fn: Any, ctx: ToolContext, **args: Any) -> dict[str, Any]:
    result = fn(**args, ctx=ctx)
    ledger.record(name, args, result)
    return result


def _place(question: str, ctx: ToolContext) -> str:
    text = _INCIDENT_ID.sub("", question.split("(Selected incident:")[0]).strip()
    match = _PLACE.search(text)
    if match:
        return match.group(1).strip(" ,")
    assert ctx.regions is not None and ctx.region_id is not None
    return ctx.regions.catalog.get(ctx.region_id).display_name


def _not_ok(result: dict[str, Any]) -> str | None:
    if result.get("status") == "ok":
        return None
    reason = result.get("reason") or result.get("message") or "no data"
    where = result.get("place") or result.get("region_id") or "this request"
    if result.get("status") == "unknown_location":
        covered = ", ".join(r["display_name"] for r in result.get("covered_regions", []))
        return f"I could not place {where!r}. Covered regions: {covered}."
    return f"{where}: {result.get('status')} — {reason}."


def _band(view: dict[str, Any]) -> str:
    band = view.get("aqi_band")
    if band:
        return f"{view.get('aqi_standard')} band: {band.get('label')}."
    reason = view.get("aqi_band_reason")
    return f"{view.get('aqi_standard')} band: — ({reason})." if reason else ""


def _air(result: dict[str, Any]) -> str:
    if (problem := _not_ok(result)) is not None:
        return problem
    if result.get("scope") == "region":
        top = result["highest"]
        return (
            f"Median hourly PM2.5 across {result['cells_with_value']} cells in {result['place']} "
            f"is {result['median_pm25_ug_m3']} µg/m³ (cycle {result['cycle_time']}). Highest: "
            f"{top['pm25_ug_m3']} µg/m³, {top['provenance_class']} by {top['source']} at "
            f"{top['observed_at']}. {_band(top)}"
        ).strip()
    return (
        f"PM2.5 near {result['place']}: {result['pm25_ug_m3']} µg/m³, "
        f"{result['provenance_class']} by {result['source']} at {result['observed_at']} "
        f"({result['distance_km']} km away). {_band(result)}"
    ).strip()


def _fires(result: dict[str, Any]) -> str:
    if (problem := _not_ok(result)) is not None:
        return problem
    clusters = result.get("clusters", [])
    if not clusters:
        return f"No fire clusters near {result['place']} in this cycle. {result.get('note', '')}"
    lines = [
        f"{result['cluster_count']} fire cluster(s), {result['detection_count']} detection(s), "
        f"{result['total_frp_mw']} MW total FRP ({result['source']}, measured)."
    ]
    origin = "the map centre" if result.get("scope") == "region" else result["place"]
    for cluster in clusters[:3]:
        lines.append(
            f"• {cluster['frp_total_mw']} MW, {cluster['distance_km']} km from {origin} at bearing "
            f"{cluster['bearing_from_place_degrees']}°, seen {cluster['observed_at']}."
        )
    lines.append(result.get("note", ""))
    return "\n".join(line for line in lines if line)


def _events(result: dict[str, Any]) -> str:
    if (problem := _not_ok(result)) is not None:
        return problem
    events = result.get("events", [])
    if not events:
        return "No open pollution events in this region."
    lines = [f"{result['total']} open event(s), from deterministic rules over measured inputs:"]
    for event in events[:5]:
        lines.append(
            f"• {event['event_id']}: {event['event_status']}, {event['severity']}, "
            f"detection confidence {event['detection_confidence']}."
        )
    return "\n".join(lines)


def _incident(result: dict[str, Any]) -> str:
    if (problem := _not_ok(result)) is not None:
        return problem
    lines = [
        f"Incident {result['incident_id']} (root: {result['root_kind']}), since {result['first_seen']}."
    ]
    forward = result.get("plumes", {}).get("plumes", [])
    if forward:
        plume = forward[0]
        lines.append(
            f"Forward plume {plume['plume_id']}: {plume['label']} ({plume['provenance_class']}, "
            f"{plume['model_version']})."
        )
    backward = result.get("back_trajectory", {}).get("plumes", [])
    if backward:
        lines.append(f"Back trajectory: {backward[0]['interpretation']}")
    likelihood = result.get("source_likelihood", {})
    ranking = (likelihood.get("cells") or [{}])[0].get("ranking") or []
    if likelihood.get("status") == "ok" and ranking:
        top = ranking[0]
        lines.append(
            f"Leading source class: {top['display_name']} (score {top['score']}). "
            f"{likelihood['interpretation']}"
        )
    elif likelihood.get("message"):
        lines.append(f"Source likelihood: {likelihood['message']}")
    if result.get("satellite", {}).get("status") == "unavailable":
        lines.append(f"Satellite: {result['satellite']['reason']}")
    return "\n".join(lines)


def _incidents(result: dict[str, Any]) -> str:
    if (problem := _not_ok(result)) is not None:
        return problem
    incidents = result.get("incidents", [])
    if not incidents:
        return "No open incidents in this region."
    lines = [f"{result['total']} open incident(s):"]
    for incident in incidents[:5]:
        lines.append(
            f"• {incident['incident_id']}: root {incident['root_kind']}, "
            f"{incident['node_count']} linked nodes, updated {incident['observed_at']}."
        )
    return "\n".join(lines)


def _context(result: dict[str, Any]) -> str:
    if (problem := _not_ok(result)) is not None:
        return problem
    hazards = ", ".join(h["display_name"] for h in result.get("hazards", []))
    snapshot = result.get("snapshot")
    state = f"latest cycle {snapshot['cycle_time']}" if snapshot else f"{result['snapshot_reason']}"
    return (
        f"{result['display_name']}: {result['aqi_standard']['name']}; hazards {hazards}; {state}. "
        "Ask about air quality, fires, events or incidents."
    )


def region_answer(question: str, ctx: ToolContext) -> RegionAnswer | None:
    """A tool-backed answer for the context's region, or ``None`` with no region data."""
    if ctx.regions is None or ctx.region_id is None:
        return None
    ledger = ToolLedger()
    # The API appends "(Selected incident: …)" to every question asked from an
    # incident, so a topic in the question itself wins over the selection.
    asked = question.split("(Selected incident:")[0]
    incident = _INCIDENT_ID.search(question)
    if _FIRE.search(asked):
        text = _fires(
            _call(ledger, "get_active_fires", get_active_fires, ctx, place=_place(question, ctx))
        )
    elif _EVENT.search(asked):
        text = _events(_call(ledger, "list_active_events", list_active_events, ctx))
    elif _AIR.search(asked):
        text = _air(
            _call(ledger, "get_current_aqi", get_current_aqi, ctx, place=_place(question, ctx))
        )
    elif incident is not None:
        text = _incident(
            _call(ledger, "explain_incident", explain_incident, ctx, incident_id=incident.group(0))
        )
    elif _INCIDENT.search(asked):
        text = _incidents(_call(ledger, "list_incidents", list_incidents, ctx))
    else:
        text = _context(_call(ledger, "get_region_context", get_region_context, ctx))
    return RegionAnswer(
        answer=text,
        ledger=ledger,
        evidence=ledger.sources(),
        tool_calls=[{"name": c.name, "arguments": c.arguments} for c in ledger.calls],
    )
