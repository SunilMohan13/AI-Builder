"""Environmental Intelligence Graph contracts (graph_node.v1, graph_edge.v1).

A logical graph stored as rows and snapshot subgraphs; there is no graph
database. Edges are associations, never causation: the vocabulary has no
``caused`` edge on purpose.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from aeropulse_contracts.provenance import ProvenanceClass

NodeKind = Literal[
    "region",
    "place",
    "cell",
    "station",
    "fire_cluster",
    "plume",
    "anomaly",
    "pollution_event",
    "citizen_report",
    "incident",
    "wind_run",
]

EdgeKind = Literal[
    "detected_by",
    "located_in",
    "emits",
    "drives",
    "reaches",
    "exposes",
    "observes",
    "traced_by",
    "on_back_trajectory_of",
    "consistent_with",
    "near",
    "groups",
    "upwind_of",
]


class GroundedValue(BaseModel):
    """A value that can enter the agent's tool ledger with its origin."""

    model_config = {"extra": "forbid"}

    value: float | str | bool | None
    unit: str | None = None
    source_id: str
    provenance_class: ProvenanceClass
    observed_at: datetime | None = None


class GraphNode(BaseModel):
    """One node of the logical graph."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["graph_node.v1"] = "graph_node.v1"
    node_id: str
    kind: NodeKind
    region_id: str
    valid_from: datetime
    valid_to: datetime | None = None
    attributes: dict[str, GroundedValue] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """One association between two nodes."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["graph_edge.v1"] = "graph_edge.v1"
    edge_id: str
    kind: EdgeKind
    src: str
    dst: str
    producer: str
    provenance_class: ProvenanceClass
    attributes: dict[str, GroundedValue] = Field(default_factory=dict)
    cycle_time: datetime


class IncidentSummary(BaseModel):
    """A connected component worth an operator's attention, with its subgraph."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["incident.v1"] = "incident.v1"
    incident_id: str
    region_id: str
    root_kind: NodeKind
    first_seen: datetime
    last_updated: datetime
    place_ids_reached: list[str] = Field(default_factory=list)
    node_ids: list[str]
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
