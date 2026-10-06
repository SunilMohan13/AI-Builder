"""Fail-open Redis API response-cache tests."""

from __future__ import annotations

from typing import Any

from aeropulse_api import cache
from aeropulse_api.app import create_app
from aeropulse_auth.jwt import Role, encode_token
from aeropulse_common.settings import get_settings
from fastapi.testclient import TestClient


def _client() -> tuple[TestClient, dict[str, str]]:
    get_settings.cache_clear()
    token = encode_token("cache-test", [Role.VIEWER])
    return TestClient(create_app()), {"Authorization": f"Bearer {token}"}


def test_cache_miss_then_hit(monkeypatch) -> None:
    stored: dict[str, dict[str, Any]] = {}

    async def fake_get(key: str):
        payload = stored.get(key)
        return (payload, "hit") if payload else (None, "miss")

    async def fake_set(key: str, payload: dict[str, Any]) -> bool:
        stored[key] = payload
        return True

    monkeypatch.setattr(cache, "get_cached", fake_get)
    monkeypatch.setattr(cache, "set_cached", fake_set)
    client, headers = _client()

    first = client.get("/api/v1/events?limit=2", headers=headers)
    second = client.get("/api/v1/events?limit=2", headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.headers["X-AeroPulse-Cache"] == "MISS"
    assert second.headers["X-AeroPulse-Cache"] == "HIT"
    assert first.json() == second.json()
    assert len(stored) == 1


def test_cache_failures_bypass_without_failing_request(monkeypatch) -> None:
    async def failing_get(key: str):
        return None, "error"

    async def failing_set(key: str, payload: dict[str, Any]) -> bool:
        return False

    monkeypatch.setattr(cache, "get_cached", failing_get)
    monkeypatch.setattr(cache, "set_cached", failing_set)
    client, headers = _client()

    response = client.get("/api/v1/map/air-quality?limit=2", headers=headers)

    assert response.status_code == 200
    assert response.headers["X-AeroPulse-Cache"] == "BYPASS"
    assert len(response.json()["features"]) == 2


def test_cache_key_uses_authorization_digest_without_exposing_token() -> None:
    first = cache.cache_key("http://test/api/v1/events?limit=2", "Bearer secret-one")
    second = cache.cache_key("http://test/api/v1/events?limit=2", "Bearer secret-two")

    assert first != second
    assert "secret-one" not in first
    assert "secret-two" not in second
    assert cache.is_cacheable("GET", "/api/v1/events") is True
    assert cache.is_cacheable("GET", "/api/v1/events/evt_1") is False
    assert cache.is_cacheable("POST", "/api/v1/events") is False


def test_cache_hit_keeps_cors_for_local_ui(monkeypatch) -> None:
    stored: dict[str, dict[str, Any]] = {}

    async def fake_get(key: str):
        payload = stored.get(key)
        return (payload, "hit") if payload else (None, "miss")

    async def fake_set(key: str, payload: dict[str, Any]) -> bool:
        stored[key] = payload
        return True

    monkeypatch.setattr(cache, "get_cached", fake_get)
    monkeypatch.setattr(cache, "set_cached", fake_set)
    client, auth = _client()
    headers = {**auth, "Origin": "http://localhost:5173"}

    first = client.get("/api/v1/grid-features?limit=2", headers=headers)
    second = client.get("/api/v1/grid-features?limit=2", headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.headers["X-AeroPulse-Cache"] == "MISS"
    assert second.headers["X-AeroPulse-Cache"] == "HIT"
    assert first.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert second.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert first.headers["access-control-allow-credentials"] == "true"
    assert second.headers["access-control-allow-credentials"] == "true"


def test_preflight_allows_local_ui_origin() -> None:
    client, _auth = _client()
    response = client.options(
        "/api/v1/grid-features?limit=2",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,accept",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
