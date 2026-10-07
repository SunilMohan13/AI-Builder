"""Gemini as a ``VisualObserver`` (LLD APAC 9.4).

Multimodal, low temperature, no tools, structured output only. The photo and
the citizen's observation type are the whole input: the environmental context
is withheld so the observation stays independent of the evidence it is
checked against. The model id is a setting; the code never pins a version.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from aeropulse_observability import get_logger

from aeropulse_vision.observer import (
    INVALID,
    OBSERVATION_SCHEMA,
    UNAVAILABLE,
    ObservationError,
    ObserverResult,
    safe_observation_type,
    validate_observation,
)
from aeropulse_vision.sanitize import SanitizedImage

log = get_logger("aeropulse.vision.gemini")

_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
#: Setting: sampling temperature for a categorical description.
TEMPERATURE = 0.1


def observer_prompt(version: str = "v1") -> str:
    return (_PROMPT_DIR / f"observer_{version}.md").read_text(encoding="utf-8")


class GeminiObserver:
    """Calls Gemini through ``google-genai`` with an API key or Vertex AI (ADC)."""

    provenance_class: Literal["ai_observation"] = "ai_observation"

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        vertex_project: str | None = None,
        vertex_location: str = "global",
        client: Any | None = None,
        prompt_version: str = "v1",
    ) -> None:
        self.model = model
        self.prompt_version = prompt_version
        self.version = f"gemini-observer-{prompt_version}:{model}"
        self._client = client
        self._api_key = api_key
        self._vertex_project = vertex_project
        self._vertex_location = vertex_location

    @property
    def available(self) -> bool:
        return self._client is not None or bool(self._api_key or self._vertex_project)

    def _ensure_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        if not self.available:
            return None
        try:
            from google import genai
        except ImportError:
            log.warning("vision.gemini_sdk_missing")
            return None
        if self._vertex_project:
            self._client = genai.Client(
                vertexai=True, project=self._vertex_project, location=self._vertex_location
            )
        else:
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def observe(self, image: SanitizedImage, observation_type: str) -> ObserverResult:
        client = self._ensure_client()
        if client is None:
            return ObserverResult(None, (UNAVAILABLE,))
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=observer_prompt(self.prompt_version),
            temperature=TEMPERATURE,
            response_mime_type="application/json",
            response_json_schema=OBSERVATION_SCHEMA,
        )
        contents = [
            types.Part.from_bytes(data=image.data, mime_type=image.content_type),
            types.Part(
                text=f"Reported observation type: {safe_observation_type(observation_type)}"
            ),
        ]
        try:
            response = client.models.generate_content(
                model=self.model, contents=contents, config=config
            )
        except Exception:
            # Any SDK, transport or quota failure: the report waits for an operator.
            log.exception("vision.gemini_failed", model=self.model)
            return ObserverResult(None, (UNAVAILABLE,))
        try:
            observation = validate_observation(
                getattr(response, "text", "") or "", observer_version=self.version
            )
        except ObservationError as exc:
            log.warning("vision.observation_rejected", model=self.model, reason=str(exc))
            return ObserverResult(None, (INVALID,))
        return ObserverResult(observation)
