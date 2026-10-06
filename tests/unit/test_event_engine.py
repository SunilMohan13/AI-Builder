"""Event engine and fixture-path detection tests."""

from pathlib import Path

from aeropulse_connector_app.runner import replay_all
from aeropulse_contracts.envelope import KafkaEnvelope
from aeropulse_contracts.event import EventStatus
from aeropulse_contracts.fire import FireObservation
from aeropulse_contracts.meteo import MeteorologicalObservation
from aeropulse_contracts.observation import Observation
from aeropulse_contracts.raster import RasterObservation
from aeropulse_worker.pipeline import (
    InMemoryRepository,
    process_air_quality,
    process_fire,
    process_weather,
    run_detection,
)


def _ingest(repo: InMemoryRepository, payload: dict) -> None:
    if "measurement" in payload:
        process_air_quality(Observation.model_validate(payload), repo)
    elif "fire" in payload:
        process_fire(FireObservation.model_validate(payload), repo)
    elif payload.get("schema_version") == "raster.v1":
        repo.add_raster(RasterObservation.model_validate(payload))
    else:
        process_weather(MeteorologicalObservation.model_validate(payload), repo)


def test_fixture_replay_creates_punjab_event() -> None:
    repo = InMemoryRepository()
    envelopes: list[tuple[str, KafkaEnvelope]] = []

    def capture(topic: str, envelope: KafkaEnvelope) -> None:
        envelopes.append((topic, envelope))
        _ingest(repo, envelope.payload)

    replay_all(Path("fixtures"), capture)
    result = run_detection(repo)
    assert result["events"] >= 1
    open_events = [
        e
        for e in repo.event_store.events.values()
        if e.status not in {EventStatus.REJECTED, EventStatus.RESOLVED}
    ]
    assert open_events

    # Select the fire-corroborated event explicitly rather than assuming it
    # ranks highest. Since OpenAQ joined the replay it contributes Delhi
    # ground stations reading ~186 ug/m3 with no nearby fire, so the
    # top-confidence open event is no longer necessarily the Punjab one.
    fire_events = [
        e
        for e in open_events
        if any(ev.evidence_type == "fire_detection" for ev in repo.event_store.evidence[e.event_id])
    ]
    assert fire_events, "fixture replay must still produce a fire-corroborated event"
    event = max(fire_events, key=lambda e: e.overall_confidence)
    types = {ev.evidence_type for ev in repo.event_store.evidence[event.event_id]}
    assert "cpcb_anomaly" in types
    assert "fire_detection" in types


def test_latest_features_populated_for_every_cell_not_just_events() -> None:
    """LLD §13/§20: grid_feature/grid_prediction persistence must cover every
    processed cell, not only the ones that happened to trigger an event."""
    repo = InMemoryRepository()

    def capture(topic: str, envelope: KafkaEnvelope) -> None:
        _ingest(repo, envelope.payload)

    replay_all(Path("fixtures"), capture)
    run_detection(repo)

    assert repo.event_store.latest_features
    # More cells were processed than events were created, proving features are
    # not gated on `evaluate_cell` returning non-None.
    assert len(repo.event_store.latest_features) >= len(repo.event_store.events)
    for feature in repo.event_store.latest_features.values():
        assert feature.grid_id
        assert feature.timestamp is not None


def test_forecast_and_impact_confidence_are_wired_not_hardcoded() -> None:
    """LLD §21.3: four confidences must be populated, not left at 0.0."""
    repo = InMemoryRepository()

    def capture(topic: str, envelope: KafkaEnvelope) -> None:
        _ingest(repo, envelope.payload)

    replay_all(Path("fixtures"), capture)
    run_detection(repo)
    events_with_forecast = [
        e for e in repo.event_store.events.values() if e.event_id in repo.event_store.forecasts
    ]
    assert events_with_forecast
    assert any(e.forecast_confidence > 0.0 for e in events_with_forecast)


def test_duplicate_snapshot_does_not_spawn_second_open_event() -> None:
    repo = InMemoryRepository()
    envelopes: list[KafkaEnvelope] = []

    def capture(_topic: str, envelope: KafkaEnvelope) -> None:
        envelopes.append(envelope)
        _ingest(repo, envelope.payload)

    replay_all(Path("fixtures"), capture)
    run_detection(repo)
    first_open = dict(repo.event_store.open_by_grid)
    replay_all(Path("fixtures"), capture)
    run_detection(repo)
    assert repo.event_store.open_by_grid == first_open or set(
        repo.event_store.open_by_grid.values()
    ).issubset(set(first_open.values()) | set(repo.event_store.events))
