"""Canonical fire observation contract (fire_observation.v1)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from aeropulse_contracts.observation import Location, Provenance, Quality


class FireProperties(BaseModel):
    """Active-fire attributes from FIRMS or equivalent."""

    model_config = {"extra": "forbid"}

    frp: float = Field(..., ge=0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    sensor: str


class FireObservation(BaseModel):
    """Canonical fire detection independent of FIRMS payload shape."""

    model_config = {"extra": "forbid"}

    observation_id: str
    source_id: str
    source_record_id: str
    schema_version: Literal["fire_observation.v1"] = "fire_observation.v1"
    observed_at: datetime
    received_at: datetime
    location: Location
    fire: FireProperties
    quality: Quality
    provenance: Provenance
    grid_id: str | None = None
    dedup_key: str | None = None
