"""Open-Meteo connector: the platform's credential-free live data path.

Open-Meteo publishes both a reanalysis-backed air-quality product and an NWP
weather product over anonymous HTTPS. That makes it the one source in the
integration matrix that can be exercised end to end in CI and on a laptop with
no API key, which is why it is wired first: every other source's live path is
blocked on a credential this repository does not hold.

Scientific caveat: Open-Meteo air quality is *model output* (CAMS-derived), not
a ground reference station. It is a legitimate background/prior input per
LLD §9 and a legitimate training signal for pipeline validation, but it must
not be presented as CPCB ground truth. ``provenance.provider`` records this so
the distinction survives into the evidence graph.

Both replay and live modes parse the identical Open-Meteo response shape: the
fixture stores a verbatim upstream payload rather than a hand-simplified one,
so ``normalize`` has exactly one code path and replay cannot drift from live.
"""

from __future__ import annotations

import math
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
from aeropulse_contracts.meteo import MeteorologicalObservation
from aeropulse_contracts.meteo_forecast import MeteoForecast
from aeropulse_contracts.observation import (
    Location,
    Measurement,
    Observation,
    Provenance,
    Quality,
)
from aeropulse_contracts.raster import RasterObservation

_PACKAGE_DIR = Path(__file__).resolve().parent
_METADATA = load_yaml_metadata(_PACKAGE_DIR / "metadata.yaml")

SOURCE_ID = "openmeteo"
PROVIDER = "Open-Meteo (CAMS-derived model output)"

AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

#: Open-Meteo hourly variable -> (canonical parameter, canonical unit, scale).
#: CO arrives in ug/m3 but the platform's canonical unit for CO is mg/m3
#: (matching the CPCB connector), so it is scaled here. Mixing units across
#: sources would silently corrupt the fused feature vector, because the feature
#: builder reads pollutant values without consulting their unit.
AQ_VARIABLES: dict[str, tuple[str, str, float]] = {
    "pm2_5": ("pm25", "ug/m3", 1.0),
    "pm10": ("pm10", "ug/m3", 1.0),
    "nitrogen_dioxide": ("no2", "ug/m3", 1.0),
    "sulphur_dioxide": ("so2", "ug/m3", 1.0),
    "carbon_monoxide": ("co", "mg/m3", 0.001),
    "ozone": ("o3", "ug/m3", 1.0),
}

#: AOD is dimensionless and is deliberately NOT mapped to a pollutant
#: measurement. LLD §18.1 and caveat §65.5 forbid treating AOD as surface
#: PM2.5; it reaches models only as the ``aod`` feature column.
AOD_VARIABLE = "aerosol_optical_depth"

WEATHER_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "surface_pressure",
    "precipitation",
    "wind_speed_10m",
    "wind_direction_10m",
    "boundary_layer_height",
)

#: Extra hourly variables only the forecast path reads: lofted transport wind
#: for the plume ensemble and cloud cover for the stability class.
FORECAST_WEATHER_VARIABLES = (
    "wind_speed_100m",
    "wind_direction_100m",
    "cloud_cover",
)

#: Indo-Gangetic corridor sites (LLD §2.1: Punjab-Haryana-Delhi NCR first).
DEFAULT_SITES: tuple[dict[str, Any], ...] = (
    {"site_id": "delhi_ncr", "name": "Delhi NCR", "lat": 28.61, "lon": 77.21},
    {"site_id": "gurugram", "name": "Gurugram", "lat": 28.46, "lon": 77.03},
    {"site_id": "karnal", "name": "Karnal", "lat": 29.69, "lon": 76.99},
    {"site_id": "ludhiana", "name": "Ludhiana", "lat": 30.90, "lon": 75.86},
    {"site_id": "amritsar", "name": "Amritsar", "lat": 31.63, "lon": 74.87},
)


def wind_components(speed_ms: float, direction_deg: float) -> tuple[float, float]:
    """Convert speed and meteorological direction into u/v components.

    Direction is the compass bearing the wind blows *from*, so the vector points
    the opposite way. This is the exact inverse of
    :func:`aeropulse_intelligence.geometry.wind_direction_from`; keeping them
    consistent matters because advection uses the reconstructed vector.

    Args:
        speed_ms: Wind speed in metres per second.
        direction_deg: Direction the wind blows from, degrees clockwise of north.

    Returns:
        ``(wind_u, wind_v)`` in metres per second, eastward and northward.
    """
    rad = math.radians(direction_deg)
    return (-speed_ms * math.sin(rad), -speed_ms * math.cos(rad))


def _parse_hour(value: str) -> datetime:
    """Parse an Open-Meteo local-naive ISO hour as UTC.

    Requests pin ``timezone=UTC``, so the returned stamps carry no offset and
    must be labelled rather than converted.

    Args:
        value: ISO-8601 timestamp without offset, e.g. ``2026-09-08T06:00``.

    Returns:
        Timezone-aware UTC datetime.
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class OpenMeteoConnector(DataConnector):
    """Fetch air quality and meteorology for a fixed set of corridor sites.

    Args:
        fixture_path: Replay payload used whenever live mode is off.
        sites: Override the default corridor sites.
        client: Pre-built hardened HTTP client, primarily for tests.
        past_days: How many trailing days to request. The feature builder needs
            at least 24 hours of history to populate its lag and rolling
            windows, so the default reaches back further than one day.
        drop_future_hours: Discard hours later than the fetch time. The API
            returns the whole of today, so the tail of every response is a
            forecast. Those rows score ``temporal_q = 0`` in the quality
            engine and land in the dead-letter table as ``future_timestamp``,
            which is a day of noise per site per cycle. Ingestion wants this
            on; a training fetch that deliberately wants the forecast window
            can turn it off.
    """

    def __init__(
        self,
        fixture_path: Path | None = None,
        *,
        sites: Sequence[dict[str, Any]] | None = None,
        client: LiveHttpClient | None = None,
        past_days: int = 2,
        drop_future_hours: bool = True,
        live: bool | None = None,
        keep_forecast_hours: int = 0,
        reference_time: datetime | None = None,
    ) -> None:
        self.fixture_path = fixture_path
        self.sites = list(sites) if sites is not None else list(DEFAULT_SITES)
        self.past_days = past_days
        self.drop_future_hours = drop_future_hours
        self._client = client
        # Plugin path: mode from the ConnectorContext; ``None`` reads settings.
        self._live = live
        #: Hours after the model run kept as ``meteo_forecast.v1``. Zero keeps
        #: the legacy behaviour of dropping the forecast tail.
        self.keep_forecast_hours = max(0, keep_forecast_hours)
        #: "Now" for the observation/forecast split. In replay it is the
        #: replayed cycle time, so a replay cannot see past its own instant.
        self.reference_time = reference_time

    @property
    def client(self) -> LiveHttpClient:
        """Return the shared hardened client, building it on first use."""
        if self._client is None:
            # Open-Meteo's anonymous tier is generous but not unlimited; two
            # requests per site means a modest sustained rate is plenty.
            self._client = LiveHttpClient(
                SOURCE_ID, rate_per_second=3.0, timeout=20.0, require_live_mode=self._live is None
            )
        return self._client

    def metadata(self) -> ConnectorMetadata:
        """Return Open-Meteo connector metadata."""
        return _METADATA

    def is_live(self) -> bool:
        """Return True when the platform is configured for live HTTP."""
        if self._live is not None:
            return self._live
        return get_settings().connector_mode == "live"

    def discover(self) -> list[SourceAsset]:
        """Return the corridor sites this connector covers."""
        return [
            SourceAsset(
                asset_id=str(site["site_id"]),
                name=str(site["name"]),
                extra={"lat": site["lat"], "lon": site["lon"]},
            )
            for site in self.sites
        ]

    def fetch(self, request: FetchRequest) -> Iterator[RawRecord]:
        """Yield one raw record per site, live or from the replay fixture.

        Args:
            request: Fetch window. ``start_time``/``end_time`` select an
                explicit archive range; otherwise a trailing window is used.

        Yields:
            ``RawRecord`` holding the verbatim upstream payloads.
        """
        if not self.is_live():
            yield from self._fetch_fixture()
            return
        yield from self._fetch_live(request)

    def _fetch_fixture(self) -> Iterator[RawRecord]:
        if not self.fixture_path:
            return
        payload = load_fixture(self.fixture_path)
        fetched_at = datetime.now(UTC)
        for record in payload.get("records", []):
            yield RawRecord(
                source_id=SOURCE_ID,
                source_record_id=str(record["site"]["site_id"]),
                payload=record,
                fetched_at=fetched_at,
            )

    def _fetch_live(self, request: FetchRequest) -> Iterator[RawRecord]:
        for site in self.sites:
            params: dict[str, Any] = {
                "latitude": site["lat"],
                "longitude": site["lon"],
                "timezone": "UTC",
            }
            if request.start_time and request.end_time:
                params["start_date"] = request.start_time.date().isoformat()
                params["end_date"] = request.end_time.date().isoformat()
            else:
                params["past_days"] = self.past_days
                params["forecast_days"] = max(1, -(-self.keep_forecast_hours // 24))

            aq_params = dict(params)
            aq_params["hourly"] = ",".join([*AQ_VARIABLES, AOD_VARIABLE])
            wx_params = dict(params)
            wx_vars = (
                (*WEATHER_VARIABLES, *FORECAST_WEATHER_VARIABLES)
                if self.keep_forecast_hours
                else WEATHER_VARIABLES
            )
            wx_params["hourly"] = ",".join(wx_vars)
            wx_params["wind_speed_unit"] = "ms"

            air_quality = self.client.get_json(AIR_QUALITY_URL, params=aq_params)
            weather = self.client.get_json(WEATHER_URL, params=wx_params)
            yield RawRecord(
                source_id=SOURCE_ID,
                source_record_id=str(site["site_id"]),
                payload={"site": site, "air_quality": air_quality, "weather": weather},
                fetched_at=datetime.now(UTC),
            )

    def _is_future(self, observed_at: datetime, fetched_at: datetime) -> bool:
        """True when an hour lies beyond the fetch time, i.e. is a forecast."""
        reference = self.reference_time or fetched_at
        return self.drop_future_hours and observed_at > reference

    def normalize(
        self, record: RawRecord
    ) -> Sequence[Observation | MeteorologicalObservation | RasterObservation | MeteoForecast]:
        """Map one site's hourly payloads to canonical observations.

        Hours whose value is null upstream are skipped rather than imputed, so
        that missingness stays visible to the quality engine.

        Args:
            record: Raw record produced by :meth:`fetch`.

        Returns:
            One ``Observation`` per pollutant-hour, one
            ``MeteorologicalObservation`` per hour, and one
            ``RasterObservation`` per hour carrying AOD.
        """
        site = record.payload["site"]
        location = Location(lat=float(site["lat"]), lon=float(site["lon"]))
        site_id = str(site["site_id"])
        provenance = Provenance(
            provider=PROVIDER,
            connector_version=_METADATA.version,
            raw_object_uri=record.raw_uri,
        )
        results: list[
            Observation | MeteorologicalObservation | RasterObservation | MeteoForecast
        ] = []
        results.extend(
            self._normalize_air_quality(record, site_id, location, provenance),
        )
        results.extend(
            self._normalize_weather(record, site_id, location, provenance),
        )
        results.extend(
            self._normalize_aod(record, site_id, location, provenance),
        )
        if self.keep_forecast_hours:
            results.extend(self._normalize_forecast(record, site_id, location, provenance))
        return results

    def _issued_at(self, record: RawRecord) -> datetime | None:
        """When the forecast in ``record`` was issued, or None if unknowable.

        Open-Meteo returns the latest model run without naming it, so live
        uses the fetch time: the run certainly existed by then, which keeps
        ``issued_at <= t`` safe. A replay fixture must state ``issued_at``;
        without it the tail is not a forecast anyone could have seen, and no
        forecast is emitted.
        """
        declared = record.payload.get("issued_at")
        if declared:
            return _parse_hour(str(declared))
        if self.is_live():
            return record.fetched_at
        return None

    def _normalize_forecast(
        self,
        record: RawRecord,
        site_id: str,
        location: Location,
        provenance: Provenance,
    ) -> list[MeteoForecast]:
        issued_at = self._issued_at(record)
        if issued_at is None:
            return []
        horizon = issued_at + timedelta(hours=self.keep_forecast_hours)
        if self.reference_time is not None and issued_at > self.reference_time:
            return []
        weather = (record.payload.get("weather") or {}).get("hourly") or {}
        air = (record.payload.get("air_quality") or {}).get("hourly") or {}
        air_index = {str(t): i for i, t in enumerate(air.get("time") or [])}
        forecasts: list[MeteoForecast] = []
        for index, raw_time in enumerate(weather.get("time") or []):
            valid_at = _parse_hour(str(raw_time))
            if valid_at <= issued_at or valid_at > horizon:
                continue
            u10, v10 = _wind(weather, "wind_speed_10m", "wind_direction_10m", index)
            u100, v100 = _wind(weather, "wind_speed_100m", "wind_direction_100m", index)
            aq_i = air_index.get(str(raw_time))
            cams = _at(air, "pm2_5", aq_i) if aq_i is not None else None
            forecasts.append(
                MeteoForecast(
                    forecast_id=new_ulid("fc"),
                    source_id=SOURCE_ID,
                    site_id=site_id,
                    issued_at=issued_at,
                    valid_at=valid_at,
                    location=location,
                    wind_u_10m=u10,
                    wind_v_10m=v10,
                    wind_u_100m=u100,
                    wind_v_100m=v100,
                    temperature=_at(weather, "temperature_2m", index),
                    humidity=_at(weather, "relative_humidity_2m", index),
                    precipitation=_at(weather, "precipitation", index),
                    boundary_layer_height=_at(weather, "boundary_layer_height", index),
                    cloud_cover=_at(weather, "cloud_cover", index),
                    cams_pm25=cams,
                    quality=Quality(quality_flag="valid", quality_score=1.0),
                    provenance=provenance,
                )
            )
        return forecasts

    def _normalize_aod(
        self,
        record: RawRecord,
        site_id: str,
        location: Location,
        provenance: Provenance,
    ) -> list[RasterObservation]:
        """Emit AOD as raster metadata rather than a surface measurement.

        ``RasterObservation.sample_aod`` is the contract's designated home for
        a point sample of a satellite-derived product. Routing AOD here rather
        than into ``Measurement`` is what keeps LLD caveat §65.5 enforceable by
        construction: no consumer can mistake it for surface PM2.5.
        """
        hourly = (record.payload.get("air_quality") or {}).get("hourly") or {}
        times = hourly.get("time") or []
        series = hourly.get(AOD_VARIABLE) or []
        observations: list[RasterObservation] = []
        for index, raw_time in enumerate(times):
            if index >= len(series) or series[index] is None:
                continue
            acquired = _parse_hour(str(raw_time))
            if self._is_future(acquired, record.fetched_at):
                continue
            observations.append(
                RasterObservation(
                    observation_id=new_ulid("ras"),
                    source_id=SOURCE_ID,
                    source_record_id=f"{site_id}_{raw_time}_aod",
                    product_id="openmeteo_aerosol_optical_depth",
                    acquisition_time=acquired,
                    processing_time=record.fetched_at,
                    # A point product is represented as a degenerate bbox at the
                    # sample location; the feature builder matches on proximity.
                    bbox=(location.lon, location.lat, location.lon, location.lat),
                    resolution="point",
                    object_uri="",
                    checksum="",
                    quality=Quality(quality_flag="valid", quality_score=1.0),
                    provenance=provenance,
                    sample_aod=float(series[index]),
                )
            )
        return observations

    def _normalize_air_quality(
        self,
        record: RawRecord,
        site_id: str,
        location: Location,
        provenance: Provenance,
    ) -> list[Observation]:
        hourly = (record.payload.get("air_quality") or {}).get("hourly") or {}
        times = hourly.get("time") or []
        observations: list[Observation] = []
        for variable, (parameter, unit, scale) in AQ_VARIABLES.items():
            series = hourly.get(variable)
            if not series:
                continue
            for index, raw_time in enumerate(times):
                if index >= len(series):
                    break
                value = series[index]
                if value is None:
                    continue
                observed_at = _parse_hour(str(raw_time))
                if self._is_future(observed_at, record.fetched_at):
                    continue
                observations.append(
                    Observation(
                        observation_id=new_ulid("obs"),
                        source_id=SOURCE_ID,
                        source_record_id=f"{site_id}_{raw_time}_{parameter}",
                        observed_at=observed_at,
                        received_at=record.fetched_at,
                        location=location,
                        measurement=Measurement(
                            parameter=parameter,
                            value=round(float(value) * scale, 6),
                            unit=unit,
                        ),
                        quality=Quality(quality_flag="valid", quality_score=1.0),
                        provenance=provenance,
                    )
                )
        return observations

    def _normalize_weather(
        self,
        record: RawRecord,
        site_id: str,
        location: Location,
        provenance: Provenance,
    ) -> list[MeteorologicalObservation]:
        weather = (record.payload.get("weather") or {}).get("hourly") or {}
        times = weather.get("time") or []
        observations: list[MeteorologicalObservation] = []
        for index, raw_time in enumerate(times):
            observed_at = _parse_hour(str(raw_time))
            if self._is_future(observed_at, record.fetched_at):
                continue
            speed = _at(weather, "wind_speed_10m", index)
            direction = _at(weather, "wind_direction_10m", index)
            wind_u: float | None = None
            wind_v: float | None = None
            if speed is not None and direction is not None:
                wind_u, wind_v = wind_components(float(speed), float(direction))
            observations.append(
                MeteorologicalObservation(
                    observation_id=new_ulid("met"),
                    source_id=SOURCE_ID,
                    source_record_id=f"{site_id}_{raw_time}_weather",
                    observed_at=observed_at,
                    received_at=record.fetched_at,
                    location=location,
                    parameter="weather",
                    wind_u=None if wind_u is None else round(wind_u, 4),
                    wind_v=None if wind_v is None else round(wind_v, 4),
                    temperature=_at(weather, "temperature_2m", index),
                    humidity=_at(weather, "relative_humidity_2m", index),
                    pressure=_at(weather, "surface_pressure", index),
                    rainfall=_at(weather, "precipitation", index),
                    boundary_layer_height=_at(weather, "boundary_layer_height", index),
                    quality=Quality(quality_flag="valid", quality_score=1.0),
                    provenance=provenance,
                )
            )
        return observations

    def health_check(self) -> HealthStatus:
        """Report readiness for the currently configured mode.

        Live health is a real one-site probe; replay health is fixture presence.
        """
        checked_at = datetime.now(UTC)
        if not self.is_live():
            available = self.fixture_path is not None and self.fixture_path.exists()
            return HealthStatus(
                connector_id=_METADATA.connector_id,
                healthy=available,
                message="replay" if available else "no fixture",
                checked_at=checked_at,
            )
        site = self.sites[0]
        try:
            self.client.get_json(
                WEATHER_URL,
                params={
                    "latitude": site["lat"],
                    "longitude": site["lon"],
                    "hourly": "temperature_2m",
                    "forecast_days": 1,
                    "timezone": "UTC",
                },
            )
        except Exception as exc:
            return HealthStatus(
                connector_id=_METADATA.connector_id,
                healthy=False,
                message=f"live probe failed: {type(exc).__name__}",
                checked_at=checked_at,
            )
        return HealthStatus(
            connector_id=_METADATA.connector_id,
            healthy=True,
            message="live",
            checked_at=checked_at,
        )


def _wind(
    hourly: dict[str, Any], speed_key: str, direction_key: str, index: int
) -> tuple[float | None, float | None]:
    speed = _at(hourly, speed_key, index)
    direction = _at(hourly, direction_key, index)
    if speed is None or direction is None:
        return None, None
    u, v = wind_components(speed, direction)
    return round(u, 4), round(v, 4)


def _at(hourly: dict[str, Any], key: str, index: int) -> float | None:
    """Return ``hourly[key][index]`` as a float, or None when absent/null."""
    series = hourly.get(key)
    if not series or index >= len(series):
        return None
    value = series[index]
    return None if value is None else float(value)


def default_window(hours: int = 48) -> FetchRequest:
    """Build a trailing fetch window ending now.

    Args:
        hours: Window length in hours.

    Returns:
        A ``FetchRequest`` covering the trailing window.
    """
    end = datetime.now(UTC)
    return FetchRequest(start_time=end - timedelta(hours=hours), end_time=end)
