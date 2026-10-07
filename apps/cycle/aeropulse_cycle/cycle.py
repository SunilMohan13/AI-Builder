"""One region, one cycle time (LLD APAC 3.4).

ingest -> archive raw -> load raw rows -> read the history window ->
preprocess at the cycle time -> detect -> features -> serve models or rules
-> plumes -> graph and incidents -> map layers -> write the snapshot
(versioned object, then the pointer) -> prediction, health, graph and cycle
rows -> alerts (live only).

Idempotent per ``(region_id, cycle_time, mode)``: the snapshot object is
overwritten, raw batches are keyed by their content, and the latest pointer
only moves forward. ``backfill`` never raises alerts or moves the pointer.
``replay`` reads recorded fixtures: it writes nothing to raw history or
analytics, and its snapshot lives under its own prefix, so fixture data can
never reach a Live view.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from aeropulse_connector_sdk.ingest import IngestOutcome, IngestPipeline
from aeropulse_connector_sdk.registry import PluginRegistry
from aeropulse_contracts import Alert, FieldStatus, RegionSnapshot, ServedModel
from aeropulse_contracts.feature_spec import HAZARD_24H, PM25_FORECAST
from aeropulse_contracts.snapshot import AnomalyFlag, CellForecast, HazardState
from aeropulse_intelligence.graph import GraphInputs, RegionGraph, build_graph, find_incidents
from aeropulse_intelligence.snapshot import MODEL_DERIVED_SOURCES
from aeropulse_ml.datasets.bigquery import TABLES as RAW_TABLES
from aeropulse_ml.datasets.history import read_raw_window
from aeropulse_ml.datasets.records import KINDS, encode
from aeropulse_ml.features.pipeline import FeatureContext, FeaturePipeline
from aeropulse_ml.preprocessing import PreprocessingPipeline
from aeropulse_ml.preprocessing.batch import PreprocessReport, RecordBatch
from aeropulse_ml.preprocessing.steps import identity
from aeropulse_ml.serving import (
    ModelResolver,
    serve_anomalies,
    serve_forecasts,
    serve_hazard,
    serve_source_likelihood,
)
from aeropulse_observability import get_logger
from aeropulse_regions import CitizenSettings, RegionCatalog, load_citizen_settings
from aeropulse_regions.ingest import ingest_region
from aeropulse_storage import Storage, batch_id
from aeropulse_storage.snapshots import SnapshotMode

from aeropulse_cycle.citizen import CitizenStage, seeded_reports
from aeropulse_cycle.detection import detect
from aeropulse_cycle.plumes import run_plumes
from aeropulse_cycle.views import cell_states, fire_clusters, wind_vectors

log = get_logger("aeropulse.cycle")

CycleMode = Literal["live", "backfill", "replay"]
CYCLE_MODES: tuple[CycleMode, ...] = ("live", "backfill", "replay")
#: Settings: raw history read back for features, lags and anomaly baselines.
#: The longest feature window is 24 h of lags over a 24 h rolling mean.
HISTORY_HOURS = 72
CYCLE_STEP = timedelta(hours=1)

AlertSink = Callable[[Alert], None]


def cycle_id(region_id: str, cycle_time: datetime, mode: CycleMode) -> str:
    return f"{region_id}_{cycle_time:%Y%m%dT%H%MZ}_{mode}"


def floor_hour(moment: datetime) -> datetime:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return aware.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


@dataclass
class CycleResult:
    cycle_id: str
    snapshot: RegionSnapshot
    snapshot_uri: str
    outcomes: list[IngestOutcome]
    preprocess: PreprocessReport
    alerts_raised: list[Alert] = field(default_factory=list)
    alerts_suppressed: int = 0
    rows_loaded: dict[str, int] = field(default_factory=dict)


class CycleRunner:
    def __init__(
        self,
        catalog: RegionCatalog,
        storage: Storage,
        *,
        resolver: ModelResolver | None = None,
        registry: PluginRegistry | None = None,
        fixtures_root: Path | None = None,
        alert_sink: AlertSink | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        history_hours: int = HISTORY_HOURS,
        citizen_settings: CitizenSettings | None = None,
    ) -> None:
        self.catalog = catalog
        self.storage = storage
        self.citizen_settings = citizen_settings or load_citizen_settings(catalog.config_dir)
        self.resolver = resolver or ModelResolver.from_config_dir(
            catalog, reader=storage.artifact_reader()
        )
        self.registry = registry
        self.fixtures_root = fixtures_root
        self.alert_sink = alert_sink
        self.clock = clock
        self.history_hours = history_hours

    # --- entry point ---------------------------------------------------

    def run(
        self,
        region_id: str,
        cycle_time: datetime,
        mode: CycleMode,
        *,
        previous: RegionSnapshot | None = None,
    ) -> CycleResult:
        """Run one cycle. ``previous`` defaults to the live pointer in live mode."""
        if mode not in CYCLE_MODES:
            raise ValueError(f"unknown cycle mode: {mode!r}")
        pack = self.catalog.get(region_id)
        t = floor_hour(cycle_time)
        cid = cycle_id(region_id, t, mode)
        keeps_history = mode != "replay"
        if previous is None and mode == "live":
            previous = self._previous(region_id, t)
        log.info("cycle.started", cycle_id=cid, region_id=region_id, mode=mode)

        outcomes = ingest_region(
            pack,
            mode=mode,
            now=self.clock() if mode == "live" else t,
            registry=self.registry,
            pipeline=IngestPipeline(self.storage.raw_archiver if keeps_history else None),
            fixtures_root=self.fixtures_root,
            watermarks=self._watermarks(region_id) if mode == "live" else None,
            run_id=cid,
        )
        fresh = RecordBatch.from_records(r for o in outcomes for r in o.records)
        loaded: dict[str, int] = {}
        if keeps_history:
            loaded = self._load_raw(fresh, cid)
            batch = self._merge(self._history(region_id, t), fresh)
        else:
            batch = fresh

        context = FeatureContext.for_region(self.catalog, region_id, as_of=t)
        cleaned, report = PreprocessingPipeline().run(batch, context.preprocess)
        display, _ = PreprocessingPipeline.for_display().run(batch, context.preprocess)

        detection = detect(
            cleaned,
            cycle_time=t,
            previous=previous,
            model_derived_sources=MODEL_DERIVED_SOURCES | set(pack.model_derived_sources),
            region_id=region_id,
        )
        forecasts, hazard, anomalies, likelihood, served = self._serve(batch, context, previous)
        snapshot_mode: SnapshotMode = "live" if mode == "live" else "backfill"
        fires = fire_clusters(cleaned, t)
        citizen = (
            seeded_reports(self.storage, self.citizen_settings, region_id, t)
            if keeps_history
            else CitizenStage(
                field_status=[
                    FieldStatus(field="citizen_watches", reason="citizen reports are not replayed")
                ]
            )
        )
        plumes = run_plumes(
            catalog=self.catalog,
            region_id=region_id,
            cycle_time=t,
            batch=cleaned,
            fires=fires,
            events=detection.events,
            anomalies=anomalies,
            store=self.storage.plumes if keeps_history else self.storage.replay_plumes,
            mode=snapshot_mode,
            citizen=citizen.origins(fires, self.citizen_settings),
        )
        watches = citizen.watches(plumes.plumes, self.citizen_settings)
        cells = cell_states(display, context.preprocess, self.catalog.aqi_for(region_id), t)
        graph = build_graph(
            GraphInputs(
                region_id=region_id,
                cycle_time=t,
                fires=fires,
                anomalies=anomalies,
                events=detection.events,
                plumes=plumes.plumes,
                cells=cells,
                citizen=watches,
            )
        )
        incidents = find_incidents(graph, previous.incidents if previous else ())

        snapshot = RegionSnapshot(
            region_id=region_id,
            cycle_time=t,
            cycle_id=cid,
            pack_version=pack.pack_version,
            mode=snapshot_mode,
            generated_at=self.clock(),
            cells=cells,
            fires=fires,
            wind=wind_vectors(cleaned, pack, t),
            forecasts=forecasts,
            hazard=hazard,
            anomalies=anomalies,
            source_likelihood=likelihood,
            plumes=plumes.summaries,
            incidents=incidents,
            citizen_watches=watches,
            events=detection.events,
            source_health=[o.health for o in outcomes if o.health is not None],
            served_models=served,
            field_status=[*plumes.field_status, *citizen.field_status],
        )

        if keeps_history:
            loaded.update(self._load_derived(snapshot, cid))
            loaded.update(self._load_graph(graph, cid))
        store = self.storage.snapshots if keeps_history else self.storage.replay_snapshots
        uri = store.write(snapshot)

        raised: list[Alert] = []
        if mode == "live":
            raised = detection.alerts
            if raised:
                loaded["ops.alerts"] = self.storage.analytics.load(
                    "ops.alerts",
                    [_row(cid, region_id, a.model_dump(mode="json")) for a in raised],
                    batch_id=batch_id(f"{cid}_alerts", [a.model_dump(mode="json") for a in raised]),
                )
                for alert in raised:
                    if self.alert_sink is not None:
                        self.alert_sink(alert)
        suppressed = 0 if mode == "live" else len(detection.alerts)

        if keeps_history:
            row = {
                "cycle_id": cid,
                "region_id": region_id,
                "cycle_time": t,
                "mode": mode,
                "generated_at": snapshot.generated_at,
                "snapshot_uri": uri,
                "records": len(fresh),
                "events": len(detection.events),
                "alerts_raised": len(raised),
                "alerts_suppressed": suppressed,
                "preprocess": json.dumps(report.to_dict(), sort_keys=True),
            }
            loaded["ops.cycles"] = self.storage.analytics.load(
                "ops.cycles", [row], batch_id=batch_id(f"{cid}_cycle", [row])
            )
        log.info(
            "cycle.finished",
            cycle_id=cid,
            region_id=region_id,
            mode=mode,
            records=len(fresh),
            cells=len(snapshot.cells),
            events=len(snapshot.events),
            plumes=len(snapshot.plumes),
            incidents=len(snapshot.incidents),
            alerts_raised=len(raised),
            alerts_suppressed=suppressed,
        )
        return CycleResult(
            cycle_id=cid,
            snapshot=snapshot,
            snapshot_uri=uri,
            outcomes=outcomes,
            preprocess=report,
            alerts_raised=raised,
            alerts_suppressed=suppressed,
            rows_loaded=loaded,
        )

    def backfill(self, region_id: str, start: datetime, end: datetime) -> list[CycleResult]:
        """Hourly backfill cycles over ``[start, end]``; open events carry forward."""
        results: list[CycleResult] = []
        previous: RegionSnapshot | None = None
        t = floor_hour(start)
        while t <= end:
            result = self.run(region_id, t, "backfill", previous=previous)
            previous = result.snapshot
            results.append(result)
            t += CYCLE_STEP
        return results

    # --- stages --------------------------------------------------------

    def _serve(
        self, batch: RecordBatch, context: FeatureContext, previous: RegionSnapshot | None
    ) -> tuple[
        list[CellForecast],
        list[HazardState],
        list[AnomalyFlag],
        list[Any],
        list[ServedModel],
    ]:
        region_id = context.region_id
        forecast_frame = FeaturePipeline(PM25_FORECAST).build(batch, context)
        hazard_frame = FeaturePipeline(HAZARD_24H).build(batch, context)
        forecasts, f_used = serve_forecasts(
            self.resolver.resolve("pm25_forecast", region_id), forecast_frame
        )
        hazard, h_used = serve_hazard(
            self.resolver.resolve("pm25_hazard_24h", region_id), hazard_frame
        )
        anomalies, a_used = serve_anomalies(
            self.resolver.resolve("anomaly", region_id),
            hazard_frame,
            previous.forecasts if previous is not None else (),
        )
        likelihood = serve_source_likelihood(self.catalog, region_id, hazard_frame)
        heuristic = self.resolver.resolve("source_likelihood", region_id)
        served = [s.to_contract() for s in (f_used, h_used, a_used, heuristic)]
        return forecasts, hazard, anomalies, likelihood, served

    def _previous(self, region_id: str, t: datetime) -> RegionSnapshot | None:
        """The snapshot before ``t``. A re-run of ``t`` must not read its own output."""
        latest = self.storage.snapshots.latest(region_id)
        if latest is None or latest.cycle_time < t:
            return latest
        before = t - CYCLE_STEP
        return self.storage.snapshots.get(region_id, before) or self.storage.snapshots.get(
            region_id, before, mode="backfill"
        )

    def _watermarks(self, region_id: str) -> dict[str, datetime]:
        rows = self.storage.analytics.query(
            "ops.source_health.watermarks",
            {"region_id": region_id},
            max_bytes=self.storage.max_query_bytes,
        )
        marks: dict[str, datetime] = {}
        for r in rows:
            value = r.get("watermark")
            moment = pd.Timestamp(value).to_pydatetime() if value is not None else None
            if isinstance(moment, datetime):
                marks[str(r["source_id"])] = moment
        return marks

    def _load_raw(self, fresh: RecordBatch, cid: str) -> dict[str, int]:
        loaded: dict[str, int] = {}
        for kind, table in RAW_TABLES.items():
            records = getattr(fresh, kind)
            if not records:
                continue
            frame = encode(records)
            rows = [
                {
                    "region_id": r["region_id"],
                    "known_at": pd.Timestamp(r["known_at"]).to_pydatetime(),
                    "record": r["record"],
                }
                for r in frame.to_dict(orient="records")
            ]
            # Keyed by record identity, not content: a re-fetch stamps a new
            # observation_id and received_at on the very same measurement.
            identities = [{"id": identity(r)} for r in records]
            name = f"raw.{table}"
            loaded[name] = self.storage.analytics.load(
                name, rows, batch_id=batch_id(f"{cid}_{table}", identities)
            )
        return loaded

    def _history(self, region_id: str, t: datetime) -> RecordBatch:
        return read_raw_window(
            self.storage.analytics,
            region_id,
            start=t - timedelta(hours=self.history_hours),
            end=t + CYCLE_STEP,
            max_bytes=self.storage.max_query_bytes,
        )

    @staticmethod
    def _merge(history: RecordBatch, fresh: RecordBatch) -> RecordBatch:
        """History plus this cycle's records; the dedup step drops repeats."""
        return RecordBatch().with_(
            **{kind: (*getattr(history, kind), *getattr(fresh, kind)) for kind in KINDS}
        )

    def _load_derived(self, snapshot: RegionSnapshot, cid: str) -> dict[str, int]:
        """Prediction and health rows: a run log, so readers take the newest ``generated_at``."""
        rows: list[dict[str, Any]] = []
        for family, records in (
            ("pm25_forecast", snapshot.forecasts),
            ("pm25_hazard_24h", snapshot.hazard),
            ("anomaly", snapshot.anomalies),
            ("source_likelihood", snapshot.source_likelihood),
        ):
            rows.extend(
                {
                    **_row(cid, snapshot.region_id, None),
                    "cycle_time": snapshot.cycle_time,
                    "generated_at": snapshot.generated_at,
                    "family": family,
                    "grid_id": getattr(r, "grid_id", None),
                    "record": r.model_dump_json(),
                }
                for r in records
            )
        health = [
            {
                **_row(cid, snapshot.region_id, None),
                "generated_at": snapshot.generated_at,
                **h.model_dump(mode="json"),
            }
            for h in snapshot.source_health
        ]
        loaded = {
            "predictions.served": self.storage.analytics.load(
                "predictions.served", rows, batch_id=batch_id(f"{cid}_predictions", rows)
            ),
            "ops.source_health": self.storage.analytics.load(
                "ops.source_health", health, batch_id=batch_id(f"{cid}_health", health)
            ),
        }
        return loaded

    def _load_graph(self, graph: RegionGraph, cid: str) -> dict[str, int]:
        """Graph rows (``aeropulse_graph.nodes`` / ``.edges``), one set per cycle."""
        base = {**_row(cid, graph.region_id, None), "cycle_time": graph.cycle_time}
        nodes = [
            {**base, "node_id": n.node_id, "kind": n.kind, "record": n.model_dump_json()}
            for n in graph.nodes.values()
        ]
        edges = [
            {
                **base,
                "edge_id": e.edge_id,
                "kind": e.kind,
                "src": e.src,
                "dst": e.dst,
                "record": e.model_dump_json(),
            }
            for e in graph.edges.values()
        ]
        return {
            "graph.nodes": self.storage.analytics.load(
                "graph.nodes", nodes, batch_id=batch_id(f"{cid}_graph_nodes", nodes)
            ),
            "graph.edges": self.storage.analytics.load(
                "graph.edges", edges, batch_id=batch_id(f"{cid}_graph_edges", edges)
            ),
        }


def _row(cid: str, region_id: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    row: dict[str, Any] = {"cycle_id": cid, "region_id": region_id}
    if payload is not None:
        row["record"] = json.dumps(payload, sort_keys=True, default=str)
    return row


class CycleFailedError(RuntimeError):
    def __init__(self, failures: dict[str, str], results: list[CycleResult]) -> None:
        super().__init__(f"cycle failed for {sorted(failures)}")
        self.failures = failures
        self.results = results


def run_many(
    runner: CycleRunner, region_ids: Iterable[str], cycle_time: datetime, mode: CycleMode
) -> list[CycleResult]:
    """One cycle per region; one region failing does not stop the others.

    Raises ``CycleFailedError`` after every region ran if any of them failed.
    """
    results: list[CycleResult] = []
    failures: dict[str, str] = {}
    for region_id in region_ids:
        try:
            results.append(runner.run(region_id, cycle_time, mode))
        except Exception as exc:  # region isolation; reported below, never swallowed
            # The type only: a message can carry a credential-bearing URL.
            failures[region_id] = type(exc).__name__
            log.error("cycle.failed", region_id=region_id, mode=mode, error=failures[region_id])
    if failures:
        raise CycleFailedError(failures, results)
    return results
