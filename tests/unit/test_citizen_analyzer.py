"""Citizen analyzer end to end (LLD APAC 9.1-9.7, 9.11) with a stub observer.

A real live cycle over the in-north fixtures gives the snapshot and raw
history; the analyzer then runs on generated EXIF JPEGs and the committed
Delhi PNG (no EXIF). The stub observer stands in for Gemini.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import pytest
from aeropulse_citizen_analyzer.analyzer import CitizenAnalyzer, ReportNotFoundError
from aeropulse_citizen_analyzer.main import build_observer, keyword_baseline, run_eval
from aeropulse_citizen_analyzer.push import create_app, object_name
from aeropulse_common.errors import RegionPackError
from aeropulse_common.settings import Settings
from aeropulse_contracts import Alert, RegionSnapshot
from aeropulse_contracts.citizen import CitizenReportDocument, VisualObservation
from aeropulse_contracts.plume import PlaceArrival
from aeropulse_cycle import CycleRunner
from aeropulse_regions import RegionCatalog, load_catalog, load_citizen_settings
from aeropulse_regions.citizen import CitizenSettings
from aeropulse_storage import ParquetAnalyticsStore, Storage, build_storage
from aeropulse_storage.errors import PreconditionFailedError
from aeropulse_vision import UNAVAILABLE, ObserverResult, SanitizedImage, UnavailableObserver
from aeropulse_vision.sanitize import has_metadata
from fastapi.testclient import TestClient
from replayed_registry import replayed_registry
from test_vision import jpeg_with_exif

T0 = datetime(2026, 9, 8, 6, tzinfo=UTC)
CONFIG = Path("config")
DELHI_PNG = Path("fixtures/citizen/sample-haze-delhi.png")
#: West of the fixture fire cluster at (30.12, 75.71); the camera looks east.
PUNJAB = (30.10, 75.55)
PUNJAB_FIRE = "863d16dafffffff:20260908T0440Z"


class StubObserver:
    provenance_class: Literal["ai_observation"] = "ai_observation"
    version = "stub-observer-1"

    def __init__(self, visual_class: str | None = "smoke_plume") -> None:
        self.visual_class = visual_class
        self.calls = 0

    def observe(self, image: SanitizedImage, observation_type: str) -> ObserverResult:
        self.calls += 1
        assert not has_metadata(image.data), "the observer only ever sees the sanitized copy"
        if self.visual_class is None:
            return ObserverResult(None, (UNAVAILABLE,))
        return ObserverResult(
            VisualObservation(
                visual_class=self.visual_class,  # type: ignore[arg-type]
                visual_certainty="high",
                likely_source_type="agricultural_field",
                image_quality="good",
                scene_summary="Smoke rising over a field.",
                observer_version=self.version,
            )
        )


@pytest.fixture(scope="module")
def catalog() -> RegionCatalog:
    return load_catalog(CONFIG)


@pytest.fixture(scope="module")
def settings() -> CitizenSettings:
    return load_citizen_settings(CONFIG)


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return build_storage(Settings(data_dir=tmp_path))


def _cycle(
    catalog: RegionCatalog, storage: Storage, at: datetime = T0, *, silent: bool = False
) -> RegionSnapshot:
    runner = CycleRunner(
        catalog,
        storage,
        registry=replayed_registry(silent=silent),
        fixtures_root=Path("fixtures"),
        clock=lambda: at + timedelta(minutes=5),
    )
    return runner.run("in-north", at, "live").snapshot


def _analyzer(
    catalog: RegionCatalog,
    storage: Storage,
    settings: CitizenSettings,
    observer: Any = None,
    alerts: list[Alert] | None = None,
) -> CitizenAnalyzer:
    return CitizenAnalyzer(
        catalog=catalog,
        storage=storage,
        settings=settings,
        observer=observer or StubObserver(),
        clock=lambda: T0 + timedelta(minutes=12),
        alert_sink=alerts.append if alerts is not None else None,
    )


def _report(
    storage: Storage,
    report_id: str,
    region_id: str,
    lat: float,
    lon: float,
    image: bytes | None,
    *,
    created_at: datetime = T0 + timedelta(minutes=10),
    content_type: str = "image/jpeg",
) -> CitizenReportDocument:
    doc = CitizenReportDocument(
        report_id=report_id,
        region_id=region_id,
        reporter_hash="salted-hash",
        claimed_lat=lat,
        claimed_lon=lon,
        device_accuracy_m=15.0,
        observation_type="smoke",
        created_at=created_at,
    )
    store = storage.citizen
    store.create(doc)
    if image is not None:
        key = store.put_incoming(report_id, image, content_type=content_type)
        doc = store.update(report_id, lambda d: d.model_copy(update={"incoming_key": key}))
    return doc


def _punjab_photo() -> bytes:
    # 11:35 IST is 06:05 UTC, five minutes before the upload.
    return jpeg_with_exif(*PUNJAB, taken_local="2026:09:08 11:35:00", direction=85.0)


def _table(storage: Storage, table: str):
    analytics = storage.analytics
    assert isinstance(analytics, ParquetAnalyticsStore)
    return analytics.read(table)


def test_corroborated_smoke_seeds_a_plume_and_never_touches_events(
    catalog: RegionCatalog, storage: Storage, settings: CitizenSettings
) -> None:
    before = _cycle(catalog, storage)
    _report(storage, "rep_punjab", "in-north", *PUNJAB, _punjab_photo())
    observer = StubObserver("smoke_plume")
    outcome = _analyzer(catalog, storage, settings, observer).analyze("rep_punjab")

    doc = outcome.doc
    analysis = doc.analysis
    assert analysis is not None and doc.status == "analyzed"
    assert analysis.geo_trust is not None and analysis.geo_trust.level == "trusted"
    assert analysis.geo_trust.observed_at == T0 + timedelta(minutes=5)
    assert analysis.corroboration is not None
    assert analysis.corroboration.level == "corroborated"
    assert analysis.corroboration.matched_fire_id == PUNJAB_FIRE
    assert analysis.decision == "seed_plume"
    assert doc.sanitized_key is not None
    assert not has_metadata(storage.citizen.read(doc.sanitized_key))

    plume = outcome.plume
    assert plume is not None and analysis.plume_id == plume.plume_id
    assert (plume.origin.kind, plume.origin.ref_id) == ("citizen_report", "rep_punjab")
    assert (plume.origin.lat, plume.origin.lon) == (30.12, 75.71), "starts at the hotspot"
    assert plume.provenance_class == "simulated" and plume.experimental
    assert storage.plumes.get("in-north", plume.plume_id) is not None

    after = storage.snapshots.latest("in-north")
    assert after is not None and after == before, "a report never changes the snapshot"

    rows = _table(storage, "citizen.reports")
    assert list(rows["report_id"]) == ["rep_punjab"]
    assert "claimed_lat" not in rows.columns and "reporter_hash" not in rows.columns
    assert rows.iloc[0]["lat_rounded"] == 30.1

    nodes = _table(storage, "graph.nodes")
    assert "citizen_report:in-north:rep_punjab" in set(nodes["node_id"])
    edges = _table(storage, "graph.edges")
    citizen_edges = edges[edges["src"] == "citizen_report:in-north:rep_punjab"]
    assert {"located_in", "consistent_with", "near"} <= set(citizen_edges["kind"])

    again = _analyzer(catalog, storage, settings, observer).analyze("rep_punjab")
    assert again.doc == doc and observer.calls == 1, "a finished report is not re-analysed"
    assert len(_table(storage, "citizen.reports")) == 1


def test_the_next_cycle_carries_the_seeded_report(
    catalog: RegionCatalog, storage: Storage, settings: CitizenSettings
) -> None:
    _cycle(catalog, storage)
    _report(storage, "rep_punjab", "in-north", *PUNJAB, _punjab_photo())
    _analyzer(catalog, storage, settings).analyze("rep_punjab")

    t1 = T0 + timedelta(hours=1)
    snapshot = _cycle(catalog, storage, t1, silent=True)
    assert [w.report_id for w in snapshot.citizen_watches] == ["rep_punjab"]
    watch = snapshot.citizen_watches[0]
    assert (watch.lat_rounded, watch.lon_rounded) == (30.1, 75.55)
    assert watch.matched_fire_id == PUNJAB_FIRE and watch.provenance_class == "ai_observation"
    seeded = [p for p in snapshot.plumes if p.origin.kind == "citizen_report"]
    assert [p.plume_id for p in seeded] == [watch.plume_id]
    assert all(s.field != "citizen_watches" for s in snapshot.field_status)
    edges = _table(storage, "graph.edges")
    cycle_edges = edges[edges["cycle_id"] == snapshot.cycle_id]
    assert "citizen_report:in-north:rep_punjab" in set(cycle_edges["src"])


def test_a_png_with_no_exif_falls_back_to_upload_time(
    catalog: RegionCatalog, storage: Storage, settings: CitizenSettings
) -> None:
    _cycle(catalog, storage)
    _report(
        storage,
        "rep_delhi",
        "in-north",
        28.61,
        77.21,
        DELHI_PNG.read_bytes(),
        content_type="image/png",
    )
    outcome = _analyzer(catalog, storage, settings, StubObserver("haze")).analyze("rep_delhi")
    analysis = outcome.doc.analysis
    assert analysis is not None and analysis.geo_trust is not None
    assert analysis.geo_trust.observed_at is None
    assert analysis.geo_trust.observed_at_status is not None
    assert analysis.corroboration is not None
    timed = [s for s in analysis.corroboration.signals if s.signal == "fire_nearby"]
    assert timed and "upload time" in (timed[0].detail or "")
    supporting = {s.signal for s in analysis.corroboration.signals if s.supports}
    assert supporting == {"pm25_elevated"}, "a Delhi station is elevated; no fire nearby"
    assert analysis.corroboration.level == "partial"
    assert analysis.decision == "operator_queue" and outcome.plume is None


def test_singapore_without_a_live_snapshot_waits_for_an_operator(
    catalog: RegionCatalog, storage: Storage, settings: CitizenSettings
) -> None:
    photo = jpeg_with_exif(1.3521, 103.8198, taken_local="2026:09:08 14:05:00", direction=200.0)
    _report(storage, "rep_sg", "sg-singapore", 1.3521, 103.8198, photo)
    outcome = _analyzer(catalog, storage, settings).analyze("rep_sg")
    analysis = outcome.doc.analysis
    assert analysis is not None and analysis.geo_trust is not None
    assert analysis.geo_trust.level == "trusted"
    assert analysis.corroboration is None and "no_live_snapshot" in analysis.degraded_reasons
    assert analysis.decision == "operator_queue" and outcome.plume is None


def test_an_untrusted_report_never_seeds_or_alerts(
    catalog: RegionCatalog, storage: Storage, settings: CitizenSettings
) -> None:
    _cycle(catalog, storage)
    # Claimed in Melbourne for the au-nsw region: outside the pack, so untrusted.
    photo = jpeg_with_exif(-37.81, 144.96, taken_local="2026:09:08 16:05:00")
    _report(storage, "rep_vic", "au-nsw", -37.81, 144.96, photo)
    alerts: list[Alert] = []
    analyzer = _analyzer(catalog, storage, settings, alerts=alerts)
    outcome = analyzer.analyze("rep_vic")
    analysis = outcome.doc.analysis
    assert analysis is not None and analysis.geo_trust is not None
    assert analysis.geo_trust.level == "untrusted"
    assert analysis.decision == "operator_queue"
    accepted = analyzer.moderate("rep_vic", action="accept")
    assert accepted.doc.moderation == "accepted"
    assert accepted.plume is None and alerts == [], "accepted or not, untrusted never acts"


def test_gemini_unavailable_queues_the_report_with_a_reason(
    catalog: RegionCatalog, storage: Storage, settings: CitizenSettings
) -> None:
    _cycle(catalog, storage)
    _report(storage, "rep_down", "in-north", *PUNJAB, _punjab_photo())
    analyzer = _analyzer(catalog, storage, settings, UnavailableObserver())
    outcome = analyzer.analyze("rep_down")
    analysis = outcome.doc.analysis
    assert analysis is not None and analysis.observation is None
    assert UNAVAILABLE in analysis.degraded_reasons
    assert analysis.decision == "operator_queue" and outcome.plume is None

    classified = analyzer.moderate("rep_down", action="accept", visual_class="smoke_plume")
    assert classified.doc.moderated_class == "smoke_plume"
    assert classified.doc.analysis is not None
    assert classified.doc.analysis.decision == "seed_plume", "the operator's class acts"
    assert classified.plume is not None

    rejected = analyzer.moderate("rep_down", action="reject")
    assert rejected.doc.moderation == "rejected"
    assert rejected.doc.analysis is not None
    assert rejected.doc.analysis.decision == "stored_operators_only"


def test_a_bad_upload_is_stored_for_operators_only(
    catalog: RegionCatalog, storage: Storage, settings: CitizenSettings
) -> None:
    _report(storage, "rep_pdf", "in-north", *PUNJAB, b"%PDF-1.7 not an image")
    _report(storage, "rep_none", "in-north", *PUNJAB, None)
    analyzer = _analyzer(catalog, storage, settings)
    pdf = analyzer.analyze("rep_pdf").doc.analysis
    assert pdf is not None and pdf.decision == "stored_operators_only"
    assert "image_rejected_unsupported_type" in pdf.degraded_reasons
    none = analyzer.analyze("rep_none").doc.analysis
    assert none is not None and "no_media_uploaded" in none.degraded_reasons
    with pytest.raises(ReportNotFoundError):
        analyzer.analyze("rep_missing")


def test_a_duplicate_photo_loses_trust(
    catalog: RegionCatalog, storage: Storage, settings: CitizenSettings
) -> None:
    photo = _punjab_photo()
    _report(storage, "rep_first", "in-north", *PUNJAB, photo)
    _report(storage, "rep_copy", "in-north", *PUNJAB, photo)
    analyzer = _analyzer(catalog, storage, settings)
    first = analyzer.analyze("rep_first").doc.analysis
    copy = analyzer.analyze("rep_copy").doc.analysis
    assert first is not None and first.geo_trust is not None
    assert copy is not None and copy.geo_trust is not None
    assert first.geo_trust.components["not_duplicate"] == 1.0
    assert copy.geo_trust.components["not_duplicate"] == 0.0


def test_a_citizen_watch_alert_names_the_report_not_an_event(
    catalog: RegionCatalog, storage: Storage, settings: CitizenSettings
) -> None:
    _cycle(catalog, storage)
    doc = _report(storage, "rep_watch", "in-north", *PUNJAB, _punjab_photo())
    alerts: list[Alert] = []
    analyzer = _analyzer(catalog, storage, settings, alerts=alerts)
    plume = analyzer.analyze("rep_watch").plume
    assert plume is not None
    reaching = plume.model_copy(
        update={
            "arrivals": [
                PlaceArrival(
                    place_id="ludhiana",
                    name="Ludhiana",
                    lat=30.9,
                    lon=75.85,
                    probability=0.6,
                    eta_hours_median=4.0,
                    population=1_600_000,
                ),
                PlaceArrival(
                    place_id="far",
                    name="Far town",
                    lat=31.5,
                    lon=76.5,
                    probability=0.2,
                    eta_hours_median=20.0,
                ),
            ]
        }
    )
    alert = analyzer._watch(doc, reaching)
    assert alert is not None and alerts == [alert]
    assert alert.report_id == "rep_watch" and alert.event_id is None
    assert alert.severity == "WATCH" and alert.message_template == "citizen_watch"
    assert "Ludhiana" in alert.message and "Far town" not in alert.message
    assert "AI observation" in alert.message and "experimental" in alert.message
    rows = _table(storage, "ops.alerts")
    citizen_rows = rows[rows["cycle_id"].isna()]
    assert len(citizen_rows) == 1
    assert json.loads(citizen_rows.iloc[0]["record"])["report_id"] == "rep_watch"
    assert analyzer._watch(doc, plume) is None, "no populated place within the window"


def test_alerts_name_exactly_one_subject() -> None:
    base = {"alert_id": "a", "severity": "WATCH", "message": "m", "created_at": T0}
    with pytest.raises(ValueError):
        Alert.model_validate(base)
    with pytest.raises(ValueError):
        Alert.model_validate({**base, "event_id": "e", "report_id": "r"})


def test_concurrent_updates_retry_and_keep_both_changes(storage: Storage) -> None:
    _report(storage, "rep_race", "in-north", *PUNJAB, None)
    store = storage.citizen
    raced = {"done": False}

    def change(doc: CitizenReportDocument) -> CitizenReportDocument:
        if not raced["done"]:
            raced["done"] = True
            store.update("rep_race", lambda d: d.model_copy(update={"notes": "operator note"}))
        return doc.model_copy(update={"status": "queued"})

    updated = store.update("rep_race", change)
    assert updated.status == "queued" and updated.notes == "operator note"
    with pytest.raises(PreconditionFailedError):
        store.create(updated)


def test_push_endpoint(catalog: RegionCatalog, storage: Storage, settings: CitizenSettings) -> None:
    doc = _report(storage, "rep_push", "in-north", *PUNJAB, _punjab_photo())
    client = TestClient(create_app(_analyzer(catalog, storage, settings)))

    def push(attributes: dict[str, str] | None = None, data: str | None = None):
        message: dict[str, Any] = {"attributes": attributes or {}}
        if data is not None:
            message["data"] = data
        return client.post("/pubsub/push", json={"message": message, "subscription": "s"})

    ok = push({"objectId": doc.incoming_key or "", "eventType": "OBJECT_FINALIZE"})
    assert ok.status_code == 200 and ok.json()["status"] == "analyzed"
    assert push({"objectId": "sanitized/rep_push.jpg"}).json()["status"] == "ignored"
    assert push({"objectId": "incoming/rep_nobody/abc"}).json()["reason"] == "unknown_report"
    encoded = base64.b64encode(json.dumps({"name": doc.incoming_key}).encode()).decode()
    assert object_name({"message": {"data": encoded}}) == doc.incoming_key

    class Broken(StubObserver):
        def observe(self, image: SanitizedImage, observation_type: str) -> ObserverResult:
            raise RuntimeError("boom")

    _report(storage, "rep_fail", "in-north", *PUNJAB, jpeg_with_exif(30.0, 75.5))
    failing = TestClient(create_app(_analyzer(catalog, storage, settings, Broken())))
    found = storage.citizen.get("rep_fail")
    assert found is not None
    response = failing.post(
        "/pubsub/push",
        json={"message": {"attributes": {"objectId": found[0].incoming_key}}},
    )
    assert response.status_code == 500, "Pub/Sub retries, then dead-letters"


def test_observer_selection_needs_a_configured_key() -> None:
    assert build_observer(Settings()).version == "unavailable"
    keyed = build_observer(Settings(gemini_api_key="test-key-not-real"))  # type: ignore[arg-type]
    assert keyed.version.startswith("gemini-observer-v1:")


def test_eval_compares_with_the_keyword_classifier_and_always_clear(
    tmp_path: Path, settings: CitizenSettings
) -> None:
    (tmp_path / "smoke.jpg").write_bytes(jpeg_with_exif(30.1, 75.5))
    (tmp_path / "fog.png").write_bytes(DELHI_PNG.read_bytes())
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {
                    "path": "smoke.jpg",
                    "label": "smoke_plume",
                    "observation_type": "smoke",
                    "licence": "team photo",
                },
                {
                    "path": "fog.png",
                    "label": "fog_or_cloud",
                    "observation_type": "haze",
                    "licence": "team photo",
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    report = run_eval(manifest, tmp_path / "out", Settings(), StubObserver("smoke_plume"))
    methods = report["methods"]
    assert isinstance(methods, dict)
    assert set(methods) == {"stub-observer-1", "keyword_classifier", "always_clear"}
    assert methods["stub-observer-1"]["smoke_plume"]["precision"] == 0.5
    assert (tmp_path / "out" / "metrics.jsonl").read_text(encoding="utf-8").strip()
    assert keyword_baseline("smoke", None) == "smoke_plume"
    assert keyword_baseline("photo", "nothing to see") is None


def test_citizen_settings_are_validated(tmp_path: Path) -> None:
    raw = (CONFIG / "citizen.yaml").read_text(encoding="utf-8")
    (tmp_path / "citizen.yaml").write_text(
        raw.replace("fire_radius_km: 25.0", "fire_radius_km: -1"), encoding="utf-8"
    )
    with pytest.raises(RegionPackError):
        load_citizen_settings(tmp_path)
