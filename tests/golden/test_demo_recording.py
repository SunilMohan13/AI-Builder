"""The frontend's Demo data is a recording of the real API over a real cycle.

If the API or the cycle changes, the committed recording goes stale and Demo
would drift from what Live serves. Regenerate with
``uv run python scripts/generate_demo_recording.py``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REGIONS = ROOT / "frontend" / "web" / "src" / "data" / "regions"


def _recording(region_id: str) -> dict[str, Any]:
    return json.loads((REGIONS / region_id / "recording.json").read_text())


def test_the_committed_recording_matches_a_fresh_generation() -> None:
    script = ROOT / "scripts" / "generate_demo_recording.py"
    done = subprocess.run(
        [sys.executable, str(script), "--check"], cwd=ROOT, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]


def test_every_onboarded_region_has_a_recording() -> None:
    catalog = json.loads((REGIONS / "catalog.json").read_text())
    listed = catalog["responses"]["GET /api/v1/regions"]["body"]["items"]
    ids = {region["region_id"] for region in listed}
    assert ids == set(catalog["recorded_regions"]) == {"in-north", "sg-singapore", "au-nsw"}
    assert catalog["cycled_regions"] == ["in-north", "sg-singapore"]
    for region_id in ids:
        recording = _recording(region_id)
        assert recording["schema"] == "aeropulse-demo-recording.v1"
        assert catalog["clocks"][region_id] == recording["clock"]


def test_regions_without_fixtures_record_not_configured_not_borrowed_data() -> None:
    recording = _recording("au-nsw")
    assert recording["has_scenario"] is False
    grid = recording["responses"]["GET /api/v1/map/grid?limit=2000&region_id=au-nsw"]
    assert grid["body"]["data_source"]["kind"] == "not_configured"
    assert grid["body"]["features"] == []
    text = json.dumps(recording["responses"])
    assert "in-north" not in text and "sg-singapore" not in text


def test_each_region_is_recorded_at_its_own_cycle_hour() -> None:
    for region_id in ("in-north", "sg-singapore"):
        recording = _recording(region_id)
        detail = recording["responses"][f"GET /api/v1/regions/{region_id}"]["body"]
        assert recording["has_scenario"] is True
        assert detail["snapshot"]["cycle_time"] == recording["cycle_time"]
        assert recording["clock"] > recording["cycle_time"]


def test_the_singapore_recording_is_its_own_haze_episode_not_borrowed_data() -> None:
    recording = _recording("sg-singapore")
    responses = recording["responses"]
    text = json.dumps(responses)
    assert "in-north" not in text and "Delhi" not in text
    sources = {
        s["source_id"]: s for s in responses["GET /api/v1/regions/sg-singapore"]["body"]["sources"]
    }
    assert sources["openaq"]["state"] == "healthy" and sources["openaq"]["records"] > 0
    assert sources["firms"]["records"] > 0
    assert sources["earthengine"]["state"] == "not_configured"
    fire = responses["GET /api/v1/map/fire?limit=2000&region_id=sg-singapore"]["body"]
    assert fire["features"]
    hazard = responses["GET /api/v1/map/hazard?limit=2000&region_id=sg-singapore"]["body"]
    assert hazard["features"] == []


def test_the_in_north_recording_carries_the_cycle_and_its_incident() -> None:
    recording = _recording("in-north")
    responses = recording["responses"]
    assert recording["has_scenario"] is True
    assert "GET /api/v1/incidents/inc_fd6ec2096981a3d3e14fb1a6" in responses
    copilot = [k for k in responses if k.startswith("POST /api/v1/copilot/query")]
    assert copilot and all(responses[k]["body"]["tool_calls"] for k in copilot)
