"""Evidence graph contract tests."""

from datetime import UTC, datetime

from aeropulse_contracts.event import (
    EventEvidence,
    EventSeverity,
    EventStatus,
    PollutionEvent,
)
from aeropulse_intelligence.lineage import build_graph


def test_graph_contains_supports_or_corroborates() -> None:
    event = PollutionEvent(
        event_id="evt_g",
        status=EventStatus.ACTIVE,
        severity=EventSeverity.HIGH,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        grid_ids=["cell"],
        detection_confidence=0.8,
        source_confidence=0.7,
        forecast_confidence=0.0,
        impact_confidence=0.0,
        overall_confidence=0.75,
        evidence_freshness=1.0,
        sensor_coverage=0.5,
        model_versions=["baseline-idw-0.1"],
        feature_version="grid-features-0.4.0",
    )
    evidence = [
        EventEvidence(
            evidence_id="evd_fire",
            evidence_type="fire_detection",
            grid_id="cell",
            summary="fires",
            quality_score=0.9,
        )
    ]
    graph = build_graph(event, evidence, origin_grid_id="cell")
    types = {e.edge_type for e in graph.edges}
    assert "SUPPORTS" in types
    assert "DERIVED_FROM" in types
    assert graph.event_id == "evt_g"
