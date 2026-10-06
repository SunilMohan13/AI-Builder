"""SDK-level request/response types (not source-specific)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ConnectorMetadata(BaseModel):
    """Declarative connector identity loaded from metadata.yaml."""

    model_config = {"extra": "allow"}

    connector_id: str
    version: str
    provider: str
    data_type: str
    transport: str = "https"
    output_contract: list[str] = Field(default_factory=list)


class SourceAsset(BaseModel):
    """A discoverable station, product, or spatial asset."""

    asset_id: str
    name: str
    extra: dict[str, Any] = Field(default_factory=dict)


class FetchRequest(BaseModel):
    """A connector fetch window."""

    start_time: datetime | None = None
    end_time: datetime | None = None
    bbox: tuple[float, float, float, float] | None = None
    processing_mode: Literal["LIVE", "BACKFILL"] = "LIVE"
    cursor: str | None = None
    provider: str | None = None


class RawRecord(BaseModel):
    """Immutable source-native payload plus fetch metadata."""

    source_id: str
    source_record_id: str
    payload: dict[str, Any]
    fetched_at: datetime
    raw_uri: str | None = None


class HealthStatus(BaseModel):
    """Connector liveness/readiness snapshot."""

    connector_id: str
    healthy: bool
    message: str = "ok"
    checked_at: datetime
