"""FIRMS connector: maps VIIRS fire detections to fire_observation.v1.

The live path uses NASA's area CSV API. Two things about it shape this code:

* the MAP_KEY sits in the URL *path*, so the URL must never be logged and is
  redacted before it can reach an error message;
* ``acq_time`` is ``HHMM`` with leading zeros stripped, so ``"412"`` means
  04:12 UTC. Reading it naively produces fires at plausible-looking wrong
  times, which is worse than a parse failure.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aeropulse_common.ids import new_ulid
from aeropulse_common.settings import get_settings
from aeropulse_connector_sdk.base import DataConnector
from aeropulse_connector_sdk.checkpoint import apply_cursor
from aeropulse_connector_sdk.contracts import (
    ConnectorMetadata,
    FetchRequest,
    HealthStatus,
    RawRecord,
    SourceAsset,
)
from aeropulse_connector_sdk.live_http import LiveHttpClient
from aeropulse_connector_sdk.testing import load_fixture, load_yaml_metadata
from aeropulse_contracts.fire import FireObservation, FireProperties
from aeropulse_contracts.observation import Location, Provenance, Quality
from aeropulse_observability.logging import get_logger

logger = get_logger("aeropulse.connector.firms")

_PACKAGE_DIR = Path(__file__).resolve().parent
_METADATA = load_yaml_metadata(_PACKAGE_DIR / "metadata.yaml")

SOURCE_ID = "firms"
AREA_CSV_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

#: Default satellite product. NOAA-20 VIIRS gives 375 m resolution with good
#: NRT latency over the Punjab-Delhi corridor.
DEFAULT_PRODUCT = "VIIRS_NOAA20_NRT"

#: Punjab - Haryana - Delhi NCR as (west, south, east, north). FIRMS orders
#: its bbox differently from the GeoJSON convention, so this is not
#: interchangeable with the OpenAQ bbox.
DEFAULT_BBOX: tuple[float, float, float, float] = (73.8, 27.5, 78.5, 32.2)

#: The API caps a request at 10 days; 1-5 is the useful NRT range.
MAX_DAY_RANGE = 5


def _confidence_to_unit(raw: object) -> float:
    if isinstance(raw, (int, float)):
        value = float(raw)
        return value / 100.0 if value > 1 else value
    mapping = {"l": 0.3, "n": 0.6, "h": 0.9, "low": 0.3, "nominal": 0.6, "high": 0.9}
    return mapping.get(str(raw).lower(), 0.5)


def redact_map_key(url: str) -> str:
    """Replace a MAP_KEY path segment with a placeholder.

    FIRMS puts the credential between ``/csv/`` and the product name, so any
    URL that reaches a log or an exception has to pass through here first.
    """
    return re.sub(r"(/api/area/csv/)[^/]+", r"\1<redacted>", url)


def _parse_acq_datetime(acq_date: str, acq_time: str) -> datetime:
    """Combine FIRMS ``acq_date`` and ``acq_time`` into aware UTC.

    ``acq_time`` is HHMM with leading zeros stripped: ``"412"`` is 04:12 and
    ``"0"`` is midnight. Zero-padding before slicing is the whole point.

    Args:
        acq_date: ``YYYY-MM-DD``.
        acq_time: ``HHMM``, possibly short.

    Returns:
        Timezone-aware UTC datetime.
    """
    padded = str(acq_time).strip().zfill(4)
    hour, minute = int(padded[:2]), int(padded[2:])
    day = datetime.strptime(acq_date.strip(), "%Y-%m-%d").replace(tzinfo=UTC)
    return day + timedelta(hours=hour, minutes=minute)


class FirmsConnector(DataConnector):
    """Read VIIRS fire detections from the FIRMS area API or a fixture.

    Args:
        fixture_path: Replay payload used whenever live mode is off.
        bbox: Area of interest as (west, south, east, north).
        product: FIRMS satellite product name.
        client: Pre-built hardened HTTP client, primarily for tests.
    """

    def __init__(
        self,
        fixture_path: Path | None = None,
        *,
        bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
        product: str = DEFAULT_PRODUCT,
        client: LiveHttpClient | None = None,
        live: bool | None = None,
        map_key: str | None = None,
        day_range: int | None = None,
    ) -> None:
        self.fixture_path = fixture_path
        self.bbox = bbox
        self.product = product
        self._client = client
        # Plugin path: mode and credential come from the ConnectorContext.
        # ``None`` keeps the legacy behaviour of reading settings.
        self._live = live
        self._explicit_key = map_key
        self._fixed_day_range = day_range

    @property
    def client(self) -> LiveHttpClient:
        """Return the shared hardened client, building it on first use."""
        if self._client is None:
            # 5000 transactions per 10 minutes is generous; the server also
            # caches each area+product for ~10 minutes, so polling harder
            # returns the same rows.
            self._client = LiveHttpClient(
                SOURCE_ID, rate_per_second=2.0, timeout=30.0, require_live_mode=self._live is None
            )
        return self._client

    def metadata(self) -> ConnectorMetadata:
        """Return FIRMS connector metadata."""
        return _METADATA

    def is_live(self) -> bool:
        """Whether this cycle should hit the network."""
        if self._live is not None:
            return self._live
        return get_settings().connector_mode == "live"

    def _map_key(self) -> str | None:
        if self._live is not None:
            return self._explicit_key or None
        secret = get_settings().firms_map_key
        if secret is None:
            return None
        value = secret.get_secret_value()
        return value or None

    def discover(self) -> list[SourceAsset]:
        """FIRMS has a single virtual asset (VIIRS detections)."""
        return [SourceAsset(asset_id="viirs", name="VIIRS active fire")]

    def _day_range(self, request: FetchRequest) -> int:
        """Pick how many days to request from the resume window.

        FIRMS re-returns the whole day on every call, so a wider range is
        only needed after an outage.
        """
        if self._fixed_day_range is not None and request.start_time is None:
            return max(1, min(MAX_DAY_RANGE, self._fixed_day_range))
        if request.start_time is None:
            return 1
        behind = datetime.now(UTC) - request.start_time
        return max(1, min(MAX_DAY_RANGE, behind.days + 1))

    def fetch(self, request: FetchRequest) -> Iterator[RawRecord]:
        """Yield one raw record per fire detection."""
        if not self.is_live():
            yield from self._fetch_fixture(request)
            return
        yield from self._fetch_live(request)

    def _fetch_fixture(self, request: FetchRequest) -> Iterator[RawRecord]:
        if not self.fixture_path:
            return
        payload = load_fixture(self.fixture_path)
        fetched_at = datetime.now(UTC)
        for idx, fire in enumerate(apply_cursor(payload.get("fires", []), request.cursor)):
            yield RawRecord(
                source_id=SOURCE_ID,
                source_record_id=str(fire.get("id", f"fire_{idx}")),
                payload=fire,
                fetched_at=fetched_at,
            )

    def _fetch_live(self, request: FetchRequest) -> Iterator[RawRecord]:
        key = self._map_key()
        if key is None:
            # The runner gates on credential presence before calling us; this
            # is the belt-and-braces guard so a direct caller cannot build a
            # URL with "None" in the key position.
            raise ValueError("AEROPULSE_FIRMS_MAP_KEY is not set")

        west, south, east, north = self.bbox
        url = (
            f"{AREA_CSV_URL}/{key}/{self.product}/"
            f"{west},{south},{east},{north}/{self._day_range(request)}"
        )
        try:
            body = self.client.get_text(url)
        except Exception as exc:
            # Never let a raw URL carrying the key reach a log or a traceback.
            raise RuntimeError(f"FIRMS fetch failed for {redact_map_key(url)}") from exc

        fetched_at = datetime.now(UTC)
        for row in csv.DictReader(io.StringIO(body)):
            if not row.get("latitude"):
                continue
            yield RawRecord(
                source_id=SOURCE_ID,
                source_record_id=self._record_id(row),
                payload=dict(row),
                fetched_at=fetched_at,
            )

    def _record_id(self, row: dict[str, Any]) -> str:
        """Build a deterministic id for a detection.

        FIRMS publishes no stable detection id and re-returns the whole day on
        every call, so dedup depends entirely on this being reproducible.
        """
        return "_".join(
            str(row.get(field, "")).strip()
            for field in ("satellite", "acq_date", "acq_time", "latitude", "longitude")
        )

    def normalize(self, record: RawRecord) -> Sequence[FireObservation]:
        """Map a FIRMS detection to a canonical fire observation."""
        fire = record.payload
        if "acq_date" in fire:
            observed_at = _parse_acq_datetime(str(fire["acq_date"]), str(fire.get("acq_time", "0")))
            lat, lon = float(fire["latitude"]), float(fire["longitude"])
            frp = float(fire.get("frp") or 0.0)
            confidence = _confidence_to_unit(fire.get("confidence", 0.5))
            sensor = str(fire.get("instrument") or fire.get("satellite") or "VIIRS")
        else:
            observed_at = datetime.fromisoformat(str(fire["observed_at"]).replace("Z", "+00:00"))
            lat, lon = float(fire["lat"]), float(fire["lon"])
            frp = float(fire["frp"])
            confidence = _confidence_to_unit(fire.get("confidence", 0.5))
            sensor = str(fire.get("sensor", "VIIRS"))

        return [
            FireObservation(
                observation_id=new_ulid("fire"),
                source_id=SOURCE_ID,
                source_record_id=record.source_record_id,
                observed_at=observed_at,
                received_at=record.fetched_at,
                location=Location(lat=lat, lon=lon),
                fire=FireProperties(frp=frp, confidence=confidence, sensor=sensor),
                quality=Quality(quality_flag="valid", quality_score=1.0),
                provenance=Provenance(
                    provider="NASA",
                    connector_version=_METADATA.version,
                    raw_object_uri=record.raw_uri,
                ),
            )
        ]

    def health_check(self) -> HealthStatus:
        """Report whether this connector can run as currently configured."""
        checked_at = datetime.now(UTC)
        if self.is_live():
            present = self._map_key() is not None
            return HealthStatus(
                connector_id=_METADATA.connector_id,
                healthy=present,
                message="live mode; credential present"
                if present
                else "AEROPULSE_FIRMS_MAP_KEY is not set",
                checked_at=checked_at,
            )
        return HealthStatus(
            connector_id=_METADATA.connector_id,
            healthy=self.fixture_path is not None and self.fixture_path.exists(),
            message="replay" if self.fixture_path else "no fixture",
            checked_at=checked_at,
        )
