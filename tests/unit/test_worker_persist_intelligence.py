"""`_persist_intelligence` must flush grid_feature/grid_prediction to the DB writer
(LLD §13/§20), not just events/evidence/graphs/forecasts."""

from __future__ import annotations

from pathlib import Path

from aeropulse_connector_app.runner import replay_all
from aeropulse_contracts.envelope import KafkaEnvelope
from aeropulse_contracts.feature import GridFeature
from aeropulse_contracts.fire import FireObservation
from aeropulse_contracts.meteo import MeteorologicalObservation
from aeropulse_contracts.observation import Observation
from aeropulse_contracts.prediction import GridPrediction
from aeropulse_contracts.raster import RasterObservation
from aeropulse_worker.main import _persist_intelligence
from aeropulse_worker.pipeline import (
    InMemoryRepository,
    process_air_quality,
    process_fire,
    process_weather,
    run_detection,
)


class _RecordingWriter:
    """Fake Timescale writer that records every call it receives."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.features: list[GridFeature] = []
        self.predictions: list[GridPrediction] = []
        self.health: list[tuple] = []

    def upsert_air_quality(self, observation: object) -> bool:
        return True

    def upsert_fire(self, observation: object) -> bool:
        return True

    def upsert_weather(self, observation: object) -> bool:
        return True

    def record_dlq(self, source_id: str, payload: dict, error: str) -> None:
        pass

    def upsert_event(self, event: object) -> None:
        self.events.append(event.event_id)  # type: ignore[attr-defined]

    def insert_evidence(self, event_id: str, items: list) -> None:
        pass

    def insert_graph(self, graph: object) -> None:
        pass

    def insert_forecast(self, forecast: object) -> None:
        pass

    def upsert_grid_feature(self, feature: GridFeature) -> None:
        self.features.append(feature)

    def upsert_grid_prediction(self, prediction: GridPrediction) -> None:
        self.predictions.append(prediction)

    def upsert_source_health(self, *args: object, **kwargs: object) -> None:
        self.health.append((args, kwargs))


def _ingest(repo: InMemoryRepository, payload: dict) -> None:
    if "measurement" in payload:
        process_air_quality(Observation.model_validate(payload), repo)
    elif "fire" in payload:
        process_fire(FireObservation.model_validate(payload), repo)
    elif payload.get("schema_version") == "raster.v1":
        repo.add_raster(RasterObservation.model_validate(payload))
    else:
        process_weather(MeteorologicalObservation.model_validate(payload), repo)


def test_persist_intelligence_flushes_grid_features_and_predictions() -> None:
    snapshot = InMemoryRepository()

    def capture(topic: str, envelope: KafkaEnvelope) -> None:
        _ingest(snapshot, envelope.payload)

    replay_all(Path("fixtures"), capture)
    run_detection(snapshot)

    writer = _RecordingWriter()
    _persist_intelligence(writer, snapshot)

    assert writer.events, "expected at least one event to be flushed"
    assert writer.features, "expected grid_feature rows to be flushed"
    assert len(writer.features) == len(snapshot.event_store.latest_features)
    assert len(writer.predictions) == len(snapshot.event_store.latest_predictions)
    assert writer.health == [], "connector runs own source_health; worker must not attribute CPCB"


def test_persist_intelligence_is_noop_when_writer_has_no_upsert_event() -> None:
    snapshot = InMemoryRepository()
    _persist_intelligence(object(), snapshot)  # type: ignore[arg-type]  # must not raise
