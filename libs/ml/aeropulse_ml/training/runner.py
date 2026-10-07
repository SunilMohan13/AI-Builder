"""Train one family over several regions and write its gate report (LLD APAC 7.8).

``DatasetSource -> preprocessing -> FeaturePipeline -> ModelPlugin.fit ->
evaluation strategies -> gate per region -> artifact + gate.json + metrics.jsonl``.

The run never writes ``config/model_serving.yaml``. Promotion is a reviewed
change to that file that points at a gate report this run produced.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from aeropulse_common.errors import TrainingError
from aeropulse_contracts import (
    DatasetLineage,
    EvalMetricRow,
    GateReport,
    RegionGate,
    StrategyResult,
)
from aeropulse_contracts.feature_spec import ML_FEATURE_VERSION
from aeropulse_observability.logging import get_logger
from aeropulse_regions import RegionCatalog

from aeropulse_ml.datasets.base import NON_SERVABLE_KINDS, DatasetSource
from aeropulse_ml.evaluation.strategies import (
    CalibrationSplit,
    EvaluationStrategy,
    Fold,
    Unavailable,
    default_strategies,
    label_horizon_hours,
)
from aeropulse_ml.features.pipeline import FeatureContext, FeaturePipeline
from aeropulse_ml.models.artifacts import save_model
from aeropulse_ml.models.base import FittedModel, Metrics, ModelPlugin
from aeropulse_ml.models.registry import get_plugin
from aeropulse_ml.preprocessing.pipelines import PREPROCESSING_VERSION
from aeropulse_ml.registry import code_commit
from aeropulse_ml.train import dataset_fingerprint

logger = get_logger(__name__)

DESCRIPTIVE = "descriptive"


@dataclass
class TrainingRun:
    report: GateReport
    metric_rows: list[EvalMetricRow]
    run_dir: Path
    model: FittedModel | None


@dataclass
class _Accumulator:
    folds: list[dict[str, Any]] = field(default_factory=list)
    metrics: list[Metrics] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def result(self, strategy: str) -> StrategyResult:
        if not self.metrics:
            reason = "; ".join(dict.fromkeys(self.reasons)) or "no fold evaluated this region"
            return StrategyResult(
                strategy=strategy, available=False, reason=reason, folds=self.folds
            )
        return StrategyResult(
            strategy=strategy, available=True, folds=self.folds, metrics=aggregate(self.metrics)
        )


def aggregate(per_fold: Sequence[Metrics]) -> dict[str, Any]:
    """Fold means (and ``*_std``) per group/subject/metric; ``_folds`` per group."""
    values: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    folds: dict[str, int] = defaultdict(int)
    for metrics in per_fold:
        for group, subjects in metrics.items():
            folds[group] += 1
            for subject, block in subjects.items():
                for name, value in block.items():
                    if value is not None and math.isfinite(value):
                        values[group][subject][name].append(float(value))
    out: dict[str, Any] = {}
    for group, subjects in values.items():
        out[group] = {"_folds": folds[group]}
        for subject, block in subjects.items():
            summary: dict[str, float] = {}
            for name, series in block.items():
                summary[name] = round(float(np.mean(series)), 6)
                if len(series) > 1:
                    summary[f"{name}_std"] = round(float(np.std(series, ddof=1)), 6)
            out[group][subject] = summary
    return out


def build_frame(
    plugin: ModelPlugin,
    source: DatasetSource,
    catalog: RegionCatalog,
    region_ids: Sequence[str],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> pd.DataFrame:
    """Pooled training rows for ``region_ids``, labelled, from the shared pipeline."""
    pipeline = FeaturePipeline(plugin.feature_set)
    frames = []
    for region_id in region_ids:
        batch = source.load(region_id, start=start, end=end)
        context = FeatureContext.for_region(catalog, region_id, as_of=None)
        frame = pipeline.build(batch, context, labels=True)
        logger.info(
            "training_frame_built",
            region_id=region_id,
            family=plugin.family,
            records=len(batch),
            rows=len(frame),
        )
        frames.append(frame)
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _no_label_reason(catalog: RegionCatalog, region_id: str, family: str) -> str:
    pack = catalog.get(region_id)
    if pack.ground_truth == "none" or not pack.ground_truth_sources:
        return "no ground truth in this region"
    if family != "pm25_forecast" and catalog.aqi_for(region_id).status != "confirmed":
        return "AQI standard unconfirmed: no hazard threshold, so no hazard label"
    return "no labelled rows for this region in the dataset"


def _season_inputs(
    catalog: RegionCatalog, region_ids: Sequence[str]
) -> tuple[dict[str, frozenset[int]], dict[str, str]]:
    months = {r: frozenset().union(*catalog.seasonal_months(r).values()) for r in region_ids}
    zones = {r: catalog.get(r).timezone for r in region_ids}
    return months, zones


def _evaluate(
    plugin: ModelPlugin,
    labelled: pd.DataFrame,
    strategies: Sequence[EvaluationStrategy],
    regions: Sequence[str],
) -> dict[str, dict[str, _Accumulator]]:
    acc: dict[str, dict[str, _Accumulator]] = {
        r: {s.name: _Accumulator() for s in strategies} for r in regions
    }
    for strategy in strategies:
        for item in strategy.folds(labelled):
            if isinstance(item, Unavailable):
                targets = [item.region_id] if item.region_id else list(regions)
                for r in targets:
                    if r in acc:
                        acc[r][strategy.name].reasons.append(item.reason)
                continue
            _run_fold(plugin, labelled, item, acc)
    return acc


def _run_fold(
    plugin: ModelPlugin,
    labelled: pd.DataFrame,
    fold: Fold,
    acc: dict[str, dict[str, _Accumulator]],
) -> None:
    fit_rows = labelled.loc[fold.fit]
    calibration = labelled.loc[fold.calibration] if len(fold.calibration) else None
    try:
        model = plugin.fit(fit_rows, calibration, model_version=f"{fold.strategy}:{fold.name}")
    except TrainingError as exc:
        for r in fold.regions:
            if r in acc:
                acc[r][fold.strategy].reasons.append(f"{fold.name}: {exc}")
                acc[r][fold.strategy].folds.append({**fold.to_dict(), "skipped": str(exc)})
        return
    baselines = [b.fit(fit_rows) for b in plugin.baselines()]
    test = labelled.loc[fold.test]
    prediction = plugin.predict(model, test)
    for region in fold.regions:
        if region not in acc:
            continue
        mine = test["region_id"] == region
        rows = test.loc[mine]
        metrics = plugin.evaluate(
            model,
            rows,
            prediction.loc[mine],
            {b.name: b.predict(rows) for b in baselines},
        )
        slot = acc[region][fold.strategy]
        slot.folds.append({**fold.to_dict(), "test_rows_in_region": int(mine.sum())})
        if metrics:
            slot.metrics.append(metrics)
        else:
            slot.reasons.append(
                f"{fold.name}: held-out rows support no metric (for example a single class)"
            )


def _metric_rows(
    report: GateReport,
) -> list[EvalMetricRow]:
    rows: list[EvalMetricRow] = []
    for gate in report.regions:
        for strategy in gate.strategies:
            for group, subjects in strategy.metrics.items():
                if not isinstance(subjects, Mapping):
                    continue
                for subject, block in subjects.items():
                    if not isinstance(block, Mapping):
                        continue
                    for name, value in block.items():
                        rows.append(
                            EvalMetricRow(
                                run_id=report.run_id,
                                family=report.family,
                                model_version=report.model_version,
                                region_id=gate.region_id,
                                strategy=strategy.strategy,
                                group=group,
                                subject=subject,
                                metric=name,
                                value=None if value is None else float(value),
                                passed=report.passed_for(gate.region_id),
                            )
                        )
    return rows


def train_family(
    family: str,
    source: DatasetSource,
    region_ids: Sequence[str],
    *,
    catalog: RegionCatalog,
    out_dir: Path,
    n_folds: int = 5,
    now: datetime | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> TrainingRun:
    """Train, evaluate and gate ``family`` pooled over ``region_ids``."""
    now = now or datetime.now(UTC)
    plugin = get_plugin(family, catalog)
    run_id = f"{family}-{now:%Y%m%dT%H%M%SZ}"
    run_dir = out_dir / run_id
    frame = build_frame(plugin, source, catalog, region_ids, start=start, end=end)
    if frame.empty:
        raise TrainingError(
            f"{family}: the dataset produced no feature rows for {list(region_ids)}"
        )

    labelled = frame[frame[plugin.label].notna()] if plugin.trained else frame
    counts = labelled["region_id"].value_counts().to_dict()
    with_rows = [r for r in region_ids if counts.get(r, 0) > 0]

    horizon = label_horizon_hours(labelled) if not labelled.empty else 24.0
    calibration = CalibrationSplit(purge_hours=horizon) if plugin.uses_calibration else None
    months, zones = _season_inputs(catalog, region_ids)
    notes: list[str] = []

    if plugin.trained:
        strategies = default_strategies(
            season_months=months, timezones=zones, n_folds=n_folds, calibration=calibration
        )
        acc = _evaluate(plugin, labelled, strategies, with_rows)
    else:
        acc = {}

    model: FittedModel | None
    try:
        fit_rows, cal_rows = (
            calibration.carve(labelled, labelled.index)
            if calibration is not None
            else (labelled.index, pd.Index([]))
        )
        model = plugin.fit(
            labelled.loc[fit_rows],
            labelled.loc[cal_rows] if len(cal_rows) else None,
            model_version=f"{plugin.version_prefix}-{now:%Y%m%d%H%M}",
        )
    except TrainingError as exc:
        model = None
        notes.append(f"final fit failed: {exc}")

    regions: list[RegionGate] = []
    for region_id in region_ids:
        if counts.get(region_id, 0) == 0:
            regions.append(
                RegionGate(
                    region_id=region_id,
                    passed=False,
                    failures=[_no_label_reason(catalog, region_id, family)],
                    labelled_rows=0,
                )
            )
            continue
        if plugin.trained:
            results = {name: a.result(name) for name, a in acc[region_id].items()}
        else:
            rows = labelled[labelled["region_id"] == region_id]
            metrics = plugin.evaluate(model, rows, plugin.predict(model, rows), {}) if model else {}
            results = {
                DESCRIPTIVE: StrategyResult(
                    strategy=DESCRIPTIVE,
                    available=bool(metrics),
                    reason=None if metrics else "nothing could be scored",
                    metrics=aggregate([metrics]) if metrics else {},
                )
            }
        failures = plugin.gate(results)
        if model is None:
            failures = [*failures, "no final model was fitted"]
        regions.append(
            RegionGate(
                region_id=region_id,
                passed=not failures,
                failures=failures,
                labelled_rows=int(counts[region_id]),
                calibrated=bool(
                    model and not failures and plugin.region_calibrated(model, results)
                ),
                strategies=list(results.values()),
            )
        )

    artifact_uri, sha = "", None
    if model is not None and plugin.trained:
        path = run_dir / "model.joblib"
        sha = save_model(model, path)
        artifact_uri = str(path)

    servable, servable_reason = True, None
    if source.kind in NON_SERVABLE_KINDS:
        servable, servable_reason = False, f"{source.kind} dataset: test data is never served"
    elif not plugin.trained:
        servable, servable_reason = False, "heuristic: served as a rule, not as a model"
    elif model is None:
        servable, servable_reason = False, "no final model was fitted"

    times = pd.to_datetime(frame["t"], utc=True)
    report = GateReport(
        run_id=run_id,
        family=plugin.family,
        model_version=model.model_version if model else f"{plugin.version_prefix}-none",
        algorithm=plugin.algorithm,
        ml_feature_version=ML_FEATURE_VERSION,
        feature_names=list(plugin.feature_set.names),
        calibrated=bool(model and model.calibrated),
        servable=servable,
        servable_reason=servable_reason,
        artifact_uri=artifact_uri,
        artifact_sha256=sha,
        code_commit=code_commit(),
        trained_at=now,
        dataset=DatasetLineage(
            uri=source.uri,
            kind=source.kind,
            fingerprint=dataset_fingerprint(frame),
            rows=len(frame),
            labelled_rows=len(labelled),
            regions=list(region_ids),
            start=times.min().to_pydatetime(),
            end=times.max().to_pydatetime(),
            preprocessing_version=PREPROCESSING_VERSION,
        ),
        regions=regions,
        notes=notes,
    )
    metric_rows = _metric_rows(report)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "gate.json").write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    with (run_dir / "metrics.jsonl").open("w", encoding="utf-8") as handle:
        for row in metric_rows:
            handle.write(row.model_dump_json() + "\n")
    logger.info(
        "training_run_written",
        family=family,
        run_id=run_id,
        regions_passed=[g.region_id for g in regions if report.passed_for(g.region_id)],
        servable=servable,
        rows=len(frame),
    )
    return TrainingRun(report=report, metric_rows=metric_rows, run_dir=run_dir, model=model)


def promotion_snippet(report: GateReport, gate_uri: str) -> str:
    """YAML a reviewer may paste into ``model_serving.yaml``; never written by code."""
    lines = []
    for gate in report.regions:
        if not report.passed_for(gate.region_id):
            continue
        lines += [
            f"  - family: {report.family}",
            f"    region_id: {gate.region_id}",
            f"    model_version: {report.model_version}",
            f"    artifact_uri: {report.artifact_uri}",
            f"    gate_report_uri: {gate_uri}",
            f"    calibrated: {str(gate.calibrated).lower()}",
        ]
    return "\n".join(lines)
