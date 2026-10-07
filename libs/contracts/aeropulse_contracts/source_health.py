"""Source health as reported by a cycle (source_health.v1)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class SourceState(StrEnum):
    """Outcome of one source in one cycle."""

    HEALTHY = "healthy"
    REPLAY = "replay"
    NOT_CONFIGURED = "not_configured"
    NOT_DUE = "not_due"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


class SourceHealth(BaseModel):
    """What a source did in a cycle, with a reason whenever it delivered nothing."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["source_health.v1"] = "source_health.v1"
    source_id: str
    region_id: str
    state: SourceState
    reason: str | None = None
    records: int = Field(default=0, ge=0)
    rejected: int = Field(default=0, ge=0)
    last_success_at: datetime | None = None
    watermark: datetime | None = None
    latency_ms: float | None = None
