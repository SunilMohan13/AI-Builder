"""Grid feature builder tests."""

from datetime import UTC, datetime
from pathlib import Path

from aeropulse_connector_cpcb import CpcbConnector
from aeropulse_connector_firms import FirmsConnector
from aeropulse_connector_imd import ImdConnector
from aeropulse_connector_sdk.contracts import FetchRequest
from aeropulse_geospatial.grid import to_grid_id
from aeropulse_intelligence.features import build_features
from aeropulse_intelligence.snapshot import FeatureSnapshot

ROOT = Path("fixtures")


def test_ludhiana_features_include_fires() -> None:
    cpcb = CpcbConnector(ROOT / "cpcb" / "stations.json")
    firms = FirmsConnector(ROOT / "firms" / "fires.json")
    imd = ImdConnector(ROOT / "imd" / "weather.json")
    aq = []
    for raw in cpcb.fetch(FetchRequest()):
        aq.extend(cpcb.normalize(raw))
    fires = []
    for raw in firms.fetch(FetchRequest()):
        fires.extend(firms.normalize(raw))
    wx = []
    for raw in imd.fetch(FetchRequest()):
        wx.extend(imd.normalize(raw))
    ludhiana = next(
        o
        for o in aq
        if o.source_record_id.startswith("PB014") and o.measurement.parameter == "pm25"
    )
    grid_id = to_grid_id(ludhiana.location.lat, ludhiana.location.lon)
    feature = build_features(
        grid_id,
        datetime(2026, 9, 8, 5, tzinfo=UTC),
        FeatureSnapshot(air_quality=aq, fires=fires, weather=wx),
        center_lat=ludhiana.location.lat,
        center_lon=ludhiana.location.lon,
    )
    assert feature.pm25 == 186.0
    assert feature.fire_count >= 1
    assert 0.0 <= feature.upwind_fire_score <= 1.0
    assert feature.aod is None
