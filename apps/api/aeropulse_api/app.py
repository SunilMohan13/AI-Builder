"""FastAPI application factory."""

import re
from time import perf_counter, time

from aeropulse_common.settings import get_settings
from aeropulse_observability.logging import configure_logging
from aeropulse_observability.metrics import (
    CACHE_REQUESTS,
    HTTP_DURATION,
    HTTP_IN_FLIGHT,
    HTTP_REQUESTS,
    route_label,
)
from aeropulse_observability.telemetry import configure_telemetry
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from aeropulse_api import cache
from aeropulse_api.demo_seed import seed_replay_episode
from aeropulse_api.routers import (
    alerts,
    citizen,
    copilot,
    drift,
    events,
    grid,
    health,
    models,
    risk,
    sources,
)
from aeropulse_api.routers import map as map_router

_LOCAL_UI_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:4173",
    "http://localhost:4173",
    "https://aeropulse-india.netlify.app",
]
# Netlify and Render both mint a subdomain per site. Allow the pattern so a
# new deploy does not need its exact URL baked into this list.
_HOSTED_UI_ORIGIN = re.compile(r"https://[a-z0-9-]+\.(?:netlify\.app|onrender\.com)")


def _cors_origins(settings) -> list[str]:
    """Local UI, the Netlify demo, plus any extra hosts from env."""
    extra = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    seen: set[str] = set()
    origins: list[str] = []
    for origin in [*_LOCAL_UI_ORIGINS, *extra]:
        if origin in seen:
            continue
        seen.add(origin)
        origins.append(origin)
    return origins


def _allowed_request_origin(origin: str | None, settings) -> str | None:
    """Return the request Origin when it is on the allow-list, else None."""
    if not origin:
        return None
    if origin in _cors_origins(settings):
        return origin
    if _HOSTED_UI_ORIGIN.fullmatch(origin):
        return origin
    return None


def _apply_cors(request: Request, response: Response) -> Response:
    """Stamp CORS on responses built outside CORSMiddleware.

    `@app.middleware("http")` is BaseHTTPMiddleware and is outermost unless
    CORS is added after it. Cache HIT and 429 paths never call `call_next`, so
    they would otherwise return 200/429 with no `Access-Control-Allow-Origin`
    and the browser would drop the body (`net::ERR_FAILED`).
    """
    origin = _allowed_request_origin(request.headers.get("origin"), get_settings())
    if origin is None:
        return response
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


def create_app() -> FastAPI:
    """Build the AeroPulse API with routers and CORS for the local UI."""
    settings = get_settings()
    settings.service_name = "aeropulse-api"  # type: ignore[misc]
    configure_logging(settings)
    configure_telemetry(settings)
    # Always load the in-memory Punjab episode. Timescale-backed Docker has
    # DATABASE_URL set, so without this the Live UI 404s on EVT-1024 until
    # the worker persists a pollution_event row. ReplayFallbackEventReader
    # only serves this seed when the events table is empty.
    seed_replay_episode()

    app = FastAPI(
        title="AeroPulse API",
        version=settings.service_version,
        description="AeroPulse India API v1: map, sources, events, forecast, evidence graph.",
        openapi_tags=[
            {"name": "health", "description": "Liveness and readiness"},
            {"name": "sources", "description": "Data source registry and backfill"},
            {"name": "map", "description": "GeoJSON layers for the operational map"},
            {"name": "events", "description": "Pollution events, evidence, forecast, lineage"},
            {"name": "grid-intelligence", "description": "Persisted grid features and predictions"},
            {"name": "drift", "description": "Feature and prediction distribution drift"},
            {"name": "copilot", "description": "Evidence-grounded reasoning (no LLM invention)"},
            {"name": "citizen", "description": "Citizen reports (corroborative, no CV)"},
            {"name": "alerts", "description": "Canonical alerts (log channel)"},
            {"name": "risk", "description": "Exposure vs pollution severity"},
        ],
    )
    app.include_router(health.router)
    app.include_router(sources.router)
    app.include_router(map_router.router)
    app.include_router(events.router)
    app.include_router(grid.router)
    app.include_router(drift.router)
    app.include_router(copilot.router)
    app.include_router(citizen.router)
    app.include_router(alerts.router)
    app.include_router(risk.router)
    app.include_router(models.router)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        """Expose Prometheus metrics for local/collector scraping."""
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    buckets: dict[str, list[float]] = {}

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        started = perf_counter()
        HTTP_IN_FLIGHT.inc()
        response = None
        try:
            if request.url.path.startswith("/api/v1/"):
                key = request.client.host if request.client else "unknown"
                now = time()
                window = [t for t in buckets.get(key, []) if now - t < 60]
                if len(window) >= 600:
                    response = JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
                else:
                    window.append(now)
                    buckets[key] = window
            cacheable = response is None and cache.is_cacheable(request.method, request.url.path)
            cache_key = None
            if cacheable:
                cache_key = cache.cache_key(str(request.url), request.headers.get("authorization"))
                cached, outcome = await cache.get_cached(cache_key)
                CACHE_REQUESTS.labels(request.url.path, outcome).inc()
                if cached is not None:
                    response = Response(
                        content=cached["body"].encode("utf-8"),
                        status_code=cached["status_code"],
                        media_type=cached["media_type"],
                        headers={"X-AeroPulse-Cache": "HIT"},
                    )
            if response is None:
                response = await call_next(request)
                if (
                    cacheable
                    and cache_key is not None
                    and response.status_code == 200
                    and response.headers.get("content-type", "").startswith("application/json")
                ):
                    body = b"".join([chunk async for chunk in response.body_iterator])
                    payload = {
                        "body": body.decode("utf-8"),
                        "status_code": response.status_code,
                        "media_type": "application/json",
                    }
                    stored = await cache.set_cached(cache_key, payload)
                    CACHE_REQUESTS.labels(
                        request.url.path, "stored" if stored else "write_error"
                    ).inc()
                    response = Response(
                        content=body,
                        status_code=response.status_code,
                        headers={
                            key: value
                            for key, value in response.headers.items()
                            if key.lower() not in {"content-length", "content-type"}
                        }
                        | {"X-AeroPulse-Cache": "MISS" if stored else "BYPASS"},
                        media_type="application/json",
                        background=response.background,
                    )
            return _apply_cors(request, response)
        finally:
            route = route_label(request)
            status = str(response.status_code) if response is not None else "500"
            HTTP_REQUESTS.labels(request.method, route, status).inc()
            HTTP_DURATION.labels(request.method, route).observe(perf_counter() - started)
            HTTP_IN_FLIGHT.dec()

    # Added last so CORS is outermost. Starlette wraps in reverse of
    # `user_middleware`; last `add_middleware` runs first on the request and
    # last on the response, including cache HIT / 429 that skip `call_next`.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(settings),
        allow_origin_regex=_HOSTED_UI_ORIGIN.pattern,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-AeroPulse-Cache"],
    )
    return app
