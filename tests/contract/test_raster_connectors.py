"""Satellite connector fixture → raster.v1 tests."""

from pathlib import Path

from aeropulse_connector_cams import CamsConnector
from aeropulse_connector_modis import ModisConnector
from aeropulse_connector_sdk.contracts import FetchRequest
from aeropulse_connector_sentinel5p import Sentinel5PConnector

ROOT = Path("fixtures")


def test_sentinel5p_normalizes() -> None:
    connector = Sentinel5PConnector(ROOT / "sentinel5p" / "products.json")
    raw = next(connector.fetch(FetchRequest()))
    obs = connector.normalize(raw)[0]
    assert obs.schema_version == "raster.v1"
    assert obs.sample_no2 is not None
    assert obs.cloud_fraction is not None


def test_modis_aod_is_not_pm25() -> None:
    connector = ModisConnector(ROOT / "modis" / "products.json")
    raw = next(connector.fetch(FetchRequest()))
    obs = connector.normalize(raw)[0]
    assert obs.sample_aod == 0.62
    assert obs.sample_pm25 is None


def test_cams_has_background_pm25() -> None:
    connector = CamsConnector(ROOT / "cams" / "products.json")
    raw = next(connector.fetch(FetchRequest()))
    obs = connector.normalize(raw)[0]
    assert obs.sample_pm25 == 95.0
