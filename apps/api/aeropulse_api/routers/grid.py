"""Materialized grid feature and prediction APIs."""

from datetime import datetime

from aeropulse_auth.jwt import TokenClaims
from fastapi import APIRouter, Depends, HTTPException, Query

from aeropulse_api.deps import get_claims
from aeropulse_api.grid_store import GridReader, get_grid_reader
from aeropulse_api.hazard_store import hazard_cells, peak_forecasts

router = APIRouter(prefix="/api/v1", tags=["grid-intelligence"])


@router.get("/grid-features")
def list_grid_features(
    _claims: TokenClaims = Depends(get_claims),
    reader: GridReader = Depends(get_grid_reader),
    grid_id: str | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """List persisted grid-hour feature vectors, newest first."""
    items, total = reader.list_features(grid_id, start, end, limit, offset)
    return {
        "items": [item.model_dump(mode="json") for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/grid-features/{grid_id}/history")
def grid_feature_history(
    grid_id: str,
    _claims: TokenClaims = Depends(get_claims),
    reader: GridReader = Depends(get_grid_reader),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=48, ge=1, le=500),
) -> dict:
    """Return observed PM2.5 for one cell as a compact series.

    ``hour`` is relative to the newest sample (0 = latest). Points without
    PM2.5 are omitted rather than invented from a single latest value.
    """
    items, _total = reader.list_features(grid_id, start, end, limit, 0)
    observed = [item for item in items if item.pm25 is not None]
    if not observed:
        return {"items": [], "total": 0, "limit": limit, "offset": 0, "grid_id": grid_id}
    newest = max(item.timestamp for item in observed)
    observed.sort(key=lambda item: item.timestamp)
    series = [
        {
            "time": item.timestamp.isoformat(),
            "hour": round((item.timestamp - newest).total_seconds() / 3600),
            "pm25": item.pm25,
        }
        for item in observed
    ]
    return {
        "items": series,
        "total": len(series),
        "limit": limit,
        "offset": 0,
        "grid_id": grid_id,
    }


@router.get("/grid-features/{grid_id}/latest")
def latest_grid_feature(
    grid_id: str,
    _claims: TokenClaims = Depends(get_claims),
    reader: GridReader = Depends(get_grid_reader),
) -> dict:
    """Return the latest persisted feature vector for one grid cell."""
    item = reader.latest_feature(grid_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"No feature found for grid {grid_id}")
    return item.model_dump(mode="json")


@router.get("/grid-predictions")
def list_grid_predictions(
    _claims: TokenClaims = Depends(get_claims),
    reader: GridReader = Depends(get_grid_reader),
    grid_id: str | None = Query(default=None),
    model_version: str | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """List persisted grid predictions, newest first."""
    items, total = reader.list_predictions(grid_id, model_version, start, end, limit, offset)
    return {
        "items": [item.model_dump(mode="json") for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/grid-predictions/{grid_id}/latest")
def latest_grid_prediction(
    grid_id: str,
    _claims: TokenClaims = Depends(get_claims),
    reader: GridReader = Depends(get_grid_reader),
    model_version: str | None = Query(default=None),
) -> dict:
    """Return the latest persisted prediction for one grid cell."""
    item = reader.latest_prediction(grid_id, model_version)
    if item is None:
        raise HTTPException(status_code=404, detail=f"No prediction found for grid {grid_id}")
    return item.model_dump(mode="json")


@router.get("/grid-hazard")
def list_grid_hazard(
    _claims: TokenClaims = Depends(get_claims),
    reader: GridReader = Depends(get_grid_reader),
    grid_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """List 24-hour hazard scores per cell, from persisted features.

    Serves the deterministic baseline while no hazard model is promoted, and
    says so on every item (``degraded``) and once in ``provenance``. A model
    being scored in shadow is deliberately not served here.
    """
    features, total = reader.list_features(grid_id, None, None, limit, offset)
    items, provenance = hazard_cells(list(features))
    return {
        "items": [item.model_dump(mode="json") for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
        "provenance": provenance,
    }


@router.get("/grid-hazard/{grid_id}/latest")
def latest_grid_hazard(
    grid_id: str,
    _claims: TokenClaims = Depends(get_claims),
    reader: GridReader = Depends(get_grid_reader),
) -> dict:
    """Return the latest hazard score for one grid cell."""
    feature = reader.latest_feature(grid_id)
    if feature is None:
        raise HTTPException(status_code=404, detail=f"No feature found for grid {grid_id}")
    items, provenance = hazard_cells([feature])
    if not items:
        raise HTTPException(
            status_code=404,
            detail=f"Grid {grid_id} has no observed PM2.5, so hazard is undefined",
        )
    return {**items[0].model_dump(mode="json"), "provenance": provenance}


@router.get("/grid-peak")
def list_grid_peak(
    _claims: TokenClaims = Depends(get_claims),
    reader: GridReader = Depends(get_grid_reader),
    grid_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """List 24-hour peak PM2.5 forecasts per cell, from persisted features."""
    features, total = reader.list_features(grid_id, None, None, limit, offset)
    items, provenance = peak_forecasts(list(features))
    return {
        "items": [item.model_dump(mode="json") for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
        "provenance": provenance,
    }


@router.get("/grid-peak/{grid_id}/latest")
def latest_grid_peak(
    grid_id: str,
    _claims: TokenClaims = Depends(get_claims),
    reader: GridReader = Depends(get_grid_reader),
) -> dict:
    """Return the latest 24-hour peak forecast for one grid cell."""
    feature = reader.latest_feature(grid_id)
    if feature is None:
        raise HTTPException(status_code=404, detail=f"No feature found for grid {grid_id}")
    items, provenance = peak_forecasts([feature])
    if not items:
        raise HTTPException(
            status_code=404,
            detail=f"Grid {grid_id} has no observed PM2.5, so a peak cannot be projected",
        )
    return {**items[0].model_dump(mode="json"), "provenance": provenance}
