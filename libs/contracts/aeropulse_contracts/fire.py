"""Canonical fire observation contract (fire_observation.v1)."""

from typing import Literal

from pydantic import BaseModel, Field

from aeropulse_contracts.observation import PointObservationBase


class FireProperties(BaseModel):
    """Active-fire attributes from FIRMS or equivalent."""

    model_config = {"extra": "forbid"}

    frp: float = Field(..., ge=0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    sensor: str


class FireObservation(PointObservationBase):
    """Canonical fire detection independent of FIRMS payload shape."""

    schema_version: Literal["fire_observation.v1"] = "fire_observation.v1"
    fire: FireProperties
