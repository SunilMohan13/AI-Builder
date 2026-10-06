"""The copilot's only route to a number.

Every fact in an answer must come from one of these functions. The model is
never given raw data in its prompt and has no other way to obtain a value, so
"did this number come from the system?" reduces to "is it in the tool
ledger?" — which is what :mod:`aeropulse_copilot.grounding` then checks.

Each result carries its own ``observed_at`` and provenance, because a number
without a time and a model version is exactly the kind of confident-sounding
output this platform is built to avoid.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from aeropulse_contracts.event import EventStatus
from aeropulse_geospatial.gazetteer import Place, known_places, resolve_place
from aeropulse_geospatial.grid import neighbors
from aeropulse_intelligence.geometry import haversine_km

#: A cell whose newest observation is older than this is reported as stale
#: rather than presented as current conditions.
DEFAULT_STALE_AFTER_MINUTES = 90

#: CPCB National Air Quality Index breakpoints for PM2.5 (24-hour, ug/m3).
#: India's scale, not the US EPA one: the same 150 ug/m3 is "Unhealthy" on the
#: US scale and "Moderate" here, so using the wrong table misstates risk.
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


class GridReaderLike(Protocol):
    """The subset of the API's grid reader the tools need."""

    def latest_feature(self, grid_id: str) -> Any: ...


class MapReaderLike(Protocol):
    """The subset of the API's map reader the tools need."""

    def air_quality(self, bbox: list[float] | None, limit: int) -> list[dict]: ...

    def fire(self, bbox: list[float] | None, limit: int) -> list[dict]: ...

    def weather(self, bbox: list[float] | None, limit: int) -> list[dict]: ...


class EventReaderLike(Protocol):
    """The subset of the API's event reader the tools need."""

    def list_events(
        self, status: EventStatus | None, limit: int, offset: int
    ) -> tuple[list[Any], int]: ...

    def get_event(self, event_id: str) -> Any: ...

    def get_evidence(self, event_id: str) -> list[Any]: ...


@dataclass
class ToolContext:
    """Readers and settings the tools resolve data through.

    Holding these rather than importing module-level singletons is what lets
    the copilot read exactly the same live data the REST API serves, instead
    of the in-memory seed the old implementation was pinned to.
    """

    grid: GridReaderLike | None = None
    map: MapReaderLike | None = None
    events: EventReaderLike | None = None
    hazard_cells: Any = None
    peak_forecasts: Any = None
    now: Callable[[], datetime] | None = None
    stale_after_minutes: int = DEFAULT_STALE_AFTER_MINUTES

    def clock(self) -> datetime:
        """Current time, injectable for deterministic tests."""
        return self.now() if self.now is not None else datetime.now(UTC)


@dataclass
class ToolCall:
    """One tool invocation and what it returned.

    Attributes:
        name: Tool name.
        arguments: Arguments the model supplied.
        result: The returned payload, recorded verbatim for grounding.
    """

    name: str
    arguments: dict[str, Any]
    result: Any


@dataclass
class ToolLedger:
    """Every tool call made while answering one question."""

    calls: list[ToolCall] = field(default_factory=list)

    def record(self, name: str, arguments: dict[str, Any], result: Any) -> None:
        """Append a call and its result."""
        self.calls.append(ToolCall(name=name, arguments=dict(arguments), result=result))

    def sources(self) -> list[dict[str, str]]:
        """Distinct evidence citations across every call."""
        seen: dict[tuple[str, str], dict[str, str]] = {}
        for call in self.calls:
            for citation in _citations(call.result):
                key = (citation.get("source", ""), citation.get("time", ""))
                seen.setdefault(key, citation)
        return list(seen.values())


def _citations(payload: Any) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    if isinstance(payload, dict):
        if "source" in payload and "observed_at" in payload:
            found.append(
                {"source": str(payload["source"]), "time": str(payload["observed_at"] or "")}
            )
        for value in payload.values():
            found.extend(_citations(value))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(_citations(item))
    return found


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


def _staleness(observed_at: datetime | None, ctx: ToolContext) -> dict[str, Any]:
    if observed_at is None:
        return {"observed_at": None, "age_minutes": None, "stale": True}
    now = ctx.clock()
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    age = (now - observed_at).total_seconds() / 60.0
    return {
        "observed_at": observed_at.isoformat(),
        "age_minutes": round(age, 1),
        "stale": age > ctx.stale_after_minutes,
    }


def _resolve(place: str) -> Place | None:
    return resolve_place(place)


def get_air_quality(place: str, *, ctx: ToolContext) -> dict[str, Any]:
    """Return the most recent measured air quality for a place.

    Args:
        place: A city, district or area in the Punjab-Haryana-Delhi corridor,
            for example "Delhi", "Ludhiana" or "Gurugram".

    Returns:
        Current PM2.5 and PM10 with the CPCB index band, the observation
        time, and whether that reading is stale.
    """
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
    timing = _staleness(getattr(feature, "timestamp", None), ctx)
    return {
        "status": "ok",
        "place": resolved.name,
        "state": resolved.state,
        "grid_id": getattr(feature, "grid_id", resolved.grid_id),
        "pm25_ug_m3": pm25,
        "pm10_ug_m3": getattr(feature, "pm10", None),
        "cpcb_band": cpcb_band(pm25) if pm25 is not None else None,
        "index_scale": "CPCB National Air Quality Index (India)",
        "source": "AeroPulse fused grid feature",
        **timing,
    }


def get_wind(place: str, *, ctx: ToolContext) -> dict[str, Any]:
    """Return current wind speed and direction for a place.

    Args:
        place: A city or district in the monitored corridor.

    Returns:
        Wind speed in m/s, the compass direction it blows from and towards,
        and the observation time.
    """
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
    return {
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
        **_staleness(getattr(feature, "timestamp", None), ctx),
    }


def get_active_fires(place: str, radius_km: float = 100.0, *, ctx: ToolContext) -> dict[str, Any]:
    """Return satellite-detected active fires near a place.

    Args:
        place: A city or district in the monitored corridor.
        radius_km: Search radius in kilometres.

    Returns:
        The number of detections, their total fire radiative power, and the
        closest few with distance and detection time.
    """
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
    return {
        "status": "ok",
        "place": resolved.name,
        "radius_km": radius_km,
        "fire_count": len(detections),
        "total_frp_mw": round(total_frp, 1) if detections else 0.0,
        "nearest": detections[:5],
        "source": "NASA FIRMS",
    }


def get_hazard_outlook(place: str, *, ctx: ToolContext) -> dict[str, Any]:
    """Return the 24-hour hazard outlook for a place.

    Args:
        place: A city or district in the monitored corridor.

    Returns:
        The hazard score with its provenance, including whether it came from
        a calibrated model or a deterministic baseline.
    """
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
    return {
        "status": "ok",
        "place": resolved.name,
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
        **_staleness(getattr(feature, "timestamp", None), ctx),
    }


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


def list_active_events(status: str | None = None, *, ctx: ToolContext) -> dict[str, Any]:
    """Return current pollution events the system has detected.

    Args:
        status: Optional status filter, for example "ACTIVE".

    Returns:
        Open events with their severity, confidence and affected cell.
    """
    if ctx.events is None:
        return {"status": "unavailable", "reason": "no event reader configured"}
    wanted, error = _event_status(status)
    if error is not None:
        return {"status": "bad_arguments", "name": "list_active_events", "detail": error}
    events, total = ctx.events.list_events(wanted, 20, 0)
    return {
        "status": "ok",
        "total": total,
        "events": [
            {
                "event_id": getattr(event, "event_id", None),
                "event_status": getattr(getattr(event, "status", None), "value", None),
                "severity": getattr(getattr(event, "severity", None), "value", None),
                "grid_id": getattr(event, "grid_id", None),
                "detection_confidence": getattr(event, "detection_confidence", None),
                "overall_confidence": getattr(event, "overall_confidence", None),
                "observed_at": _iso(getattr(event, "detected_at", None)),
                "source": "AeroPulse event engine",
            }
            for event in events
        ],
    }


def explain_event(event_id: str, *, ctx: ToolContext) -> dict[str, Any]:
    """Return the evidence behind one detected pollution event.

    Args:
        event_id: The event identifier, for example "EVT-1024".

    Returns:
        The event's confidences plus every piece of supporting evidence.
    """
    if ctx.events is None:
        return {"status": "unavailable", "reason": "no event reader configured"}
    event = ctx.events.get_event(event_id)
    if event is None:
        return {"status": "not_found", "event_id": event_id}
    evidence = ctx.events.get_evidence(event_id) or []
    return {
        "status": "ok",
        "event_id": event_id,
        "event_status": getattr(getattr(event, "status", None), "value", None),
        "severity": getattr(getattr(event, "severity", None), "value", None),
        "grid_id": getattr(event, "grid_id", None),
        "detection_confidence": getattr(event, "detection_confidence", None),
        "source_confidence": getattr(event, "source_confidence", None),
        "forecast_confidence": getattr(event, "forecast_confidence", None),
        "overall_confidence": getattr(event, "overall_confidence", None),
        "observed_at": _iso(getattr(event, "detected_at", None)),
        "source": "AeroPulse event engine",
        "evidence": [
            {
                "type": getattr(item, "evidence_type", None),
                "summary": getattr(item, "summary", None),
                "observed_at": _iso(getattr(item, "observed_at", None)),
                "source": getattr(item, "source_id", "AeroPulse evidence"),
            }
            for item in evidence
        ],
    }


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


#: Tool name -> callable. The model may call nothing else.
TOOLS = {
    "get_air_quality": get_air_quality,
    "get_wind": get_wind,
    "get_active_fires": get_active_fires,
    "get_hazard_outlook": get_hazard_outlook,
    "list_active_events": list_active_events,
    "explain_event": explain_event,
}


def describe_tools() -> list[dict[str, Any]]:
    """Return JSON-schema declarations for every tool.

    Written by hand rather than derived from signatures because the model
    reads these descriptions to decide what to call, and they need to be
    phrased for that audience.
    """
    place_arg = {
        "type": "string",
        "description": (
            "City or district in the Punjab-Haryana-Delhi NCR corridor, "
            "e.g. 'Delhi', 'Ludhiana', 'Gurugram'."
        ),
    }
    return [
        {
            "name": "get_air_quality",
            "description": (
                "Current measured PM2.5 and PM10 for a place, with the CPCB index band "
                "and how old the reading is. Use for any question about air quality, "
                "pollution levels, AQI or how bad the air is."
            ),
            "parameters": {
                "type": "object",
                "properties": {"place": place_arg},
                "required": ["place"],
            },
        },
        {
            "name": "get_wind",
            "description": (
                "Current wind speed, the direction it blows from and towards, and the "
                "boundary layer height for a place. Use for questions about wind, "
                "transport direction, or where pollution is heading."
            ),
            "parameters": {
                "type": "object",
                "properties": {"place": place_arg},
                "required": ["place"],
            },
        },
        {
            "name": "get_active_fires",
            "description": (
                "Satellite-detected active fires near a place, with count, total fire "
                "radiative power and distances. Use for questions about fires, stubble "
                "or crop burning."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "place": place_arg,
                    "radius_km": {
                        "type": "number",
                        "description": "Search radius in km. Defaults to 100.",
                    },
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
                "properties": {"place": place_arg},
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
                    }
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
    ]
