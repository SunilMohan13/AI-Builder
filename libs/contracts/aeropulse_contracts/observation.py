"""Canonical air-quality observation contract (observation.v1)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from aeropulse_contracts.provenance import ProvenanceClass


class Location(BaseModel):
    """WGS84 point location."""

    model_config = {"extra": "forbid"}

    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class Measurement(BaseModel):
    """A single measured parameter."""

    model_config = {"extra": "forbid"}

    parameter: str
    value: float
    unit: str


class Quality(BaseModel):
    """Quality assessment attached to an observation."""

    model_config = {"extra": "forbid"}

    quality_flag: Literal["valid", "suspect", "invalid", "missing"] = "valid"
    quality_score: float = Field(..., ge=0.0, le=1.0)


class Provenance(BaseModel):
    """Lineage of an observation back to the connector and raw object.

    ``provenance_class`` is ``None`` only on records produced before the
    region-pack ingest path assigned it; the shared ingest pipeline fills it
    from the pack (``ground_truth_sources`` vs ``model_derived_sources``) and
    never defaults an unknown source to ``measured``.
    """

    model_config = {"extra": "forbid"}

    provider: str
    connector_version: str
    raw_object_uri: str | None = None
    provenance_class: ProvenanceClass | None = None


class PointObservationBase(BaseModel):
    """Identity, time, location, quality and lineage shared by point observations."""

    model_config = {"extra": "forbid"}

    observation_id: str
    source_id: str
    source_record_id: str
    observed_at: datetime
    received_at: datetime
    location: Location
    quality: Quality
    provenance: Provenance
    region_id: str | None = None
    grid_id: str | None = None
    dedup_key: str | None = None


class Observation(PointObservationBase):
    """Canonical observation independent of the originating source payload."""

    schema_version: Literal["observation.v1"] = "observation.v1"
    measurement: Measurement
