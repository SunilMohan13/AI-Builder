"""Test-wide isolation from developer configuration.

``Settings`` loads a local ``.env`` (``SettingsConfigDict(env_file=".env")``).
That is right for running the platform and wrong for running its tests: a
developer who has configured real OpenAQ, FIRMS or Gemini credentials would
see different results from one who has not, and assertions about
"no credential is configured" would silently invert.

This pins the whole suite to declared defaults, so a test that wants a
credential sets one explicitly.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from aeropulse_common.settings import Settings, get_settings

# Logging configures itself on import, before fixtures run. A test-only secret
# lets collection succeed. Runtime still refuses to start without one.
os.environ.setdefault("AEROPULSE_JWT_SECRET", "unit-test-secret-must-be-32bytes!")

#: Variables that change behaviour under test if a developer has them set.
#: Credentials flip live-mode branches; connector mode flips replay/live.
_ISOLATED_ENV_PREFIX = "AEROPULSE_"


@pytest.fixture(autouse=True, scope="session")
def _isolate_settings_from_dotenv() -> Iterator[None]:
    """Stop ``Settings`` reading the developer's ``.env`` during tests."""
    original = Settings.model_config.get("env_file")
    Settings.model_config["env_file"] = None
    get_settings.cache_clear()
    try:
        yield
    finally:
        Settings.model_config["env_file"] = original
        get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _isolate_settings_from_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear exported ``AEROPULSE_*`` variables for the duration of a test.

    ``.env`` is the usual source, but a shell export would bypass the session
    fixture above. Tests that need a value set it themselves.
    """
    for name in list(os.environ):
        if name.startswith(_ISOLATED_ENV_PREFIX):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AEROPULSE_JWT_SECRET", "unit-test-secret-must-be-32bytes!")
    get_settings.cache_clear()
