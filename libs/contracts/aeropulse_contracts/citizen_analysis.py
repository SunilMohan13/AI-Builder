"""Citizen visual observation and analysis contracts.

Gemini may describe a photo. It may not put a concentration, distance, or
count into AeroPulse. Corroboration, not the model, decides what happens next.
"""

import re
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from aeropulse_contracts.observation import ProvenanceClass

_NUMERIC_CLAIM = re.compile(
    r"\d+(?:\.\d+)?\s*(?:µg|μg|ug(?:/m3)?|aqi|ppm|km|%)",
    re.IGNORECASE,
)

VisualClass = Literal[
    "smoke_plume",
    "haze",
    "flames",
    "dust",
    "fog_or_cloud",
    "steam",
    "clear",
    "other",
    "unclear",
]
VisualCertainty = Literal["low", "medium", "high"]
SmokeColour = Literal["white", "grey", "black", "brown", "mixed", "not_applicable"]
SmokeDensity = Literal["light", "moderate", "dense", "not_applicable"]
LikelySourceType = Literal[
    "agricultural_field",
    "vegetation_or_forest",
    "peat",
    "waste_burning",
    "industrial_stack",
    "vehicle",
    "building_fire",
    "dust_storm",
    "regional_haze",
    "unknown",
]
ApparentDrift = Literal[
    "left",
    "right",
    "toward_camera",
    "away_from_camera",
    "vertical",
    "unclear",
]
PossibleConfuser = Literal["fog", "cloud", "steam", "dust", "sunset", "none"]
ImageQuality = Literal["good", "fair", "poor"]
GeoTrust = Literal["trusted", "usable", "untrusted"]
CorroborationLevel = Literal["corroborated", "partial", "uncorroborated"]


def contains_numeric_claim(text: str) -> bool:
    """Return True when prose states a measurement AeroPulse must not accept."""
    return _NUMERIC_CLAIM.search(text) is not None


class VisualObservation(BaseModel):
    """Schema-constrained AI description of one photo. No figures."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["visual_observation.v1"] = "visual_observation.v1"
    visual_class: VisualClass
    visual_certainty: VisualCertainty
    smoke_colour: SmokeColour = "not_applicable"
    smoke_density: SmokeDensity = "not_applicable"
    likely_source_type: LikelySourceType
    apparent_drift_in_image: ApparentDrift = "unclear"
    possible_confusers: list[PossibleConfuser] = Field(default_factory=list)
    image_quality: ImageQuality
    scene_summary: str = Field(..., max_length=280)
    provenance_class: Literal[ProvenanceClass.AI_OBSERVATION] = ProvenanceClass.AI_OBSERVATION
    model_name: str

    @model_validator(mode="after")
    def summary_has_no_figures(self) -> Self:
        """Reject a summary that smuggles a concentration, distance, or count."""
        if contains_numeric_claim(self.scene_summary):
            raise ValueError("scene_summary must not contain a numeric claim")
        return self


class CorroborationSignal(BaseModel):
    """One deterministic environmental check of a visual observation."""

    model_config = {"extra": "forbid"}

    name: str
    supports: bool
    source_id: str | None = None
    observed_at: datetime | None = None
    detail: str | None = None


class CitizenAnalysis(BaseModel):
    """Result of one analyzer pass. Does not create a pollution event."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["citizen_analysis.v1"] = "citizen_analysis.v1"
    report_id: str
    region_id: str | None = None
    geo_trust: GeoTrust
    observation: VisualObservation | None = None
    corroboration: CorroborationLevel
    corroboration_score: float = Field(..., ge=0.0, le=1.0)
    signals: list[CorroborationSignal] = Field(default_factory=list)
    provenance_class: Literal[ProvenanceClass.HEURISTIC] = ProvenanceClass.HEURISTIC
    plume_id: str | None = None
    degraded_reasons: list[str] = Field(default_factory=list)
    analyzed_at: datetime
