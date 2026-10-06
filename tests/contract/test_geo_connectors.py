"""INSAT/Bhuvan/ICAR/industry/OSM fixture connectors."""

from pathlib import Path

from aeropulse_connector_bhuvan import BhuvanConnector
from aeropulse_connector_icar import IcarConnector
from aeropulse_connector_industry import IndustryConnector
from aeropulse_connector_insat import InsatConnector
from aeropulse_connector_osm import OsmConnector
from aeropulse_connector_sdk.contracts import FetchRequest

ROOT = Path("fixtures")


def test_insat() -> None:
    raw = next(InsatConnector(ROOT / "insat" / "assets.json").fetch(FetchRequest()))
    obs = InsatConnector(ROOT / "insat" / "assets.json").normalize(raw)[0]
    assert obs.source_id == "insat"


def test_bhuvan_icar_industry_osm() -> None:
    for cls, folder, source in [
        (BhuvanConnector, "bhuvan", "bhuvan"),
        (IcarConnector, "icar", "icar"),
        (IndustryConnector, "industry", "industry"),
        (OsmConnector, "osm", "osm"),
    ]:
        connector = cls(ROOT / folder / "assets.json")
        raw = next(connector.fetch(FetchRequest()))
        obs = connector.normalize(raw)[0]
        assert obs.source_id == source
        assert obs.schema_version == "raster.v1"
