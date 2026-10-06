"""Evidence lineage vertices and edges (LLD section 14.4) as JSON, not Arango."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class LineageVertex(BaseModel):
    """A graph vertex: grid, observation, fire, weather, event, or model."""

    model_config = {"extra": "forbid"}

    id: str
    type: str
    properties: dict[str, Any] = Field(default_factory=dict)


class LineageEdge(BaseModel):
    """A typed, provenance-bearing relationship."""

    model_config = {"extra": "forbid"}

    edge_id: str
    edge_type: str
    from_id: str
    to_id: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)
    model_version: str | None = None
    created_at: datetime


class EvidenceGraph(BaseModel):
    """UI-colleague contract for GET /events/{id}/graph."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["graph.v1"] = "graph.v1"
    event_id: str
    vertices: list[LineageVertex]
    edges: list[LineageEdge]
