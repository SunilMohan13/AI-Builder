"""Run a pre-plugin ``DataConnector`` behind the :class:`ConnectorPlugin` contract.

Used for fixture-only sources (CPCB) so they can sit in a Region Pack
without a rewrite. The adapter is replay-only: a legacy connector has no
region-aware network path, so in live mode it reports "not configured".
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from aeropulse_contracts import CanonicalRecord, ProvenanceClass

from aeropulse_connector_sdk.base import DataConnector
from aeropulse_connector_sdk.contracts import FetchRequest
from aeropulse_connector_sdk.plugin import BasePlugin, ConnectorContext, ConnectorResult


class LegacyConnectorAdapter(BasePlugin):
    """Wrap ``factory(fixture_path) -> DataConnector`` as a replay-only plugin."""

    live_capable = False

    def __init__(
        self,
        source_id: str,
        factory: Callable[[Path | None], DataConnector],
        *,
        supported_contracts: frozenset[str],
        provenance_class: ProvenanceClass = ProvenanceClass.MEASURED,
    ) -> None:
        self.source_id = source_id
        self._factory = factory
        self.supported_contracts = supported_contracts
        self.provenance_class = provenance_class
        self._connector: DataConnector | None = None
        self._context: ConnectorContext | None = None

    def _build(self, context: ConnectorContext) -> DataConnector:
        if self._connector is None or self._context is not context:
            self._context = context
            self._connector = self._factory(context.fixture_path)
        return self._connector

    def fetch(self, context: ConnectorContext) -> ConnectorResult:
        connector = self._build(context)
        request = FetchRequest(
            start_time=context.window_start,
            end_time=context.window_end,
            bbox=context.bbox,
            processing_mode="BACKFILL" if context.mode == "backfill" else "LIVE",
        )
        # Legacy connectors stamp the wall clock; the cycle's clock is the context's.
        records = [
            r.model_copy(update={"fetched_at": context.now}) for r in connector.fetch(request)
        ]
        return ConnectorResult(source_id=self.source_id, records=records, fetched_at=context.now)

    def normalize(
        self, result: ConnectorResult, context: ConnectorContext
    ) -> list[CanonicalRecord]:
        connector = self._build(context)
        out: list[CanonicalRecord] = []
        for record in result.records:
            out.extend(connector.normalize(record))  # type: ignore[arg-type]
        return out
