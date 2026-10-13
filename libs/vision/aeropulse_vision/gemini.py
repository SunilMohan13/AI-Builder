"""Gemini as a ``VisualObserver`` (LLD APAC 9.4).

Multimodal, low temperature, no tools, structured output only. The photo and
the citizen's observation type are the whole input: the environmental context
is withheld so the observation stays independent of the evidence it is
checked against. The model id is a setting; the code never pins a version.
"""

from __future__ import annotations

from collections.abc import Sequence
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
#: Transient Gemini answers worth another attempt ("high demand" is a 503).
#: A 504 is not retried: the model already used the whole request timeout,
#: so the next model is the better bet.
RETRY_STATUS_CODES = (408, 429, 500, 502, 503)
#: Attempts per model, with exponential backoff between them. The local API
#: waits 60 s for the whole analysis, so the backoff stays short.
RETRY_ATTEMPTS = 3
RETRY_INITIAL_DELAY_S = 2.0
RETRY_MAX_DELAY_S = 8.0
#: Per request. Without it an overloaded model can hold the call for minutes.
REQUEST_TIMEOUT_MS = 20_000


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
        fallback_models: Sequence[str] = (),
    ) -> None:
        self.model = model
        self.models = list(dict.fromkeys([model, *(m for m in fallback_models if m)]))
        self.prompt_version = prompt_version
        self.version = self._version(model)
        self._client = client
        self._api_key = api_key
        self._vertex_project = vertex_project
        self._vertex_location = vertex_location

    @property
    def available(self) -> bool:
        return self._client is not None or bool(self._api_key or self._vertex_project)

    def _version(self, model: str) -> str:
        return f"gemini-observer-{self.prompt_version}:{model}"

    def _ensure_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        if not self.available:
            return None
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            log.warning("vision.gemini_sdk_missing")
            return None
        http_options = types.HttpOptions(
            timeout=REQUEST_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(
                attempts=RETRY_ATTEMPTS,
                initial_delay=RETRY_INITIAL_DELAY_S,
                max_delay=RETRY_MAX_DELAY_S,
                http_status_codes=list(RETRY_STATUS_CODES),
            ),
        )
        if self._vertex_project:
            self._client = genai.Client(
                vertexai=True,
                project=self._vertex_project,
                location=self._vertex_location,
                http_options=http_options,
            )
        else:
            self._client = genai.Client(api_key=self._api_key, http_options=http_options)
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
        response: Any = None
        used = self.model
        for used in self.models:
            try:
                response = client.models.generate_content(
                    model=used, contents=contents, config=config
                )
                break
            except Exception:
                # Any SDK, transport or quota failure, after the client's retries.
                log.exception("vision.gemini_failed", model=used)
        if response is None:
            return ObserverResult(None, (UNAVAILABLE,))
        try:
            observation = validate_observation(
                getattr(response, "text", "") or "", observer_version=self._version(used)
            )
        except ObservationError as exc:
            log.warning("vision.observation_rejected", model=used, reason=str(exc))
            return ObserverResult(None, (INVALID,))
        return ObserverResult(observation)
