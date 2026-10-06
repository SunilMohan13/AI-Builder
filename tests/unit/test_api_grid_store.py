"""Materialized grid feature/prediction API and Timescale reader tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from aeropulse_api.app import create_app
from aeropulse_api.grid_store import TimescaleGridReader, get_grid_reader
from aeropulse_auth.jwt import Role, encode_token
from aeropulse_common.settings import get_settings
from aeropulse_contracts.feature import GridFeature
from aeropulse_contracts.prediction import GridPrediction
from fastapi.testclient import TestClient

NOW = datetime(2026, 9, 14, 5, 0, tzinfo=UTC)
GRID_ID = "883da11415fffff"


def _feature() -> GridFeature:
    return GridFeature(
        grid_id=GRID_ID,
        timestamp=NOW,
        center_lat=28.628,
        center_lon=77.241,
        pm25=142.3,
        upwind_fire_score=0.4,
        quality_score=0.9,
        source_count=2,
    )


def _prediction() -> GridPrediction:
    return GridPrediction(
        grid_id=GRID_ID,
        timestamp=NOW,
        model_version="baseline-idw-0.1",
        pm25_estimate=140.0,
        prediction_interval_low=125.0,
        prediction_interval_high=155.0,
        confidence=0.8,
    )


class _Cursor:
    def __init__(
        self, responses: list[list[tuple[Any, ...]]], calls: list[tuple[str, Any]]
    ) -> None:
        self.responses = responses
        self.calls = calls
        self.rows: list[tuple[Any, ...]] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: Any) -> None:
        self.calls.append((" ".join(sql.split()), params))
        self.rows = self.responses.pop(0)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class _Connection:
    def __init__(self, responses: list[list[tuple[Any, ...]]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, Any]] = []

    def cursor(self) -> _Cursor:
        return _Cursor(self.responses, self.calls)


def test_timescale_grid_reader_lists_filtered_features_and_predictions() -> None:
    feature_payload = _feature().model_dump(mode="json")
    prediction_row = (NOW, GRID_ID, "baseline-idw-0.1", 140.0, 125.0, 155.0, 0.8)
    connection = _Connection([[(1,)], [(feature_payload,)], [(1,)], [prediction_row]])
    reader = TimescaleGridReader(connection)

    features, feature_total = reader.list_features(GRID_ID, NOW, NOW, 10, 0)
    predictions, prediction_total = reader.list_predictions(
        GRID_ID, "baseline-idw-0.1", NOW, NOW, 10, 0
    )

    assert feature_total == prediction_total == 1
    assert features == [_feature()]
    assert predictions == [_prediction()]
    assert "grid_id = %s AND time >= %s AND time <= %s" in connection.calls[0][0]
    assert "model_version = %s" in connection.calls[2][0]


class _FakeGridReader:
    def list_features(self, grid_id, start, end, limit, offset):
        return ([_feature()], 1)

    def latest_feature(self, grid_id):
        return _feature() if grid_id == GRID_ID else None

    def list_predictions(self, grid_id, model_version, start, end, limit, offset):
        return ([_prediction()], 1)

    def latest_prediction(self, grid_id, model_version):
        return _prediction() if grid_id == GRID_ID else None


def _client() -> tuple[TestClient, dict[str, str]]:
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_grid_reader] = lambda: _FakeGridReader()
    token = encode_token("grid-test", [Role.VIEWER])
    return TestClient(app), {"Authorization": f"Bearer {token}"}


def test_grid_feature_history_returns_relative_hour_series() -> None:
    older = _feature().model_copy(update={"timestamp": NOW - timedelta(hours=3), "pm25": 110.0})
    newer = _feature()

    class _HistoryReader(_FakeGridReader):
        def list_features(self, grid_id, start, end, limit, offset):
            assert grid_id == GRID_ID
            return ([newer, older], 2)

    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_grid_reader] = lambda: _HistoryReader()
    token = encode_token("grid-test", [Role.VIEWER])
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get(f"/api/v1/grid-features/{GRID_ID}/history", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["grid_id"] == GRID_ID
    assert body["total"] == 2
    hours = [item["hour"] for item in body["items"]]
    assert hours == [-3, 0]
    assert body["items"][0]["pm25"] == 110.0
    assert body["items"][1]["pm25"] == 142.3


def test_grid_feature_history_is_empty_when_pm25_is_missing() -> None:
    blank = _feature().model_copy(update={"pm25": None})

    class _EmptyPm(_FakeGridReader):
        def list_features(self, grid_id, start, end, limit, offset):
            return ([blank], 1)

    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_grid_reader] = lambda: _EmptyPm()
    token = encode_token("grid-test", [Role.VIEWER])
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get(f"/api/v1/grid-features/{GRID_ID}/history", headers=headers)
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_grid_endpoints_return_contracts_and_pagination() -> None:
    client, headers = _client()

    features = client.get("/api/v1/grid-features?limit=10", headers=headers)
    latest_feature = client.get(f"/api/v1/grid-features/{GRID_ID}/latest", headers=headers)
    predictions = client.get("/api/v1/grid-predictions?limit=10", headers=headers)
    latest_prediction = client.get(
        f"/api/v1/grid-predictions/{GRID_ID}/latest?model_version=baseline-idw-0.1",
        headers=headers,
    )

    assert features.status_code == latest_feature.status_code == 200
    assert predictions.status_code == latest_prediction.status_code == 200
    assert features.json()["total"] == 1
    assert features.json()["items"][0]["schema_version"] == "grid-features.v1"
    assert latest_feature.json()["grid_id"] == GRID_ID
    assert predictions.json()["items"][0]["schema_version"] == "prediction.v1"
    assert latest_prediction.json()["model_version"] == "baseline-idw-0.1"


def test_grid_endpoints_enforce_auth_and_return_404() -> None:
    client, headers = _client()

    assert client.get("/api/v1/grid-features").status_code == 401
    assert client.get("/api/v1/grid-predictions").status_code == 401
    assert client.get("/api/v1/grid-features/missing/latest", headers=headers).status_code == 404
    assert client.get("/api/v1/grid-predictions/missing/latest", headers=headers).status_code == 404


def test_grid_endpoint_rejects_invalid_pagination() -> None:
    client, headers = _client()

    assert client.get("/api/v1/grid-features?limit=0", headers=headers).status_code == 422
    assert client.get("/api/v1/grid-predictions?offset=-1", headers=headers).status_code == 422


def test_replay_fallback_serves_seeded_feature_when_timescale_empty() -> None:
    from aeropulse_api.demo_seed import seed_replay_episode
    from aeropulse_api.event_store import reset_event_store
    from aeropulse_api.grid_store import InMemoryGridReader, ReplayFallbackGridReader

    class _Empty:
        def list_features(self, *_args: object, **_kwargs: object) -> tuple[list, int]:
            return [], 0

        def latest_feature(self, _grid_id: str) -> None:
            return None

        def list_predictions(self, *_args: object, **_kwargs: object) -> tuple[list, int]:
            return [], 0

        def latest_prediction(self, *_args: object, **_kwargs: object) -> None:
            return None

    reset_event_store()
    seed_replay_episode()
    reader = ReplayFallbackGridReader(_Empty(), InMemoryGridReader())  # type: ignore[arg-type]
    items, total = reader.list_features(None, None, None, 10, 0)
    assert total > 0
    assert reader.latest_feature(items[0].grid_id) is not None
