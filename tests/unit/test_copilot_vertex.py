"""On Google Cloud the copilot reaches Gemini through Vertex AI, never a key (LLD APAC 10)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from aeropulse_api.copilot_service import get_copilot_service
from aeropulse_common.settings import get_settings


@pytest.fixture(autouse=True)
def _fresh_service() -> Iterator[None]:
    get_copilot_service.cache_clear()
    yield
    get_copilot_service.cache_clear()


def _gemini(monkeypatch: pytest.MonkeyPatch, **env: str) -> Any:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    return get_copilot_service()._gemini  # pyright: ignore[reportPrivateUsage]


def test_on_gcp_the_service_account_answers_and_a_key_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gemini = _gemini(
        monkeypatch,
        AEROPULSE_PLATFORM="gcp",
        AEROPULSE_GCP_PROJECT="demo-project",
        AEROPULSE_GEMINI_API_KEY="local-only-placeholder",
    )
    assert gemini is not None and gemini.available
    assert gemini._vertex_project == "demo-project"
    assert gemini._api_key is None


def test_locally_without_a_key_there_is_no_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _gemini(monkeypatch) is None


def test_locally_a_key_enables_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    gemini = _gemini(monkeypatch, AEROPULSE_GEMINI_API_KEY="local-only-placeholder")
    assert gemini is not None and gemini.available
    assert gemini._vertex_project is None
