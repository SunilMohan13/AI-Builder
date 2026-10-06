"""Map tile/query APIs (LLD §25.1)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from aeropulse_auth.jwt import TokenClaims
from fastapi import APIRouter, Depends, HTTPException, Query

from aeropulse_api.deps import get_claims
from aeropulse_api.grid_store import GridReader, get_grid_reader
from aeropulse_api.hazard_store import hazard_cells
from aeropulse_api.map_store import MapReader, get_map_reader

router = APIRouter(prefix="/api/v1/map", tags=["map"])


def _collection(features: list[dict]) -> dict:
    return {
        "type": "FeatureCollection",
        "generated_at": datetime.now(UTC).isoformat(),
        "features": features,
    }


def _fixture_assets(source_id: str) -> list[dict]:
    """Read deterministic geo assets for domains without a Timescale table."""
    path = Path("/app") / "fixtures" / source_id / "assets.json"
    if not path.exists():
        path = Path("fixtures") / source_id / "assets.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
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
) -> dict:
    """Return recent air-quality points as GeoJSON."""
    return _collection(reader.air_quality(_parse_bbox(bbox), limit))


@router.get("/fire")
def fire(
    bbox: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    _claims: TokenClaims = Depends(get_claims),
    reader: MapReader = Depends(get_map_reader),
) -> dict:
    """Return recent fire detections as GeoJSON."""
    return _collection(reader.fire(_parse_bbox(bbox), limit))


@router.get("/weather")
def weather(
    bbox: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    _claims: TokenClaims = Depends(get_claims),
    reader: MapReader = Depends(get_map_reader),
) -> dict:
    """Return recent meteorological points as GeoJSON."""
    return _collection(reader.weather(_parse_bbox(bbox), limit))


@router.get("/satellite")
def satellite(
    limit: int = Query(default=500, ge=1, le=2000),
    _claims: TokenClaims = Depends(get_claims),
    reader: MapReader = Depends(get_map_reader),
) -> dict:
    """Return latest persisted satellite/raster metadata footprints."""
    return _collection(reader.satellite(limit))


@router.get("/forecast")
def forecast(
    limit: int = Query(default=500, ge=1, le=2000),
    horizon_hours: int | None = Query(default=None, ge=0, le=48),
    _claims: TokenClaims = Depends(get_claims),
    reader: MapReader = Depends(get_map_reader),
) -> dict:
    """Return persisted advection forecast points as GeoJSON.

    Args:
        limit: Maximum features.
        horizon_hours: Return only this horizon. Omit for every horizon.
            The map timeline uses this so scrubbing forward shows the
            forecast for that hour instead of redrawing the present.
    """
    return _collection(reader.forecast(limit, horizon_hours))


@router.get("/grid")
def grid(
    limit: int = Query(default=500, ge=1, le=2000),
    _claims: TokenClaims = Depends(get_claims),
    reader: MapReader = Depends(get_map_reader),
) -> dict:
    """Return latest persisted H3 grid cells as GeoJSON polygons."""
    return _collection(reader.grid(limit))


@router.get("/hazard")
def hazard(
    limit: int = Query(default=500, ge=1, le=2000),
    _claims: TokenClaims = Depends(get_claims),
    reader: GridReader = Depends(get_grid_reader),
) -> dict:
    """Return the 24-hour hazard layer as GeoJSON points.

    Every feature carries ``degraded`` and ``calibrated`` in its properties.
    A hazard number rendered without them would be the most consequential
    mislabelling this API can produce: an uncalibrated ranking shown as a
    probability, or a persistence rule shown as a model forecast.
    """
    features, _ = reader.list_features(None, None, None, limit, 0)
    cells, provenance = hazard_cells(list(features))
    collection = _collection(
        [
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
        ]
    )
    collection["provenance"] = provenance
    return collection


@router.get("/industry")
def industry(
    limit: int = Query(default=500, ge=1, le=2000),
    _claims: TokenClaims = Depends(get_claims),
) -> dict:
    """Return replayed industry/OCEMS asset locations."""
    return _collection(_fixture_assets("industry")[:limit])
