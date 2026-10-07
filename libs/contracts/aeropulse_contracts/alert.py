"""Canonical alert contract (LLD section 29).

An alert is about exactly one subject: a pollution event, or (for a citizen
watch, LLD APAC 9.6) a corroborated citizen report. A citizen watch never
names an event, because a citizen observation never creates one.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class Alert(BaseModel):
    """Notification payload. Delivery adapters are out of process."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["alert.v1"] = "alert.v1"
    alert_id: str
    event_id: str | None = None
    report_id: str | None = None
    severity: str
    recipient_group: str = "operators"
    message_template: str = "pollution_event"
    message: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    expires_at: datetime | None = None
    channel: Literal["webhook", "log"] = "log"

    @model_validator(mode="after")
    def _one_subject(self) -> "Alert":
        if (self.event_id is None) == (self.report_id is None):
            raise ValueError("an alert names exactly one of event_id or report_id")
        return self
