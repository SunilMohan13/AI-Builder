"""Every fixture declared in config/sources.yaml must exist on disk.

The whole replay pipeline is fixture-backed. When these files go missing the
connector process raises FileNotFoundError mid-cycle and publishes nothing, and
`docker compose build` fails on `COPY fixtures`. That failure mode is silent in
a working tree and expensive in CI, so it gets its own guard.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCES_CONFIG = REPO_ROOT / "config" / "sources.yaml"


def _declared_fixtures() -> list[tuple[str, Path]]:
    config = yaml.safe_load(SOURCES_CONFIG.read_text(encoding="utf-8"))
    declared: list[tuple[str, Path]] = []
    for source in config["sources"]:
        fixture = source.get("fixture")
        if fixture:
            declared.append((source["id"], REPO_ROOT / fixture))
    return declared


def test_sources_config_declares_fixtures() -> None:
    """Guard the guard: an empty parse would make every case below vacuous."""
    assert len(_declared_fixtures()) >= 13


@pytest.mark.parametrize(("source_id", "path"), _declared_fixtures())
def test_declared_fixture_exists(source_id: str, path: Path) -> None:
    assert path.is_file(), f"{source_id}: fixture missing at {path.relative_to(REPO_ROOT)}"


@pytest.mark.parametrize(("source_id", "path"), _declared_fixtures())
def test_declared_fixture_is_valid_json(source_id: str, path: Path) -> None:
    if not path.is_file():
        pytest.skip("covered by test_declared_fixture_exists")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload, f"{source_id}: fixture parsed but is empty"
