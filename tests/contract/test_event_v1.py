"""event.v1 golden contract."""

from datetime import datetime

import pytest
from aeropulse_contracts.event import EventSeverity, EventStatus, PollutionEvent
from pydantic import ValidationError

GOLDEN = {
    "event_id": "evt_123",
    "event_type": "pollution",
    "schema_version": "event.v1",
    "status": "ACTIVE",
    "severity": "HIGH",
    "created_at": "2026-09-08T05:20:00Z",
    "updated_at": "2026-09-08T05:20:00Z",
    "geometry": "POINT(75.85 30.90)",
    "grid_ids": ["abc"],
    "pollutants": ["PM2.5"],
    "detection_confidence": 0.94,
    "source_confidence": 0.82,
    "forecast_confidence": 0.0,
    "impact_confidence": 0.0,
    "overall_confidence": 0.89,
    "evidence_ids": ["evd_1"],
    "model_versions": ["baseline-idw-0.1"],
    "feature_version": "grid-features-0.4.0",
    "evidence_freshness": 1.0,
    "sensor_coverage": 0.66,
}


def test_golden_event_parses() -> None:
    event = PollutionEvent.model_validate(GOLDEN)
    assert event.status == EventStatus.ACTIVE
    assert event.severity == EventSeverity.HIGH
    assert event.forecast_confidence == 0.0


def test_extra_fields_forbidden() -> None:
    payload = dict(GOLDEN)
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        PollutionEvent.model_validate(payload)


def test_event_requires_timezone() -> None:
    event = PollutionEvent.model_validate(GOLDEN)
    assert event.created_at.tzinfo is not None or event.created_at == datetime.fromisoformat(
        "2026-09-08T05:20:00+00:00"
    )
