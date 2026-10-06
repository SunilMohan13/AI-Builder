"""Hazard and peak prediction endpoints (integration plan Phase 6).

The plan's binding constraint for this phase is a negative one: *a shadow
model's output is never returned as a served prediction*. Until promotion
these routes return the deterministic baseline, correctly labelled. These
tests assert the labelling is present and truthful, because a hazard number
shown without it is the most consequential thing this API could get wrong.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from aeropulse_api.app import create_app
from aeropulse_api.grid_store import get_grid_reader
from aeropulse_api.hazard_store import baseline_hazard, baseline_peak
from aeropulse_auth.jwt import Role, encode_token
from aeropulse_common.settings import Settings, get_settings
from aeropulse_contracts.feature import GridFeature
from aeropulse_contracts.hazard import HAZARD_THRESHOLD_UGM3
from fastapi.testclient import TestClient

HOUR = datetime(2026, 9, 8, 12, tzinfo=UTC)

HAZARDOUS = GridFeature(
    grid_id="8842492739fffff",
    timestamp=HOUR,
    center_lat=28.6,
    center_lon=77.2,
    pm25=180.0,
    pm25_roll_max_24h=220.0,
)
CLEAN = GridFeature(
    grid_id="8842492731fffff",
    timestamp=HOUR,
    center_lat=29.1,
    center_lon=76.5,
    pm25=20.0,
)
UNOBSERVED = GridFeature(
    grid_id="8842492733fffff",
    timestamp=HOUR,
    center_lat=30.1,
    center_lon=75.5,
    pm25=None,
)


class _StubReader:
    """Serves a fixed set of persisted features."""

    def __init__(self, features: list[GridFeature]) -> None:
        self.features = features

    def list_features(self, grid_id, start, end, limit, offset):  # type: ignore[no-untyped-def]
        items = [f for f in self.features if grid_id is None or f.grid_id == grid_id]
        return items[offset : offset + limit], len(items)

    def latest_feature(self, grid_id):  # type: ignore[no-untyped-def]
        return next((f for f in self.features if f.grid_id == grid_id), None)

    def list_predictions(self, *args):  # type: ignore[no-untyped-def]
        return [], 0

    def latest_prediction(self, *args):  # type: ignore[no-untyped-def]
        return None


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_grid_reader] = lambda: _StubReader([HAZARDOUS, CLEAN, UNOBSERVED])
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def settings() -> Settings:
    return get_settings()


def _auth(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {encode_token('tester', [Role.VIEWER], settings=settings)}"}


# --- The labelling that keeps the numbers honest --------------------------


def test_hazard_items_declare_degraded_and_uncalibrated(
    client: TestClient, settings: Settings
) -> None:
    """A persistence rule must never look like a calibrated model output."""
    body = client.get("/api/v1/grid-hazard", headers=_auth(settings)).json()

    assert body["items"]
    for item in body["items"]:
        assert item["degraded"] is True
        assert item["calibrated"] is False
        assert item["model_version"] == "persistence-hazard-0.1"
    assert body["provenance"]["degraded"] is True
    assert "no PRODUCTION pm25_hazard_24h" in body["provenance"]["reason"]


def test_map_hazard_carries_the_labels_into_geojson_properties(
    client: TestClient, settings: Settings
) -> None:
    """The map layer is where a number is most likely to be read uncritically."""
    body = client.get("/api/v1/map/hazard", headers=_auth(settings)).json()

    assert body["type"] == "FeatureCollection"
    assert body["features"]
    for feature in body["features"]:
        assert feature["properties"]["degraded"] is True
        assert feature["properties"]["calibrated"] is False
    assert body["provenance"]["model_version"] == "persistence-hazard-0.1"


def test_a_shadow_model_does_not_change_what_is_served(
    client: TestClient, settings: Settings, tmp_path, monkeypatch
) -> None:
    """Registering a challenger at SHADOW must not alter any response."""
    from aeropulse_ml.registry import ModelRecord, ModelRegistry, ModelStage

    registry = ModelRegistry(tmp_path / "models")
    registry.register(
        ModelRecord(
            model_id="hazard-shadow",
            model_name="pm25_hazard_24h",
            version="hazard-shadow",
            stage=ModelStage.SHADOW,
            artifact_uri=str(tmp_path / "models" / "hazard-shadow.joblib"),
            training_time=datetime(2026, 9, 8, tzinfo=UTC),
        )
    )
    monkeypatch.setenv("AEROPULSE_MODEL_DIR", str(tmp_path / "models"))

    body = client.get("/api/v1/grid-hazard", headers=_auth(settings)).json()

    assert body["provenance"]["model_version"] == "persistence-hazard-0.1"
    assert "promoted_champion" not in body["provenance"]
    assert all(item["degraded"] for item in body["items"])


# --- Behaviour ------------------------------------------------------------


def test_unobserved_cells_are_omitted_rather_than_scored_zero(
    client: TestClient, settings: Settings
) -> None:
    """ "No data" and "no hazard" must not render identically on a map."""
    body = client.get("/api/v1/grid-hazard", headers=_auth(settings)).json()

    returned = {item["grid_id"] for item in body["items"]}
    assert UNOBSERVED.grid_id not in returned
    assert returned == {HAZARDOUS.grid_id, CLEAN.grid_id}


def test_latest_hazard_for_an_unobserved_cell_is_404(
    client: TestClient, settings: Settings
) -> None:
    """Undefined is reported as undefined, not as a zero score."""
    response = client.get(
        f"/api/v1/grid-hazard/{UNOBSERVED.grid_id}/latest", headers=_auth(settings)
    )

    assert response.status_code == 404
    assert "no observed PM2.5" in response.json()["detail"]


def test_peak_baseline_uses_the_trailing_maximum(client: TestClient, settings: Settings) -> None:
    """For a peak target, the recent maximum beats the current value."""
    body = client.get(
        f"/api/v1/grid-peak/{HAZARDOUS.grid_id}/latest", headers=_auth(settings)
    ).json()

    assert body["peak_pm25"] == pytest.approx(220.0)
    assert body["observed_pm25"] == pytest.approx(180.0)
    assert body["exceeds_threshold"] is True
    assert body["degraded"] is True


def test_list_endpoints_follow_the_pagination_convention(
    client: TestClient, settings: Settings
) -> None:
    """items/total/limit/offset, like every other collection route."""
    body = client.get("/api/v1/grid-hazard?limit=1&offset=0", headers=_auth(settings)).json()

    assert set(body) >= {"items", "total", "limit", "offset"}
    assert body["limit"] == 1
    assert len(body["items"]) <= 1


def test_hazard_endpoints_require_authentication(client: TestClient) -> None:
    for path in ("/api/v1/grid-hazard", "/api/v1/grid-peak", "/api/v1/map/hazard"):
        assert client.get(path).status_code == 401


# --- The scoring rule itself ---------------------------------------------


def test_baseline_hazard_is_bounded_and_monotonic() -> None:
    """The ramp must stay on [0, 1] and never invert."""
    scores = []
    for value in (0.0, 30.0, 75.0, HAZARD_THRESHOLD_UGM3, 500.0):
        cell = baseline_hazard(GridFeature(**{**CLEAN.model_dump(), "pm25": value}))
        assert cell is not None
        assert 0.0 <= cell.hazard_score <= 1.0
        scores.append(cell.hazard_score)

    assert scores == sorted(scores)
    assert scores[0] == 0.0
    assert scores[-1] == 1.0


def test_baseline_returns_none_without_an_observation() -> None:
    """A null input must produce no answer, not a zero one."""
    assert baseline_hazard(UNOBSERVED) is None
    assert baseline_peak(UNOBSERVED) is None
