"""Region-aware tools (LLD APAC 11.2).

Every value these return was already computed and stored: a cycle snapshot,
the plume store, analytics history or the citizen store. Nothing here runs a
model or simulation. Results name their ``region_id``, the region's AQI
standard where a band is shown, and the ``provenance_class`` of each figure,
so the model can label simulated, heuristic and AI-observation values and the
grounding validator can check that it did.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from aeropulse_contracts.graph import IncidentSummary
from aeropulse_contracts.plume import Plume, PlumeSummary
from aeropulse_contracts.snapshot import CellState, RegionSnapshot, WindVector
from aeropulse_geospatial.gazetteer import known_places, resolve_place
from aeropulse_geospatial.grid import grid_center
from aeropulse_intelligence.geometry import haversine_km
from aeropulse_regions import RegionPack

from aeropulse_copilot.context import SeriesPoint, ToolContext, iso, staleness

#: How far from a place a cell, station or report may be and still answer for it.
NEAR_KM = 25.0
#: The only region with a legacy (pre-snapshot) gazetteer and readers.
LEGACY_REGION = "in-north"
MAX_TREND_HOURS = 72
MAX_QUERY_DAYS = 7
QUERY_ROW_LIMIT = 500
CITIZEN_LOOKBACK = timedelta(days=7)
MAX_PLUMES = 3
MAX_GRAPH_NODES = 60
MAX_GRAPH_EDGES = 120
PLUME_LABEL = "Predicted smoke transport — experimental"
AI_OBSERVATION_LABEL = "AI observation — requires corroboration"

#: ``query_trends`` templates. Each maps to a reviewed, parameter-only
#: analytics template in ``aeropulse_storage.analytics`` (``raw.air_quality.window``);
#: place names resolve to coordinates here and never reach SQL.
QUERY_TEMPLATES: dict[str, str] = {
    "pm25_hourly": "Hourly PM2.5 at the stations nearest a place, or the region median.",
}


@dataclass(frozen=True)
class Located:
    """A place or a whole region a question is about."""

    region_id: str
    name: str
    lat: float
    lon: float
    kind: Literal["place", "region"]
    radius_km: float = NEAR_KM


def _unavailable(reason: str) -> dict[str, Any]:
    return {"status": "unavailable", "reason": reason}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.casefold())).strip()


def _region_order(region_id: str | None, ctx: ToolContext) -> list[str] | dict[str, Any]:
    assert ctx.regions is not None
    packs = ctx.regions.catalog.packs
    if region_id:
        if region_id not in packs:
            return {
                "status": "unknown_region",
                "requested": region_id,
                "known_regions": sorted(packs),
            }
        return [region_id]
    first = ctx.region_id if ctx.region_id in packs else None
    rest = [r for r in sorted(packs) if r != first]
    return [first, *rest] if first else rest


def _names_region(key: str, pack: RegionPack) -> bool:
    if key in (pack.region_id.casefold(), _norm(pack.display_name)):
        return True
    return (
        len(key) >= 4 and re.search(rf"\b{re.escape(key)}\b", _norm(pack.display_name)) is not None
    )


def _unknown_place(place: str, order: Sequence[str], ctx: ToolContext) -> dict[str, Any]:
    assert ctx.regions is not None
    catalog = ctx.regions.catalog
    names: list[str] = []
    for rid in order:
        names.extend(p.name for p in ctx.regions.places(rid))
        if rid == LEGACY_REGION:
            names.extend(known_places())
    covered = [{"region_id": r, "display_name": catalog.get(r).display_name} for r in order]
    return {
        "status": "unknown_location",
        "requested": place,
        "message": (
            f"{place!r} is not a location AeroPulse covers. Covered regions: "
            + ", ".join(c["display_name"] for c in covered)
            + "."
        ),
        "covered_regions": covered,
        "known_locations": sorted(set(names)),
    }


def locate(place: str, region_id: str | None, ctx: ToolContext) -> Located | dict[str, Any]:
    """Resolve ``place`` to a gazetteer place or a whole region, never a guess.

    Gazetteer places win over region names, so "Delhi" is the city, not the
    region whose display name contains it.
    """
    if ctx.regions is None:
        return _unavailable("no region data configured")
    order = _region_order(region_id, ctx)
    if isinstance(order, dict):
        return order
    key = _norm(place or "")
    if not key:
        return _unknown_place(place, order, ctx)
    for rid in order:
        for candidate in ctx.regions.places(rid):
            if _norm(candidate.name) == key:
                return Located(
                    rid,
                    candidate.name,
                    candidate.lat,
                    candidate.lon,
                    "place",
                    max(NEAR_KM, candidate.radius_km),
                )
        pack = ctx.regions.catalog.get(rid)
        if key in (_norm(pack.display_name), _norm(rid)):
            return Located(rid, pack.display_name, pack.map_view.lat, pack.map_view.lon, "region")
        if rid == LEGACY_REGION:
            legacy = resolve_place(place)
            if legacy is not None:
                return Located(rid, legacy.name, legacy.lat, legacy.lon, "place")
    catalog = ctx.regions.catalog
    for rid in order:
        pack = catalog.get(rid)
        if _names_region(key, pack):
            return Located(rid, pack.display_name, pack.map_view.lat, pack.map_view.lon, "region")
    return _unknown_place(place, order, ctx)


def _region_for(region_id: str | None, ctx: ToolContext) -> str | dict[str, Any]:
    if ctx.regions is None:
        return _unavailable("no region data configured")
    order = _region_order(region_id, ctx)
    if isinstance(order, dict):
        return order
    if not order:
        return _unavailable("no regions are onboarded")
    return order[0]


def _no_snapshot(region_id: str, place: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "status": "not_configured",
        "region_id": region_id,
        "reason": "no cycle snapshot has been written for this region yet",
    }
    if place is not None:
        body["place"] = place
    return body


def _snapshot(ctx: ToolContext, region_id: str) -> RegionSnapshot | None:
    return ctx.regions.snapshot(region_id) if ctx.regions is not None else None


def _aqi(ctx: ToolContext, region_id: str) -> dict[str, Any]:
    assert ctx.regions is not None
    standard = ctx.regions.catalog.aqi_for(region_id)
    return {
        "aqi_standard": standard.name,
        "aqi_standard_status": standard.status,
        "aqi_averaging": standard.averaging,
    }


def _cell_view(cell: CellState, region_id: str, ctx: ToolContext) -> dict[str, Any]:
    """A served cell. The band is the cycle's (over the standard's averaging
    window), never re-derived here from the latest hourly value."""
    reason = next((f.reason for f in cell.field_status if f.field == "aqi_band"), None)
    body: dict[str, Any] = {
        "grid_id": cell.grid_id,
        "pm25_ug_m3": cell.pm25,
        **_aqi(ctx, region_id),
        "aqi_band": cell.aqi_band.label if cell.aqi_band is not None else None,
        "provenance_class": cell.provenance_class.value if cell.provenance_class else None,
        "source": cell.pm25_source_id or "AeroPulse snapshot",
        **staleness(cell.observed_at, ctx),
    }
    if cell.aqi_band is None:
        body["aqi_band_reason"] = reason or "the cycle served no band for this cell"
    else:
        body["aqi_band_basis"] = f"{body['aqi_averaging']} mean, not the latest hourly value"
    if body["provenance_class"] == "model_derived":
        body["note"] = "CAMS model output, not a station measurement."
    return body


def _nearest[T](
    items: Iterable[T], lat: float, lon: float, max_km: float, where: Any
) -> tuple[T, float] | None:
    best: tuple[T, float] | None = None
    for item in items:
        ilat, ilon = where(item)
        distance = haversine_km(lat, lon, ilat, ilon)
        if distance <= max_km and (best is None or distance < best[1]):
            best = (item, distance)
    return best


def _nearest_measured_first[T](
    items: Iterable[T], lat: float, lon: float, max_km: float, where: Any, measured: Any
) -> tuple[T, float] | None:
    """A ground station in range outranks a closer CAMS cell for a place answer."""
    pool = list(items)
    hit = _nearest([i for i in pool if measured(i)], lat, lon, max_km, where)
    return hit if hit is not None else _nearest(pool, lat, lon, max_km, where)


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return round((math.degrees(math.atan2(x, y)) + 360.0) % 360.0, 0)


def _wind(vector: WindVector) -> dict[str, Any]:
    speed = math.hypot(vector.u, vector.v)
    wind_from = (math.degrees(math.atan2(-vector.u, -vector.v)) + 360.0) % 360.0
    return {
        "valid_at": iso(vector.valid_at),
        "issued_at": iso(vector.issued_at),
        "wind_speed_ms": round(speed, 1),
        "wind_from_degrees": round(wind_from, 0),
        "wind_towards_degrees": round((wind_from + 180.0) % 360.0, 0),
        "level": vector.level,
        "provenance_class": vector.provenance_class.value,
    }


def _snapshot_meta(snapshot: RegionSnapshot) -> dict[str, Any]:
    return {"cycle_id": snapshot.cycle_id, "cycle_time": iso(snapshot.cycle_time)}


# --- region context --------------------------------------------------------


def get_region_context(region_id: str | None = None, *, ctx: ToolContext) -> dict[str, Any]:
    """Name, AQI standard, hazards, sources and what is served for one region."""
    rid = _region_for(region_id, ctx)
    if isinstance(rid, dict):
        return rid
    assert ctx.regions is not None
    catalog = ctx.regions.catalog
    pack = catalog.get(rid)
    standard = catalog.aqi_for(rid)
    snapshot = _snapshot(ctx, rid)
    health = {h.source_id: h for h in snapshot.source_health} if snapshot else {}
    sources = []
    for source in pack.sources:
        state = health.get(source.id)
        sources.append(
            {
                "source_id": source.id,
                "enabled": source.enabled,
                "state": state.state if state is not None else None,
                "reason": state.reason if state is not None else None,
            }
        )
    return {
        "status": "ok",
        "region_id": rid,
        "display_name": pack.display_name,
        "timezone": pack.timezone,
        "country_codes": list(pack.country_codes),
        "aqi_standard": {
            "name": standard.name,
            "status": standard.status,
            "averaging": standard.averaging,
            "reason": standard.reason,
            "bands": [b.label for b in standard.bands],
        },
        "hazards": [
            {"key": h.key, "display_name": h.display_name, "source_class": h.source_class}
            for h in catalog.hazards_for(rid)
        ],
        "ground_truth": pack.ground_truth,
        "sources": sources,
        "served_models": [
            {
                "family": m.family,
                "model_version": m.model_version,
                "degraded": m.degraded,
                "degraded_reason": m.degraded_reason,
                "calibrated": m.calibrated,
            }
            for m in (snapshot.served_models if snapshot else [])
        ],
        "snapshot": _snapshot_meta(snapshot) if snapshot else None,
        "snapshot_reason": None if snapshot else _no_snapshot(rid)["reason"],
        "provenance_class": "configuration",
    }


# --- air quality -----------------------------------------------------------


def snapshot_air_quality(
    loc: Located, snapshot: RegionSnapshot, ctx: ToolContext
) -> dict[str, Any]:
    """Served PM2.5 for a place (nearest cell) or a region (median and highest)."""
    cells = [c for c in snapshot.cells if c.pm25 is not None]
    base = {"place": loc.name, "region_id": loc.region_id, **_snapshot_meta(snapshot)}
    if not cells:
        return {"status": "no_data", **base, "message": f"No served PM2.5 for {loc.name}."}
    if loc.kind == "region":
        values = [c.pm25 for c in cells if c.pm25 is not None]
        median = round(statistics.median(values), 1)
        top = max(cells, key=lambda c: c.pm25 or 0.0)
        classes = Counter(
            c.provenance_class.value if c.provenance_class else "unknown" for c in cells
        )
        return {
            "status": "ok",
            "scope": "region",
            **base,
            "cells_with_value": len(cells),
            "median_pm25_ug_m3": median,
            **_aqi(ctx, loc.region_id),
            "aqi_band": None,
            "aqi_band_reason": "bands are served per cell; a regional median has none",
            "highest": _cell_view(top, loc.region_id, ctx),
            "provenance_classes": dict(sorted(classes.items())),
        }
    hit = _nearest_measured_first(
        cells,
        loc.lat,
        loc.lon,
        loc.radius_km,
        lambda c: (c.lat, c.lon),
        lambda c: c.provenance_class is not None and c.provenance_class.value == "measured",
    )
    if hit is None:
        return {
            "status": "no_data",
            **base,
            "message": f"No served PM2.5 cell within {loc.radius_km:g} km of {loc.name}.",
        }
    cell, distance = hit
    return {
        "status": "ok",
        "scope": "place",
        **base,
        "distance_km": round(distance, 1),
        **_cell_view(cell, loc.region_id, ctx),
    }


def get_current_aqi(
    place: str, region_id: str | None = None, *, ctx: ToolContext
) -> dict[str, Any]:
    """Served PM2.5 with the region's AQI band, provenance and staleness."""
    loc = locate(place, region_id, ctx)
    if isinstance(loc, dict):
        return loc
    snapshot = _snapshot(ctx, loc.region_id)
    if snapshot is None:
        return _no_snapshot(loc.region_id, loc.name)
    return snapshot_air_quality(loc, snapshot, ctx)


# --- trend / query_trends ---------------------------------------------------


def _hourly(points: Iterable[SeriesPoint]) -> list[tuple[datetime, float]]:
    """Median per UTC hour across the given observations."""
    buckets: dict[datetime, list[float]] = defaultdict(list)
    for p in points:
        hour = p.observed_at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        buckets[hour].append(p.value)
    return [(h, statistics.median(v)) for h, v in sorted(buckets.items())]


def _series(
    loc: Located, start: datetime, end: datetime, ctx: ToolContext, *, limit: int
) -> dict[str, Any]:
    assert ctx.regions is not None
    points = ctx.regions.pm25_series(loc.region_id, start, end)
    base = {
        "place": loc.name,
        "region_id": loc.region_id,
        "start": iso(start),
        "end": iso(end),
    }
    if loc.kind == "place":
        stations: dict[tuple[float, float], list[SeriesPoint]] = defaultdict(list)
        for p in points:
            stations[(p.lat, p.lon)].append(p)
        hit = _nearest_measured_first(
            stations,
            loc.lat,
            loc.lon,
            loc.radius_km,
            lambda k: k,
            lambda k: any(p.provenance_class == "measured" for p in stations[k]),
        )
        points = stations[hit[0]] if hit is not None else []
    if not points:
        return {
            "status": "no_data",
            **base,
            "message": f"No stored PM2.5 observations for {loc.name} in this window.",
        }
    hourly = _hourly(points)[-limit:]
    first, last = hourly[0][1], hourly[-1][1]
    change = round(last - first, 1)
    return {
        "status": "ok",
        "scope": loc.kind,
        **base,
        "aggregation": "hourly median" if loc.kind == "region" else "hourly median at one station",
        "series": [{"hour": iso(h), "pm25_ug_m3": round(v, 1)} for h, v in hourly],
        "first_pm25_ug_m3": round(first, 1),
        "last_pm25_ug_m3": round(last, 1),
        "change_ug_m3": change,
        "direction": "rising" if change > 0 else "falling" if change < 0 else "flat",
        "provenance_class": sorted({p.provenance_class or "unknown" for p in points}),
        "source": ", ".join(sorted({p.source_id for p in points})),
        "observed_at": iso(hourly[-1][0]),
    }


def get_pm25_trend(
    place: str, hours: int = 6, region_id: str | None = None, *, ctx: ToolContext
) -> dict[str, Any]:
    """Hourly stored PM2.5 for the last ``hours`` and how it changed."""
    loc = locate(place, region_id, ctx)
    if isinstance(loc, dict):
        return loc
    hours = max(1, min(int(hours), MAX_TREND_HOURS))
    end = ctx.clock()
    return _series(loc, end - timedelta(hours=hours), end, ctx, limit=hours + 1)


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def query_trends(
    template_id: str,
    place: str,
    start: str,
    end: str,
    region_id: str | None = None,
    *,
    ctx: ToolContext,
) -> dict[str, Any]:
    """Rows from an allow-listed template over an explicit window."""
    if template_id not in QUERY_TEMPLATES:
        return {
            "status": "bad_arguments",
            "name": "query_trends",
            "detail": f"Unknown template {template_id!r}. Use one of: {sorted(QUERY_TEMPLATES)}.",
        }
    t0, t1 = _parse_time(start), _parse_time(end)
    if t0 is None or t1 is None or t1 <= t0:
        return {
            "status": "bad_arguments",
            "name": "query_trends",
            "detail": "start and end must be ISO-8601 times with end after start.",
        }
    if t1 - t0 > timedelta(days=MAX_QUERY_DAYS):
        return {
            "status": "bad_arguments",
            "name": "query_trends",
            "detail": f"The window may span at most {MAX_QUERY_DAYS} days.",
        }
    loc = locate(place, region_id, ctx)
    if isinstance(loc, dict):
        return loc
    result = _series(loc, t0, t1, ctx, limit=QUERY_ROW_LIMIT)
    result["template_id"] = template_id
    return result


# --- forecast / hazard -------------------------------------------------------


def get_pm25_forecast(
    place: str, region_id: str | None = None, *, ctx: ToolContext
) -> dict[str, Any]:
    """Served PM2.5 quantiles per horizon, with model version and degraded flag."""
    loc = locate(place, region_id, ctx)
    if isinstance(loc, dict):
        return loc
    snapshot = _snapshot(ctx, loc.region_id)
    if snapshot is None:
        return _no_snapshot(loc.region_id, loc.name)
    base = {
        "place": loc.name,
        "region_id": loc.region_id,
        **_snapshot_meta(snapshot),
        "provenance_class": "predicted",
        "source": "AeroPulse PM2.5 forecast",
        "observed_at": iso(snapshot.cycle_time),
    }
    by_cell: dict[str, list[Any]] = defaultdict(list)
    for forecast in snapshot.forecasts:
        by_cell[forecast.grid_id].append(forecast)
    if not by_cell:
        return {"status": "no_data", **base, "message": "No PM2.5 forecast was served this cycle."}
    if loc.kind == "region":
        horizons: dict[int, list[float]] = defaultdict(list)
        for forecasts in by_cell.values():
            for f in forecasts:
                if f.p50 is not None:
                    horizons[f.horizon_hours].append(f.p50)
        return {
            "status": "ok",
            "scope": "region",
            **base,
            "cells_forecast": len(by_cell),
            "horizons": [
                {
                    "horizon_hours": h,
                    "p50_min_ug_m3": round(min(v), 1),
                    "p50_max_ug_m3": round(max(v), 1),
                }
                for h, v in sorted(horizons.items())
            ],
        }
    hit = _nearest(by_cell, loc.lat, loc.lon, loc.radius_km, grid_center)
    if hit is None:
        return {
            "status": "no_data",
            **base,
            "message": f"No forecast cell within {loc.radius_km:g} km of {loc.name}.",
        }
    grid_id, distance = hit
    return {
        "status": "ok",
        "scope": "place",
        **base,
        "grid_id": grid_id,
        "distance_km": round(distance, 1),
        "horizons": [
            {
                "horizon_hours": f.horizon_hours,
                "valid_at": iso(f.valid_at),
                "p10_ug_m3": f.p10,
                "p50_ug_m3": f.p50,
                "p90_ug_m3": f.p90,
                "model_version": f.model_version,
                "degraded": f.degraded,
                "degraded_reason": f.degraded_reason,
            }
            for f in sorted(by_cell[grid_id], key=lambda f: f.horizon_hours)
        ],
    }


def snapshot_hazard(loc: Located, snapshot: RegionSnapshot, ctx: ToolContext) -> dict[str, Any]:
    """The served 24-hour hazard nearest a place, labelled rank or probability."""
    assert ctx.regions is not None
    standard = ctx.regions.catalog.aqi_for(loc.region_id)
    base = {
        "place": loc.name,
        "region_id": loc.region_id,
        **_snapshot_meta(snapshot),
        "aqi_standard": standard.name,
        "hazard_threshold_ug_m3": standard.hazard_threshold_ugm3,
        "provenance_class": "predicted",
        "source": "AeroPulse hazard outlook",
        "observed_at": iso(snapshot.cycle_time),
    }
    if not snapshot.hazard:
        return {"status": "no_data", **base, "message": "No hazard outlook was served this cycle."}
    if loc.kind == "region":
        hazard = max(snapshot.hazard, key=lambda h: h.score)
        distance = None
    else:
        hit = _nearest(
            snapshot.hazard, loc.lat, loc.lon, loc.radius_km, lambda h: grid_center(h.grid_id)
        )
        if hit is None:
            return {
                "status": "no_data",
                **base,
                "message": f"No hazard cell within {loc.radius_km:g} km of {loc.name}.",
            }
        hazard, distance = hit
    return {
        "status": "ok",
        "scope": loc.kind,
        **base,
        "grid_id": hazard.grid_id,
        "distance_km": round(distance, 1) if distance is not None else None,
        "hazard_score": hazard.score,
        "horizon_hours": hazard.horizon_hours,
        "calibrated": hazard.calibrated,
        "degraded": hazard.degraded,
        "degraded_reason": hazard.degraded_reason,
        "model_version": hazard.model_version,
        "interpretation": (
            "Calibrated probability of exceeding the hazard threshold."
            if hazard.calibrated
            else "This score ranks cells by relative risk. It is not a probability, "
            "because the model is uncalibrated."
        ),
    }


# --- fires / weather / satellite ---------------------------------------------


def snapshot_fires(
    loc: Located, snapshot: RegionSnapshot, radius_km: float, ctx: ToolContext
) -> dict[str, Any]:
    """Fire clusters near a place (or the largest in a region) with distance and bearing."""
    clusters = []
    for cluster in snapshot.fires:
        distance = haversine_km(loc.lat, loc.lon, cluster.lat, cluster.lon)
        if loc.kind == "place" and distance > radius_km:
            continue
        clusters.append(
            {
                "cluster_id": cluster.cluster_id,
                "distance_km": round(distance, 1),
                "bearing_from_place_degrees": _bearing(loc.lat, loc.lon, cluster.lat, cluster.lon),
                "detection_count": cluster.detection_count,
                "frp_total_mw": round(cluster.frp_total, 1),
                "observed_at": iso(cluster.last_seen),
                "source": ", ".join(cluster.source_ids) or "NASA FIRMS",
                "provenance_class": cluster.provenance_class,
            }
        )
    order = "distance_km" if loc.kind == "place" else "frp_total_mw"
    clusters.sort(key=lambda c: c[order], reverse=loc.kind == "region")
    return {
        "status": "ok",
        "scope": loc.kind,
        "place": loc.name,
        "region_id": loc.region_id,
        **_snapshot_meta(snapshot),
        "radius_km": radius_km if loc.kind == "place" else None,
        "cluster_count": len(clusters),
        "detection_count": sum(c["detection_count"] for c in clusters),
        "total_frp_mw": round(sum(c["frp_total_mw"] for c in clusters), 1),
        "clusters": clusters[:5],
        "provenance_class": "measured",
        "source": "NASA FIRMS",
        "note": "A zero count means no detections where the satellite overflew, not proof of no fire.",
    }


def snapshot_weather(loc: Located, snapshot: RegionSnapshot, ctx: ToolContext) -> dict[str, Any]:
    """Observed wind at the nearest site and its forecast vectors with ``issued_at``."""
    observed = [w for w in snapshot.wind if w.issued_at is None and w.level == "10m"]
    hit = _nearest(observed, loc.lat, loc.lon, float("inf"), lambda w: (w.lat, w.lon))
    base = {"place": loc.name, "region_id": loc.region_id, **_snapshot_meta(snapshot)}
    field_status = [
        {"field": "humidity", "reason": "the snapshot carries wind vectors only"},
        {"field": "boundary_layer_height_m", "reason": "the snapshot carries wind vectors only"},
    ]
    if hit is None:
        return {
            "status": "no_data",
            **base,
            "message": "No observed wind was served this cycle.",
            "field_status": field_status,
        }
    site, distance = hit
    latest = max((w for w in observed if w.site_id == site.site_id), key=lambda w: w.valid_at)
    horizon = snapshot.cycle_time + timedelta(hours=24)
    forecast = sorted(
        (
            w
            for w in snapshot.wind
            if w.site_id == site.site_id
            and w.issued_at is not None
            and w.level == "10m"
            and w.valid_at <= horizon
        ),
        key=lambda w: w.valid_at,
    )
    return {
        "status": "ok",
        **base,
        "site_id": site.site_id,
        "distance_km": round(distance, 1),
        "now": {**_wind(latest), "observed_at": iso(latest.valid_at), "source": "Open-Meteo"},
        "forecast": [_wind(w) for w in forecast],
        "humidity": None,
        "boundary_layer_height_m": None,
        "field_status": field_status,
        "provenance_class": latest.provenance_class.value,
        "source": "Open-Meteo",
        "observed_at": iso(latest.valid_at),
    }


def get_weather(place: str, region_id: str | None = None, *, ctx: ToolContext) -> dict[str, Any]:
    """Wind now and forecast at the site nearest a place."""
    loc = locate(place, region_id, ctx)
    if isinstance(loc, dict):
        return loc
    snapshot = _snapshot(ctx, loc.region_id)
    if snapshot is None:
        return _no_snapshot(loc.region_id, loc.name)
    return snapshot_weather(loc, snapshot, ctx)


def get_satellite_signal(
    place: str, region_id: str | None = None, *, ctx: ToolContext
) -> dict[str, Any]:
    """Satellite aerosol signal: not served in this build, said plainly."""
    loc = locate(place, region_id, ctx)
    if isinstance(loc, dict):
        return loc
    return {
        "status": "unavailable",
        "place": loc.name,
        "region_id": loc.region_id,
        "reason": (
            "No satellite aerosol layer is served yet: Sentinel-5P and MODIS ingest are not "
            "live in this build, so there is no aerosol index to report."
        ),
        "provenance_class": None,
    }


# --- incidents / plumes --------------------------------------------------------


def _find_incident(
    incident_id: str, ctx: ToolContext
) -> tuple[IncidentSummary, RegionSnapshot] | None:
    if ctx.regions is None:
        return None
    for rid in sorted(ctx.regions.catalog.packs):
        snapshot = ctx.regions.snapshot(rid)
        if snapshot is None:
            continue
        for incident in snapshot.incidents:
            if incident.incident_id == incident_id:
                return incident, snapshot
    return None


def _node_refs(incident: IncidentSummary, kind: str) -> list[str]:
    prefix = f"{kind}:"
    return [
        n.split(":", 2)[2] for n in incident.node_ids if n.startswith(prefix) and n.count(":") >= 2
    ]


def _plume_view(
    summary: PlumeSummary, full: Plume | None, snapshot: RegionSnapshot
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "plume_id": summary.plume_id,
        "direction": summary.direction,
        "origin": {
            "kind": summary.origin.kind,
            "ref_id": summary.origin.ref_id,
            "lat": summary.origin.lat,
            "lon": summary.origin.lon,
        },
        "max_horizon_hours": summary.max_horizon_hours,
        "max_population_p90": summary.max_population_p90,
        "model_version": summary.model_version,
        "experimental": summary.experimental,
        "degraded": summary.degraded,
        "degraded_reasons": list(summary.degraded_reasons),
        "label": PLUME_LABEL,
        "interpretation": (
            "Probabilities are the share of simulated particles reaching a place "
            "(footprint probability), not a concentration forecast."
            if summary.direction == "forward"
            else "The likely source region of this air, not proof of what caused it."
        ),
        "provenance_class": "simulated",
        "source": "AeroPulse plume ensemble",
        "observed_at": iso(snapshot.cycle_time),
    }
    if full is None:
        body["field_status"] = [{"field": "detail", "reason": "plume detail is not in the store"}]
        return body
    body["wind_issued_at"] = iso(full.wind_issued_at)
    body["horizons"] = [
        {
            "horizon_hours": h.horizon_hours,
            "p50_cell_count": len(h.p50_cells),
            "p90_cell_count": len(h.p90_cells),
            "centroid_lat": h.centroid_lat,
            "centroid_lon": h.centroid_lon,
            "weight_remaining": h.weight_remaining,
        }
        for h in full.horizons
    ]
    body["arrivals"] = [
        {
            "name": a.name,
            "probability": a.probability,
            "eta_hours_median": a.eta_hours_median,
            "population": a.population,
        }
        for a in sorted(full.arrivals, key=lambda a: a.probability, reverse=True)
    ]
    body["exposure"] = [
        {
            "horizon_hours": e.horizon_hours,
            "population_p90": e.population_p90,
            "population_source": e.population_source,
            "population_year": e.population_year,
        }
        for e in full.exposure
    ]
    if full.source_candidates:
        body["source_candidates"] = [
            {
                "fire_cluster_id": c.fire_cluster_id,
                "particle_fraction": c.particle_fraction,
                "distance_km": c.distance_km,
                "bearing_degrees": c.bearing_deg,
                "frp_total_mw": c.frp_total,
            }
            for c in full.source_candidates
        ]
    return body


def _plume_result(
    summaries: Sequence[PlumeSummary], snapshot: RegionSnapshot, ctx: ToolContext, **base: Any
) -> dict[str, Any]:
    assert ctx.regions is not None
    ranked = sorted(summaries, key=lambda s: -(s.max_population_p90 or 0.0))[:MAX_PLUMES]
    plumes = [
        _plume_view(s, ctx.regions.plume(snapshot.region_id, s.plume_id), snapshot) for s in ranked
    ]
    return {
        "status": "ok" if plumes else "no_data",
        "region_id": snapshot.region_id,
        **_snapshot_meta(snapshot),
        **base,
        "plume_count": len(summaries),
        "plumes": plumes,
        "label": PLUME_LABEL,
        "provenance_class": "simulated",
    }


def get_plume(
    place: str | None = None,
    incident_id: str | None = None,
    report_id: str | None = None,
    direction: str = "forward",
    region_id: str | None = None,
    *,
    ctx: ToolContext,
) -> dict[str, Any]:
    """Stored plume footprints, arrivals and exposure for a place, incident or report."""
    if ctx.regions is None:
        return _unavailable("no region data configured")
    if sum(x is not None for x in (place, incident_id, report_id)) != 1:
        return {
            "status": "bad_arguments",
            "name": "get_plume",
            "detail": "Give exactly one of place, incident_id or report_id.",
        }
    if direction not in ("forward", "backward"):
        return {
            "status": "bad_arguments",
            "name": "get_plume",
            "detail": "direction must be 'forward' or 'backward'.",
        }
    if incident_id is not None:
        found = _find_incident(incident_id, ctx)
        if found is None:
            return {"status": "not_found", "incident_id": incident_id}
        incident, snapshot = found
        ids = set(_node_refs(incident, "plume"))
        chosen = [s for s in snapshot.plumes if s.plume_id in ids and s.direction == direction]
        return _plume_result(chosen, snapshot, ctx, incident_id=incident_id, direction=direction)
    if report_id is not None:
        for rid in sorted(ctx.regions.catalog.packs):
            snapshot = ctx.regions.snapshot(rid)
            if snapshot is None:
                continue
            linked = {w.plume_id for w in snapshot.citizen_watches if w.report_id == report_id}
            chosen = [
                s
                for s in snapshot.plumes
                if s.direction == direction
                and (s.plume_id in linked or s.origin.ref_id == report_id)
            ]
            if chosen or any(w.report_id == report_id for w in snapshot.citizen_watches):
                return _plume_result(
                    chosen, snapshot, ctx, report_id=report_id, direction=direction
                )
        return {"status": "not_found", "report_id": report_id}
    assert place is not None
    loc = locate(place, region_id, ctx)
    if isinstance(loc, dict):
        return loc
    snapshot = _snapshot(ctx, loc.region_id)
    if snapshot is None:
        return _no_snapshot(loc.region_id, loc.name)
    chosen = [s for s in snapshot.plumes if s.direction == direction]
    if loc.kind == "place":
        reaching = []
        for summary in chosen:
            near = haversine_km(loc.lat, loc.lon, summary.origin.lat, summary.origin.lon)
            full = ctx.regions.plume(loc.region_id, summary.plume_id)
            arrives = full is not None and any(
                _norm(a.name) == _norm(loc.name) for a in full.arrivals
            )
            if arrives or near <= 2 * loc.radius_km:
                reaching.append(summary)
        chosen = reaching
    return _plume_result(chosen, snapshot, ctx, place=loc.name, direction=direction)


def get_population_exposure(incident_id: str, *, ctx: ToolContext) -> dict[str, Any]:
    """Simulated exposed population per horizon for an incident's forward plumes."""
    plumes = get_plume(incident_id=incident_id, direction="forward", ctx=ctx)
    if plumes.get("status") not in ("ok", "no_data"):
        return plumes
    return {
        "status": plumes["status"],
        "incident_id": incident_id,
        "region_id": plumes.get("region_id"),
        "exposure": [
            {
                "plume_id": p["plume_id"],
                "horizons": p.get("exposure", []),
                "field_status": p.get("field_status", []),
            }
            for p in plumes.get("plumes", [])
        ],
        "interpretation": (
            "Population inside the simulated P90 footprint; an estimate of who could be "
            "exposed, not a count of people affected."
        ),
        "label": PLUME_LABEL,
        "provenance_class": "simulated",
        "source": "AeroPulse plume ensemble",
        "observed_at": plumes.get("cycle_time"),
    }


def get_source_likelihood(
    place: str, region_id: str | None = None, *, ctx: ToolContext
) -> dict[str, Any]:
    """Heuristic, uncalibrated source ranking with its evidence."""
    loc = locate(place, region_id, ctx)
    if isinstance(loc, dict):
        return loc
    snapshot = _snapshot(ctx, loc.region_id)
    if snapshot is None:
        return _no_snapshot(loc.region_id, loc.name)
    return _likelihood(loc, snapshot, ctx)


def _likelihood_view(entry: Any, names: dict[str, str]) -> dict[str, Any]:
    return {
        "grid_id": entry.grid_id,
        "valid_at": iso(entry.valid_at),
        "method_version": entry.method_version,
        "ranking": [
            {
                "source_class": s.source_class,
                "display_name": names.get(s.source_class, s.source_class),
                "score": s.score,
                "contributing_signals": list(s.contributing_signals),
            }
            for s in sorted(entry.ranking, key=lambda s: s.score, reverse=True)
        ],
        "evidence": [
            {
                "signal": e.signal,
                "source": e.source_id,
                "value": e.value,
                "unit": e.unit,
                "observed_at": iso(e.observed_at),
            }
            for e in entry.evidence
        ],
    }


def _likelihood(
    loc: Located, snapshot: RegionSnapshot, ctx: ToolContext, grid_ids: set[str] | None = None
) -> dict[str, Any]:
    assert ctx.regions is not None
    names = {h.source_class: h.display_name for h in ctx.regions.catalog.hazards_for(loc.region_id)}
    base = {
        "place": loc.name,
        "region_id": loc.region_id,
        **_snapshot_meta(snapshot),
        "provenance_class": "heuristic",
        "calibrated": False,
        "interpretation": (
            "Heuristic ranking, not calibrated. Scores do not sum to 1 and are not "
            "percentages or probabilities."
        ),
        "source": "AeroPulse source likelihood",
        "observed_at": iso(snapshot.cycle_time),
    }
    entries = list(snapshot.source_likelihood)
    if grid_ids is not None:
        entries = [e for e in entries if e.grid_id in grid_ids]
    elif loc.kind == "place":
        hit = _nearest(entries, loc.lat, loc.lon, loc.radius_km, lambda e: grid_center(e.grid_id))
        entries = [hit[0]] if hit is not None else []
    else:
        entries = sorted(
            entries, key=lambda e: max((s.score for s in e.ranking), default=0.0), reverse=True
        )
    if not entries:
        return {"status": "no_data", **base, "message": "No source likelihood was served here."}
    return {"status": "ok", **base, "cells": [_likelihood_view(e, names) for e in entries[:3]]}


# --- citizen -----------------------------------------------------------------


def _public(row: dict[str, Any]) -> bool:
    return row.get("moderation") != "rejected" and row.get("decision") != "stored_operators_only"


def _latest_reports(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        rid = str(row.get("report_id"))
        current = latest.get(rid)
        if current is None or str(row.get("recorded_at")) >= str(current.get("recorded_at")):
            latest[rid] = row
    return list(latest.values())


def _report_view(row: dict[str, Any]) -> dict[str, Any]:
    operator_set = row.get("visual_class_source") == "operator"
    return {
        "report_id": row.get("report_id"),
        "visual_class": row.get("visual_class"),
        "visual_class_label": "Set by an operator" if operator_set else AI_OBSERVATION_LABEL,
        "corroboration": row.get("corroboration"),
        "geo_trust": row.get("geo_trust"),
        "decision": row.get("decision"),
        "plume_id": row.get("plume_id"),
        "matched_fire_id": row.get("matched_fire_id"),
        "lat_rounded": row.get("lat_rounded"),
        "lon_rounded": row.get("lon_rounded"),
        "observed_at": iso(row.get("observed_at") or row.get("created_at")),
        "source": "Citizen photo",
        "provenance_class": "citizen" if operator_set else "ai_observation",
    }


def get_citizen_reports(
    place: str | None = None,
    incident_id: str | None = None,
    region_id: str | None = None,
    *,
    ctx: ToolContext,
) -> dict[str, Any]:
    """Public citizen photo reports near a place or linked to an incident."""
    if ctx.regions is None:
        return _unavailable("no region data configured")
    if (place is None) == (incident_id is None):
        return {
            "status": "bad_arguments",
            "name": "get_citizen_reports",
            "detail": "Give exactly one of place or incident_id.",
        }
    loc: Located | None = None
    linked: set[str] | None = None
    if incident_id is not None:
        found = _find_incident(incident_id, ctx)
        if found is None:
            return {"status": "not_found", "incident_id": incident_id}
        incident, _ = found
        rid = incident.region_id
        linked = set(_node_refs(incident, "citizen_report"))
    else:
        assert place is not None
        located = locate(place, region_id, ctx)
        if isinstance(located, dict):
            return located
        loc, rid = located, located.region_id
    end = ctx.clock()
    rows = [
        r
        for r in _latest_reports(ctx.regions.citizen_reports(rid, end - CITIZEN_LOOKBACK, end))
        if _public(r)
    ]
    if linked is not None:
        rows = [
            r for r in rows if r.get("report_id") in linked or r.get("incident_id") == incident_id
        ]
    elif loc is not None and loc.kind == "place":
        rows = [
            r
            for r in rows
            if r.get("lat_rounded") is not None
            and r.get("lon_rounded") is not None
            and haversine_km(loc.lat, loc.lon, float(r["lat_rounded"]), float(r["lon_rounded"]))
            <= loc.radius_km
        ]
    reports = [_report_view(r) for r in rows]
    reports.sort(key=lambda r: str(r["observed_at"] or ""), reverse=True)
    return {
        "status": "ok" if reports else "no_data",
        "region_id": rid,
        "place": loc.name if loc is not None else None,
        "incident_id": incident_id,
        "lookback_days": CITIZEN_LOOKBACK.days,
        "report_count": len(reports),
        "by_corroboration": dict(sorted(Counter(str(r["corroboration"]) for r in reports).items())),
        "reports": reports[:10],
        "interpretation": (
            "Visual classes are AI observations of a photo. They count only when "
            "corroborated by station, fire or wind data."
        ),
        "provenance_class": "ai_observation",
    }


# --- incidents ---------------------------------------------------------------


def list_incidents(region_id: str | None = None, *, ctx: ToolContext) -> dict[str, Any]:
    """Active incidents with root kind, places reached and last update."""
    rid = _region_for(region_id, ctx)
    if isinstance(rid, dict):
        return rid
    snapshot = _snapshot(ctx, rid)
    if snapshot is None:
        return _no_snapshot(rid)
    incidents = sorted(snapshot.incidents, key=lambda i: i.last_updated, reverse=True)
    return {
        "status": "ok",
        "region_id": rid,
        **_snapshot_meta(snapshot),
        "total": len(incidents),
        "incidents": [
            {
                "incident_id": i.incident_id,
                "root_kind": i.root_kind,
                "first_seen": iso(i.first_seen),
                "observed_at": iso(i.last_updated),
                "places_reached": list(i.place_ids_reached),
                "node_count": len(i.node_ids),
                "source": "AeroPulse intelligence graph",
            }
            for i in incidents[:20]
        ],
        "provenance_class": "mixed",
        "provenance_note": "Each node and edge carries its own class; see get_incident_graph.",
    }


def get_incident_graph(incident_id: str, *, ctx: ToolContext) -> dict[str, Any]:
    """The incident's nodes and edges, each with its provenance."""
    if ctx.regions is None:
        return _unavailable("no region data configured")
    found = _find_incident(incident_id, ctx)
    if found is None:
        return {"status": "not_found", "incident_id": incident_id}
    incident, snapshot = found
    nodes = [
        {
            "node_id": n.node_id,
            "kind": n.kind,
            "valid_from": iso(n.valid_from),
            "attributes": {
                k: {
                    "value": v.value,
                    "unit": v.unit,
                    "provenance_class": v.provenance_class.value,
                    "source": v.source_id,
                    "observed_at": iso(v.observed_at),
                }
                for k, v in n.attributes.items()
            },
        }
        for n in incident.nodes[:MAX_GRAPH_NODES]
    ]
    edges = [
        {
            "kind": e.kind,
            "src": e.src,
            "dst": e.dst,
            "producer": e.producer,
            "provenance_class": e.provenance_class.value,
        }
        for e in incident.edges[:MAX_GRAPH_EDGES]
    ]
    return {
        "status": "ok",
        "incident_id": incident_id,
        "region_id": incident.region_id,
        **_snapshot_meta(snapshot),
        "root_kind": incident.root_kind,
        "nodes": nodes,
        "edges": edges,
        "truncated": len(incident.nodes) > MAX_GRAPH_NODES or len(incident.edges) > MAX_GRAPH_EDGES,
        "provenance_class": "mixed",
    }


def explain_incident(incident_id: str, *, ctx: ToolContext) -> dict[str, Any]:
    """AQI, fires, wind, satellite, plume, exposure, source likelihood and reports, in one call."""
    if ctx.regions is None:
        return _unavailable("no region data configured")
    found = _find_incident(incident_id, ctx)
    if found is None:
        return {"status": "not_found", "incident_id": incident_id}
    incident, snapshot = found
    rid = incident.region_id
    cell_ids = {n.removeprefix("cell:") for n in incident.node_ids if n.startswith("cell:")}
    cluster_ids = set(_node_refs(incident, "fire_cluster"))
    cells = [c for c in snapshot.cells if c.grid_id in cell_ids and c.pm25 is not None]
    fires = [f for f in snapshot.fires if f.cluster_id in cluster_ids]
    anchor: tuple[float, float] | None = None
    if fires:
        anchor = (fires[0].lat, fires[0].lon)
    elif cells:
        anchor = (cells[0].lat, cells[0].lon)
    elif cell_ids:
        anchor = grid_center(sorted(cell_ids)[0])
    pack = ctx.regions.catalog.get(rid)
    lat, lon = anchor if anchor is not None else (pack.map_view.lat, pack.map_view.lon)
    loc = Located(rid, f"incident {incident_id}", lat, lon, "place")
    return {
        "status": "ok",
        "incident_id": incident_id,
        "region_id": rid,
        **_snapshot_meta(snapshot),
        "root_kind": incident.root_kind,
        "first_seen": iso(incident.first_seen),
        "last_updated": iso(incident.last_updated),
        "places_reached": list(incident.place_ids_reached),
        "air_quality": [
            _cell_view(c, rid, ctx)
            for c in sorted(cells, key=lambda c: c.pm25 or 0.0, reverse=True)[:5]
        ],
        "fires": [
            {
                "cluster_id": f.cluster_id,
                "detection_count": f.detection_count,
                "frp_total_mw": round(f.frp_total, 1),
                "observed_at": iso(f.last_seen),
                "source": ", ".join(f.source_ids) or "NASA FIRMS",
                "provenance_class": f.provenance_class,
            }
            for f in fires[:5]
        ],
        "weather": snapshot_weather(loc, snapshot, ctx),
        "satellite": {
            "status": "unavailable",
            "reason": "No satellite aerosol layer is served in this build.",
        },
        "plumes": get_plume(incident_id=incident_id, direction="forward", ctx=ctx),
        "back_trajectory": get_plume(incident_id=incident_id, direction="backward", ctx=ctx),
        "source_likelihood": _likelihood(loc, snapshot, ctx, grid_ids=cell_ids or None),
        "citizen_reports": get_citizen_reports(incident_id=incident_id, ctx=ctx),
        "provenance_class": "mixed",
    }


def region_facts(ctx: ToolContext) -> str | None:
    """The request's region as prompt text: names and labels only, never a figure."""
    if ctx.regions is None or ctx.region_id not in ctx.regions.catalog.packs:
        return None
    catalog = ctx.regions.catalog
    rid = ctx.region_id
    assert rid is not None
    pack = catalog.get(rid)
    standard = catalog.aqi_for(rid)
    bands = ", ".join(b.label for b in standard.bands) or "none (standard unconfirmed)"
    hazards = ", ".join(h.display_name for h in catalog.hazards_for(rid))
    others = ", ".join(
        f"{catalog.get(r).display_name} (`{r}`)" for r in sorted(catalog.packs) if r != rid
    )
    lines = [
        "## This conversation's region",
        "",
        f"- Region: {pack.display_name} (`{rid}`), timezone {pack.timezone}.",
        f"- Air quality standard: {standard.name} ({standard.status}). Bands: {bands}.",
        f"- Hazard types: {hazards}.",
        f"- Ground truth: {'ground stations' if pack.ground_truth == 'stations' else 'none'}.",
    ]
    if standard.status != "confirmed" and standard.reason:
        lines.append(f"- The standard is unconfirmed: {standard.reason}")
    if others:
        lines.append(f"- Other covered regions: {others}.")
    return "\n".join(lines)


REGION_TOOLS = {
    "get_region_context": get_region_context,
    "get_current_aqi": get_current_aqi,
    "get_pm25_trend": get_pm25_trend,
    "get_pm25_forecast": get_pm25_forecast,
    "get_weather": get_weather,
    "get_satellite_signal": get_satellite_signal,
    "get_plume": get_plume,
    "get_population_exposure": get_population_exposure,
    "get_source_likelihood": get_source_likelihood,
    "get_citizen_reports": get_citizen_reports,
    "list_incidents": list_incidents,
    "get_incident_graph": get_incident_graph,
    "explain_incident": explain_incident,
    "query_trends": query_trends,
}


def _string(description: str) -> dict[str, str]:
    return {"type": "string", "description": description}


_PLACE = _string("A city, district or area, or a region name such as 'Singapore'.")
_REGION = _string("Optional region id, e.g. 'in-north', 'sg-singapore', 'au-nsw'.")
_INCIDENT = _string("Incident id from list_incidents.")


def _decl(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict:
    params: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        params["required"] = required
    return {"name": name, "description": description, "parameters": params}


def describe_region_tools() -> list[dict[str, Any]]:
    """Declarations for the region tools, phrased for the model."""
    return [
        _decl(
            "get_region_context",
            "A region's name, timezone, AQI standard, hazard types, which sources are "
            "configured, and which models are served or degraded. Call first when the "
            "region matters.",
            {"region_id": _REGION},
            [],
        ),
        _decl(
            "get_current_aqi",
            "Served PM2.5 for a place or region, with the band in that region's AQI "
            "standard, provenance (measured vs model-derived) and how old it is.",
            {"place": _PLACE, "region_id": _REGION},
            ["place"],
        ),
        _decl(
            "get_pm25_trend",
            "Hourly stored PM2.5 over the last N hours and how it changed. Use for "
            "'getting worse/better' questions.",
            {
                "place": _PLACE,
                "hours": {"type": "integer", "description": "Look-back hours, 1-72. Default 6."},
                "region_id": _REGION,
            },
            ["place"],
        ),
        _decl(
            "get_pm25_forecast",
            "PM2.5 forecast quantiles (p10/p50/p90) per horizon, with model version and "
            "whether a baseline answered.",
            {"place": _PLACE, "region_id": _REGION},
            ["place"],
        ),
        _decl(
            "get_weather",
            "Observed wind now and forecast wind (with issue time) at the site nearest a place.",
            {"place": _PLACE, "region_id": _REGION},
            ["place"],
        ),
        _decl(
            "get_satellite_signal",
            "Satellite aerosol signal for a place. Reports plainly when none is served.",
            {"place": _PLACE, "region_id": _REGION},
            ["place"],
        ),
        _decl(
            "get_plume",
            "Simulated smoke transport (experimental): footprint, places reached with "
            "probability and ETA, exposed population. direction='backward' gives the "
            "likely source region. Give exactly one of place, incident_id, report_id.",
            {
                "place": _PLACE,
                "incident_id": _INCIDENT,
                "report_id": _string("Citizen report id."),
                "direction": _string("'forward' (default) or 'backward'."),
                "region_id": _REGION,
            },
            [],
        ),
        _decl(
            "get_population_exposure",
            "Simulated population inside an incident's plume footprint per horizon, "
            "with population source and year.",
            {"incident_id": _INCIDENT},
            ["incident_id"],
        ),
        _decl(
            "get_source_likelihood",
            "Heuristic, uncalibrated ranking of likely pollution sources near a place, "
            "with the evidence behind it.",
            {"place": _PLACE, "region_id": _REGION},
            ["place"],
        ),
        _decl(
            "get_citizen_reports",
            "Citizen photo reports near a place or linked to an incident: AI visual "
            "class, corroboration level and geo-trust. Give one of place or incident_id.",
            {"place": _PLACE, "incident_id": _INCIDENT, "region_id": _REGION},
            [],
        ),
        _decl(
            "list_incidents",
            "Active incidents in a region with root kind, places reached and last update.",
            {"region_id": _REGION},
            [],
        ),
        _decl(
            "get_incident_graph",
            "The nodes and edges of one incident, each with its provenance class.",
            {"incident_id": _INCIDENT},
            ["incident_id"],
        ),
        _decl(
            "explain_incident",
            "Everything about one incident in a single call: air quality, fires, wind, "
            "satellite, forward plume, back-trajectory, exposure, source likelihood and "
            "citizen reports. Prefer this for 'why' questions about an incident.",
            {"incident_id": _INCIDENT},
            ["incident_id"],
        ),
        _decl(
            "query_trends",
            "Rows from an allow-listed history template over an explicit window (at most "
            f"{MAX_QUERY_DAYS} days). Templates: {', '.join(sorted(QUERY_TEMPLATES))}.",
            {
                "template_id": _string("Template id, e.g. 'pm25_hourly'."),
                "place": _PLACE,
                "start": _string("ISO-8601 start time."),
                "end": _string("ISO-8601 end time."),
                "region_id": _REGION,
            },
            ["template_id", "place", "start", "end"],
        ),
    ]
