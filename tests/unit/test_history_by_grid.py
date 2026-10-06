"""Detection history excludes the current hour and model-derived values."""

from datetime import UTC, datetime

from aeropulse_contracts.observation import (
    Location,
    Measurement,
    Observation,
    Provenance,
    Quality,
)
from aeropulse_worker.pipeline import InMemoryRepository, history_by_grid


def _obs(source_id: str, hour: int, grid_id: str, value: float) -> Observation:
    observed_at = datetime(2026, 9, 8, hour, tzinfo=UTC)
    return Observation(
        observation_id=f"{source_id}-{hour}",
        source_id=source_id,
        source_record_id=f"{grid_id}-{hour}",
        observed_at=observed_at,
        received_at=observed_at,
        location=Location(lat=28.6, lon=77.2),
        measurement=Measurement(parameter="pm25", value=value, unit="ug/m3"),
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=Provenance(provider=source_id, connector_version="1"),
        grid_id=grid_id,
        dedup_key=f"{source_id}-{grid_id}-{hour}",
    )


def test_history_is_prior_ground_truth_only() -> None:
    repository = InMemoryRepository()
    repository.upsert_air_quality(_obs("cpcb", 1, "cell-a", 10.0))
    repository.upsert_air_quality(_obs("cpcb", 2, "cell-a", 20.0))
    repository.upsert_air_quality(_obs("cpcb", 3, "cell-a", 30.0))
    repository.upsert_air_quality(_obs("openmeteo", 2, "cell-a", 999.0))

    history = history_by_grid(repository)

    assert history["cell-a"] == [10.0, 20.0]
