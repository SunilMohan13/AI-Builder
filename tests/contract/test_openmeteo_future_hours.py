"""Open-Meteo returns the whole of today, so a live response ends in forecast.

Those hours score ``temporal_q = 0`` in the quality engine and land in
connector_dead_letter as ``future_timestamp`` — roughly a day of noise per
site per cycle once the scheduler is running. The connector drops them at
normalize time instead.
"""

from datetime import UTC, datetime
from pathlib import Path

from aeropulse_connector_openmeteo import OpenMeteoConnector
from aeropulse_connector_sdk.contracts import FetchRequest, RawRecord
from aeropulse_connector_sdk.testing import load_fixture

FIXTURE = Path("fixtures/openmeteo/observations.json")


def _record_with_fetched_at(fetched_at: datetime) -> RawRecord:
    """Rebuild one fixture record with a caller-chosen fetch time."""
    payload = load_fixture(FIXTURE)
    record = payload["records"][0]
    return RawRecord(
        source_id="openmeteo",
        source_record_id=str(record["site"]["site_id"]),
        payload=record,
        fetched_at=fetched_at,
    )


def _series_hours() -> list[str]:
    payload = load_fixture(FIXTURE)
    return payload["records"][0]["air_quality"]["hourly"]["time"]


def _observed(obs: object) -> datetime:
    return getattr(obs, "observed_at", None) or obs.acquisition_time  # type: ignore[attr-defined]


def test_hours_after_the_fetch_time_are_dropped() -> None:
    hours = _series_hours()
    midpoint = datetime.fromisoformat(hours[len(hours) // 2]).replace(tzinfo=UTC)
    record = _record_with_fetched_at(midpoint)

    connector = OpenMeteoConnector(FIXTURE, drop_future_hours=True)
    results = connector.normalize(record)

    assert results, "the past half of the series must still be emitted"
    assert all(_observed(o) <= midpoint for o in results)


def test_disabling_the_filter_keeps_the_forecast_tail() -> None:
    """A training fetch may legitimately want the forecast window."""
    hours = _series_hours()
    midpoint = datetime.fromisoformat(hours[len(hours) // 2]).replace(tzinfo=UTC)
    record = _record_with_fetched_at(midpoint)

    kept = OpenMeteoConnector(FIXTURE, drop_future_hours=False).normalize(record)
    dropped = OpenMeteoConnector(FIXTURE, drop_future_hours=True).normalize(record)

    assert len(kept) > len(dropped)
    assert any(_observed(o) > midpoint for o in kept)


def test_filtering_is_on_by_default() -> None:
    hours = _series_hours()
    midpoint = datetime.fromisoformat(hours[len(hours) // 2]).replace(tzinfo=UTC)
    record = _record_with_fetched_at(midpoint)

    results = OpenMeteoConnector(FIXTURE).normalize(record)

    assert all(_observed(o) <= midpoint for o in results)


def test_replay_of_a_wholly_historical_fixture_is_unaffected() -> None:
    """Replay stamps fetched_at=now, so nothing in a past fixture is future."""
    connector = OpenMeteoConnector(FIXTURE, drop_future_hours=True)
    emitted = sum(len(connector.normalize(raw)) for raw in connector.fetch(FetchRequest()))

    unfiltered = OpenMeteoConnector(FIXTURE, drop_future_hours=False)
    baseline = sum(len(unfiltered.normalize(raw)) for raw in unfiltered.fetch(FetchRequest()))

    assert emitted == baseline
