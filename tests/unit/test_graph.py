"""Environmental Intelligence Graph (LLD APAC 10): vocabulary, determinism, incidents."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import get_args

import h3
from aeropulse_contracts import EventSeverity, EventStatus, PollutionEvent
from aeropulse_contracts.graph import EdgeKind, IncidentSummary
from aeropulse_contracts.plume import (
    PlaceArrival,
    Plume,
    PlumeHorizon,
    PlumeOrigin,
    SourceCandidate,
)
from aeropulse_contracts.provenance import ProvenanceClass
from aeropulse_contracts.snapshot import (
    AnomalyFlag,
    CellState,
    CitizenWatchSummary,
    FireCluster,
)
from aeropulse_intelligence.graph import GraphInputs, build_graph, find_incidents

T0 = datetime(2026, 10, 1, 6, tzinfo=UTC)
RID = "in-north"
FIRE_LAT, FIRE_LON = 30.90, 75.80
STATION_LAT, STATION_LON = 30.70, 76.70


def _fire(lat: float = FIRE_LAT, lon: float = FIRE_LON, *, at: datetime = T0) -> FireCluster:
    parent = h3.latlng_to_cell(lat, lon, 6)
    return FireCluster(
        cluster_id=f"{parent}:{at:%Y%m%dT%H%MZ}",
        lat=lat,
        lon=lon,
        detection_count=3,
        frp_total=42.0,
        first_seen=at - timedelta(hours=2),
        last_seen=at,
        parent_cell=parent,
        source_ids=["firms_viirs_snpp"],
    )


def _forward(fire: FireCluster, *, place: str = "ludhiana", t: datetime = T0) -> Plume:
    return Plume(
        plume_id=f"plm_fwd_{fire.cluster_id}",
        region_id=RID,
        cycle_time=t,
        model_version="lagrangian-ens-1.0",
        direction="forward",
        origin=PlumeOrigin(kind="fire_cluster", ref_id=fire.cluster_id, lat=fire.lat, lon=fire.lon),
        release_time=t,
        wind_issued_at=t - timedelta(hours=1),
        horizons=[PlumeHorizon(horizon_hours=6, p50_cells=[], p90_cells=[], weight_remaining=1)],
        arrivals=[
            PlaceArrival(
                place_id=place,
                name=place.title(),
                lat=30.9,
                lon=75.85,
                probability=0.6,
                eta_hours_median=3.0,
                population=1000.0,
            )
        ],
    )


def _anomaly(lat: float = STATION_LAT, lon: float = STATION_LON) -> AnomalyFlag:
    return AnomalyFlag(
        grid_id=h3.latlng_to_cell(lat, lon, 8),
        observed_at=T0,
        observed_pm25=180.0,
        expected_high=90.0,
        score=0.8,
        reason="PM2.5 180 at or above expected high 90",
        method_version="anomaly-rule-1.0",
    )


def _backward(anomaly: AnomalyFlag, fire: FireCluster) -> Plume:
    lat, lon = h3.cell_to_latlng(anomaly.grid_id)
    return Plume(
        plume_id=f"plm_back_{anomaly.grid_id}",
        region_id=RID,
        cycle_time=T0,
        model_version="lagrangian-ens-1.0",
        direction="backward",
        origin=PlumeOrigin(kind="anomaly", ref_id=anomaly.grid_id, lat=lat, lon=lon),
        release_time=T0,
        horizons=[PlumeHorizon(horizon_hours=12, p50_cells=[], p90_cells=[], weight_remaining=1)],
        source_candidates=[
            SourceCandidate(
                fire_cluster_id=fire.cluster_id,
                particle_fraction=0.3,
                distance_km=88.0,
                bearing_deg=275.0,
            )
        ],
    )


def _event(status: EventStatus, lat: float = 28.6, lon: float = 77.2) -> PollutionEvent:
    return PollutionEvent(
        event_id=f"evt_{status.value.lower()}",
        status=status,
        severity=EventSeverity.HIGH,
        created_at=T0,
        updated_at=T0,
        grid_ids=[h3.latlng_to_cell(lat, lon, 8)],
        detection_confidence=0.7,
        source_confidence=0.5,
        forecast_confidence=0.0,
        impact_confidence=0.0,
        overall_confidence=0.6,
        evidence_freshness=1.0,
        sensor_coverage=1.0,
        model_versions=["rules-1.0"],
    )


def test_edges_use_the_association_vocabulary_and_every_value_is_grounded() -> None:
    fire, anomaly = _fire(), _anomaly()
    station_cell = CellState(
        grid_id=anomaly.grid_id,
        lat=STATION_LAT,
        lon=STATION_LON,
        pm25=180.0,
        pm25_source_id="openaq",
        provenance_class=ProvenanceClass.MEASURED,
    )
    graph = build_graph(
        GraphInputs(
            RID,
            T0,
            fires=[fire],
            anomalies=[anomaly],
            events=[_event(EventStatus.ACTIVE)],
            plumes=[_forward(fire), _backward(anomaly, fire)],
            cells=[station_cell],
        )
    )
    kinds = {e.kind for e in graph.edges.values()}
    assert kinds <= set(get_args(EdgeKind))
    assert "caused" not in get_args(EdgeKind), "edges are associations, never causation"
    assert {"located_in", "emits", "drives", "reaches", "observes", "traced_by"} <= kinds
    assert "on_back_trajectory_of" in kinds
    for edge in graph.edges.values():
        assert edge.src in graph.nodes and edge.dst in graph.nodes
        assert edge.producer
        if edge.kind in {"emits", "drives", "reaches", "traced_by", "on_back_trajectory_of"}:
            assert edge.provenance_class == ProvenanceClass.SIMULATED
    for item in [*graph.nodes.values(), *graph.edges.values()]:
        for value in item.attributes.values():
            assert value.source_id and value.provenance_class
    back = next(e for e in graph.edges.values() if e.kind == "on_back_trajectory_of")
    assert back.attributes["distance_km"].value == 88.0
    assert back.attributes["particle_fraction"].provenance_class == ProvenanceClass.SIMULATED
    observed = next(n for n in graph.nodes.values() if n.kind == "anomaly")
    assert observed.attributes["observed_pm25"].provenance_class == ProvenanceClass.MEASURED
    assert observed.attributes["observed_pm25"].source_id == "openaq"


def test_the_graph_is_deterministic() -> None:
    fire, anomaly = _fire(), _anomaly()
    inputs = GraphInputs(
        RID,
        T0,
        fires=[fire],
        anomalies=[anomaly],
        plumes=[_forward(fire), _backward(anomaly, fire)],
    )
    first, second = build_graph(inputs), build_graph(inputs)
    assert [n.model_dump() for n in first.nodes.values()] == [
        n.model_dump() for n in second.nodes.values()
    ]
    assert list(first.edges) == list(second.edges)
    assert find_incidents(first) == find_incidents(second)


def test_a_fire_whose_plume_reaches_a_place_is_an_incident() -> None:
    fire = _fire()
    graph = build_graph(GraphInputs(RID, T0, fires=[fire], plumes=[_forward(fire)]))
    [incident] = find_incidents(graph)
    assert incident.root_kind == "fire_cluster"
    assert incident.place_ids_reached == ["ludhiana"]
    assert incident.first_seen == incident.last_updated == T0
    assert f"fire_cluster:{RID}:{fire.cluster_id}" in incident.node_ids
    assert any(e.kind == "groups" for e in incident.edges)
    assert any(n.kind == "place" for n in incident.nodes), "the subgraph carries its context"


def test_a_corroborated_report_joins_the_fire_and_the_plume_it_agrees_with() -> None:
    fire = _fire()
    report_cell = h3.latlng_to_cell(30.92, 75.82, 8)
    plume = _forward(fire).model_copy(
        update={
            "horizons": [
                PlumeHorizon(
                    horizon_hours=3, p50_cells=[], p90_cells=[report_cell], weight_remaining=1
                )
            ]
        }
    )
    watch = CitizenWatchSummary(
        report_id="rep1",
        lat_rounded=30.92,
        lon_rounded=75.82,
        visual_class="smoke_plume",
        corroboration="corroborated",
        matched_fire_id=fire.cluster_id,
        observed_at=T0,
    )
    graph = build_graph(GraphInputs(RID, T0, fires=[fire], plumes=[plume], citizen=[watch]))
    node = graph.nodes[f"citizen_report:{RID}:rep1"]
    assert node.attributes["visual_class"].provenance_class == ProvenanceClass.AI_OBSERVATION
    assert node.attributes["corroboration"].provenance_class == ProvenanceClass.HEURISTIC
    kinds = {e.kind: e for e in graph.edges.values() if e.src == node.node_id}
    assert set(kinds) == {"located_in", "consistent_with", "near"}
    assert kinds["consistent_with"].dst == f"plume:{RID}:{plume.plume_id}"
    assert kinds["near"].dst == f"fire_cluster:{RID}:{fire.cluster_id}"
    [incident] = find_incidents(graph)
    assert node.node_id in incident.node_ids, "the report sits in the fire's incident"


def test_quiet_components_are_not_incidents() -> None:
    fire = _fire()
    unreached = _forward(fire).model_copy(update={"arrivals": []})
    graph = build_graph(
        GraphInputs(
            RID,
            T0,
            fires=[fire],
            plumes=[unreached],
            events=[_event(EventStatus.RESOLVED), _event(EventStatus.DETECTED, 29.0, 77.0)],
        )
    )
    assert find_incidents(graph) == []


def test_an_active_event_is_an_incident_on_its_own() -> None:
    graph = build_graph(GraphInputs(RID, T0, events=[_event(EventStatus.CONFIRMED)]))
    [incident] = find_incidents(graph)
    assert incident.root_kind == "pollution_event"
    assert incident.place_ids_reached == []


def test_a_back_trajectory_joins_the_anomaly_and_the_fire() -> None:
    fire, anomaly = _fire(), _anomaly()
    graph = build_graph(
        GraphInputs(
            RID,
            T0,
            fires=[fire],
            anomalies=[anomaly],
            plumes=[_forward(fire), _backward(anomaly, fire)],
        )
    )
    [incident] = find_incidents(graph)
    kinds = {graph.nodes[n].kind for n in incident.node_ids}
    assert {"fire_cluster", "anomaly", "plume"} <= kinds
    assert incident.root_kind == "fire_cluster"


def test_two_fires_reaching_one_city_stay_two_incidents() -> None:
    west, east = _fire(), _fire(31.6, 74.9)
    graph = build_graph(
        GraphInputs(RID, T0, fires=[west, east], plumes=[_forward(west), _forward(east)])
    )
    incidents = find_incidents(graph)
    assert len(incidents) == 2
    assert all(i.place_ids_reached == ["ludhiana"] for i in incidents)


def test_incident_ids_survive_the_next_cycle_when_the_component_overlaps() -> None:
    fire = _fire()
    [first] = find_incidents(
        build_graph(GraphInputs(RID, T0, fires=[fire], plumes=[_forward(fire)]))
    )

    t1 = T0 + timedelta(hours=1)
    same_cell = _fire(FIRE_LAT + 0.001, FIRE_LON, at=t1)
    elsewhere = _fire(31.6, 74.9, at=t1)
    graph = build_graph(
        GraphInputs(
            RID,
            t1,
            fires=[same_cell, elsewhere],
            plumes=[_forward(same_cell, t=t1), _forward(elsewhere, t=t1)],
        )
    )
    incidents = {i.incident_id: i for i in find_incidents(graph, [first])}
    assert first.incident_id in incidents, "the overlapping component keeps the id"
    carried = incidents[first.incident_id]
    assert carried.first_seen == T0 and carried.last_updated == t1
    assert f"fire_cluster:{RID}:{same_cell.cluster_id}" in carried.node_ids
    assert len(incidents) == 2, "the new component gets a new id"


def test_a_previous_incident_is_inherited_by_one_component_only() -> None:
    fire = _fire()
    earlier = IncidentSummary(
        incident_id="inc_previous",
        region_id=RID,
        root_kind="fire_cluster",
        first_seen=T0 - timedelta(hours=3),
        last_updated=T0 - timedelta(hours=1),
        node_ids=[f"cell:{fire.parent_cell}", f"cell:{h3.latlng_to_cell(31.6, 74.9, 6)}"],
    )
    west, east = _fire(), _fire(31.6, 74.9)
    graph = build_graph(
        GraphInputs(RID, T0, fires=[west, east], plumes=[_forward(west), _forward(east)])
    )
    ids = [i.incident_id for i in find_incidents(graph, [earlier])]
    assert ids.count("inc_previous") == 1
    assert len(set(ids)) == 2
    other = find_incidents(
        build_graph(GraphInputs("sg-singapore", T0, fires=[west], plumes=[_forward(west)])),
        [earlier],
    )
    assert other[0].incident_id != "inc_previous", "incidents never cross regions"
