"""Liveness and readiness endpoints (unauthenticated)."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Return process liveness."""
    return {"status": "ok"}


@router.get("/ready")
def ready() -> dict[str, str]:
    """Return readiness. Dependency pings are best-effort in Phase 1."""
    return {"status": "ready"}
