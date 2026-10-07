"""A live-mode connector registry whose network fetches are answered from replay fixtures.

Used where the live cycle code must run with no network and no credentials:
the golden tests and the Demo recording. The cycle sees ``mode="live"``
(watermarks, history, the live pointer); each plugin is handed
``mode="replay"`` so it reads its committed fixture instead of the provider.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from aeropulse_connector_sdk.plugin import ConnectorContext, ConnectorResult
from aeropulse_connector_sdk.registry import PluginRegistry


class Recorded:
    """A real plugin whose network fetch is answered from its replay fixture."""

    def __init__(self, inner: Any, seen: list[ConnectorContext], *, silent: bool) -> None:
        self.inner = inner
        self.seen = seen
        self.silent = silent
        self.source_id = inner.source_id
        self.supported_contracts = inner.supported_contracts
        self.provenance_class = inner.provenance_class

    def _replay(self, context: ConnectorContext) -> ConnectorContext:
        return replace(context, mode="replay")

    def configuration_issue(self, context: ConnectorContext) -> str | None:
        return self.inner.configuration_issue(self._replay(context))

    def fetch(self, context: ConnectorContext) -> ConnectorResult:
        self.seen.append(context)
        if self.silent:
            return ConnectorResult(source_id=self.source_id, records=[], fetched_at=context.now)
        return self.inner.fetch(self._replay(context))

    def normalize(self, result: ConnectorResult, context: ConnectorContext) -> list[Any]:
        return self.inner.normalize(result, self._replay(context))

    def health(self, context: ConnectorContext) -> Any:
        return self.inner.health(self._replay(context))


def replayed_registry(
    seen: list[ConnectorContext] | None = None, *, silent: bool = False
) -> PluginRegistry:
    """Every discovered plugin, wrapped so its fetch reads the replay fixture.

    Args:
        seen: Collects each context a fetch received, for assertions.
        silent: Fetch nothing at all (an outage), keeping health and normalize.
    """
    real = PluginRegistry.discover()
    log = seen if seen is not None else []
    return PluginRegistry(
        {
            sid: (lambda sid=sid: Recorded(real.create(sid), log, silent=silent))
            for sid in real.source_ids()
        }
    )
