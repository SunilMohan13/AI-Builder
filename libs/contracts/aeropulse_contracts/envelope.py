"""Kafka envelope wrapping canonical payloads."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProcessingMode(StrEnum):
    """Distinguishes live operational data from historical replay."""

    LIVE = "LIVE"
    BACKFILL = "BACKFILL"


class KafkaEnvelope(BaseModel):
    """Versioned envelope published to Kafka topics."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["envelope.v1"] = "envelope.v1"
    produced_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    processing_mode: ProcessingMode = ProcessingMode.LIVE
    correlation_id: str
    source_id: str
    payload: dict[str, Any]
