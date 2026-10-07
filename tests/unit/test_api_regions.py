"""Snapshot-backed API routes (LLD APAC 12.1) over a real in-north cycle.

One live cycle over the replay fixtures writes the snapshot, plumes and raw
history; the routes then read only that. Singapore and NSW have no snapshot,
so every route must say ``not_configured`` for them rather than serve the
in-north fixtures under another region's name.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from aeropulse_api.routers.plume import PLUME_LABEL
from aeropulse_auth import Role
from aeropulse_common.settings import Settings
from aeropulse_contracts import RegionSnapshot
from aeropulse_storage import build_storage
from fastapi.testclient import TestClient
from region_cycle import auth, client_for, platform_for


@pytest.fixture
def client(cycled: tuple[Path, RegionSnapshot]) -> Iterator[TestClient]:
    yield client_for(platform_for(cycled[0]))


def test_regions_list_every_pack_with_its_snapshot_state(
    client: TestClient, cycled: tuple[Path, RegionSnapshot]
) -> None:
    body = client.get("/api/v1/regions", headers=auth()).json()
    by_id = {r["region_id"]: r for r in body["items"]}
    assert set(by_id) == {"in-north", "sg-singapore", "au-nsw"}
    assert body["total"] == 3 and body["offset"] == 0

    north = by_id["in-north"]
    assert north["snapshot"]["cycle_id"] == cycled[1].cycle_id
    assert north["field_status"] == []
    assert "CPCB" in north["aqi_standard"]["name"]
    assert {m["family"] for m in north["served_models"]} >= {"pm25_forecast"}

    singapore = by_id["sg-singapore"]
    assert singapore["snapshot"] is None and singapore["served_models"] is None
    assert singapore["field_status"][0]["field"] == "snapshot"

    detail = client.get("/api/v1/regions/in-north", headers=auth()).json()
    assert {s["source_id"] for s in detail["sources"]} and all(
        "secret_ref" in s for s in detail["sources"]
    )
    assert client.get("/api/v1/regions/xx-nowhere", headers=auth()).status_code == 404


def test_incidents_list_detail_and_plumes(
    client: TestClient, cycled: tuple[Path, RegionSnapshot]
) -> None:
    snapshot = cycled[1]
    listed = client.get("/api/v1/incidents?region_id=in-north", headers=auth()).json()
    assert listed["total"] == len(snapshot.incidents) >= 1
    first = listed["items"][0]
    assert "nodes" not in first and first["node_count"] == len(snapshot.incidents[0].node_ids)
    assert listed["data_source"]["cycle_id"] == snapshot.cycle_id

    incident_id = first["incident_id"]
    detail = client.get(f"/api/v1/incidents/{incident_id}", headers=auth()).json()
    assert detail["nodes"] and detail["edges"]
    plume_nodes = {n.split(":", 2)[2] for n in detail["node_ids"] if n.startswith("plume:")}

    plumes = client.get(f"/api/v1/incidents/{incident_id}/plume", headers=auth()).json()
    assert {p["plume_id"] for p in plumes["items"]} == plume_nodes
    assert all(p["provenance_class"] == "simulated" for p in plumes["items"])

    other = client.get("/api/v1/incidents?region_id=sg-singapore", headers=auth()).json()
    assert other["status"] == "not_configured" and other["items"] == []
    assert client.get("/api/v1/incidents/inc_missing", headers=auth()).status_code == 404


def test_plume_map_and_document_are_labelled_experimental(
    client: TestClient, cycled: tuple[Path, RegionSnapshot]
) -> None:
    forward = client.get("/api/v1/map/plume?region_id=in-north", headers=auth()).json()
    assert forward["features"] and forward["label"] == PLUME_LABEL
    for feature in forward["features"]:
        props = feature["properties"]
        assert props["experimental"] is True and props["provenance_class"] == "simulated"
        assert props["band"] in {"p50", "p90"} and props["model_version"]
    backward = client.get(
        "/api/v1/map/plume?region_id=in-north&direction=backward", headers=auth()
    ).json()
    assert {f["properties"]["direction"] for f in backward["features"]} == {"backward"}

    plume_id = cycled[1].plumes[0].plume_id
    document = client.get(f"/api/v1/plume/{plume_id}", headers=auth()).json()
    assert document["plume_id"] == plume_id and document["label"] == PLUME_LABEL
    assert client.get("/api/v1/plume/plm_missing", headers=auth()).status_code == 404

    empty = client.get("/api/v1/map/plume?region_id=au-nsw", headers=auth()).json()
    assert empty["features"] == [] and empty["status"] == "not_configured"


def test_plume_list_carries_every_horizon_for_the_region(
    client: TestClient, cycled: tuple[Path, RegionSnapshot]
) -> None:
    listed = client.get("/api/v1/plumes?region_id=in-north", headers=auth()).json()
    assert listed["total"] == len(cycled[1].plumes) and listed["offset"] == 0
    assert {p["plume_id"] for p in listed["items"]} == {p.plume_id for p in cycled[1].plumes}
    for plume in listed["items"]:
        assert plume["label"] == PLUME_LABEL and plume["provenance_class"] == "simulated"
        assert plume["horizons"] and plume["experimental"] is True
    backward = client.get(
        "/api/v1/plumes?region_id=in-north&direction=backward&limit=1", headers=auth()
    ).json()
    assert len(backward["items"]) == 1 and backward["items"][0]["direction"] == "backward"
    empty = client.get("/api/v1/plumes?region_id=sg-singapore", headers=auth()).json()
    assert empty["items"] == [] and empty["total"] == 0 and empty["status"] == "not_configured"


def test_source_likelihood_is_served_as_an_uncalibrated_ranking(
    client: TestClient, cycled: tuple[Path, RegionSnapshot]
) -> None:
    body = client.get("/api/v1/map/source-likelihood?region_id=in-north", headers=auth()).json()
    assert body["total"] == len(cycled[1].source_likelihood) > 0
    assert body["data_source"]["cycle_id"] == cycled[1].cycle_id
    for item in body["items"]:
        assert item["provenance_class"] == "heuristic" and item["calibrated"] is False
        assert item["ranking"] and item["evidence"]
    empty = client.get("/api/v1/map/source-likelihood?region_id=au-nsw", headers=auth()).json()
    assert empty["items"] == [] and empty["status"] == "not_configured"


def test_what_if_is_simulated_on_the_cycle_wind_and_never_stored(
    client: TestClient, cycled: tuple[Path, RegionSnapshot]
) -> None:
    root, snapshot = cycled
    body = {"region_id": "in-north", "lat": 30.12, "lon": 75.71}
    headers = auth(Role.OPERATOR)
    first = client.post("/api/v1/plume/what-if", headers=headers, json=body)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["stored"] is False and result["provenance_class"] == "simulated"
    assert result["origin"]["kind"] == "operator" and result["label"] == PLUME_LABEL
    assert result["data_source"]["cycle_id"] == snapshot.cycle_id
    assert build_storage(Settings(data_dir=root)).plumes.get("in-north", result["plume_id"]) is None

    again = client.post("/api/v1/plume/what-if", headers=headers, json=body).json()
    assert again["plume_id"] == result["plume_id"], "a repeated click is served from the cache"

    viewer = client.post("/api/v1/plume/what-if", headers=auth(Role.VIEWER), json=body)
    assert viewer.status_code == 403
    outside = client.post(
        "/api/v1/plume/what-if", headers=headers, json={**body, "lat": 1.35, "lon": 103.8}
    )
    assert outside.status_code == 422


def test_map_and_events_say_where_their_data_came_from(
    client: TestClient, cycled: tuple[Path, RegionSnapshot]
) -> None:
    snapshot = cycled[1]
    aq = client.get("/api/v1/map/air-quality?region_id=in-north", headers=auth()).json()
    assert aq["data_source"]["kind"] == "snapshot"
    assert len(aq["features"]) == sum(c.pm25 is not None for c in snapshot.cells)

    hazard = client.get("/api/v1/map/hazard?region_id=in-north", headers=auth()).json()
    assert hazard["data_source"]["cycle_id"] == snapshot.cycle_id
    assert all("calibrated" in f["properties"] for f in hazard["features"])

    events = client.get("/api/v1/events?region_id=in-north", headers=auth()).json()
    assert events["total"] == len(snapshot.events)
    assert events["data_source"]["kind"] == "snapshot"

    for path in ("air-quality", "fire", "hazard", "industry"):
        empty = client.get(f"/api/v1/map/{path}?region_id=sg-singapore", headers=auth()).json()
        assert empty["features"] == [], path
        assert empty["data_source"]["kind"] == "not_configured", path
        assert empty["field_status"], path
    other = client.get("/api/v1/events?region_id=sg-singapore", headers=auth()).json()
    assert other["items"] == [] and other["data_source"]["kind"] == "not_configured"

    risk = client.get("/api/v1/risk/areas?region_id=sg-singapore", headers=auth()).json()
    assert risk["items"] == [] and risk["data_source"]["kind"] == "not_configured"


def test_models_report_what_the_cycle_served(
    client: TestClient, cycled: tuple[Path, RegionSnapshot]
) -> None:
    served = client.get("/api/v1/models?region_id=in-north", headers=auth()).json()
    assert {m["family"] for m in served["items"]} == {m.family for m in cycled[1].served_models}
    assert all(m["verified_by_cycle"] for m in served["items"])

    configured = client.get("/api/v1/models?region_id=sg-singapore", headers=auth()).json()
    assert configured["data_source"]["kind"] == "model_serving.yaml"
    assert all(m["verified_by_cycle"] is False for m in configured["items"])
    assert configured["field_status"]


def test_ml_evaluation_reads_eval_reports_for_the_region(tmp_path: Path) -> None:
    platform = platform_for(tmp_path)
    client = client_for(platform)
    empty = client.get("/api/v1/ml/evaluation?region_id=in-north", headers=auth()).json()
    assert empty["items"] == [] and empty["field_status"]

    def row(region: str, metric: str, value: float, passed: bool) -> dict[str, object]:
        return {
            "run_id": "run_1",
            "family": "pm25_forecast",
            "model_version": "lgbm-1",
            "region_id": region,
            "strategy": "time",
            "group": "fold_0",
            "subject": "model",
            "metric": metric,
            "value": value,
            "passed": passed,
        }

    rows = [row("all", "mae", 11.5, True), row("in-north", "mae", 12.25, True)]
    rows.append(row("sg-singapore", "mae", 30.0, False))
    platform.storage.analytics.load("eval.reports", rows, batch_id="eval_run_1")

    body = client.get("/api/v1/ml/evaluation?region_id=in-north", headers=auth()).json()
    assert body["total"] == 1 and body["field_status"] == []
    metrics = body["items"][0]["metrics"]
    assert sorted(m["value"] for m in metrics) == [11.5, 12.25]
    assert {m["region_id"] for m in metrics} == {"all", "in-north"}


def test_models_registry_lists_baselines_without_writing(tmp_path: Path) -> None:
    client = client_for(platform_for(tmp_path))
    body = client.get("/api/v1/models/registry", headers=auth()).json()
    assert any(item["runtime_role"] == "PRIMARY_BASELINE" for item in body["items"])
    assert body["total"] == len(body["items"])
    assert not list(tmp_path.rglob("*.json")), "a GET never syncs baselines to disk"


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        ("http://localhost:5173", True),
        ("https://aeropulse-preview-12.netlify.app", True),
        ("https://evil.example.com", False),
        ("https://netlify.app.evil.example.com", False),
    ],
)
def test_cors_follows_settings_only(tmp_path: Path, origin: str, allowed: bool) -> None:
    client = client_for(platform_for(tmp_path))
    response = client.options(
        "/api/v1/regions",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    assert (response.headers.get("access-control-allow-origin") == origin) is allowed
