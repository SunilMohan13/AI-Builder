"""Plug-and-play connectors (LLD APAC 5).

Every source is discovered through the ``aeropulse.connectors`` entry point,
takes its geography from a ``ConnectorContext`` built from a Region Pack, and
runs through the one shared ``IngestPipeline``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from aeropulse_common.errors import ConnectorError
from aeropulse_common.settings import Settings
from aeropulse_connector_sdk import (
    BasePlugin,
    ConnectorContext,
    ConnectorResult,
    Domain,
    IngestPipeline,
    LegacyConnectorAdapter,
    PluginRegistry,
    Site,
    UnknownSourceError,
    available_source_ids,
    resolve_secret,
)
from aeropulse_connector_sdk.contracts import RawRecord
from aeropulse_contracts import (
    CanonicalRecord,
    FireObservation,
    MeteoForecast,
    Observation,
    ProvenanceClass,
    RasterObservation,
    SourceState,
)
from aeropulse_geospatial import to_grid_id
from aeropulse_regions import load_catalog
from aeropulse_regions.context import build_context, provenance_for

FIXTURES = Path("fixtures")
NOW = datetime(2026, 9, 9, tzinfo=UTC)


@pytest.fixture(scope="module")
def catalog() -> Any:
    return load_catalog()


@pytest.fixture(scope="module")
def registry() -> PluginRegistry:
    return PluginRegistry.discover()


def _context(catalog: Any, region_id: str, source_id: str, **kwargs: Any) -> ConnectorContext:
    pack = catalog.get(region_id)
    entry = pack.source(source_id)
    assert entry is not None
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("fixtures_root", FIXTURES)
    return build_context(pack, entry, mode=kwargs.pop("mode", "replay"), **kwargs)


def _run(registry: PluginRegistry, catalog: Any, region_id: str, source_id: str, **kw: Any):
    context = _context(catalog, region_id, source_id, **kw)
    plugin = registry.create(source_id)
    return IngestPipeline().run(
        plugin,
        context,
        provenance_override=provenance_for(catalog.get(region_id), source_id),
    )


# --- discovery ---


def test_every_shipped_source_is_discovered_through_entry_points() -> None:
    assert set(available_source_ids()) >= {"cpcb", "earthengine", "firms", "openaq", "openmeteo"}


def test_every_pack_source_has_an_installed_plugin(catalog: Any) -> None:
    installed = set(available_source_ids())
    for pack in catalog.packs.values():
        assert {s.id for s in pack.sources} <= installed, pack.region_id


def test_unknown_source_is_a_typed_error(registry: PluginRegistry) -> None:
    with pytest.raises(UnknownSourceError):
        registry.create("not-a-source")


def test_registered_plugin_must_declare_its_own_id() -> None:
    registry = PluginRegistry()
    registry.register("alias", lambda: _StubPlugin([]))
    with pytest.raises(ConnectorError, match="built a plugin for 'stub'"):
        registry.create("alias")


# --- replay per region ---


def test_openaq_replay_in_north_is_measured_and_stamped(
    registry: PluginRegistry, catalog: Any
) -> None:
    outcome = _run(registry, catalog, "in-north", "openaq")
    assert outcome.health is not None
    assert outcome.health.state == SourceState.REPLAY
    assert outcome.records
    for record in outcome.records:
        assert isinstance(record, Observation)
        assert record.region_id == "in-north"
        assert record.provenance.provenance_class == ProvenanceClass.MEASURED
        assert record.grid_id == to_grid_id(record.location.lat, record.location.lon)
        assert record.dedup_key


def test_firms_replay_in_north_returns_fires_inside_the_source_domain(
    registry: PluginRegistry, catalog: Any
) -> None:
    outcome = _run(registry, catalog, "in-north", "firms")
    bbox = catalog.get("in-north").source_domain.bbox
    assert outcome.records
    for record in outcome.records:
        assert isinstance(record, FireObservation)
        assert bbox[0] <= record.location.lon <= bbox[2]
        assert bbox[1] <= record.location.lat <= bbox[3]


def test_openmeteo_replay_is_model_derived_never_measured(
    registry: PluginRegistry, catalog: Any
) -> None:
    outcome = _run(registry, catalog, "in-north", "openmeteo")
    assert outcome.records
    assert {r.provenance.provenance_class for r in outcome.records} == {
        ProvenanceClass.MODEL_DERIVED
    }


@pytest.mark.parametrize("region_id", ["sg-singapore", "au-nsw"])
@pytest.mark.parametrize("source_id", ["openaq", "firms", "openmeteo"])
def test_regions_without_fixtures_are_not_configured_not_backfilled_with_india(
    registry: PluginRegistry, catalog: Any, region_id: str, source_id: str
) -> None:
    outcome = _run(registry, catalog, region_id, source_id)
    assert outcome.health is not None
    assert outcome.health.state == SourceState.NOT_CONFIGURED
    assert outcome.records == []


def test_live_without_a_key_is_not_configured(
    registry: PluginRegistry, catalog: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AEROPULSE_OPENAQ_API_KEY", raising=False)
    context = _context(catalog, "in-north", "openaq", mode="live")
    context = _with(context, resolver=lambda _ref: None)
    outcome = IngestPipeline().run(registry.create("openaq"), context)
    assert outcome.health is not None
    assert outcome.health.state == SourceState.NOT_CONFIGURED
    assert outcome.records == []


# --- forecasts: issued_at <= t ---


def _forecast_fixture(tmp_path: Path, *, issued_at: str | None) -> Path:
    payload = json.loads((FIXTURES / "openmeteo/observations.json").read_text())
    for record in payload["records"]:
        if issued_at is not None:
            record["issued_at"] = issued_at
    path = tmp_path / "openmeteo.json"
    path.write_text(json.dumps(payload))
    return path


def _openmeteo_context(catalog: Any, fixture: Path, now: datetime) -> ConnectorContext:
    context = _context(catalog, "in-north", "openmeteo", now=now)
    return _with(context, fixture_path=fixture)


def test_replay_forecasts_require_a_declared_issue_time(
    registry: PluginRegistry, catalog: Any, tmp_path: Path
) -> None:
    now = datetime(2026, 9, 7, 12, tzinfo=UTC)
    context = _openmeteo_context(catalog, _forecast_fixture(tmp_path, issued_at=None), now)
    outcome = IngestPipeline().run(registry.create("openmeteo"), context)
    assert not [r for r in outcome.records if isinstance(r, MeteoForecast)]


def test_replay_forecasts_are_issued_before_they_are_valid(
    registry: PluginRegistry, catalog: Any, tmp_path: Path
) -> None:
    now = datetime(2026, 9, 7, 12, tzinfo=UTC)
    fixture = _forecast_fixture(tmp_path, issued_at="2026-09-07T12:00")
    outcome = IngestPipeline().run(
        registry.create("openmeteo"), _openmeteo_context(catalog, fixture, now)
    )
    forecasts = [r for r in outcome.records if isinstance(r, MeteoForecast)]
    assert forecasts
    for forecast in forecasts:
        assert forecast.issued_at <= now < forecast.valid_at
        assert forecast.valid_at <= forecast.issued_at + timedelta(hours=48)
    observed = [r for r in outcome.records if not isinstance(r, MeteoForecast)]
    assert all(_time(r) <= now for r in observed)


def test_a_forecast_issued_after_the_cycle_is_never_emitted(
    registry: PluginRegistry, catalog: Any, tmp_path: Path
) -> None:
    now = datetime(2026, 9, 7, 12, tzinfo=UTC)
    fixture = _forecast_fixture(tmp_path, issued_at="2026-09-07T18:00")
    outcome = IngestPipeline().run(
        registry.create("openmeteo"), _openmeteo_context(catalog, fixture, now)
    )
    assert not [r for r in outcome.records if isinstance(r, MeteoForecast)]


def _time(record: CanonicalRecord) -> datetime:
    if isinstance(record, RasterObservation):
        return record.acquisition_time
    if isinstance(record, MeteoForecast):
        return record.valid_at
    return record.observed_at


# --- the shared pipeline ---


class _StubPlugin(BasePlugin):
    source_id = "stub"
    supported_contracts = frozenset({"observation.v1"})
    provenance_class = ProvenanceClass.MEASURED
    requires_credential = False
    live_capable = False

    def __init__(self, points: list[tuple[str, float, float]], *, fail: bool = False) -> None:
        self.points = points
        self.fail = fail

    def configuration_issue(self, context: ConnectorContext) -> str | None:
        return None

    def fetch(self, context: ConnectorContext) -> ConnectorResult:
        if self.fail:
            raise ConnectionError("https://example.invalid/?api_key=SHOULD-NOT-LEAK")
        records = [
            RawRecord(
                source_id="stub",
                source_record_id=rid,
                payload={"lat": lat, "lon": lon},
                fetched_at=context.now,
            )
            for rid, lat, lon in self.points
        ]
        return ConnectorResult(source_id="stub", records=records, fetched_at=context.now)

    def normalize(self, result: ConnectorResult, context: ConnectorContext) -> list[Any]:
        from aeropulse_contracts import Location, Measurement, Provenance, Quality

        out = []
        for raw in result.records:
            if raw.payload["lat"] is None:
                raise ValueError("no latitude")
            out.append(
                Observation(
                    observation_id=f"obs_{raw.source_record_id}",
                    source_id="stub",
                    source_record_id=raw.source_record_id.split("#")[0],
                    observed_at=context.now - timedelta(hours=1),
                    received_at=context.now,
                    location=Location(lat=raw.payload["lat"], lon=raw.payload["lon"]),
                    measurement=Measurement(parameter="pm25", value=40.0, unit="ug/m3"),
                    quality=Quality(quality_flag="valid", quality_score=1.0),
                    provenance=Provenance(
                        provider="stub",
                        connector_version="0",
                        provenance_class=ProvenanceClass.HEURISTIC,
                    ),
                )
            )
        return out


def _stub_context(**overrides: Any) -> ConnectorContext:
    base = ConnectorContext(
        region_id="zz-synthetic",
        bboxes={Domain.DISPLAY: (0.0, 0.0, 1.0, 1.0), Domain.SOURCE: (0.0, 0.0, 2.0, 2.0)},
        domain=Domain.DISPLAY,
        mode="replay",
        now=NOW,
        window_start=NOW - timedelta(hours=6),
        window_end=NOW,
    )
    return _with(base, **overrides)


def _with(context: ConnectorContext, **overrides: Any) -> ConnectorContext:
    from dataclasses import replace

    return replace(context, **overrides)


def _ids(records: list[CanonicalRecord]) -> list[str]:
    return [r.source_record_id for r in records if isinstance(r, Observation)]


def test_pipeline_rejects_records_outside_the_domain() -> None:
    plugin = _StubPlugin([("a", 0.5, 0.5), ("b", 1.5, 1.5)])
    outcome = IngestPipeline().run(plugin, _stub_context())
    assert _ids(outcome.records) == ["a"]
    assert [(r.source_record_id, r.reason) for r in outcome.rejected] == [("b", "outside_domain")]


def test_source_domain_widens_the_filter() -> None:
    plugin = _StubPlugin([("a", 0.5, 0.5), ("b", 1.5, 1.5)])
    outcome = IngestPipeline().run(plugin, _stub_context(domain=Domain.SOURCE))
    assert sorted(_ids(outcome.records)) == ["a", "b"]


def test_pipeline_dedups_on_the_canonical_key() -> None:
    plugin = _StubPlugin([("a", 0.5, 0.5), ("a#dup", 0.5, 0.5)])
    outcome = IngestPipeline().run(plugin, _stub_context())
    assert len(outcome.records) == 1


def test_region_provenance_overrides_the_plugin_default() -> None:
    plugin = _StubPlugin([("a", 0.5, 0.5)])
    plain = IngestPipeline().run(plugin, _stub_context())
    assert plain.records[0].provenance.provenance_class == ProvenanceClass.MEASURED
    over = IngestPipeline().run(
        plugin, _stub_context(), provenance_override=ProvenanceClass.MODEL_DERIVED
    )
    assert over.records[0].provenance.provenance_class == ProvenanceClass.MODEL_DERIVED


def test_a_bad_record_is_rejected_not_fatal() -> None:
    plugin = _StubPlugin([("a", 0.5, 0.5), ("bad", None, 0.5)])  # type: ignore[list-item]
    outcome = IngestPipeline().run(plugin, _stub_context())
    assert _ids(outcome.records) == ["a"]
    assert [(r.source_record_id, r.reason) for r in outcome.rejected] == [("bad", "ValueError")]


def test_all_rejected_is_degraded_not_healthy() -> None:
    plugin = _StubPlugin([("b", 1.5, 1.5)])
    outcome = IngestPipeline().run(plugin, _stub_context())
    assert outcome.health is not None
    assert outcome.health.state == SourceState.DEGRADED


def test_fetch_failure_is_isolated_and_never_leaks_the_message() -> None:
    outcome = IngestPipeline().run(_StubPlugin([], fail=True), _stub_context())
    assert outcome.health is not None
    assert outcome.health.state == SourceState.UNAVAILABLE
    assert outcome.health.reason == "fetch failed: ConnectionError"
    assert "SHOULD-NOT-LEAK" not in outcome.health.model_dump_json()


def test_raw_payload_is_archived_before_normalize() -> None:
    stored: dict[str, bytes] = {}

    def archive(key: str, body: bytes) -> str:
        stored[key] = body
        return f"mem://{key}"

    plugin = _StubPlugin([("a", 0.5, 0.5)])
    outcome = IngestPipeline(archiver=archive).run(plugin, _stub_context(run_id="r1"))
    assert outcome.raw_uri == "mem://raw/zz-synthetic/stub/2026/09/09/r1.json"
    assert json.loads(stored["raw/zz-synthetic/stub/2026/09/09/r1.json"])[0]["source_record_id"]


def test_health_watermark_is_the_newest_record() -> None:
    outcome = IngestPipeline().run(_StubPlugin([("a", 0.5, 0.5)]), _stub_context())
    assert outcome.health is not None
    assert outcome.health.watermark == NOW - timedelta(hours=1)
    assert outcome.health.records == 1


# --- Earth Engine ---


def test_earthengine_needs_a_project_and_the_library_for_live(catalog: Any) -> None:
    from aeropulse_connector_earthengine.plugin import EarthEnginePlugin

    context = _context(catalog, "in-north", "earthengine", mode="live")
    issue = EarthEnginePlugin(settings=Settings(earthengine_project=None)).configuration_issue(
        context
    )
    assert issue is not None


def test_earthengine_replay_without_a_fixture_is_not_configured(catalog: Any) -> None:
    from aeropulse_connector_earthengine.plugin import EarthEnginePlugin

    outcome = IngestPipeline().run(
        EarthEnginePlugin(), _context(catalog, "in-north", "earthengine")
    )
    assert outcome.health is not None
    assert outcome.health.state == SourceState.NOT_CONFIGURED


def test_earthengine_replay_maps_cells_to_aerosol_index(catalog: Any, tmp_path: Path) -> None:
    from aeropulse_connector_earthengine.plugin import EarthEnginePlugin

    cell = to_grid_id(29.0, 76.0)
    fixture = tmp_path / "ee.json"
    fixture.write_text(
        json.dumps(
            {
                "product": "s5p_aer_ai",
                "date": "2026-09-08",
                "cells": [
                    {"cell": cell, "mean": 1.25, "valid_fraction": 0.8},
                    {"cell": to_grid_id(29.1, 76.1), "mean": None, "valid_fraction": 0.0},
                ],
            }
        )
    )
    context = _with(_context(catalog, "in-north", "earthengine"), fixture_path=fixture)
    outcome = IngestPipeline().run(EarthEnginePlugin(), context)
    rasters = [r for r in outcome.records if isinstance(r, RasterObservation)]
    assert len(rasters) == 2
    by_cell = {r.grid_id: r for r in rasters}
    assert by_cell[cell].sample_aerosol_index == 1.25
    assert by_cell[cell].valid_pixel_fraction == 0.8
    assert by_cell[cell].region_id == "in-north"
    missing = next(r for r in rasters if r.grid_id != cell)
    assert missing.sample_aerosol_index is None
    assert missing.quality.quality_flag == "missing"


# --- credentials and legacy ---


def test_secret_refs_resolve_from_env_and_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOME_TEST_SECRET", "value-from-env")
    assert resolve_secret("env:SOME_TEST_SECRET") == "value-from-env"
    assert resolve_secret("env:MISSING_TEST_SECRET") is None
    assert resolve_secret(None) is None
    settings = Settings(openaq_api_key="from-settings")  # type: ignore[arg-type]
    assert resolve_secret("AEROPULSE_OPENAQ_API_KEY", settings=settings) == "from-settings"


def test_legacy_adapter_is_replay_only(catalog: Any) -> None:
    from aeropulse_connector_cpcb.plugin import plugin

    adapter = plugin()
    assert isinstance(adapter, LegacyConnectorAdapter)
    live = _context(catalog, "in-north", "cpcb", mode="live")
    assert adapter.configuration_issue(live) is not None
    replay = _context(catalog, "in-north", "cpcb")
    outcome = IngestPipeline().run(
        adapter, replay, provenance_override=provenance_for(catalog.get("in-north"), "cpcb")
    )
    assert outcome.health is not None
    assert outcome.health.state == SourceState.REPLAY
    assert outcome.records
    assert all(r.region_id == "in-north" for r in outcome.records)


def test_context_carries_the_packs_wind_sites(catalog: Any) -> None:
    context = _context(catalog, "sg-singapore", "openmeteo")
    assert context.domain == Domain.SOURCE
    assert len(context.sites) == 60
    assert all(isinstance(s, Site) for s in context.sites)
    assert any(s.in_display for s in context.sites)


# --- ingest -> preprocessing on the in-north fixtures ---


def test_in_north_replay_preprocesses_with_stations_over_cams(
    registry: PluginRegistry, catalog: Any
) -> None:
    from aeropulse_ml.preprocessing import (
        PreprocessContext,
        PreprocessingPipeline,
        hour_ending,
        label_observations,
    )

    pack = catalog.get("in-north")
    records: list[CanonicalRecord] = []
    for source_id in ("openaq", "cpcb", "openmeteo", "firms"):
        records.extend(_run(registry, catalog, "in-north", source_id).records)
    context = PreprocessContext.for_region(pack, as_of=NOW)
    batch, report = PreprocessingPipeline.for_display().run_records(records, context)

    labels = label_observations(batch, context)
    assert labels
    assert {o.source_id for o in labels} <= {"openaq", "cpcb"}

    def cell_hour(o: Observation) -> tuple[str | None, datetime, str]:
        return o.grid_id, hour_ending(o.observed_at), o.measurement.parameter

    stations = {cell_hour(o) for o in batch.observations if o.source_id != "openmeteo"}
    cams = [o for o in batch.observations if o.source_id == "openmeteo"]
    assert not [o for o in cams if cell_hour(o) in stations]
    assert all(r.region_id == "in-north" for r in batch.records())
    assert report.steps[0].rows_in == len(records)


def test_replay_fetches_at_the_cycle_time_not_the_wall_clock(
    registry: PluginRegistry, catalog: Any
) -> None:
    from aeropulse_ml.preprocessing import PreprocessContext, PreprocessingPipeline

    outcome = _run(registry, catalog, "in-north", "openmeteo")
    rasters = [r for r in outcome.records if isinstance(r, RasterObservation)]
    assert rasters
    assert {r.processing_time for r in rasters} == {NOW}
    context = PreprocessContext.for_region(catalog.get("in-north"), as_of=NOW)
    _, report = PreprocessingPipeline().run_records(outcome.records, context)
    assert not [k for k in report.dropped if k.startswith("leak:")]
