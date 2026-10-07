"""Open-Meteo as a region-aware plugin.

Sites are the pack's wind sites (display area plus coarse source-domain
sites), never a hardcoded corridor. Past hours become observations; hours
after the model run become ``meteo_forecast.v1`` with ``issued_at``, so the
feature builder can enforce ``issued_at <= t``.
"""

from __future__ import annotations

from aeropulse_connector_sdk.contracts import FetchRequest
from aeropulse_connector_sdk.plugin import BasePlugin, ConnectorContext, ConnectorResult
from aeropulse_contracts import CanonicalRecord, ProvenanceClass

from aeropulse_connector_openmeteo.connector import SOURCE_ID, OpenMeteoConnector


class OpenMeteoPlugin(BasePlugin):
    source_id = SOURCE_ID
    supported_contracts = frozenset(
        {"observation.v1", "meteo.v1", "raster.v1", "meteo_forecast.v1"}
    )
    #: CAMS-derived air quality and NWP weather: model output, never a label.
    provenance_class = ProvenanceClass.MODEL_DERIVED
    requires_credential = False

    def configuration_issue(self, context: ConnectorContext) -> str | None:
        issue = super().configuration_issue(context)
        if issue is None and context.is_network and not context.sites:
            return f"no wind sites placed for {context.region_id}"
        return issue

    def _connector(self, context: ConnectorContext) -> OpenMeteoConnector:
        sites = [
            {"site_id": s.site_id, "name": s.site_id, "lat": s.lat, "lon": s.lon}
            for s in context.sites
        ]
        return OpenMeteoConnector(
            context.fixture_path,
            sites=sites or None,
            live=context.is_network,
            past_days=int(context.param("past_days", 2)),
            keep_forecast_hours=int(context.param("keep_forecast_hours", 0)),
            reference_time=context.now,
        )

    def fetch(self, context: ConnectorContext) -> ConnectorResult:
        request = FetchRequest(start_time=context.window_start, end_time=context.window_end)
        records = list(self._connector(context).fetch(request))
        return ConnectorResult(source_id=SOURCE_ID, records=records, fetched_at=context.now)

    def normalize(
        self, result: ConnectorResult, context: ConnectorContext
    ) -> list[CanonicalRecord]:
        connector = self._connector(context)
        out: list[CanonicalRecord] = []
        for record in result.records:
            out.extend(connector.normalize(record))
        return out
