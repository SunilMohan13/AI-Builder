"""The existing map and event reader protocols, answered from a region snapshot (LLD APAC 12.1).

When a cycle has written a snapshot for the requested region, the map and
events routers serve it instead of Timescale or the corridor fixtures, with
no change to their response shapes. Every feature carries the provenance
class the cycle recorded, and every collection says which cycle it came from.
"""

from __future__ import annotations

from typing import Any

import h3
from aeropulse_contracts import RegionSnapshot
from aeropulse_contracts.event import EventEvidence, EventStatus, PollutionEvent
from aeropulse_contracts.forecast import ForecastResult
from aeropulse_contracts.lineage import EvidenceGraph

from aeropulse_api.platform import snapshot_meta


def _inside(bbox: list[float] | None, lat: float, lon: float) -> bool:
    if bbox is None:
        return True
    min_lon, min_lat, max_lon, max_lat = bbox
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def _point(lon: float, lat: float, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": properties,
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


class SnapshotMapReader:
    """``MapReader`` over one snapshot."""

    def __init__(self, snapshot: RegionSnapshot) -> None:
        self.snapshot = snapshot
        self.data_source = snapshot_meta(snapshot)

    def air_quality(self, bbox: list[float] | None, limit: int) -> list[dict]:
        features = []
        for cell in self.snapshot.cells:
            if cell.pm25 is None or not _inside(bbox, cell.lat, cell.lon):
                continue
            features.append(
                _point(
                    cell.lon,
                    cell.lat,
                    {
                        "source_id": cell.pm25_source_id,
                        "parameter": "pm25",
                        "value": cell.pm25,
                        "unit": "ug/m3",
                        "observed_at": _iso(cell.observed_at),
                        "grid_id": cell.grid_id,
                        "provenance_class": cell.provenance_class,
                        "aqi_band": cell.aqi_band.model_dump(mode="json")
                        if cell.aqi_band
                        else None,
                        "field_status": [s.model_dump(mode="json") for s in cell.field_status],
                    },
                )
            )
        return features[:limit]

    def fire(self, bbox: list[float] | None, limit: int) -> list[dict]:
        features = [
            _point(
                fire.lon,
                fire.lat,
                {
                    "source_id": fire.source_ids[0] if fire.source_ids else None,
                    "source_ids": fire.source_ids,
                    "cluster_id": fire.cluster_id,
                    "frp": fire.frp_total,
                    "detection_count": fire.detection_count,
                    "first_seen": _iso(fire.first_seen),
                    "observed_at": _iso(fire.last_seen),
                    "grid_id": fire.parent_cell,
                    "provenance_class": fire.provenance_class,
                },
            )
            for fire in self.snapshot.fires
            if _inside(bbox, fire.lat, fire.lon)
        ]
        return features[:limit]

    def weather(self, bbox: list[float] | None, limit: int) -> list[dict]:
        latest: dict[str, Any] = {}
        for wind in self.snapshot.wind:
            if wind.issued_at is not None or not _inside(bbox, wind.lat, wind.lon):
                continue
            key = f"{wind.site_id}:{wind.level}"
            if key not in latest or wind.valid_at > latest[key].valid_at:
                latest[key] = wind
        features = [
            _point(
                wind.lon,
                wind.lat,
                {
                    "site_id": wind.site_id,
                    "level": wind.level,
                    "wind_u": wind.u,
                    "wind_v": wind.v,
                    "observed_at": _iso(wind.valid_at),
                    "provenance_class": wind.provenance_class,
                },
            )
            for _, wind in sorted(latest.items())
        ]
        return features[:limit]

    def forecast(self, limit: int, horizon_hours: int | None = None) -> list[dict]:
        features = []
        for item in self.snapshot.forecasts:
            if horizon_hours is not None and item.horizon_hours != horizon_hours:
                continue
            lat, lon = h3.cell_to_latlng(item.grid_id)
            features.append(_point(lon, lat, item.model_dump(mode="json")))
        return features[:limit]

    def grid(self, limit: int) -> list[dict]:
        features = []
        for cell in self.snapshot.cells:
            ring = [[lon, lat] for lat, lon in h3.cell_to_boundary(cell.grid_id)]
            ring.append(ring[0])
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                    "properties": cell.model_dump(mode="json"),
                }
            )
        return features[:limit]

    def satellite(self, limit: int) -> list[dict]:
        return []

    def hazard(self, limit: int) -> list[dict]:
        features = []
        for item in self.snapshot.hazard:
            lat, lon = h3.cell_to_latlng(item.grid_id)
            features.append(_point(lon, lat, item.model_dump(mode="json")))
        return features[:limit]


class SnapshotEventReader:
    """``EventReader`` over one snapshot. Evidence and lineage are not in the snapshot."""

    def __init__(self, snapshot: RegionSnapshot) -> None:
        self.snapshot = snapshot
        self.data_source = snapshot_meta(snapshot)

    def list_events(
        self, status: EventStatus | None, limit: int | None, offset: int
    ) -> tuple[list[PollutionEvent], int]:
        events = [e for e in self.snapshot.events if status is None or e.status == status]
        events.sort(key=lambda e: (e.updated_at, e.event_id), reverse=True)
        window = events[offset : offset + limit] if limit is not None else events[offset:]
        return window, len(events)

    def get_event(self, event_id: str) -> PollutionEvent | None:
        return next((e for e in self.snapshot.events if e.event_id == event_id), None)

    def get_evidence(self, event_id: str) -> list[EventEvidence]:
        return []

    def get_forecast(self, event_id: str) -> ForecastResult | None:
        return None

    def get_graph(self, event_id: str) -> EvidenceGraph | None:
        return None


class NotConfiguredMapReader:
    """No snapshot and no legacy source for a region: every layer empty, with the reason."""

    def __init__(self, region_id: str, reason: str) -> None:
        self.data_source = {"kind": "not_configured", "region_id": region_id, "reason": reason}

    def air_quality(self, bbox: list[float] | None, limit: int) -> list[dict]:
        return []

    def fire(self, bbox: list[float] | None, limit: int) -> list[dict]:
        return []

    def weather(self, bbox: list[float] | None, limit: int) -> list[dict]:
        return []

    def forecast(self, limit: int, horizon_hours: int | None = None) -> list[dict]:
        return []

    def grid(self, limit: int) -> list[dict]:
        return []

    def satellite(self, limit: int) -> list[dict]:
        return []


class NotConfiguredEventReader:
    def __init__(self, region_id: str, reason: str) -> None:
        self.data_source = {"kind": "not_configured", "region_id": region_id, "reason": reason}

    def list_events(
        self, status: EventStatus | None, limit: int | None, offset: int
    ) -> tuple[list[PollutionEvent], int]:
        return [], 0

    def get_event(self, event_id: str) -> PollutionEvent | None:
        return None

    def get_evidence(self, event_id: str) -> list[EventEvidence]:
        return []

    def get_forecast(self, event_id: str) -> ForecastResult | None:
        return None

    def get_graph(self, event_id: str) -> EvidenceGraph | None:
        return None
