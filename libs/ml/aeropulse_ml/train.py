"""Trainers for the six AeroPulse models.

Estimator choice: scikit-learn's ``HistGradientBoosting*`` is used rather than
LightGBM (LLD §18.1). It is the same gradient-boosted-histogram family, but
scikit-learn ships its own OpenMP runtime in its wheels whereas LightGBM
requires a system ``libomp`` that is not present on every target machine. The
estimator is a single constructor call in each trainer, so swapping LightGBM
back in is a one-line change once that dependency is guaranteed.

Two leakage defects found in the notebook track are fixed structurally here:

* The anomaly baseline is fitted on **training rows only** and then applied to
  the test rows. Previously the baseline was computed over the whole dataset
  before splitting, so each test row's regression target had already seen the
  test period.
* The source-likelihood label is a weak rule over fire/pollutant/wind signals,
  and :data:`aeropulse_contracts.feature_spec.SOURCE_LIKELIHOOD` deliberately
  **excludes every input that rule uses**. Previously the classifier received
  the exact columns its own label was computed from, so a high score measured
  threshold re-derivation rather than source attribution.

Neither model is trained on validated ground truth. Both are weak-supervision
baselines and are reported as such; see ``docs/architecture.md``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from aeropulse_contracts.feature_spec import (
    ANOMALY_RESIDUAL,
    ML_FEATURE_VERSION,
    PM25_ESTIMATOR,
    PM25_HAZARD_24H,
    PM25_PEAK_24H,
    PROPAGATION_FORECAST,
    SOURCE_LIKELIHOOD,
    FeatureSet,
)
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
)

from aeropulse_ml.evaluation import (
    classification_metrics,
    detection_metrics,
    ranking_metrics,
    regression_metrics,
    seasonal_split,
    skill_score,
    spatial_split,
    temporal_split,
)
from aeropulse_ml.registry import ModelRecord, ModelRegistry, ModelStage, code_commit

RANDOM_STATE = 42

#: CPCB National Air Quality Index "Very Poor" lower breakpoint for PM2.5
#: (ug/m3, 24h). Used as an *external, standards-based* exceedance label so the
#: anomaly evaluation label is not derived from the model's own residual.
CPCB_VERY_POOR_PM25 = 121.0

#: Minimum rows before training is attempted. Below this the metrics would be
#: noise and reporting them would be misleading.
MIN_TRAINING_ROWS = 60

#: Forecast horizons in hours (LLD §18.4). The nowcast band is 0-3h.
FORECAST_HORIZONS = (3, 6, 12, 24)


class InsufficientDataError(RuntimeError):
    """Raised when a frame is too small to train and evaluate honestly."""


@dataclass
class TrainingResult:
    """Outcome of one model's training run.

    Attributes:
        model_name: Model family.
        version: Version string recorded in the registry.
        algorithm: Estimator description.
        metrics: Metrics keyed by holdout name.
        artifact_path: Where the bundle was written.
        feature_names: Exact ordered feature list baked into the artifact.
        notes: Caveats a reader must see alongside the metrics.
    """

    model_name: str
    version: str
    algorithm: str
    metrics: dict[str, Any] = field(default_factory=dict)
    artifact_path: Path | None = None
    feature_names: list[str] = field(default_factory=list)
    notes: str = ""
    #: Probability calibration applied. Empty for regressors; ``none`` on a
    #: classifier is a deliberate statement that the scores are uncalibrated.
    calibration: str = ""
    #: Estimator and target construction, recorded so a run can be reproduced.
    regression_config: dict[str, Any] = field(default_factory=dict)
    #: Lead time in hours, or None for a nowcast.
    primary_horizon_h: int | None = None


def _require_rows(frame: pd.DataFrame, model_name: str) -> None:
    if len(frame) < MIN_TRAINING_ROWS:
        raise InsufficientDataError(
            f"{model_name}: {len(frame)} rows available, need at least "
            f"{MIN_TRAINING_ROWS} to train and evaluate honestly"
        )


def degenerate_features(frame: pd.DataFrame, feature_set: FeatureSet) -> list[str]:
    """Return features that carry no usable signal in this frame.

    A feature is degenerate when the column is absent or entirely null, which
    happens for feature groups no connector populates yet (industry, urban,
    population). Reporting them matters: a reader must know that a model
    nominally consuming 30 features actually saw fewer.

    Args:
        frame: Training frame.
        feature_set: Feature projection.

    Returns:
        Sorted degenerate feature names.
    """
    missing: list[str] = []
    for name in feature_set.names:
        if name not in frame.columns:
            missing.append(name)
            continue
        if pd.to_numeric(frame[name], errors="coerce").notna().sum() == 0:
            missing.append(name)
    return sorted(missing)


def _matrix(frame: pd.DataFrame, feature_set: FeatureSet) -> np.ndarray:
    """Project a frame onto a feature set as a float matrix.

    ``HistGradientBoosting`` handles NaN natively but cannot bin a column that
    is *entirely* NaN. Such columns are zero-filled so the vector keeps its
    contracted width -- dropping them would change the artifact's feature
    layout and break the serving contract. A constant column carries no
    signal, so the estimator simply ignores it; the affected names are
    reported separately via :func:`degenerate_features`.

    Args:
        frame: Training frame.
        feature_set: Feature projection.

    Returns:
        Float matrix with one column per feature, in contract order.
    """
    columns: list[np.ndarray] = []
    for name in feature_set.names:
        if name in frame.columns:
            series = pd.to_numeric(frame[name], errors="coerce")
        else:
            series = pd.Series(np.nan, index=frame.index, name=name)
        values = series.to_numpy(dtype=float)
        if not np.isfinite(values).any():
            values = np.zeros_like(values)
        columns.append(values)
    return np.column_stack(columns)


def _regressor() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        max_iter=400,
        learning_rate=0.05,
        max_depth=6,
        min_samples_leaf=10,
        l2_regularization=1.0,
        random_state=RANDOM_STATE,
    )


def _evaluate_regression(
    frame: pd.DataFrame,
    feature_set: FeatureSet,
    target: str,
    *,
    baseline_column: str | None = None,
) -> dict[str, Any]:
    """Fit and score across temporal, spatial and seasonal holdouts.

    A separate model is fitted per holdout so that no test row ever influences
    the model it is scored against.

    Args:
        frame: Training frame containing ``target``.
        feature_set: Feature projection to use.
        target: Target column name.
        baseline_column: Column holding a naive baseline prediction, used to
            compute a skill score.

    Returns:
        Metrics keyed by holdout name.
    """
    results: dict[str, Any] = {}
    for split in (temporal_split(frame), spatial_split(frame), seasonal_split(frame)):
        if not split.usable:
            results[split.name] = {"evaluated": False, "reason": split.detail}
            continue
        model = _regressor()
        model.fit(_matrix(split.train, feature_set), split.train[target].to_numpy(dtype=float))
        predicted = model.predict(_matrix(split.test, feature_set))
        scores = regression_metrics(split.test[target].to_numpy(dtype=float), predicted)
        metrics: dict[str, Any] = dict(scores)
        metrics["evaluated"] = True
        metrics["detail"] = split.detail
        metrics["train_rows"] = float(len(split.train))
        if baseline_column and baseline_column in split.test.columns:
            baseline = regression_metrics(
                split.test[target].to_numpy(dtype=float),
                split.test[baseline_column].to_numpy(dtype=float),
            )
            if baseline:
                metrics["baseline_mae"] = baseline["mae"]
                metrics["baseline_rmse"] = baseline["rmse"]
                metrics["skill_vs_baseline"] = skill_score(metrics["mae"], baseline["mae"])
        results[split.name] = metrics
    return results


def _fit_final(frame: pd.DataFrame, feature_set: FeatureSet, target: str) -> Any:
    """Fit the shipped model on all available rows."""
    model = _regressor()
    model.fit(_matrix(frame, feature_set), frame[target].to_numpy(dtype=float))
    return model


def dataset_fingerprint(frame: pd.DataFrame) -> str:
    """Return a stable hash of the training frame's contents.

    Two runs producing the same fingerprint were fitted on identical rows,
    which is what lets a reviewer tell "the metrics moved because the model
    changed" from "the metrics moved because the trailing window moved". The
    hash covers shape, column names and the value bytes, so a reordering of
    rows that pandas considers equivalent still hashes the same.

    Args:
        frame: Training frame.

    Returns:
        Short hex digest, or ``"empty"`` for a frame with no rows.
    """
    if frame.empty:
        return "empty"
    ordered = frame.reindex(sorted(frame.columns), axis=1)
    digest = hashlib.sha256()
    digest.update(f"{ordered.shape}".encode())
    digest.update("|".join(map(str, ordered.columns)).encode())
    digest.update(pd.util.hash_pandas_object(ordered, index=False).values.tobytes())
    return digest.hexdigest()[:16]


def _season_label(frame: pd.DataFrame) -> str:
    """Describe the calendar coverage of a frame, for artifact metadata."""
    if frame.empty:
        return "unknown"
    months = sorted(frame["timestamp"].dt.strftime("%Y-%m").unique())
    return months[0] if len(months) == 1 else f"{months[0]}..{months[-1]}"


def _save_bundle(
    bundle: dict[str, Any],
    registry: ModelRegistry,
    filename: str,
) -> Path:
    """Persist a model bundle under the registry root."""
    registry.root.mkdir(parents=True, exist_ok=True)
    path = registry.root / filename
    joblib.dump(bundle, path)
    return path


# --- Model 1: PM2.5 estimator ---------------------------------------------


def train_pm25_estimator(frame: pd.DataFrame, registry: ModelRegistry) -> TrainingResult:
    """Train the hyper-local PM2.5 estimator.

    The target is observed PM2.5 and the feature set excludes it, so the model
    must reconstruct the surface value from co-pollutants, AOD, weather, fire
    proximity and its own history. AOD enters as one input among many, never as
    a PM2.5 substitute (LLD §18.1, caveat §65.5).

    Args:
        frame: Training frame.
        registry: Registry to write the artifact into.

    Returns:
        The training result.

    Raises:
        InsufficientDataError: If too few labelled rows exist.
    """
    data = frame.dropna(subset=["pm25"]).copy()
    _require_rows(data, "pm25_estimator")

    # Persistence is the honest baseline for an estimator with history.
    data["baseline_pred"] = data["pm25_lag_1h"]
    metrics = _evaluate_regression(
        data,
        PM25_ESTIMATOR,
        "pm25",
        baseline_column="baseline_pred",
    )
    model = _fit_final(data, PM25_ESTIMATOR, "pm25")

    version = f"hgb-pm25-{datetime.now(UTC):%Y%m%d%H%M}"
    residual_std = float(
        np.std(data["pm25"].to_numpy(dtype=float) - model.predict(_matrix(data, PM25_ESTIMATOR)))
    )
    bundle = {
        "model": model,
        "feature_names": list(PM25_ESTIMATOR.names),
        "target": PM25_ESTIMATOR.target,
        "ml_feature_version": ML_FEATURE_VERSION,
        # Prediction intervals come from the in-sample residual spread, which
        # is optimistic; the holdout RMSE in metrics is the honest number.
        "residual_std": residual_std,
    }
    path = _save_bundle(bundle, registry, f"{version}.joblib")
    return TrainingResult(
        model_name="pm25_estimator",
        version=version,
        algorithm="sklearn.HistGradientBoostingRegressor",
        metrics=metrics,
        artifact_path=path,
        feature_names=list(PM25_ESTIMATOR.names),
        notes=(
            "Trained on Open-Meteo CAMS-derived air quality, which is model "
            "output rather than ground reference. Retrain on CPCB before any "
            "operational claim."
        ),
    )


# --- Model 2: anomaly detector --------------------------------------------


def fit_anomaly_baseline(train: pd.DataFrame) -> pd.DataFrame:
    """Fit a per-cell, per-hour-of-week PM2.5 baseline on training rows only.

    Fitting on the training partition and then applying to the test partition
    is the fix for the leakage found in the notebook track, where the baseline
    saw the whole dataset before the split and therefore contaminated every
    test-row target.

    Args:
        train: Training rows only.

    Returns:
        Baseline table keyed by ``grid_id`` and ``hour_of_week``.
    """
    local = train.dropna(subset=["pm25"]).copy()
    local["hour_of_week"] = local["timestamp"].dt.dayofweek * 24 + local["timestamp"].dt.hour
    grouped = (
        local.groupby(["grid_id", "hour_of_week"])["pm25"]
        .agg(baseline_pm25="median", baseline_mad=lambda s: float((s - s.median()).abs().median()))
        .reset_index()
    )
    # A global fallback covers cell-hours the training partition never saw.
    grouped.attrs["global_median"] = float(local["pm25"].median())
    return grouped


def apply_anomaly_baseline(frame: pd.DataFrame, baseline: pd.DataFrame) -> pd.DataFrame:
    """Attach baseline, residual and robust z-score columns.

    Args:
        frame: Rows to annotate.
        baseline: Table from :func:`fit_anomaly_baseline`.

    Returns:
        A copy with ``baseline_pm25``, ``residual`` and ``robust_z`` columns.
    """
    local = frame.copy()
    local["hour_of_week"] = local["timestamp"].dt.dayofweek * 24 + local["timestamp"].dt.hour
    merged = local.merge(baseline, on=["grid_id", "hour_of_week"], how="left")
    fallback = baseline.attrs.get("global_median", float("nan"))
    merged["baseline_pm25"] = merged["baseline_pm25"].fillna(fallback)
    merged["baseline_mad"] = merged["baseline_mad"].fillna(0.0)
    merged["residual"] = merged["pm25"] - merged["baseline_pm25"]
    scale = merged["baseline_mad"].replace(0.0, np.nan) * 1.4826
    merged["robust_z"] = merged["residual"] / scale
    merged["robust_z"] = merged["robust_z"].replace([np.inf, -np.inf], np.nan)
    return merged


def train_anomaly_detector(frame: pd.DataFrame, registry: ModelRegistry) -> TrainingResult:
    """Train the residual model behind anomaly detection.

    Evaluation uses an *external* exceedance label: whether observed PM2.5
    crosses the CPCB "Very Poor" breakpoint. That label is defined by a
    published standard rather than by the model's own residual, which is what
    makes the precision/recall numbers meaningful.

    Args:
        frame: Training frame.
        registry: Registry to write the artifact into.

    Returns:
        The training result.

    Raises:
        InsufficientDataError: If too few labelled rows exist.
    """
    data = frame.dropna(subset=["pm25"]).copy()
    _require_rows(data, "anomaly_detector")

    metrics: dict[str, Any] = {}
    for split in (temporal_split(data), spatial_split(data)):
        if not split.usable:
            metrics[split.name] = {"evaluated": False, "reason": split.detail}
            continue
        baseline = fit_anomaly_baseline(split.train)
        train_rows = apply_anomaly_baseline(split.train, baseline).dropna(subset=["residual"])
        test_rows = apply_anomaly_baseline(split.test, baseline).dropna(subset=["residual"])
        if train_rows.empty or test_rows.empty:
            metrics[split.name] = {"evaluated": False, "reason": "no residual rows after baseline"}
            continue

        model = _regressor()
        model.fit(
            _matrix(train_rows, ANOMALY_RESIDUAL),
            train_rows["residual"].to_numpy(dtype=float),
        )
        predicted_residual = model.predict(_matrix(test_rows, ANOMALY_RESIDUAL))
        residual_metrics = regression_metrics(
            test_rows["residual"].to_numpy(dtype=float), predicted_residual
        )

        # Detection: an alert fires when observed PM2.5 exceeds what the
        # meteorology-conditioned model expected, by more than a margin.
        expected = test_rows["baseline_pm25"].to_numpy(dtype=float) + predicted_residual
        observed = test_rows["pm25"].to_numpy(dtype=float)
        exceedance = observed >= CPCB_VERY_POOR_PM25
        margin = float(np.nanstd(test_rows["residual"].to_numpy(dtype=float))) or 1.0
        alert = (observed - expected) > margin
        detection = detection_metrics(exceedance, alert)

        metrics[split.name] = {
            "evaluated": True,
            "detail": split.detail,
            "residual_model": residual_metrics,
            "detection_vs_cpcb_very_poor": detection,
            "label_definition": (
                f"observed pm25 >= {CPCB_VERY_POOR_PM25} ug/m3 (CPCB NAQI 'Very Poor' breakpoint)"
            ),
            "positive_rate": round(float(np.mean(exceedance)), 6),
        }

    full_baseline = fit_anomaly_baseline(data)
    annotated = apply_anomaly_baseline(data, full_baseline).dropna(subset=["residual"])
    final = _regressor()
    final.fit(
        _matrix(annotated, ANOMALY_RESIDUAL),
        annotated["residual"].to_numpy(dtype=float),
    )

    version = f"hgb-anomaly-{datetime.now(UTC):%Y%m%d%H%M}"
    bundle = {
        "model": final,
        "feature_names": list(ANOMALY_RESIDUAL.names),
        "target": ANOMALY_RESIDUAL.target,
        "ml_feature_version": ML_FEATURE_VERSION,
        "baseline": full_baseline.to_dict(orient="records"),
        "baseline_global_median": full_baseline.attrs.get("global_median"),
        "residual_std": float(np.nanstd(annotated["residual"].to_numpy(dtype=float))),
        "exceedance_threshold": CPCB_VERY_POOR_PM25,
    }
    path = _save_bundle(bundle, registry, f"{version}.joblib")
    return TrainingResult(
        model_name="anomaly_detector",
        version=version,
        algorithm="sklearn.HistGradientBoostingRegressor (residual on hour-of-week baseline)",
        metrics=metrics,
        artifact_path=path,
        feature_names=list(ANOMALY_RESIDUAL.names),
        notes=(
            "Baseline is fitted on training rows only and applied to held-out "
            "rows. Detection is scored against a CPCB standards-based "
            "exceedance label, not against a residual-derived label."
        ),
    )


# --- Model 3: source likelihood -------------------------------------------

SOURCE_CLASSES = ("biomass_burning", "traffic", "regional_transport", "mixed_unknown")


def weak_source_labels(frame: pd.DataFrame, *, thresholds: dict[str, float]) -> pd.Series:
    """Assign weak source labels from fire, pollutant-ratio and wind signals.

    These are **not ground truth**. They encode domain heuristics so that a
    classifier can be exercised end to end; every downstream consumer must
    treat the output as a probabilistic hint (LLD §18.3, caveat §65.4).

    The columns this rule reads are deliberately absent from
    :data:`SOURCE_LIKELIHOOD`, so the classifier cannot simply re-derive the
    rule from its own inputs.

    Args:
        frame: Rows to label.
        thresholds: Quantile thresholds fitted on the training partition only.

    Returns:
        Label per row.
    """

    # Build the fire signal from explicit Series so that a missing column
    # degrades to an all-False mask rather than to a scalar bool, which would
    # silently broadcast and mislabel every row.
    def _numeric(column: str) -> pd.Series:
        if column not in frame.columns:
            return pd.Series(0.0, index=frame.index)
        return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)

    fire_signal = (_numeric("fire_count") >= 1) | (_numeric("fire_frp") > 0)
    pm25 = frame["pm25"]
    high_pm = pm25 >= thresholds["pm25_high"]
    ratio = frame["no2"] / pm25.replace(0.0, np.nan)
    traffic_hours = frame["timestamp"].dt.hour.isin(range(6, 11))
    traffic_signal = (ratio >= thresholds["no2_ratio_high"]) & traffic_hours
    windy = frame["wind_speed"] >= thresholds["wind_high"]

    labels = pd.Series("mixed_unknown", index=frame.index, dtype=object)
    labels[windy & high_pm] = "regional_transport"
    labels[traffic_signal.fillna(False)] = "traffic"
    labels[fire_signal & high_pm] = "biomass_burning"
    return labels


def fit_label_thresholds(train: pd.DataFrame) -> dict[str, float]:
    """Fit label quantile thresholds on the training partition only.

    Computing these over the full dataset, as the notebook track did, lets the
    label definition peek at held-out rows.

    Args:
        train: Training rows only.

    Returns:
        Threshold values.
    """
    ratio = train["no2"] / train["pm25"].replace(0.0, np.nan)
    return {
        "pm25_high": float(train["pm25"].quantile(0.80)),
        "no2_ratio_high": float(ratio.quantile(0.80)) if ratio.notna().any() else float("inf"),
        "wind_high": float(train["wind_speed"].quantile(0.60))
        if train["wind_speed"].notna().any()
        else float("inf"),
    }


def train_source_likelihood(frame: pd.DataFrame, registry: ModelRegistry) -> TrainingResult:
    """Train the source-likelihood classifier under weak supervision.

    Args:
        frame: Training frame.
        registry: Registry to write the artifact into.

    Returns:
        The training result.

    Raises:
        InsufficientDataError: If too few labelled rows exist.
    """
    data = frame.dropna(subset=["pm25"]).copy()
    _require_rows(data, "source_likelihood")

    metrics: dict[str, Any] = {}
    for split in (temporal_split(data), spatial_split(data)):
        if not split.usable:
            metrics[split.name] = {"evaluated": False, "reason": split.detail}
            continue
        thresholds = fit_label_thresholds(split.train)
        y_train = weak_source_labels(split.train, thresholds=thresholds)
        y_test = weak_source_labels(split.test, thresholds=thresholds)
        if y_train.nunique() < 2:
            metrics[split.name] = {
                "evaluated": False,
                "reason": f"only {y_train.nunique()} label class present in training rows",
            }
            continue

        model = HistGradientBoostingClassifier(
            max_iter=250,
            learning_rate=0.05,
            max_depth=5,
            min_samples_leaf=10,
            random_state=RANDOM_STATE,
        )
        model.fit(_matrix(split.train, SOURCE_LIKELIHOOD), y_train.to_numpy())
        predicted = model.predict(_matrix(split.test, SOURCE_LIKELIHOOD))
        proba = model.predict_proba(_matrix(split.test, SOURCE_LIKELIHOOD))
        report = classification_metrics(
            y_test.to_numpy(),
            predicted,
            probabilities=proba,
            classes=model.classes_,
        )
        # Majority-class accuracy is the only meaningful reference point for a
        # weakly supervised, imbalanced task.
        majority = float(y_test.value_counts(normalize=True).max())
        metrics[split.name] = {
            "evaluated": True,
            "detail": split.detail,
            **report.to_dict(),
            "accuracy": round(float(np.mean(predicted == y_test.to_numpy())), 6),
            "majority_class_rate": round(majority, 6),
            "label_distribution": {
                str(k): int(v) for k, v in y_test.value_counts().to_dict().items()
            },
        }

    thresholds = fit_label_thresholds(data)
    labels = weak_source_labels(data, thresholds=thresholds)
    final: Any = None
    if labels.nunique() >= 2:
        final = HistGradientBoostingClassifier(
            max_iter=250,
            learning_rate=0.05,
            max_depth=5,
            min_samples_leaf=10,
            random_state=RANDOM_STATE,
        )
        final.fit(_matrix(data, SOURCE_LIKELIHOOD), labels.to_numpy())

    version = f"hgb-source-{datetime.now(UTC):%Y%m%d%H%M}"
    bundle = {
        "model": final,
        "feature_names": list(SOURCE_LIKELIHOOD.names),
        "target": SOURCE_LIKELIHOOD.target,
        "ml_feature_version": ML_FEATURE_VERSION,
        "classes": list(final.classes_) if final is not None else [],
        "label_thresholds": thresholds,
        "supervision": "weak-heuristic",
    }
    path = _save_bundle(bundle, registry, f"{version}.joblib")
    return TrainingResult(
        model_name="source_likelihood",
        version=version,
        algorithm="sklearn.HistGradientBoostingClassifier",
        metrics=metrics,
        artifact_path=path,
        feature_names=list(SOURCE_LIKELIHOOD.names),
        notes=(
            "WEAK SUPERVISION. Labels are heuristics, not verified source "
            "attribution. The feature set excludes every signal the label rule "
            "uses, so scores are not inflated by label circularity, but they "
            "also cannot be read as attribution accuracy. Never present as "
            "proven causality."
        ),
    )


# --- Model 4: propagation forecast ----------------------------------------


def build_forecast_frame(frame: pd.DataFrame, horizon_hours: int) -> pd.DataFrame:
    """Attach a future PM2.5 target and a persistence baseline.

    The target is the same cell's PM2.5 ``horizon_hours`` later, so the current
    value is a legitimate input. The model learns the residual over
    persistence, which is the standard way to demonstrate forecast skill.

    Args:
        frame: Training frame.
        horizon_hours: Forecast horizon.

    Returns:
        Rows that have a resolvable future target.
    """
    local = frame.dropna(subset=["pm25"]).copy()
    future = local[["grid_id", "timestamp", "pm25"]].rename(columns={"pm25": "target_pm25"})
    future["timestamp"] = future["timestamp"] - pd.Timedelta(hours=horizon_hours)
    merged = local.merge(future, on=["grid_id", "timestamp"], how="inner")
    merged["persistence"] = merged["pm25"]
    merged["residual_target"] = merged["target_pm25"] - merged["persistence"]
    return merged


def train_propagation_forecast(
    frame: pd.DataFrame,
    registry: ModelRegistry,
    *,
    horizons: tuple[int, ...] = FORECAST_HORIZONS,
) -> TrainingResult:
    """Train residual-over-persistence forecasters for each horizon.

    Args:
        frame: Training frame.
        registry: Registry to write the artifact into.
        horizons: Forecast horizons in hours.

    Returns:
        The training result, with metrics keyed by horizon.

    Raises:
        InsufficientDataError: If no horizon has enough resolvable rows.
    """
    metrics: dict[str, Any] = {}
    models: dict[int, Any] = {}
    trained_any = False

    for horizon in horizons:
        data = build_forecast_frame(frame, horizon)
        key = f"{horizon}h"
        if len(data) < MIN_TRAINING_ROWS:
            metrics[key] = {
                "evaluated": False,
                "reason": f"{len(data)} resolvable rows, need {MIN_TRAINING_ROWS}",
            }
            continue

        horizon_metrics: dict[str, Any] = {}
        for split in (temporal_split(data), spatial_split(data)):
            if not split.usable:
                horizon_metrics[split.name] = {"evaluated": False, "reason": split.detail}
                continue
            model = _regressor()
            model.fit(
                _matrix(split.train, PROPAGATION_FORECAST),
                split.train["residual_target"].to_numpy(dtype=float),
            )
            predicted_residual = model.predict(_matrix(split.test, PROPAGATION_FORECAST))
            predicted = split.test["persistence"].to_numpy(dtype=float) + predicted_residual
            actual = split.test["target_pm25"].to_numpy(dtype=float)

            model_metrics = regression_metrics(actual, predicted)
            persistence_metrics = regression_metrics(
                actual, split.test["persistence"].to_numpy(dtype=float)
            )
            horizon_metrics[split.name] = {
                "evaluated": True,
                "detail": split.detail,
                "model": model_metrics,
                "persistence_baseline": persistence_metrics,
                "skill_vs_persistence": skill_score(
                    model_metrics.get("mae", float("inf")),
                    persistence_metrics.get("mae", 0.0),
                ),
            }

        final = _regressor()
        final.fit(
            _matrix(data, PROPAGATION_FORECAST),
            data["residual_target"].to_numpy(dtype=float),
        )
        models[horizon] = final
        metrics[key] = horizon_metrics
        trained_any = True

    if not trained_any:
        raise InsufficientDataError(
            "propagation_forecast: no horizon had enough resolvable rows; "
            "widen the observation window"
        )

    version = f"hgb-forecast-{datetime.now(UTC):%Y%m%d%H%M}"
    bundle = {
        "models": models,
        "feature_names": list(PROPAGATION_FORECAST.names),
        "target": PROPAGATION_FORECAST.target,
        "ml_feature_version": ML_FEATURE_VERSION,
        "horizons": sorted(models),
        "correction": "residual-over-persistence",
    }
    path = _save_bundle(bundle, registry, f"{version}.joblib")
    return TrainingResult(
        model_name="propagation_forecast",
        version=version,
        algorithm="sklearn.HistGradientBoostingRegressor (residual over persistence)",
        metrics=metrics,
        artifact_path=path,
        feature_names=list(PROPAGATION_FORECAST.names),
        notes=(
            "Corrects a persistence baseline per horizon. skill_vs_persistence "
            "is the number that matters: a value at or below zero means the "
            "model adds nothing and must not be promoted."
        ),
    )


# --- Models 5 and 6: 24-hour peak and hazard ------------------------------
#
# Both are the "Route B" retrain from the integration plan: the notebook Phase
# 7 bundle needs 184 features of which the online path can supply 12, so rather
# than serving a model that would be fed 94% nulls, the same two targets are
# re-fitted on the servable feature set. The notebooks' own SHAP result -
# temporal lags carry 77.7% of attribution - is the reason to expect the loss
# from dropping the other families to be small; `peak_lift_vs_persistence` in
# the metrics is where that expectation is actually tested.
#
# The plan's §5.4 reconciliation is applied here: the two competing hazard
# definitions (150 ug/m3 from the pm25 pipeline, 121 from the anomaly pipeline)
# collapse to one, at the CPCB "Very Poor" breakpoint of 121, so the product
# cannot show two contradictory hazard probabilities for one cell.

#: Horizon over which the peak and hazard targets are computed.
PEAK_HORIZON_HOURS = 24


def build_peak_frame(frame: pd.DataFrame, horizon_hours: int = PEAK_HORIZON_HOURS) -> pd.DataFrame:
    """Attach the forward maximum PM2.5 and its hazard label.

    The target is the maximum over hours ``t+1 .. t+horizon``, so the current
    hour is excluded: including it would let a model that has already seen an
    episode begin trivially "predict" it.

    Args:
        frame: Training frame, one row per grid-hour.
        horizon_hours: Length of the forward window.

    Returns:
        Rows with a resolvable forward window, carrying ``pm25_peak_24h_target``,
        ``hazard_extreme_24h`` and the persistence baseline. Rows whose window
        is only partially observed are dropped rather than filled, because a
        partial maximum understates the peak and would look like a model that
        under-predicts episodes.
    """
    local = frame.dropna(subset=["pm25"]).copy()
    if local.empty:
        return local.assign(pm25_peak_24h_target=[], hazard_extreme_24h=[], persistence=[])

    future = local[["grid_id", "timestamp", "pm25"]]
    windows: list[pd.DataFrame] = []
    for offset in range(1, horizon_hours + 1):
        shifted = future.rename(columns={"pm25": f"fwd_{offset}"}).copy()
        shifted["timestamp"] = shifted["timestamp"] - pd.Timedelta(hours=offset)
        windows.append(shifted)

    merged = local
    for shifted in windows:
        merged = merged.merge(shifted, on=["grid_id", "timestamp"], how="left")

    forward_columns = [f"fwd_{offset}" for offset in range(1, horizon_hours + 1)]
    observed = merged[forward_columns].notna().sum(axis=1)
    # Require the whole window. A maximum taken over 3 of 24 hours is a
    # different quantity from the one the model is asked to predict.
    merged = merged[observed == horizon_hours].copy()
    if merged.empty:
        return merged.drop(columns=forward_columns, errors="ignore").assign(
            pm25_peak_24h_target=[], hazard_extreme_24h=[], persistence=[]
        )

    merged["pm25_peak_24h_target"] = merged[forward_columns].max(axis=1)
    merged["hazard_extreme_24h"] = (merged["pm25_peak_24h_target"] >= CPCB_VERY_POOR_PM25).astype(
        int
    )
    merged["persistence"] = merged["pm25"]
    return merged.drop(columns=forward_columns)


def train_pm25_peak_24h(frame: pd.DataFrame, registry: ModelRegistry) -> TrainingResult:
    """Train the 24-hour peak PM2.5 regressor.

    Predicting the forward maximum rather than the forward mean is the point:
    an alert is about the worst hour a person will breathe, and a squared-error
    model fitted on the point value minimises aggregate loss by predicting
    "no episode", which is exactly the failure the notebooks measured.

    Args:
        frame: Training frame.
        registry: Registry to write the artifact into.

    Returns:
        The training result.

    Raises:
        InsufficientDataError: If too few complete forward windows resolve.
    """
    data = build_peak_frame(frame)
    _require_rows(data, "pm25_peak_24h")

    metrics: dict[str, Any] = {}
    for split in (temporal_split(data), spatial_split(data)):
        if not split.usable:
            metrics[split.name] = {"evaluated": False, "reason": split.detail}
            continue
        model = _regressor()
        model.fit(
            _matrix(split.train, PM25_PEAK_24H),
            split.train["pm25_peak_24h_target"].to_numpy(dtype=float),
        )
        predicted = model.predict(_matrix(split.test, PM25_PEAK_24H))
        actual = split.test["pm25_peak_24h_target"].to_numpy(dtype=float)
        persistence = split.test["persistence"].to_numpy(dtype=float)

        model_metrics = regression_metrics(actual, predicted)
        persistence_metrics = regression_metrics(actual, persistence)
        extreme = actual >= CPCB_VERY_POOR_PM25
        metrics[split.name] = {
            "evaluated": True,
            "detail": split.detail,
            "model": model_metrics,
            "persistence_baseline": persistence_metrics,
            "skill_vs_persistence": skill_score(
                model_metrics.get("mae", float("inf")),
                persistence_metrics.get("mae", 0.0),
            ),
            # Aggregate MAE hides how a model behaves on the hours that
            # matter, so the bias on extreme rows is reported separately.
            "extreme_rows": float(int(extreme.sum())),
            "extreme_bias": (
                round(float(np.mean(predicted[extreme] - actual[extreme])), 6)
                if extreme.any()
                else None
            ),
            "extreme_recall": (
                round(
                    float(np.mean(predicted[extreme] >= CPCB_VERY_POOR_PM25)),
                    6,
                )
                if extreme.any()
                else None
            ),
        }

    final = _regressor()
    final.fit(
        _matrix(data, PM25_PEAK_24H),
        data["pm25_peak_24h_target"].to_numpy(dtype=float),
    )
    residuals = data["pm25_peak_24h_target"].to_numpy(dtype=float) - final.predict(
        _matrix(data, PM25_PEAK_24H)
    )

    version = f"hgb-peak-{datetime.now(UTC):%Y%m%d%H%M}"
    bundle = {
        "model": final,
        "feature_names": list(PM25_PEAK_24H.names),
        "target": PM25_PEAK_24H.target,
        "ml_feature_version": ML_FEATURE_VERSION,
        "residual_std": float(np.std(residuals)) if residuals.size else 0.0,
        "primary_horizon_h": PEAK_HORIZON_HOURS,
        "exceedance_threshold": CPCB_VERY_POOR_PM25,
    }
    path = _save_bundle(bundle, registry, f"{version}.joblib")
    return TrainingResult(
        model_name="pm25_peak_24h",
        version=version,
        algorithm="sklearn.HistGradientBoostingRegressor (forward 24h maximum)",
        metrics=metrics,
        artifact_path=path,
        feature_names=list(PM25_PEAK_24H.names),
        primary_horizon_h=PEAK_HORIZON_HOURS,
        regression_config={
            "estimator": "HistGradientBoostingRegressor",
            "target": "max pm25 over t+1..t+24",
            "exceedance_threshold_ugm3": CPCB_VERY_POOR_PM25,
            "random_state": RANDOM_STATE,
        },
        notes=(
            "Predicts the maximum PM2.5 over the next 24 hours. extreme_bias "
            "on rows above the CPCB Very Poor breakpoint matters more than "
            "aggregate MAE: a model that is accurate on quiet hours and "
            "under-predicts episodes is worse than useless for alerting."
        ),
    )


def train_pm25_hazard_24h(frame: pd.DataFrame, registry: ModelRegistry) -> TrainingResult:
    """Train the reconciled 24-hour hazard classifier.

    One hazard model at one threshold, per integration plan §5.4. The
    threshold is the CPCB "Very Poor" breakpoint rather than the 150 ug/m3 the
    pm25 notebook used, because a public-facing alert should fire on the
    national standard and because two hazard probabilities for one cell is a
    product defect regardless of which is more accurate.

    The honest baseline is the current concentration used directly as a score:
    "it is bad now, so it will be bad later" is a strong predictor at 24 hours,
    and a classifier that cannot beat it has learned nothing worth serving.

    Args:
        frame: Training frame.
        registry: Registry to write the artifact into.

    Returns:
        The training result.

    Raises:
        InsufficientDataError: If too few complete forward windows resolve.
    """
    data = build_peak_frame(frame)
    _require_rows(data, "pm25_hazard_24h")

    metrics: dict[str, Any] = {}
    for split in (temporal_split(data), spatial_split(data)):
        if not split.usable:
            metrics[split.name] = {"evaluated": False, "reason": split.detail}
            continue
        y_train = split.train["hazard_extreme_24h"].to_numpy(dtype=int)
        y_test = split.test["hazard_extreme_24h"].to_numpy(dtype=int)
        if len(set(y_train.tolist())) < 2:
            metrics[split.name] = {
                "evaluated": False,
                "reason": "training partition holds a single hazard class",
            }
            continue

        model = HistGradientBoostingClassifier(random_state=RANDOM_STATE)
        model.fit(_matrix(split.train, PM25_HAZARD_24H), y_train)
        proba = model.predict_proba(_matrix(split.test, PM25_HAZARD_24H))
        fitted_classes = [int(c) for c in np.asarray(model.classes_).tolist()]
        positive_index = fitted_classes.index(1) if 1 in fitted_classes else None
        if positive_index is None:
            metrics[split.name] = {
                "evaluated": False,
                "reason": "model never saw a positive hazard row",
            }
            continue
        scores = proba[:, positive_index]

        metrics[split.name] = {
            "evaluated": True,
            "detail": split.detail,
            "model": ranking_metrics(y_test, scores),
            # The baseline is the current concentration, not a constant: at a
            # 24h horizon persistence of "already bad" is the bar to clear.
            "current_pm25_baseline": ranking_metrics(
                y_test, split.test["pm25"].to_numpy(dtype=float)
            ),
            "detection_at_0.5": detection_metrics(y_test, scores >= 0.5),
        }

    y_all = data["hazard_extreme_24h"].to_numpy(dtype=int)
    if len(set(y_all.tolist())) < 2:
        raise InsufficientDataError(
            "pm25_hazard_24h: the window holds a single hazard class, so no "
            "classifier can be fitted or evaluated honestly"
        )
    final = HistGradientBoostingClassifier(random_state=RANDOM_STATE)
    final.fit(_matrix(data, PM25_HAZARD_24H), y_all)

    version = f"hgb-hazard-{datetime.now(UTC):%Y%m%d%H%M}"
    bundle = {
        "model": final,
        "feature_names": list(PM25_HAZARD_24H.names),
        "target": PM25_HAZARD_24H.target,
        "ml_feature_version": ML_FEATURE_VERSION,
        "classes": [int(c) for c in np.asarray(final.classes_).tolist()],
        "hazard_threshold_ugm3": CPCB_VERY_POOR_PM25,
        "primary_horizon_h": PEAK_HORIZON_HOURS,
        # Uncalibrated. Recorded explicitly so a consumer does not read the
        # score as a calibrated probability before isotonic/Platt fitting on a
        # held-out window has been run and measured.
        "calibration": "none",
    }
    path = _save_bundle(bundle, registry, f"{version}.joblib")
    return TrainingResult(
        model_name="pm25_hazard_24h",
        version=version,
        algorithm="sklearn.HistGradientBoostingClassifier (P(peak >= 121 within 24h))",
        metrics=metrics,
        artifact_path=path,
        feature_names=list(PM25_HAZARD_24H.names),
        primary_horizon_h=PEAK_HORIZON_HOURS,
        calibration="none",
        regression_config={
            "estimator": "HistGradientBoostingClassifier",
            "target": f"peak pm25 over t+1..t+24 >= {CPCB_VERY_POOR_PM25}",
            "random_state": RANDOM_STATE,
        },
        notes=(
            f"Single reconciled hazard definition at the CPCB Very Poor "
            f"breakpoint ({CPCB_VERY_POOR_PM25:.0f} ug/m3). Scores are "
            "uncalibrated, so they rank hours correctly but must not be "
            "presented as probabilities until calibration is fitted and its "
            "ECE measured on a held-out window."
        ),
    )


TRAINERS = {
    "pm25_estimator": train_pm25_estimator,
    "anomaly_detector": train_anomaly_detector,
    "source_likelihood": train_source_likelihood,
    "propagation_forecast": train_propagation_forecast,
    "pm25_peak_24h": train_pm25_peak_24h,
    "pm25_hazard_24h": train_pm25_hazard_24h,
}

#: Minimum detection F1 before an anomaly detector may serve. A detector that
#: almost never fires has excellent precision and is still useless.
MIN_DETECTION_F1 = 0.30

#: A weakly supervised classifier must beat always-guess-the-majority-class by
#: this margin, measured on macro F1 rather than accuracy.
MIN_MACRO_F1 = 0.50

#: Peak-model gates, carried over from the notebooks' own Phase 7 criteria so
#: that the production gate is no easier to pass than the research one.
#: `extreme recall 0.675 < 0.70` is one of the two gates the notebook bundle
#: failed; keeping the threshold means this trainer must actually improve on
#: it rather than be waved through.
MIN_PEAK_EXTREME_RECALL = 0.70
#: Under-predicting an episode is the dangerous direction, so the tolerated
#: negative bias on extreme rows is bounded. The notebook peak model measured
#: -32.4 ug/m3 and the concentration model -70.6; both would fail this.
MAX_PEAK_EXTREME_BIAS = -25.0

#: A hazard classifier must rank hazardous hours better than simply reading
#: the current concentration, which is a strong 24-hour predictor on its own.
#: Expressed as a required PR-AUC margin over that baseline rather than an
#: absolute floor, because the achievable PR-AUC depends on the base rate.
MIN_HAZARD_PR_AUC_MARGIN = 0.05
#: An alerting model that fires on more than this fraction of quiet hours will
#: be ignored by operators regardless of its recall (LLD §45).
MAX_HAZARD_FALSE_ALERT_RATE = 0.10


def evaluate_promotion_gate(result: TrainingResult) -> list[str]:
    """Return the reasons a model must not be promoted, empty if it may be.

    Metrics are only worth computing if they can block a release. Without this
    gate the registry would happily mark a model PRODUCTION while its own
    report showed it performing worse than the baseline it replaces.

    Args:
        result: Training outcome to judge.

    Returns:
        Human-readable blocking reasons, empty when the model passes.
    """
    failures: list[str] = []
    metrics = result.metrics

    if result.model_name == "pm25_estimator":
        for holdout in ("temporal", "spatial", "seasonal"):
            block = metrics.get(holdout) or {}
            if not block.get("evaluated"):
                reason = block.get("reason")
                suffix = f" ({reason})" if reason else ""
                failures.append(f"{holdout} holdout was not evaluable{suffix}")
                continue
            skill = block.get("skill_vs_baseline")
            if skill is not None and skill <= 0:
                failures.append(f"{holdout} skill vs persistence is {skill:+.4f} (must exceed 0)")
        temporal = metrics.get("temporal", {})
        if temporal.get("evaluated"):
            r2 = temporal.get("r2")
            if r2 is not None and r2 <= 0:
                failures.append(f"temporal R2 is {r2:.4f} (must exceed 0)")

    elif result.model_name == "anomaly_detector":
        temporal = metrics.get("temporal", {})
        if not temporal.get("evaluated"):
            failures.append("temporal holdout was not evaluable")
        else:
            detection = temporal.get("detection_vs_cpcb_very_poor", {})
            f1 = detection.get("f1")
            if f1 is None or f1 < MIN_DETECTION_F1:
                failures.append(
                    f"detection F1 is {f1} against the CPCB exceedance label "
                    f"(must reach {MIN_DETECTION_F1}); recall "
                    f"{detection.get('recall')} means most exceedances are missed"
                )

    elif result.model_name == "source_likelihood":
        temporal = metrics.get("temporal", {})
        if not temporal.get("evaluated"):
            failures.append("temporal holdout was not evaluable")
        else:
            macro = temporal.get("macro_f1", 0.0)
            if macro < MIN_MACRO_F1:
                failures.append(f"macro F1 is {macro:.4f} (must reach {MIN_MACRO_F1})")
            dead = [
                cls
                for cls, stats in temporal.get("per_class", {}).items()
                if stats.get("support", 0) > 0 and stats.get("f1", 0.0) == 0.0
            ]
            if dead:
                failures.append(f"classes never predicted correctly: {sorted(dead)}")

    elif result.model_name == "propagation_forecast":
        negative: list[str] = []
        evaluated = False
        for horizon, horizon_metrics in metrics.items():
            if not isinstance(horizon_metrics, dict):
                continue
            temporal = horizon_metrics.get("temporal", {})
            if not isinstance(temporal, dict) or not temporal.get("evaluated"):
                continue
            evaluated = True
            skill = temporal.get("skill_vs_persistence")
            if skill is not None and skill <= 0:
                negative.append(f"{horizon} skill {skill:+.4f}")
        if not evaluated:
            failures.append("no horizon had an evaluable temporal holdout")
        if negative:
            failures.append("horizons at or below persistence skill: " + ", ".join(negative))

    elif result.model_name == "pm25_peak_24h":
        temporal = metrics.get("temporal", {})
        if not temporal.get("evaluated"):
            failures.append("temporal holdout was not evaluable")
        else:
            skill = temporal.get("skill_vs_persistence")
            if skill is not None and skill <= 0:
                failures.append(f"temporal skill vs persistence is {skill:+.4f} (must exceed 0)")
            if not temporal.get("extreme_rows"):
                failures.append(
                    "the temporal holdout contains no rows above the CPCB Very Poor "
                    "breakpoint, so episode behaviour is unmeasured and cannot be cleared"
                )
            else:
                recall = temporal.get("extreme_recall")
                if recall is None or recall < MIN_PEAK_EXTREME_RECALL:
                    failures.append(
                        f"extreme recall is {recall} (must reach {MIN_PEAK_EXTREME_RECALL}); "
                        "episodes would be missed"
                    )
                bias = temporal.get("extreme_bias")
                if bias is not None and bias < MAX_PEAK_EXTREME_BIAS:
                    failures.append(
                        f"extreme bias is {bias:+.1f} ug/m3 (must not fall below "
                        f"{MAX_PEAK_EXTREME_BIAS}); the model under-predicts episodes"
                    )
        # The spatial holdout is gated too, unlike the older models. This one
        # is sold as hyper-local prediction for cells with no station of their
        # own, so a model that only works in cells it was fitted on has failed
        # at the thing it exists to do. Time-only validation cannot see that.
        spatial = metrics.get("spatial", {})
        if spatial.get("evaluated") and spatial.get("extreme_rows"):
            spatial_recall = spatial.get("extreme_recall")
            if spatial_recall is None or spatial_recall < MIN_PEAK_EXTREME_RECALL:
                failures.append(
                    f"extreme recall on held-out cells is {spatial_recall} "
                    f"(must reach {MIN_PEAK_EXTREME_RECALL}); the model does not "
                    "generalise to cells it was not fitted on"
                )

    elif result.model_name == "pm25_hazard_24h":
        temporal = metrics.get("temporal", {})
        if not temporal.get("evaluated"):
            failures.append("temporal holdout was not evaluable")
        else:
            model_pr = (temporal.get("model") or {}).get("pr_auc")
            baseline_pr = (temporal.get("current_pm25_baseline") or {}).get("pr_auc")
            if model_pr is None:
                failures.append("PR-AUC was not computable; the holdout has a single class")
            elif baseline_pr is not None and model_pr < baseline_pr + MIN_HAZARD_PR_AUC_MARGIN:
                failures.append(
                    f"PR-AUC {model_pr:.4f} does not beat the current-pm25 baseline "
                    f"{baseline_pr:.4f} by {MIN_HAZARD_PR_AUC_MARGIN}; reading the "
                    "current concentration would do as well"
                )
            false_alerts = (temporal.get("detection_at_0.5") or {}).get("false_alert_rate")
            if false_alerts is not None and false_alerts > MAX_HAZARD_FALSE_ALERT_RATE:
                failures.append(
                    f"false-alert rate is {false_alerts:.4f} at the 0.5 operating point "
                    f"(must not exceed {MAX_HAZARD_FALSE_ALERT_RATE})"
                )

    return failures


def register_result(
    result: TrainingResult,
    registry: ModelRegistry,
    dataset_metadata: dict[str, Any],
    *,
    frame: pd.DataFrame,
    promote: bool = False,
    force: bool = False,
) -> tuple[ModelRecord, list[str]]:
    """Write a training result into the registry, applying the promotion gate.

    Args:
        result: Training outcome.
        registry: Target registry.
        dataset_metadata: Dataset provenance.
        frame: Training frame, used to record season coverage.
        promote: Attempt to walk the model to PRODUCTION.
        force: Promote even when the gate fails. For demos and drills only;
            the blocking reasons are still recorded on the record.

    Returns:
        ``(record, gate_failures)``. A non-empty failure list with
        ``promote=True`` means the model was deliberately held back.
    """
    gate_failures = evaluate_promotion_gate(result)
    notes = result.notes
    if gate_failures:
        notes = (
            (notes + " | " if notes else "") + "PROMOTION GATE FAILED: " + "; ".join(gate_failures)
        )

    record = ModelRecord(
        model_id=result.version,
        model_name=result.model_name,
        version=result.version,
        stage=ModelStage.TRAINING,
        algorithm=result.algorithm,
        feature_version=str(dataset_metadata.get("feature_version", "")),
        ml_feature_version=ML_FEATURE_VERSION,
        feature_names=result.feature_names,
        training_dataset_version=str(dataset_metadata.get("ml_feature_version", "")),
        dataset=dataset_metadata,
        code_commit=code_commit(),
        training_time=datetime.now(UTC),
        season=_season_label(frame),
        metrics=result.metrics,
        artifact_uri=str(result.artifact_path) if result.artifact_path else "",
        notes=notes,
        dataset_fingerprint=dataset_fingerprint(frame),
        calibration=result.calibration,
        regression_config=result.regression_config,
        primary_horizon_h=result.primary_horizon_h,
        gate_failures=gate_failures,
    )
    registry.register(record)

    if promote and (not gate_failures or force):
        registry.promote_to_production(record.model_id)
    elif promote:
        # Held at VALIDATION: registered and inspectable, but never served.
        registry.transition(record.model_id, ModelStage.VALIDATION)

    refreshed = registry.get(record.model_id)
    return (refreshed or record), gate_failures
