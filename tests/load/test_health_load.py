"""Lightweight load check for /health (LLD hardening). Not a full k6 suite."""

from aeropulse_api.app import create_app
from fastapi.testclient import TestClient


def test_health_burst() -> None:
    client = TestClient(create_app())
    for _ in range(50):
        assert client.get("/health").status_code == 200
