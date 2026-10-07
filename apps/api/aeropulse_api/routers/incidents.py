"""Incident APIs (LLD APAC 10, 12.1): stable incidents from the latest snapshot."""

from __future__ import annotations

from typing import Annotated, Any

from aeropulse_auth.jwt import TokenClaims
from aeropulse_contracts.graph import IncidentSummary
from fastapi import APIRouter, Depends, HTTPException, Query

from aeropulse_api.deps import get_claims
from aeropulse_api.platform import (
    ApiPlatform,
    get_platform,
    no_snapshot_reason,
    not_configured,
    page,
    region_id_param,
    snapshot_meta,
)

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


def _summary(incident: IncidentSummary) -> dict[str, Any]:
    body = incident.model_dump(mode="json", exclude={"nodes", "edges"})
    body["node_count"] = len(incident.node_ids)
    body["edge_count"] = len(incident.edges)
    return body


def find_incident(platform: ApiPlatform, incident_id: str) -> tuple[IncidentSummary, Any]:
    """The incident and its snapshot, searching every region's latest snapshot."""
    for region_id in sorted(platform.catalog.packs):
        snapshot = platform.latest(region_id)
        if snapshot is None:
            continue
        for incident in snapshot.incidents:
            if incident.incident_id == incident_id:
                return incident, snapshot
    raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")


@router.get("")
def list_incidents(
    _claims: Annotated[TokenClaims, Depends(get_claims)],
    platform: Annotated[ApiPlatform, Depends(get_platform)],
    region_id: Annotated[str, Depends(region_id_param)],
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    snapshot = platform.latest(region_id)
    if snapshot is None:
        return {
            **page([], limit, offset),
            **not_configured(region_id, "incidents", no_snapshot_reason(region_id)),
        }
    incidents = sorted(
        snapshot.incidents, key=lambda i: (i.last_updated, i.incident_id), reverse=True
    )
    return {
        **page([_summary(i) for i in incidents], limit, offset),
        "region_id": region_id,
        "data_source": snapshot_meta(snapshot),
    }


@router.get("/{incident_id}")
def get_incident(
    incident_id: str,
    _claims: Annotated[TokenClaims, Depends(get_claims)],
    platform: Annotated[ApiPlatform, Depends(get_platform)],
) -> dict[str, Any]:
    """The incident with its subgraph: nodes, edges and every grounded attribute."""
    incident, snapshot = find_incident(platform, incident_id)
    body = incident.model_dump(mode="json")
    body["data_source"] = snapshot_meta(snapshot)
    return body


@router.get("/{incident_id}/plume")
def incident_plumes(
    incident_id: str,
    _claims: Annotated[TokenClaims, Depends(get_claims)],
    platform: Annotated[ApiPlatform, Depends(get_platform)],
) -> dict[str, Any]:
    """Full plumes whose nodes belong to the incident."""
    incident, snapshot = find_incident(platform, incident_id)
    ids = [n.node_id.split(":", 2)[2] for n in incident.nodes if n.kind == "plume"]
    plumes = []
    missing = []
    for pid in ids:
        plume = platform.storage.plumes.get(snapshot.region_id, pid)
        if plume is None:
            missing.append(pid)
        else:
            plumes.append(plume.model_dump(mode="json"))
    return {
        "items": plumes,
        "total": len(plumes),
        "limit": None,
        "offset": 0,
        "incident_id": incident_id,
        "data_source": snapshot_meta(snapshot),
        "field_status": [
            {"field": f"plume:{pid}", "reason": "plume document not in the plume store"}
            for pid in missing
        ],
    }
