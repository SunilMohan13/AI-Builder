"""Environmental intelligence graph contracts.

Nodes and edges are associations. The vocabulary has no caused-by edge.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from aeropulse_contracts.observation import ProvenanceClass

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
    """A number or label that names where it came from."""

    model_config = {"extra": "forbid"}

    value: float | int | str | bool | None
    unit: str | None = None
    source_id: str
    provenance_class: ProvenanceClass
    observed_at: datetime | None = None


class GraphNode(BaseModel):
    """One entity in a region cycle's graph."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["graph_node.v1"] = "graph_node.v1"
    node_id: str
    kind: NodeKind
    region_id: str
    valid_from: datetime
    valid_to: datetime | None = None
    attributes: dict[str, GroundedValue] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """A directed association between two nodes."""

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
    region_id: str


class IncidentSummary(BaseModel):
    """A stable grouping of fire, plume, anomaly, and citizen nodes."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["incident_summary.v1"] = "incident_summary.v1"
    incident_id: str
    region_id: str
    root_kind: NodeKind
    places_reached: list[str] = Field(default_factory=list)
    updated_at: datetime
    node_ids: list[str] = Field(default_factory=list)
    edge_ids: list[str] = Field(default_factory=list)
