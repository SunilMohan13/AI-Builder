"""Plug-and-play data connector SDK.

New sources implement ``ConnectorPlugin`` (region-aware, context-driven) and
register under the ``aeropulse.connectors`` entry point. ``DataConnector``
is the pre-plugin interface, kept for the legacy runner and wrapped by
``LegacyConnectorAdapter``.
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
from aeropulse_connector_sdk.credentials import resolve_secret
from aeropulse_connector_sdk.ingest import IngestOutcome, IngestPipeline, Rejection
from aeropulse_connector_sdk.legacy import LegacyConnectorAdapter
from aeropulse_connector_sdk.plugin import (
    BasePlugin,
    ConnectorContext,
    ConnectorPlugin,
    ConnectorResult,
    Domain,
    Site,
)
from aeropulse_connector_sdk.quality import QualityResult, evaluate_observation
from aeropulse_connector_sdk.registry import (
    PluginRegistry,
    UnknownSourceError,
    available_source_ids,
)
from aeropulse_connector_sdk.retry import retry_http
from aeropulse_connector_sdk.testing import (
    FixtureMissingError,
    load_fixture,
    load_yaml_metadata,
)

__all__ = [
    "BasePlugin",
    "CircuitBreaker",
    "CircuitState",
    "ConnectorContext",
    "ConnectorMetadata",
    "ConnectorPlugin",
    "ConnectorResult",
    "DataConnector",
    "Domain",
    "FetchRequest",
    "FixtureMissingError",
    "HealthStatus",
    "IngestOutcome",
    "IngestPipeline",
    "LegacyConnectorAdapter",
    "PluginRegistry",
    "QualityResult",
    "RawRecord",
    "Rejection",
    "Site",
    "SourceAsset",
    "UnknownSourceError",
    "available_source_ids",
    "evaluate_observation",
    "load_fixture",
    "load_yaml_metadata",
    "resolve_secret",
    "retry_http",
]
