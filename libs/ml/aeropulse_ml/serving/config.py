"""``config/model_serving.yaml``: the only place that says what is served (LLD APAC 7.7).

Promotion is a reviewed edit of this file. Training prints a snippet for the
reviewer and never writes it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from aeropulse_common.errors import ModelServingError
from aeropulse_contracts import ModelFamily
from pydantic import BaseModel, Field, ValidationError, model_validator

SERVING_SCHEMA_VERSION = "model_serving.v1"
SERVING_FILENAME = "model_serving.yaml"


class ServingEntry(BaseModel):
    """One promoted (family, region) pair."""

    model_config = {"extra": "forbid", "frozen": True}

    family: ModelFamily
    region_id: str
    model_version: str = Field(..., min_length=1)
    artifact_uri: str = Field(..., min_length=1)
    gate_report_uri: str = Field(..., min_length=1)
    calibrated: bool = False


class ServingConfig(BaseModel):
    model_config = {"extra": "forbid", "frozen": True}

    schema_version: Literal["model_serving.v1"] = SERVING_SCHEMA_VERSION
    entries: tuple[ServingEntry, ...] = ()

    @model_validator(mode="after")
    def _one_entry_per_pair(self) -> ServingConfig:
        seen: set[tuple[str, str]] = set()
        for entry in self.entries:
            key = (entry.family, entry.region_id)
            if key in seen:
                raise ValueError(f"two entries for {entry.family} in {entry.region_id}")
            seen.add(key)
        return self

    def entry(self, family: str, region_id: str) -> ServingEntry | None:
        for entry in self.entries:
            if entry.family == family and entry.region_id == region_id:
                return entry
        return None


def load_serving_config(path: Path) -> ServingConfig:
    """Parse and validate the serving file; a missing file means nothing is served."""
    if not path.is_file():
        return ServingConfig()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ModelServingError(f"{path.name} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ModelServingError(f"{path.name} must be a mapping with schema_version and entries")
    try:
        return ServingConfig.model_validate({**raw, "entries": raw.get("entries") or ()})
    except ValidationError as exc:
        raise ModelServingError(f"{path.name} is invalid: {exc}") from exc
