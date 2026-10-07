"""Region-aware connector plugins (LLD APAC 5.1).

A plugin knows one provider and nothing about geography: the cycle builds a
:class:`ConnectorContext` from the Region Pack and the plugin reads the bbox,
sites, window, params, and credential from it. Plugins register under the
``aeropulse.connectors`` entry-point group, so adding a source means adding
a package, not editing a registry.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from aeropulse_contracts import CanonicalRecord, ProvenanceClass, SourceHealth, SourceState

from aeropulse_connector_sdk.contracts import RawRecord
from aeropulse_connector_sdk.credentials import CredentialResolver, resolve_secret

BBox = tuple[float, float, float, float]
ConnectorMode = Literal["live", "replay", "backfill"]


class Domain(StrEnum):
    """Which area a connector queries."""

    DISPLAY = "display"
    SOURCE = "source"


@dataclass(frozen=True)
class Site:
    """A point a connector samples (wind sites, monitor locations)."""

    site_id: str
    lat: float
    lon: float
    in_display: bool = True


@dataclass(frozen=True)
class ConnectorContext:
    """Everything a plugin may know about the run it is part of.

    Attributes:
        region_id: Region the run belongs to.
        bboxes: Display and source-domain bboxes as (min_lon, min_lat,
            max_lon, max_lat).
        domain: Which bbox this source queries.
        mode: ``live`` hits the network; ``replay`` reads ``fixture_path``;
            ``backfill`` hits the network for a historical window.
        now: The cycle time. In replay this is the replayed instant, so
            "future" means after the cycle, not after the wall clock.
        window_start / window_end: Requested observation window.
        watermark: Latest observation time already ingested for this
            region and source.
        params: The pack's ``params`` for this source.
        secret_ref: The pack's secret *name*; resolve with :meth:`credential`.
        fixture_path: Region-specific replay payload, if the pack names one.
        sites: Sample points (Open-Meteo wind sites).
        run_id: Cycle id, stamped into raw archive keys and provenance.
    """

    region_id: str
    bboxes: Mapping[Domain, BBox]
    domain: Domain = Domain.DISPLAY
    mode: ConnectorMode = "replay"
    now: datetime = field(default_factory=lambda: datetime.now(UTC))
    window_start: datetime | None = None
    window_end: datetime | None = None
    watermark: datetime | None = None
    params: Mapping[str, Any] = field(default_factory=dict)
    secret_ref: str | None = None
    fixture_path: Path | None = None
    sites: tuple[Site, ...] = ()
    run_id: str = "adhoc"
    resolver: CredentialResolver = field(default=resolve_secret)

    @property
    def bbox(self) -> BBox:
        """The bbox for this source's domain."""
        return self.bboxes[self.domain]

    @property
    def is_network(self) -> bool:
        return self.mode in ("live", "backfill")

    def credential(self) -> str | None:
        """Resolve the secret at call time; never stored on the context."""
        return self.resolver(self.secret_ref)

    def param(self, name: str, default: Any = None) -> Any:
        return self.params.get(name, default)


@dataclass
class ConnectorResult:
    """What one fetch returned, before normalization."""

    source_id: str
    records: list[RawRecord]
    fetched_at: datetime
    state: SourceState = SourceState.HEALTHY
    reason: str | None = None


@runtime_checkable
class ConnectorPlugin(Protocol):
    """The contract every data source implements."""

    source_id: str
    supported_contracts: frozenset[str]
    #: Default provenance class; the pack's ground-truth and model-derived
    #: lists override it per region.
    provenance_class: ProvenanceClass

    def configuration_issue(self, context: ConnectorContext) -> str | None:
        """Why this source cannot run under ``context``, or ``None`` if it can."""
        ...

    def fetch(self, context: ConnectorContext) -> ConnectorResult: ...

    def normalize(
        self, result: ConnectorResult, context: ConnectorContext
    ) -> list[CanonicalRecord]: ...

    def health(self, context: ConnectorContext) -> SourceHealth: ...


class BasePlugin:
    """Shared behaviour: replay needs a fixture, live may need a credential."""

    source_id: str = ""
    supported_contracts: frozenset[str] = frozenset()
    provenance_class: ProvenanceClass = ProvenanceClass.MEASURED
    #: Whether a network fetch needs a credential from ``secret_ref``.
    requires_credential: bool = False
    #: Whether a network path exists at all.
    live_capable: bool = True

    def is_configured(self, context: ConnectorContext) -> bool:
        return self.configuration_issue(context) is None

    def configuration_issue(self, context: ConnectorContext) -> str | None:
        if not context.is_network:
            if context.fixture_path is None:
                return f"no replay fixture for {self.source_id} in {context.region_id}"
            if not context.fixture_path.exists():
                return f"replay fixture missing: {context.fixture_path.name}"
            return None
        if not self.live_capable:
            return f"{self.source_id} has no live API"
        if self.requires_credential and context.credential() is None:
            return f"{context.secret_ref or 'credential'} is not set"
        return None

    def health(self, context: ConnectorContext) -> SourceHealth:
        issue = self.configuration_issue(context)
        if issue is not None:
            return SourceHealth(
                source_id=self.source_id,
                region_id=context.region_id,
                state=SourceState.NOT_CONFIGURED,
                reason=issue,
            )
        state = SourceState.HEALTHY if context.is_network else SourceState.REPLAY
        return SourceHealth(source_id=self.source_id, region_id=context.region_id, state=state)
