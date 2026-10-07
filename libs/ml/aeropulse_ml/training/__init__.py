"""Shared training, evaluation and gate reporting for every family."""

from aeropulse_ml.training.runner import (
    TrainingRun,
    aggregate,
    build_frame,
    promotion_snippet,
    train_family,
)

__all__ = ["TrainingRun", "aggregate", "build_frame", "promotion_snippet", "train_family"]
