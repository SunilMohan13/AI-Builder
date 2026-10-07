"""Serving snapshot contract (region_snapshot.v1, LLD APAC 6.3).

The cycle job precomputes everything the map needs for one region and the
API serves it from memory. ``mode`` is never ``demo``: Demo data lives only
in the web bundle, so Live can never paint it.

One addition over the LLD listing: ``events`` carries the deterministic
pollution events so the existing events endpoints can be served from the
snapshot instead of a database.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from aeropulse_contracts.event import PollutionEvent
from aeropulse_contracts.graph import IncidentSummary
from aeropulse_contracts.likelihood import SourceLikelihoodV2
from aeropulse_contracts.plume import PlumeSummary
from aeropulse_contracts.provenance import FieldStatus, ProvenanceClass
from aeropulse_contracts.source_health import SourceHealth

SNAPSHOT_SCHEMA_VERSION = "region_snapshot.v1"


class AqiBandRef(BaseModel):
    """The band a value falls in, in the region's own standard."""

    model_config = {"extra": "forbid"}

    standard: str
    key: str
    label: str
    colour: str | None = None


class CellState(BaseModel):
    """Served PM2.5 for one display cell."""

    model_config = {"extra": "forbid"}

    grid_id: str
    lat: float
    lon: float
    pm25: float | None
    pm25_source_id: str | None = None
    provenance_class: ProvenanceClass | None = None
    observed_at: datetime | None = None
    aqi_band: AqiBandRef | None = None
    field_status: list[FieldStatus] = Field(default_factory=list)


class FireCluster(BaseModel):
    """FIRMS detections grouped by coarse H3 parent and time window."""

    model_config = {"extra": "forbid"}

    cluster_id: str
    lat: float
    lon: float
    detection_count: int = Field(..., ge=1)
    frp_total: float = Field(..., ge=0.0)
    first_seen: datetime
    last_seen: datetime
    parent_cell: str
    source_ids: list[str] = Field(default_factory=list)
    provenance_class: Literal["measured"] = "measured"


class WindVector(BaseModel):
    """Wind at one site: observed (``issued_at`` is ``None``) or forecast."""

    model_config = {"extra": "forbid"}

    site_id: str
    lat: float
    lon: float
    valid_at: datetime
    issued_at: datetime | None = None
    u: float
    v: float
    level: Literal["10m", "100m"] = "10m"
    provenance_class: ProvenanceClass = ProvenanceClass.MODEL_DERIVED


class CellForecast(BaseModel):
    """PM2.5 quantiles at one horizon for one cell with a station."""

    model_config = {"extra": "forbid"}

    grid_id: str
    horizon_hours: int
    valid_at: datetime
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None
    model_version: str
    feature_version: str | None = None
    degraded: bool
    degraded_reason: str | None = None
    provenance_class: ProvenanceClass = ProvenanceClass.PREDICTED


class HazardState(BaseModel):
    """24 h hazard for one cell: a probability only when ``calibrated``."""

    model_config = {"extra": "forbid"}

    grid_id: str
    score: float = Field(..., ge=0.0, le=1.0)
    calibrated: bool
    threshold_ugm3: float | None
    horizon_hours: int = 24
    model_version: str
    feature_version: str | None = None
    degraded: bool
    degraded_reason: str | None = None
    provenance_class: ProvenanceClass = ProvenanceClass.PREDICTED


class AnomalyFlag(BaseModel):
    """Observed PM2.5 outside its expected range."""

    model_config = {"extra": "forbid"}

    grid_id: str
    observed_at: datetime
    observed_pm25: float
    expected_low: float | None = None
    expected_high: float | None = None
    score: float = Field(..., ge=0.0, le=1.0)
    reason: str
    method_version: str
    degraded: bool = False
    degraded_reason: str | None = None
    provenance_class: ProvenanceClass = ProvenanceClass.PREDICTED


class CitizenWatchSummary(BaseModel):
    """Public view of a corroborated citizen observation (rounded location)."""

    model_config = {"extra": "forbid"}

    report_id: str
    lat_rounded: float
    lon_rounded: float
    visual_class: str
    corroboration: Literal["corroborated", "partial", "uncorroborated"]
    plume_id: str | None = None
    matched_fire_id: str | None = None
    observed_at: datetime | None = None
    #: ``citizen`` when an operator set the class instead of the AI observer.
    provenance_class: Literal["ai_observation", "citizen"] = "ai_observation"


class ServedModel(BaseModel):
    """Which model or rule answered a family in this region, and why."""

    model_config = {"extra": "forbid"}

    family: str
    model_version: str
    feature_version: str | None = None
    degraded: bool
    degraded_reason: str | None = None
    calibrated: bool = False


class RegionSnapshot(BaseModel):
    """Everything the map needs for one region at one cycle time."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["region_snapshot.v1"] = "region_snapshot.v1"
    region_id: str
    cycle_time: datetime
    cycle_id: str
    pack_version: str
    mode: Literal["live", "backfill"]
    generated_at: datetime
    cells: list[CellState] = Field(default_factory=list)
    fires: list[FireCluster] = Field(default_factory=list)
    wind: list[WindVector] = Field(default_factory=list)
    forecasts: list[CellForecast] = Field(default_factory=list)
    hazard: list[HazardState] = Field(default_factory=list)
    anomalies: list[AnomalyFlag] = Field(default_factory=list)
    source_likelihood: list[SourceLikelihoodV2] = Field(default_factory=list)
    plumes: list[PlumeSummary] = Field(default_factory=list)
    incidents: list[IncidentSummary] = Field(default_factory=list)
    citizen_watches: list[CitizenWatchSummary] = Field(default_factory=list)
    events: list[PollutionEvent] = Field(default_factory=list)
    source_health: list[SourceHealth] = Field(default_factory=list)
    served_models: list[ServedModel] = Field(default_factory=list)
    field_status: list[FieldStatus] = Field(default_factory=list)
