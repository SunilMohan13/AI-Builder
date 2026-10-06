"""Plug-and-play data connector SDK.

New sources implement ``DataConnector`` and map payloads to canonical contracts.
"""

from aeropulse_connector_sdk.base import DataConnector
from aeropulse_connector_sdk.circuit import CircuitBreaker, CircuitState
from aeropulse_connector_sdk.contracts import (
    ConnectorMetadata,
    FetchRequest,
    HealthStatus,
    RawRecord,
    SourceAsset,
)
from aeropulse_connector_sdk.quality import QualityResult, evaluate_observation
from aeropulse_connector_sdk.retry import retry_http
from aeropulse_connector_sdk.testing import (
    FixtureMissingError,
    load_fixture,
    load_yaml_metadata,
)

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "ConnectorMetadata",
    "DataConnector",
    "FetchRequest",
    "FixtureMissingError",
    "HealthStatus",
    "QualityResult",
    "RawRecord",
    "SourceAsset",
    "evaluate_observation",
    "load_fixture",
    "load_yaml_metadata",
    "retry_http",
]
