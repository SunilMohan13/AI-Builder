"""Worker pipeline persistence and dedup tests."""

from datetime import UTC, datetime

from aeropulse_contracts.observation import (
    Location,
    Measurement,
    Observation,
    Provenance,
    Quality,
)
from aeropulse_worker.pipeline import InMemoryRepository, process_air_quality


def _obs() -> Observation:
    return Observation(
        observation_id="obs_1",
        source_id="cpcb",
        source_record_id="DL001_2026-09-08T05:15:00Z_pm25",
        observed_at=datetime(2026, 9, 8, 5, 15, tzinfo=UTC),
        received_at=datetime(2026, 9, 8, 5, 17, tzinfo=UTC),
        location=Location(lat=28.628, lon=77.241),
        measurement=Measurement(parameter="pm25", value=142.3, unit="ug/m3"),
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=Provenance(provider="CPCB", connector_version="1.0.0"),
    )


def test_process_persists_and_dedups() -> None:
    repo = InMemoryRepository()
    first = process_air_quality(_obs(), repo)
    second = process_air_quality(_obs(), repo)
    assert first["status"] == "persisted"
    assert second["status"] == "duplicate"
    assert len(repo.air_quality) == 1
    assert first["grid_id"]


def test_invalid_observation_rejected() -> None:
    repo = InMemoryRepository()
    obs = _obs()
    obs.measurement.value = -5
    result = process_air_quality(obs, repo)
    assert result["status"] == "rejected"
    assert repo.air_quality == {}
