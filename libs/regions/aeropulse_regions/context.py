"""Build a :class:`ConnectorContext` from a Region Pack entry.

This is the only place a pack's geography reaches a connector.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from aeropulse_connector_sdk.plugin import ConnectorContext, ConnectorMode, Domain, Site
from aeropulse_contracts import ProvenanceClass

from aeropulse_regions.models import RegionPack, SourceEntry
from aeropulse_regions.sites import wind_sites


def provenance_for(pack: RegionPack, source_id: str) -> ProvenanceClass | None:
    """Region-level provenance: ground truth is measured; model output is not."""
    if source_id in pack.ground_truth_sources:
        return ProvenanceClass.MEASURED
    if source_id in pack.model_derived_sources:
        return ProvenanceClass.MODEL_DERIVED
    return None


def build_context(
    pack: RegionPack,
    entry: SourceEntry,
    *,
    mode: ConnectorMode,
    now: datetime | None = None,
    fixtures_root: Path | None = None,
    watermark: datetime | None = None,
    lookback: timedelta = timedelta(hours=48),
    run_id: str = "adhoc",
) -> ConnectorContext:
    """Context for running ``entry`` in ``pack``'s region."""
    cycle_time = now or datetime.now(UTC)
    fixture = None
    if entry.fixture is not None and fixtures_root is not None:
        fixture = fixtures_root / entry.fixture
    sites = tuple(
        Site(site_id=s.site_id, lat=s.lat, lon=s.lon, in_display=s.in_display)
        for s in wind_sites(pack)
    )
    return ConnectorContext(
        region_id=pack.region_id,
        bboxes={Domain.DISPLAY: pack.geometry.bbox, Domain.SOURCE: pack.source_domain.bbox},
        domain=Domain(entry.domain),
        mode=mode,
        now=cycle_time,
        window_start=watermark or (cycle_time - lookback),
        window_end=cycle_time,
        watermark=watermark,
        params=dict(entry.params),
        secret_ref=entry.secret_ref,
        fixture_path=fixture,
        sites=sites,
        run_id=run_id,
    )
