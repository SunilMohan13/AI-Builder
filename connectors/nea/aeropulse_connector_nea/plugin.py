"""NEA PM2.5 as a region-aware plugin: window and bbox from the context."""

from __future__ import annotations

from aeropulse_connector_sdk.live_http import LiveHttpClient
from aeropulse_connector_sdk.plugin import BasePlugin, ConnectorContext, ConnectorResult
from aeropulse_contracts import CanonicalRecord, ProvenanceClass

from aeropulse_connector_nea.connector import (
    SOURCE_ID,
    JsonGetter,
    fetch_fixture,
    fetch_live,
    normalize,
)


class NeaPlugin(BasePlugin):
    source_id = SOURCE_ID
    supported_contracts = frozenset({"observation.v1"})
    provenance_class = ProvenanceClass.MEASURED
    requires_credential = False

    def __init__(self, client: JsonGetter | None = None) -> None:
        self._client = client

    @property
    def client(self) -> JsonGetter:
        if self._client is None:
            # The plugin path decides network mode from the context.
            self._client = LiveHttpClient(
                SOURCE_ID, rate_per_second=1.0, timeout=20.0, require_live_mode=False
            )
        return self._client

    def fetch(self, context: ConnectorContext) -> ConnectorResult:
        if not context.is_network:
            fixture = context.fixture_path
            records = list(fetch_fixture(fixture, fetched_at=context.now)) if fixture else []
        else:
            start = context.window_start or context.now
            end = context.window_end or context.now
            records = list(fetch_live(self.client, start, end, fetched_at=context.now))
        return ConnectorResult(source_id=SOURCE_ID, records=records, fetched_at=context.now)

    def normalize(
        self, result: ConnectorResult, context: ConnectorContext
    ) -> list[CanonicalRecord]:
        out: list[CanonicalRecord] = []
        for record in result.records:
            out.extend(
                normalize(
                    record,
                    bbox=context.bbox,
                    start=context.window_start,
                    end=context.window_end,
                )
            )
        return out
