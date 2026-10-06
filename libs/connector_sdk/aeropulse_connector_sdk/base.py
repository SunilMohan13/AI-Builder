"""Abstract base connector. Source-specific code lives in connectors/."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence

from aeropulse_connector_sdk.contracts import (
    ConnectorMetadata,
    FetchRequest,
    HealthStatus,
    RawRecord,
    SourceAsset,
)


class DataConnector(ABC):
    """Convert a source-specific stream into canonical observations.

    Implementations must not leak source payload shapes past ``normalize``.
    """

    @abstractmethod
    def metadata(self) -> ConnectorMetadata:
        """Return static connector identity."""

    @abstractmethod
    def discover(self) -> list[SourceAsset]:
        """List stations, products, or spatial assets this connector covers."""

    @abstractmethod
    def fetch(self, request: FetchRequest) -> Iterator[RawRecord]:
        """Yield source-native records for the requested window."""

    @abstractmethod
    def normalize(self, record: RawRecord) -> Sequence[object]:
        """Map a raw record to one or more canonical contracts.

        Returns:
            Observation, FireObservation, and/or MeteorologicalObservation instances.
        """

    @abstractmethod
    def health_check(self) -> HealthStatus:
        """Return current connector health without mutating checkpoints."""
