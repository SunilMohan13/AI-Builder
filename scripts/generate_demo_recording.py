"""Generate the frontend's Demo data by recording the real API over a real cycle (LLD APAC 12.3).

Demo data is never typed by hand. This script:

1. runs the live region cycle for every region that has replay fixtures, with
   each connector fetch answered from ``fixtures/`` (no network, no keys);
2. submits one citizen photo (the committed ``fixtures/citizen`` image) through
   the citizen API and the real analyzer, with a canned visual observation in
   place of a Gemini call;
3. starts the real API over that storage and records the responses of the
   routes the UI reads, for every onboarded region. A region with no fixtures
   records exactly what the API says about it: ``not_configured``.

Output: ``frontend/web/src/data/regions/catalog.json`` and
``frontend/web/src/data/regions/<region_id>/recording.json``.

Run from the repository root::

    uv run python scripts/generate_demo_recording.py
    uv run python scripts/generate_demo_recording.py --check   # CI: fail if stale
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "web" / "src" / "data" / "regions"
CONFIG = ROOT / "config"
FIXTURES = ROOT / "fixtures"
#: The cycle time of the committed replay fixtures.
CYCLE_TIME = datetime(2026, 9, 8, 6, tzinfo=UTC)
#: The API's clock while recording: ten minutes after the cycle.
CLOCK = CYCLE_TIME + timedelta(minutes=10)
SCHEMA = "aeropulse-demo-recording.v1"
#: Every list the UI reads asks for this many rows; the UI sends the same.
LIST_LIMIT = 2000
#: The citizen photo the recording submits, and where the reporter claims to be.
CITIZEN_PHOTO = FIXTURES / "citizen" / "sample-haze-delhi.png"
CITIZEN_POINT = (28.61, 77.21)
DEMO_REPORT_ID = "cr_demo_recording_000001"

INPUTS = (
    "Live cycle code run at the fixture cycle time with every connector fetch answered "
    "from the committed replay fixtures (fixtures/). No network, no credentials, no "
    "language model. The citizen photo is fixtures/citizen/sample-haze-delhi.png with a "
    "canned visual observation instead of a Gemini call."
)


def _isolate() -> None:
    """Pin settings to declared defaults: no ``.env`` and no exported ``AEROPULSE_*``."""
    from aeropulse_common.settings import Settings, get_settings

    Settings.model_config["env_file"] = None
    for name in list(os.environ):
        if name.startswith("AEROPULSE_"):
            del os.environ[name]
    get_settings.cache_clear()


class CannedObserver:
    """Stands in for Gemini: one fixed visual observation, labelled as such."""

    provenance_class: Literal["ai_observation"] = "ai_observation"
    version = "demo-canned-observer-1"

    def observe(self, image: Any, observation_type: str) -> Any:
        from aeropulse_contracts.citizen import VisualObservation
        from aeropulse_vision import ObserverResult

        return ObserverResult(
            VisualObservation(
                visual_class="haze",
                visual_certainty="medium",
                likely_source_type="unknown",
                image_quality="good",
                scene_summary="Haze over a city skyline; no flame or plume source visible.",
                observer_version=self.version,
            )
        )


def _key(method: str, path: str, params: dict[str, Any] | None = None) -> str:
    """``GET /path?a=1&b=2`` with parameters sorted; the frontend builds the same key."""
    query = urlencode(sorted((k, str(v)) for k, v in (params or {}).items() if v is not None))
    return f"{method} {path}" + (f"?{query}" if query else "")


class Recorder:
    def __init__(self, client: Any, headers: dict[str, str]) -> None:
        self.client = client
        self.headers = headers
        self.responses: dict[str, dict[str, Any]] = {}

    def get(self, path: str, **params: Any) -> Any:
        key = _key("GET", path, params)
        query = {k: v for k, v in params.items() if v is not None}
        response = self.client.get(path, params=query, headers=self.headers)
        body = response.json() if response.content else None
        self.responses[key] = {"status": response.status_code, "body": body}
        return body if response.status_code == 200 else None

    def post(self, path: str, body: dict[str, Any]) -> Any:
        key = _key("POST", path) + "#" + json.dumps(body, sort_keys=True)
        response = self.client.post(path, json=body, headers=self.headers)
        payload = response.json() if response.content else None
        self.responses[key] = {"status": response.status_code, "request": body, "body": payload}
        return payload


def _run_cycles(root: Path, catalog: Any) -> list[str]:
    from aeropulse_common.settings import Settings
    from aeropulse_connector_sdk.replayed import replayed_registry
    from aeropulse_cycle import CycleRunner
    from aeropulse_storage import build_storage

    cycled = []
    for region_id in sorted(catalog.packs):
        # Fixtures are per source, and describe only the legacy corridor.
        if region_id != "in-north":
            continue
        CycleRunner(
            catalog,
            build_storage(Settings(data_dir=root)),
            registry=replayed_registry(),
            fixtures_root=FIXTURES,
            clock=lambda: CYCLE_TIME + timedelta(minutes=5),
        ).run(region_id, CYCLE_TIME, "live")
        cycled.append(region_id)
    return cycled


def _submit_citizen_photo(platform: Any) -> str | None:
    from aeropulse_api.app import create_app
    from aeropulse_api.citizen_client import AnalyzerClient, get_analyzer_client
    from aeropulse_api.platform import get_platform
    from aeropulse_auth import Role, encode_token
    from aeropulse_citizen_analyzer.analyzer import CitizenAnalyzer
    from aeropulse_citizen_analyzer.push import create_app as create_analyzer_app
    from aeropulse_common.settings import get_settings
    from fastapi.testclient import TestClient

    analyzer = CitizenAnalyzer(
        catalog=platform.catalog,
        storage=platform.storage,
        settings=platform.citizen,
        observer=CannedObserver(),
        clock=lambda: CLOCK + timedelta(seconds=30),
    )
    app = create_app()
    app.dependency_overrides[get_platform] = lambda: platform
    app.dependency_overrides[get_analyzer_client] = lambda: AnalyzerClient(
        "http://analyzer", client=TestClient(create_analyzer_app(analyzer))
    )
    client = TestClient(app)
    token = encode_token("demo-reporter", [Role.CITIZEN], settings=get_settings())
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/api/v1/citizen/reports",
        headers=headers,
        json={
            "lat": CITIZEN_POINT[0],
            "lon": CITIZEN_POINT[1],
            "observation_type": "haze",
            "notes": "Thick haze this morning",
        },
    )
    if created.status_code != 201:
        raise SystemExit(f"citizen create failed: {created.status_code} {created.text}")
    report_id = created.json()["report"]["report_id"]
    uploaded = client.post(
        f"/api/v1/citizen/reports/{report_id}/media",
        headers=headers,
        files={"file": (CITIZEN_PHOTO.name, CITIZEN_PHOTO.read_bytes(), "image/png")},
    )
    if uploaded.status_code != 200:
        raise SystemExit(f"citizen upload failed: {uploaded.status_code} {uploaded.text}")
    return report_id


INCIDENT_QUESTION = "Explain this incident."


def _suggested_questions(display_name: str) -> list[str]:
    return [
        f"What is the air quality in {display_name} right now?",
        "Which pollution events are active?",
        "Are there active fires?",
    ]


def _record_region(rec: Recorder, region_id: str, display_name: str) -> list[str]:
    params = {"region_id": region_id}
    rec.get(f"/api/v1/regions/{region_id}")
    for layer in ("grid", "air-quality", "fire", "weather", "forecast", "hazard"):
        rec.get(f"/api/v1/map/{layer}", limit=LIST_LIMIT, **params)
    rec.get("/api/v1/map/source-likelihood", **params)
    rec.get("/api/v1/plumes", **params)
    rec.get("/api/v1/models", **params)
    rec.get("/api/v1/ml/evaluation", **params)

    events = rec.get("/api/v1/events", **params) or {}
    for event in events.get("items", []):
        rec.get(f"/api/v1/events/{event['event_id']}", **params)

    incidents = rec.get("/api/v1/incidents", **params) or {}
    incident_ids = [i["incident_id"] for i in incidents.get("items", [])]
    for incident_id in incident_ids:
        rec.get(f"/api/v1/incidents/{incident_id}")

    reports = rec.get("/api/v1/citizen/reports", limit=100, **params) or {}
    for report in reports.get("items", []):
        rec.get(f"/api/v1/citizen/reports/{report['report_id']}")

    questions = _suggested_questions(display_name)
    for question in questions:
        rec.post("/api/v1/copilot/query", {"question": question, "region_id": region_id})
    for incident_id in incident_ids:
        for question in [INCIDENT_QUESTION, *questions]:
            rec.post(
                "/api/v1/copilot/query",
                {"question": question, "region_id": region_id, "incident_id": incident_id},
            )
    return questions


def _replace(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [_replace(v, old, new) for v in value]
    if isinstance(value, dict):
        return {_replace(k, old, new): _replace(v, old, new) for k, v in value.items()}
    return value


def _dump(payload: Any) -> str:
    return json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def generate() -> dict[Path, str]:
    """Build every output file in memory: path → text."""
    _isolate()
    from aeropulse_api.app import create_app
    from aeropulse_api.platform import ApiPlatform, get_platform
    from aeropulse_auth import Role, encode_token
    from aeropulse_common.settings import Settings, get_settings
    from aeropulse_regions import load_catalog, load_citizen_settings
    from aeropulse_storage import build_storage
    from fastapi.testclient import TestClient

    files: dict[Path, str] = {}
    with tempfile.TemporaryDirectory(prefix="aeropulse-demo-") as tmp:
        root = Path(tmp)
        os.environ["AEROPULSE_DATA_DIR"] = str(root)
        get_settings.cache_clear()
        catalog = load_catalog(CONFIG)
        cycled = _run_cycles(root, catalog)
        settings = Settings(data_dir=root, citizen_analyzer_url="http://analyzer")
        platform = ApiPlatform(
            settings=settings,
            catalog=catalog,
            storage=build_storage(settings),
            citizen=load_citizen_settings(CONFIG),
            clock=lambda: CLOCK,
        )
        report_id = _submit_citizen_photo(platform) if "in-north" in cycled else None

        app = create_app()
        app.dependency_overrides[get_platform] = lambda: platform
        client = TestClient(app)
        token = encode_token("demo-operator", [Role.OPERATOR], settings=get_settings())
        headers = {"Authorization": f"Bearer {token}"}

        catalog_rec = Recorder(client, headers)
        regions = catalog_rec.get("/api/v1/regions")
        files[OUT / "catalog.json"] = _dump(
            {
                "schema": SCHEMA,
                "generator": "scripts/generate_demo_recording.py",
                "inputs": INPUTS,
                "clock": CLOCK.isoformat(),
                "recorded_regions": sorted(catalog.packs),
                "cycled_regions": cycled,
                "responses": catalog_rec.responses,
            }
        )
        for item in regions["items"]:
            region_id = item["region_id"]
            rec = Recorder(client, headers)
            questions = _record_region(rec, region_id, item["display_name"])
            responses: Any = rec.responses
            if report_id is not None:
                responses = _replace(responses, report_id, DEMO_REPORT_ID)
            files[OUT / region_id / "recording.json"] = _dump(
                {
                    "schema": SCHEMA,
                    "region_id": region_id,
                    "generator": "scripts/generate_demo_recording.py",
                    "inputs": INPUTS,
                    "clock": CLOCK.isoformat(),
                    "cycle_time": CYCLE_TIME.isoformat() if region_id in cycled else None,
                    "has_scenario": region_id in cycled,
                    "scenario_reason": None
                    if region_id in cycled
                    else (
                        f"No replay fixtures exist for {region_id} yet, so the cycle was not "
                        "run; every route records what the API returns without a snapshot."
                    ),
                    "persona": {"subject": "demo-operator", "roles": ["operator"]},
                    "id_substitutions": {"citizen_report_id": DEMO_REPORT_ID}
                    if report_id is not None
                    else {},
                    "suggested_questions": questions,
                    "incident_question": INCIDENT_QUESTION,
                    "responses": responses,
                }
            )
    return files


def _stale(files: dict[Path, str]) -> Iterable[Path]:
    for path, text in files.items():
        if not path.exists() or path.read_text() != text:
            yield path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="fail if the committed files differ")
    args = parser.parse_args(argv)
    os.chdir(ROOT)
    files = generate()
    if args.check:
        stale = list(_stale(files))
        for path in stale:
            print(f"stale: {path.relative_to(ROOT)}", file=sys.stderr)
        if stale:
            print("run: uv run python scripts/generate_demo_recording.py", file=sys.stderr)
        return 1 if stale else 0
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        print(f"wrote {path.relative_to(ROOT)} ({len(text) // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
