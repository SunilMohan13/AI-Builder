"""NEA one-hour PM2.5 from data.gov.sg.

data.gov.sg publishes one reading per NEA reporting region each hour, with a
label point per region. A network run asks for every local date the window
touches (``?date=``) and keeps the hours inside the window, so the first live
cycle already has the hours the forecast lags need. Replay reads captured
response bodies from a fixture.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from aeropulse_common.ids import new_ulid
from aeropulse_connector_sdk.contracts import RawRecord
from aeropulse_connector_sdk.testing import load_fixture, load_yaml_metadata
from aeropulse_contracts.observation import (
    Location,
    Measurement,
    Observation,
    Provenance,
    Quality,
)

SOURCE_ID = "nea"
PM25_URL = "https://api-open.data.gov.sg/v2/real-time/api/pm25"
READING = "pm25_one_hourly"
CANONICAL_UNIT = "ug/m3"
PROVIDER = "NEA via data.gov.sg"
#: The API's ``date`` parameter is a Singapore calendar date (UTC+8, no DST).
API_DATE_TZ = timezone(timedelta(hours=8))
#: From a reading's API timestamp to the hour boundary at which it is known.
KNOWN_AFTER = timedelta(hours=1)

_METADATA = load_yaml_metadata(Path(__file__).resolve().parent / "metadata.yaml")
BBox = tuple[float, float, float, float]


class NeaApiError(RuntimeError):
    """data.gov.sg answered with a non-zero ``code``."""


class JsonGetter(Protocol):
    def get_json(self, url: str, *, params: dict[str, Any] | None = None) -> Any: ...


def api_dates(start: datetime, end: datetime) -> list[date]:
    """Every API date that ``[start, end]`` touches, oldest first."""
    first = start.astimezone(API_DATE_TZ).date()
    last = end.astimezone(API_DATE_TZ).date()
    return [first + timedelta(days=n) for n in range((last - first).days + 1)]


def fetch_live(
    client: JsonGetter, start: datetime, end: datetime, *, fetched_at: datetime
) -> Iterator[RawRecord]:
    """One raw record per response page for each date in the window."""
    for day in api_dates(start, end):
        params: dict[str, Any] = {"date": day.isoformat()}
        page = 1
        while True:
            body = client.get_json(PM25_URL, params=params)
            if body.get("code") != 0:
                raise NeaApiError(str(body.get("errorMsg") or f"code {body.get('code')}"))
            data = body.get("data") or {}
            yield RawRecord(
                source_id=SOURCE_ID,
                source_record_id=f"pm25_{day.isoformat()}_p{page}",
                payload=data,
                fetched_at=fetched_at,
            )
            token = data.get("paginationToken")
            if not token:
                break
            params = {"date": day.isoformat(), "paginationToken": token}
            page += 1


def fetch_fixture(path: Path, *, fetched_at: datetime) -> Iterator[RawRecord]:
    """Captured response bodies: ``{"responses": [<body>, ...]}``."""
    for n, body in enumerate(load_fixture(path).get("responses", []), start=1):
        yield RawRecord(
            source_id=SOURCE_ID,
            source_record_id=f"pm25_fixture_{n}",
            payload=body.get("data") or {},
            fetched_at=fetched_at,
        )


def _points(data: dict[str, Any], bbox: BBox) -> dict[str, tuple[float, float]]:
    """Label point per reporting region, kept only inside ``bbox``."""
    min_lon, min_lat, max_lon, max_lat = bbox
    points: dict[str, tuple[float, float]] = {}
    for meta in data.get("regionMetadata") or []:
        where = meta.get("labelLocation") or {}
        lat, lon = where.get("latitude"), where.get("longitude")
        if meta.get("name") is None or lat is None or lon is None:
            continue
        if min_lon <= float(lon) <= max_lon and min_lat <= float(lat) <= max_lat:
            points[str(meta["name"])] = (float(lat), float(lon))
    return points


def normalize(
    record: RawRecord,
    *,
    bbox: BBox,
    start: datetime | None,
    end: datetime | None,
) -> Sequence[Observation]:
    """One observation per region-hour inside the window.

    A reading is the one-hour mean ending at its API timestamp and is
    published about a quarter hour later, so it is stamped one hour after
    the API timestamp: the first hour boundary at which it is known. OpenAQ's
    copy of this series, which the Singapore models were trained on, carries
    the same stamps. A reading whose stamp is still ahead of the fetch waits
    for the next run.
    """
    data = record.payload
    points = _points(data, bbox)
    provenance = Provenance(
        provider=PROVIDER, connector_version=_METADATA.version, raw_object_uri=record.raw_uri
    )
    out: list[Observation] = []
    for item in data.get("items") or []:
        stamp = item.get("timestamp")
        if not stamp:
            continue
        observed_at = datetime.fromisoformat(stamp).astimezone(UTC) + KNOWN_AFTER
        if observed_at > record.fetched_at:
            continue
        if (start is not None and observed_at < start) or (end is not None and observed_at > end):
            continue
        readings = (item.get("readings") or {}).get(READING) or {}
        for region, value in sorted(readings.items()):
            if value is None or region not in points:
                continue
            lat, lon = points[region]
            out.append(
                Observation(
                    observation_id=new_ulid("obs"),
                    source_id=SOURCE_ID,
                    source_record_id=f"{region}_{observed_at.isoformat()}",
                    observed_at=observed_at,
                    received_at=record.fetched_at,
                    location=Location(lat=lat, lon=lon),
                    measurement=Measurement(
                        parameter="pm25", value=float(value), unit=CANONICAL_UNIT
                    ),
                    quality=Quality(quality_flag="valid", quality_score=1.0),
                    provenance=provenance,
                )
            )
    return out
