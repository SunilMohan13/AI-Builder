"""Champion model loading and prediction.

Two invariants are enforced here rather than trusted:

* An artifact is rejected unless its baked-in ``feature_names`` match the
  current shared spec exactly. This is the guard against the train/serve skew
  that previously made the notebook artifacts unloadable: a silent mismatch
  would otherwise feed the model a permuted vector and return plausible
  nonsense.
* A missing, stale or unloadable champion is never fatal. Callers fall back to
  the deterministic baseline with reduced confidence, per LLD §40.

Trust boundary: artifacts are deserialised with :func:`joblib.load`, which is
pickle-based and therefore executes arbitrary code from the payload. This is
only safe because the registry root is a deployment-controlled location written
exclusively by this package's own training runs. Never point
``AEROPULSE_MODEL_DIR`` at a directory that accepts third-party uploads, and
never fetch artifacts from an untrusted registry mirror. Moving to object
storage must keep that property (signed, write-restricted bucket); if artifacts
ever become externally supplied, this loader must be replaced with a
schema-validated format such as ONNX before that happens.
"""

from __future__ import annotations

from dataclasses import dataclass
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

from aeropulse_ml.registry import ModelRecord, ModelRegistry

FEATURE_SET_BY_MODEL: dict[str, FeatureSet] = {
    "pm25_estimator": PM25_ESTIMATOR,
    "anomaly_detector": ANOMALY_RESIDUAL,
    "source_likelihood": SOURCE_LIKELIHOOD,
    "propagation_forecast": PROPAGATION_FORECAST,
    "pm25_peak_24h": PM25_PEAK_24H,
    "pm25_hazard_24h": PM25_HAZARD_24H,
}


class FeatureContractMismatchError(RuntimeError):
    """Raised when an artifact's feature list disagrees with the current spec."""


@dataclass
class LoadedModel:
    """A champion artifact plus the registry record describing it.

    Attributes:
        record: Registry metadata.
        bundle: Deserialised artifact contents.
    """

    record: ModelRecord
    bundle: dict[str, Any]

    @property
    def feature_names(self) -> list[str]:
        """Return the artifact's baked-in feature order."""
        return list(self.bundle.get("feature_names", []))


def validate_feature_contract(model_name: str, bundle: dict[str, Any]) -> None:
    """Assert an artifact was trained against the current feature spec.

    Args:
        model_name: Model family.
        bundle: Deserialised artifact.

    Raises:
        FeatureContractMismatchError: On any name, order or version mismatch.
    """
    expected = FEATURE_SET_BY_MODEL[model_name]
    actual = list(bundle.get("feature_names", []))
    if actual != list(expected.names):
        missing = sorted(set(expected.names) - set(actual))
        extra = sorted(set(actual) - set(expected.names))
        raise FeatureContractMismatchError(
            f"{model_name}: artifact feature list does not match the current spec "
            f"(missing={missing}, unexpected={extra}, order_changed={set(actual) == set(expected.names)})"
        )
    baked = bundle.get("ml_feature_version")
    if baked and baked != ML_FEATURE_VERSION:
        raise FeatureContractMismatchError(
            f"{model_name}: artifact built for ml_feature_version {baked!r}, "
            f"runtime is {ML_FEATURE_VERSION!r}"
        )


class ModelBundleCache:
    """Load and memoise champion artifacts.

    Args:
        registry: Registry to resolve champions from.
    """

    def __init__(self, registry: ModelRegistry) -> None:
        self.registry = registry
        self._cache: dict[str, LoadedModel | None] = {}
        self.load_errors: dict[str, str] = {}

    def get(self, model_name: str) -> LoadedModel | None:
        """Return the champion for a family, or None when unavailable.

        Failures are recorded in :attr:`load_errors` and returned as None so
        that a bad artifact degrades the system instead of stopping it.

        Args:
            model_name: Model family.

        Returns:
            The loaded champion, or None.
        """
        if model_name in self._cache:
            return self._cache[model_name]

        loaded: LoadedModel | None = None
        record = self.registry.champion(model_name)
        if record is None:
            self.load_errors[model_name] = "no PRODUCTION model registered"
        else:
            try:
                path = self.registry.artifact_path(record)
                bundle = joblib.load(path)
                validate_feature_contract(model_name, bundle)
                loaded = LoadedModel(record=record, bundle=bundle)
            except (
                OSError,
                KeyError,
                ValueError,
                FeatureContractMismatchError,
            ) as exc:
                self.load_errors[model_name] = f"{type(exc).__name__}: {exc}"
        self._cache[model_name] = loaded
        return loaded


#: A prediction is refused below this fraction of populated features. Gradient
#: boosting handles NaN natively, which is convenient and dangerous: a feature
#: family that is silently all-null yields a confident answer rather than an
#: error. The floor turns that into a visible refusal. It is deliberately low —
#: the point is to catch a collapsed input path, not to demand a full vector,
#: since sparse co-pollutant and satellite coverage is normal here.
MIN_FEATURE_COMPLETENESS = 0.5


def feature_completeness(row: pd.Series, feature_set: FeatureSet) -> dict[str, Any]:
    """Report how much of a feature vector is actually populated.

    Recorded on every prediction so that a downstream consumer can tell a
    well-supported answer from one computed mostly from imputed nulls.

    Args:
        row: One row of a materialised feature frame.
        feature_set: Feature projection being used.

    Returns:
        ``present``, ``total``, ``ratio`` and the sorted ``missing`` names.
    """
    missing = [name for name in feature_set.names if name not in row.index or pd.isna(row[name])]
    total = len(feature_set.names)
    present = total - len(missing)
    return {
        "present": present,
        "total": total,
        "ratio": round(present / total, 4) if total else 0.0,
        "missing": sorted(missing),
    }


def _insufficient_features(completeness: dict[str, Any], model_name: str) -> dict[str, Any] | None:
    """Return a refusal payload when too little of the vector is populated.

    Args:
        completeness: Output of :func:`feature_completeness`.
        model_name: Model family, for the message.

    Returns:
        A refusal payload, or None when the vector is usable.
    """
    if completeness["ratio"] >= MIN_FEATURE_COMPLETENESS:
        return None
    return {
        "available": False,
        "reason": (
            f"{model_name}: only {completeness['present']}/{completeness['total']} "
            f"features populated, below the {MIN_FEATURE_COMPLETENESS:.0%} floor"
        ),
        "feature_completeness": completeness,
    }


def _row_matrix(row: pd.Series, feature_set: FeatureSet) -> np.ndarray:
    """Project one dataframe row onto a feature set, in contract order."""
    values = [
        float(row[name]) if name in row.index and pd.notna(row[name]) else np.nan
        for name in feature_set.names
    ]
    return np.array([values], dtype=float)


def predict_pm25(row: pd.Series, cache: ModelBundleCache) -> dict[str, Any]:
    """Estimate PM2.5 for one grid-hour using the champion estimator.

    Args:
        row: One row of a materialised feature frame.
        cache: Champion cache.

    Returns:
        Prediction payload including model version and an interval, or a
        ``fallback`` marker when no usable champion exists.
    """
    loaded = cache.get("pm25_estimator")
    if loaded is None:
        return {
            "available": False,
            "reason": cache.load_errors.get("pm25_estimator", "unavailable"),
        }
    completeness = feature_completeness(row, PM25_ESTIMATOR)
    refusal = _insufficient_features(completeness, "pm25_estimator")
    if refusal is not None:
        return refusal
    model = loaded.bundle["model"]
    value = float(model.predict(_row_matrix(row, PM25_ESTIMATOR))[0])
    spread = float(loaded.bundle.get("residual_std", 0.0))
    return {
        "available": True,
        "pm25_estimate": round(value, 3),
        "prediction_interval_low": round(value - 1.96 * spread, 3),
        "prediction_interval_high": round(value + 1.96 * spread, 3),
        "model_version": loaded.record.version,
        "model_name": loaded.record.model_name,
        "feature_version": loaded.record.feature_version,
        "feature_completeness": completeness,
    }


def predict_anomaly(row: pd.Series, cache: ModelBundleCache) -> dict[str, Any]:
    """Score anomaly for one grid-hour against the fitted baseline.

    Args:
        row: One row of a materialised feature frame.
        cache: Champion cache.

    Returns:
        Anomaly payload, or an unavailability marker.
    """
    loaded = cache.get("anomaly_detector")
    if loaded is None:
        return {
            "available": False,
            "reason": cache.load_errors.get("anomaly_detector", "unavailable"),
        }
    observed = row.get("pm25")
    if observed is None or pd.isna(observed):
        return {"available": False, "reason": "no observed pm25 for this cell-hour"}

    baseline_rows = loaded.bundle.get("baseline", [])
    hour_of_week = int(pd.Timestamp(row["timestamp"]).dayofweek) * 24 + int(
        pd.Timestamp(row["timestamp"]).hour
    )
    baseline_value = loaded.bundle.get("baseline_global_median")
    for entry in baseline_rows:
        if entry.get("grid_id") == row.get("grid_id") and entry.get("hour_of_week") == hour_of_week:
            baseline_value = entry.get("baseline_pm25", baseline_value)
            break
    if baseline_value is None:
        return {"available": False, "reason": "no baseline for this cell-hour"}

    predicted_residual = float(
        loaded.bundle["model"].predict(_row_matrix(row, ANOMALY_RESIDUAL))[0]
    )
    expected = float(baseline_value) + predicted_residual
    excess = float(observed) - expected
    spread = float(loaded.bundle.get("residual_std", 0.0)) or 1.0
    threshold = float(loaded.bundle.get("exceedance_threshold", 121.0))
    return {
        "available": True,
        "observed_pm25": round(float(observed), 3),
        "baseline_pm25": round(float(baseline_value), 3),
        "expected_pm25": round(expected, 3),
        "residual": round(excess, 3),
        # Normalised to [0,1] by residual spread so it is comparable across cells.
        "anomaly_score": round(float(min(1.0, max(0.0, excess / (3.0 * spread)))), 4),
        "event_trigger": bool(excess > spread and float(observed) >= threshold),
        "model_version": loaded.record.version,
    }


def predict_source_likelihood(row: pd.Series, cache: ModelBundleCache) -> dict[str, Any]:
    """Return independent source likelihoods for one grid-hour.

    Per LLD §18.3 these are independent likelihoods, not a mutually exclusive
    softmax, so the classifier's probabilities are reported per class without
    being forced to imply exclusivity.

    Args:
        row: One row of a materialised feature frame.
        cache: Champion cache.

    Returns:
        Likelihood payload, or an unavailability marker.
    """
    loaded = cache.get("source_likelihood")
    if loaded is None:
        return {
            "available": False,
            "reason": cache.load_errors.get("source_likelihood", "unavailable"),
        }
    model = loaded.bundle.get("model")
    if model is None:
        return {"available": False, "reason": "artifact holds no fitted classifier"}
    proba = model.predict_proba(_row_matrix(row, SOURCE_LIKELIHOOD))[0]
    classes = [str(c) for c in loaded.bundle.get("classes", model.classes_)]
    return {
        "available": True,
        "likelihoods": {c: round(float(p), 4) for c, p in zip(classes, proba, strict=False)},
        "supervision": loaded.bundle.get("supervision", "weak-heuristic"),
        "caveat": "weak labels; probabilistic hint only, never proven causality",
        "model_version": loaded.record.version,
    }


def predict_forecast(row: pd.Series, cache: ModelBundleCache) -> dict[str, Any]:
    """Forecast PM2.5 at each trained horizon for one grid-hour.

    Args:
        row: One row of a materialised feature frame.
        cache: Champion cache.

    Returns:
        Per-horizon forecast payload, or an unavailability marker.
    """
    loaded = cache.get("propagation_forecast")
    if loaded is None:
        return {
            "available": False,
            "reason": cache.load_errors.get("propagation_forecast", "unavailable"),
        }
    persistence = row.get("pm25")
    if persistence is None or pd.isna(persistence):
        return {"available": False, "reason": "no current pm25 to propagate"}

    matrix = _row_matrix(row, PROPAGATION_FORECAST)
    horizons: dict[str, Any] = {}
    for horizon, model in sorted(loaded.bundle.get("models", {}).items()):
        residual = float(model.predict(matrix)[0])
        horizons[f"{horizon}h"] = {
            "pm25": round(float(persistence) + residual, 3),
            "persistence": round(float(persistence), 3),
            "residual_correction": round(residual, 3),
        }
    return {
        "available": True,
        "horizons": horizons,
        "model_version": loaded.record.version,
        "correction": loaded.bundle.get("correction"),
    }


def predict_peak_24h(row: pd.Series, cache: ModelBundleCache) -> dict[str, Any]:
    """Forecast the maximum PM2.5 over the next 24 hours for one grid-hour.

    Args:
        row: One row of a materialised feature frame.
        cache: Champion cache.

    Returns:
        Peak payload with an interval, or an unavailability marker.
    """
    loaded = cache.get("pm25_peak_24h")
    if loaded is None:
        return {
            "available": False,
            "reason": cache.load_errors.get("pm25_peak_24h", "unavailable"),
        }
    completeness = feature_completeness(row, PM25_PEAK_24H)
    refusal = _insufficient_features(completeness, "pm25_peak_24h")
    if refusal is not None:
        return refusal

    value = float(loaded.bundle["model"].predict(_row_matrix(row, PM25_PEAK_24H))[0])
    spread = float(loaded.bundle.get("residual_std", 0.0))
    threshold = float(loaded.bundle.get("exceedance_threshold", 121.0))
    return {
        "available": True,
        "peak_pm25": round(value, 3),
        "prediction_interval_low": round(value - 1.96 * spread, 3),
        "prediction_interval_high": round(value + 1.96 * spread, 3),
        "horizon_hours": int(loaded.bundle.get("primary_horizon_h", 24)),
        "exceeds_threshold": bool(value >= threshold),
        "threshold_ugm3": threshold,
        "model_version": loaded.record.version,
        "feature_completeness": completeness,
    }


def predict_hazard_24h(row: pd.Series, cache: ModelBundleCache) -> dict[str, Any]:
    """Score the probability of a hazardous 24 hours for one grid-hour.

    The single reconciled hazard definition (integration plan §5.4): one
    model, one threshold, so two contradictory hazard numbers can never reach
    the same map cell.

    Args:
        row: One row of a materialised feature frame.
        cache: Champion cache.

    Returns:
        Hazard payload, or an unavailability marker. ``calibrated`` states
        whether the score may be read as a probability; when it is False the
        value ranks hours but its magnitude is not a frequency.
    """
    loaded = cache.get("pm25_hazard_24h")
    if loaded is None:
        return {
            "available": False,
            "reason": cache.load_errors.get("pm25_hazard_24h", "unavailable"),
        }
    completeness = feature_completeness(row, PM25_HAZARD_24H)
    refusal = _insufficient_features(completeness, "pm25_hazard_24h")
    if refusal is not None:
        return refusal

    model = loaded.bundle["model"]
    classes = [int(c) for c in loaded.bundle.get("classes", model.classes_)]
    if 1 not in classes:
        return {
            "available": False,
            "reason": "artifact was fitted without a positive hazard class",
        }
    proba = model.predict_proba(_row_matrix(row, PM25_HAZARD_24H))[0]
    score = float(proba[classes.index(1)])
    calibration = str(loaded.bundle.get("calibration", "none"))
    return {
        "available": True,
        "hazard_score": round(score, 4),
        "calibrated": calibration not in ("", "none"),
        "calibration": calibration,
        "threshold_ugm3": float(loaded.bundle.get("hazard_threshold_ugm3", 121.0)),
        "horizon_hours": int(loaded.bundle.get("primary_horizon_h", 24)),
        "model_version": loaded.record.version,
        "feature_completeness": completeness,
    }


def predict_latest(frame: pd.DataFrame, cache: ModelBundleCache) -> dict[str, Any]:
    """Run all champion models over the most recent row of each grid cell.

    Args:
        frame: Materialised feature frame.
        cache: Champion cache.

    Returns:
        A JSON-serialisable prediction report, including any model that could
        not be loaded so that degraded operation is visible rather than silent.
    """
    latest = (
        frame.sort_values("timestamp").groupby("grid_id", as_index=False).tail(1)
        if not frame.empty
        else frame
    )
    cells: list[dict[str, Any]] = []
    for _, row in latest.iterrows():
        cells.append(
            {
                "grid_id": row["grid_id"],
                "timestamp": pd.Timestamp(row["timestamp"]).isoformat(),
                "observed_pm25": None if pd.isna(row.get("pm25")) else float(row["pm25"]),
                "pm25_estimate": predict_pm25(row, cache),
                "anomaly": predict_anomaly(row, cache),
                "source_likelihood": predict_source_likelihood(row, cache),
                "forecast": predict_forecast(row, cache),
                "peak_24h": predict_peak_24h(row, cache),
                "hazard_24h": predict_hazard_24h(row, cache),
            }
        )
    return {
        "ml_feature_version": ML_FEATURE_VERSION,
        "cells": cells,
        "degraded_models": dict(cache.load_errors),
    }
