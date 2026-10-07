"""Replay helper for periodic geospatial asset inventories."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

from aeropulse_common.ids import new_ulid
from aeropulse_contracts.observation import Provenance, Quality
from aeropulse_contracts.raster import RasterObservation

from aeropulse_connector_sdk.base import DataConnector
from aeropulse_connector_sdk.contracts import (
    ConnectorMetadata,
    FetchRequest,
    HealthStatus,
    RawRecord,
    SourceAsset,
)
from aeropulse_connector_sdk.testing import load_fixture, load_yaml_metadata


class GeoAssetConnector(DataConnector):
    """Maps inventory JSON (points + bbox) to raster.v1 metadata records."""

    def __init__(
        self,
        *,
        metadata_path: Path,
        fixture_path: Path | None,
        source_id: str,
        provider: str,
    ) -> None:
        self._meta = load_yaml_metadata(metadata_path)
        self.fixture_path = fixture_path
        self.source_id = source_id
        self.provider = provider

    def metadata(self) -> ConnectorMetadata:
        """Return connector metadata."""
        return self._meta

    def discover(self) -> list[SourceAsset]:
        """List assets from the fixture."""
        if not self.fixture_path:
            return []
        payload = load_fixture(self.fixture_path)
        return [
            SourceAsset(asset_id=str(a["asset_id"]), name=str(a.get("name", a["asset_id"])))
            for a in payload.get("assets", [])
        ]

    def fetch(self, request: FetchRequest) -> Iterator[RawRecord]:
        """Yield inventory records."""
        if not self.fixture_path:
            return
        payload = load_fixture(self.fixture_path)
        fetched = datetime.now(UTC)
        for asset in payload.get("assets", []):
            yield RawRecord(
                source_id=self.source_id,
                source_record_id=str(asset["asset_id"]),
                payload=asset,
                fetched_at=fetched,
            )

    def normalize(self, record: RawRecord) -> Sequence[RasterObservation]:
        """Encode a geospatial asset as raster.v1 metadata (no large arrays)."""
        asset = record.payload
        lat = float(asset.get("lat", 0))
        lon = float(asset.get("lon", 0))
        bbox = (
            tuple(float(x) for x in asset["bbox"])
            if "bbox" in asset
            else (lon - 0.05, lat - 0.05, lon + 0.05, lat + 0.05)
        )
        acquired = datetime.fromisoformat(
            str(asset.get("observed_at", record.fetched_at.isoformat())).replace("Z", "+00:00")
        )
        return [
            RasterObservation(
                observation_id=new_ulid("geo"),
                source_id=self.source_id,
                source_record_id=record.source_record_id,
                product_id=str(asset.get("product_id", record.source_record_id)),
                acquisition_time=acquired,
                processing_time=record.fetched_at,
                bbox=bbox,  # type: ignore[arg-type]
                resolution=str(asset.get("resolution", "vector")),
                object_uri=str(asset.get("object_uri", "")),
                checksum=str(asset.get("checksum", "fixture")),
                cloud_fraction=None,
                quality=Quality(quality_flag="valid", quality_score=0.9),
                provenance=Provenance(
                    provider=self.provider,
                    connector_version=self._meta.version,
                    raw_object_uri=record.raw_uri,
                ),
            )
        ]

    def health_check(self) -> HealthStatus:
        """Replay health is fixture presence."""
        return HealthStatus(
            connector_id=self._meta.connector_id,
            healthy=self.fixture_path is not None and self.fixture_path.exists(),
            message="replay",
            checked_at=datetime.now(UTC),
        )
