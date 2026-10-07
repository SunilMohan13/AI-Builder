"""Citizen report contracts.

``citizen_report.v1`` is the original corroborative-only report used by the
legacy API. ``citizen_report.v2`` is the document stored per report by the
citizen analyzer (LLD APAC 9): sanitised media, geo-trust, an AI visual
observation that is labelled as such, and a deterministic corroboration
table. A citizen report never creates or changes a pollution event.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from aeropulse_contracts.provenance import FieldStatus

CV_CLASSES = ("smoke", "fire", "dust", "haze", "clear", "unknown")


class CitizenReport(BaseModel):
    """Citizen observation. Never opens a HIGH event by itself."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["citizen_report.v1"] = "citizen_report.v1"
    report_id: str
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    observed_at: datetime
    observation_type: str = "unknown"
    notes: str | None = None
    media_uri: str | None = None
    cv_class: Literal["smoke", "fire", "dust", "haze", "clear", "unknown"] = "unknown"
    moderation: Literal["pending", "accepted", "rejected"] = "pending"
    grid_id: str | None = None
    correlated_event_id: str | None = None


VisualClass = Literal[
    "smoke_plume", "haze", "flames", "dust", "fog_or_cloud", "steam", "clear", "other", "unclear"
]
SMOKE_LIKE_CLASSES: frozenset[str] = frozenset({"smoke_plume", "flames", "haze", "dust"})


class VisualObservation(BaseModel):
    """Schema-constrained AI visual observation. Contains no figures.

    ``visual_certainty`` is the model's own categorical judgement; it is not
    calibrated and is never shown as a percentage.
    """

    model_config = {"extra": "forbid"}

    schema_version: Literal["visual_observation.v1"] = "visual_observation.v1"
    visual_class: VisualClass
    visual_certainty: Literal["low", "medium", "high"]
    smoke_colour: Literal["white", "grey", "black", "brown", "mixed", "not_applicable"] | None = (
        None
    )
    smoke_density: Literal["light", "moderate", "dense", "not_applicable"] | None = None
    likely_source_type: Literal[
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
    apparent_drift_in_image: (
        Literal["left", "right", "toward_camera", "away_from_camera", "vertical", "unclear"] | None
    ) = None
    possible_confusers: list[Literal["fog", "cloud", "steam", "dust", "sunset", "none"]] = Field(
        default_factory=list
    )
    image_quality: Literal["good", "fair", "poor"]
    scene_summary: str = Field(..., max_length=280)
    observer_version: str
    provenance_class: Literal["ai_observation"] = "ai_observation"


class GeoTrust(BaseModel):
    """Deterministic trust in where and when a photo was taken."""

    model_config = {"extra": "forbid"}

    level: Literal["trusted", "usable", "untrusted"]
    score: float = Field(..., ge=0.0, le=1.0)
    components: dict[str, float]
    region_id: str | None = None
    observed_at: datetime | None = None
    observed_at_status: FieldStatus | None = None


class CorroborationSignal(BaseModel):
    """One environmental signal checked against an observation."""

    model_config = {"extra": "forbid"}

    signal: str
    supports: bool | None
    weight: float
    source_id: str | None = None
    observed_at: datetime | None = None
    value: float | str | None = None
    detail: str | None = None


class Corroboration(BaseModel):
    """Heuristic corroboration result with the full signal table."""

    model_config = {"extra": "forbid"}

    level: Literal["corroborated", "partial", "uncorroborated"]
    score: float = Field(..., ge=0.0)
    method_version: str
    signals: list[CorroborationSignal]
    matched_fire_id: str | None = None
    provenance_class: Literal["heuristic"] = "heuristic"


CitizenDecision = Literal[
    "seed_plume", "operator_queue", "stored_operators_only", "no_smoke_observed"
]


class CitizenAnalysis(BaseModel):
    """Everything the analyzer concluded, stage by stage."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["citizen_analysis.v1"] = "citizen_analysis.v1"
    sha256: str | None = None
    geo_trust: GeoTrust | None = None
    observation: VisualObservation | None = None
    corroboration: Corroboration | None = None
    decision: CitizenDecision | None = None
    plume_id: str | None = None
    incident_id: str | None = None
    degraded_reasons: list[str] = Field(default_factory=list)
    analyzed_at: datetime | None = None


class CitizenReportDocument(BaseModel):
    """System-of-record document for one report (``reports/{report_id}.json``)."""

    model_config = {"extra": "forbid"}

    schema_version: Literal["citizen_report.v2"] = "citizen_report.v2"
    report_id: str
    region_id: str
    reporter_hash: str
    claimed_lat: float = Field(..., ge=-90, le=90)
    claimed_lon: float = Field(..., ge=-180, le=180)
    device_accuracy_m: float | None = Field(default=None, ge=0.0)
    client_captured_at: datetime | None = None
    observation_type: str = "unknown"
    notes: str | None = Field(default=None, max_length=1000)
    created_at: datetime
    status: Literal["awaiting_media", "queued", "analyzed", "moderated"] = "awaiting_media"
    incoming_key: str | None = None
    sanitized_key: str | None = None
    analysis: CitizenAnalysis | None = None
    moderation: Literal["pending", "accepted", "rejected"] = "pending"
    moderated_class: VisualClass | None = None
