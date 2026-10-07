"""Measure the visual observer, do not train it (LLD APAC 9.8).

Per-class precision and recall for the smoke-like classes against a labelled
set that includes hard negatives (fog, cloud, steam, dust, sunset haze), with
the same metrics for each baseline. A class with no predictions has no
precision (``None``), never a made-up zero or one.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from aeropulse_contracts.citizen import VisualClass
from aeropulse_contracts.gate_report import EvalMetricRow

FAMILY: Literal["citizen_ai_observation"] = "citizen_ai_observation"
TARGET_CLASSES: tuple[VisualClass, ...] = ("smoke_plume", "haze", "flames")


@dataclass(frozen=True)
class EvalItem:
    path: Path
    label: VisualClass
    observation_type: str = "unknown"
    notes: str | None = None
    licence: str | None = None


def load_manifest(path: Path) -> list[EvalItem]:
    """JSON Lines: ``{"path", "label", "observation_type"?, "notes"?, "licence"}``.

    Paths are relative to the manifest. Every item must state its licence.
    """
    items: list[EvalItem] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not row.get("licence"):
            raise ValueError(f"{path}:{number}: every evaluation image states its licence")
        items.append(
            EvalItem(
                path=(path.parent / row["path"]).resolve(),
                label=row["label"],
                observation_type=row.get("observation_type", "unknown"),
                notes=row.get("notes"),
                licence=row["licence"],
            )
        )
    return items


def class_metrics(
    labels: Sequence[str], predictions: Sequence[str | None]
) -> dict[str, dict[str, float | int | None]]:
    """Precision, recall and counts per target class. ``None`` predictions are misses."""
    if len(labels) != len(predictions):
        raise ValueError("labels and predictions differ in length")
    out: dict[str, dict[str, float | int | None]] = {}
    for cls in TARGET_CLASSES:
        tp = sum(1 for y, p in zip(labels, predictions, strict=True) if y == cls and p == cls)
        predicted = sum(1 for p in predictions if p == cls)
        support = sum(1 for y in labels if y == cls)
        out[cls] = {
            "precision": round(tp / predicted, 4) if predicted else None,
            "recall": round(tp / support, 4) if support else None,
            "true_positives": tp,
            "predicted": predicted,
            "support": support,
        }
    return out


def evaluation_report(
    labels: Sequence[str], methods: Mapping[str, Sequence[str | None]]
) -> dict[str, object]:
    """Metrics for every method on the same labels (observer first, then baselines)."""
    negatives = sum(1 for y in labels if y not in TARGET_CLASSES)
    return {
        "family": FAMILY,
        "items": len(labels),
        "hard_negatives": negatives,
        "methods": {name: class_metrics(labels, preds) for name, preds in methods.items()},
    }


def metric_rows(
    report: Mapping[str, object], *, run_id: str, observer_version: str
) -> list[EvalMetricRow]:
    """``aeropulse_eval.reports`` rows. Never gated, so ``passed`` is always false."""
    methods = report.get("methods")
    rows: list[EvalMetricRow] = []
    if not isinstance(methods, Mapping):
        return rows
    for method, classes in methods.items():
        if not isinstance(classes, Mapping):
            continue
        for cls, block in classes.items():
            if not isinstance(block, Mapping):
                continue
            for name, value in block.items():
                rows.append(
                    EvalMetricRow(
                        run_id=run_id,
                        family=FAMILY,
                        model_version=observer_version,
                        region_id="all",
                        strategy="labelled_set",
                        group=str(method),
                        subject=str(cls),
                        metric=str(name),
                        value=None if value is None else float(value),
                        passed=False,
                    )
                )
    return rows
