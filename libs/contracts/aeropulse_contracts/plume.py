"""Plume contract (plume.v1) for the Lagrangian ensemble (LLD APAC 8.5).

A plume answers *where* smoke is likely to travel (forward) or where air came
from (backward). Probabilities are footprint probabilities, not
concentration forecasts, and every plume is ``simulated`` and experimental
until its evaluation exists.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

PLUME_SCHEMA_VERSION = "plume.v1"

PlumeDirection = Literal["forward", "backward"]
PlumeOriginKind = Literal["fire_cluster", "event", "anomaly", "citizen_report", "operator"]


class PlumeOrigin(BaseModel):
    """Where a run starts."""

    model_config = {"extra": "forbid"}

    kind: PlumeOriginKind
    ref_id: str | None = None
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    initial_spread_km: float = Field(default=0.0, ge=0.0)


class PlumeHorizon(BaseModel):
    """Footprint at one horizon: H3 cells holding the P50 and P90 particle mass."""

    model_config = {"extra": "forbid"}

    horizon_hours: float
    p50_cells: list[str]
    p90_cells: list[str]
    centroid_lat: float | None = None
    centroid_lon: float | None = None
    #: Share of the initial particle weight still airborne (wet removal).
    weight_remaining: float = Field(..., ge=0.0, le=1.0)


class PlaceArrival(BaseModel):
    """A gazetteer place the ensemble reaches."""

    model_config = {"extra": "forbid"}

    place_id: str
    name: str
    lat: float
    lon: float
    probability: float = Field(..., ge=0.0, le=1.0)
    eta_hours_median: float | None = None
    population: float | None = None


class HorizonExposure(BaseModel):
    """Estimated population potentially exposed (simulated) at one horizon."""

    model_config = {"extra": "forbid"}

    horizon_hours: float
    population_p90: float | None
    population_source: str | None = None
    population_year: int | None = None


class SourceCandidate(BaseModel):
    """A fire cluster lying inside a backward footprint ("likely source region")."""

    model_config = {"extra": "forbid"}

    fire_cluster_id: str
    particle_fraction: float = Field(..., ge=0.0, le=1.0)
    distance_km: float
    bearing_deg: float
    frp_total: float | None = None


class Plume(BaseModel):
    """One ensemble run, forward or backward."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["plume.v1"] = "plume.v1"
    plume_id: str
    region_id: str
    cycle_time: datetime
    model_version: str
    direction: PlumeDirection
    origin: PlumeOrigin
    release_time: datetime
    wind_issued_at: datetime | None = None
    horizons: list[PlumeHorizon]
    arrivals: list[PlaceArrival] = Field(default_factory=list)
    exposure: list[HorizonExposure] = Field(default_factory=list)
    source_candidates: list[SourceCandidate] = Field(default_factory=list)
    settings: dict[str, float | int | str] = Field(default_factory=dict)
    provenance_class: Literal["simulated"] = "simulated"
    experimental: bool = True
    degraded: bool = False
    degraded_reasons: list[str] = Field(default_factory=list)


class PlumeSummary(BaseModel):
    """What the snapshot carries; the full plume is stored by id."""

    model_config = {"extra": "forbid"}

    plume_id: str
    direction: PlumeDirection
    origin: PlumeOrigin
    model_version: str
    max_horizon_hours: float
    p90_cells_at_max: list[str]
    arrival_place_ids: list[str] = Field(default_factory=list)
    max_population_p90: float | None = None
    provenance_class: Literal["simulated"] = "simulated"
    experimental: bool = True
    degraded: bool = False
    degraded_reasons: list[str] = Field(default_factory=list)

    @classmethod
    def from_plume(cls, plume: Plume) -> PlumeSummary:
        """Summarise a full plume for the snapshot."""
        last = max(plume.horizons, key=lambda h: h.horizon_hours) if plume.horizons else None
        populations = [e.population_p90 for e in plume.exposure if e.population_p90 is not None]
        return cls(
            plume_id=plume.plume_id,
            direction=plume.direction,
            origin=plume.origin,
            model_version=plume.model_version,
            max_horizon_hours=last.horizon_hours if last else 0.0,
            p90_cells_at_max=last.p90_cells if last else [],
            arrival_place_ids=[a.place_id for a in plume.arrivals],
            max_population_p90=max(populations) if populations else None,
            experimental=plume.experimental,
            degraded=plume.degraded,
            degraded_reasons=list(plume.degraded_reasons),
        )
