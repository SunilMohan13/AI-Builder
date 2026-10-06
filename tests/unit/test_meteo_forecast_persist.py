"""Forecast hours are stored and kept off the detection path."""

from datetime import UTC, datetime

from aeropulse_common.topics import METEO_FORECAST
from aeropulse_contracts.meteo_forecast import MeteoForecast
from aeropulse_contracts.observation import Location, Provenance, ProvenanceClass
from aeropulse_worker.main import _handle
from aeropulse_worker.pipeline import InMemoryRepository


def _forecast() -> MeteoForecast:
    return MeteoForecast(
        forecast_id="fc-1",
        source_id="openmeteo",
        source_record_id="openmeteo:1",
        issued_at=datetime(2026, 9, 8, 6, tzinfo=UTC),
        valid_at=datetime(2026, 9, 8, 12, tzinfo=UTC),
        location=Location(lat=28.6, lon=77.2),
        wind_u_10m=1.2,
        wind_v_10m=-0.4,
        provenance=Provenance(
            provider="Open-Meteo",
            connector_version="1",
            provenance_class=ProvenanceClass.MODEL_DERIVED,
        ),
    )


class _RecordingRepository:
    def __init__(self) -> None:
        self.saved: list[MeteoForecast] = []

    def upsert_meteo_forecast(self, forecast: MeteoForecast) -> bool:
        self.saved.append(forecast)
        return True


def test_meteo_forecast_is_persisted_without_detection(monkeypatch) -> None:
    called = {"detection": 0}

    def _boom(*_args, **_kwargs):
        called["detection"] += 1
        raise AssertionError("detection must not run for a forecast hour")

    monkeypatch.setattr("aeropulse_worker.main.run_detection", _boom)
    repo = _RecordingRepository()
    forecast = _forecast()

    _handle(
        METEO_FORECAST,
        {"payload": forecast.model_dump(mode="json")},
        repo,  # type: ignore[arg-type]
        InMemoryRepository(),
    )

    assert called["detection"] == 0
    assert len(repo.saved) == 1
    assert repo.saved[0].forecast_id == "fc-1"
    assert repo.saved[0].valid_at == forecast.valid_at
