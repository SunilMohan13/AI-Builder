"""What is served, and why (LLD APAC 7.5, 12.1).

``GET /api/v1/models`` reports, per family, the model or rule the latest
cycle actually served in a region, with its degraded reason. Before any
cycle has run it falls back to what ``config/model_serving.yaml`` declares,
marked as unverified. ``GET /api/v1/models/registry`` lists the legacy
filesystem registry read-only; the deterministic baselines are merged in
memory, so a GET never writes the registry.
"""

from __future__ import annotations

from typing import Annotated, Any

from aeropulse_auth.jwt import TokenClaims
from aeropulse_ml.baselines import baseline_records, is_baseline
from aeropulse_ml.registry import ModelRecord, ModelRegistry, ModelStage
from aeropulse_ml.serving.config import SERVING_FILENAME, load_serving_config
from fastapi import APIRouter, Depends, Query

from aeropulse_api.deps import get_claims
from aeropulse_api.platform import (
    ApiPlatform,
    get_platform,
    no_snapshot_reason,
    page,
    region_id_param,
    snapshot_meta,
)

router = APIRouter(prefix="/api/v1/models", tags=["models"])


@router.get("")
def served_models(
    _claims: Annotated[TokenClaims, Depends(get_claims)],
    platform: Annotated[ApiPlatform, Depends(get_platform)],
    region_id: Annotated[str, Depends(region_id_param)],
) -> dict[str, Any]:
    snapshot = platform.latest(region_id)
    if snapshot is not None:
        items = [
            {**m.model_dump(mode="json"), "verified_by_cycle": True} for m in snapshot.served_models
        ]
        return {
            **page(items, None, 0),
            "region_id": region_id,
            "data_source": snapshot_meta(snapshot),
            "field_status": [],
        }
    config = load_serving_config(platform.catalog.config_dir / SERVING_FILENAME)
    items = [
        {
            "family": entry.family,
            "model_version": entry.model_version,
            "feature_version": None,
            "degraded": None,
            "degraded_reason": None,
            "calibrated": entry.calibrated,
            "verified_by_cycle": False,
        }
        for entry in config.entries
        if entry.region_id == region_id
    ]
    return {
        **page(items, None, 0),
        "region_id": region_id,
        "data_source": {"kind": "model_serving.yaml"},
        "field_status": [
            {
                "field": "items",
                "reason": (
                    f"{no_snapshot_reason(region_id)}; listing model_serving.yaml entries "
                    "that no cycle has loaded and checked"
                ),
            }
        ],
    }


def _runtime_role(record: ModelRecord) -> str:
    """``PRIMARY_BASELINE``, ``PRIMARY_MODEL``, ``SHADOW_MODEL`` or ``REGISTERED_ONLY``."""
    if is_baseline(record):
        return "PRIMARY_BASELINE" if record.stage is ModelStage.PRODUCTION else "RETIRED_BASELINE"
    if record.stage is ModelStage.PRODUCTION:
        return "PRIMARY_MODEL"
    if record.stage in (ModelStage.SHADOW, ModelStage.CANARY):
        return "SHADOW_MODEL"
    return "REGISTERED_ONLY"


@router.get("/registry")
def list_registry(
    _claims: Annotated[TokenClaims, Depends(get_claims)],
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """Every registered model plus the baselines, without writing the registry."""
    registry = ModelRegistry()
    records = registry.list_models()
    known = {r.model_id for r in records}
    records = [*records, *(b for b in baseline_records() if b.model_id not in known)]
    items = []
    for record in records:
        payload = record.model_dump(mode="json")
        payload["runtime_role"] = _runtime_role(record)
        payload["approval_status"] = record.stage.value
        payload["artifact_available"] = bool(
            record.artifact_uri and registry.artifact_path(record).is_file()
        )
        items.append(payload)
    return page(items, limit, offset)
