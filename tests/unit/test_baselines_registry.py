"""Registry convergence: the baselines are real records (plan Phase 3).

The endpoint used to merge a hardcoded list of three always-PRODUCTION
baselines with the filesystem registry. One registry now backs it, so these
tests pin the property that made the merge unsafe: there must never be two
production records for one family.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from aeropulse_ml.baselines import baseline_records, is_baseline, sync_baselines
from aeropulse_ml.registry import ModelRecord, ModelRegistry, ModelStage


@pytest.fixture
def registry(tmp_path: Path) -> ModelRegistry:
    return ModelRegistry(tmp_path / "models")


def _champions_per_family(registry: ModelRegistry) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in registry.list_models():
        if record.stage is ModelStage.PRODUCTION:
            counts[record.model_name] = counts.get(record.model_name, 0) + 1
    return counts


def test_baselines_serve_when_nothing_is_trained(registry: ModelRegistry) -> None:
    """With no trained model, the deterministic path is what serves."""
    sync_baselines(registry)

    counts = _champions_per_family(registry)
    assert counts == {
        "pm25_estimator": 1,
        "anomaly_detector": 1,
        "source_likelihood": 1,
        "propagation_forecast": 1,
    }
    assert all(is_baseline(r) for r in registry.list_models())


def test_baseline_is_retired_when_a_champion_already_exists(
    registry: ModelRegistry,
) -> None:
    """Two production records in one family would make serving ambiguous."""
    registry.register(
        ModelRecord(
            model_id="trained-1",
            model_name="pm25_estimator",
            version="trained-1",
            artifact_uri="trained-1.joblib",
            training_time=datetime(2026, 9, 8, tzinfo=UTC),
        )
    )
    registry.promote_to_production("trained-1")

    sync_baselines(registry)

    assert _champions_per_family(registry)["pm25_estimator"] == 1
    baseline = registry.get("baseline-idw-0.1")
    assert baseline is not None
    assert baseline.stage is ModelStage.RETIRED
    assert "Superseded" in baseline.notes
    # The trained model still answers, and the loader can still find it.
    champion = registry.champion("pm25_estimator")
    assert champion is not None
    assert champion.model_id == "trained-1"


def test_sync_is_idempotent(registry: ModelRegistry) -> None:
    """An API process calls this per request; it must not churn the index."""
    first = sync_baselines(registry)
    snapshot = sorted((r.model_id, r.stage) for r in registry.list_models())

    second = sync_baselines(registry)
    third = sync_baselines(registry)

    assert len(first) == 4
    assert second == [] and third == []
    assert sorted((r.model_id, r.stage) for r in registry.list_models()) == snapshot


def test_sync_does_not_reset_an_operator_set_stage(registry: ModelRegistry) -> None:
    """An operator who retired a baseline must not see it resurrected."""
    sync_baselines(registry)
    registry.transition("quantile-baseline-0.1", ModelStage.RETIRED, force=True)

    sync_baselines(registry)

    record = registry.get("quantile-baseline-0.1")
    assert record is not None
    assert record.stage is ModelStage.RETIRED


def test_baselines_carry_no_artifact(registry: ModelRegistry) -> None:
    """Their behaviour is code, so the loader must never try to open one."""
    for record in baseline_records():
        assert record.artifact_uri == ""
    sync_baselines(registry)
    assert registry.champion("pm25_estimator") is None
