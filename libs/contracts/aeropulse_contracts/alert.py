"""Canonical alert contract (LLD section 29)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Alert(BaseModel):
    """Notification payload. Delivery adapters are out of process."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["alert.v1"] = "alert.v1"
    alert_id: str
    event_id: str
    severity: str
    recipient_group: str = "operators"
    message_template: str = "pollution_event"
    message: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    expires_at: datetime | None = None
    channel: Literal["webhook", "log"] = "log"
