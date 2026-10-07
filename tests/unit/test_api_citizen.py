"""Citizen photo API v2 (LLD APAC 9.1, 9.6, 12.1) with the analyzer over HTTP.

The API never imports the analyzer app: it posts the push envelope to it.
Here that HTTP hop is a ``TestClient`` around the real analyzer app with a
stub observer standing in for Gemini.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Literal

import httpx
import pytest
from aeropulse_api.citizen_client import (
    AnalyzerClient,
    AnalyzerUnavailableError,
    get_analyzer_client,
    google_id_token,
)
from aeropulse_api.platform import ApiPlatform
from aeropulse_auth import Role
from aeropulse_citizen_analyzer.analyzer import CitizenAnalyzer
from aeropulse_citizen_analyzer.push import create_app as create_analyzer_app
from aeropulse_common.settings import Settings
from aeropulse_contracts.citizen import VisualObservation
from aeropulse_cycle import CycleRunner
from aeropulse_regions import load_catalog
from aeropulse_storage import build_storage
from aeropulse_vision import ObserverResult, SanitizedImage
from aeropulse_vision.sanitize import has_metadata
from fastapi.testclient import TestClient
from region_cycle import CONFIG, T0, auth, client_for, platform_for
from replayed_registry import replayed_registry
from test_vision import jpeg_with_exif

#: West of the fixture fire cluster at (30.12, 75.71); the camera looks east.
PUNJAB = (30.10, 75.55)


class StubObserver:
    provenance_class: Literal["ai_observation"] = "ai_observation"
    version = "stub-observer-1"

    def observe(self, image: SanitizedImage, observation_type: str) -> ObserverResult:
        assert not has_metadata(image.data)
        return ObserverResult(
            VisualObservation(
                visual_class="smoke_plume",
                visual_certainty="high",
                likely_source_type="agricultural_field",
                image_quality="good",
                scene_summary="Smoke rising over a field.",
                observer_version=self.version,
            )
        )


def _photo() -> bytes:
    # 11:35 IST is 06:05 UTC, five minutes before the report is created.
    return jpeg_with_exif(*PUNJAB, taken_local="2026:09:08 11:35:00", direction=85.0)


@pytest.fixture
def platform(tmp_path: Path) -> ApiPlatform:
    catalog = load_catalog(CONFIG)
    CycleRunner(
        catalog,
        build_storage(Settings(data_dir=tmp_path)),
        registry=replayed_registry(),
        fixtures_root=Path("fixtures"),
        clock=lambda: T0 + timedelta(minutes=5),
    ).run("in-north", T0, "live")
    return platform_for(tmp_path, citizen_analyzer_url="http://analyzer")


@pytest.fixture
def client(platform: ApiPlatform) -> TestClient:
    analyzer = CitizenAnalyzer(
        catalog=platform.catalog,
        storage=platform.storage,
        settings=platform.citizen,
        observer=StubObserver(),
        # Just after the API's own clock, as a push a moment after upload is.
        clock=lambda: T0 + timedelta(minutes=10, seconds=30),
    )
    transport = TestClient(create_analyzer_app(analyzer))
    client = client_for(platform)
    app = client.app
    app.dependency_overrides[get_analyzer_client] = lambda: AnalyzerClient(  # type: ignore[attr-defined]
        "http://analyzer", client=transport
    )
    return client


def _create(client: TestClient, sub: str = "alice", **body: object) -> dict:
    response = client.post(
        "/api/v1/citizen/reports",
        headers=auth(Role.CITIZEN, sub=sub),
        json={"lat": PUNJAB[0], "lon": PUNJAB[1], "observation_type": "smoke", **body},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_a_photo_is_analysed_corroborated_and_shown_without_private_fields(
    client: TestClient,
) -> None:
    created = _create(client, notes="smoke over the field")
    report = created["report"]
    assert report["region_id"] == "in-north" and report["status"] == "awaiting_media"
    assert "reporter_hash" not in report and "incoming_key" not in report
    assert created["upload"]["method"] == "POST", "local storage has no signed URL"
    report_id = report["report_id"]

    alice, bob = auth(Role.CITIZEN, sub="alice"), auth(Role.CITIZEN, sub="bob")
    media = f"/api/v1/citizen/reports/{report_id}/media"
    photo = {"file": ("smoke.jpg", _photo(), "image/jpeg")}
    assert client.post(media, headers=bob, files=photo).status_code == 403

    uploaded = client.post(media, headers=alice, files=photo)
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert body["analysis"] == "triggered" and body["field_status"] == []
    analysed = body["report"]
    assert analysed["status"] == "analyzed"
    assert analysed["visual_class"] == "smoke_plume"
    assert analysed["visual_class_provenance"] == "ai_observation"
    assert analysed["analysis"]["corroboration"]["level"] == "corroborated"
    assert client.post(media, headers=alice, files=photo).status_code == 409

    public = client.get(f"/api/v1/citizen/reports/{report_id}", headers=bob).json()
    assert "notes" not in public and public["location_rounded_to_decimals"] >= 1
    assert public["claimed_lat"] == round(PUNJAB[0], public["location_rounded_to_decimals"])

    listed = client.get("/api/v1/citizen/reports?region_id=in-north", headers=bob).json()
    row = next(r for r in listed["items"] if r["report_id"] == report_id)
    assert row["corroboration"] == "corroborated" and row["visual_class"] == "smoke_plume"
    assert "reporter_hash" not in row and "claimed_lat" not in row
    assert listed["limit"] is None and listed["offset"] == 0

    assert client.get(f"{media}", headers=bob).status_code == 403
    link = client.get(media, headers=alice).json()
    content = client.get(link["url"], headers=alice)
    assert content.status_code == 200
    assert content.headers["cache-control"] == "private, no-store"
    assert not has_metadata(content.content), "only the sanitized copy is ever served"


def test_moderation_is_operator_only_and_proxied_with_the_callers_token(
    client: TestClient,
) -> None:
    report_id = _create(client)["report"]["report_id"]
    client.post(
        f"/api/v1/citizen/reports/{report_id}/media",
        headers=auth(Role.CITIZEN, sub="alice"),
        files={"file": ("smoke.jpg", _photo(), "image/jpeg")},
    )
    path = f"/api/v1/citizen/reports/{report_id}/moderation"
    denied = client.post(path, headers=auth(Role.VIEWER), json={"action": "reject"})
    assert denied.status_code == 403

    set_class = client.post(
        path, headers=auth(Role.OPERATOR), json={"action": "set_class", "visual_class": "haze"}
    )
    assert set_class.status_code == 200, set_class.text
    assert set_class.json()["moderated_class"] == "haze"

    rejected = client.post(path, headers=auth(Role.OPERATOR), json={"action": "reject"})
    assert rejected.status_code == 200 and rejected.json()["moderation"] == "rejected"
    hidden = client.get(f"/api/v1/citizen/reports/{report_id}", headers=auth(Role.VIEWER))
    assert hidden.status_code == 404, "a rejected report is visible to operators only"
    seen = client.get(f"/api/v1/citizen/reports/{report_id}", headers=auth(Role.OPERATOR))
    assert seen.status_code == 200 and seen.json()["visual_class_provenance"] == "citizen"


def test_on_google_cloud_the_api_identity_rides_beside_the_operators_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"report_id": "r1"})

    analyzer = AnalyzerClient(
        "https://analyzer.example.run.app/",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        id_token=lambda audience: f"id-for:{audience}",
    )
    status, _ = analyzer.moderate("r1", {"action": "reject"}, authorization="Bearer operator")

    assert status == 200
    assert seen[0].headers["authorization"] == "Bearer operator"
    assert (
        seen[0].headers["x-serverless-authorization"]
        == "Bearer id-for:https://analyzer.example.run.app"
    )


def test_a_missing_google_identity_is_an_unavailable_analyzer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import google.auth.exceptions
    import google.oauth2.id_token

    def no_credentials(request: object, audience: str) -> str:
        raise google.auth.exceptions.DefaultCredentialsError("no ADC")

    monkeypatch.setattr(google.oauth2.id_token, "fetch_id_token", no_credentials)
    with pytest.raises(AnalyzerUnavailableError, match="no identity token"):
        google_id_token("https://analyzer.example.run.app")


def test_without_an_analyzer_the_upload_says_how_to_analyse(tmp_path: Path) -> None:
    client = client_for(platform_for(tmp_path))
    report_id = _create(client)["report"]["report_id"]
    uploaded = client.post(
        f"/api/v1/citizen/reports/{report_id}/media",
        headers=auth(Role.CITIZEN, sub="alice"),
        files={"file": ("smoke.jpg", _photo(), "image/jpeg")},
    ).json()
    assert uploaded["analysis"] == "not_triggered"
    assert uploaded["report"]["status"] == "queued"
    assert "AEROPULSE_CITIZEN_ANALYZER_URL" in uploaded["field_status"][0]["reason"]
    moderation = client.post(
        f"/api/v1/citizen/reports/{report_id}/moderation",
        headers=auth(Role.OPERATOR),
        json={"action": "accept"},
    )
    assert moderation.status_code == 503


def test_reports_are_validated_before_anything_is_stored(tmp_path: Path) -> None:
    client = client_for(platform_for(tmp_path))
    headers = auth(Role.CITIZEN, sub="alice")
    url = "/api/v1/citizen/reports"
    assert client.post(url, headers=headers, json={"lat": 0.0, "lon": 0.0}).status_code == 422
    wrong_region = {"lat": PUNJAB[0], "lon": PUNJAB[1], "region_id": "sg-singapore"}
    assert client.post(url, headers=headers, json=wrong_region).status_code == 422
    bad_type = {"lat": PUNJAB[0], "lon": PUNJAB[1], "content_type": "image/gif"}
    assert client.post(url, headers=headers, json=bad_type).status_code == 422
    operator = client.post(
        url, headers=auth(Role.OPERATOR), json={"lat": PUNJAB[0], "lon": PUNJAB[1]}
    )
    assert operator.status_code == 403, "operators moderate; they do not file citizen reports"

    report_id = _create(client)["report"]["report_id"]
    text = client.post(
        f"{url}/{report_id}/media",
        headers=headers,
        files={"file": ("notes.txt", b"not-an-image", "image/jpeg")},
    )
    assert text.status_code == 400, "the bytes are sniffed, not the declared type"


def test_the_reporter_salt_is_required_outside_development(tmp_path: Path) -> None:
    client = client_for(platform_for(tmp_path, environment="production", jwt_secret="x" * 40))
    response = client.post(
        "/api/v1/citizen/reports",
        headers=auth(Role.CITIZEN, sub="alice"),
        json={"lat": PUNJAB[0], "lon": PUNJAB[1]},
    )
    assert response.status_code == 503
