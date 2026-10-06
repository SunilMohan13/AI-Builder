"""Drift API and Timescale signal reader tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aeropulse_api.app import create_app
from aeropulse_api.drift_store import TimescaleDriftReader, get_drift_reader
from aeropulse_auth.jwt import Role, encode_token
from aeropulse_common.settings import get_settings
from fastapi.testclient import TestClient

REFERENCE_START = datetime(2026, 8, 1, tzinfo=UTC)
REFERENCE_END = datetime(2026, 8, 15, tzinfo=UTC)
CURRENT_START = datetime(2026, 9, 1, tzinfo=UTC)
CURRENT_END = datetime(2026, 9, 15, tzinfo=UTC)


class _Cursor:
    def __init__(self, rows: list[tuple[float]], calls: list[tuple[str, Any]]) -> None:
        self.rows = rows
        self.calls = calls

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: Any) -> None:
        self.calls.append((" ".join(sql.split()), params))

    def fetchall(self) -> list[tuple[float]]:
        return self.rows


class _Connection:
    def __init__(self, rows: list[tuple[float]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, Any]] = []

    def cursor(self) -> _Cursor:
        return _Cursor(self.rows, self.calls)


def test_timescale_drift_reader_uses_whitelisted_signal_and_filters() -> None:
    connection = _Connection([(100.0,), (120.0,)])
    reader = TimescaleDriftReader(connection)

    values = reader.values(
        "prediction.pm25_estimate",
        REFERENCE_START,
        REFERENCE_END,
        "grid_a",
        "baseline-idw-0.1",
        1000,
    )

    assert values == [100.0, 120.0]
    sql, params = connection.calls[0]
    assert "SELECT pm25_estimate FROM grid_prediction" in sql
    assert "grid_id = %s" in sql
    assert "model_version = %s" in sql
    assert params == [
        REFERENCE_START,
        REFERENCE_END,
        "grid_a",
        "baseline-idw-0.1",
        1000,
    ]


class _FakeDriftReader:
    def values(self, signal, start, end, grid_id, model_version, limit):
        if start == REFERENCE_START:
            return [float(value) for value in range(100)]
        return [float(value + 100) for value in range(100)]


def _client() -> tuple[TestClient, dict[str, str]]:
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_drift_reader] = lambda: _FakeDriftReader()
    token = encode_token("drift-test", [Role.VIEWER])
    return TestClient(app), {"Authorization": f"Bearer {token}"}


def _params() -> dict[str, str]:
    return {
        "reference_start": REFERENCE_START.isoformat(),
        "reference_end": REFERENCE_END.isoformat(),
        "current_start": CURRENT_START.isoformat(),
        "current_end": CURRENT_END.isoformat(),
    }


def test_drift_endpoint_reports_shifted_distribution() -> None:
    client, headers = _client()

    response = client.get("/api/v1/drift", params=_params(), headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["signal"] == "prediction.pm25_estimate"
    assert body["status"] == "DRIFT"
    assert body["psi"] >= 0.25
    assert body["ks_statistic"] > body["ks_critical_value"]
    assert "Error drift is unavailable" in body["limitations"][1]


def test_drift_endpoint_validates_signal_and_windows() -> None:
    client, headers = _client()
    params = _params()

    bad_signal = client.get(
        "/api/v1/drift", params={**params, "signal": "feature.unsafe"}, headers=headers
    )
    overlap = client.get(
        "/api/v1/drift",
        params={**params, "current_start": "2026-08-14T00:00:00+00:00"},
        headers=headers,
    )
    bad_scope = client.get(
        "/api/v1/drift",
        params={**params, "signal": "feature.pm25", "model_version": "model"},
        headers=headers,
    )

    assert bad_signal.status_code == 422
    assert overlap.status_code == 422
    assert bad_scope.status_code == 422
    assert client.get("/api/v1/drift", params=params).status_code == 401
