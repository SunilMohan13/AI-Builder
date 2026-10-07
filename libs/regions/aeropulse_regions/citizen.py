"""``config/citizen.yaml``: Citizen Smoke Intelligence settings (LLD APAC 9).

Every radius, window, weight and threshold is a setting to tune against the
evaluation set, not a measured value. Loading fails closed: a missing or
malformed file is an error, never a silent default.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from aeropulse_common.errors import RegionPackError
from pydantic import BaseModel, Field, ValidationError, model_validator

CITIZEN_FILE = "citizen.yaml"

GeoComponent = Literal[
    "in_region", "exif_claim_distance", "device_accuracy", "time_consistency", "not_duplicate"
]
Signal = Literal[
    "fire_nearby",
    "fire_on_bearing",
    "fire_upwind",
    "on_plume_path",
    "pm25_elevated",
    "aerosol_index_elevated",
    "active_event",
]
SIGNALS: tuple[Signal, ...] = (
    "fire_nearby",
    "fire_on_bearing",
    "fire_upwind",
    "on_plume_path",
    "pm25_elevated",
    "aerosol_index_elevated",
    "active_event",
)


class _Strict(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}


class UploadSettings(_Strict):
    max_bytes: int = Field(..., gt=0)
    max_pixels: int = Field(..., gt=0)
    allowed_mime: tuple[str, ...]
    signed_url_ttl_seconds: int = Field(..., gt=0)


class RateLimits(_Strict):
    per_reporter_per_hour: int = Field(..., gt=0)
    per_ip_per_hour: int = Field(..., gt=0)


class GeoTrustSettings(_Strict):
    weights: dict[GeoComponent, float]
    exif_claim_max_km: float = Field(..., gt=0)
    exif_absent_score: float = Field(..., ge=0, le=1)
    device_accuracy_good_m: float = Field(..., gt=0)
    device_accuracy_bad_m: float = Field(..., gt=0)
    max_capture_age_hours: float = Field(..., gt=0)
    trusted_min: float = Field(..., ge=0, le=1)
    usable_min: float = Field(..., ge=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> GeoTrustSettings:
        if self.usable_min > self.trusted_min:
            raise ValueError("geo_trust.usable_min must not exceed trusted_min")
        if self.device_accuracy_good_m >= self.device_accuracy_bad_m:
            raise ValueError("device_accuracy_good_m must be below device_accuracy_bad_m")
        return self


class CorroborationSettings(_Strict):
    method_version: str
    fire_radius_km: float = Field(..., gt=0)
    fire_window_hours: float = Field(..., gt=0)
    #: Half-width of the cone either side of the camera bearing.
    bearing_cone_deg: float = Field(..., gt=0, le=90)
    bearing_max_km: float = Field(..., gt=0)
    #: Half-width of the cone either side of the direction the wind blows from.
    upwind_cone_deg: float = Field(..., gt=0, le=90)
    station_radius_km: float = Field(..., gt=0)
    pm25_rise_window_hours: float = Field(..., gt=0)
    corroborated_min: float = Field(..., ge=0)
    partial_min: float = Field(..., ge=0)
    weights: dict[str, dict[Signal, float]]

    @model_validator(mode="after")
    def _ordered(self) -> CorroborationSettings:
        if self.partial_min > self.corroborated_min:
            raise ValueError("corroboration.partial_min must not exceed corroborated_min")
        for visual_class, weights in self.weights.items():
            missing = set(SIGNALS) - set(weights)
            if missing:
                raise ValueError(f"weights.{visual_class} misses {sorted(missing)}")
        return self

    def weights_for(self, visual_class: str) -> dict[str, float]:
        """Weights for a smoke-like class; other classes are never corroborated."""
        return {str(k): v for k, v in self.weights.get(visual_class, {}).items()}


class DecisionSettings(_Strict):
    watch_reach_hours: float = Field(..., gt=0)
    reporter_origin_spread_km: float = Field(..., ge=0)
    public_round_decimals: int = Field(..., ge=0, le=4)
    #: How long a seeded report keeps seeding a plume in later cycles.
    seed_window_hours: float = Field(..., gt=0)
    max_plumes_per_cycle: int = Field(..., ge=0)


class CitizenSettings(_Strict):
    schema_version: Literal["citizen.v1"]
    upload: UploadSettings
    rate_limits: RateLimits
    geo_trust: GeoTrustSettings
    corroboration: CorroborationSettings
    decision: DecisionSettings


def load_citizen_settings(config_dir: Path) -> CitizenSettings:
    path = config_dir / CITIZEN_FILE
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RegionPackError(f"cannot read {path}: {exc}") from exc
    try:
        return CitizenSettings.model_validate(raw)
    except ValidationError as exc:
        raise RegionPackError(f"{path}: {exc}") from exc
