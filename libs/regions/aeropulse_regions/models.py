"""Pydantic models for Region Packs, hazard profiles, and AQI standards.

Everything region-specific lives in ``config/`` as data validated by these
models; no Python or TypeScript file names a bbox, city, or timezone. Rules
that need only one file are enforced here. Rules that cross files (a hazard
named by a pack must exist) live in :mod:`aeropulse_regions.validator`.
"""

from __future__ import annotations

import re
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: (min_lon, min_lat, max_lon, max_lat), WGS84 degrees.
BBox = tuple[float, float, float, float]

#: The only accepted shapes for a secret reference. Anything else, including
#: anything that looks like a key value, fails validation.
_SECRET_REF_PATTERNS = (
    re.compile(r"^projects/[A-Za-z0-9_<>.-]+/secrets/[A-Za-z0-9_-]+(/versions/[A-Za-z0-9]+)?$"),
    re.compile(r"^env:[A-Z][A-Z0-9_]*$"),
    re.compile(r"^AEROPULSE_[A-Z0-9_]+$"),
)

_REGION_ID = re.compile(r"^[a-z]{2}-[a-z0-9-]{2,40}$")


def _check_bbox(bbox: BBox, label: str) -> BBox:
    min_lon, min_lat, max_lon, max_lat = bbox
    if not (-180.0 <= min_lon < max_lon <= 180.0):
        raise ValueError(f"{label}: longitudes must satisfy -180 <= min < max <= 180")
    if not (-90.0 <= min_lat < max_lat <= 90.0):
        raise ValueError(f"{label}: latitudes must satisfy -90 <= min < max <= 90")
    return bbox


def bbox_contains(outer: BBox, inner: BBox) -> bool:
    """True when ``inner`` lies entirely inside ``outer``."""
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[2] >= inner[2]
        and outer[3] >= inner[3]
    )


def bbox_contains_point(bbox: BBox, lat: float, lon: float) -> bool:
    """True when the point lies inside or on the edge of ``bbox``."""
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Geometry(_Strict):
    """Display area: where H3 resolution-8 cells are materialised."""

    bbox: BBox

    @field_validator("bbox")
    @classmethod
    def _valid(cls, v: BBox) -> BBox:
        return _check_bbox(v, "geometry.bbox")


class SourceDomain(_Strict):
    """Where sources and wind are watched; may be far larger than the display."""

    bbox: BBox
    wind_site_resolution: int = Field(default=4, ge=0, le=7)
    max_wind_sites: int = Field(default=60, ge=1, le=500)

    @field_validator("bbox")
    @classmethod
    def _valid(cls, v: BBox) -> BBox:
        return _check_bbox(v, "source_domain.bbox")


class MapView(_Strict):
    lon: float = Field(..., ge=-180, le=180)
    lat: float = Field(..., ge=-90, le=90)
    zoom: float = Field(..., ge=0, le=22)


class SourceEntry(_Strict):
    """One connector enabled for a region, with its region-specific params."""

    id: str = Field(..., min_length=1)
    enabled: bool = True
    interval_seconds: int | None = Field(default=None, ge=60)
    params: dict[str, Any] = Field(default_factory=dict)
    #: Replay payload for this region, relative to the fixtures root. Absent
    #: means replay reports "not configured" rather than borrowing another
    #: region's data.
    fixture: str | None = None
    #: A *name* of a secret (Secret Manager path, ``env:NAME``, or an
    #: ``AEROPULSE_*`` settings variable). Never a value.
    secret_ref: str | None = None

    @field_validator("secret_ref")
    @classmethod
    def _reference_only(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not any(p.match(v) for p in _SECRET_REF_PATTERNS):
            raise ValueError(
                "secret_ref must be a reference (projects/<p>/secrets/<name>, env:NAME, "
                "or AEROPULSE_NAME), never a credential value"
            )
        return v

    @property
    def domain(self) -> Literal["display", "source"]:
        """Which bbox the connector should query (``params.domain``)."""
        return "source" if self.params.get("domain") == "source" else "display"


class Gazetteer(_Strict):
    source: str
    min_population: int = Field(default=10000, ge=0)


class Population(_Strict):
    source: str


class Demo(_Strict):
    enabled: bool = True


class RegionPack(_Strict):
    """``region.yaml``: everything that makes one region different."""

    schema_version: Literal["region.v1"] = "region.v1"
    region_id: str
    pack_version: str = "1"
    display_name: str
    country_codes: list[str] = Field(..., min_length=1)
    timezone: str
    #: AGENTS.md: 1 km cells. Any other value fails validation.
    h3_resolution: Literal[8] = 8
    aqi_standard: str
    geometry: Geometry
    source_domain: SourceDomain
    map_view: MapView
    hazards: list[str] = Field(..., min_length=1)
    sources: list[SourceEntry] = Field(default_factory=list)
    model_derived_sources: list[str] = Field(default_factory=list)
    ground_truth_sources: list[str] = Field(default_factory=list)
    #: ``none`` when onboarding found no reference stations: rules run marked
    #: degraded and no model can be validated in the region.
    ground_truth: Literal["stations", "none"] = "stations"
    gazetteer: Gazetteer | None = None
    population: Population | None = None
    demo: Demo = Field(default_factory=Demo)

    @field_validator("region_id")
    @classmethod
    def _region_id_shape(cls, v: str) -> str:
        if not _REGION_ID.match(v):
            raise ValueError(
                "region_id must look like '<cc>-<name>' in lowercase, e.g. sg-singapore"
            )
        return v

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown IANA timezone: {v}") from exc
        return v

    @field_validator("country_codes")
    @classmethod
    def _iso_alpha2(cls, v: list[str]) -> list[str]:
        for code in v:
            if not re.fullmatch(r"[A-Z]{2}", code):
                raise ValueError(f"country code must be ISO 3166-1 alpha-2: {code}")
        return v

    @model_validator(mode="after")
    def _cross_field_rules(self) -> RegionPack:
        if not bbox_contains(self.source_domain.bbox, self.geometry.bbox):
            raise ValueError("source_domain.bbox must contain geometry.bbox")
        if not bbox_contains_point(self.geometry.bbox, self.map_view.lat, self.map_view.lon):
            raise ValueError("map_view centre must lie inside geometry.bbox")

        ids = [s.id for s in self.sources]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate source ids: {sorted(duplicates)}")

        overlap = set(self.ground_truth_sources) & set(self.model_derived_sources)
        if overlap:
            raise ValueError(
                f"sources cannot be both ground truth and model-derived: {sorted(overlap)}"
            )
        unknown = (set(self.ground_truth_sources) | set(self.model_derived_sources)) - set(ids)
        if unknown:
            raise ValueError(
                f"truth/model-derived lists name unconfigured sources: {sorted(unknown)}"
            )

        if len(set(self.hazards)) != len(self.hazards):
            raise ValueError("hazards must not repeat")
        if self.ground_truth == "none" and self.ground_truth_sources:
            raise ValueError("ground_truth: none cannot list ground_truth_sources")
        return self

    def source(self, source_id: str) -> SourceEntry | None:
        """The pack's entry for ``source_id``, if configured."""
        return next((s for s in self.sources if s.id == source_id), None)

    def bbox_for(self, entry: SourceEntry) -> BBox:
        """The bbox a connector should query for this entry."""
        return self.source_domain.bbox if entry.domain == "source" else self.geometry.bbox

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


class SeasonalPrior(_Strict):
    months: list[int] = Field(..., min_length=1)
    feature: str

    @field_validator("months")
    @classmethod
    def _months(cls, v: list[int]) -> list[int]:
        if any(m < 1 or m > 12 for m in v):
            raise ValueError("months must be 1..12")
        return v


class PlumeDefaults(_Strict):
    release_level_weights: dict[Literal["10m", "100m"], float]
    horizons_hours: list[float] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> PlumeDefaults:
        total = sum(self.release_level_weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError("release_level_weights must sum to 1")
        if sorted(self.horizons_hours) != self.horizons_hours or self.horizons_hours[0] <= 0:
            raise ValueError("horizons_hours must be positive and ascending")
        return self


class HazardCopy(_Strict):
    explainer: str


#: Pseudo-signal: the profile's own seasonal prior, if it has one.
SEASONAL_PRIOR_SIGNAL = "seasonal_prior"


class EvidenceWeights(_Strict):
    """Source-likelihood weights (LLD APAC 7.6). Settings, never fitted.

    No gold label set exists, so these are reviewed by reading them, and the
    score they produce is a ranking, never a calibrated probability.
    """

    method_version: str = Field(..., min_length=1)
    bias: float
    weights: dict[str, float] = Field(..., min_length=1)


class HazardProfile(_Strict):
    """A configurable hazard the shared engine looks for (LLD APAC 4.3)."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_version: Literal["hazard_profile.v1"] = "hazard_profile.v1"
    key: str
    display_name: str
    source_class: str
    seasonal_prior: SeasonalPrior | None = None
    signals: list[str] = Field(default_factory=list)
    #: ``None`` means the hazard runs no plume (e.g. urban pollution).
    plume_defaults: PlumeDefaults | None = None
    #: ``None`` means the class is never scored for source likelihood.
    likelihood: EvidenceWeights | None = None
    copy_text: HazardCopy = Field(alias="copy")

    @model_validator(mode="after")
    def _weights_name_signals(self) -> HazardProfile:
        if self.likelihood is None:
            return self
        allowed = set(self.signals)
        if self.seasonal_prior is not None:
            allowed.add(SEASONAL_PRIOR_SIGNAL)
        unknown = sorted(set(self.likelihood.weights) - allowed)
        if unknown:
            raise ValueError(
                f"likelihood weights name signals this profile does not list: {unknown}"
            )
        return self


class AqiBand(_Strict):
    """Half-open band ``[low, high)``; ``high`` is ``None`` for the top band."""

    key: str
    label: str
    low: float = Field(..., ge=0.0)
    high: float | None = None
    colour: str | None = None


class AqiStandard(_Strict):
    """Bands are data copied from the official publication, never from memory.

    An ``unconfirmed`` standard ships with no bands: the UI then shows "—"
    with ``reason`` instead of borrowing another country's scale.
    """

    schema_version: Literal["aqi_standard.v1"] = "aqi_standard.v1"
    key: str
    name: str
    pollutant: Literal["pm25"] = "pm25"
    unit: Literal["ug/m3"] = "ug/m3"
    status: Literal["confirmed", "unconfirmed"]
    averaging: Literal["1h", "24h"] | None = None
    #: Fewest hourly values an average may be computed from; ``None`` means
    #: the full averaging period.
    averaging_min_hours: int | None = Field(default=None, ge=1, le=24)
    source_url: str | None = None
    reason: str | None = None
    bands: list[AqiBand] = Field(default_factory=list)
    hazard_label: str | None = None
    hazard_threshold_ugm3: float | None = None
    hazard_source: str | None = None

    @model_validator(mode="after")
    def _rules(self) -> AqiStandard:
        if self.status == "unconfirmed":
            if self.bands or self.hazard_threshold_ugm3 is not None:
                raise ValueError("an unconfirmed standard must not carry bands or a threshold")
            if not self.reason:
                raise ValueError("an unconfirmed standard must say why (reason)")
            return self
        if not self.bands or not self.source_url or self.averaging is None:
            raise ValueError("a confirmed standard needs bands, source_url, and averaging")
        for prev, nxt in zip(self.bands, self.bands[1:], strict=False):
            if prev.high is None or prev.high != nxt.low:
                raise ValueError(f"bands must be contiguous: {prev.key} -> {nxt.key}")
        if self.bands[-1].high is not None:
            raise ValueError("the top band must be open-ended (high: null)")
        if self.hazard_label is not None:
            band = next((b for b in self.bands if b.key == self.hazard_label), None)
            if band is None:
                raise ValueError(f"hazard_label {self.hazard_label} is not a band key")
            t = self.hazard_threshold_ugm3
            if t is None or t < band.low or (band.high is not None and t >= band.high):
                raise ValueError("hazard_threshold_ugm3 must fall inside the hazard_label band")
        return self

    def classify(self, value: float | None) -> AqiBand | None:
        """The band ``value`` falls in, or ``None`` when unknowable."""
        if value is None or not self.bands:
            return None
        for band in self.bands:
            if value >= band.low and (band.high is None or value < band.high):
                return band
        return None
