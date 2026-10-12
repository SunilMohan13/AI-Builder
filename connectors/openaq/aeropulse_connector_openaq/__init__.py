"""OpenAQ v3 connector for reference-grade ground-station air quality."""

from aeropulse_connector_openaq.connector import (
    BASE_URL,
    CANONICAL_UNIT,
    DEFAULT_BBOX,
    DEFAULT_MAX_LOCATIONS,
    DISCOVERY_PAGE_SIZE,
    HISTORY_PAGE_SIZE,
    LOCATIONS_URL,
    SENSORS_URL,
    SOURCE_ID,
    SUPPORTED_PARAMETERS,
    OpenAqConnector,
)

__all__ = [
    "BASE_URL",
    "CANONICAL_UNIT",
    "DEFAULT_BBOX",
    "DEFAULT_MAX_LOCATIONS",
    "DISCOVERY_PAGE_SIZE",
    "HISTORY_PAGE_SIZE",
    "LOCATIONS_URL",
    "SENSORS_URL",
    "SOURCE_ID",
    "SUPPORTED_PARAMETERS",
    "OpenAqConnector",
]
