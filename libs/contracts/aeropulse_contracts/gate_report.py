"""Gate report (gate_report.v1) and evaluation metric rows (LLD APAC 7.7-7.9).

Written by the training job next to the artifact. The serving resolver reads
it to decide whether a ``model_serving.yaml`` entry may serve; the ML
evaluation page reads the metric rows. Neither invents a number: a strategy
the data could not support carries ``available=False`` and a reason.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

GATE_REPORT_SCHEMA = "gate_report.v1"

ModelFamily = Literal["pm25_forecast", "pm25_hazard_24h", "anomaly", "source_likelihood"]
MODEL_FAMILIES: tuple[str, ...] = (
    "pm25_forecast",
    "pm25_hazard_24h",
    "anomaly",
    "source_likelihood",
)
#: Measured but never trained or gated here (LLD APAC 9.8).
EvalFamily = ModelFamily | Literal["citizen_ai_observation"]


class _Strict(BaseModel):
    model_config = {"extra": "forbid"}


class DatasetLineage(_Strict):
    uri: str
    kind: Literal["bigquery", "parquet", "fixture", "synthetic"]
    fingerprint: str
    rows: int = Field(..., ge=0)
    labelled_rows: int = Field(..., ge=0)
    regions: list[str]
    start: datetime | None = None
    end: datetime | None = None
    preprocessing_version: str


class StrategyResult(_Strict):
    strategy: str
    available: bool
    reason: str | None = None
    folds: list[dict[str, Any]] = Field(default_factory=list)
    #: ``{group: {subject: {metric: value}}}``; fold means, plus ``*_std``.
    metrics: dict[str, Any] = Field(default_factory=dict)


class RegionGate(_Strict):
    region_id: str
    passed: bool
    failures: list[str] = Field(default_factory=list)
    labelled_rows: int = Field(..., ge=0)
    #: Hazard only: the served score is a probability in this region.
    calibrated: bool = False
    strategies: list[StrategyResult] = Field(default_factory=list)


class GateReport(_Strict):
    schema_version: Literal["gate_report.v1"] = "gate_report.v1"
    run_id: str
    family: ModelFamily
    model_version: str
    algorithm: str
    ml_feature_version: str
    feature_names: list[str]
    calibrated: bool
    #: ``False`` for synthetic data or a heuristic: never served as a model.
    servable: bool
    servable_reason: str | None = None
    artifact_uri: str
    artifact_sha256: str | None = None
    code_commit: str
    trained_at: datetime
    dataset: DatasetLineage
    regions: list[RegionGate]
    notes: list[str] = Field(default_factory=list)

    def region(self, region_id: str) -> RegionGate | None:
        return next((r for r in self.regions if r.region_id == region_id), None)

    def passed_for(self, region_id: str) -> bool:
        gate = self.region(region_id)
        return bool(self.servable and gate is not None and gate.passed)


class EvalMetricRow(_Strict):
    """One row of ``aeropulse_eval.reports``."""

    run_id: str
    family: EvalFamily
    model_version: str
    region_id: str
    strategy: str
    group: str
    subject: str
    metric: str
    value: float | None
    passed: bool
