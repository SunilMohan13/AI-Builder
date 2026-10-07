"""``aeropulse-citizen``: analyse citizen reports, evaluate the observer, serve the push endpoint.

    aeropulse-citizen analyze <report_id> [<report_id> ...]
    aeropulse-citizen eval --manifest data/citizen-eval/manifest.jsonl --out var/eval/citizen
    aeropulse-citizen serve --port 8080

The observer is Gemini when ``AEROPULSE_GEMINI_API_KEY`` or a Google Cloud
project is configured; otherwise every report is stored with
``ai_observation_unavailable`` and waits for an operator.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from aeropulse_common.settings import Settings, get_settings
from aeropulse_contracts.citizen import CitizenReport
from aeropulse_intelligence.cv import classify_report
from aeropulse_observability import configure_logging
from aeropulse_regions import load_catalog, load_citizen_settings
from aeropulse_storage import batch_id, build_storage
from aeropulse_vision import (
    RejectedImageError,
    UnavailableObserver,
    VisualObserver,
    sanitize,
)
from aeropulse_vision.evaluation import evaluation_report, load_manifest, metric_rows

from aeropulse_citizen_analyzer.analyzer import CitizenAnalyzer

#: The legacy keyword classifier's labels, in visual classes (the eval baseline).
KEYWORD_CLASSES: dict[str, str | None] = {
    "smoke": "smoke_plume",
    "fire": "flames",
    "haze": "haze",
    "dust": "dust",
    "clear": "clear",
    "unknown": None,
}


def build_observer(settings: Settings) -> VisualObserver:
    key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
    vertex = settings.gcp_project if settings.platform == "gcp" else None
    if not key and not vertex:
        return UnavailableObserver()
    from aeropulse_vision.gemini import GeminiObserver

    return GeminiObserver(
        model=settings.citizen_vision_model,
        api_key=None if vertex else key,
        vertex_project=vertex,
    )


def build_analyzer(settings: Settings) -> CitizenAnalyzer:
    return CitizenAnalyzer(
        catalog=load_catalog(settings.config_dir),
        storage=build_storage(settings),
        settings=load_citizen_settings(settings.config_dir),
        observer=build_observer(settings),
    )


def keyword_baseline(observation_type: str, notes: str | None) -> str | None:
    report = CitizenReport(
        report_id="eval",
        lat=0.0,
        lon=0.0,
        observed_at=datetime.now(UTC),
        observation_type=observation_type,
        notes=notes,
    )
    return KEYWORD_CLASSES[classify_report(report).cv_class]


def run_eval(
    manifest: Path, out: Path, settings: Settings, observer: VisualObserver
) -> dict[str, object]:
    citizen = load_citizen_settings(settings.config_dir)
    items = load_manifest(manifest)
    labels: list[str] = []
    observed: list[str | None] = []
    keyword: list[str | None] = []
    for item in items:
        labels.append(item.label)
        keyword.append(keyword_baseline(item.observation_type, item.notes))
        try:
            image = sanitize(
                item.path.read_bytes(),
                max_bytes=citizen.upload.max_bytes,
                max_pixels=citizen.upload.max_pixels,
                allowed_mime=citizen.upload.allowed_mime,
            )
        except RejectedImageError:
            observed.append(None)
            continue
        result = observer.observe(image, item.observation_type)
        observed.append(result.observation.visual_class if result.observation else None)
    report = evaluation_report(
        labels,
        {
            observer.version: observed,
            "keyword_classifier": keyword,
            "always_clear": ["clear"] * len(labels),
        },
    )
    run_id = f"citizen_eval_{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    report = {"run_id": run_id, "observer_version": observer.version, **report}
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    rows = metric_rows(report, run_id=run_id, observer_version=observer.version)
    with (out / "metrics.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(row.model_dump_json() + "\n")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aeropulse-citizen", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    analyze = sub.add_parser("analyze", help="analyse reports by id")
    analyze.add_argument("report_ids", nargs="+")
    evaluate = sub.add_parser("eval", help="measure the observer on a labelled set")
    evaluate.add_argument("--manifest", type=Path, required=True)
    evaluate.add_argument("--out", type=Path, default=Path("var/eval/citizen"))
    evaluate.add_argument(
        "--load", action="store_true", help="also load rows into aeropulse_eval.reports"
    )
    serve = sub.add_parser("serve", help="Pub/Sub push endpoint")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings, stream=sys.stderr)

    if args.command == "eval":
        observer = build_observer(settings)
        report = run_eval(args.manifest, args.out, settings, observer)
        if args.load:
            rows = [
                r.model_dump(mode="json")
                for r in metric_rows(
                    report, run_id=str(report["run_id"]), observer_version=observer.version
                )
            ]
            build_storage(settings).analytics.load(
                "eval.reports", rows, batch_id=batch_id(str(report["run_id"]), rows)
            )
        print(json.dumps({"run_id": report["run_id"], "items": report["items"]}))
        return 0

    analyzer = build_analyzer(settings)
    if args.command == "serve":
        import uvicorn

        from aeropulse_citizen_analyzer.push import create_app

        uvicorn.run(create_app(analyzer), host=args.host, port=args.port)
        return 0

    for report_id in args.report_ids:
        outcome = analyzer.analyze(report_id)
        analysis = outcome.doc.analysis
        print(
            json.dumps(
                {
                    "report_id": report_id,
                    "status": outcome.doc.status,
                    "decision": analysis.decision if analysis else None,
                    "plume_id": outcome.plume.plume_id if outcome.plume else None,
                    "alert_id": outcome.alert.alert_id if outcome.alert else None,
                    "degraded_reasons": analysis.degraded_reasons if analysis else [],
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
