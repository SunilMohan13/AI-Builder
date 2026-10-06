"""Domain metrics actually increment (LLD §33.2, gap analysis P1-9).

A declared-but-never-incremented metric is worse than no metric: it produces
a dashboard panel that reads zero and is believed. These tests exist so the
counters cannot quietly stop being wired.
"""

from __future__ import annotations

from datetime import UTC, datetime

from aeropulse_contracts.observation import (
    Location,
    Measurement,
    Observation,
    Provenance,
    Quality,
)
from aeropulse_observability.metrics import (
    INGESTED_OBSERVATIONS,
    QUALITY_REJECTIONS,
)
from aeropulse_worker.pipeline import InMemoryRepository, process_air_quality


def _observation(
    value: float,
    *,
    source_id: str = "metrics-test",
    observed_at: datetime | None = None,
) -> Observation:
    # The dedup key is derived from the timestamp, so a caller testing
    # duplicate handling must pin it rather than take two different `now()`s.
    now = observed_at or datetime.now(UTC)
    return Observation(
        observation_id=f"obs-{value}",
        source_id=source_id,
        source_record_id=f"rec-{value}",
        observed_at=now,
        received_at=now,
        location=Location(lat=28.6, lon=77.2),
        measurement=Measurement(parameter="pm25", value=value, unit="ug/m3"),
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=Provenance(provider="test", connector_version="1.0.0"),
    )


def _counter_value(counter, **labels: str) -> float:
    """Read one labelled counter's current value, 0.0 when never incremented."""
    try:
        return counter.labels(**labels)._value.get()
    except Exception:
        return 0.0


def test_accepted_observations_are_counted() -> None:
    """An ingesting worker must be distinguishable from a stalled one."""
    labels = {
        "source_id": "metrics-accept",
        "observation_type": "air_quality",
        "outcome": "persisted",
    }
    before = _counter_value(INGESTED_OBSERVATIONS, **labels)

    process_air_quality(_observation(85.0, source_id="metrics-accept"), InMemoryRepository())

    assert _counter_value(INGESTED_OBSERVATIONS, **labels) == before + 1


def test_duplicates_are_counted_separately_from_new_rows() -> None:
    """Otherwise a replay loop looks like healthy ingestion."""
    repository = InMemoryRepository()
    fixed = datetime(2026, 9, 8, 12, tzinfo=UTC)
    labels = {
        "source_id": "metrics-dup",
        "observation_type": "air_quality",
        "outcome": "duplicate",
    }
    before = _counter_value(INGESTED_OBSERVATIONS, **labels)

    process_air_quality(_observation(90.0, source_id="metrics-dup", observed_at=fixed), repository)
    process_air_quality(_observation(90.0, source_id="metrics-dup", observed_at=fixed), repository)

    assert _counter_value(INGESTED_OBSERVATIONS, **labels) == before + 1


def test_quality_rejections_are_counted_per_failing_rule() -> None:
    """An operator needs to know *which* rule is rejecting everything."""
    rejected_labels = {
        "source_id": "metrics-reject",
        "observation_type": "air_quality",
        "outcome": "rejected",
    }
    before = _counter_value(INGESTED_OBSERVATIONS, **rejected_labels)

    # Negative PM2.5 is physically impossible and fails the range rule.
    result = process_air_quality(
        _observation(-50.0, source_id="metrics-reject"), InMemoryRepository()
    )

    assert result["status"] == "rejected"
    assert _counter_value(INGESTED_OBSERVATIONS, **rejected_labels) == before + 1
    # At least one named rule must have been attributed the rejection.
    assert any(
        _counter_value(QUALITY_REJECTIONS, source_id="metrics-reject", reason=reason) > 0
        for reason in result["reasons"]
    )
