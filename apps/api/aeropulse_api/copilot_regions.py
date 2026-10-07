"""The copilot's region data, read through the API platform's storage."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from aeropulse_contracts import RegionSnapshot
from aeropulse_contracts.observation import Observation
from aeropulse_contracts.plume import Plume
from aeropulse_copilot.context import SeriesPoint
from aeropulse_intelligence.plume.outputs import Place
from aeropulse_intelligence.plume.region import load_places
from aeropulse_ml.datasets.records import decode
from aeropulse_regions import RegionCatalog

from aeropulse_api.platform import ApiPlatform

_MISSING = object()


class PlatformRegionData:
    """Stored output only, cached for the lifetime of one copilot request."""

    def __init__(self, platform: ApiPlatform) -> None:
        self._platform = platform
        self._snapshots: dict[str, RegionSnapshot | None] = {}
        self._places: dict[str, list[Place]] = {}

    @property
    def catalog(self) -> RegionCatalog:
        return self._platform.catalog

    def snapshot(self, region_id: str) -> RegionSnapshot | None:
        cached = self._snapshots.get(region_id, _MISSING)
        if cached is _MISSING:
            cached = self._platform.latest(region_id)
            self._snapshots[region_id] = cached
        return cached  # type: ignore[return-value]

    def plume(self, region_id: str, plume_id: str) -> Plume | None:
        return self._platform.storage.plumes.get(region_id, plume_id)

    def places(self, region_id: str) -> Sequence[Place]:
        if region_id not in self._places:
            pack = self.catalog.get(region_id)
            places = load_places(self.catalog.region_dir(region_id), pack)
            self._places[region_id] = places or []
        return self._places[region_id]

    def pm25_series(self, region_id: str, start: datetime, end: datetime) -> list[SeriesPoint]:
        storage = self._platform.storage
        rows = storage.analytics.query(
            "raw.air_quality.window",
            {"region_id": region_id, "start": start, "end": end},
            max_bytes=storage.max_query_bytes,
        )
        points = []
        for record in decode("observations", (str(r["record"]) for r in rows)):
            if not isinstance(record, Observation) or record.measurement.parameter != "pm25":
                continue
            if not start <= record.observed_at < end:
                continue
            klass = record.provenance.provenance_class
            points.append(
                SeriesPoint(
                    grid_id=record.grid_id,
                    lat=record.location.lat,
                    lon=record.location.lon,
                    observed_at=record.observed_at,
                    value=record.measurement.value,
                    source_id=record.source_id,
                    provenance_class=klass.value if klass is not None else None,
                )
            )
        return points

    def citizen_reports(
        self, region_id: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        storage = self._platform.storage
        return storage.analytics.query(
            "citizen.reports.window",
            {"region_id": region_id, "start": start, "end": end},
            max_bytes=storage.max_query_bytes,
        )
