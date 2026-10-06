"""Wind-advection forecast tests."""

from datetime import UTC, datetime

import h3
from aeropulse_contracts.event import EventSeverity, EventStatus, PollutionEvent
from aeropulse_intelligence.forecast import forecast_event


def _event() -> PollutionEvent:
    return PollutionEvent(
        event_id="evt_test",
        status=EventStatus.ACTIVE,
        severity=EventSeverity.HIGH,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        grid_ids=["origin"],
        detection_confidence=0.8,
        source_confidence=0.7,
        forecast_confidence=0.0,
        impact_confidence=0.0,
        overall_confidence=0.75,
        evidence_freshness=1.0,
        sensor_coverage=0.5,
    )


def test_wind_moves_prediction_off_origin() -> None:
    origin = h3.latlng_to_cell(30.90, 75.85, 8)
    lat, lon = h3.cell_to_latlng(origin)
    result = forecast_event(
        _event(),
        origin_grid_id=origin,
        origin_lat=lat,
        origin_lon=lon,
        pm25=180.0,
        wind_u=5.0,
        wind_v=0.0,
    )
    assert result.cams_applied is False
    far = result.grid_predictions[-1]
    assert far.grid_id != origin
    assert far.pm25 < 180.0
    assert far.confidence < result.grid_predictions[0].confidence


def test_calm_wind_stays_on_origin() -> None:
    origin = h3.latlng_to_cell(30.90, 75.85, 8)
    lat, lon = h3.cell_to_latlng(origin)
    result = forecast_event(
        _event(),
        origin_grid_id=origin,
        origin_lat=lat,
        origin_lon=lon,
        pm25=180.0,
        wind_u=0.0,
        wind_v=0.0,
    )
    cells = {p.grid_id for p in result.grid_predictions}
    assert cells == {origin}


def test_cams_blend_sets_flag() -> None:
    origin = h3.latlng_to_cell(30.90, 75.85, 8)
    lat, lon = h3.cell_to_latlng(origin)
    result = forecast_event(
        _event(),
        origin_grid_id=origin,
        origin_lat=lat,
        origin_lon=lon,
        pm25=180.0,
        wind_u=5.0,
        wind_v=0.0,
        cams_pm25=90.0,
    )
    assert result.cams_applied is True
    assert result.grid_predictions[-1].pm25 < 180.0
