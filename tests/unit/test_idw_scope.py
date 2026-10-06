"""IDW must not mix hours or model-derived values into a served PM2.5."""

from datetime import UTC, datetime

from aeropulse_contracts.observation import (
    Location,
    Measurement,
    Observation,
    Provenance,
    ProvenanceClass,
    Quality,
)
from aeropulse_intelligence.estimator import estimate_pm25


def _obs(source_id: str, hour: int, value: float) -> Observation:
    return Observation(
        observation_id=f"{source_id}-{hour}",
        source_id=source_id,
        source_record_id="s",
        observed_at=datetime(2026, 9, 8, hour, 15, tzinfo=UTC),
        received_at=datetime(2026, 9, 8, hour, 20, tzinfo=UTC),
        location=Location(lat=28.61, lon=77.21),
        measurement=Measurement(parameter="pm25", value=value, unit="ug/m3"),
        quality=Quality(quality_flag="valid", quality_score=0.9),
        provenance=Provenance(
            provider=source_id,
            connector_version="1.0.0",
            provenance_class=(
                ProvenanceClass.MODEL_DERIVED
                if source_id == "openmeteo"
                else ProvenanceClass.MEASURED
            ),
        ),
    )


def test_idw_ignores_other_hours_and_cams() -> None:
    stations = [
        _obs("cpcb", 5, 40.0),
        _obs("cpcb", 4, 400.0),
        _obs("openmeteo", 5, 400.0),
    ]
    pred = estimate_pm25(
        "cell",
        datetime(2026, 9, 8, 5, tzinfo=UTC),
        28.61,
        77.21,
        stations,
    )
    assert pred is not None
    assert pred.pm25_estimate == 40.0


def test_idw_returns_none_when_only_cams_is_present() -> None:
    pred = estimate_pm25(
        "cell",
        datetime(2026, 9, 8, 5, tzinfo=UTC),
        28.61,
        77.21,
        [_obs("cams", 5, 180.0)],
    )
    assert pred is None
