"""FIRMS live CSV path: time parsing, deterministic ids, credential safety.

The two defects these guard against are silent ones. A mis-parsed ``acq_time``
produces fires at plausible but wrong times, and a MAP_KEY in the URL reaches
logs the moment anything echoes a request.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from aeropulse_common.settings import Settings
from aeropulse_connector_firms import FirmsConnector
from aeropulse_connector_firms.connector import (
    AREA_CSV_URL,
    _parse_acq_datetime,
    redact_map_key,
)
from aeropulse_connector_sdk.contracts import FetchRequest
from aeropulse_connector_sdk.live_http import LiveHttpClient
from pydantic import SecretStr

FIXTURE = Path("fixtures/firms/fires.json")
MAP_KEY = "abcdef0123456789abcdef0123456789"

CSV_BODY = (
    "country_id,latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,"
    "satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
    "IND,30.4521,75.2103,334.2,0.42,0.38,2026-09-08,412,N,VIIRS,n,2.0NRT,289.1,14.7,D\n"
    "IND,30.6712,75.9834,351.8,0.45,0.40,2026-09-08,1130,N,VIIRS,h,2.0NRT,295.3,32.4,D\n"
    "IND,29.9812,76.1204,318.5,0.39,0.36,2026-09-08,0,N,VIIRS,l,2.0NRT,281.7,5.2,N\n"
)


class _Response:
    def __init__(self, text: str) -> None:
        self.status_code = 200
        self.text = text
        self.headers: dict[str, str] = {}

    def raise_for_status(self) -> None:
        return None


class _Transport:
    def __init__(self, body: str) -> None:
        self.body = body
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> Any:
        self.calls.append({"url": url, **kwargs})
        return _Response(self.body)


@pytest.fixture
def live_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = Settings(connector_mode="live", firms_map_key=SecretStr(MAP_KEY))
    monkeypatch.setattr("aeropulse_connector_firms.connector.get_settings", lambda: settings)
    monkeypatch.setattr("aeropulse_connector_sdk.live_http.get_settings", lambda: settings)
    return settings


# --- acq_time parsing ---


@pytest.mark.parametrize(
    ("acq_time", "expected_hour", "expected_minute"),
    [
        ("412", 4, 12),  # leading zero stripped by the API
        ("0", 0, 0),  # midnight collapses to a single character
        ("1130", 11, 30),
        ("0045", 0, 45),
        ("2359", 23, 59),
    ],
)
def test_acq_time_is_zero_padded_before_parsing(
    acq_time: str, expected_hour: int, expected_minute: int
) -> None:
    parsed = _parse_acq_datetime("2026-09-08", acq_time)
    assert (parsed.hour, parsed.minute) == (expected_hour, expected_minute)
    assert parsed.tzinfo is UTC


def test_acq_datetime_is_utc_aware() -> None:
    assert _parse_acq_datetime("2026-09-08", "412").isoformat() == "2026-09-08T04:12:00+00:00"


# --- credential safety ---


def test_redact_map_key_removes_the_credential_segment() -> None:
    url = f"{AREA_CSV_URL}/{MAP_KEY}/VIIRS_NOAA20_NRT/73.8,27.5,78.5,32.2/1"
    redacted = redact_map_key(url)
    assert MAP_KEY not in redacted
    assert "<redacted>" in redacted
    assert "VIIRS_NOAA20_NRT" in redacted, "only the key is removed"


def test_map_key_never_appears_in_logs_or_payloads(
    live_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    transport = _Transport(CSV_BODY)
    connector = FirmsConnector(FIXTURE, client=LiveHttpClient("firms", transport_get=transport))

    with caplog.at_level(logging.DEBUG):
        records = list(connector.fetch(FetchRequest()))

    assert records
    assert all(MAP_KEY not in str(r.payload) for r in records)
    assert MAP_KEY not in caplog.text


def test_a_fetch_failure_reports_a_redacted_url(live_settings: Settings) -> None:
    class _Boom:
        def __call__(self, url: str, **kwargs: Any) -> Any:
            raise ConnectionError("upstream down")

    connector = FirmsConnector(FIXTURE, client=LiveHttpClient("firms", transport_get=_Boom()))

    with pytest.raises(RuntimeError) as excinfo:
        list(connector.fetch(FetchRequest()))

    assert MAP_KEY not in str(excinfo.value)
    assert "<redacted>" in str(excinfo.value)


def test_live_fetch_without_a_key_refuses_to_build_a_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "aeropulse_connector_firms.connector.get_settings",
        lambda: Settings(connector_mode="live"),
    )
    with pytest.raises(ValueError, match="AEROPULSE_FIRMS_MAP_KEY"):
        list(FirmsConnector(FIXTURE).fetch(FetchRequest()))


# --- live CSV normalization ---


def test_csv_rows_become_canonical_fire_observations(live_settings: Settings) -> None:
    transport = _Transport(CSV_BODY)
    connector = FirmsConnector(FIXTURE, client=LiveHttpClient("firms", transport_get=transport))

    observations = [
        obs for raw in connector.fetch(FetchRequest()) for obs in connector.normalize(raw)
    ]

    assert len(observations) == 3
    first = observations[0]
    assert first.observed_at == datetime(2026, 9, 8, 4, 12, tzinfo=UTC)
    assert first.location.lat == pytest.approx(30.4521)
    assert first.fire.frp == pytest.approx(14.7)
    assert first.fire.sensor == "VIIRS"


def test_viirs_letter_confidence_maps_to_a_unit_interval(live_settings: Settings) -> None:
    transport = _Transport(CSV_BODY)
    connector = FirmsConnector(FIXTURE, client=LiveHttpClient("firms", transport_get=transport))

    confidences = [
        obs.fire.confidence
        for raw in connector.fetch(FetchRequest())
        for obs in connector.normalize(raw)
    ]

    assert confidences == [0.6, 0.9, 0.3]  # n, h, l
    assert all(0.0 <= c <= 1.0 for c in confidences)


def test_record_ids_are_deterministic_across_repeated_fetches(
    live_settings: Settings,
) -> None:
    """FIRMS re-returns the whole day every call; dedup depends on this."""

    def ids() -> list[str]:
        connector = FirmsConnector(
            FIXTURE, client=LiveHttpClient("firms", transport_get=_Transport(CSV_BODY))
        )
        return [r.source_record_id for r in connector.fetch(FetchRequest())]

    first, second = ids(), ids()
    assert first == second
    assert len(set(first)) == 3


def test_request_url_carries_bbox_product_and_day_range(live_settings: Settings) -> None:
    transport = _Transport(CSV_BODY)
    connector = FirmsConnector(FIXTURE, client=LiveHttpClient("firms", transport_get=transport))

    list(connector.fetch(FetchRequest()))

    url = transport.calls[0]["url"]
    assert url.startswith(f"{AREA_CSV_URL}/{MAP_KEY}/VIIRS_NOAA20_NRT/")
    assert "73.8,27.5,78.5,32.2" in url
    assert url.endswith("/1")


def test_day_range_widens_after_an_outage_but_is_capped(live_settings: Settings) -> None:
    from datetime import timedelta

    transport = _Transport(CSV_BODY)
    connector = FirmsConnector(FIXTURE, client=LiveHttpClient("firms", transport_get=transport))

    behind = FetchRequest(start_time=datetime.now(UTC) - timedelta(days=30))
    list(connector.fetch(behind))

    assert transport.calls[0]["url"].endswith("/5"), "API caps a request at 5 days"


def test_blank_csv_rows_are_skipped(live_settings: Settings) -> None:
    body = CSV_BODY + ",,,,,,,,,,,,,,\n"
    connector = FirmsConnector(
        FIXTURE, client=LiveHttpClient("firms", transport_get=_Transport(body))
    )
    assert len(list(connector.fetch(FetchRequest()))) == 3


# --- replay path is unchanged ---


def test_fixture_replay_still_works() -> None:
    connector = FirmsConnector(FIXTURE)
    observations = [
        obs for raw in connector.fetch(FetchRequest()) for obs in connector.normalize(raw)
    ]
    assert len(observations) == 2
    assert all(o.source_id == "firms" for o in observations)


def test_health_check_reports_a_missing_key_in_live_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "aeropulse_connector_firms.connector.get_settings",
        lambda: Settings(connector_mode="live"),
    )
    status = FirmsConnector(FIXTURE).health_check()
    assert status.healthy is False
    assert "AEROPULSE_FIRMS_MAP_KEY" in status.message
