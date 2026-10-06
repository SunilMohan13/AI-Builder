"""OpenAQ v3 connector: reference-grade ground-station air quality.

This is the source that makes "live PM2.5 in Delhi" a measured value rather
than a model estimate. Discovery is filtered to ``monitor=true``, which
restricts results to reference-grade government monitors — in India, the CPCB
CAAQMS network. Open-Meteo remains the modelled background; this is ground
truth.

API: https://api.openaq.org/v3, authenticated with an ``X-API-Key`` header.
Header auth matters here: the credential never enters a URL, so it cannot
appear in request logs.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aeropulse_common.ids import new_ulid
from aeropulse_common.settings import get_settings
from aeropulse_connector_sdk.base import DataConnector
from aeropulse_connector_sdk.contracts import (
    ConnectorMetadata,
    FetchRequest,
    HealthStatus,
    RawRecord,
    SourceAsset,
)
from aeropulse_connector_sdk.live_http import LiveHttpClient
from aeropulse_connector_sdk.testing import load_fixture, load_yaml_metadata
from aeropulse_contracts.observation import (
    Location,
    Measurement,
    Observation,
    Provenance,
    ProvenanceClass,
    Quality,
)
from aeropulse_observability.logging import get_logger

logger = get_logger("aeropulse.connector.openaq")

_PACKAGE_DIR = Path(__file__).resolve().parent
_METADATA = load_yaml_metadata(_PACKAGE_DIR / "metadata.yaml")

SOURCE_ID = "openaq"
BASE_URL = "https://api.openaq.org/v3"
LOCATIONS_URL = f"{BASE_URL}/locations"

#: Punjab - Haryana - Delhi NCR, matching the Open-Meteo corridor sites so the
#: two sources fuse over the same geography. (minLon, minLat, maxLon, maxLat).
DEFAULT_BBOX: tuple[float, float, float, float] = (73.8, 27.5, 78.5, 32.2)

#: Caps the per-cycle request count deterministically. Each location costs one
#: /latest call, and OpenAQ allows 60 requests/minute.
DEFAULT_MAX_LOCATIONS = 60

#: OpenAQ parameter name -> (canonical parameter, required canonical unit).
#: Deliberately particulates only. OpenAQ gas sensors commonly report ppm, and
#: the feature builder reads values without consulting their unit, so mixing
#: units would silently corrupt the fused vector rather than fail loudly.
SUPPORTED_PARAMETERS: dict[str, tuple[str, str]] = {
    "pm25": ("pm25", "µg/m³"),
    "pm10": ("pm10", "µg/m³"),
}

#: OpenAQ writes micrograms several ways across endpoints.
_UNIT_ALIASES = {
    "µg/m³": "ug/m3",
    "ug/m3": "ug/m3",
    "µg/m3": "ug/m3",
    "umg/m3": "ug/m3",
}

CANONICAL_UNIT = "ug/m3"


def _canonical_unit(raw_unit: str | None) -> str | None:
    """Map an OpenAQ unit string onto the platform's canonical unit."""
    if raw_unit is None:
        return None
    return _UNIT_ALIASES.get(raw_unit.strip())


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse an OpenAQ datetime object or ISO string into aware UTC."""
    if isinstance(value, dict):
        value = value.get("utc") or value.get("local")
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class OpenAqConnector(DataConnector):
    """Fetch ground-station particulate measurements from OpenAQ v3.

    Args:
        fixture_path: Replay payload used whenever live mode is off.
        bbox: Discovery bounding box as (minLon, minLat, maxLon, maxLat).
        max_locations: Upper bound on locations polled per cycle.
        client: Pre-built hardened HTTP client, primarily for tests.
        max_age_hours: Drop values older than this. ``None`` reads the
            platform default from settings.
    """

    def __init__(
        self,
        fixture_path: Path | None = None,
        *,
        bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
        max_locations: int = DEFAULT_MAX_LOCATIONS,
        client: LiveHttpClient | None = None,
        max_age_hours: int | None = None,
    ) -> None:
        self.fixture_path = fixture_path
        self.bbox = bbox
        self.max_locations = max_locations
        self._client = client
        self._max_age_hours = max_age_hours
        self._window_start: datetime | None = None

    @property
    def client(self) -> LiveHttpClient:
        """Return the shared hardened client, building it on first use."""
        if self._client is None:
            # 60 req/min is the documented allowance. Staying under 1 req/s
            # with a small burst leaves headroom for the discovery call.
            self._client = LiveHttpClient(SOURCE_ID, rate_per_second=0.8, burst=4.0, timeout=20.0)
        return self._client

    @property
    def max_age_hours(self) -> int:
        """Staleness cutoff for a returned value."""
        if self._max_age_hours is not None:
            return self._max_age_hours
        return get_settings().connector_max_observation_age_hours

    def metadata(self) -> ConnectorMetadata:
        """Return OpenAQ connector metadata."""
        return _METADATA

    def is_live(self) -> bool:
        """Whether this cycle should hit the network."""
        return get_settings().connector_mode == "live"

    def _api_key(self) -> str | None:
        secret = get_settings().openaq_api_key
        if secret is None:
            return None
        value = secret.get_secret_value()
        return value or None

    def _headers(self) -> dict[str, str]:
        key = self._api_key()
        return {"X-API-Key": key} if key else {}

    def discover(self) -> list[SourceAsset]:
        """List the reference-grade monitors inside the configured bbox."""
        assets: list[SourceAsset] = []
        for location in self._locations():
            coords = location.get("coordinates") or {}
            lat, lon = coords.get("latitude"), coords.get("longitude")
            if lat is None or lon is None:
                continue
            assets.append(
                SourceAsset(
                    asset_id=str(location["id"]),
                    name=str(location.get("name") or location["id"]),
                    extra={
                        "lat": float(lat),
                        "lon": float(lon),
                        "provider": (location.get("provider") or {}).get("name"),
                    },
                )
            )
        return assets

    def _locations(self) -> list[dict[str, Any]]:
        """Return monitor locations, from the fixture or from discovery."""
        if not self.is_live():
            payload = load_fixture(self.fixture_path) if self.fixture_path else {}
            return list(payload.get("locations", []))
        min_lon, min_lat, max_lon, max_lat = self.bbox
        response = self.client.get_json(
            LOCATIONS_URL,
            params={
                "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat}",
                # parameters_id 2 is PM2.5; monitor=true keeps this to
                # reference-grade government instruments rather than low-cost
                # sensors, which is what makes the CPCB claim honest.
                "parameters_id": 2,
                "monitor": "true",
                "limit": self.max_locations,
            },
            headers=self._headers(),
        )
        return list(response.get("results", []))

    def fetch(self, request: FetchRequest) -> Iterator[RawRecord]:
        """Yield one raw record per monitor location."""
        if not self.is_live():
            self._window_start = None
            yield from self._fetch_fixture()
            return
        self._window_start = request.start_time
        yield from self._fetch_live()

    def _fetch_fixture(self) -> Iterator[RawRecord]:
        if not self.fixture_path:
            return
        payload = load_fixture(self.fixture_path)
        fetched_at = datetime.now(UTC)
        locations = {str(loc["id"]): loc for loc in payload.get("locations", [])}
        for entry in payload.get("latest", []):
            location = locations.get(str(entry.get("locations_id")))
            if location is None:
                continue
            yield RawRecord(
                source_id=SOURCE_ID,
                source_record_id=str(location["id"]),
                payload={"location": location, "latest": entry},
                fetched_at=fetched_at,
            )

    def _fetch_live(self) -> Iterator[RawRecord]:
        for location in self._locations()[: self.max_locations]:
            location_id = location.get("id")
            if location_id is None:
                continue
            latest = self.client.get_json(
                f"{LOCATIONS_URL}/{location_id}/latest",
                headers=self._headers(),
            )
            yield RawRecord(
                source_id=SOURCE_ID,
                source_record_id=str(location_id),
                payload={"location": location, "latest": latest},
                fetched_at=datetime.now(UTC),
            )

    def normalize(self, record: RawRecord) -> Sequence[Observation]:
        """Map one location's latest sensor values to canonical observations.

        Skips any sensor whose parameter is not a supported particulate or
        whose unit is not micrograms per cubic metre, and any value older
        than the staleness cutoff. Both are dropped with a counted reason
        rather than coerced.
        """
        location = record.payload.get("location") or {}
        coords = location.get("coordinates") or {}
        lat, lon = coords.get("latitude"), coords.get("longitude")
        if lat is None or lon is None:
            return []

        sensors = {str(sensor.get("id")): sensor for sensor in (location.get("sensors") or [])}
        provider = (location.get("provider") or {}).get("name")
        # Name the true upstream, not just the aggregator. Some Indian
        # locations in OpenAQ are not CPCB, so this must not be hardcoded.
        provenance = Provenance(
            provenance_class=ProvenanceClass.MEASURED,
            provider=f"OpenAQ / {provider}" if provider else "OpenAQ",
            connector_version=_METADATA.version,
            raw_object_uri=record.raw_uri,
        )
        location_of = Location(lat=float(lat), lon=float(lon))
        # Staleness only applies to a live feed, where `/latest` will happily
        # return a value from a station that died weeks ago. A replayed
        # fixture is historical on purpose and is already reported as REPLAY,
        # so applying the cutoff there would silently empty every cycle.
        cutoff = record.fetched_at - timedelta(hours=self.max_age_hours) if self.is_live() else None

        observations: list[Observation] = []
        for entry in self._latest_entries(record):
            observation = self._to_observation(
                entry, sensors, location, location_of, provenance, record, cutoff
            )
            if observation is not None:
                observations.append(observation)
        return observations

    def _latest_entries(self, record: RawRecord) -> list[dict[str, Any]]:
        latest = record.payload.get("latest") or {}
        if isinstance(latest, dict):
            return list(latest.get("results", []))
        if isinstance(latest, list):
            return list(latest)
        return []

    def _to_observation(
        self,
        entry: dict[str, Any],
        sensors: dict[str, dict[str, Any]],
        location: dict[str, Any],
        location_of: Location,
        provenance: Provenance,
        record: RawRecord,
        cutoff: datetime | None,
    ) -> Observation | None:
        sensor_id = str(entry.get("sensorsId") or entry.get("sensors_id") or "")
        sensor = sensors.get(sensor_id, {})
        parameter_block = sensor.get("parameter") or entry.get("parameter") or {}
        parameter_name = str(parameter_block.get("name") or "").lower()

        supported = SUPPORTED_PARAMETERS.get(parameter_name)
        if supported is None:
            return None

        canonical_parameter, _ = supported
        unit = _canonical_unit(parameter_block.get("units"))
        if unit != CANONICAL_UNIT:
            # A ppm value reaching the feature builder would be read as
            # micrograms. Drop it loudly rather than convert on a guess.
            logger.warning(
                "openaq.unit_unsupported",
                parameter=parameter_name,
                unit=parameter_block.get("units"),
                sensor_id=sensor_id,
            )
            return None

        value = entry.get("value")
        if value is None:
            return None

        observed_at = _parse_timestamp(entry.get("datetime"))
        if observed_at is None:
            return None
        if cutoff is not None and observed_at < cutoff:
            logger.info(
                "openaq.value_stale",
                sensor_id=sensor_id,
                observed_at=observed_at.isoformat(),
                max_age_hours=self.max_age_hours,
            )
            return None
        window_start = getattr(self, "_window_start", None)
        if window_start is not None and observed_at < window_start:
            return None

        return Observation(
            observation_id=new_ulid("obs"),
            source_id=SOURCE_ID,
            # Stable and unique, so dedup_key holds across the overlapping
            # windows a watermark resume deliberately re-requests.
            source_record_id=f"{location.get('id')}_{sensor_id}_{observed_at.isoformat()}",
            observed_at=observed_at,
            received_at=record.fetched_at,
            location=location_of,
            measurement=Measurement(
                parameter=canonical_parameter,
                value=round(float(value), 6),
                unit=CANONICAL_UNIT,
            ),
            quality=Quality(quality_flag="valid", quality_score=1.0),
            provenance=provenance,
        )

    def health_check(self) -> HealthStatus:
        """Report whether this connector can run as currently configured."""
        checked_at = datetime.now(UTC)
        if self.is_live():
            if self._api_key() is None:
                return HealthStatus(
                    connector_id=SOURCE_ID,
                    healthy=False,
                    message="AEROPULSE_OPENAQ_API_KEY is not set",
                    checked_at=checked_at,
                )
            return HealthStatus(
                connector_id=SOURCE_ID,
                healthy=True,
                message="live mode; credential present",
                checked_at=checked_at,
            )
        present = bool(self.fixture_path and self.fixture_path.exists())
        return HealthStatus(
            connector_id=SOURCE_ID,
            healthy=present,
            message="fixture present" if present else "fixture missing",
            checked_at=checked_at,
        )
