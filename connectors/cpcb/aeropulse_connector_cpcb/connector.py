"""CPCB connector: maps station pollutant snapshots to observation.v1."""

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
from aeropulse_contracts.observation import (
    Location,
    Measurement,
    Observation,
    Provenance,
    Quality,
)

_PACKAGE_DIR = Path(__file__).resolve().parent
_METADATA = load_yaml_metadata(_PACKAGE_DIR / "metadata.yaml")

PARAMETER_MAP = {
    "pm25": ("pm25", "ug/m3"),
    "pm2_5": ("pm25", "ug/m3"),
    "PM2.5": ("pm25", "ug/m3"),
    "pm10": ("pm10", "ug/m3"),
    "PM10": ("pm10", "ug/m3"),
    "no2": ("no2", "ug/m3"),
    "NO2": ("no2", "ug/m3"),
    "so2": ("so2", "ug/m3"),
    "SO2": ("so2", "ug/m3"),
    "co": ("co", "mg/m3"),
    "CO": ("co", "mg/m3"),
    "o3": ("o3", "ug/m3"),
    "O3": ("o3", "ug/m3"),
}


class CpcbConnector(DataConnector):
    """Reads CPCB-like station payloads (replay fixtures or live JSON)."""

    def __init__(self, fixture_path: Path | None = None) -> None:
        self.fixture_path = fixture_path

    def metadata(self) -> ConnectorMetadata:
        """Return CPCB connector metadata."""
        return _METADATA

    def discover(self) -> list[SourceAsset]:
        """Return stations from the current fixture, if any."""
        if not self.fixture_path:
            return []
        payload = load_fixture(self.fixture_path)
        return [
            SourceAsset(
                asset_id=str(station["station_id"]),
                name=str(station.get("name", station["station_id"])),
            )
            for station in payload.get("stations", [])
        ]

    def fetch(self, request: FetchRequest) -> Iterator[RawRecord]:
        """Yield one raw record per station in the replay fixture."""
        if not self.fixture_path:
            return
        payload = load_fixture(self.fixture_path)
        fetched_at = datetime.now(UTC)
        for station in apply_cursor(payload.get("stations", []), request.cursor):
            yield RawRecord(
                source_id="cpcb",
                source_record_id=str(station["station_id"]),
                payload=station,
                fetched_at=fetched_at,
            )

    def normalize(self, record: RawRecord) -> Sequence[Observation]:
        """Map a station snapshot into one Observation per pollutant."""
        station = record.payload
        observed_at = datetime.fromisoformat(str(station["observed_at"]).replace("Z", "+00:00"))
        location = Location(lat=float(station["lat"]), lon=float(station["lon"]))
        pollutants = station.get("pollutants") or {}
        observations: list[Observation] = []
        for raw_name, raw_value in pollutants.items():
            mapped = PARAMETER_MAP.get(str(raw_name))
            if mapped is None:
                continue
            parameter, unit = mapped
            source_record_id = f"{record.source_record_id}_{station['observed_at']}_{parameter}"
            observations.append(
                Observation(
                    observation_id=new_ulid("obs"),
                    source_id="cpcb",
                    source_record_id=source_record_id,
                    observed_at=observed_at,
                    received_at=record.fetched_at,
                    location=location,
                    measurement=Measurement(parameter=parameter, value=float(raw_value), unit=unit),
                    quality=Quality(quality_flag="valid", quality_score=1.0),
                    provenance=Provenance(
                        provider="CPCB",
                        connector_version=_METADATA.version,
                        raw_object_uri=record.raw_uri,
                    ),
                )
            )
        return observations

    def health_check(self) -> HealthStatus:
        """Replay connector is healthy when a fixture path is configured."""
        return HealthStatus(
            connector_id=_METADATA.connector_id,
            healthy=self.fixture_path is not None and self.fixture_path.exists(),
            message="replay" if self.fixture_path else "no fixture",
            checked_at=datetime.now(UTC),
        )
