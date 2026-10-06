"""Open-Meteo returns the whole of today, so a live response ends in forecast.

Those hours must not become observations. They are meteo_forecast.v1 rows.
"""

from datetime import UTC, datetime
from pathlib import Path

from aeropulse_connector_openmeteo import OpenMeteoConnector
from aeropulse_connector_sdk.contracts import FetchRequest, RawRecord
from aeropulse_connector_sdk.testing import load_fixture
from aeropulse_contracts.meteo_forecast import MeteoForecast
from aeropulse_contracts.observation import Observation, ProvenanceClass

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


def test_future_hours_are_forecasts_not_observations() -> None:
    hours = _series_hours()
    midpoint = datetime.fromisoformat(hours[len(hours) // 2]).replace(tzinfo=UTC)
    record = _record_with_fetched_at(midpoint)

    results = OpenMeteoConnector(FIXTURE).normalize(record)
    observations = [item for item in results if not isinstance(item, MeteoForecast)]
    forecasts = [item for item in results if isinstance(item, MeteoForecast)]

    assert observations, "the past half of the series must still be emitted"
    assert forecasts, "future hours must be kept as forecasts"
    assert all(_observed(item) <= midpoint for item in observations)
    assert all(item.valid_at > midpoint for item in forecasts)
    assert all(item.issued_at <= item.valid_at for item in forecasts)
    assert all(
        item.provenance.provenance_class == ProvenanceClass.MODEL_DERIVED for item in forecasts
    )
    assert not any(
        isinstance(item, Observation) and item.observed_at > midpoint for item in results
    )


def test_disabling_the_old_flag_still_does_not_emit_forecast_observations() -> None:
    hours = _series_hours()
    midpoint = datetime.fromisoformat(hours[len(hours) // 2]).replace(tzinfo=UTC)
    record = _record_with_fetched_at(midpoint)

    results = OpenMeteoConnector(FIXTURE, drop_future_hours=False).normalize(record)

    assert any(isinstance(item, MeteoForecast) and item.valid_at > midpoint for item in results)
    assert not any(
        isinstance(item, Observation) and item.observed_at > midpoint for item in results
    )


def test_replay_of_a_wholly_historical_fixture_is_unaffected() -> None:
    """Replay stamps fetched_at=now, so nothing in a past fixture is future."""
    connector = OpenMeteoConnector(FIXTURE, drop_future_hours=True)
    emitted = sum(len(connector.normalize(raw)) for raw in connector.fetch(FetchRequest()))

    unfiltered = OpenMeteoConnector(FIXTURE, drop_future_hours=False)
    baseline = sum(len(unfiltered.normalize(raw)) for raw in unfiltered.fetch(FetchRequest()))

    assert emitted == baseline
