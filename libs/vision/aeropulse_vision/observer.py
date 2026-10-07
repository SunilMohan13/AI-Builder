"""AI visual observation (LLD APAC 9.4): the observer contract and its validator.

An observer describes what is visible in a sanitized photo, in a fixed
categorical schema with no numeric fields. The validator also rejects a
``scene_summary`` that carries a figure (digits, number words, or units), so
a model cannot put a number into AeroPulse. A missing or failing observer
yields no observation and a reason; nothing falls back to a keyword guess.

The observation is labelled ``ai_observation`` and only acts through the
deterministic corroboration that follows it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from aeropulse_contracts.citizen import VisualObservation
from pydantic import ValidationError

from aeropulse_vision.sanitize import SanitizedImage

UNAVAILABLE = "ai_observation_unavailable"
INVALID = "ai_observation_invalid"
OBSERVATION_TYPES = frozenset({"smoke", "fire", "haze", "dust", "photo", "unknown"})

#: The LLD 9.4 response schema, passed to the model as structured output.
OBSERVATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "visual_class": {
            "type": "string",
            "enum": [
                "smoke_plume",
                "haze",
                "flames",
                "dust",
                "fog_or_cloud",
                "steam",
                "clear",
                "other",
                "unclear",
            ],
        },
        "visual_certainty": {"type": "string", "enum": ["low", "medium", "high"]},
        "smoke_colour": {
            "type": "string",
            "enum": ["white", "grey", "black", "brown", "mixed", "not_applicable"],
        },
        "smoke_density": {
            "type": "string",
            "enum": ["light", "moderate", "dense", "not_applicable"],
        },
        "likely_source_type": {
            "type": "string",
            "enum": [
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
            ],
        },
        "apparent_drift_in_image": {
            "type": "string",
            "enum": ["left", "right", "toward_camera", "away_from_camera", "vertical", "unclear"],
        },
        "possible_confusers": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["fog", "cloud", "steam", "dust", "sunset", "none"],
            },
        },
        "image_quality": {"type": "string", "enum": ["good", "fair", "poor"]},
        "scene_summary": {"type": "string", "maxLength": 280},
    },
    "required": [
        "visual_class",
        "visual_certainty",
        "likely_source_type",
        "image_quality",
        "scene_summary",
    ],
    "additionalProperties": False,
}

_NUMBER_WORDS = (
    "zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    "fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
    "sixty|seventy|eighty|ninety|hundred|hundreds|thousand|thousands|million|dozen|dozens"
)
_UNITS = r"aqi|µg|ug/m|μg|ppm|ppb|km|kilomet\w*|met(?:er|re)s?|percent|per\s*cent|mw"
_FIGURE = re.compile(rf"\d|%|\b(?:{_NUMBER_WORDS})\b|\b(?:{_UNITS})", re.IGNORECASE)


class ObservationError(ValueError):
    """A model response that does not fit the observation schema or rules."""


@dataclass(frozen=True)
class ObserverResult:
    observation: VisualObservation | None
    degraded_reasons: tuple[str, ...] = field(default_factory=tuple)


class VisualObserver(Protocol):
    @property
    def version(self) -> str: ...

    @property
    def provenance_class(self) -> Literal["ai_observation", "predicted", "citizen"]: ...

    def observe(self, image: SanitizedImage, observation_type: str) -> ObserverResult: ...


def safe_observation_type(text: str | None) -> str:
    """The citizen's observation type, limited to known words (it reaches a prompt)."""
    value = (text or "").strip().lower()
    return value if value in OBSERVATION_TYPES else "unknown"


def contains_figure(text: str) -> bool:
    return _FIGURE.search(text) is not None


def validate_observation(raw: str | dict[str, Any], *, observer_version: str) -> VisualObservation:
    """Parse and check one model response.

    Raises:
        ObservationError: not JSON, outside the schema, or a summary with a figure.
    """
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ObservationError("response is not JSON") from exc
    else:
        payload = raw
    if not isinstance(payload, dict):
        raise ObservationError("response is not an object")
    allowed = set(OBSERVATION_SCHEMA["properties"])
    unexpected = set(payload) - allowed
    if unexpected:
        raise ObservationError(f"unexpected fields: {sorted(unexpected)}")
    summary = payload.get("scene_summary")
    if isinstance(summary, str) and contains_figure(summary):
        raise ObservationError("scene_summary contains a figure")
    try:
        return VisualObservation.model_validate({**payload, "observer_version": observer_version})
    except ValidationError as exc:
        raise ObservationError(f"response violates the schema: {exc.error_count()} errors") from exc


class UnavailableObserver:
    """The observer when no vision model is configured: no observation, with the reason."""

    provenance_class: Literal["ai_observation"] = "ai_observation"

    def __init__(self, reason: str = "vision model not configured") -> None:
        self.version = "unavailable"
        self.reason = reason

    def observe(self, image: SanitizedImage, observation_type: str) -> ObserverResult:
        return ObserverResult(None, (UNAVAILABLE,))
