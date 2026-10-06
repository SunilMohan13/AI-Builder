"""Golden JSON round-trip for observation.v1."""

import json
from pathlib import Path

import pytest
from aeropulse_contracts.observation import Observation
from pydantic import ValidationError

GOLDEN = {
    "observation_id": "obs_01JTEST",
    "source_id": "cpcb",
    "source_record_id": "station123_2026",
    "schema_version": "observation.v1",
    "observed_at": "2026-09-08T05:15:00Z",
    "received_at": "2026-09-08T05:17:10Z",
    "location": {"lat": 28.6139, "lon": 77.2090},
    "measurement": {"parameter": "pm25", "value": 142.3, "unit": "ug/m3"},
    "quality": {"quality_flag": "valid", "quality_score": 0.97},
    "provenance": {
        "provider": "CPCB",
        "connector_version": "1.2.0",
        "raw_object_uri": "s3://raw/cpcb/example.json",
    },
}


def test_golden_observation_parses() -> None:
    obs = Observation.model_validate(GOLDEN)
    assert obs.measurement.parameter == "pm25"
    dumped = json.loads(obs.model_dump_json())
    assert dumped["schema_version"] == "observation.v1"


def test_extra_fields_forbidden() -> None:
    payload = dict(GOLDEN)
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        Observation.model_validate(payload)


def test_cpcb_fixture_exists() -> None:
    path = Path("fixtures/cpcb/stations.json")
    assert path.exists()
