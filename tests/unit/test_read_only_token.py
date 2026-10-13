"""The public demo token: it reads and asks questions, and every other write is refused."""

from __future__ import annotations

from pathlib import Path

import pytest
from aeropulse_auth import Role, encode_token
from aeropulse_auth.jwt import decode_token
from aeropulse_common.settings import Settings, get_settings
from fastapi.testclient import TestClient
from region_cycle import auth, client_for, platform_for, run_cycle

REPORT = {"lat": 30.10, "lon": 75.55, "observation_type": "smoke"}


def _demo(*roles: Role) -> dict[str, str]:
    token = encode_token(
        "public-demo", list(roles) or [Role.VIEWER], settings=get_settings(), read_only=True
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    run_cycle(tmp_path)
    return client_for(platform_for(tmp_path))


def test_the_claim_round_trips_and_defaults_to_off() -> None:
    settings = Settings(jwt_secret="unit-test-secret-must-be-32bytes!")  # type: ignore[arg-type]
    demo = encode_token("public-demo", [Role.VIEWER], settings=settings, read_only=True)
    normal = encode_token("analyst", [Role.ANALYST], settings=settings)
    assert decode_token(demo, settings=settings).read_only
    assert not decode_token(normal, settings=settings).read_only


def test_a_read_only_token_reads(client: TestClient) -> None:
    response = client.get("/api/v1/map/air-quality?region_id=in-north", headers=_demo())
    assert response.status_code == 200, response.text


def test_a_read_only_token_cannot_report_upload_or_administer(client: TestClient) -> None:
    refused = client.post("/api/v1/citizen/reports", headers=_demo(Role.CITIZEN), json=REPORT)
    assert refused.status_code == 403
    assert refused.json()["detail"] == "this demo token is read-only"
    admin = client.put("/api/v1/sources/openaq", headers=_demo(Role.ADMIN), json={})
    assert admin.status_code == 403
    assert admin.json()["detail"] == "this demo token is read-only"


def test_a_read_only_token_can_ask_aeropulse(client: TestClient) -> None:
    answer = client.post(
        "/api/v1/copilot/query",
        headers=_demo(),
        json={"question": "What is the air quality right now?", "region_id": "in-north"},
    )
    assert answer.status_code == 200, answer.text


def test_a_normal_token_still_writes(client: TestClient) -> None:
    created = client.post("/api/v1/citizen/reports", headers=auth(Role.CITIZEN), json=REPORT)
    assert created.status_code == 201, created.text
