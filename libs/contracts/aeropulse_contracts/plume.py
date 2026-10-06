"""Particle-ensemble plume contract (plume.v1).

This answers where smoke may travel, not how much. Concentration stays with
the forecast model. Until evaluation exists the consumer must keep the
experimental label.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from aeropulse_contracts.observation import ProvenanceClass

PLUME_VERSION = "lagrangian-ens-1.0"


class HorizonExposure(BaseModel):
    """Population inside the P90 footprint at one horizon."""

    model_config = {"extra": "forbid"}

    horizon_hours: int = Field(..., ge=0)
    population_p90: float = Field(..., ge=0.0)
    population_source: str
    population_year: int | None = None


class SourceCandidate(BaseModel):
    """A fire cluster on a backward trajectory. Association, not causation."""

    model_config = {"extra": "forbid"}

    fire_cluster_id: str
    particle_fraction: float = Field(..., ge=0.0, le=1.0)
    distance_km: float = Field(..., ge=0.0)
    bearing_deg: float = Field(..., ge=0.0, lt=360.0)


class Plume(BaseModel):
    """Forward or backward smoke-transport result."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["plume.v1"] = "plume.v1"
    plume_id: str
    region_id: str
    model_version: str = PLUME_VERSION
    direction: Literal["forward", "backward"]
    origin_grid_id: str
    origin_lat: float = Field(..., ge=-90, le=90)
    origin_lon: float = Field(..., ge=-180, le=180)
    generated_at: datetime
    horizons_hours: list[int] = Field(default_factory=list)
    exposure: list[HorizonExposure] = Field(default_factory=list)
    source_candidates: list[SourceCandidate] = Field(default_factory=list)
    provenance_class: Literal[ProvenanceClass.SIMULATED] = ProvenanceClass.SIMULATED
    degraded: bool = False
    degraded_reason: str | None = None
    experimental: bool = True
