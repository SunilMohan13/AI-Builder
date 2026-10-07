"""FIRMS as a region-aware plugin.

Queries the source domain (so Singapore watches Sumatra and Borneo) for
every product the pack lists, NOAA-20 and SNPP by default. Detections from
two satellites over the same fire are distinct records; clustering, not
ingest, merges them.
"""

from __future__ import annotations

from aeropulse_connector_sdk.contracts import FetchRequest, RawRecord
from aeropulse_connector_sdk.plugin import BasePlugin, ConnectorContext, ConnectorResult
from aeropulse_contracts import CanonicalRecord, ProvenanceClass

from aeropulse_connector_firms.connector import DEFAULT_PRODUCT, SOURCE_ID, FirmsConnector


class FirmsPlugin(BasePlugin):
    source_id = SOURCE_ID
    supported_contracts = frozenset({"fire_observation.v1"})
    provenance_class = ProvenanceClass.MEASURED
    requires_credential = True

    def _connector(self, context: ConnectorContext, product: str) -> FirmsConnector:
        return FirmsConnector(
            context.fixture_path,
            bbox=context.bbox,
            product=product,
            live=context.is_network,
            map_key=context.credential() if context.is_network else None,
            day_range=context.param("day_range"),
        )

    def _products(self, context: ConnectorContext) -> list[str]:
        products = context.param("products") or [DEFAULT_PRODUCT]
        return [str(p) for p in products]

    def fetch(self, context: ConnectorContext) -> ConnectorResult:
        request = FetchRequest(
            start_time=context.window_start, end_time=context.window_end, bbox=context.bbox
        )
        records: list[RawRecord] = []
        # Replay has one fixture covering every product.
        products = self._products(context) if context.is_network else [DEFAULT_PRODUCT]
        for product in products:
            records.extend(self._connector(context, product).fetch(request))
        return ConnectorResult(source_id=SOURCE_ID, records=records, fetched_at=context.now)

    def normalize(
        self, result: ConnectorResult, context: ConnectorContext
    ) -> list[CanonicalRecord]:
        connector = self._connector(context, DEFAULT_PRODUCT)
        out: list[CanonicalRecord] = []
        for record in result.records:
            out.extend(connector.normalize(record))
        return out
