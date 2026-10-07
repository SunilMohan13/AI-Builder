"""Plugin discovery through the ``aeropulse.connectors`` entry-point group.

Each connector package declares, in its ``pyproject.toml``::

    [project.entry-points."aeropulse.connectors"]
    openaq = "aeropulse_connector_openaq.plugin:OpenAqPlugin"

The target is a class or zero-argument factory returning a
:class:`ConnectorPlugin`. Nothing here imports a connector by name.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from importlib.metadata import EntryPoint, entry_points

from aeropulse_common.errors import ConnectorError

from aeropulse_connector_sdk.plugin import ConnectorPlugin

ENTRY_POINT_GROUP = "aeropulse.connectors"

PluginFactory = Callable[[], ConnectorPlugin]


class UnknownSourceError(ConnectorError):
    """Raised when no installed plugin provides a source id."""

    def __init__(self, source_id: str) -> None:
        super().__init__(f"no connector plugin installed for source {source_id!r}")
        self.source_id = source_id


def _entry_points() -> Iterable[EntryPoint]:
    return entry_points(group=ENTRY_POINT_GROUP)


class PluginRegistry:
    """Source id -> plugin factory, from entry points plus explicit overrides."""

    def __init__(self, factories: dict[str, PluginFactory] | None = None) -> None:
        self._factories: dict[str, PluginFactory] = dict(factories or {})

    @classmethod
    def discover(cls) -> PluginRegistry:
        factories: dict[str, PluginFactory] = {}
        for ep in _entry_points():
            if ep.name in factories:
                raise ConnectorError(f"two plugins claim source id {ep.name!r}")
            factories[ep.name] = ep.load()
        return cls(factories)

    def register(self, source_id: str, factory: PluginFactory) -> None:
        self._factories[source_id] = factory

    def source_ids(self) -> list[str]:
        return sorted(self._factories)

    def create(self, source_id: str) -> ConnectorPlugin:
        try:
            factory = self._factories[source_id]
        except KeyError as exc:
            raise UnknownSourceError(source_id) from exc
        plugin = factory()
        if plugin.source_id != source_id:
            raise ConnectorError(
                f"entry point {source_id!r} built a plugin for {plugin.source_id!r}"
            )
        return plugin


def available_source_ids() -> list[str]:
    """Ids of every installed connector plugin."""
    return sorted({ep.name for ep in _entry_points()})
