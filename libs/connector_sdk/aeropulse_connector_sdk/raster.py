"""Replay helper that maps raster product JSON to raster.v1."""

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


def _opt_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, str)):
        return float(value)
    return None


class RasterFixtureConnector(DataConnector):
    """Generic fixture connector for satellite/raster metadata products."""

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
        """Return static connector metadata."""
        return self._meta

    def discover(self) -> list[SourceAsset]:
        """Return the product listed in the fixture, if any."""
        if not self.fixture_path:
            return []
        payload = load_fixture(self.fixture_path)
        return [
            SourceAsset(asset_id=str(p["product_id"]), name=str(p.get("name", p["product_id"])))
            for p in payload.get("products", [])
        ]

    def fetch(self, request: FetchRequest) -> Iterator[RawRecord]:
        """Yield one raw record per raster product in the fixture."""
        if not self.fixture_path:
            return
        payload = load_fixture(self.fixture_path)
        fetched_at = datetime.now(UTC)
        for product in payload.get("products", []):
            yield RawRecord(
                source_id=self.source_id,
                source_record_id=str(product["product_id"]),
                payload=product,
                fetched_at=fetched_at,
            )

    def normalize(self, record: RawRecord) -> Sequence[RasterObservation]:
        """Map a product dict to raster.v1. Arrays stay in object storage."""
        product = record.payload
        acquired = datetime.fromisoformat(str(product["acquisition_time"]).replace("Z", "+00:00"))
        bbox = tuple(float(x) for x in product["bbox"])
        cloud = product.get("cloud_fraction")
        return [
            RasterObservation(
                observation_id=new_ulid("rst"),
                source_id=self.source_id,
                source_record_id=record.source_record_id,
                product_id=str(product["product_id"]),
                acquisition_time=acquired,
                processing_time=record.fetched_at,
                bbox=bbox,  # type: ignore[arg-type]
                resolution=str(product.get("resolution", "unknown")),
                object_uri=str(product.get("object_uri", record.raw_uri or "")),
                checksum=str(product.get("checksum", "fixture")),
                cloud_fraction=float(cloud) if cloud is not None else None,
                quality=Quality(
                    quality_flag="valid", quality_score=float(product.get("quality_score", 0.8))
                ),
                provenance=Provenance(
                    provider=self.provider,
                    connector_version=self._meta.version,
                    raw_object_uri=record.raw_uri,
                ),
                sample_aod=_opt_float(product.get("sample_aod")),
                sample_no2=_opt_float(product.get("sample_no2")),
                sample_pm25=_opt_float(product.get("sample_pm25")),
            )
        ]

    def health_check(self) -> HealthStatus:
        """Replay health is fixture presence."""
        return HealthStatus(
            connector_id=self._meta.connector_id,
            healthy=self.fixture_path is not None and self.fixture_path.exists(),
            message="replay" if self.fixture_path else "no fixture",
            checked_at=datetime.now(UTC),
        )
