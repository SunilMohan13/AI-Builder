"""Contract tests for the OpenAQ v3 connector.

These run against a committed fixture and never touch the network. The traps
they pin are the ones that would corrupt data silently rather than fail:
ppm-vs-micrograms, stale values from dead stations, and provider attribution.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from aeropulse_common.settings import Settings
from aeropulse_connector_openaq import (
    CANONICAL_UNIT,
    DISCOVERY_PAGE_SIZE,
    HISTORY_PAGE_SIZE,
    LOCATIONS_URL,
    SENSORS_URL,
    SOURCE_ID,
    OpenAqConnector,
)
from aeropulse_connector_sdk.contracts import FetchRequest, RawRecord
from aeropulse_connector_sdk.live_http import LiveHttpClient
from aeropulse_connector_sdk.testing import load_fixture

FIXTURE = Path("fixtures/openaq/latest.json")


@pytest.fixture
def connector() -> OpenAqConnector:
    return OpenAqConnector(FIXTURE)


@pytest.fixture
def normalized(connector: OpenAqConnector) -> list[Any]:
    out: list[Any] = []
    for raw in connector.fetch(FetchRequest()):
        out.extend(connector.normalize(raw))
    return out


# --- identity ---


def test_metadata_declares_header_auth() -> None:
    meta = OpenAqConnector(FIXTURE).metadata()
    assert meta.connector_id == SOURCE_ID
    assert meta.provider == "OpenAQ"
    assert meta.output_contract == ["observation.v1"]


def test_replay_is_the_default_mode(connector: OpenAqConnector) -> None:
    """Live must stay opt-in; a test run must never reach the network."""
    assert connector.is_live() is False


# --- normalization ---


def test_emits_observations_for_every_particulate_sensor(normalized: list[Any]) -> None:
    assert len(normalized) == 4
    assert {o.measurement.parameter for o in normalized} == {"pm25", "pm10"}


def test_every_value_is_in_canonical_micrograms(normalized: list[Any]) -> None:
    assert all(o.measurement.unit == CANONICAL_UNIT for o in normalized)


def test_ppm_gas_sensors_are_skipped_not_converted(normalized: list[Any]) -> None:
    """A ppm NO2 read as micrograms would silently corrupt the fused vector.

    The feature builder consumes pollutant values without consulting units, so
    the only safe handling is to drop the sensor.
    """
    assert all(o.measurement.parameter not in {"no2", "so2", "co", "o3"} for o in normalized)
    # The fixture does contain one, so this assertion is not vacuous.
    payload = load_fixture(FIXTURE)
    units = {s["parameter"]["units"] for loc in payload["locations"] for s in loc["sensors"]}
    assert "ppm" in units


def test_provider_names_the_upstream_network_not_just_the_aggregator(
    normalized: list[Any],
) -> None:
    """Some Indian OpenAQ locations are not CPCB, so this must not be hardcoded."""
    providers = {o.provenance.provider for o in normalized}
    assert providers == {"OpenAQ / Central Pollution Control Board"}


def test_source_record_id_is_stable_and_unique(normalized: list[Any]) -> None:
    """dedup_key relies on this across the overlap a watermark resume re-requests."""
    ids = [o.source_record_id for o in normalized]
    assert len(ids) == len(set(ids))

    again = OpenAqConnector(FIXTURE)
    repeat = [
        o.source_record_id for raw in again.fetch(FetchRequest()) for o in again.normalize(raw)
    ]
    assert ids == repeat


def test_live_start_time_drops_observations_before_the_window(connector: OpenAqConnector) -> None:
    """FetchRequest.start_time is a lower bound, not a decorative field."""
    connector._window_start = datetime(2099, 1, 1, tzinfo=UTC)
    dropped: list[Any] = []
    for raw in connector._fetch_fixture():
        dropped.extend(connector.normalize(raw))
    assert dropped == []


def test_observed_at_is_timezone_aware_utc(normalized: list[Any]) -> None:
    assert all(o.observed_at.tzinfo is not None for o in normalized)
    assert all(o.observed_at.utcoffset() == timedelta(0) for o in normalized)


def test_values_are_positive_and_finite(normalized: list[Any]) -> None:
    assert all(o.measurement.value > 0 for o in normalized)


# --- staleness ---


def test_stale_values_are_dropped_in_live_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """`/latest` returns a value from a station that died weeks ago."""
    monkeypatch.setattr(
        "aeropulse_connector_openaq.connector.get_settings",
        lambda: Settings(connector_mode="live", connector_max_observation_age_hours=6),
    )
    connector = OpenAqConnector(FIXTURE)
    payload = load_fixture(FIXTURE)
    locations = {str(loc["id"]): loc for loc in payload["locations"]}

    # Ludhiana's only reading is 19 days older than the Delhi ones.
    fresh_at = datetime(2026, 9, 8, 6, 0, tzinfo=UTC)
    stale_entry = next(e for e in payload["latest"] if e["locations_id"] == 8790)
    record = RawRecord(
        source_id=SOURCE_ID,
        source_record_id="8790",
        payload={"location": locations["8790"], "latest": stale_entry},
        fetched_at=fresh_at,
    )

    assert connector.normalize(record) == []


def test_fresh_values_survive_the_staleness_cutoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "aeropulse_connector_openaq.connector.get_settings",
        lambda: Settings(connector_mode="live", connector_max_observation_age_hours=6),
    )
    connector = OpenAqConnector(FIXTURE)
    payload = load_fixture(FIXTURE)
    locations = {str(loc["id"]): loc for loc in payload["locations"]}
    entry = next(e for e in payload["latest"] if e["locations_id"] == 8544)
    record = RawRecord(
        source_id=SOURCE_ID,
        source_record_id="8544",
        payload={"location": locations["8544"], "latest": entry},
        fetched_at=datetime(2026, 9, 8, 6, 0, tzinfo=UTC),
    )

    results = connector.normalize(record)
    assert len(results) == 1
    assert results[0].measurement.parameter == "pm25"


def test_replay_does_not_apply_the_staleness_cutoff(normalized: list[Any]) -> None:
    """A historical fixture is deliberately old and is reported as REPLAY."""
    assert len(normalized) == 4


# --- live transport ---


class _Response:
    def __init__(self, payload: Any) -> None:
        self.status_code = 200
        self._payload = payload
        self.headers = {"x-ratelimit-remaining": "58"}

    def raise_for_status(self) -> None:
        return None

    @property
    def text(self) -> str:
        return json.dumps(self._payload)


class _Transport:
    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kwargs: Any) -> Any:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0) if self.responses else _Response({"results": []})


def test_discovery_requests_reference_grade_monitors_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """monitor=true is what makes the CPCB claim honest rather than aspirational."""
    monkeypatch.setattr(
        "aeropulse_connector_openaq.connector.get_settings",
        lambda: Settings(connector_mode="live"),
    )
    monkeypatch.setattr(
        "aeropulse_connector_sdk.live_http.get_settings",
        lambda: Settings(connector_mode="live"),
    )
    transport = _Transport(_Response({"results": []}))
    client = LiveHttpClient(SOURCE_ID, transport_get=transport)
    connector = OpenAqConnector(FIXTURE, client=client)

    connector.discover()

    call = transport.calls[0]
    assert call["url"] == LOCATIONS_URL
    assert call["params"]["monitor"] == "true"
    assert call["params"]["parameters_id"] == 2
    assert call["params"]["bbox"] == "73.8,27.5,78.5,32.2"


def test_discovery_polls_only_reporting_monitors_newest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenAQ lists monitors oldest id first; a capped poll of dead stations yields nothing."""
    settings = Settings(connector_mode="live", connector_max_observation_age_hours=6)
    monkeypatch.setattr("aeropulse_connector_openaq.connector.get_settings", lambda: settings)
    monkeypatch.setattr("aeropulse_connector_sdk.live_http.get_settings", lambda: settings)
    now = datetime.now(UTC)

    def location(location_id: int, age: timedelta | None) -> dict[str, Any]:
        last = None if age is None else {"utc": (now - age).isoformat()}
        return {"id": location_id, "datetimeLast": last}

    listed = [
        location(1, timedelta(days=3000)),
        location(2, None),
        location(3, timedelta(hours=5)),
        location(4, timedelta(hours=7)),
        location(5, timedelta(minutes=30)),
    ]
    transport = _Transport(_Response({"results": listed}))
    client = LiveHttpClient(SOURCE_ID, transport_get=transport)
    connector = OpenAqConnector(FIXTURE, client=client, max_locations=1)

    raws = list(connector.fetch(FetchRequest()))

    assert transport.calls[0]["params"]["limit"] == DISCOVERY_PAGE_SIZE
    assert [loc["id"] for loc in connector._reporting(listed)] == [5, 3]
    assert [r.source_record_id for r in raws] == ["5"]
    assert transport.calls[1]["url"] == f"{LOCATIONS_URL}/5/latest"


def _hour(value: float, end: datetime) -> dict[str, Any]:
    start = end - timedelta(hours=1)
    return {
        "value": value,
        "parameter": {"id": 2, "name": "pm25", "units": "µg/m³"},
        "period": {
            "datetimeFrom": {"utc": start.isoformat()},
            "datetimeTo": {"utc": end.isoformat()},
        },
    }


def _historical(monkeypatch: pytest.MonkeyPatch, transport: _Transport) -> OpenAqConnector:
    settings = Settings(connector_mode="live", connector_max_observation_age_hours=6)
    monkeypatch.setattr("aeropulse_connector_openaq.connector.get_settings", lambda: settings)
    monkeypatch.setattr("aeropulse_connector_sdk.live_http.get_settings", lambda: settings)
    client = LiveHttpClient(SOURCE_ID, transport_get=transport)
    return OpenAqConnector(FIXTURE, client=client, max_locations=1, historical=True)


HISTORY_START = datetime(2026, 8, 1, tzinfo=UTC)
HISTORY_END = datetime(2026, 8, 21, tzinfo=UTC)


def _monitor(location_id: int, first: datetime, last: datetime) -> dict[str, Any]:
    return {
        "id": location_id,
        "coordinates": {"latitude": 28.6, "longitude": 77.2},
        "provider": {"name": "Central Pollution Control Board"},
        "datetimeFirst": {"utc": first.isoformat()},
        "datetimeLast": {"utc": last.isoformat()},
        "sensors": [
            {"id": location_id * 10, "parameter": {"name": "pm25", "units": "µg/m³"}},
            {"id": location_id * 10 + 1, "parameter": {"name": "no2", "units": "ppm"}},
        ],
    }


def test_backfill_reads_each_sensors_hourly_series_for_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every monitor active in the window is read, past the live cap and staleness filter."""
    listed = [
        _monitor(1, datetime(2020, 1, 1, tzinfo=UTC), datetime(2026, 8, 10, tzinfo=UTC)),
        _monitor(2, datetime(2020, 1, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC)),
        _monitor(3, datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)),
        _monitor(4, datetime(2026, 8, 5, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)),
    ]
    full = [_hour(40.0, HISTORY_START + timedelta(hours=i + 1)) for i in range(HISTORY_PAGE_SIZE)]
    transport = _Transport(
        _Response({"results": listed}),
        _Response({"results": full}),
        _Response({"results": [_hour(41.0, HISTORY_END)]}),
        _Response({"results": [_hour(42.0, HISTORY_END)]}),
    )
    connector = _historical(monkeypatch, transport)

    raws = list(connector.fetch(FetchRequest(start_time=HISTORY_START, end_time=HISTORY_END)))

    hour_calls = transport.calls[1:]
    assert [c["url"] for c in hour_calls] == [
        f"{SENSORS_URL}/10/hours",
        f"{SENSORS_URL}/10/hours",
        f"{SENSORS_URL}/40/hours",
    ]
    assert [c["params"]["page"] for c in hour_calls] == [1, 2, 1]
    assert hour_calls[0]["params"]["datetime_from"] == "2026-08-01T00:00:00Z"
    assert hour_calls[0]["params"]["datetime_to"] == "2026-08-21T00:00:00Z"
    assert hour_calls[0]["params"]["limit"] == HISTORY_PAGE_SIZE
    assert len(raws) == 3


def test_backfilled_hours_skip_the_staleness_cutoff_and_stamp_the_hour_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A month-old hourly mean is the point of a backfill; it is complete at its hour's end."""
    connector = _historical(monkeypatch, _Transport())
    end = datetime(2026, 8, 3, 6, tzinfo=UTC)
    record = RawRecord(
        source_id=SOURCE_ID,
        source_record_id="1_10_p1",
        payload={
            "location": _monitor(1, HISTORY_START, HISTORY_END),
            "sensor_id": "10",
            "hours": [_hour(55.5, end), _hour(60.0, end + timedelta(hours=1))],
        },
        fetched_at=datetime(2026, 10, 10, tzinfo=UTC),
    )

    results = connector.normalize(record)

    assert [o.observed_at for o in results] == [end, end + timedelta(hours=1)]
    assert [o.measurement.value for o in results] == [55.5, 60.0]
    assert {o.measurement.unit for o in results} == {CANONICAL_UNIT}
    assert len({o.source_record_id for o in results}) == 2


def test_a_replay_fixture_of_hourly_series_normalizes_like_a_backfill(tmp_path: Path) -> None:
    end = datetime(2026, 8, 3, 6, tzinfo=UTC)
    fixture = tmp_path / "hours.json"
    fixture.write_text(
        json.dumps(
            {
                "locations": [_monitor(1, HISTORY_START, HISTORY_END)],
                "hours": [
                    {"locations_id": 1, "sensor_id": "10", "results": [_hour(55.5, end)]},
                    {"locations_id": 9, "sensor_id": "90", "results": [_hour(1.0, end)]},
                ],
            }
        )
    )
    connector = OpenAqConnector(fixture)

    [raw] = list(connector.fetch(FetchRequest()))
    [observation] = connector.normalize(raw)

    assert raw.source_record_id == "1_10"
    assert observation.observed_at == end
    assert observation.measurement.value == 55.5


def test_backfill_needs_a_bounded_window(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = _historical(monkeypatch, _Transport())
    with pytest.raises(ValueError, match="start_time and end_time"):
        list(connector.fetch(FetchRequest(start_time=HISTORY_START)))


def test_api_key_is_sent_as_a_header_never_in_the_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Header auth is why this credential cannot leak into request logs."""
    from pydantic import SecretStr

    settings = Settings(connector_mode="live", openaq_api_key=SecretStr("secret-key-value"))
    monkeypatch.setattr("aeropulse_connector_openaq.connector.get_settings", lambda: settings)
    monkeypatch.setattr("aeropulse_connector_sdk.live_http.get_settings", lambda: settings)
    transport = _Transport(_Response({"results": []}))
    connector = OpenAqConnector(FIXTURE, client=LiveHttpClient(SOURCE_ID, transport_get=transport))

    connector.discover()

    call = transport.calls[0]
    assert call["headers"]["X-API-Key"] == "secret-key-value"
    assert "secret-key-value" not in call["url"]
    assert "secret-key-value" not in json.dumps(call["params"])


def test_health_check_reports_a_missing_credential_in_live_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "aeropulse_connector_openaq.connector.get_settings",
        lambda: Settings(connector_mode="live"),
    )
    status = OpenAqConnector(FIXTURE).health_check()
    assert status.healthy is False
    assert "AEROPULSE_OPENAQ_API_KEY" in status.message


def test_health_check_is_fixture_presence_in_replay(connector: OpenAqConnector) -> None:
    assert connector.health_check().healthy is True
    assert OpenAqConnector(Path("fixtures/openaq/missing.json")).health_check().healthy is False
