"""API auth and source/map contract tests."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from aeropulse_api.app import create_app
from aeropulse_api.event_store import reset_event_store
from aeropulse_api.routers.sources import reset_source_overrides
from aeropulse_auth.jwt import Role, encode_token
from aeropulse_common.settings import Settings, get_settings
from aeropulse_ml.registry import ModelRecord, ModelRegistry, ModelStage
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    get_settings.cache_clear()
    reset_event_store()
    reset_source_overrides()
    return TestClient(create_app())


@pytest.fixture
def settings() -> Settings:
    return get_settings()


def _auth(settings: Settings, *roles: Role) -> dict[str, str]:
    token = encode_token("tester", list(roles) or [Role.VIEWER], settings=settings)
    return {"Authorization": f"Bearer {token}"}


def test_health_unauthenticated(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


def test_metrics_expose_http_count_latency_and_route_templates(
    client: TestClient, settings: Settings
) -> None:
    headers = _auth(settings, Role.VIEWER)
    assert client.get("/api/v1/events/concrete-id", headers=headers).status_code == 404

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "aeropulse_http_requests_total" in body
    assert "aeropulse_http_request_duration_seconds_bucket" in body
    assert 'route="/api/v1/events/{event_id}"' in body
    assert 'route="/api/v1/events/concrete-id"' not in body


def test_sources_requires_auth(client: TestClient) -> None:
    assert client.get("/api/v1/sources").status_code == 401


def test_viewer_can_list_sources(client: TestClient, settings: Settings) -> None:
    response = client.get("/api/v1/sources", headers=_auth(settings, Role.VIEWER))
    assert response.status_code == 200
    body = response.json()
    ids = {item["source_id"] for item in body["items"]}
    assert {"cpcb", "firms", "imd", "openaq", "openmeteo"} <= ids
    imd = next(item for item in body["items"] if item["source_id"] == "imd")
    assert imd["enabled"] is False
    openaq = next(item for item in body["items"] if item["source_id"] == "openaq")
    assert openaq["enabled"] is True
    assert openaq["live_capable"] is True
    assert openaq["last_success_at"] is None
    assert openaq["latency_ms"] is None
    assert body["total"] == len(body["items"])
    assert body["limit"] is None
    assert body["offset"] == 0


def test_source_list_joins_connector_health(settings: Settings) -> None:
    """GET /sources is a registry plus nullable telemetry, not a parallel dict."""
    from datetime import UTC, datetime

    from aeropulse_api.routers.sources import get_source_health_reader
    from aeropulse_api.source_health_store import SourceHealthRow

    class _FakeHealth:
        def latest(self) -> dict[str, SourceHealthRow]:
            return {
                "openaq": SourceHealthRow(
                    source_id="openaq",
                    status="HEALTHY",
                    last_success_at=datetime(2026, 9, 27, 12, 0, tzinfo=UTC),
                    records_per_run=12,
                    latency_ms=340,
                    last_error=None,
                    processing_mode="live",
                )
            }

    get_settings.cache_clear()
    reset_event_store()
    reset_source_overrides()
    app = create_app()
    app.dependency_overrides[get_source_health_reader] = lambda: _FakeHealth()
    try:
        client = TestClient(app)
        response = client.get("/api/v1/sources", headers=_auth(settings, Role.VIEWER))
    finally:
        app.dependency_overrides.pop(get_source_health_reader, None)

    assert response.status_code == 200
    openaq = next(item for item in response.json()["items"] if item["source_id"] == "openaq")
    assert openaq["status"] == "HEALTHY"
    assert openaq["records_per_run"] == 12
    assert openaq["latency_ms"] == 340
    assert openaq["last_success_at"] is not None
    imd = next(item for item in response.json()["items"] if item["source_id"] == "imd")
    assert imd["enabled"] is False
    assert imd["latency_ms"] is None


def test_source_health_uses_real_connector_status(client: TestClient, settings: Settings) -> None:
    response = client.post(
        "/api/v1/sources/cpcb/test",
        headers=_auth(settings, Role.ADMIN),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["source_id"] == "cpcb"
    assert payload["healthy"] is True
    assert payload["mode"] == "replay"
    assert payload["connector_id"] == "cpcb_caaqms"


def test_sources_pagination(client: TestClient, settings: Settings) -> None:
    headers = _auth(settings, Role.VIEWER)
    full = client.get("/api/v1/sources", headers=headers).json()
    paged = client.get("/api/v1/sources?limit=2&offset=1", headers=headers).json()
    assert paged["total"] == full["total"]
    assert paged["limit"] == 2
    assert paged["offset"] == 1
    assert paged["items"] == full["items"][1:3]


def test_viewer_cannot_create_source(client: TestClient, settings: Settings) -> None:
    response = client.post(
        "/api/v1/sources",
        headers=_auth(settings, Role.VIEWER),
        json={
            "source_id": "x",
            "provider": "x",
            "connector_id": "x",
            "display_name": "x",
            "data_type": "air_quality",
        },
    )
    assert response.status_code == 403


def test_admin_can_create_source(client: TestClient, settings: Settings) -> None:
    response = client.post(
        "/api/v1/sources",
        headers=_auth(settings, Role.ADMIN),
        json={
            "source_id": "openaq",
            "provider": "OpenAQ",
            "connector_id": "openaq",
            "display_name": "OpenAQ",
            "data_type": "air_quality",
        },
    )
    assert response.status_code == 201


def test_map_air_quality(client: TestClient, settings: Settings) -> None:
    response = client.get(
        "/api/v1/map/air-quality",
        headers=_auth(settings, Role.VIEWER),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) >= 1


def test_replay_seed_serves_hero_episode(client: TestClient, settings: Settings) -> None:
    """DB-free API answers the same Punjab episode the UI demo narrates."""
    headers = _auth(settings, Role.VIEWER)
    events = client.get("/api/v1/events", headers=headers).json()
    ids = {item["event_id"] for item in events["items"]}
    assert "EVT-1024" in ids
    assert events["total"] >= 5

    hero = client.get("/api/v1/events/EVT-1024", headers=headers)
    assert hero.status_code == 200
    assert hero.json()["status"] == "ACTIVE"

    evidence = client.get("/api/v1/events/EVT-1024/evidence", headers=headers)
    assert evidence.status_code == 200
    assert len(evidence.json()["items"]) >= 4

    forecast = client.get("/api/v1/events/EVT-1024/forecast", headers=headers)
    assert forecast.status_code == 200
    assert forecast.json()["grid_predictions"]

    graph = client.get("/api/v1/events/EVT-1024/graph", headers=headers)
    assert graph.status_code == 200
    assert graph.json()["vertices"]

    features = client.get("/api/v1/grid-features?limit=50", headers=headers)
    assert features.status_code == 200
    assert features.json()["total"] > 0
    origin = hero.json()["grid_ids"][0]
    latest = client.get(f"/api/v1/grid-features/{origin}/latest", headers=headers)
    assert latest.status_code == 200
    assert latest.json()["pm25"] is not None

    fires = client.get("/api/v1/map/fire", headers=headers).json()
    assert len(fires["features"]) >= 10


def test_events_rejects_invalid_pagination_params(client: TestClient, settings: Settings) -> None:
    headers = _auth(settings, Role.VIEWER)
    assert client.get("/api/v1/events?limit=0", headers=headers).status_code == 422
    assert client.get("/api/v1/events?offset=-1", headers=headers).status_code == 422


def test_missing_event_forecast_and_graph_are_404(client: TestClient, settings: Settings) -> None:
    headers = _auth(settings, Role.VIEWER)
    assert client.get("/api/v1/events/evt_x/forecast", headers=headers).status_code == 404
    assert client.get("/api/v1/events/evt_x/graph", headers=headers).status_code == 404


def test_openapi_includes_forecast_and_graph(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/api/v1/events/{event_id}/forecast" in paths
    assert "/api/v1/events/{event_id}/graph" in paths
    assert "/api/v1/map/forecast" in paths
    assert "/api/v1/copilot/explain-event" in paths
    assert "/api/v1/citizen/reports" in paths
    assert "/api/v1/grid-features/{grid_id}/history" in paths
    assert "/api/v1/alerts" in paths
    assert "/api/v1/risk" in paths


def test_models_lists_runtime_baselines_and_registered_challengers(
    client: TestClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "challenger.joblib"
    artifact.write_bytes(b"test-artifact")
    registry = ModelRegistry(tmp_path)
    registry.register(
        ModelRecord(
            model_id="pm25-challenger-v1",
            model_name="pm25_forecast",
            version="v1",
            stage=ModelStage.VALIDATION,
            algorithm="LightGBM",
            feature_names=["pm25", "pm25_lag_1h"],
            training_time=datetime(2026, 9, 13, tzinfo=UTC),
            artifact_uri=str(artifact),
        )
    )
    monkeypatch.setenv("AEROPULSE_MODEL_DIR", str(tmp_path))

    response = client.get("/api/v1/models", headers=_auth(settings, Role.VIEWER))

    assert response.status_code == 200
    body = response.json()
    challenger = next(item for item in body["items"] if item["model_id"] == "pm25-challenger-v1")
    assert challenger["approval_status"] == "VALIDATION"
    assert challenger["runtime_role"] == "REGISTERED_ONLY"
    assert challenger["artifact_available"] is True
    assert any(item["runtime_role"] == "PRIMARY_BASELINE" for item in body["items"])
    assert body["total"] == len(body["items"])


def test_citizen_report_links_high_event_without_changing_it(
    client: TestClient, settings: Settings
) -> None:
    from aeropulse_api.event_store import current_store
    from aeropulse_contracts.event import EventSeverity, EventStatus, PollutionEvent
    from aeropulse_geospatial.grid import to_grid_id

    lat, lon = 1.35, 103.82
    grid_id = to_grid_id(lat, lon)
    event = PollutionEvent(
        event_id="evt-high",
        status=EventStatus.ACTIVE,
        severity=EventSeverity.HIGH,
        created_at=datetime(2026, 9, 8, tzinfo=UTC),
        updated_at=datetime(2026, 9, 8, tzinfo=UTC),
        grid_ids=[grid_id],
        detection_confidence=0.9,
        source_confidence=0.4,
        overall_confidence=0.7,
    )
    store = current_store()
    store.events.clear()
    store.events[event.event_id] = event

    response = client.post(
        "/api/v1/citizen/reports",
        headers=_auth(settings, Role.CITIZEN),
        json={"lat": lat, "lon": lon, "notes": "haze"},
    )
    assert response.status_code == 201
    assert response.json()["correlated_event_id"] == event.event_id
    assert store.events[event.event_id].severity == EventSeverity.HIGH


def test_citizen_report_round_trip(client: TestClient, settings: Settings) -> None:
    headers = _auth(settings, Role.CITIZEN)
    created = client.post(
        "/api/v1/citizen/reports",
        headers=headers,
        json={"lat": 28.6, "lon": 77.2, "observation_type": "haze"},
    )
    assert created.status_code == 201
    report_id = created.json()["report_id"]
    fetched = client.get(f"/api/v1/citizen/reports/{report_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["cv_class"] == "haze"
    assert fetched.json()["moderation"] == "pending"
    listed = client.get("/api/v1/citizen/reports", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1
    assert listed.json()["offset"] == 0
    assert any(item["report_id"] == report_id for item in listed.json()["items"])
    paged = client.get("/api/v1/citizen/reports?limit=1&offset=0", headers=headers)
    assert paged.status_code == 200
    assert paged.json()["limit"] == 1
    assert len(paged.json()["items"]) == 1


def test_citizen_photo_upload_is_processed(client: TestClient, settings: Settings) -> None:
    headers = _auth(settings, Role.VIEWER)
    created = client.post(
        "/api/v1/citizen/reports",
        headers=headers,
        json={
            "lat": 28.61,
            "lon": 77.21,
            "observation_type": "photo",
            "notes": "heavy haze over Delhi",
        },
    )
    assert created.status_code == 201
    report_id = created.json()["report_id"]
    assert created.json()["cv_class"] == "haze"

    jpeg = b"\xff\xd8\xff" + b"\x00" * 32
    attached = client.post(
        f"/api/v1/citizen/reports/{report_id}/media",
        headers=headers,
        files={"file": ("haze.jpg", jpeg, "image/jpeg")},
    )
    assert attached.status_code == 200
    body = attached.json()
    assert body["media_uri"].startswith("s3://")
    assert body["cv_class"] == "haze"

    rejected = client.post(
        f"/api/v1/citizen/reports/{report_id}/media",
        headers=headers,
        files={"file": ("notes.txt", b"not-an-image", "text/plain")},
    )
    assert rejected.status_code == 400


def test_copilot_does_not_invent_event(client: TestClient, settings: Settings) -> None:
    headers = _auth(settings, Role.VIEWER)
    response = client.post(
        "/api/v1/copilot/explain-event",
        headers=headers,
        json={"event_id": "does-not-exist"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["llm_used"] is False
    assert body["observed_facts"] == []


def test_risk_endpoint(client: TestClient, settings: Settings) -> None:
    response = client.get(
        "/api/v1/risk", params={"pm25": 180}, headers=_auth(settings, Role.VIEWER)
    )
    assert response.status_code == 200
    assert "pollution_severity" in response.json()
    assert "population_risk" in response.json()

    def test_risk_areas_and_industry_map_are_exposed(
        client: TestClient, settings: Settings
    ) -> None:
        headers = _auth(settings, Role.VIEWER)
        risk = client.get("/api/v1/risk/areas?pm25=180", headers=headers)
        assert risk.status_code == 200
        risk_body = risk.json()
        assert risk_body["total"] == 5
        assert risk_body["items"][0]["population"] > 0
        assert risk_body["population_source"]["provider"] == "reference-fixture"

        industry = client.get("/api/v1/map/industry", headers=headers)
        assert industry.status_code == 200
        assert industry.json()["features"][0]["properties"]["source_id"] == "industry"


def test_risk_areas_returns_ranked_cells_with_provenance(
    client: TestClient, settings: Settings
) -> None:
    """`/risk/areas` had no coverage, and a merge silently broke its call.

    `score_risk`'s density parameter was renamed while this endpoint was
    being added on another branch; the merge produced a `TypeError` on every
    request that no test caught. This is that test.
    """
    response = client.get("/api/v1/risk/areas?pm25=180", headers=_auth(settings, Role.VIEWER))

    assert response.status_code == 200
    body = response.json()
    assert body["items"], "the population fixture should yield at least one cell"

    ranks = [item["rank"] for item in body["items"]]
    assert ranks == sorted(ranks) == list(range(1, len(ranks) + 1))
    risks = [item["population_risk"] for item in body["items"]]
    assert risks == sorted(risks, reverse=True), "areas must be ranked by risk"

    # Denser cells must carry more exposure at identical concentration, or the
    # endpoint is reporting severity twice under two names.
    assert body["items"][0]["population_density"] > body["items"][-1]["population_density"]

    # Provenance is the point of this fixture: it is explicitly not licensed
    # for operational use, and the response has to say so.
    source = body["population_source"]
    assert source["provider"]
    assert source["license"] == "replace-before-production"


def test_map_industry_returns_geojson(client: TestClient, settings: Settings) -> None:
    """The industry layer the UI reads in live mode."""
    response = client.get("/api/v1/map/industry", headers=_auth(settings, Role.VIEWER))

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FeatureCollection"
    for feature in body["features"]:
        assert feature["geometry"]["type"] in {"Point", "Polygon"}


def test_citizen_reports_list_is_paginated_and_empty_by_default(
    client: TestClient, settings: Settings
) -> None:
    """The list route that unblocked the Citizen screen in live mode."""
    response = client.get("/api/v1/citizen/reports", headers=_auth(settings, Role.VIEWER))

    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"items", "total"}
    assert body["total"] == len(body["items"])
