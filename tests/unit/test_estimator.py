"""Baseline IDW PM2.5 estimator tests."""

from datetime import UTC, datetime

from aeropulse_contracts.observation import (
    Location,
    Measurement,
    Observation,
    Provenance,
    Quality,
)
from aeropulse_intelligence.estimator import estimate_pm25


def _obs(lat: float, lon: float, value: float) -> Observation:
    return Observation(
        observation_id="obs",
        source_id="cpcb",
        source_record_id="s",
        observed_at=datetime(2026, 9, 8, 5, 15, tzinfo=UTC),
        received_at=datetime(2026, 9, 8, 5, 17, tzinfo=UTC),
        location=Location(lat=lat, lon=lon),
        measurement=Measurement(parameter="pm25", value=value, unit="ug/m3"),
        quality=Quality(quality_flag="valid", quality_score=0.9),
        provenance=Provenance(provider="CPCB", connector_version="1.0.0"),
    )


def test_idw_prefers_nearer_station() -> None:
    near = _obs(30.90, 75.85, 180.0)
    far = _obs(28.63, 77.24, 80.0)
    pred = estimate_pm25("cell", datetime(2026, 9, 8, 5, tzinfo=UTC), 30.90, 75.85, [near, far])
    assert pred is not None
    assert pred.pm25_estimate > 150
    assert pred.prediction_interval_low <= pred.pm25_estimate <= pred.prediction_interval_high


def test_no_stations_returns_none() -> None:
    assert estimate_pm25("cell", datetime(2026, 9, 8, 5, tzinfo=UTC), 30.0, 75.0, []) is None
