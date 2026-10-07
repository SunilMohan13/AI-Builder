"""CPCB as a replay-only plugin (CPCB publishes no free public API)."""

from __future__ import annotations

from aeropulse_connector_sdk.legacy import LegacyConnectorAdapter
from aeropulse_contracts import ProvenanceClass

from aeropulse_connector_cpcb.connector import CpcbConnector


def plugin() -> LegacyConnectorAdapter:
    return LegacyConnectorAdapter(
        "cpcb",
        CpcbConnector,
        supported_contracts=frozenset({"observation.v1"}),
        provenance_class=ProvenanceClass.MEASURED,
    )
