"""Model catalog (LLD §19).

One registry backs this endpoint: the filesystem
:class:`~aeropulse_ml.registry.ModelRegistry`. The deterministic baselines are
registered into it as real records rather than merged in from a hardcoded
literal, so a single read reports both what serves today and what has been
trained but withheld, and the two can never disagree.
"""

from typing import Annotated

from aeropulse_auth.jwt import TokenClaims
from aeropulse_ml.baselines import is_baseline, sync_baselines
from aeropulse_ml.registry import ModelRecord, ModelRegistry, ModelStage
from fastapi import APIRouter, Depends, Query

from aeropulse_api.deps import get_claims

router = APIRouter(prefix="/api/v1/models", tags=["models"])


def _runtime_role(record: ModelRecord) -> str:
    """Classify how a record participates in serving.

    Args:
        record: Registry record.

    Returns:
        ``PRIMARY_BASELINE`` for the deterministic code path,
        ``PRIMARY_MODEL`` for a promoted trained artifact, ``SHADOW_MODEL``
        for a challenger scored alongside the champion but never returned, and
        ``REGISTERED_ONLY`` for anything that does not affect a response.
    """
    if is_baseline(record):
        return "PRIMARY_BASELINE" if record.stage is ModelStage.PRODUCTION else "RETIRED_BASELINE"
    if record.stage is ModelStage.PRODUCTION:
        return "PRIMARY_MODEL"
    if record.stage in (ModelStage.SHADOW, ModelStage.CANARY):
        return "SHADOW_MODEL"
    return "REGISTERED_ONLY"


@router.get("")
def list_models(
    _claims: Annotated[TokenClaims, Depends(get_claims)],
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """List every registered model, serving and withheld alike.

    Args:
        _claims: Authenticated caller.
        limit: Maximum records to return. Omitted returns all of them.
        offset: Records to skip.

    Returns:
        ``items``/``total``/``limit``/``offset``, matching the list convention
        used by the other collection endpoints.
    """
    registry = ModelRegistry()
    # Idempotent: only writes when a baseline is missing, so a read-only API
    # process does not churn the index on every request.
    sync_baselines(registry)

    records = registry.list_models()
    total = len(records)
    window = records[offset : offset + limit] if limit is not None else records[offset:]

    items = []
    for record in window:
        payload = record.model_dump(mode="json")
        payload["runtime_role"] = _runtime_role(record)
        # Retained for existing consumers that read `approval_status`; `stage`
        # is the field to use.
        payload["approval_status"] = record.stage.value
        payload["artifact_available"] = bool(
            record.artifact_uri and registry.artifact_path(record).is_file()
        )
        items.append(payload)

    return {"items": items, "total": total, "limit": limit, "offset": offset}
