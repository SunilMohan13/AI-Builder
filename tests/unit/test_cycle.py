"""The region cycle (LLD APAC 3.4): idempotence, pointer rules, history, alerts."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aeropulse_common.errors import DatasetError
from aeropulse_common.settings import Settings, get_settings
from aeropulse_connector_sdk.plugin import ConnectorContext
from aeropulse_connector_sdk.registry import PluginRegistry
from aeropulse_contracts import Alert, EventStatus
from aeropulse_cycle import CycleFailedError, CycleRunner, cycle_id, floor_hour, run_many
from aeropulse_cycle.detection import seed_store
from aeropulse_cycle.main import main
from aeropulse_ml.datasets.parquet import ParquetDatasetSource
from aeropulse_regions import RegionCatalog, load_catalog
from aeropulse_storage import ParquetAnalyticsStore, Storage, build_storage
from replayed_registry import replayed_registry

T0 = datetime(2026, 9, 8, 6, tzinfo=UTC)
FIXTURES = Path("fixtures")


def _registry(seen: list[ConnectorContext], *, silent: bool = False) -> PluginRegistry:
    return replayed_registry(seen, silent=silent)


@pytest.fixture(scope="module")
def catalog() -> RegionCatalog:
    return load_catalog(Path("config"))


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return build_storage(Settings(data_dir=tmp_path))


def _runner(
    catalog: RegionCatalog,
    storage: Storage,
    *,
    seen: list[ConnectorContext] | None = None,
    silent: bool = False,
    alerts: list[Alert] | None = None,
    at: datetime = T0,
) -> CycleRunner:
    return CycleRunner(
        catalog,
        storage,
        registry=_registry(seen if seen is not None else [], silent=silent),
        fixtures_root=FIXTURES,
        alert_sink=(alerts.append if alerts is not None else None),
        clock=lambda: at + timedelta(minutes=5),
    )


def _raw_files(storage: Storage) -> list[Path]:
    analytics = storage.analytics
    assert isinstance(analytics, ParquetAnalyticsStore)
    return sorted((analytics.root / "raw").rglob("*.parquet"))


def test_cycle_ids_and_hours_are_deterministic() -> None:
    assert floor_hour(datetime(2026, 9, 8, 6, 59, 59, tzinfo=UTC)) == T0
    assert cycle_id("in-north", T0, "live") == "in-north_20260908T0600Z_live"


def test_replay_writes_no_history_and_never_touches_live(
    catalog: RegionCatalog, storage: Storage
) -> None:
    runner = CycleRunner(catalog, storage, fixtures_root=FIXTURES, clock=lambda: T0)
    result = runner.run("in-north", T0, "replay")
    assert result.snapshot.mode == "backfill"
    assert "replay-snapshots/in-north/" in result.snapshot_uri
    assert storage.snapshots.latest("in-north") is None
    assert storage.snapshots.get("in-north", T0) is None
    assert result.rows_loaded == {} and _raw_files(storage) == []
    assert result.alerts_raised == [] and result.alerts_suppressed > 0
    assert {h.state.value for h in result.snapshot.source_health} <= {"replay", "not_configured"}


def test_live_cycle_writes_history_snapshot_pointer_and_alerts(
    catalog: RegionCatalog, storage: Storage
) -> None:
    alerts: list[Alert] = []
    result = _runner(catalog, storage, alerts=alerts).run("in-north", T0, "live")
    snapshot = result.snapshot
    assert snapshot.mode == "live" and snapshot.cycle_id == "in-north_20260908T0600Z_live"
    latest = storage.snapshots.latest("in-north")
    assert latest is not None and latest.cycle_id == snapshot.cycle_id
    assert result.rows_loaded["raw.air_quality"] > 0
    assert result.rows_loaded["ops.cycles"] == 1
    assert result.rows_loaded["predictions.served"] > 0
    assert alerts == result.alerts_raised and result.alerts_suppressed == 0
    assert snapshot.cells and snapshot.events and snapshot.wind
    assert {h.state.value for h in snapshot.source_health} <= {"healthy", "not_configured"}


def test_training_reads_the_history_the_cycle_wrote(
    catalog: RegionCatalog, storage: Storage
) -> None:
    result = _runner(catalog, storage).run("in-north", T0, "live")
    analytics = storage.analytics
    assert isinstance(analytics, ParquetAnalyticsStore)
    batch = ParquetDatasetSource(analytics.root).load("in-north")
    assert len(batch.observations) == result.rows_loaded["raw.air_quality"]
    assert {o.region_id for o in batch.observations} == {"in-north"}
    with pytest.raises(DatasetError):
        ParquetDatasetSource(analytics.root / "empty").load("in-north")


def test_every_family_says_what_answered_and_why(catalog: RegionCatalog, storage: Storage) -> None:
    result = _runner(catalog, storage).run("in-north", T0, "live")
    served = {m.family: m for m in result.snapshot.served_models}
    assert set(served) == {"pm25_forecast", "pm25_hazard_24h", "anomaly", "source_likelihood"}
    for family in ("pm25_forecast", "pm25_hazard_24h", "anomaly"):
        assert served[family].degraded and served[family].degraded_reason
    assert served["source_likelihood"].calibrated is False
    for state in result.snapshot.hazard:
        assert state.calibrated is False, "a rule score is a rank, never a probability"


def test_rerunning_a_live_cycle_is_idempotent(catalog: RegionCatalog, storage: Storage) -> None:
    first = _runner(catalog, storage).run("in-north", T0, "live")
    files = _raw_files(storage)
    again = _runner(catalog, storage).run("in-north", T0, "live")
    assert _raw_files(storage) == files, "identical raw batches are not duplicated"
    assert first.snapshot.events, "the fixtures open events"
    assert [e.event_id for e in again.snapshot.events] == [
        e.event_id for e in first.snapshot.events
    ], "a re-run reproduces the same event ids"
    assert [e.created_at for e in again.snapshot.events] == [
        e.created_at for e in first.snapshot.events
    ]
    assert [a.alert_id for a in again.alerts_raised] == [a.alert_id for a in first.alerts_raised]
    snapshots = storage.objects["serving"]
    assert snapshots.get(f"snapshots/in-north/{T0:%Y%m%dT%H%M%SZ}.json").generation == 2
    latest = storage.snapshots.latest("in-north")
    assert latest is not None and latest.generated_at == again.snapshot.generated_at


def test_next_live_cycle_reads_watermarks_history_and_open_events(
    catalog: RegionCatalog, storage: Storage
) -> None:
    first = _runner(catalog, storage).run("in-north", T0, "live")
    seen: list[ConnectorContext] = []
    t1 = T0 + timedelta(hours=1)
    second = _runner(catalog, storage, seen=seen, silent=True, at=t1).run("in-north", t1, "live")
    watermarks = {c.watermark for c in seen if c.watermark is not None}
    assert watermarks, "live cycles resume from the stored watermarks"
    assert second.snapshot.cells, "with no new records the cells come from raw history"
    assert any(c.pm25 is not None for c in second.snapshot.cells)
    open_first = {
        e.event_id
        for e in first.snapshot.events
        if e.status not in (EventStatus.RESOLVED, EventStatus.REJECTED)
    }
    assert open_first, "the fixtures open events"
    assert open_first <= {e.event_id for e in second.snapshot.events}


def test_the_cycle_builds_the_graph_and_keeps_incident_ids(
    catalog: RegionCatalog, storage: Storage
) -> None:
    first = _runner(catalog, storage).run("in-north", T0, "live")
    assert first.rows_loaded["graph.nodes"] > 0 and first.rows_loaded["graph.edges"] > 0
    assert all(s.field != "incidents" for s in first.snapshot.field_status)
    incidents = first.snapshot.incidents
    assert incidents, "the fixtures' active events and plumes make incidents"
    for incident in incidents:
        assert set(incident.node_ids) <= {n.node_id for n in incident.nodes}
        assert incident.first_seen == T0

    again = _runner(catalog, storage).run("in-north", T0, "live")
    assert [i.incident_id for i in again.snapshot.incidents] == [i.incident_id for i in incidents]

    t1 = T0 + timedelta(hours=1)
    later = _runner(catalog, storage, silent=True, at=t1).run("in-north", t1, "live")
    kept = {i.incident_id for i in incidents} & {i.incident_id for i in later.snapshot.incidents}
    assert kept, "overlapping components keep their incident ids"
    for incident in later.snapshot.incidents:
        if incident.incident_id in kept:
            assert incident.first_seen == T0 and incident.last_updated == t1


def test_closed_events_are_not_carried_forward(catalog: RegionCatalog, storage: Storage) -> None:
    first = _runner(catalog, storage).run("in-north", T0, "live").snapshot
    closed = first.model_copy(deep=True)
    for event in closed.events:
        event.status = EventStatus.RESOLVED
    assert seed_store(closed).events == {}
    store = seed_store(first)
    assert set(store.events) == {e.event_id for e in first.events}
    for event in first.events:
        for cell in event.grid_ids:
            assert store.open_by_grid[cell] == event.event_id


def test_backfill_never_moves_the_pointer_or_raises_alerts(
    catalog: RegionCatalog, storage: Storage
) -> None:
    alerts: list[Alert] = []
    runner = _runner(catalog, storage, alerts=alerts)
    runner.run("in-north", T0, "live")
    sent = list(alerts)
    results = runner.backfill("in-north", T0 - timedelta(hours=1), T0 + timedelta(hours=1))
    assert [r.snapshot.cycle_time for r in results] == [
        T0 - timedelta(hours=1),
        T0,
        T0 + timedelta(hours=1),
    ]
    assert all(r.snapshot.mode == "backfill" and r.alerts_raised == [] for r in results)
    assert alerts == sent, "backfill must not reach the alert sink"
    latest = storage.snapshots.latest("in-north")
    assert latest is not None and latest.cycle_time == T0 and latest.mode == "live"
    assert storage.snapshots.get("in-north", T0 + timedelta(hours=1)) is None
    assert storage.snapshots.get("in-north", T0 + timedelta(hours=1), mode="backfill") is not None


def test_an_older_live_cycle_does_not_replace_a_newer_pointer(
    catalog: RegionCatalog, storage: Storage
) -> None:
    t1 = T0 + timedelta(hours=1)
    _runner(catalog, storage, at=t1).run("in-north", t1, "live")
    _runner(catalog, storage).run("in-north", T0, "live")
    latest = storage.snapshots.latest("in-north")
    assert latest is not None and latest.cycle_time == t1


def test_unknown_mode_is_refused(catalog: RegionCatalog, storage: Storage) -> None:
    with pytest.raises(ValueError, match="unknown cycle mode"):
        _runner(catalog, storage).run("in-north", T0, "demo")  # type: ignore[arg-type]


def test_one_failing_region_does_not_stop_the_others(
    catalog: RegionCatalog, storage: Storage
) -> None:
    runner = _runner(catalog, storage)
    with pytest.raises(CycleFailedError) as info:
        run_many(runner, ["no-such-region", "in-north"], T0, "replay")
    assert set(info.value.failures) == {"no-such-region"}
    assert [r.snapshot.region_id for r in info.value.results] == ["in-north"]


def test_cli_replay_prints_a_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("AEROPULSE_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    code = main(["--region", "in-north", "--mode", "replay", "--cycle-time", "2026-09-08T06:00Z"])
    assert code == 0
    (line,) = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("{")]
    summary = json.loads(line)
    assert summary["cycle_id"] == "in-north_20260908T0600Z_replay"
    assert summary["mode"] == "backfill" and summary["alerts_raised"] == 0
    assert set(summary["served"]) == {
        "pm25_forecast",
        "pm25_hazard_24h",
        "anomaly",
        "source_likelihood",
    }
