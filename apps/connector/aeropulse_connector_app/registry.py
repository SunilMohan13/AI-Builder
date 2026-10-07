"""Declarative source registry for the connector runner.

The runner used to pin one Kafka topic per connector, hardcoded at the call
site. That is why Open-Meteo was never wired in: it emits three contracts
(air quality, weather and an AOD raster) from a single fetch, and there was
nowhere to put the second and third. Topic is therefore derived from the
contract instance here, not declared per source.

Credentials are referenced by *setting name* only. Never put a secret value
in this module.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from aeropulse_common.topics import (
    OBSERVATION_AQ,
    OBSERVATION_FIRE,
    OBSERVATION_RASTER,
    OBSERVATION_WEATHER,
)
from aeropulse_connector_bhuvan import BhuvanConnector
from aeropulse_connector_cams import CamsConnector
from aeropulse_connector_cpcb import CpcbConnector
from aeropulse_connector_firms import FirmsConnector
from aeropulse_connector_icar import IcarConnector
from aeropulse_connector_imd import ImdConnector
from aeropulse_connector_industry import IndustryConnector
from aeropulse_connector_insat import InsatConnector
from aeropulse_connector_modis import ModisConnector
from aeropulse_connector_openaq import OpenAqConnector
from aeropulse_connector_openmeteo import OpenMeteoConnector
from aeropulse_connector_osm import OsmConnector
from aeropulse_connector_sdk.base import DataConnector
from aeropulse_connector_sentinel5p import Sentinel5PConnector
from aeropulse_contracts.fire import FireObservation
from aeropulse_contracts.meteo import MeteorologicalObservation
from aeropulse_contracts.observation import Observation
from aeropulse_contracts.raster import RasterObservation

STATIONS_JSON = "stations.json"
PRODUCTS_JSON = "products.json"
ASSETS_JSON = "assets.json"


@dataclass(frozen=True)
class SourceSpec:
    """How to build and run one source for a cycle.

    Attributes:
        source_id: Registry id, matching ``config/sources.yaml``.
        factory: Builds the connector from an optional fixture path.
        fixture_rel: Fixture location relative to the fixtures root, or None
            for a source with no replay payload.
        live_capable: Whether the connector implements a real upstream fetch.
        credential_setting: Name of the ``Settings`` attribute holding this
            source's credential, or None when it needs none. A name, never a
            value.
        archive_raw: Copy the raw payload to object storage and stamp
            ``raw_object_uri`` on every observation it produces.
    """

    source_id: str
    factory: Callable[[Path | None], DataConnector]
    fixture_rel: str | None
    live_capable: bool = False
    credential_setting: str | None = None
    archive_raw: bool = False

    def build(self, fixtures_root: Path) -> DataConnector:
        """Instantiate the connector for this cycle."""
        return self.factory(self.fixture_path(fixtures_root))

    def fixture_path(self, fixtures_root: Path) -> Path | None:
        """Resolve the fixture path against a fixtures root."""
        if self.fixture_rel is None:
            return None
        return fixtures_root / self.fixture_rel


#: Contract type -> Kafka topic. Deriving the topic from what a connector
#: actually produced is what allows one source to emit several contracts.
_TOPIC_BY_CONTRACT: tuple[tuple[type, str], ...] = (
    (Observation, OBSERVATION_AQ),
    (FireObservation, OBSERVATION_FIRE),
    (MeteorologicalObservation, OBSERVATION_WEATHER),
    (RasterObservation, OBSERVATION_RASTER),
)


def topic_for(observation: object) -> str:
    """Return the Kafka topic for a canonical observation.

    Args:
        observation: A canonical contract instance.

    Returns:
        The topic name.

    Raises:
        TypeError: The object is not a recognised canonical contract.
    """
    for contract, topic in _TOPIC_BY_CONTRACT:
        if isinstance(observation, contract):
            return topic
    raise TypeError(f"no topic for contract type {type(observation).__name__}")


SOURCE_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec(
        source_id="cpcb",
        factory=CpcbConnector,
        fixture_rel=f"cpcb/{STATIONS_JSON}",
        archive_raw=True,
    ),
    SourceSpec(
        source_id="firms",
        factory=FirmsConnector,
        fixture_rel="firms/fires.json",
        live_capable=True,
        credential_setting="firms_map_key",
    ),
    SourceSpec(source_id="imd", factory=ImdConnector, fixture_rel="imd/weather.json"),
    SourceSpec(
        source_id="openaq",
        factory=OpenAqConnector,
        fixture_rel="openaq/latest.json",
        live_capable=True,
        credential_setting="openaq_api_key",
    ),
    SourceSpec(
        source_id="openmeteo",
        factory=OpenMeteoConnector,
        fixture_rel="openmeteo/observations.json",
        live_capable=True,
    ),
    SourceSpec(
        source_id="sentinel5p",
        factory=Sentinel5PConnector,
        fixture_rel=f"sentinel5p/{PRODUCTS_JSON}",
    ),
    SourceSpec(source_id="modis", factory=ModisConnector, fixture_rel=f"modis/{PRODUCTS_JSON}"),
    SourceSpec(source_id="cams", factory=CamsConnector, fixture_rel=f"cams/{PRODUCTS_JSON}"),
    SourceSpec(source_id="insat", factory=InsatConnector, fixture_rel=f"insat/{ASSETS_JSON}"),
    SourceSpec(source_id="bhuvan", factory=BhuvanConnector, fixture_rel=f"bhuvan/{ASSETS_JSON}"),
    SourceSpec(source_id="icar", factory=IcarConnector, fixture_rel=f"icar/{ASSETS_JSON}"),
    SourceSpec(
        source_id="industry",
        factory=IndustryConnector,
        fixture_rel=f"industry/{ASSETS_JSON}",
    ),
    SourceSpec(source_id="osm", factory=OsmConnector, fixture_rel=f"osm/{ASSETS_JSON}"),
)

SPECS_BY_ID: dict[str, SourceSpec] = {spec.source_id: spec for spec in SOURCE_SPECS}
