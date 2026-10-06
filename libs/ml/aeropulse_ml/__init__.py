"""AeroPulse training, evaluation, model registry and champion inference."""

from aeropulse_ml.dataset import build_grid_features, describe, features_to_frame
from aeropulse_ml.evaluation import (
    classification_metrics,
    detection_metrics,
    regression_metrics,
    seasonal_split,
    skill_score,
    spatial_split,
    temporal_split,
)
from aeropulse_ml.inference import (
    ModelBundleCache,
    predict_latest,
    validate_feature_contract,
)
from aeropulse_ml.registry import ModelRecord, ModelRegistry, ModelStage
from aeropulse_ml.train import TRAINERS, InsufficientDataError

__all__ = [
    "TRAINERS",
    "InsufficientDataError",
    "ModelBundleCache",
    "ModelRecord",
    "ModelRegistry",
    "ModelStage",
    "build_grid_features",
    "classification_metrics",
    "describe",
    "detection_metrics",
    "features_to_frame",
    "predict_latest",
    "regression_metrics",
    "seasonal_split",
    "skill_score",
    "spatial_split",
    "temporal_split",
    "validate_feature_contract",
]
