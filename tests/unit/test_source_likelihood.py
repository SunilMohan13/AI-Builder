"""Independent source-likelihood tests."""

from datetime import UTC, datetime

from aeropulse_contracts.feature import GridFeature
from aeropulse_intelligence.likelihood import score_sources


def _feature(**kwargs: object) -> GridFeature:
    base = {
        "grid_id": "g",
        "timestamp": datetime(2026, 9, 8, 5, tzinfo=UTC),
        "center_lat": 30.9,
        "center_lon": 75.85,
        "pm25": 186.0,
        "fire_count": 0,
        "fire_frp": 0.0,
        "upwind_fire_score": 0.0,
    }
    base.update(kwargs)
    return GridFeature.model_validate(base)


def test_fires_raise_biomass_not_industrial() -> None:
    with_fire = score_sources(
        _feature(fire_count=2, fire_frp=120.0, upwind_fire_score=0.8, wind_speed=4.0)
    )
    no_fire = score_sources(_feature(fire_count=0, fire_frp=0.0, wind_speed=1.0))
    assert with_fire.biomass_burning > no_fire.biomass_burning
    assert with_fire.industrial == no_fire.industrial
    total = (
        with_fire.biomass_burning
        + with_fire.industrial
        + with_fire.traffic
        + with_fire.dust
        + with_fire.regional_transport
    )
    assert total > 1.0 or with_fire.biomass_burning >= 0.5
