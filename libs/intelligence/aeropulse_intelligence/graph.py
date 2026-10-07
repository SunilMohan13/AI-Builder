"""Environmental Intelligence Graph builder (LLD APAC 10).

Deterministic: the same cycle inputs give the same nodes, edges and ids. Edges
are associations, never causation (the vocabulary has no ``caused`` edge).
Co-location is a shared resolution-6 cell, so no distance threshold is
invented here; plume links come from the plume model's own outputs.

An incident is a connected component that contains a fire cluster or anomaly
*and* a forward plume reaching a place, or that contains an active pollution
event. Context nodes (region, place, wind run) do not join components, so two
fires heading to the same city stay two incidents.

Citizen reports enter only once corroborated (or accepted by an operator):
``located_in`` their cell, ``consistent_with`` a forward plume they seeded or
whose P90 footprint holds them, and ``near`` the fire they matched. They join
an incident through those links and never qualify one on their own.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import h3
from aeropulse_contracts import EventStatus, PollutionEvent
from aeropulse_contracts.graph import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    GroundedValue,
    IncidentSummary,
    NodeKind,
)
from aeropulse_contracts.plume import Plume
from aeropulse_contracts.provenance import ProvenanceClass
from aeropulse_contracts.snapshot import (
    AnomalyFlag,
    CellState,
    CitizenWatchSummary,
    FireCluster,
)

GRAPH_VERSION = "eig-1.0"

#: Settings.
CELL_RESOLUTION = 6
REPORT_RESOLUTION = 8
MIN_INCIDENT_OVERLAP = 1
ACTIVE_EVENT_STATUSES = frozenset(
    {EventStatus.CONFIRMED, EventStatus.FORECASTING, EventStatus.ACTIVE, EventStatus.DECLINING}
)

CONTEXT_KINDS: frozenset[NodeKind] = frozenset({"region", "place", "wind_run", "incident"})
#: Nodes whose ids survive from one cycle to the next; incident ids follow them.
STABLE_KINDS: frozenset[NodeKind] = frozenset(
    {"fire_cluster", "pollution_event", "cell", "station"}
)
ROOT_PRIORITY: tuple[NodeKind, ...] = (
    "fire_cluster",
    "anomaly",
    "pollution_event",
    "citizen_report",
)

_SIM = ProvenanceClass.SIMULATED
_MEASURED = ProvenanceClass.MEASURED
_HEURISTIC = ProvenanceClass.HEURISTIC
_REFERENCE = ProvenanceClass.MODEL_DERIVED


@dataclass(frozen=True)
class GraphInputs:
    region_id: str
    cycle_time: datetime
    fires: Sequence[FireCluster] = ()
    anomalies: Sequence[AnomalyFlag] = ()
    events: Sequence[PollutionEvent] = ()
    plumes: Sequence[Plume] = ()
    cells: Sequence[CellState] = ()
    #: Corroborated (or operator-accepted) citizen reports only.
    citizen: Sequence[CitizenWatchSummary] = ()


@dataclass
class RegionGraph:
    region_id: str
    cycle_time: datetime
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: dict[str, GraphEdge] = field(default_factory=dict)

    def add_node(
        self,
        node_id: str,
        kind: NodeKind,
        *,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        attributes: dict[str, GroundedValue] | None = None,
    ) -> str:
        if node_id not in self.nodes:
            self.nodes[node_id] = GraphNode(
                node_id=node_id,
                kind=kind,
                region_id=self.region_id,
                valid_from=valid_from or self.cycle_time,
                valid_to=valid_to,
                attributes=attributes or {},
            )
        return node_id

    def add_edge(
        self,
        kind: EdgeKind,
        src: str,
        dst: str,
        *,
        producer: str,
        provenance: ProvenanceClass,
        attributes: dict[str, GroundedValue] | None = None,
    ) -> None:
        edge_id = "edg_" + _digest(self.region_id, self.cycle_time.isoformat(), kind, src, dst)
        if edge_id not in self.edges:
            self.edges[edge_id] = GraphEdge(
                edge_id=edge_id,
                kind=kind,
                src=src,
                dst=dst,
                producer=producer,
                provenance_class=provenance,
                attributes=attributes or {},
                cycle_time=self.cycle_time,
            )

    def components(self) -> list[list[str]]:
        """Connected components over non-context nodes, each sorted, in a stable order."""
        parent = {n: n for n, node in self.nodes.items() if node.kind not in CONTEXT_KINDS}

        def find(n: str) -> str:
            while parent[n] != n:
                parent[n] = parent[parent[n]]
                n = parent[n]
            return n

        for edge in self.edges.values():
            if edge.src in parent and edge.dst in parent:
                a, b = find(edge.src), find(edge.dst)
                if a != b:
                    parent[max(a, b)] = min(a, b)
        groups: dict[str, list[str]] = defaultdict(list)
        for n in parent:
            groups[find(n)].append(n)
        return sorted((sorted(g) for g in groups.values()), key=lambda g: g[0])


def build_graph(inputs: GraphInputs) -> RegionGraph:
    """Nodes and association edges for one region cycle."""
    rid, t = inputs.region_id, inputs.cycle_time
    graph = RegionGraph(rid, t)
    region = graph.add_node(f"region:{rid}", "region")
    measured_cells = {
        c.grid_id: c
        for c in inputs.cells
        if c.provenance_class == ProvenanceClass.MEASURED and c.pm25_source_id
    }

    fire_nodes: dict[str, str] = {}
    for fire in inputs.fires:
        source = ",".join(fire.source_ids) or "firms"
        node = graph.add_node(
            f"fire_cluster:{rid}:{fire.cluster_id}",
            "fire_cluster",
            valid_from=fire.first_seen,
            valid_to=fire.last_seen,
            attributes={
                "frp_total": _value(fire.frp_total, "MW", source, _MEASURED, fire.last_seen),
                "detection_count": _value(
                    float(fire.detection_count), None, source, _MEASURED, fire.last_seen
                ),
            },
        )
        fire_nodes[fire.cluster_id] = node
        graph.add_edge(
            "located_in",
            node,
            _cell(graph, fire.parent_cell),
            producer=GRAPH_VERSION,
            provenance=_MEASURED,
        )

    anomaly_nodes: dict[str, str] = {}
    for flag in sorted(inputs.anomalies, key=lambda a: (a.grid_id, a.observed_at)):
        cell = measured_cells.get(flag.grid_id)
        pm_source = cell.pm25_source_id if cell and cell.pm25_source_id else flag.method_version
        pm_class = _MEASURED if cell else flag.provenance_class
        attributes = {
            "observed_pm25": _value(
                flag.observed_pm25, "ug/m3", pm_source, pm_class, flag.observed_at
            ),
            "score": _value(flag.score, None, flag.method_version, flag.provenance_class),
        }
        if flag.expected_high is not None:
            attributes["expected_high"] = _value(
                flag.expected_high, "ug/m3", flag.method_version, flag.provenance_class
            )
        node = graph.add_node(
            f"anomaly:{rid}:{flag.grid_id}:{flag.observed_at:%Y%m%dT%H%MZ}",
            "anomaly",
            valid_from=flag.observed_at,
            attributes=attributes,
        )
        anomaly_nodes[flag.grid_id] = node
        graph.add_edge(
            "located_in",
            node,
            _cell(graph, _parent(flag.grid_id)),
            producer=GRAPH_VERSION,
            provenance=flag.provenance_class,
        )
        if cell is not None and cell.pm25_source_id:
            station = graph.add_node(
                f"station:{cell.pm25_source_id}:{cell.grid_id}",
                "station",
                attributes={
                    "source_id": _value(cell.pm25_source_id, None, cell.pm25_source_id, _MEASURED)
                },
            )
            graph.add_edge(
                "observes", station, node, producer=cell.pm25_source_id, provenance=_MEASURED
            )

    event_nodes: dict[str, str] = {}
    for event in inputs.events:
        engine = ",".join(event.model_versions) or "event-engine"
        node = graph.add_node(
            f"pollution_event:{rid}:{event.event_id}",
            "pollution_event",
            valid_from=event.created_at,
            attributes={
                "status": _value(event.status.value, None, engine, _HEURISTIC, event.updated_at),
                "severity": _value(event.severity.value, None, engine, _HEURISTIC),
                "overall_confidence": _value(event.overall_confidence, None, engine, _HEURISTIC),
            },
        )
        event_nodes[event.event_id] = node
        for parent in sorted({_parent(g) for g in event.grid_ids}):
            graph.add_edge(
                "located_in",
                node,
                _cell(graph, parent),
                producer=GRAPH_VERSION,
                provenance=_HEURISTIC,
            )

    plume_nodes: dict[str, str] = {}
    for plume in sorted(inputs.plumes, key=lambda p: p.plume_id):
        plume_nodes[plume.plume_id] = _add_plume(
            graph, plume, region, fire_nodes, event_nodes, anomaly_nodes
        )
    fires_by_id = {f.cluster_id: f for f in inputs.fires}
    for report in sorted(inputs.citizen, key=lambda r: r.report_id):
        _add_citizen(graph, report, inputs.plumes, plume_nodes, fire_nodes, fires_by_id)
    return graph


def find_incidents(
    graph: RegionGraph, previous: Iterable[IncidentSummary] = ()
) -> list[IncidentSummary]:
    """Incidents in ``graph``, keeping ids of previous incidents they overlap.

    Adds an ``incident`` node and ``groups`` edges for each incident to ``graph``.
    """
    rid, t = graph.region_id, graph.cycle_time
    qualifying = [c for c in graph.components() if _qualifies(graph, c)]
    earlier = [p for p in previous if p.region_id == rid]
    claims = _match(qualifying, earlier, graph)

    incidents: list[IncidentSummary] = []
    for index, members in enumerate(qualifying):
        roots = [n for n in members if graph.nodes[n].kind in ROOT_PRIORITY]
        prior = claims.get(index)
        incident_id = (
            prior.incident_id
            if prior
            else "inc_" + _digest(rid, t.isoformat(), *(roots or members))
        )
        incident_node = graph.add_node(f"incident:{rid}:{incident_id}", "incident")
        for member in members:
            graph.add_edge(
                "groups", incident_node, member, producer=GRAPH_VERSION, provenance=_HEURISTIC
            )
        member_set = set(members)
        edges = [e for e in graph.edges.values() if e.src in member_set or e.dst in member_set]
        touched = sorted(member_set | {e.src for e in edges} | {e.dst for e in edges})
        incidents.append(
            IncidentSummary(
                incident_id=incident_id,
                region_id=rid,
                root_kind=_root_kind(graph, members),
                first_seen=min(prior.first_seen, t) if prior else t,
                last_updated=t,
                place_ids_reached=sorted(
                    {
                        e.dst.split(":", 2)[2]
                        for e in edges
                        if e.kind == "reaches" and e.src in member_set
                    }
                ),
                node_ids=members,
                nodes=[graph.nodes[n] for n in touched],
                edges=sorted(edges, key=lambda e: e.edge_id),
            )
        )
    return incidents


# --- plumes ---------------------------------------------------------------


def _add_plume(
    graph: RegionGraph,
    plume: Plume,
    region: str,
    fire_nodes: dict[str, str],
    event_nodes: dict[str, str],
    anomaly_nodes: dict[str, str],
) -> str:
    rid = graph.region_id
    version = plume.model_version
    longest = max((h.horizon_hours for h in plume.horizons), default=0.0)
    span = timedelta(hours=longest)
    if plume.direction == "forward":
        valid_from, valid_to = plume.release_time, plume.release_time + span
    else:
        valid_from, valid_to = plume.release_time - span, plume.release_time
    node = graph.add_node(
        f"plume:{rid}:{plume.plume_id}",
        "plume",
        valid_from=valid_from,
        valid_to=valid_to,
        attributes={
            "direction": _value(plume.direction, None, version, _SIM),
            "max_horizon_hours": _value(longest, "h", version, _SIM),
            "degraded": _value(plume.degraded, None, version, _SIM),
            "experimental": _value(plume.experimental, None, version, _SIM),
        },
    )

    wind = plume.wind_issued_at
    wind_id = (
        f"wind_run:{rid}:{wind:%Y%m%dT%H%MZ}"
        if wind
        else f"wind_run:{rid}:observed:{graph.cycle_time:%Y%m%dT%H%MZ}"
    )
    graph.add_node(wind_id, "wind_run", valid_from=wind or graph.cycle_time)
    graph.add_edge("drives", wind_id, node, producer=version, provenance=_SIM)

    origin = plume.origin
    ref = origin.ref_id or ""
    if plume.direction == "forward":
        emitters = {"fire_cluster": fire_nodes, "event": event_nodes}.get(origin.kind, {})
        source = emitters.get(ref)
        if source is not None:
            graph.add_edge("emits", source, node, producer=version, provenance=_SIM)
        for arrival in plume.arrivals:
            place = graph.add_node(
                f"place:{rid}:{arrival.place_id}",
                "place",
                attributes={"name": _value(arrival.name, None, "gazetteer", _REFERENCE)},
            )
            attributes = {"probability": _value(arrival.probability, None, version, _SIM)}
            if arrival.eta_hours_median is not None:
                attributes["eta_hours"] = _value(arrival.eta_hours_median, "h", version, _SIM)
            if arrival.population is not None:
                attributes["population"] = _value(
                    arrival.population, "people", "gazetteer", _REFERENCE
                )
            graph.add_edge(
                "reaches", node, place, producer=version, provenance=_SIM, attributes=attributes
            )
        exposure = [(e, e.population_p90) for e in plume.exposure if e.population_p90 is not None]
        if exposure:
            last, people = max(exposure, key=lambda pair: pair[0].horizon_hours)
            attributes = {
                "population_p90": _value(people, "people", version, _SIM),
                "horizon_hours": _value(last.horizon_hours, "h", version, _SIM),
            }
            if last.population_source:
                attributes["population_source"] = _value(
                    last.population_source, None, last.population_source, _REFERENCE
                )
            graph.add_edge(
                "exposes", node, region, producer=version, provenance=_SIM, attributes=attributes
            )
        return node

    anomaly = anomaly_nodes.get(ref) if origin.kind == "anomaly" else None
    if anomaly is not None:
        graph.add_edge("traced_by", anomaly, node, producer=version, provenance=_SIM)
    for candidate in plume.source_candidates:
        fire = fire_nodes.get(candidate.fire_cluster_id)
        if fire is None:
            continue
        graph.add_edge(
            "on_back_trajectory_of",
            node,
            fire,
            producer=version,
            provenance=_SIM,
            attributes={
                "particle_fraction": _value(candidate.particle_fraction, None, version, _SIM),
                "distance_km": _value(candidate.distance_km, "km", version, _SIM),
                "bearing_deg": _value(candidate.bearing_deg, "deg", version, _SIM),
            },
        )
    return node


# --- citizen reports --------------------------------------------------------


def _add_citizen(
    graph: RegionGraph,
    report: CitizenWatchSummary,
    plumes: Sequence[Plume],
    plume_nodes: dict[str, str],
    fire_nodes: dict[str, str],
    fires: dict[str, FireCluster],
) -> None:
    """A corroborated report: where it is, the plumes it agrees with, the fire it is near."""
    rid = graph.region_id
    observed = ProvenanceClass(report.provenance_class)
    source = "citizen-analyzer"
    node = graph.add_node(
        f"citizen_report:{rid}:{report.report_id}",
        "citizen_report",
        valid_from=report.observed_at or graph.cycle_time,
        attributes={
            "visual_class": _value(report.visual_class, None, source, observed, report.observed_at),
            "corroboration": _value(report.corroboration, None, source, _HEURISTIC),
        },
    )
    cell = h3.latlng_to_cell(report.lat_rounded, report.lon_rounded, REPORT_RESOLUTION)
    graph.add_edge(
        "located_in", node, _cell(graph, _parent(cell)), producer=source, provenance=_HEURISTIC
    )
    ancestors = {cell, *(h3.cell_to_parent(cell, r) for r in range(REPORT_RESOLUTION))}
    for plume in plumes:
        target = plume_nodes.get(plume.plume_id)
        if target is None or plume.direction != "forward":
            continue
        seeded = plume.origin.kind == "citizen_report" and plume.origin.ref_id == report.report_id
        inside = next(
            (h.horizon_hours for h in plume.horizons if ancestors & set(h.p90_cells)), None
        )
        if not seeded and inside is None:
            continue
        attributes = {
            "relation": _value(
                "seeded_by_report" if seeded else "inside_p90", None, plume.model_version, _SIM
            )
        }
        if inside is not None:
            attributes["horizon_hours"] = _value(inside, "h", plume.model_version, _SIM)
        graph.add_edge(
            "consistent_with",
            node,
            target,
            producer=plume.model_version,
            provenance=_SIM,
            attributes=attributes,
        )
    fire = fires.get(report.matched_fire_id or "")
    fire_node = fire_nodes.get(report.matched_fire_id or "")
    if fire is not None and fire_node is not None:
        km = h3.great_circle_distance(
            (report.lat_rounded, report.lon_rounded), (fire.lat, fire.lon), unit="km"
        )
        graph.add_edge(
            "near",
            node,
            fire_node,
            producer=source,
            provenance=_HEURISTIC,
            attributes={"distance_km": _value(round(km, 1), "km", source, _HEURISTIC)},
        )


# --- incidents --------------------------------------------------------------


def _qualifies(graph: RegionGraph, members: Sequence[str]) -> bool:
    active = {s.value for s in ACTIVE_EVENT_STATUSES}
    nodes = [graph.nodes[n] for n in members]
    for node in nodes:
        status = node.attributes.get("status")
        if node.kind == "pollution_event" and status is not None and status.value in active:
            return True
    if not {n.kind for n in nodes} & {"fire_cluster", "anomaly"}:
        return False
    member_set = set(members)
    return any(e.kind == "reaches" and e.src in member_set for e in graph.edges.values())


def _match(
    components: Sequence[Sequence[str]],
    previous: Sequence[IncidentSummary],
    graph: RegionGraph,
) -> dict[int, IncidentSummary]:
    """Greedy one-to-one match on shared stable nodes, largest overlap first."""
    pairs: list[tuple[int, str, int, IncidentSummary]] = []
    for index, members in enumerate(components):
        stable = {n for n in members if graph.nodes[n].kind in STABLE_KINDS}
        for prior in previous:
            overlap = len(stable & set(prior.node_ids))
            if overlap >= MIN_INCIDENT_OVERLAP:
                pairs.append((overlap, prior.incident_id, index, prior))
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))
    claims: dict[int, IncidentSummary] = {}
    taken: set[str] = set()
    for _, incident_id, index, prior in pairs:
        if index in claims or incident_id in taken:
            continue
        claims[index] = prior
        taken.add(incident_id)
    return claims


def _root_kind(graph: RegionGraph, members: Sequence[str]) -> NodeKind:
    kinds = {graph.nodes[n].kind for n in members}
    for kind in ROOT_PRIORITY:
        if kind in kinds:
            return kind
    return graph.nodes[members[0]].kind


# --- helpers ----------------------------------------------------------------


def _cell(graph: RegionGraph, cell: str) -> str:
    return graph.add_node(f"cell:{cell}", "cell")


def _parent(grid_id: str) -> str:
    if h3.get_resolution(grid_id) <= CELL_RESOLUTION:
        return grid_id
    return h3.cell_to_parent(grid_id, CELL_RESOLUTION)


def _value(
    value: float | str | bool,
    unit: str | None,
    source_id: str,
    provenance: ProvenanceClass,
    observed_at: datetime | None = None,
) -> GroundedValue:
    return GroundedValue(
        value=value,
        unit=unit,
        source_id=source_id,
        provenance_class=provenance,
        observed_at=observed_at,
    )


def _digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]
