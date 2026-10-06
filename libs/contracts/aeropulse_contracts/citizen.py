"""Citizen report contract (LLD section 23). Corroborative only."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CV_CLASSES = ("smoke", "fire", "dust", "haze", "clear", "unknown")


class CitizenReport(BaseModel):
    """Citizen observation. Never opens a HIGH event by itself."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["citizen_report.v1"] = "citizen_report.v1"
    report_id: str
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    observed_at: datetime
    observation_type: str = "unknown"
    notes: str | None = None
    media_uri: str | None = None
    cv_class: Literal["smoke", "fire", "dust", "haze", "clear", "unknown"] = "unknown"
    moderation: Literal["pending", "accepted", "rejected"] = "pending"
    grid_id: str | None = None
    correlated_event_id: str | None = None
