"""IMD connector: maps station weather snapshots to meteo.v1."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

from aeropulse_common.ids import new_ulid
from aeropulse_connector_sdk.base import DataConnector
from aeropulse_connector_sdk.checkpoint import apply_cursor
from aeropulse_connector_sdk.contracts import (
    ConnectorMetadata,
    FetchRequest,
    HealthStatus,
    RawRecord,
    SourceAsset,
)
from aeropulse_connector_sdk.testing import load_fixture, load_yaml_metadata
from aeropulse_contracts.meteo import MeteorologicalObservation
from aeropulse_contracts.observation import Location, Provenance, Quality

_PACKAGE_DIR = Path(__file__).resolve().parent
_METADATA = load_yaml_metadata(_PACKAGE_DIR / "metadata.yaml")


class ImdConnector(DataConnector):
    """Reads IMD-like weather payloads from fixtures or live JSON."""

    def __init__(self, fixture_path: Path | None = None) -> None:
        self.fixture_path = fixture_path

    def metadata(self) -> ConnectorMetadata:
        """Return IMD connector metadata."""
        return _METADATA

    def discover(self) -> list[SourceAsset]:
        """Return weather stations from the current fixture, if any."""
        if not self.fixture_path:
            return []
        payload = load_fixture(self.fixture_path)
        return [
            SourceAsset(asset_id=str(s["station_id"]), name=str(s.get("name", s["station_id"])))
            for s in payload.get("stations", [])
        ]

    def fetch(self, request: FetchRequest) -> Iterator[RawRecord]:
        """Yield one raw record per weather station in the fixture."""
        if not self.fixture_path:
            return
        payload = load_fixture(self.fixture_path)
        fetched_at = datetime.now(UTC)
        for station in apply_cursor(payload.get("stations", []), request.cursor):
            yield RawRecord(
                source_id="imd",
                source_record_id=str(station["station_id"]),
                payload=station,
                fetched_at=fetched_at,
            )

    def normalize(self, record: RawRecord) -> Sequence[MeteorologicalObservation]:
        """Map a weather snapshot to a canonical meteorological observation."""
        station = record.payload
        observed_at = datetime.fromisoformat(str(station["observed_at"]).replace("Z", "+00:00"))
        source_record_id = f"{record.source_record_id}_{station['observed_at']}"
        return [
            MeteorologicalObservation(
                observation_id=new_ulid("met"),
                source_id="imd",
                source_record_id=source_record_id,
                observed_at=observed_at,
                received_at=record.fetched_at,
                location=Location(lat=float(station["lat"]), lon=float(station["lon"])),
                parameter="weather",
                wind_u=station.get("wind_u"),
                wind_v=station.get("wind_v"),
                temperature=station.get("temperature"),
                humidity=station.get("humidity"),
                pressure=station.get("pressure"),
                boundary_layer_height=station.get("boundary_layer_height"),
                quality=Quality(quality_flag="valid", quality_score=1.0),
                provenance=Provenance(
                    provider="IMD",
                    connector_version=_METADATA.version,
                    raw_object_uri=record.raw_uri,
                ),
            )
        ]

    def health_check(self) -> HealthStatus:
        """Replay connector is healthy when a fixture path is configured."""
        return HealthStatus(
            connector_id=_METADATA.connector_id,
            healthy=self.fixture_path is not None and self.fixture_path.exists(),
            message="replay" if self.fixture_path else "no fixture",
            checked_at=datetime.now(UTC),
        )
