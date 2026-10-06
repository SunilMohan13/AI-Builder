"""Pydantic models for region packs. Unknown fields are rejected."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

_SECRET_VALUE_MARKERS = ("sk-", "bearer ", "api_key=", "key=")


class BBox(BaseModel):
    """min_lon, min_lat, max_lon, max_lat."""

    model_config = {"extra": "forbid"}

    bbox: tuple[float, float, float, float]

    @model_validator(mode="after")
    def ordered(self) -> Self:
        min_lon, min_lat, max_lon, max_lat = self.bbox
        if min_lon >= max_lon or min_lat >= max_lat:
            raise ValueError("bbox min corner must be less than max corner")
        if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
            raise ValueError("longitude out of range")
        if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
            raise ValueError("latitude out of range")
        return self

    def contains(self, other: BBox) -> bool:
        min_lon, min_lat, max_lon, max_lat = self.bbox
        inner_min_lon, inner_min_lat, inner_max_lon, inner_max_lat = other.bbox
        return (
            min_lon <= inner_min_lon
            and min_lat <= inner_min_lat
            and max_lon >= inner_max_lon
            and max_lat >= inner_max_lat
        )


class RegionSource(BaseModel):
    """One connector enabled for a pack. secret_ref is a name, never a value."""

    model_config = {"extra": "forbid"}

    id: str
    enabled: bool = True
    params: dict[str, object] = Field(default_factory=dict)
    secret_ref: str | None = None
    interval_seconds: int | None = Field(default=None, ge=60)

    @model_validator(mode="after")
    def secret_ref_is_a_name(self) -> Self:
        if self.secret_ref is None:
            return self
        ref = self.secret_ref.strip()
        lowered = ref.lower()
        if (
            not ref
            or any(char.isspace() for char in ref)
            or "=" in ref
            or any(marker in lowered for marker in _SECRET_VALUE_MARKERS)
            or (len(ref) > 40 and "/" not in ref)
        ):
            raise ValueError("secret_ref must be a name, not a secret value")
        return self


class SourceDomain(BaseModel):
    """Area where fires and wind are watched. May be larger than the display area."""

    model_config = {"extra": "forbid"}

    bbox: tuple[float, float, float, float]
    wind_site_resolution: int = Field(default=4, ge=0, le=8)
    max_wind_sites: int = Field(default=60, ge=1)

    def as_bbox(self) -> BBox:
        return BBox(bbox=self.bbox)


class RegionPack(BaseModel):
    """Geography, standards, and sources for one region. No application code changes."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["region.v1"] = "region.v1"
    region_id: str
    display_name: str
    country_codes: list[str]
    timezone: str
    h3_resolution: Literal[8] = 8
    aqi_standard: str
    geometry: BBox
    source_domain: SourceDomain
    map_view: dict[str, float]
    hazards: list[str]
    sources: list[RegionSource]
    model_derived_sources: list[str]
    ground_truth_sources: list[str]
    gazetteer: dict[str, object] = Field(default_factory=dict)
    population: dict[str, object] = Field(default_factory=dict)
    demo: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def domain_contains_display_and_sources_do_not_overlap(self) -> Self:
        if not self.source_domain.as_bbox().contains(self.geometry):
            raise ValueError("source_domain.bbox must contain geometry.bbox")
        overlap = set(self.ground_truth_sources) & set(self.model_derived_sources)
        if overlap:
            names = ", ".join(sorted(overlap))
            raise ValueError(f"source cannot be both ground truth and model-derived: {names}")
        return self


class HazardProfile(BaseModel):
    """Configuration that tells the shared engine what to look for."""

    model_config = {"extra": "forbid"}

    key: str
    display_name: str
    source_class: str
    seasonal_prior: dict[str, object] = Field(default_factory=dict)
    signals: list[str] = Field(default_factory=list)
    plume_defaults: dict[str, object] = Field(default_factory=dict)
    copy_text: dict[str, str] = Field(default_factory=dict, validation_alias="copy")


class AqiBand(BaseModel):
    """One official band. Copied from the publication, not typed from memory."""

    model_config = {"extra": "forbid"}

    low: float
    high: float | None = None
    label: str


class AqiStandard(BaseModel):
    """Official air-quality scale for one region. Unconfirmed standards do not label."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["aqi_standard.v1"] = "aqi_standard.v1"
    key: str
    display_name: str
    confirmed: bool
    source_url: str | None = None
    averaging: str | None = None
    hazard_label: str | None = None
    hazard_threshold_ugm3: float | None = None
    bands: list[AqiBand] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def confirmed_standards_have_bands(self) -> Self:
        if self.confirmed and not self.bands:
            raise ValueError("a confirmed AQI standard must include its official bands")
        if not self.confirmed and self.bands:
            raise ValueError("an unconfirmed AQI standard must not invent bands")
        return self
