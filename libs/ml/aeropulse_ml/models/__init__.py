"""Model plugins, one per family (LLD APAC 7.1)."""

from aeropulse_ml.models.anomaly import AnomalyPlugin
from aeropulse_ml.models.artifacts import file_sha256, load_model, save_model
from aeropulse_ml.models.base import (
    MIN_EVALUATED_FOLDS,
    MIN_FIT_ROWS,
    RANDOM_STATE,
    FittedModel,
    Metrics,
    ModelPlugin,
)
from aeropulse_ml.models.forecast import Pm25ForecastPlugin
from aeropulse_ml.models.hazard import Pm25Hazard24hPlugin
from aeropulse_ml.models.registry import PLUGINS, get_plugin
from aeropulse_ml.models.source_likelihood import SourceLikelihoodPlugin

__all__ = [
    "MIN_EVALUATED_FOLDS",
    "MIN_FIT_ROWS",
    "PLUGINS",
    "RANDOM_STATE",
    "AnomalyPlugin",
    "FittedModel",
    "Metrics",
    "ModelPlugin",
    "Pm25ForecastPlugin",
    "Pm25Hazard24hPlugin",
    "SourceLikelihoodPlugin",
    "file_sha256",
    "get_plugin",
    "load_model",
    "save_model",
]
