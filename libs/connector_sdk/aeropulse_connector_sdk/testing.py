"""Test helpers for connector contract tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from aeropulse_common.errors import ConnectorError

from aeropulse_connector_sdk.contracts import ConnectorMetadata


class FixtureMissingError(ConnectorError):
    """Raised when a connector's replay fixture is absent from disk.

    Distinguished from a bare ``FileNotFoundError`` so the runner can degrade a
    single source instead of aborting the whole cycle. Returning ``{}`` here
    instead would hide a real fault inside a primitive.
    """

    def __init__(self, path: Path) -> None:
        super().__init__(f"fixture not found: {path}")
        self.path = path


def load_fixture(path: str | Path) -> Any:
    """Load a JSON fixture file.

    Args:
        path: Path to a JSON document.

    Returns:
        Parsed JSON (dict or list).

    Raises:
        FixtureMissingError: The file does not exist.
    """
    fixture_path = Path(path)
    try:
        return json.loads(fixture_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FixtureMissingError(fixture_path) from exc


def load_yaml_metadata(path: str | Path) -> ConnectorMetadata:
    """Load connector metadata.yaml into a typed model."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return ConnectorMetadata.model_validate(data)
