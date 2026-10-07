"""OpenAQ as a region-aware plugin: bbox, parameters, and key from the context."""

from __future__ import annotations

from aeropulse_connector_sdk.contracts import FetchRequest
from aeropulse_connector_sdk.plugin import BasePlugin, ConnectorContext, ConnectorResult
from aeropulse_contracts import CanonicalRecord, ProvenanceClass

from aeropulse_connector_openaq.connector import (
    DEFAULT_MAX_LOCATIONS,
    SOURCE_ID,
    OpenAqConnector,
)


class OpenAqPlugin(BasePlugin):
    source_id = SOURCE_ID
    supported_contracts = frozenset({"observation.v1"})
    provenance_class = ProvenanceClass.MEASURED
    requires_credential = True

    def __init__(self) -> None:
        self._connector: OpenAqConnector | None = None
        self._context: ConnectorContext | None = None

    def _build(self, context: ConnectorContext) -> OpenAqConnector:
        if self._connector is None or self._context is not context:
            self._context = context
            self._connector = OpenAqConnector(
                context.fixture_path,
                bbox=context.bbox,
                max_locations=int(context.param("max_locations", DEFAULT_MAX_LOCATIONS)),
                live=context.is_network,
                api_key=context.credential() if context.is_network else None,
                parameters=context.param("parameters"),
                monitor_only=bool(context.param("monitor_only", True)),
            )
        return self._connector

    def fetch(self, context: ConnectorContext) -> ConnectorResult:
        connector = self._build(context)
        records = list(
            connector.fetch(
                FetchRequest(
                    start_time=context.window_start,
                    end_time=context.window_end,
                    bbox=context.bbox,
                )
            )
        )
        return ConnectorResult(source_id=SOURCE_ID, records=records, fetched_at=context.now)

    def normalize(
        self, result: ConnectorResult, context: ConnectorContext
    ) -> list[CanonicalRecord]:
        connector = self._build(context)
        out: list[CanonicalRecord] = []
        for record in result.records:
            out.extend(connector.normalize(record))
        return out
