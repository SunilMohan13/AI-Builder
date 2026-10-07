"""Resolve a pack's ``secret_ref`` name to a value at call time.

Packs hold names only. Values come from settings, the environment, or
Google Secret Manager, and are never logged or cached in module state.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from typing import Any

from aeropulse_common.settings import Settings, get_settings
from aeropulse_observability.logging import get_logger

logger = get_logger("aeropulse.connector.credentials")

CredentialResolver = Callable[[str | None], str | None]

_SETTINGS_PREFIX = "AEROPULSE_"
_ENV_PREFIX = "env:"
_SECRET_MANAGER_PREFIX = "projects/"


def _from_settings(ref: str, settings: Settings) -> str | None:
    field = ref.removeprefix(_SETTINGS_PREFIX).lower()
    value: Any = getattr(settings, field, None)
    if value is None:
        return None
    if hasattr(value, "get_secret_value"):
        value = value.get_secret_value()
    return str(value) or None


def _from_secret_manager(ref: str) -> str | None:
    try:
        secretmanager: Any = importlib.import_module("google.cloud.secretmanager")
    except ImportError:
        logger.warning("credentials.secret_manager_unavailable", secret_ref=ref)
        return None
    name = ref if "/versions/" in ref else f"{ref}/versions/latest"
    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(name=name)
    return response.payload.data.decode("utf-8") or None


def resolve_secret(ref: str | None, *, settings: Settings | None = None) -> str | None:
    """Return the secret named by ``ref``, or ``None`` when it is not configured.

    Args:
        ref: ``AEROPULSE_NAME`` (a settings field), ``env:NAME``, or a Secret
            Manager resource path. ``None`` means the source needs no secret.
        settings: Optional settings override.
    """
    if ref is None:
        return None
    if ref.startswith(_ENV_PREFIX):
        return os.environ.get(ref.removeprefix(_ENV_PREFIX)) or None
    if ref.startswith(_SETTINGS_PREFIX):
        return _from_settings(ref, settings or get_settings())
    if ref.startswith(_SECRET_MANAGER_PREFIX):
        return _from_secret_manager(ref)
    return None
