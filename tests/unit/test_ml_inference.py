"""Guards on champion loading and the train/serve feature contract.

The mismatch these tests cover is the concrete failure this work set out to fix:
an artifact trained against a different feature list must be refused rather
than silently handed a permuted vector, which would return confident nonsense.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import pandas as pd
import pytest
from aeropulse_contracts.feature_spec import (
    ML_FEATURE_VERSION,
    PM25_ESTIMATOR,
)
from aeropulse_ml.inference import (
    FeatureContractMismatchError,
    ModelBundleCache,
    predict_latest,
    predict_pm25,
    validate_feature_contract,
)
from aeropulse_ml.registry import ModelRecord, ModelRegistry, ModelStage


class _ConstantModel:
    """Minimal stand-in that records the matrix width it was given."""

    def __init__(self, value: float = 100.0) -> None:
        self.value = value
        self.seen_width: int | None = None

    def predict(self, matrix: Any) -> list[float]:
        self.seen_width = matrix.shape[1]
        return [self.value] * matrix.shape[0]


def _bundle(**overrides: Any) -> dict[str, Any]:
    bundle: dict[str, Any] = {
        "model": _ConstantModel(),
        "feature_names": list(PM25_ESTIMATOR.names),
        "target": "pm25",
        "ml_feature_version": ML_FEATURE_VERSION,
        "residual_std": 10.0,
    }
    bundle.update(overrides)
    return bundle


def _register(registry: ModelRegistry, bundle: dict[str, Any]) -> ModelRecord:
    registry.root.mkdir(parents=True, exist_ok=True)
    path = registry.root / "champion.joblib"
    joblib.dump(bundle, path)
    record = ModelRecord(
        model_id="champion",
        model_name="pm25_estimator",
        version="champion",
        artifact_uri=str(path),
    )
    registry.register(record)
    registry.promote_to_production("champion")
    return record


@pytest.fixture
def registry(tmp_path: Path) -> ModelRegistry:
    """Registry rooted in a temporary directory."""
    return ModelRegistry(tmp_path / "models")


def _row() -> pd.Series:
    data: dict[str, Any] = dict.fromkeys(PM25_ESTIMATOR.names, 1.0)
    data["grid_id"] = "cell0"
    data["timestamp"] = pd.Timestamp("2026-09-08T06:00:00Z")
    data["pm25"] = 140.0
    return pd.Series(data)


# --- contract validation ---


def test_matching_contract_validates() -> None:
    """The happy path must pass without ceremony."""
    validate_feature_contract("pm25_estimator", _bundle())


def test_renamed_feature_is_rejected() -> None:
    """This is exactly the notebook-vs-serving skew that motivated the guard."""
    names = list(PM25_ESTIMATOR.names)
    names[names.index("temperature")] = "temperature_2m"
    with pytest.raises(FeatureContractMismatchError, match="does not match"):
        validate_feature_contract("pm25_estimator", _bundle(feature_names=names))


def test_reordered_features_are_rejected() -> None:
    """Tree models are positional once serialised; order is contractual."""
    names = list(PM25_ESTIMATOR.names)
    names[0], names[1] = names[1], names[0]
    with pytest.raises(FeatureContractMismatchError):
        validate_feature_contract("pm25_estimator", _bundle(feature_names=names))


def test_missing_feature_is_rejected() -> None:
    """A shorter vector must never be silently padded."""
    with pytest.raises(FeatureContractMismatchError):
        validate_feature_contract(
            "pm25_estimator", _bundle(feature_names=list(PM25_ESTIMATOR.names)[:-1])
        )


def test_stale_ml_feature_version_is_rejected() -> None:
    """An artifact from an older spec must not be served."""
    with pytest.raises(FeatureContractMismatchError, match="ml_feature_version"):
        validate_feature_contract("pm25_estimator", _bundle(ml_feature_version="ml-features-0.9.0"))


# --- champion loading and degradation ---


def test_no_champion_degrades_instead_of_raising(registry: ModelRegistry) -> None:
    """LLD 40: a missing model must not stop the pipeline."""
    cache = ModelBundleCache(registry)
    result = predict_pm25(_row(), cache)
    assert result["available"] is False
    assert "no PRODUCTION model" in result["reason"]


def test_champion_is_used_when_valid(registry: ModelRegistry) -> None:
    """A promoted, contract-valid artifact must actually serve."""
    _register(registry, _bundle())
    cache = ModelBundleCache(registry)
    result = predict_pm25(_row(), cache)
    assert result["available"] is True
    assert result["pm25_estimate"] == 100.0
    assert result["model_version"] == "champion"


def test_prediction_carries_an_interval(registry: ModelRegistry) -> None:
    """LLD 18.1 requires an interval alongside the point estimate."""
    _register(registry, _bundle())
    result = predict_pm25(_row(), ModelBundleCache(registry))
    assert result["prediction_interval_low"] < result["pm25_estimate"]
    assert result["prediction_interval_high"] > result["pm25_estimate"]


def test_mismatched_artifact_degrades_and_reports_why(registry: ModelRegistry) -> None:
    """A bad artifact must be refused, and the reason must be visible."""
    _register(registry, _bundle(feature_names=["only_one_feature"]))
    cache = ModelBundleCache(registry)
    result = predict_pm25(_row(), cache)
    assert result["available"] is False
    assert "FeatureContractMismatchError" in cache.load_errors["pm25_estimator"]


def test_corrupt_artifact_degrades(registry: ModelRegistry) -> None:
    """An unreadable file must not crash serving."""
    registry.root.mkdir(parents=True, exist_ok=True)
    path = registry.root / "champion.joblib"
    path.write_bytes(b"not a joblib payload")
    registry.register(
        ModelRecord(
            model_id="champion",
            model_name="pm25_estimator",
            version="champion",
            artifact_uri=str(path),
        )
    )
    registry.promote_to_production("champion")
    cache = ModelBundleCache(registry)
    assert predict_pm25(_row(), cache)["available"] is False
    assert "pm25_estimator" in cache.load_errors


def test_model_receives_the_full_contracted_width(registry: ModelRegistry) -> None:
    """Width drift is the silent form of the skew bug."""
    bundle = _bundle()
    _register(registry, bundle)
    cache = ModelBundleCache(registry)
    predict_pm25(_row(), cache)
    loaded = cache.get("pm25_estimator")
    assert loaded is not None
    assert loaded.bundle["model"].seen_width == len(PM25_ESTIMATOR.names)


def test_predict_latest_surfaces_degraded_models(registry: ModelRegistry) -> None:
    """Operators must see partial degradation rather than quiet gaps."""
    frame = pd.DataFrame([_row().to_dict()])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    output = predict_latest(frame, ModelBundleCache(registry))
    assert output["ml_feature_version"] == ML_FEATURE_VERSION
    assert len(output["cells"]) == 1
    assert set(output["degraded_models"]) >= {"pm25_estimator"}


def test_predict_latest_returns_one_row_per_cell(registry: ModelRegistry) -> None:
    """Only the newest grid-hour per cell should be scored."""
    rows = []
    for cell in ("cell0", "cell1"):
        for hour in (5, 6):
            row = _row().to_dict()
            row["grid_id"] = cell
            row["timestamp"] = pd.Timestamp(f"2026-09-08T0{hour}:00:00Z")
            rows.append(row)
    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    output = predict_latest(frame, ModelBundleCache(registry))
    assert len(output["cells"]) == 2
    assert all(c["timestamp"].startswith("2026-09-08T06") for c in output["cells"])


def test_cache_does_not_reload_on_every_call(registry: ModelRegistry) -> None:
    """Per-request artifact loading would dominate inference latency."""
    _register(registry, _bundle())
    cache = ModelBundleCache(registry)
    first = cache.get("pm25_estimator")
    second = cache.get("pm25_estimator")
    assert first is second


def test_retired_champion_is_not_served(registry: ModelRegistry) -> None:
    """Rolling back must take effect immediately for new caches."""
    _register(registry, _bundle())
    registry.transition("champion", ModelStage.RETIRED, force=True)
    assert predict_pm25(_row(), ModelBundleCache(registry))["available"] is False
