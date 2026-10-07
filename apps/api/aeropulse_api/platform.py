"""Region catalog, storage and citizen settings as one request dependency (LLD APAC 12.1).

Every snapshot-backed router reads through :func:`get_platform`, so tests
swap the whole data plane with one ``dependency_overrides`` entry instead of
patching module globals. Reads only: the API never writes a snapshot, a
plume or a model file; the only writes it makes are citizen report
documents and uploads.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Any

from aeropulse_common.settings import Settings, get_settings
from aeropulse_contracts import RegionSnapshot
from aeropulse_contracts.provenance import FieldStatus
from aeropulse_regions import (
    CitizenSettings,
    RegionCatalog,
    RegionPack,
    bbox_contains_point,
    load_catalog,
    load_citizen_settings,
)
from aeropulse_storage import Storage, build_storage
from fastapi import Depends, HTTPException, Query


@dataclass
class ApiPlatform:
    settings: Settings
    catalog: RegionCatalog
    storage: Storage
    citizen: CitizenSettings
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    def pack(self, region_id: str) -> RegionPack:
        pack = self.catalog.packs.get(region_id)
        if pack is None:
            raise HTTPException(status_code=404, detail=f"Unknown region {region_id!r}")
        return pack

    def latest(self, region_id: str) -> RegionSnapshot | None:
        return self.storage.snapshots.latest(region_id)

    def region_at(self, lat: float, lon: float) -> RegionPack | None:
        """The onboarded region whose display area contains the point."""
        for region_id in sorted(self.catalog.packs):
            pack = self.catalog.packs[region_id]
            if bbox_contains_point(pack.geometry.bbox, lat, lon):
                return pack
        return None


@lru_cache(maxsize=1)
def _default_platform() -> ApiPlatform:
    settings = get_settings()
    catalog = load_catalog(settings.config_dir)
    return ApiPlatform(
        settings=settings,
        catalog=catalog,
        storage=build_storage(settings),
        citizen=load_citizen_settings(catalog.config_dir),
    )


def get_platform() -> ApiPlatform:
    return _default_platform()


def reset_platform() -> None:
    """Drop the cached platform (tests, or after settings change)."""
    _default_platform.cache_clear()


def region_id_param(
    platform: Annotated[ApiPlatform, Depends(get_platform)],
    region_id: Annotated[
        str | None, Query(description="Region id; defaults to AEROPULSE_DEFAULT_REGION")
    ] = None,
) -> str:
    """A known region id, defaulting from settings; 404 for an unknown one."""
    wanted = region_id or platform.settings.default_region
    platform.pack(wanted)
    return wanted


def not_configured(region_id: str, field_name: str, reason: str) -> dict[str, Any]:
    """The body for something that cannot be served, instead of an empty success."""
    return {
        "status": "not_configured",
        "region_id": region_id,
        "field_status": [FieldStatus(field=field_name, reason=reason).model_dump(mode="json")],
    }


def no_snapshot_reason(region_id: str) -> str:
    return f"no cycle has written a snapshot for {region_id} yet"


def snapshot_meta(snapshot: RegionSnapshot) -> dict[str, Any]:
    """Which cycle a snapshot-backed response came from."""
    return {
        "kind": "snapshot",
        "region_id": snapshot.region_id,
        "cycle_id": snapshot.cycle_id,
        "cycle_time": snapshot.cycle_time.isoformat(),
        "mode": snapshot.mode,
        "pack_version": snapshot.pack_version,
    }


def page(items: list[Any], limit: int | None, offset: int) -> dict[str, Any]:
    window = items[offset : offset + limit] if limit is not None else items[offset:]
    return {"items": window, "total": len(items), "limit": limit, "offset": offset}
