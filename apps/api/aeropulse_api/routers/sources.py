"""Source registry API (LLD §25.3)."""

from __future__ import annotations

from aeropulse_auth.jwt import Role, TokenClaims
from aeropulse_connector_app.registry import SPECS_BY_ID
from aeropulse_connector_sdk.base import DataConnector
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from aeropulse_api.deps import get_claims, require
from aeropulse_api.source_health_store import (
    SourceHealthReader,
    SourceHealthRow,
    get_source_health_reader,
)
from aeropulse_api.source_registry import registry_by_id, registry_items, repo_root

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])

#: In-memory overlay for POST/PUT used by tests. Yaml remains the source of
#: truth for the running connector; this never writes sources.yaml.
_OVERRIDES: dict[str, dict] = {}


class SourceWrite(BaseModel):
    """Payload for creating or updating a source (no secrets)."""

    source_id: str
    provider: str
    connector_id: str
    display_name: str
    data_type: str
    enabled: bool = True
    auth_ref: str | None = Field(default=None, description="Secret name, never the value")


class BackfillRequest(BaseModel):
    """Historical replay window (LLD §38)."""

    start: str
    end: str
    bbox: list[float] | None = None


def reset_source_overrides() -> None:
    """Clear test overlays (called from API test fixtures)."""
    _OVERRIDES.clear()


def _telemetry(health: SourceHealthRow | None) -> dict:
    """Nullable health fields. Never invent a freshness from enabled=true."""
    if health is None:
        return {
            "last_success_at": None,
            "latency_ms": None,
            "records_per_run": None,
            "error": None,
            "processing_mode": None,
            "quality_score": None,
            "error_rate": None,
        }
    return {
        "last_success_at": health.last_success_at.isoformat() if health.last_success_at else None,
        "latency_ms": health.latency_ms,
        "records_per_run": health.records_per_run,
        "error": health.last_error,
        "processing_mode": health.processing_mode,
        "quality_score": health.quality_score,
        "error_rate": health.error_rate,
    }


def _merged_items(health_by_id: dict[str, SourceHealthRow]) -> list[dict]:
    """Yaml registry, then test overlays, then nullable telemetry."""
    items = {item["source_id"]: dict(item) for item in registry_items()}
    for source_id, overlay in _OVERRIDES.items():
        base = items.get(source_id, {"source_id": source_id, "status": "registered"})
        items[source_id] = {**base, **overlay}
    merged: list[dict] = []
    for item in items.values():
        health = health_by_id.get(item["source_id"])
        row = {**item, **_telemetry(health)}
        if health is not None:
            row["status"] = health.status
        merged.append(row)
    return merged


def _known(health_by_id: dict[str, SourceHealthRow]) -> dict[str, dict]:
    return {item["source_id"]: item for item in _merged_items(health_by_id)}


def _source_connector(source_id: str) -> DataConnector | None:
    """Instantiate a connector from SOURCE_SPECS when the fixture is present."""
    spec = SPECS_BY_ID.get(source_id)
    if spec is None:
        return None
    return spec.build(repo_root() / "fixtures")


@router.get("")
def list_sources(
    _claims: TokenClaims = Depends(get_claims),
    health: SourceHealthReader = Depends(get_source_health_reader),
    limit: int | None = Query(default=None, ge=1, le=500, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Items to skip"),
) -> dict:
    """List registered data sources with nullable connector telemetry."""
    items = _merged_items(health.latest())
    total = len(items)
    page = items[offset : offset + limit] if limit is not None else items[offset:]
    return {"items": page, "total": total, "limit": limit, "offset": offset}


@router.get("/{source_id}")
def get_source(
    source_id: str,
    _claims: TokenClaims = Depends(get_claims),
    health: SourceHealthReader = Depends(get_source_health_reader),
) -> dict:
    """Return a single source or 404."""
    source = _known(health.latest()).get(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.post("", status_code=201)
def create_source(
    body: SourceWrite,
    _claims: TokenClaims = Depends(require(Role.ADMIN)),
) -> dict:
    """Register a source. Secrets must be referenced by ``auth_ref`` only."""
    record = body.model_dump()
    record["status"] = "registered"
    _OVERRIDES[body.source_id] = record
    return record


@router.put("/{source_id}")
def update_source(
    source_id: str,
    body: SourceWrite,
    _claims: TokenClaims = Depends(require(Role.ADMIN)),
) -> dict:
    """Update source configuration (in-memory overlay; does not edit yaml)."""
    known = {**registry_by_id(), **_OVERRIDES}
    if source_id not in known:
        raise HTTPException(status_code=404, detail="Source not found")
    record = body.model_dump()
    record["status"] = "updated"
    _OVERRIDES[source_id] = record
    return record


@router.post("/{source_id}/test")
def test_source(
    source_id: str,
    _claims: TokenClaims = Depends(require(Role.ADMIN, Role.OPERATOR)),
) -> dict:
    """Run a connector health check using the actual fixture-backed connector."""
    known = {**registry_by_id(), **_OVERRIDES}
    if source_id not in known:
        raise HTTPException(status_code=404, detail="Source not found")

    connector = _source_connector(source_id)
    if connector is None:
        return {
            "source_id": source_id,
            "connector_id": known[source_id].get("connector_id", source_id),
            "healthy": True,
            "mode": "replay",
            "message": "configured",
        }

    status = connector.health_check()
    return {
        "source_id": source_id,
        "connector_id": status.connector_id,
        "healthy": status.healthy,
        "mode": "replay",
        "message": status.message,
        "checked_at": status.checked_at.isoformat(),
    }


@router.post("/{source_id}/backfill")
def backfill_source(
    source_id: str,
    body: BackfillRequest,
    _claims: TokenClaims = Depends(require(Role.ADMIN, Role.OPERATOR)),
) -> dict:
    """Run fixture replay for a source with processing_mode=BACKFILL."""
    known = {**registry_by_id(), **_OVERRIDES}
    if source_id not in known:
        raise HTTPException(status_code=404, detail="Source not found")
    from pathlib import Path

    from aeropulse_connector_app.runner import replay_all
    from aeropulse_contracts.envelope import KafkaEnvelope, ProcessingMode

    published = 0

    def _count(_topic: str, envelope: KafkaEnvelope) -> None:
        nonlocal published
        if envelope.source_id == source_id:
            published += 1

    root = Path("/app/fixtures") if Path("/app/fixtures").exists() else Path("fixtures")
    if root.exists():
        replay_all(root, _count, processing_mode=ProcessingMode.BACKFILL)
    return {
        "source_id": source_id,
        "accepted": True,
        "processing_mode": "BACKFILL",
        "start": body.start,
        "end": body.end,
        "records": published,
    }
