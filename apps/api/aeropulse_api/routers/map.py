"""Map layer APIs (LLD §25.1, APAC 12.1).

Every collection says where it came from in ``data_source``: a region
snapshot (with its cycle id), Timescale, replay fixtures, or
``not_configured`` with the reason. Fixtures are served only for the legacy
``in-north`` corridor in replay mode, and are labelled as such.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from aeropulse_auth.jwt import TokenClaims
from aeropulse_common.settings import get_settings
from fastapi import APIRouter, Depends, HTTPException, Query

from aeropulse_api.deps import get_claims
from aeropulse_api.grid_store import GridReader, get_grid_reader
from aeropulse_api.hazard_store import hazard_cells
from aeropulse_api.map_store import LEGACY_REGION, MapReader, get_map_reader
from aeropulse_api.platform import (
    ApiPlatform,
    get_platform,
    no_snapshot_reason,
    not_configured,
    page,
    region_id_param,
    snapshot_meta,
)
from aeropulse_api.snapshot_readers import SnapshotMapReader

router = APIRouter(prefix="/api/v1/map", tags=["map"])


def _collection(features: list[dict], reader: Any = None, *, now: datetime | None = None) -> dict:
    body: dict[str, Any] = {
        "type": "FeatureCollection",
        "generated_at": (now or datetime.now(UTC)).isoformat(),
        "features": features,
    }
    source = getattr(reader, "data_source", None)
    if source is not None:
        body["data_source"] = source
        if source.get("kind") == "not_configured":
            body["field_status"] = [{"field": "features", "reason": source["reason"]}]
    return body


@lru_cache(maxsize=8)
def _fixture_assets(source_id: str) -> tuple[dict, ...]:
    """Replay geo assets for domains without a live source, read once per process."""
    path = Path("/app") / "fixtures" / source_id / "assets.json"
    if not path.exists():
        path = Path("fixtures") / source_id / "assets.json"
    if not path.exists():
        return ()
    payload = json.loads(path.read_text())
    return tuple(_asset_features(source_id, payload))


def _asset_features(source_id: str, payload: dict) -> list[dict]:
    return [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [asset["lon"], asset["lat"]]},
            "properties": {
                "asset_id": asset.get("asset_id"),
                "name": asset.get("name"),
                "source_id": source_id,
                "observed_at": asset.get("observed_at"),
                "object_uri": asset.get("object_uri"),
            },
        }
        for asset in payload.get("assets", [])
        if "lat" in asset and "lon" in asset
    ]


def _parse_bbox(value: str | None) -> list[float] | None:
    if value is None:
        return None
    try:
        bbox = [float(part) for part in value.split(",")]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="bbox must contain four numbers") from exc
    if len(bbox) != 4:
        raise HTTPException(status_code=422, detail="bbox must contain four numbers")
    min_lon, min_lat, max_lon, max_lat = bbox
    if min_lon > max_lon or min_lat > max_lat:
        raise HTTPException(status_code=422, detail="bbox minimums must not exceed maximums")
    return bbox


@router.get("/air-quality")
def air_quality(
    bbox: str | None = Query(default=None, description="min_lon,min_lat,max_lon,max_lat"),
    limit: int = Query(default=500, ge=1, le=2000),
    _claims: TokenClaims = Depends(get_claims),
    reader: MapReader = Depends(get_map_reader),
    platform: ApiPlatform = Depends(get_platform),
) -> dict:
    """Return recent air-quality points as GeoJSON."""
    return _collection(reader.air_quality(_parse_bbox(bbox), limit), reader, now=platform.clock())


@router.get("/fire")
def fire(
    bbox: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    _claims: TokenClaims = Depends(get_claims),
    reader: MapReader = Depends(get_map_reader),
    platform: ApiPlatform = Depends(get_platform),
) -> dict:
    """Return recent fire detections as GeoJSON."""
    return _collection(reader.fire(_parse_bbox(bbox), limit), reader, now=platform.clock())


@router.get("/weather")
def weather(
    bbox: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    _claims: TokenClaims = Depends(get_claims),
    reader: MapReader = Depends(get_map_reader),
    platform: ApiPlatform = Depends(get_platform),
) -> dict:
    """Return recent meteorological points as GeoJSON."""
    return _collection(reader.weather(_parse_bbox(bbox), limit), reader, now=platform.clock())


@router.get("/satellite")
def satellite(
    limit: int = Query(default=500, ge=1, le=2000),
    _claims: TokenClaims = Depends(get_claims),
    reader: MapReader = Depends(get_map_reader),
    platform: ApiPlatform = Depends(get_platform),
) -> dict:
    """Return latest persisted satellite/raster metadata footprints."""
    return _collection(reader.satellite(limit), reader, now=platform.clock())


@router.get("/forecast")
def forecast(
    limit: int = Query(default=500, ge=1, le=2000),
    horizon_hours: int | None = Query(default=None, ge=0, le=48),
    _claims: TokenClaims = Depends(get_claims),
    reader: MapReader = Depends(get_map_reader),
    platform: ApiPlatform = Depends(get_platform),
) -> dict:
    """Return persisted advection forecast points as GeoJSON.

    Args:
        limit: Maximum features.
        horizon_hours: Return only this horizon. Omit for every horizon.
            The map timeline uses this so scrubbing forward shows the
            forecast for that hour instead of redrawing the present.
    """
    return _collection(reader.forecast(limit, horizon_hours), reader, now=platform.clock())


@router.get("/grid")
def grid(
    limit: int = Query(default=500, ge=1, le=2000),
    _claims: TokenClaims = Depends(get_claims),
    reader: MapReader = Depends(get_map_reader),
    platform: ApiPlatform = Depends(get_platform),
) -> dict:
    """Return latest persisted H3 grid cells as GeoJSON polygons."""
    return _collection(reader.grid(limit), reader, now=platform.clock())


@router.get("/hazard")
def hazard(
    limit: int = Query(default=500, ge=1, le=2000),
    _claims: TokenClaims = Depends(get_claims),
    reader: GridReader = Depends(get_grid_reader),
    platform: ApiPlatform = Depends(get_platform),
    region_id: str = Depends(region_id_param),
) -> dict:
    """Return the 24-hour hazard layer as GeoJSON points.

    Every feature carries ``degraded`` and ``calibrated`` in its properties.
    A hazard number rendered without them would be the most consequential
    mislabelling this API can produce: an uncalibrated ranking shown as a
    probability, or a persistence rule shown as a model forecast.
    """
    snapshot = platform.latest(region_id)
    if snapshot is not None:
        collection = _collection(SnapshotMapReader(snapshot).hazard(limit), now=platform.clock())
        collection["data_source"] = snapshot_meta(snapshot)
        return collection
    if get_settings().platform == "gcp" or region_id != LEGACY_REGION:
        collection = _collection([], now=platform.clock())
        collection["data_source"] = {"kind": "not_configured", "region_id": region_id}
        collection["field_status"] = [
            {"field": "features", "reason": no_snapshot_reason(region_id)}
        ]
        return collection
    features, _ = reader.list_features(None, None, None, limit, 0)
    cells, provenance = hazard_cells(list(features))
    collection = _collection(
        now=platform.clock(),
        features=[
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [cell.center_lon, cell.center_lat],
                },
                "properties": cell.model_dump(mode="json", exclude={"center_lat", "center_lon"}),
            }
            for cell in cells
            if cell.center_lat is not None and cell.center_lon is not None
        ],
    )
    collection["provenance"] = provenance
    return collection


@router.get("/source-likelihood")
def source_likelihood(
    _claims: TokenClaims = Depends(get_claims),
    platform: ApiPlatform = Depends(get_platform),
    region_id: str = Depends(region_id_param),
    limit: int | None = Query(default=None, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Per-cell source ranking with its evidence: heuristic and uncalibrated, never a percentage."""
    snapshot = platform.latest(region_id)
    if snapshot is None:
        return {
            **page([], limit, offset),
            **not_configured(region_id, "source_likelihood", no_snapshot_reason(region_id)),
        }
    items = [s.model_dump(mode="json") for s in snapshot.source_likelihood]
    return {
        **page(items, limit, offset),
        "region_id": region_id,
        "data_source": snapshot_meta(snapshot),
    }


@router.get("/industry")
def industry(
    limit: int = Query(default=500, ge=1, le=2000),
    _claims: TokenClaims = Depends(get_claims),
    platform: ApiPlatform = Depends(get_platform),
    region_id: str = Depends(region_id_param),
) -> dict:
    """Replay industry/OCEMS asset locations: ``in-north`` in replay mode only."""
    settings = get_settings()
    if region_id != LEGACY_REGION or settings.connector_mode != "replay":
        collection = _collection([], now=platform.clock())
        collection["data_source"] = {"kind": "not_configured", "region_id": region_id}
        collection["field_status"] = [
            {"field": "features", "reason": "no live industry source; replay fixtures only"}
        ]
        return collection
    collection = _collection(list(_fixture_assets("industry")[:limit]), now=platform.clock())
    collection["data_source"] = {"kind": "fixtures", "mode": "replay", "region_id": region_id}
    return collection
