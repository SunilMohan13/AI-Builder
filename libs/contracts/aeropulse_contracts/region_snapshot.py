"""Precomputed map payload for one region cycle (region_snapshot.v1).

Demo data is never a snapshot. A missing value is null plus a field status,
not a substituted number.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from aeropulse_contracts.citizen_analysis import CitizenAnalysis
from aeropulse_contracts.graph import IncidentSummary
from aeropulse_contracts.hazard import HazardCell
from aeropulse_contracts.observation import ProvenanceClass
from aeropulse_contracts.plume import Plume
from aeropulse_contracts.prediction import AnomalyResult
from aeropulse_contracts.source_likelihood import SourceLikelihoodV2


class FieldStatus(BaseModel):
    """Why a served field is null."""

    model_config = {"extra": "forbid"}

    field: str
    reason: str


class CellState(BaseModel):
    """Served PM2.5 for one display cell."""

    model_config = {"extra": "forbid"}

    grid_id: str
    pm25: float | None = None
    provenance_class: ProvenanceClass
    aqi_band: str | None = None
    aqi_standard: str | None = None
    field_status: list[FieldStatus] = Field(default_factory=list)


class FireCluster(BaseModel):
    """FIRMS hotspots grouped for one plume origin."""

    model_config = {"extra": "forbid"}

    cluster_id: str
    grid_id: str
    lat: float
    lon: float
    count: int = Field(..., ge=0)
    frp: float = Field(..., ge=0.0)
    observed_at: datetime
    provenance_class: Literal[ProvenanceClass.MEASURED] = ProvenanceClass.MEASURED


class WindVector(BaseModel):
    """Observed or forecast wind at one site."""

    model_config = {"extra": "forbid"}

    grid_id: str
    valid_at: datetime
    issued_at: datetime
    wind_u: float | None = None
    wind_v: float | None = None
    provenance_class: ProvenanceClass
    field_status: list[FieldStatus] = Field(default_factory=list)


class CellForecast(BaseModel):
    """Quantile PM2.5 forecast for one cell. Degraded when a rule answered."""

    model_config = {"extra": "forbid"}

    grid_id: str
    valid_at: datetime
    horizon_hours: int = Field(..., ge=1)
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None
    model_version: str
    degraded: bool = True
    degraded_reason: str | None = None
    provenance_class: Literal[ProvenanceClass.PREDICTED] = ProvenanceClass.PREDICTED


class PlumeSummary(BaseModel):
    """Snapshot pointer to a full plume.v1 object."""

    model_config = {"extra": "forbid"}

    plume_id: str
    direction: Literal["forward", "backward"]
    origin_grid_id: str
    model_version: str
    experimental: bool = True
    degraded: bool = False
    degraded_reason: str | None = None


class CitizenWatchSummary(BaseModel):
    """Public view of a corroborated report. No photo, no raw reporter id."""

    model_config = {"extra": "forbid"}

    report_id: str
    grid_id: str
    visual_class: str | None = None
    corroboration: str
    provenance_class: Literal[ProvenanceClass.AI_OBSERVATION] = ProvenanceClass.AI_OBSERVATION


class SourceHealth(BaseModel):
    """Freshness or an explicit not-configured state."""

    model_config = {"extra": "forbid"}

    source_id: str
    status: Literal["ok", "stale", "not_configured", "error"]
    reason: str | None = None
    observed_at: datetime | None = None


class ServedModel(BaseModel):
    """What answered one family in this snapshot."""

    model_config = {"extra": "forbid"}

    family: str
    model_version: str
    degraded: bool
    degraded_reason: str | None = None
    calibrated: bool = False


class RegionSnapshot(BaseModel):
    """Everything the map needs for one region at one cycle."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["region_snapshot.v1"] = "region_snapshot.v1"
    region_id: str
    cycle_time: datetime
    pack_version: str
    mode: Literal["live", "backfill"]
    cells: list[CellState] = Field(default_factory=list)
    fires: list[FireCluster] = Field(default_factory=list)
    wind: list[WindVector] = Field(default_factory=list)
    forecasts: list[CellForecast] = Field(default_factory=list)
    hazard: list[HazardCell] = Field(default_factory=list)
    anomalies: list[AnomalyResult] = Field(default_factory=list)
    source_likelihood: list[SourceLikelihoodV2] = Field(default_factory=list)
    plumes: list[PlumeSummary] = Field(default_factory=list)
    incidents: list[IncidentSummary] = Field(default_factory=list)
    citizen_watches: list[CitizenWatchSummary] = Field(default_factory=list)
    citizen_analyses: list[CitizenAnalysis] = Field(default_factory=list)
    source_health: list[SourceHealth] = Field(default_factory=list)
    served_models: list[ServedModel] = Field(default_factory=list)
    plume_ids: list[str] = Field(default_factory=list)


def plume_summary(plume: Plume) -> PlumeSummary:
    """Project a full plume onto the snapshot pointer."""
    return PlumeSummary(
        plume_id=plume.plume_id,
        direction=plume.direction,
        origin_grid_id=plume.origin_grid_id,
        model_version=plume.model_version,
        experimental=plume.experimental,
        degraded=plume.degraded,
        degraded_reason=plume.degraded_reason,
    )
