"""Connector fixture → canonical contract tests."""

from datetime import UTC, datetime
from pathlib import Path

from aeropulse_connector_cpcb import CpcbConnector
from aeropulse_connector_firms import FirmsConnector
from aeropulse_connector_imd import ImdConnector
from aeropulse_connector_sdk.contracts import FetchRequest, RawRecord
from aeropulse_contracts.fire import FireObservation
from aeropulse_contracts.meteo import MeteorologicalObservation
from aeropulse_contracts.observation import Observation

ROOT = Path("fixtures")


def test_cpcb_normalizes_pollutants() -> None:
    connector = CpcbConnector(ROOT / "cpcb" / "stations.json")
    records = list(connector.fetch(FetchRequest()))
    assert len(records) == 2
    observations: list[Observation] = []
    for raw in records:
        observations.extend(connector.normalize(raw))
    parameters = {o.measurement.parameter for o in observations}
    assert "pm25" in parameters
    assert "pm10" in parameters
    ito = [o for o in observations if o.source_record_id.startswith("DL001")]
    assert any(o.measurement.value == 142.3 for o in ito)


def test_firms_normalizes_confidence() -> None:
    connector = FirmsConnector(ROOT / "firms" / "fires.json")
    observations: list[FireObservation] = []
    for raw in connector.fetch(FetchRequest()):
        observations.extend(connector.normalize(raw))
    assert len(observations) == 2
    assert observations[0].fire.frp == 82.4
    assert 0.0 <= observations[0].fire.confidence <= 1.0
    assert observations[1].fire.confidence == 0.9


def test_imd_normalizes_wind() -> None:
    connector = ImdConnector(ROOT / "imd" / "weather.json")
    raw = next(connector.fetch(FetchRequest()))
    obs = connector.normalize(raw)[0]
    assert isinstance(obs, MeteorologicalObservation)
    assert obs.wind_u == -2.1
    assert obs.humidity == 72.0


def test_cursor_offsets_fixture_fetches() -> None:
    connector = CpcbConnector(ROOT / "cpcb" / "stations.json")
    records = list(connector.fetch(FetchRequest(cursor="1")))
    assert len(records) == 1
    assert records[0].source_record_id == "PB014"


def test_empty_payload_yields_no_observations() -> None:
    connector = CpcbConnector()
    raw = RawRecord(
        source_id="cpcb",
        source_record_id="x",
        payload={
            "station_id": "x",
            "lat": 28.0,
            "lon": 77.0,
            "observed_at": "2026-09-08T00:00:00Z",
        },
        fetched_at=datetime.now(UTC),
    )
    assert connector.normalize(raw) == []
