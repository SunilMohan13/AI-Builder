"""The copilot's only route to a number.

Every fact in an answer must come from one of these functions. The model is
never given raw data in its prompt and has no other way to obtain a value, so
"did this number come from the system?" reduces to "is it in the tool
ledger?" — which is what :mod:`aeropulse_copilot.grounding` then checks.

Each result carries its own ``observed_at``, ``region_id`` and
``provenance_class``, because a number without a time, a place and a class is
exactly the kind of confident-sounding output this platform is built to avoid.

The six original tools answer from a region snapshot when one exists
(:mod:`aeropulse_copilot.region_tools`) and fall back to the legacy
``in-north`` readers otherwise.
"""

from __future__ import annotations

from typing import Any

from aeropulse_contracts.event import EventStatus
from aeropulse_contracts.snapshot import RegionSnapshot
from aeropulse_geospatial.gazetteer import Place, known_places, resolve_place
from aeropulse_geospatial.grid import neighbors
from aeropulse_intelligence.geometry import haversine_km

from aeropulse_copilot.context import (
    DEFAULT_STALE_AFTER_MINUTES,
    EventReaderLike,
    GridReaderLike,
    MapReaderLike,
    RegionData,
    SeriesPoint,
    ToolCall,
    ToolContext,
    ToolLedger,
    iso,
    staleness,
)
from aeropulse_copilot.region_tools import (
    LEGACY_REGION,
    REGION_TOOLS,
    Located,
    describe_region_tools,
    locate,
    snapshot_air_quality,
    snapshot_fires,
    snapshot_hazard,
    snapshot_weather,
)

__all__ = [
    "CPCB_PM25_BANDS",
    "DEFAULT_STALE_AFTER_MINUTES",
    "TOOLS",
    "EventReaderLike",
    "GridReaderLike",
    "MapReaderLike",
    "RegionData",
    "SeriesPoint",
    "ToolCall",
    "ToolContext",
    "ToolLedger",
    "cpcb_band",
    "describe_tools",
    "explain_event",
    "get_active_fires",
    "get_air_quality",
    "get_hazard_outlook",
    "get_wind",
    "list_active_events",
]

CPCB_NAME = "CPCB National Air Quality Index (India)"

#: CPCB National Air Quality Index breakpoints for PM2.5 (24-hour, ug/m3).
#: India's scale, not the US EPA one: the same 150 ug/m3 is "Unhealthy" on the
#: US scale and "Moderate" here, so using the wrong table misstates risk.
#: The legacy ``in-north`` path only; snapshot answers use the region's pack.
CPCB_PM25_BANDS: tuple[tuple[float, float, str], ...] = (
    (0.0, 30.0, "Good"),
    (30.0, 60.0, "Satisfactory"),
    (60.0, 90.0, "Moderate"),
    (90.0, 120.0, "Poor"),
    (120.0, 250.0, "Very Poor"),
    (250.0, float("inf"), "Severe"),
)


def cpcb_band(pm25: float) -> str:
    """Return the CPCB NAQI band label for a PM2.5 concentration."""
    for low, high, label in CPCB_PM25_BANDS:
        if low <= pm25 < high:
            return label
    return "Severe"


def _unknown_place(place: str) -> dict[str, Any]:
    """The only acceptable answer for a place outside the gazetteer."""
    return {
        "status": "unknown_location",
        "requested": place,
        "message": (
            f"{place!r} is not a location AeroPulse covers. The monitored area is the "
            "Punjab-Haryana-Delhi NCR corridor."
        ),
        "known_locations": known_places(),
    }


def _resolve(place: str) -> Place | None:
    return resolve_place(place)


def _route(
    place: str, region_id: str | None, ctx: ToolContext
) -> tuple[Located, RegionSnapshot] | dict[str, Any] | None:
    """The snapshot to answer from, an error to return, or ``None`` for the legacy path."""
    if ctx.regions is None:
        if region_id not in (None, LEGACY_REGION):
            return {
                "status": "not_configured",
                "region_id": region_id,
                "reason": "no region data configured",
            }
        return None
    loc = locate(place, region_id, ctx)
    if isinstance(loc, dict):
        return loc
    snapshot = ctx.regions.snapshot(loc.region_id)
    if snapshot is not None:
        return loc, snapshot
    if loc.region_id == LEGACY_REGION and loc.kind == "place":
        return None
    return {
        "status": "not_configured",
        "region_id": loc.region_id,
        "place": loc.name,
        "reason": "no cycle snapshot has been written for this region yet",
    }


def _legacy(body: dict[str, Any], provenance_class: str | None) -> dict[str, Any]:
    return {"region_id": LEGACY_REGION, **body, "provenance_class": provenance_class}


def get_air_quality(
    place: str, region_id: str | None = None, *, ctx: ToolContext
) -> dict[str, Any]:
    """Return the most recent measured air quality for a place.

    Args:
        place: A city, district or area, for example "Delhi" or "Singapore".
        region_id: Optional region id.

    Returns:
        Current PM2.5 with the region's AQI band, the observation time, and
        whether that reading is stale.
    """
    routed = _route(place, region_id, ctx)
    if isinstance(routed, dict):
        return routed
    if routed is not None:
        return snapshot_air_quality(*routed, ctx)
    resolved = _resolve(place)
    if resolved is None:
        return _unknown_place(place)
    if ctx.grid is None:
        return {"status": "unavailable", "reason": "no grid reader configured"}

    feature = ctx.grid.latest_feature(resolved.grid_id)
    if feature is None:
        for cell in neighbors(resolved.grid_id, 2):
            feature = ctx.grid.latest_feature(cell)
            if feature is not None:
                break
    if feature is None:
        return {
            "status": "no_data",
            "place": resolved.name,
            "message": f"No air quality observation is available for {resolved.name}.",
        }

    pm25 = getattr(feature, "pm25", None)
    timing = staleness(getattr(feature, "timestamp", None), ctx)
    return _legacy(
        {
            "status": "ok",
            "place": resolved.name,
            "state": resolved.state,
            "grid_id": getattr(feature, "grid_id", resolved.grid_id),
            "pm25_ug_m3": pm25,
            "pm10_ug_m3": getattr(feature, "pm10", None),
            "cpcb_band": cpcb_band(pm25) if pm25 is not None else None,
            "aqi_band": cpcb_band(pm25) if pm25 is not None else None,
            "aqi_standard": CPCB_NAME,
            "index_scale": CPCB_NAME,
            "source": "AeroPulse fused grid feature",
            "provenance_reason": "the fused grid feature does not record station vs CAMS",
            **timing,
        },
        None,
    )


def get_wind(place: str, region_id: str | None = None, *, ctx: ToolContext) -> dict[str, Any]:
    """Return current wind speed and direction for a place.

    Args:
        place: A city or district.
        region_id: Optional region id.

    Returns:
        Wind speed in m/s, the compass direction it blows from and towards,
        and the observation time.
    """
    routed = _route(place, region_id, ctx)
    if isinstance(routed, dict):
        return routed
    if routed is not None:
        return snapshot_weather(*routed, ctx)
    resolved = _resolve(place)
    if resolved is None:
        return _unknown_place(place)
    if ctx.grid is None:
        return {"status": "unavailable", "reason": "no grid reader configured"}

    feature = ctx.grid.latest_feature(resolved.grid_id)
    if feature is None:
        return {
            "status": "no_data",
            "place": resolved.name,
            "message": f"No wind observation is available for {resolved.name}.",
        }
    wind_from = getattr(feature, "wind_direction", None)
    return _legacy(
        {
            "status": "ok",
            "place": resolved.name,
            "wind_speed_ms": getattr(feature, "wind_speed", None),
            # GridFeature.wind_direction is the bearing the wind blows *from*
            # (features.py sets it from wdir_from). The "towards" bearing is the
            # reciprocal, and is what matters for transport questions.
            "wind_from_degrees": wind_from,
            "wind_towards_degrees": None if wind_from is None else (wind_from + 180.0) % 360.0,
            "boundary_layer_height_m": getattr(feature, "boundary_layer_height", None),
            "source": "AeroPulse fused grid feature",
            **staleness(getattr(feature, "timestamp", None), ctx),
        },
        "model_derived",
    )


def get_active_fires(
    place: str, radius_km: float = 100.0, region_id: str | None = None, *, ctx: ToolContext
) -> dict[str, Any]:
    """Return satellite-detected active fires near a place.

    Args:
        place: A city or district.
        radius_km: Search radius in kilometres.
        region_id: Optional region id.

    Returns:
        The number of detections, their total fire radiative power, and the
        closest few with distance and detection time.
    """
    routed = _route(place, region_id, ctx)
    if isinstance(routed, dict):
        return routed
    if routed is not None:
        return snapshot_fires(routed[0], routed[1], float(radius_km), ctx)
    resolved = _resolve(place)
    if resolved is None:
        return _unknown_place(place)
    if ctx.map is None:
        return {"status": "unavailable", "reason": "no map reader configured"}

    detections: list[dict[str, Any]] = []
    for feature in ctx.map.fire(None, 500):
        geometry = (feature or {}).get("geometry") or {}
        coords = geometry.get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        distance = haversine_km(resolved.lat, resolved.lon, lat, lon)
        if distance > radius_km:
            continue
        properties = (feature or {}).get("properties") or {}
        detections.append(
            {
                "distance_km": round(distance, 1),
                "frp_mw": properties.get("frp"),
                "confidence": properties.get("confidence"),
                "observed_at": properties.get("observed_at"),
                "source": "NASA FIRMS",
            }
        )

    detections.sort(key=lambda d: d["distance_km"])
    total_frp = sum(d["frp_mw"] or 0.0 for d in detections)
    return _legacy(
        {
            "status": "ok",
            "place": resolved.name,
            "radius_km": radius_km,
            "fire_count": len(detections),
            "total_frp_mw": round(total_frp, 1) if detections else 0.0,
            "nearest": detections[:5],
            "source": "NASA FIRMS",
        },
        "measured",
    )


def get_hazard_outlook(
    place: str, region_id: str | None = None, *, ctx: ToolContext
) -> dict[str, Any]:
    """Return the 24-hour hazard outlook for a place.

    Args:
        place: A city or district.
        region_id: Optional region id.

    Returns:
        The hazard score with its provenance, including whether it came from
        a calibrated model or a deterministic baseline.
    """
    routed = _route(place, region_id, ctx)
    if isinstance(routed, dict):
        return routed
    if routed is not None:
        return snapshot_hazard(*routed, ctx)
    resolved = _resolve(place)
    if resolved is None:
        return _unknown_place(place)
    if ctx.hazard_cells is None or ctx.grid is None:
        return {"status": "unavailable", "reason": "no hazard reader configured"}

    feature = ctx.grid.latest_feature(resolved.grid_id)
    if feature is None:
        return {
            "status": "no_data",
            "place": resolved.name,
            "message": f"No hazard outlook is available for {resolved.name}.",
        }

    cells, provenance = ctx.hazard_cells([feature])
    if not cells:
        return {
            "status": "no_data",
            "place": resolved.name,
            "message": (
                f"No hazard score could be computed for {resolved.name}; the cell has "
                "no PM2.5 observation."
            ),
        }
    cell = cells[0]
    calibrated = bool(getattr(cell, "calibrated", False))
    return _legacy(
        {
            "status": "ok",
            "place": resolved.name,
            "aqi_standard": CPCB_NAME,
            "hazard_score": getattr(cell, "hazard_score", None),
            "horizon_hours": getattr(cell, "horizon_hours", None),
            "calibrated": calibrated,
            "degraded": bool(getattr(cell, "degraded", True)),
            "model_version": getattr(cell, "model_version", None),
            "provenance_reason": (provenance or {}).get("reason"),
            "interpretation": (
                "Calibrated probability of exceeding the hazard threshold."
                if calibrated
                else (
                    "This score ranks cells by relative risk. It is not a probability, "
                    "because the model is uncalibrated."
                )
            ),
            "source": "AeroPulse hazard outlook",
            **staleness(getattr(feature, "timestamp", None), ctx),
        },
        "predicted",
    )


def _event_status(status: str | EventStatus | None) -> tuple[EventStatus | None, str | None]:
    """Turn a model-supplied status string into the enum the reader expects.

    The event reader reads ``status.value``. A raw ``ACTIVE`` string crashes
    that lookup, so the tool converts here and reports an unknown value as a
    tool error the model can read.
    """
    if status is None or (isinstance(status, str) and not status.strip()):
        return None, None
    if isinstance(status, EventStatus):
        return status, None
    try:
        return EventStatus(str(status).strip().upper()), None
    except ValueError:
        allowed = ", ".join(member.value for member in EventStatus)
        return None, f"Unknown event status {status!r}. Use one of: {allowed}."


def _snapshot_events(region_id: str | None, ctx: ToolContext) -> RegionSnapshot | dict | None:
    """The snapshot whose events answer, or ``None`` to use the context's event reader.

    The reader belongs to ``ctx.region_id``; any other region, or a context
    without a reader, answers from that region's snapshot.
    """
    target = region_id or ctx.region_id
    if ctx.regions is None or target is None:
        return None
    if target == ctx.region_id and ctx.events is not None:
        return None
    if target not in ctx.regions.catalog.packs:
        return {
            "status": "unknown_region",
            "requested": target,
            "known_regions": sorted(ctx.regions.catalog.packs),
        }
    snapshot = ctx.regions.snapshot(target)
    if snapshot is None:
        return {
            "status": "not_configured",
            "region_id": target,
            "reason": "no cycle snapshot has been written for this region yet",
        }
    return snapshot


def list_active_events(
    status: str | None = None, region_id: str | None = None, *, ctx: ToolContext
) -> dict[str, Any]:
    """Return current pollution events the system has detected.

    Args:
        status: Optional status filter, for example "ACTIVE".
        region_id: Optional region id; defaults to the request's region.

    Returns:
        Open events with their severity, confidence and affected cell.
    """
    wanted, error = _event_status(status)
    if error is not None:
        return {"status": "bad_arguments", "name": "list_active_events", "detail": error}
    other = _snapshot_events(region_id, ctx)
    if isinstance(other, dict):
        return other
    if other is not None:
        matching = [e for e in other.events if wanted is None or e.status == wanted]
        events, total = matching[:20], len(matching)
    elif ctx.events is None:
        return {"status": "unavailable", "reason": "no event reader configured"}
    else:
        events, total = ctx.events.list_events(wanted, 20, 0)
    return {
        "status": "ok",
        "region_id": region_id or ctx.region_id or LEGACY_REGION,
        "total": total,
        "events": [
            {
                "event_id": getattr(event, "event_id", None),
                "event_status": getattr(getattr(event, "status", None), "value", None),
                "severity": getattr(getattr(event, "severity", None), "value", None),
                "grid_id": getattr(event, "grid_id", None),
                "detection_confidence": getattr(event, "detection_confidence", None),
                "overall_confidence": getattr(event, "overall_confidence", None),
                "observed_at": iso(getattr(event, "detected_at", None)),
                "source": "AeroPulse event engine",
            }
            for event in events
        ],
        "provenance_class": "heuristic",
        "provenance_note": "Events come from deterministic rules over measured inputs.",
    }


def explain_event(event_id: str, *, ctx: ToolContext) -> dict[str, Any]:
    """Return the evidence behind one detected pollution event.

    Args:
        event_id: The event identifier, for example "EVT-1024".

    Returns:
        The event's confidences plus every piece of supporting evidence.
    """
    event: Any = None
    evidence: list[Any] = []
    event_region = ctx.region_id or LEGACY_REGION
    if ctx.events is not None:
        event = ctx.events.get_event(event_id)
        evidence = (ctx.events.get_evidence(event_id) or []) if event is not None else []
    if event is None and ctx.regions is not None:
        for rid in sorted(ctx.regions.catalog.packs):
            snapshot = ctx.regions.snapshot(rid)
            match = next(
                (e for e in (snapshot.events if snapshot else []) if e.event_id == event_id), None
            )
            if match is not None:
                event, event_region = match, rid
                break
    if event is None:
        if ctx.events is None and ctx.regions is None:
            return {"status": "unavailable", "reason": "no event reader configured"}
        return {"status": "not_found", "event_id": event_id}
    return {
        "status": "ok",
        "event_id": event_id,
        "region_id": event_region,
        "event_status": getattr(getattr(event, "status", None), "value", None),
        "severity": getattr(getattr(event, "severity", None), "value", None),
        "grid_id": getattr(event, "grid_id", None),
        "detection_confidence": getattr(event, "detection_confidence", None),
        "source_confidence": getattr(event, "source_confidence", None),
        "forecast_confidence": getattr(event, "forecast_confidence", None),
        "overall_confidence": getattr(event, "overall_confidence", None),
        "observed_at": iso(getattr(event, "detected_at", None)),
        "source": "AeroPulse event engine",
        "provenance_class": "heuristic",
        "evidence": [
            {
                "type": getattr(item, "evidence_type", None),
                "summary": getattr(item, "summary", None),
                "observed_at": iso(getattr(item, "observed_at", None)),
                "source": getattr(item, "source_id", "AeroPulse evidence"),
            }
            for item in evidence
        ],
    }


#: Tool name -> callable. The model may call nothing else.
TOOLS = {
    "get_air_quality": get_air_quality,
    "get_wind": get_wind,
    "get_active_fires": get_active_fires,
    "get_hazard_outlook": get_hazard_outlook,
    "list_active_events": list_active_events,
    "explain_event": explain_event,
    **REGION_TOOLS,
}


def describe_tools() -> list[dict[str, Any]]:
    """Return JSON-schema declarations for every tool.

    Written by hand rather than derived from signatures because the model
    reads these descriptions to decide what to call, and they need to be
    phrased for that audience.
    """
    place_arg = {
        "type": "string",
        "description": ("City, district or area, e.g. 'Delhi', 'Ludhiana', 'Singapore', 'Sydney'."),
    }
    region_arg = {
        "type": "string",
        "description": "Optional region id, e.g. 'in-north', 'sg-singapore', 'au-nsw'.",
    }
    return [
        {
            "name": "get_air_quality",
            "description": (
                "Current PM2.5 for a place, with the band in that region's AQI standard "
                "and how old the reading is. Use for any question about air quality, "
                "pollution levels, AQI or how bad the air is."
            ),
            "parameters": {
                "type": "object",
                "properties": {"place": place_arg, "region_id": region_arg},
                "required": ["place"],
            },
        },
        {
            "name": "get_wind",
            "description": (
                "Current wind speed and the direction it blows from and towards for a "
                "place. Use for questions about wind, transport direction, or where "
                "pollution is heading."
            ),
            "parameters": {
                "type": "object",
                "properties": {"place": place_arg, "region_id": region_arg},
                "required": ["place"],
            },
        },
        {
            "name": "get_active_fires",
            "description": (
                "Satellite-detected active fires near a place, with count, total fire "
                "radiative power, distances and bearings. Use for questions about fires, "
                "stubble or crop burning."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "place": place_arg,
                    "radius_km": {
                        "type": "number",
                        "description": "Search radius in km. Defaults to 100.",
                    },
                    "region_id": region_arg,
                },
                "required": ["place"],
            },
        },
        {
            "name": "get_hazard_outlook",
            "description": (
                "24-hour hazard outlook for a place, including whether the score comes "
                "from a calibrated model or a deterministic baseline. Use for questions "
                "about risk, threat, hazard or what happens next."
            ),
            "parameters": {
                "type": "object",
                "properties": {"place": place_arg, "region_id": region_arg},
                "required": ["place"],
            },
        },
        {
            "name": "list_active_events",
            "description": (
                "Pollution events the system has currently detected, with severity and "
                "confidence. Use for 'what is happening now' questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Optional status filter, e.g. 'ACTIVE'.",
                    },
                    "region_id": region_arg,
                },
            },
        },
        {
            "name": "explain_event",
            "description": (
                "All supporting evidence behind one detected event. Use when the user "
                "names an event id or asks why an event was raised."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "Event id, e.g. 'EVT-1024'."}
                },
                "required": ["event_id"],
            },
        },
        *describe_region_tools(),
    ]
