"""Pollution event contract (event.v1, LLD §52)."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class EventStatus(StrEnum):
    """Event state machine (LLD §21.1)."""

    DETECTED = "DETECTED"
    VALIDATING = "VALIDATING"
    CONFIRMED = "CONFIRMED"
    FORECASTING = "FORECASTING"
    ACTIVE = "ACTIVE"
    DECLINING = "DECLINING"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class EventSeverity(StrEnum):
    """Operational severity derived from PM2.5 / anomaly."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class EventEvidence(BaseModel):
    """One corroborating evidence item attached to an event."""

    model_config = {"extra": "forbid"}

    evidence_id: str
    evidence_type: str
    observation_id: str | None = None
    grid_id: str | None = None
    summary: str
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime | None = None


class EventConfidence(BaseModel):
    """Split confidence dimensions (LLD §21.3). Unavailable dims are 0."""

    model_config = {"extra": "forbid"}

    detection_confidence: float = Field(..., ge=0.0, le=1.0)
    source_likelihood_confidence: float = Field(..., ge=0.0, le=1.0)
    forecast_confidence: float = Field(0.0, ge=0.0, le=1.0)
    impact_confidence: float = Field(0.0, ge=0.0, le=1.0)
    evidence_freshness: float = Field(..., ge=0.0, le=1.0)
    sensor_coverage: float = Field(..., ge=0.0, le=1.0)
    overall_confidence: float = Field(..., ge=0.0, le=1.0)


class PollutionEvent(BaseModel):
    """Canonical pollution event independent of UI rendering."""

    model_config = {"extra": "forbid"}

    event_id: str
    event_type: Literal["pollution"] = "pollution"
    schema_version: Literal["event.v1"] = "event.v1"
    status: EventStatus
    severity: EventSeverity
    created_at: datetime
    updated_at: datetime
    geometry: str | None = None
    grid_ids: list[str] = Field(default_factory=list)
    pollutants: list[str] = Field(default_factory=lambda: ["PM2.5"])
    detection_confidence: float = Field(..., ge=0.0, le=1.0)
    source_confidence: float = Field(..., ge=0.0, le=1.0)
    forecast_confidence: float = Field(0.0, ge=0.0, le=1.0)
    impact_confidence: float = Field(0.0, ge=0.0, le=1.0)
    overall_confidence: float = Field(..., ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)
    model_versions: list[str] = Field(default_factory=list)
    feature_version: str = "grid-features-0.4.0"
    evidence_freshness: float = Field(0.0, ge=0.0, le=1.0)
    sensor_coverage: float = Field(0.0, ge=0.0, le=1.0)
