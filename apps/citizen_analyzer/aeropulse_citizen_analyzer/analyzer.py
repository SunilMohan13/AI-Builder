"""Citizen report analysis, stage by stage (LLD APAC 9.1-9.7).

sanitize -> geo-trust -> AI visual observation -> environmental corroboration
-> decision -> (seed a plume, link an incident, citizen-watch alert).

Each stage writes its result to ``reports/{report_id}.json`` before the next
starts, so a failure leaves a partial analysis with reasons, not nothing. A
finished report is not analysed again. A report never creates or changes a
pollution event, prediction or label: the only things it can produce are its
own document, a plume, graph rows and a citizen-watch alert.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import h3
from aeropulse_contracts import Alert, RegionSnapshot
from aeropulse_contracts.citizen import (
    SMOKE_LIKE_CLASSES,
    CitizenAnalysis,
    CitizenDecision,
    CitizenReportDocument,
    Corroboration,
    GeoTrust,
    VisualClass,
    VisualObservation,
)
from aeropulse_contracts.plume import Plume
from aeropulse_contracts.provenance import ProvenanceClass
from aeropulse_contracts.snapshot import FireCluster
from aeropulse_intelligence.corroboration import (
    Environment,
    ReportPoint,
    corroborate,
    decide,
    plume_origin,
    watch_summary,
)
from aeropulse_intelligence.graph import GraphInputs, RegionGraph, build_graph
from aeropulse_intelligence.plume import simulate
from aeropulse_intelligence.plume.region import RegionTransport
from aeropulse_ml.datasets.history import read_raw_window
from aeropulse_ml.preprocessing.batch import RecordBatch
from aeropulse_observability import get_logger
from aeropulse_regions import CitizenSettings, RegionCatalog
from aeropulse_storage import Storage, batch_id, citizen_row
from aeropulse_vision import (
    RejectedImageError,
    SanitizedImage,
    VisualObserver,
    geo_trust,
    sanitize,
)

log = get_logger("aeropulse.citizen")

#: Setting: raw history read for wind and station series.
HISTORY_HOURS = 72
WATCH_SEVERITY = "WATCH"


class ReportNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class AnalysisOutcome:
    doc: CitizenReportDocument
    plume: Plume | None = None
    alert: Alert | None = None


class CitizenAnalyzer:
    def __init__(
        self,
        *,
        catalog: RegionCatalog,
        storage: Storage,
        settings: CitizenSettings,
        observer: VisualObserver,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        alert_sink: Callable[[Alert], None] | None = None,
    ) -> None:
        self.catalog = catalog
        self.storage = storage
        self.settings = settings
        self.observer = observer
        self.clock = clock
        self.alert_sink = alert_sink

    # --- entry points ---------------------------------------------------

    def analyze(self, report_id: str) -> AnalysisOutcome:
        doc = self._doc(report_id)
        if doc.analysis is not None and doc.analysis.decision is not None:
            return AnalysisOutcome(doc)
        if doc.incoming_key is None:
            doc = self._stage(report_id, degraded="no_media_uploaded", decision="operator_queue")
            return AnalysisOutcome(doc)

        try:
            image = sanitize(
                self.storage.citizen.read(doc.incoming_key),
                max_bytes=self.settings.upload.max_bytes,
                max_pixels=self.settings.upload.max_pixels,
                allowed_mime=self.settings.upload.allowed_mime,
            )
        except RejectedImageError as exc:
            doc = self._stage(
                report_id, degraded=f"image_rejected_{exc.reason}", decision="stored_operators_only"
            )
            return AnalysisOutcome(doc)
        doc = self._sanitized(report_id, image)

        geo = self._geo(doc, image)
        doc = self._stage(report_id, geo_trust=geo)

        observed = self.observer.observe(image, doc.observation_type)
        doc = self._stage(
            report_id, observation=observed.observation, degraded=observed.degraded_reasons
        )
        visual_class = doc.moderated_class or (
            observed.observation.visual_class if observed.observation else None
        )
        return self._conclude(doc, geo, visual_class, image.exif.img_direction_deg, accepted=False)

    def moderate(
        self,
        report_id: str,
        *,
        action: str,
        visual_class: VisualClass | None = None,
    ) -> AnalysisOutcome:
        """Operator moderation (LLD 9.6): ``accept``, ``reject`` or ``set_class``.

        Accepting a partial or corroborated report acts on it as a corroborated
        one would. An untrusted report never seeds anything, accepted or not.
        """
        doc = self._doc(report_id)
        if action == "reject":

            def rejected(d: CitizenReportDocument) -> CitizenReportDocument:
                d.moderation, d.status = "rejected", "moderated"
                d.analysis = _analysis(d)
                d.analysis.decision = "stored_operators_only"
                return d

            doc = self.storage.citizen.update(report_id, rejected)
            self._record(doc)
            return AnalysisOutcome(doc)
        if action not in ("accept", "set_class"):
            raise ValueError(f"unknown moderation action: {action!r}")

        def moderated(d: CitizenReportDocument) -> CitizenReportDocument:
            if visual_class is not None:
                d.moderated_class = visual_class
            if action == "accept":
                d.moderation = "accepted"
            d.status = "moderated"
            return d

        doc = self.storage.citizen.update(report_id, moderated)
        analysis = doc.analysis
        geo = analysis.geo_trust if analysis else None
        if geo is None:
            self._record(doc)
            return AnalysisOutcome(doc)
        current = doc.moderated_class or (
            analysis.observation.visual_class if analysis and analysis.observation else None
        )
        return self._conclude(
            doc, geo, current, self._direction(doc), accepted=doc.moderation == "accepted"
        )

    # --- stages ---------------------------------------------------------

    def _conclude(
        self,
        doc: CitizenReportDocument,
        geo: GeoTrust,
        visual_class: str | None,
        direction: float | None,
        *,
        accepted: bool,
    ) -> AnalysisOutcome:
        snapshot = self.storage.snapshots.latest(doc.region_id)
        corroboration: Corroboration | None = None
        degraded: list[str] = []
        point = ReportPoint(
            lat=doc.claimed_lat,
            lon=doc.claimed_lon,
            reference_time=geo.observed_at or doc.created_at,
            reference_is_capture=geo.observed_at is not None,
            img_direction_deg=direction,
        )
        fires = snapshot.fires if snapshot else []
        if visual_class in SMOKE_LIKE_CLASSES:
            if snapshot is None:
                degraded.append("no_live_snapshot")
            else:
                history = self._history(doc.region_id, point.reference_time)
                env = self._environment(snapshot, history)
                corroboration = corroborate(
                    point, visual_class or "", env, self.settings.corroboration
                )
        decision = decide(visual_class=visual_class, geo=geo, corroboration=corroboration)
        if (
            accepted
            and decision == "operator_queue"
            and geo.level != "untrusted"
            and corroboration is not None
            and corroboration.level != "uncorroborated"
        ):
            decision = "seed_plume"
        doc = self._stage(
            doc.report_id, corroboration=corroboration, decision=decision, degraded=degraded
        )

        plume: Plume | None = None
        alert: Alert | None = None
        if decision == "seed_plume" and corroboration is not None:
            plume, reason = self._seed(doc, point, corroboration, fires)
            incident = self._incident(snapshot, doc, corroboration) if snapshot else None
            doc = self._stage(
                doc.report_id,
                plume_id=plume.plume_id if plume else None,
                incident_id=incident,
                degraded=[reason] if reason else [],
            )
            if plume is not None:
                alert = self._watch(doc, plume)
                self._graph_rows(doc, plume, snapshot, fires)
        doc = self._finish(doc.report_id)
        self._record(doc)
        log.info(
            "citizen.analyzed",
            report_id=doc.report_id,
            region_id=doc.region_id,
            decision=decision,
            corroboration=corroboration.level if corroboration else None,
            plume=plume is not None,
            alert=alert is not None,
        )
        return AnalysisOutcome(doc, plume, alert)

    def _seed(
        self,
        doc: CitizenReportDocument,
        point: ReportPoint,
        corroboration: Corroboration,
        fires: Sequence[FireCluster],
    ) -> tuple[Plume | None, str | None]:
        transport = RegionTransport.load(self.catalog, doc.region_id)
        if transport is None:
            return None, "no_plume_profile_for_region"
        release = _floor_hour(point.reference_time)
        history = self._history(doc.region_id, release)
        inputs = transport.forward_inputs(history.forecasts, history.weather, release)
        if inputs is None:
            return None, "no_wind_for_plume"
        origin = plume_origin(
            doc.report_id,
            point,
            corroboration,
            fires,
            reporter_spread_km=self.settings.decision.reporter_origin_spread_km,
        )
        plume = simulate(
            region_id=doc.region_id,
            cycle_time=_floor_hour(self.clock()),
            direction="forward",
            origin=origin,
            horizons_hours=transport.forward_hours,
            inputs=inputs,
            release_time=point.reference_time,
        )
        self.storage.plumes.write(plume)
        return plume, None

    def _watch(self, doc: CitizenReportDocument, plume: Plume) -> Alert | None:
        """A citizen watch when the P90 footprint reaches a populated place soon enough."""
        within = self.settings.decision.watch_reach_hours
        reached = sorted(
            (
                a
                for a in plume.arrivals
                if a.eta_hours_median is not None
                and a.eta_hours_median <= within
                and (a.population is None or a.population > 0)
            ),
            key=lambda a: (a.eta_hours_median or 0.0, a.place_id),
        )
        if not reached:
            return None
        now = self.clock()
        names = ", ".join(a.name for a in reached)
        alert = Alert(
            alert_id=f"al_{doc.report_id}_watch",
            report_id=doc.report_id,
            severity=WATCH_SEVERITY,
            message_template="citizen_watch",
            message=(
                f"Citizen watch: a corroborated citizen photo ({doc.region_id}) seeds a plume "
                f"that may reach {names} within {within:g} h. AI observation, corroborated by "
                "environmental data; simulated transport, experimental."
            ),
            evidence=[
                {
                    "plume_id": plume.plume_id,
                    "model_version": plume.model_version,
                    "provenance_class": "simulated",
                    "places": [a.place_id for a in reached],
                }
            ],
            created_at=now,
            expires_at=now + timedelta(hours=within),
        )
        payload = alert.model_dump(mode="json")
        self.storage.analytics.load(
            "ops.alerts",
            [
                {
                    "cycle_id": None,
                    "region_id": doc.region_id,
                    "record": json.dumps(payload, sort_keys=True, default=str),
                }
            ],
            batch_id=batch_id(f"citizen_{doc.report_id}_alert", [payload]),
        )
        if self.alert_sink is not None:
            self.alert_sink(alert)
        return alert

    def _incident(
        self, snapshot: RegionSnapshot, doc: CitizenReportDocument, corroboration: Corroboration
    ) -> str | None:
        """The current incident sharing the matched fire or the report's cell."""
        rid = doc.region_id
        cell = h3.cell_to_parent(h3.latlng_to_cell(doc.claimed_lat, doc.claimed_lon, 8), 6)
        wanted = {f"cell:{cell}"}
        if corroboration.matched_fire_id:
            wanted.add(f"fire_cluster:{rid}:{corroboration.matched_fire_id}")
        for incident in sorted(snapshot.incidents, key=lambda i: i.incident_id):
            if wanted & set(incident.node_ids):
                return incident.incident_id
        return None

    def _graph_rows(
        self,
        doc: CitizenReportDocument,
        plume: Plume,
        snapshot: RegionSnapshot | None,
        fires: Sequence[FireCluster],
    ) -> None:
        """The report's own subgraph, written right after the analysis (LLD 10.2)."""
        summary = watch_summary(
            doc,
            round_decimals=self.settings.decision.public_round_decimals,
            plume_id=plume.plume_id,
        )
        if summary is None:
            return
        forward = [plume, *self._snapshot_plumes(snapshot)]
        graph = build_graph(
            GraphInputs(
                region_id=doc.region_id,
                cycle_time=plume.cycle_time,
                fires=fires,
                plumes=forward,
                citizen=[summary],
            )
        )
        node_id = f"citizen_report:{doc.region_id}:{doc.report_id}"
        load_subgraph(self.storage, graph, node_id, prefix=f"citizen_{doc.report_id}")

    # --- helpers --------------------------------------------------------

    def _doc(self, report_id: str) -> CitizenReportDocument:
        found = self.storage.citizen.get(report_id)
        if found is None:
            raise ReportNotFoundError(report_id)
        return found[0]

    def _sanitized(self, report_id: str, image: SanitizedImage) -> CitizenReportDocument:
        key = self.storage.citizen.put_sanitized(
            report_id, image.data, content_type=image.content_type
        )

        def change(d: CitizenReportDocument) -> CitizenReportDocument:
            d.sanitized_key = key
            d.status = "queued"
            d.analysis = _analysis(d)
            d.analysis.sha256 = image.sha256
            return d

        return self.storage.citizen.update(report_id, change)

    def _geo(self, doc: CitizenReportDocument, image: SanitizedImage) -> GeoTrust:
        first = self.storage.citizen.claim_hash(image.sha256, doc.report_id)
        return geo_trust(
            pack=self.catalog.get(doc.region_id),
            claimed_lat=doc.claimed_lat,
            claimed_lon=doc.claimed_lon,
            device_accuracy_m=doc.device_accuracy_m,
            received_at=doc.created_at,
            exif=image.exif,
            duplicate=first != doc.report_id,
            settings=self.settings.geo_trust,
        )

    def _direction(self, doc: CitizenReportDocument) -> float | None:
        """Camera bearing, re-read from the original (the sanitized copy has no EXIF)."""
        if doc.incoming_key is None:
            return None
        try:
            image = sanitize(
                self.storage.citizen.read(doc.incoming_key),
                max_bytes=self.settings.upload.max_bytes,
                max_pixels=self.settings.upload.max_pixels,
                allowed_mime=self.settings.upload.allowed_mime,
            )
        except RejectedImageError:
            return None
        return image.exif.img_direction_deg

    def _history(self, region_id: str, at: datetime) -> RecordBatch:
        return read_raw_window(
            self.storage.analytics,
            region_id,
            start=at - timedelta(hours=HISTORY_HOURS),
            end=at + timedelta(hours=1),
            max_bytes=self.storage.max_query_bytes,
        )

    def _environment(self, snapshot: RegionSnapshot, history: RecordBatch) -> Environment:
        series: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
        for obs in history.observations:
            if (
                obs.measurement.parameter == "pm25"
                and obs.grid_id is not None
                and obs.provenance.provenance_class == ProvenanceClass.MEASURED
            ):
                series[obs.grid_id].append((obs.observed_at, obs.measurement.value))
        return Environment(
            fires=snapshot.fires,
            wind=snapshot.wind,
            anomalies=snapshot.anomalies,
            cells=snapshot.cells,
            plumes=self._snapshot_plumes(snapshot),
            events=snapshot.events,
            station_series=series,
        )

    def _snapshot_plumes(self, snapshot: RegionSnapshot | None) -> list[Plume]:
        if snapshot is None:
            return []
        out: list[Plume] = []
        for summary in snapshot.plumes:
            if summary.direction != "forward":
                continue
            plume = self.storage.plumes.get(snapshot.region_id, summary.plume_id)
            if plume is not None:
                out.append(plume)
        return out

    def _stage(
        self,
        report_id: str,
        *,
        geo_trust: GeoTrust | None = None,
        observation: VisualObservation | None = None,
        corroboration: Corroboration | None = None,
        decision: CitizenDecision | None = None,
        plume_id: str | None = None,
        incident_id: str | None = None,
        degraded: Sequence[str] | str = (),
    ) -> CitizenReportDocument:
        reasons = [degraded] if isinstance(degraded, str) else list(degraded)

        def change(d: CitizenReportDocument) -> CitizenReportDocument:
            a = _analysis(d)
            if geo_trust is not None:
                a.geo_trust = geo_trust
            if observation is not None:
                a.observation = observation
            if corroboration is not None:
                a.corroboration = corroboration
            if decision is not None:
                a.decision = decision
            if plume_id is not None:
                a.plume_id = plume_id
            if incident_id is not None:
                a.incident_id = incident_id
            a.degraded_reasons += [r for r in reasons if r not in a.degraded_reasons]
            d.analysis = a
            return d

        return self.storage.citizen.update(report_id, change)

    def _finish(self, report_id: str) -> CitizenReportDocument:
        now = self.clock()

        def change(d: CitizenReportDocument) -> CitizenReportDocument:
            d.analysis = _analysis(d)
            d.analysis.analyzed_at = now
            if d.status != "moderated":
                d.status = "analyzed"
            return d

        return self.storage.citizen.update(report_id, change)

    def _record(self, doc: CitizenReportDocument) -> None:
        now = self.clock()
        row = citizen_row(
            doc, recorded_at=now, round_decimals=self.settings.decision.public_round_decimals
        )
        self.storage.analytics.load(
            "citizen.reports", [row], batch_id=batch_id(f"citizen_{doc.report_id}", [row])
        )


def _analysis(doc: CitizenReportDocument) -> CitizenAnalysis:
    return doc.analysis.model_copy(deep=True) if doc.analysis else CitizenAnalysis()


def _floor_hour(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def load_subgraph(storage: Storage, graph: RegionGraph, node_id: str, *, prefix: str) -> None:
    """Graph rows for one node, its edges and their endpoints."""
    edges = [e for e in graph.edges.values() if node_id in (e.src, e.dst)]
    ids = {node_id, *(e.src for e in edges), *(e.dst for e in edges)}
    base = {"cycle_id": None, "region_id": graph.region_id, "cycle_time": graph.cycle_time}
    nodes = [
        {**base, "node_id": n.node_id, "kind": n.kind, "record": n.model_dump_json()}
        for n in graph.nodes.values()
        if n.node_id in ids
    ]
    rows = [
        {
            **base,
            "edge_id": e.edge_id,
            "kind": e.kind,
            "src": e.src,
            "dst": e.dst,
            "record": e.model_dump_json(),
        }
        for e in edges
    ]
    storage.analytics.load("graph.nodes", nodes, batch_id=batch_id(f"{prefix}_nodes", nodes))
    storage.analytics.load("graph.edges", rows, batch_id=batch_id(f"{prefix}_edges", rows))
