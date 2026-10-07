"""Command line entry point for training, inspection and live prediction.

uv run aeropulse-ml train --family pm25_forecast --dataset bq://<project> --regions in-north
uv run aeropulse-ml train --family all --dataset parquet://data/training --regions in-north
uv run aeropulse-ml train --model all            # legacy grid trainers
uv run aeropulse-ml train --model all --live --days 60 --promote
uv run aeropulse-ml models
uv run aeropulse-ml serving --strict              # what model_serving.yaml serves, and why
uv run aeropulse-ml predict --live
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from aeropulse_observability.logging import suppress_credential_bearing_loggers

from aeropulse_ml.dataset import (
    build_grid_features,
    describe,
    features_to_frame,
    load_observations_from_openmeteo,
    save_parquet,
    write_metadata,
)
from aeropulse_ml.registry import ModelRegistry, ModelStage
from aeropulse_ml.train import TRAINERS, InsufficientDataError, register_result

DEFAULT_MODEL_DIR = "models"
DEFAULT_DATASET_PATH = Path("data/training/grid_features.parquet")


def _load_frame(args: argparse.Namespace) -> tuple[Any, dict[str, Any], float]:
    """Materialise the training frame and report how long ingestion took."""
    started = time.perf_counter()
    if args.live:
        os.environ["AEROPULSE_CONNECTOR_MODE"] = "live"
    air_quality, weather, rasters = load_observations_from_openmeteo(
        fixture_path=Path(args.fixture) if args.fixture else None,
        live=args.live,
        days=args.days,
    )
    features = build_grid_features(air_quality, weather, rasters=rasters)
    frame = features_to_frame(features)
    metadata = describe(frame, sources=["openmeteo"])
    elapsed = time.perf_counter() - started
    # Diagnostics go to stderr so that `predict` emits pipeable JSON on stdout.
    print(
        f"dataset: rows={metadata.rows} cells={metadata.grid_cells} "
        f"window={metadata.start} -> {metadata.end} "
        f"observations(aq={len(air_quality)}, weather={len(weather)}, raster={len(rasters)}) "
        f"in {elapsed:.2f}s",
        file=sys.stderr,
    )
    return frame, metadata.to_dict(), elapsed


def _train_families(args: argparse.Namespace) -> int:
    """APAC families: dataset -> shared pipeline -> plugin -> gate report.

    Writes artifacts and gate reports under ``--out``; never writes
    ``config/model_serving.yaml``. A failed gate is a result, not an error.
    """
    from aeropulse_common.errors import DatasetError, TrainingError
    from aeropulse_observability.logging import configure_logging
    from aeropulse_regions import load_catalog

    from aeropulse_ml.datasets import open_dataset
    from aeropulse_ml.models import PLUGINS
    from aeropulse_ml.training import promotion_snippet, train_family

    configure_logging(stream=sys.stderr)
    catalog = load_catalog()
    families = list(PLUGINS) if args.family == "all" else [args.family]
    regions = [r for r in (args.regions or "").split(",") if r] or catalog.region_ids()
    try:
        source = open_dataset(args.dataset, catalog=catalog)
    except DatasetError as exc:
        print(f"dataset: {exc}", file=sys.stderr)
        return 2
    if source.kind == "synthetic":
        print("dataset: synthetic test data; reports will be marked not servable", file=sys.stderr)
    summaries: list[dict[str, Any]] = []
    errors = 0
    for family in families:
        try:
            run = train_family(
                family,
                source,
                regions,
                catalog=catalog,
                out_dir=Path(args.out),
                n_folds=args.folds,
            )
        except (DatasetError, TrainingError) as exc:
            print(f"{family}: {exc}", file=sys.stderr)
            summaries.append({"family": family, "trained": False, "reason": str(exc)})
            errors += 1
            continue
        report = run.report
        gate_path = run.run_dir / "gate.json"
        if args.load_eval:
            _load_eval_rows(report.run_id, [r.model_dump(mode="json") for r in run.metric_rows])
        summaries.append(
            {
                "family": family,
                "run_id": report.run_id,
                "model_version": report.model_version,
                "gate_report": str(gate_path),
                "servable": report.servable,
                "servable_reason": report.servable_reason,
                "regions": {
                    g.region_id: {
                        "passed": report.passed_for(g.region_id),
                        "calibrated": g.calibrated,
                        "labelled_rows": g.labelled_rows,
                        "failures": g.failures,
                    }
                    for g in report.regions
                },
            }
        )
        snippet = promotion_snippet(report, str(gate_path))
        if snippet:
            print(
                f"\n{family}: passed for some regions. To serve, open a pull request "
                "adding these entries to config/model_serving.yaml:\n" + snippet,
                file=sys.stderr,
            )
    print(json.dumps({"training": summaries}, indent=2, default=str))
    return 1 if errors else 0


def _load_eval_rows(run_id: str, rows: list[dict[str, Any]]) -> None:
    """Append a run's metric rows to ``aeropulse_eval.reports`` (idempotent per run)."""
    from aeropulse_common.settings import get_settings
    from aeropulse_storage import batch_id, build_storage

    build_storage(get_settings()).analytics.load(
        "eval.reports", rows, batch_id=batch_id(run_id, rows)
    )


def cmd_train(args: argparse.Namespace) -> int:
    """Train one or all models and register the artifacts."""
    if args.family:
        return _train_families(args)
    frame, dataset_metadata, _ = _load_frame(args)
    if frame.empty:
        print("no training rows produced; check the connector or fixture", file=sys.stderr)
        return 1

    if args.save_dataset:
        written = save_parquet(frame, DEFAULT_DATASET_PATH)
        write_metadata_path = written.with_name(written.stem + "_metadata.json")
        from aeropulse_ml.dataset import DatasetMetadata

        write_metadata(DatasetMetadata(**_metadata_kwargs(dataset_metadata)), write_metadata_path)
        print(f"dataset written: {written}")

    registry = ModelRegistry(Path(args.model_dir))
    selected = list(TRAINERS) if args.model == "all" else [args.model]
    summary: dict[str, Any] = {}
    failures = 0

    for name in selected:
        trainer = TRAINERS[name]
        print(f"\n--- {name} ---")
        started = time.perf_counter()
        try:
            result = trainer(frame, registry)
        except InsufficientDataError as exc:
            print(f"SKIPPED: {exc}", file=sys.stderr)
            summary[name] = {"trained": False, "reason": str(exc)}
            failures += 1
            continue
        record, gate_failures = register_result(
            result,
            registry,
            dataset_metadata,
            frame=frame,
            promote=args.promote,
            force=args.force_promote,
        )
        elapsed = time.perf_counter() - started
        print(f"version:  {record.version}")
        print(f"stage:    {record.stage}")
        print(f"artifact: {record.artifact_uri}")
        print(f"trained in {elapsed:.2f}s")
        print(f"metrics:  {json.dumps(result.metrics, indent=2, default=str)}")
        if gate_failures:
            print("PROMOTION GATE FAILED - not serving:")
            for reason in gate_failures:
                print(f"  - {reason}")
        if result.notes:
            print(f"caveat:   {result.notes}")
        summary[name] = {
            "trained": True,
            "version": record.version,
            "stage": str(record.stage),
            "promotion_gate_passed": not gate_failures,
            "promotion_gate_failures": gate_failures,
            "metrics": result.metrics,
            "train_seconds": round(elapsed, 3),
        }

    report_path = Path(args.model_dir) / "training_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps({"dataset": dataset_metadata, "models": summary}, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"\nreport: {report_path}")
    return 1 if failures == len(selected) else 0


def _metadata_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    """Rehydrate DatasetMetadata kwargs from its dict form."""
    from datetime import datetime

    return {
        "rows": payload["rows"],
        "grid_cells": payload["grid_cells"],
        "start": datetime.fromisoformat(payload["start"]) if payload.get("start") else None,
        "end": datetime.fromisoformat(payload["end"]) if payload.get("end") else None,
        "feature_version": payload["feature_version"],
        "ml_feature_version": payload["ml_feature_version"],
        "sources": tuple(payload.get("sources", ())),
    }


def cmd_models(args: argparse.Namespace) -> int:
    """List registered models and their stages."""
    registry = ModelRegistry(Path(args.model_dir))
    records = registry.list_models()
    if not records:
        print("no models registered; run: aeropulse-ml train --model all")
        return 0
    print(f"{'stage':<12}{'model_name':<24}{'version':<28}commit")
    for record in records:
        print(f"{record.stage:<12}{record.model_name:<24}{record.version:<28}{record.code_commit}")
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    """Promote a model version, or transition it to a named stage."""
    registry = ModelRegistry(Path(args.model_dir))
    try:
        if args.stage:
            record = registry.transition(args.model_id, ModelStage(args.stage), force=args.force)
        else:
            record = registry.promote_to_production(args.model_id)
    except (KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{record.model_name} {record.version} -> {record.stage}")
    return 0


def cmd_predict(args: argparse.Namespace) -> int:
    """Run the champion models over the latest available grid-hour."""
    from aeropulse_ml.inference import ModelBundleCache, predict_latest

    frame, _, ingest_seconds = _load_frame(args)
    if frame.empty:
        print("no rows produced; nothing to predict", file=sys.stderr)
        return 1
    registry = ModelRegistry(Path(args.model_dir))
    cache = ModelBundleCache(registry)
    started = time.perf_counter()
    output = predict_latest(frame, cache)
    inference_seconds = time.perf_counter() - started
    output["timings_seconds"] = {
        "ingest_and_features": round(ingest_seconds, 4),
        "inference": round(inference_seconds, 4),
    }
    print(json.dumps(output, indent=2, default=str))
    return 0


def cmd_parity(args: argparse.Namespace) -> int:
    """Check that batch features match point-in-time replay.

    Exits non-zero on any disagreement. A feature that differs between the two
    paths is either leaking future observations into training or is absent at
    inference time, and both invalidate the offline metrics that promotion
    decisions rest on.
    """
    from aeropulse_ml.parity import check_parity

    if args.live:
        os.environ["AEROPULSE_CONNECTOR_MODE"] = "live"
    air_quality, weather, rasters = load_observations_from_openmeteo(
        fixture_path=Path(args.fixture) if args.fixture else None,
        live=args.live,
        days=args.days,
    )
    report = check_parity(
        air_quality,
        weather,
        rasters=rasters,
        sample=args.sample,
        tolerance=args.tolerance,
    )
    print(json.dumps(report.to_dict(), indent=2, default=str))
    if not report.rows_compared:
        print("no grid-hours compared; parity is unproven", file=sys.stderr)
        return 1
    if not report.passed:
        print(
            f"feature parity FAILED: {len(report.failing)} features disagree "
            f"across {report.rows_compared} grid-hours",
            file=sys.stderr,
        )
        return 1
    print(
        f"feature parity OK: {report.rows_compared} grid-hours, no divergence",
        file=sys.stderr,
    )
    return _family_parity(args)


def _family_parity(args: argparse.Namespace) -> int:
    """``ml-features-3.0.0`` parity for every family in every shipped region.

    Runs on the deterministic synthetic history from ``aeropulse_ml.testing``:
    the check is about the code (does a training row equal the serving row
    built from data truncated at ``t``?), so it needs a multi-day history the
    committed fixtures do not have. No value from it is served.
    """
    from aeropulse_contracts.feature_spec import FAMILY_FEATURE_SETS
    from aeropulse_regions import load_catalog

    from aeropulse_ml.features import FeatureContext
    from aeropulse_ml.features.parity import check_family_parity
    from aeropulse_ml.testing import SYNTHETIC_PLACES, synthetic_batch

    catalog = load_catalog()
    failed = 0
    reports = []
    for region_id in sorted(set(catalog.region_ids()) & set(SYNTHETIC_PLACES)):
        batch = synthetic_batch(region_id)
        context = FeatureContext.for_region(catalog, region_id, as_of=None)
        for feature_set in FAMILY_FEATURE_SETS.values():
            result = check_family_parity(
                batch, context, feature_set, sample=args.family_sample, tolerance=args.tolerance
            )
            reports.append(result.to_dict())
            failed += not result.passed
    print(json.dumps({"family_parity": reports}, indent=2, default=str))
    if failed:
        print(f"family feature parity FAILED for {failed} region/family pairs", file=sys.stderr)
        return 1
    print(f"family feature parity OK: {len(reports)} region/family pairs", file=sys.stderr)
    return 0


def cmd_drift(args: argparse.Namespace) -> int:
    """Run one scheduled drift sweep over the persisted signal whitelist.

    Intended to be invoked on a timer (cron, a Compose sidecar, or a
    Kubernetes CronJob). Exits 2 when any signal is drifting, so a scheduler
    can distinguish "ran and found nothing" from "ran and found something"
    without parsing the JSON.
    """
    from aeropulse_common.settings import get_settings

    from aeropulse_ml.drift_monitor import evaluate_drift

    database_url = get_settings().database_url
    if not database_url:
        print("AEROPULSE_DATABASE_URL is not set; drift needs persisted history", file=sys.stderr)
        return 1

    try:
        import psycopg

        from aeropulse_ml.drift_store import DRIFT_SIGNALS, TimescaleDriftReader
    except ImportError as exc:
        print(f"drift dependencies unavailable: {exc}", file=sys.stderr)
        return 1

    signals = args.signals or sorted(DRIFT_SIGNALS)
    unknown = [s for s in signals if s not in DRIFT_SIGNALS]
    if unknown:
        print(f"unknown signals: {unknown}; known: {sorted(DRIFT_SIGNALS)}", file=sys.stderr)
        return 1

    with psycopg.connect(database_url) as connection:
        report = evaluate_drift(
            TimescaleDriftReader(connection),
            signals,
            current_hours=args.current_hours,
            reference_hours=args.reference_hours,
            grid_id=args.grid_id,
            min_samples=args.min_samples,
        )

    print(json.dumps(report.to_dict(), indent=2, default=str))
    if report.alerts:
        print(
            f"drift detected on {len(report.alerts)} signal(s): "
            + ", ".join(f.signal for f in report.alerts),
            file=sys.stderr,
        )
        return 2
    return 0


def cmd_serving(args: argparse.Namespace) -> int:
    """Check ``model_serving.yaml`` and print what answers each family in each region.

    Exits 1 when the file itself is invalid, or with ``--strict`` when any
    entry is refused; a refused entry otherwise degrades to the rule.
    """
    from aeropulse_common.errors import AeropulseError
    from aeropulse_observability import configure_logging
    from aeropulse_regions import load_catalog

    from aeropulse_ml.serving import ModelResolver

    configure_logging(stream=sys.stderr)
    config_dir = Path(args.config_dir) if args.config_dir else None
    try:
        catalog = load_catalog(config_dir)
        resolver = ModelResolver.from_config_dir(catalog, config_dir=config_dir)
    except AeropulseError as exc:
        print(f"model serving config invalid: {exc.message}", file=sys.stderr)
        return 1
    report = {
        "served": {
            region_id: [m.model_dump() for m in resolver.served_models(region_id)]
            for region_id in catalog.region_ids()
        },
        "refused": [
            {
                "family": r.entry.family,
                "region_id": r.entry.region_id,
                "model_version": r.entry.model_version,
                "reason": r.reason,
            }
            for r in resolver.refusals
        ],
    }
    print(json.dumps(report, indent=2))
    return 1 if args.strict and resolver.refusals else 0


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser."""
    parser = argparse.ArgumentParser(
        prog="aeropulse-ml",
        description="AeroPulse model training, registry and live prediction",
    )
    parser.add_argument(
        "--model-dir",
        default=os.environ.get("AEROPULSE_MODEL_DIR", DEFAULT_MODEL_DIR),
        help="registry root (default: %(default)s)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_data_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--live", action="store_true", help="fetch live data (no credential needed)")
        p.add_argument("--days", type=int, default=30, help="trailing days to fetch when live")
        p.add_argument("--fixture", default=None, help="replay fixture path")

    train = sub.add_parser("train", help="train and register models")
    train.add_argument(
        "--family",
        choices=["pm25_forecast", "pm25_hazard_24h", "anomaly", "source_likelihood", "all"],
        default=None,
        help="APAC family; with --dataset and --regions. Omit for the legacy trainers.",
    )
    train.add_argument(
        "--dataset",
        default="fixture",
        help="bq://project[/dataset], parquet://path, fixture[://path], synthetic://",
    )
    train.add_argument("--regions", default="", help="comma-separated region ids (default: all)")
    train.add_argument("--out", default="models/runs", help="where artifacts and gate reports go")
    train.add_argument("--folds", type=int, default=5, help="purged rolling-origin folds")
    train.add_argument(
        "--load-eval",
        action="store_true",
        help="also append metric rows to aeropulse_eval.reports (the ML Evaluation page)",
    )
    train.add_argument("--model", choices=[*TRAINERS, "all"], default="all")
    train.add_argument(
        "--promote", action="store_true", help="promote to PRODUCTION after training"
    )
    train.add_argument(
        "--force-promote",
        action="store_true",
        help="promote even when the quality gate fails (drills and demos only)",
    )
    train.add_argument("--save-dataset", action="store_true", help="persist the training frame")
    add_data_args(train)
    train.set_defaults(func=cmd_train)

    models = sub.add_parser("models", help="list registered models")
    models.set_defaults(func=cmd_models)

    promote = sub.add_parser("promote", help="transition a model version")
    promote.add_argument("model_id")
    promote.add_argument("--stage", default=None, choices=[s.value for s in ModelStage])
    promote.add_argument("--force", action="store_true")
    promote.set_defaults(func=cmd_promote)

    predict = sub.add_parser("predict", help="predict with champion models")
    add_data_args(predict)
    predict.set_defaults(func=cmd_predict)

    parity = sub.add_parser("parity", help="verify batch features match point-in-time replay")
    parity.add_argument(
        "--sample",
        type=int,
        default=200,
        help="grid-hours to check, spread across the window (default: %(default)s)",
    )
    parity.add_argument(
        "--tolerance",
        type=float,
        default=1e-4,
        help="absolute numeric tolerance (default: %(default)s)",
    )
    parity.add_argument(
        "--family-sample",
        type=int,
        default=12,
        help="cycle times checked per region and ml-features-3 family (default: %(default)s)",
    )
    add_data_args(parity)
    parity.set_defaults(func=cmd_parity)

    drift = sub.add_parser("drift", help="run one scheduled drift sweep")
    drift.add_argument(
        "--signals",
        nargs="*",
        default=None,
        help="signals to evaluate (default: every whitelisted signal)",
    )
    drift.add_argument("--current-hours", type=int, default=24)
    drift.add_argument("--reference-hours", type=int, default=168)
    drift.add_argument("--grid-id", default=None)
    drift.add_argument(
        "--min-samples",
        type=int,
        default=30,
        help="rows required per window before a verdict (default: %(default)s)",
    )
    drift.set_defaults(func=cmd_drift)

    serving = sub.add_parser("serving", help="check model_serving.yaml and show what is served")
    serving.add_argument("--config-dir", default=None, help="config/ directory (default: settings)")
    serving.add_argument("--strict", action="store_true", help="exit 1 if any entry is refused")
    serving.set_defaults(func=cmd_serving)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list, defaulting to ``sys.argv``.

    Returns:
        Process exit code.
    """
    # Shared with every other service via aeropulse_observability. Only the
    # suppression is applied here: this CLI writes JSON to stdout, so it must
    # not adopt the full stdout logging setup.
    suppress_credential_bearing_loggers()

    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
