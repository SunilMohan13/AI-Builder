"""Grid prediction and anomaly contracts (LLD sections 18.1 and 18.2)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AnomalyResult(BaseModel):
    """Anomaly detector output (quantile-baseline-0.1)."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["anomaly.v1"] = "anomaly.v1"
    model_version: str = "quantile-baseline-0.1"
    grid_id: str
    timestamp: datetime
    observed_pm25: float | None = None
    baseline_pm25: float | None = None
    residual: float | None = None
    anomaly_score: float = Field(..., ge=0.0, le=1.0)
    event_trigger: bool = False


class GridPrediction(BaseModel):
    """PM2.5 estimate for a cell (baseline-idw-0.1)."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["prediction.v1"] = "prediction.v1"
    model_version: str = "baseline-idw-0.1"
    grid_id: str
    timestamp: datetime
    pm25_estimate: float
    prediction_interval_low: float
    prediction_interval_high: float
    confidence: float = Field(..., ge=0.0, le=1.0)
