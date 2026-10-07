"""The model-plugin contract (target architecture 4.4).

A plugin owns one family: how to fit, predict, evaluate one region's test
rows against fitted baselines, and gate the aggregated result. Splits,
baselines fitting, aggregation, reports and artifacts are shared and live in
:mod:`aeropulse_ml.training`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np
import pandas as pd
from aeropulse_contracts import ModelFamily, StrategyResult
from aeropulse_contracts.feature_spec import FeatureSet

from aeropulse_ml.baselines import Baseline

#: ``{group: {subject: {metric: value}}}`` for one fold and one region.
Metrics = dict[str, dict[str, dict[str, float | None]]]

RANDOM_STATE = 42
#: A fold whose training side has fewer rows than this is not fitted.
MIN_FIT_ROWS = 60
#: The headline strategy must have at least this many evaluated folds.
MIN_EVALUATED_FOLDS = 3


@dataclass
class FittedModel:
    family: str
    model_version: str
    algorithm: str
    feature_names: tuple[str, ...]
    ml_feature_version: str
    calibrated: bool
    payload: dict[str, Any]
    params: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ModelPlugin(Protocol):
    family: ModelFamily
    feature_set: FeatureSet
    label: str
    #: ``False`` for a heuristic: evaluated descriptively, never gated to serve.
    trained: bool
    uses_calibration: bool
    algorithm: str
    version_prefix: str

    def fit(
        self, train: pd.DataFrame, calibration: pd.DataFrame | None, *, model_version: str
    ) -> FittedModel: ...

    def predict(self, model: FittedModel, frame: pd.DataFrame) -> pd.DataFrame: ...

    def baselines(self) -> list[Baseline]: ...

    def evaluate(
        self,
        model: FittedModel,
        test: pd.DataFrame,
        prediction: pd.DataFrame,
        baselines: Mapping[str, np.ndarray],
    ) -> Metrics: ...

    def gate(self, strategies: Mapping[str, StrategyResult]) -> list[str]: ...

    def region_calibrated(
        self, model: FittedModel, strategies: Mapping[str, StrategyResult]
    ) -> bool: ...


def matrix(frame: pd.DataFrame, names: tuple[str, ...]) -> np.ndarray:
    """Feature matrix in spec order; missing columns are NaN, never zero."""
    out = np.full((len(frame), len(names)), np.nan)
    for j, name in enumerate(names):
        if name in frame.columns:
            out[:, j] = pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)
    return out


def fit_matrix(frame: pd.DataFrame, names: tuple[str, ...]) -> tuple[np.ndarray, list[str]]:
    """Training matrix plus the features that were missing on every row.

    A column with no value at all cannot be binned. It is set to a constant,
    so no split can use it, and reported so the gap is visible in the model.
    """
    x = matrix(frame, names)
    dead = np.isnan(x).all(axis=0) if len(x) else np.ones(len(names), dtype=bool)
    x[:, dead] = 0.0
    return x, [n for n, d in zip(names, dead, strict=True) if d]


def column(frame: pd.DataFrame, name: str) -> np.ndarray:
    if name not in frame.columns:
        return np.full(len(frame), np.nan)
    return pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)


def flatten(prefix: str, values: Mapping[str, Any]) -> dict[str, float | None]:
    """``{"a": {"b": 1}}`` -> ``{"a.b": 1}``; non-numeric leaves are dropped."""
    out: dict[str, float | None] = {}
    for key, value in values.items():
        name = f"{prefix}{key}"
        if isinstance(value, Mapping):
            out.update(flatten(f"{name}.", value))
        elif value is None or isinstance(value, int | float):
            out[name] = None if value is None else float(value)
    return out


def metric(result: StrategyResult | None, group: str, subject: str, name: str) -> float | None:
    """A fold-mean metric from a strategy result, or ``None``."""
    if result is None or not result.available:
        return None
    value = result.metrics.get(group, {}).get(subject, {}).get(name)
    return None if value is None else float(value)


def folds_evaluated(result: StrategyResult | None, group: str) -> int:
    if result is None or not result.available:
        return 0
    return int(result.metrics.get(group, {}).get("_folds", 0) or 0)
