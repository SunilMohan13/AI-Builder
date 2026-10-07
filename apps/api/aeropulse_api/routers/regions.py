"""Region APIs (LLD APAC 12.1): what each onboarded region is, and what it serves now."""

from __future__ import annotations

from typing import Annotated, Any

from aeropulse_auth.jwt import TokenClaims
from aeropulse_contracts import RegionSnapshot
from fastapi import APIRouter, Depends

from aeropulse_api.deps import get_claims
from aeropulse_api.platform import ApiPlatform, get_platform, no_snapshot_reason, snapshot_meta

router = APIRouter(prefix="/api/v1/regions", tags=["regions"])


def _aqi(platform: ApiPlatform, region_id: str) -> dict[str, Any]:
    standard = platform.catalog.aqi_for(region_id)
    return {
        "key": standard.key,
        "name": standard.name,
        "status": standard.status,
        "reason": standard.reason,
        "averaging": standard.averaging,
        "source_url": standard.source_url,
        "unit": standard.unit,
        "bands": [band.model_dump(mode="json") for band in standard.bands],
        "hazard_label": standard.hazard_label,
    }


def _sources(
    platform: ApiPlatform, region_id: str, snapshot: RegionSnapshot | None
) -> list[dict[str, Any]]:
    pack = platform.pack(region_id)
    health = {h.source_id: h for h in snapshot.source_health} if snapshot else {}
    rows = []
    for entry in pack.sources:
        seen = health.get(entry.id)
        rows.append(
            {
                "source_id": entry.id,
                "enabled": entry.enabled,
                "domain": entry.domain,
                "secret_ref": entry.secret_ref,
                "state": seen.state if seen else None,
                "reason": seen.reason if seen else None,
                "records": seen.records if seen else None,
                "last_success_at": seen.last_success_at.isoformat()
                if seen and seen.last_success_at
                else None,
                "field_status": []
                if seen
                else [
                    {
                        "field": "state",
                        "reason": no_snapshot_reason(region_id)
                        if snapshot is None
                        else "source did not run in the latest cycle",
                    }
                ],
            }
        )
    return rows


def _region(platform: ApiPlatform, region_id: str, *, detail: bool) -> dict[str, Any]:
    pack = platform.pack(region_id)
    snapshot = platform.latest(region_id)
    body: dict[str, Any] = {
        "region_id": pack.region_id,
        "display_name": pack.display_name,
        "pack_version": pack.pack_version,
        "country_codes": pack.country_codes,
        "timezone": pack.timezone,
        "bbox": list(pack.geometry.bbox),
        "source_domain_bbox": list(pack.source_domain.bbox),
        "map_view": pack.map_view.model_dump(mode="json"),
        "aqi_standard": _aqi(platform, region_id),
        "hazards": [
            {
                "key": profile.key,
                "display_name": profile.display_name,
                "source_class": profile.source_class,
                "explainer": profile.copy_text.explainer,
            }
            for profile in platform.catalog.hazards_for(region_id)
        ],
        "ground_truth": pack.ground_truth,
        "default": region_id == platform.settings.default_region,
        "snapshot": snapshot_meta(snapshot) if snapshot else None,
        "served_models": [m.model_dump(mode="json") for m in snapshot.served_models]
        if snapshot
        else None,
        "field_status": []
        if snapshot
        else [{"field": "snapshot", "reason": no_snapshot_reason(region_id)}],
    }
    if detail:
        body["sources"] = _sources(platform, region_id, snapshot)
        body["snapshot_field_status"] = (
            [s.model_dump(mode="json") for s in snapshot.field_status] if snapshot else []
        )
    return body


@router.get("")
def list_regions(
    _claims: Annotated[TokenClaims, Depends(get_claims)],
    platform: Annotated[ApiPlatform, Depends(get_platform)],
) -> dict[str, Any]:
    items = [_region(platform, rid, detail=False) for rid in sorted(platform.catalog.packs)]
    return {"items": items, "total": len(items), "limit": None, "offset": 0}


@router.get("/{region_id}")
def get_region(
    region_id: str,
    _claims: Annotated[TokenClaims, Depends(get_claims)],
    platform: Annotated[ApiPlatform, Depends(get_platform)],
) -> dict[str, Any]:
    return _region(platform, region_id, detail=True)
