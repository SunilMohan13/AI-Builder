"""Fail-open Redis response cache for bounded read-only API routes."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from aeropulse_common.settings import get_settings

CACHE_TTL_SECONDS = 30
_CACHEABLE_PATHS = frozenset(
    {
        "/api/v1/events",
        "/api/v1/grid-features",
        "/api/v1/grid-predictions",
        "/api/v1/map/air-quality",
        "/api/v1/map/fire",
        "/api/v1/map/forecast",
        "/api/v1/map/grid",
        "/api/v1/map/satellite",
        "/api/v1/map/weather",
        "/api/v1/models",
    }
)

_client: Any | None = None


def is_cacheable(method: str, path: str) -> bool:
    """Return whether a request is an allowlisted read endpoint."""
    return method == "GET" and path in _CACHEABLE_PATHS


def cache_key(url: str, authorization: str | None) -> str:
    """Build a non-secret key scoped to the full URL and caller token digest."""
    auth_digest = hashlib.sha256((authorization or "anonymous").encode()).hexdigest()[:16]
    request_digest = hashlib.sha256(url.encode()).hexdigest()
    return f"aeropulse:api:v1:{auth_digest}:{request_digest}"


async def get_cached(key: str) -> tuple[dict[str, Any] | None, str]:
    """Return cached response and ``hit``/``miss``/``error`` outcome."""
    try:
        raw = await _redis().get(key)
        return (json.loads(raw), "hit") if raw else (None, "miss")
    except Exception:
        return None, "error"


async def set_cached(key: str, payload: dict[str, Any]) -> bool:
    """Cache one response for the short configured TTL; return False on failure."""
    try:
        await _redis().set(key, json.dumps(payload), ex=CACHE_TTL_SECONDS)
        return True
    except Exception:
        return False


def reset_cache_client() -> None:
    """Discard the lazy client, primarily for tests and configuration reloads."""
    global _client
    _client = None


def _redis() -> Any:
    global _client
    if _client is None:
        from redis.asyncio import from_url

        _client = from_url(get_settings().redis_url, encoding="utf-8", decode_responses=True)
    return _client
