"""Build evidence-lineage graphs from an event and its evidence (LLD 14.4)."""

from __future__ import annotations

from datetime import UTC, datetime

from aeropulse_common.ids import new_ulid
from aeropulse_contracts.event import EventEvidence, PollutionEvent
from aeropulse_contracts.lineage import EvidenceGraph, LineageEdge, LineageVertex


def build_graph(
    event: PollutionEvent,
    evidence: list[EventEvidence],
    *,
    origin_grid_id: str | None = None,
    model_version: str = "source-likelihood-0.1",
) -> EvidenceGraph:
    """Return vertices and provenance-bearing edges for an event.

    Args:
        event: Canonical event.
        evidence: Attached evidence rows.
        origin_grid_id: Primary H3 cell if not already on the event.
        model_version: Version stamped on derived edges.

    Returns:
        ``graph.v1`` payload for GET /events/{id}/graph.
    """
    now = datetime.now(UTC)
    vertices: dict[str, LineageVertex] = {}
    edges: list[LineageEdge] = []
    event_vid = f"event:{event.event_id}"
    vertices[event_vid] = LineageVertex(
        id=event_vid,
        type="PollutionEvent",
        properties={"status": event.status.value, "severity": event.severity.value},
    )
    grid_id = origin_grid_id or (event.grid_ids[0] if event.grid_ids else None)
    if grid_id:
        gid = f"grid:{grid_id}"
        vertices[gid] = LineageVertex(id=gid, type="GridCell", properties={"grid_id": grid_id})
        edges.append(
            _edge("LOCATED_IN", event_vid, gid, event.detection_confidence, [], model_version, now)
        )
    fv = f"feature:{event.feature_version}"
    vertices[fv] = LineageVertex(
        id=fv, type="FeatureVersion", properties={"version": event.feature_version}
    )
    edges.append(
        _edge("DERIVED_FROM", event_vid, fv, event.overall_confidence, [], model_version, now)
    )
    for mv in event.model_versions:
        mid = f"model:{mv}"
        vertices[mid] = LineageVertex(id=mid, type="ModelVersion", properties={"version": mv})
        edges.append(_edge("GENERATED_BY", event_vid, mid, event.overall_confidence, [], mv, now))

    for item in evidence:
        eid = f"evidence:{item.evidence_id}"
        vertices[eid] = LineageVertex(
            id=eid,
            type="Evidence",
            properties={"evidence_type": item.evidence_type, "summary": item.summary},
        )
        conf = item.quality_score if item.quality_score is not None else event.detection_confidence
        edge_type = "SUPPORTS" if item.evidence_type == "fire_detection" else "CORROBORATES"
        if item.evidence_type == "wind_consistency":
            edge_type = "UPWIND_OF"
        edges.append(_edge(edge_type, eid, event_vid, conf, [item.evidence_id], model_version, now))
        if item.grid_id:
            gid = f"grid:{item.grid_id}"
            vertices.setdefault(
                gid, LineageVertex(id=gid, type="GridCell", properties={"grid_id": item.grid_id})
            )
            edges.append(
                _edge("OBSERVED_IN", eid, gid, conf, [item.evidence_id], model_version, now)
            )
    return EvidenceGraph(
        event_id=event.event_id,
        vertices=list(vertices.values()),
        edges=edges,
    )


def _edge(
    edge_type: str,
    from_id: str,
    to_id: str,
    confidence: float,
    evidence_ids: list[str],
    model_version: str,
    created_at: datetime,
) -> LineageEdge:
    return LineageEdge(
        edge_id=new_ulid("edge"),
        edge_type=edge_type,
        from_id=from_id,
        to_id=to_id,
        confidence=round(max(0.0, min(1.0, confidence)), 4),
        evidence_ids=evidence_ids,
        model_version=model_version,
        created_at=created_at,
    )
