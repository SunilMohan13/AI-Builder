"""Plume APIs (LLD APAC 8.6). Every footprint is simulated transport, labelled experimental."""

from __future__ import annotations

import threading
from collections import OrderedDict, defaultdict, deque
from datetime import datetime, timedelta
from time import monotonic
from typing import Annotated, Any, Literal

import h3
from aeropulse_auth.jwt import Role, TokenClaims
from aeropulse_contracts.plume import Plume, PlumeOrigin
from aeropulse_intelligence.plume import PlumeInputError, simulate
from aeropulse_intelligence.plume.region import RegionTransport
from aeropulse_ml.datasets.history import read_raw_window
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from aeropulse_api.deps import get_claims, require
from aeropulse_api.platform import (
    ApiPlatform,
    get_platform,
    no_snapshot_reason,
    not_configured,
    page,
    region_id_param,
    snapshot_meta,
)

router = APIRouter(prefix="/api/v1", tags=["plume"])

PLUME_LABEL = "Predicted smoke transport — experimental"
#: Raw history the what-if reads for forecast wind and its error.
WHAT_IF_HISTORY_HOURS = 72
#: Rounding of the what-if cache key (about 1 km), so nearby clicks share a run.
WHAT_IF_ROUND_DECIMALS = 2
WHAT_IF_CACHE_SIZE = 128

_what_if_cache: OrderedDict[tuple[Any, ...], Plume] = OrderedDict()
_what_if_calls: defaultdict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def reset_what_if_state() -> None:
    with _lock:
        _what_if_cache.clear()
        _what_if_calls.clear()


def _find_plume(platform: ApiPlatform, plume_id: str) -> Plume:
    for region_id in sorted(platform.catalog.packs):
        plume = platform.storage.plumes.get(region_id, plume_id)
        if plume is not None:
            return plume
    raise HTTPException(status_code=404, detail=f"Plume {plume_id} not found")


@router.get("/plumes")
def list_plumes(
    _claims: Annotated[TokenClaims, Depends(get_claims)],
    platform: Annotated[ApiPlatform, Depends(get_platform)],
    region_id: Annotated[str, Depends(region_id_param)],
    direction: Annotated[Literal["forward", "backward"] | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """The latest cycle's plume documents: every horizon's P50 / P90 cells, for an H3 layer."""
    snapshot = platform.latest(region_id)
    if snapshot is None:
        return {
            **page([], limit, offset),
            **not_configured(region_id, "plumes", no_snapshot_reason(region_id)),
        }
    plumes: list[dict[str, Any]] = []
    missing = []
    for summary in snapshot.plumes:
        if direction is not None and summary.direction != direction:
            continue
        plume = platform.storage.plumes.get(region_id, summary.plume_id)
        if plume is None:
            missing.append(summary.plume_id)
            continue
        plumes.append({**plume.model_dump(mode="json"), "label": PLUME_LABEL})
    return {
        **page(plumes, limit, offset),
        "region_id": region_id,
        "label": PLUME_LABEL,
        "data_source": snapshot_meta(snapshot),
        "field_status": [
            {"field": f"plume:{pid}", "reason": "plume document not in the plume store"}
            for pid in missing
        ],
    }


@router.get("/plume/{plume_id}")
def get_plume(
    plume_id: str,
    _claims: Annotated[TokenClaims, Depends(get_claims)],
    platform: Annotated[ApiPlatform, Depends(get_platform)],
) -> dict[str, Any]:
    body = _find_plume(platform, plume_id).model_dump(mode="json")
    body["label"] = PLUME_LABEL
    return body


def _footprint(plume: Plume, horizon_hours: float | None) -> list[dict[str, Any]]:
    horizons = plume.horizons
    if horizon_hours is not None:
        horizons = [h for h in horizons if abs(h.horizon_hours - horizon_hours) < 1e-6]
    else:
        # Particles that left the source domain leave a late horizon empty;
        # default to the last one that still has a footprint.
        with_cells = [h for h in horizons if h.p90_cells]
        horizons = [max(with_cells, key=lambda h: h.horizon_hours)] if with_cells else []
    features = []
    for horizon in horizons:
        for band, cells in (("p90", horizon.p90_cells), ("p50", horizon.p50_cells)):
            if not cells:
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": h3.cells_to_geo(cells),
                    "properties": {
                        "plume_id": plume.plume_id,
                        "direction": plume.direction,
                        "origin_kind": plume.origin.kind,
                        "horizon_hours": horizon.horizon_hours,
                        "band": band,
                        "cell_count": len(cells),
                        "weight_remaining": horizon.weight_remaining,
                        "model_version": plume.model_version,
                        "provenance_class": plume.provenance_class,
                        "experimental": plume.experimental,
                        "degraded": plume.degraded,
                        "degraded_reasons": plume.degraded_reasons,
                        "label": PLUME_LABEL,
                    },
                }
            )
    return features


@router.get("/map/plume")
def map_plume(
    _claims: Annotated[TokenClaims, Depends(get_claims)],
    platform: Annotated[ApiPlatform, Depends(get_platform)],
    region_id: Annotated[str, Depends(region_id_param)],
    horizon_hours: Annotated[float | None, Query(gt=0, le=72)] = None,
    direction: Annotated[Literal["forward", "backward"], Query()] = "forward",
) -> dict[str, Any]:
    """P50 / P90 footprints of the snapshot's plumes at one horizon (default: the last)."""
    snapshot = platform.latest(region_id)
    if snapshot is None:
        return {
            "type": "FeatureCollection",
            "features": [],
            **not_configured(region_id, "plumes", no_snapshot_reason(region_id)),
        }
    features: list[dict[str, Any]] = []
    missing = []
    for summary in snapshot.plumes:
        if summary.direction != direction:
            continue
        plume = platform.storage.plumes.get(region_id, summary.plume_id)
        if plume is None:
            missing.append(summary.plume_id)
            continue
        features.extend(_footprint(plume, horizon_hours))
    return {
        "type": "FeatureCollection",
        "features": features,
        "label": PLUME_LABEL,
        "data_source": snapshot_meta(snapshot),
        "field_status": [
            {"field": f"plume:{pid}", "reason": "plume document not in the plume store"}
            for pid in missing
        ],
    }


class WhatIfBody(BaseModel):
    model_config = {"extra": "forbid"}

    region_id: str | None = None
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    initial_spread_km: float = Field(default=1.0, ge=0.0, le=50.0)


def _rate_limit(subject: str, per_hour: int) -> None:
    now = monotonic()
    with _lock:
        calls = _what_if_calls[subject]
        while calls and now - calls[0] >= 3600:
            calls.popleft()
        if len(calls) >= per_hour:
            raise HTTPException(status_code=429, detail="What-if rate limit exceeded")
        calls.append(now)


def _floor_hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


@router.post("/plume/what-if")
def what_if(
    body: WhatIfBody,
    claims: Annotated[
        TokenClaims, Depends(require(Role.OPERATOR, Role.ANALYST, Role.AUTHORITY, Role.ADMIN))
    ],
    platform: Annotated[ApiPlatform, Depends(get_platform)],
) -> dict[str, Any]:
    """A forward plume from a map click, on the latest cycle's wind. Not stored."""
    pack = platform.region_at(body.lat, body.lon)
    region_id = body.region_id or (pack.region_id if pack else platform.settings.default_region)
    platform.pack(region_id)
    if pack is None or pack.region_id != region_id:
        raise HTTPException(status_code=422, detail=f"Point is outside {region_id}")
    snapshot = platform.latest(region_id)
    if snapshot is None:
        return not_configured(region_id, "plume", no_snapshot_reason(region_id))
    transport = RegionTransport.load(platform.catalog, region_id)
    if transport is None:
        return not_configured(region_id, "plume", f"no hazard in {region_id} runs a plume")

    key = (
        region_id,
        snapshot.cycle_id,
        round(body.lat, WHAT_IF_ROUND_DECIMALS),
        round(body.lon, WHAT_IF_ROUND_DECIMALS),
        round(body.initial_spread_km, 1),
    )
    with _lock:
        cached = _what_if_cache.get(key)
        if cached is not None:
            _what_if_cache.move_to_end(key)
    if cached is None:
        _rate_limit(claims.sub, platform.settings.plume_what_if_per_hour)
        release = _floor_hour(snapshot.cycle_time)
        history = read_raw_window(
            platform.storage.analytics,
            region_id,
            start=release - timedelta(hours=WHAT_IF_HISTORY_HOURS),
            end=release + timedelta(hours=1),
            max_bytes=platform.storage.max_query_bytes,
        )
        inputs = transport.forward_inputs(history.forecasts, history.weather, release)
        if inputs is None:
            return not_configured(region_id, "plume", "no forecast wind covers the plume window")
        origin = PlumeOrigin(
            kind="operator",
            lat=key[2],
            lon=key[3],
            initial_spread_km=key[4],
        )
        try:
            cached = simulate(
                region_id=region_id,
                cycle_time=release,
                direction="forward",
                origin=origin,
                horizons_hours=transport.forward_hours,
                inputs=inputs,
            )
        except PlumeInputError as exc:
            return not_configured(region_id, "plume", str(exc))
        with _lock:
            _what_if_cache[key] = cached
            while len(_what_if_cache) > WHAT_IF_CACHE_SIZE:
                _what_if_cache.popitem(last=False)
    result = cached.model_dump(mode="json")
    result["label"] = PLUME_LABEL
    result["stored"] = False
    result["data_source"] = snapshot_meta(snapshot)
    result["field_status"] = [s.model_dump(mode="json") for s in transport.field_status]
    return result
