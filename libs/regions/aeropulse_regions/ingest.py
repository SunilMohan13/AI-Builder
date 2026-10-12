"""Run every enabled source of one region through the shared ingest pipeline.

Used by the cycle and by the fixture dataset source, so replay, training and
serving read a region's sources the same way.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime, timedelta
from pathlib import Path

from aeropulse_connector_sdk.ingest import IngestOutcome, IngestPipeline
from aeropulse_connector_sdk.plugin import ConnectorMode
from aeropulse_connector_sdk.registry import PluginRegistry

from aeropulse_regions.context import build_context, provenance_for
from aeropulse_regions.models import RegionPack


def ingest_region(
    pack: RegionPack,
    *,
    mode: ConnectorMode,
    now: datetime,
    registry: PluginRegistry | None = None,
    pipeline: IngestPipeline | None = None,
    fixtures_root: Path | None = None,
    watermarks: dict[str, datetime] | None = None,
    run_id: str = "adhoc",
    lookback: timedelta | None = None,
    sources: Collection[str] | None = None,
) -> list[IngestOutcome]:
    """One outcome per enabled source, in pack order. A failure stays local.

    ``lookback`` widens each source's window to ``[now - lookback, now]``;
    ``None`` keeps the context's default. ``sources`` limits the run to those
    source ids; ``None`` runs every enabled source.
    """
    registry = registry or PluginRegistry.discover()
    pipeline = pipeline or IngestPipeline()
    outcomes: list[IngestOutcome] = []
    for entry in pack.sources:
        if not entry.enabled or (sources is not None and entry.id not in sources):
            continue
        context = build_context(
            pack,
            entry,
            mode=mode,
            now=now,
            fixtures_root=fixtures_root,
            watermark=(watermarks or {}).get(entry.id),
            run_id=run_id,
            **({"lookback": lookback} if lookback is not None else {}),
        )
        outcomes.append(
            pipeline.run(
                registry.create(entry.id),
                context,
                provenance_override=provenance_for(pack, entry.id),
            )
        )
    return outcomes
