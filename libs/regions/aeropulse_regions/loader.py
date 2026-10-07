"""Read Region Packs, hazard profiles, and AQI standards from ``config/``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from aeropulse_common.errors import RegionPackError
from pydantic import ValidationError

from aeropulse_regions.models import AqiStandard, HazardProfile, RegionPack

REGIONS_DIR = "regions"
HAZARDS_DIR = "hazard_profiles"
AQI_DIR = "aqi_standards"
REGION_FILE = "region.yaml"


def find_config_dir(configured: Path) -> Path:
    """Resolve the config directory.

    An absolute or existing path is used as given. A relative path that does
    not exist from the working directory is searched for upward, so tests
    and CLIs work from any sub-directory of the repository.
    """
    if configured.is_absolute() or (configured / REGIONS_DIR).is_dir():
        return configured
    for base in (Path.cwd(), *Path.cwd().parents):
        candidate = base / configured
        if (candidate / REGIONS_DIR).is_dir():
            return candidate
    raise RegionPackError(f"config directory not found: {configured}")


def read_yaml(path: Path) -> dict[str, Any]:
    """Load one YAML mapping, failing loudly on anything else."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RegionPackError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RegionPackError(f"{path} must contain a mapping")
    return data


def load_pack(path: Path) -> RegionPack:
    """Load and validate one ``region.yaml``."""
    try:
        pack = RegionPack.model_validate(read_yaml(path))
    except ValidationError as exc:
        raise RegionPackError(f"{path}: {exc}") from exc
    if pack.region_id != path.parent.name:
        raise RegionPackError(
            f"{path}: region_id {pack.region_id!r} must match its directory {path.parent.name!r}"
        )
    return pack


def load_packs(*regions_dirs: Path) -> dict[str, RegionPack]:
    """Load every ``<dir>/<region_id>/region.yaml`` under each directory."""
    packs: dict[str, RegionPack] = {}
    for regions_dir in regions_dirs:
        if not regions_dir.is_dir():
            continue
        for path in sorted(regions_dir.glob(f"*/{REGION_FILE}")):
            pack = load_pack(path)
            if pack.region_id in packs:
                raise RegionPackError(f"region {pack.region_id} is defined twice")
            packs[pack.region_id] = pack
    return packs


def load_hazard_profiles(config_dir: Path) -> dict[str, HazardProfile]:
    profiles: dict[str, HazardProfile] = {}
    for path in sorted((config_dir / HAZARDS_DIR).glob("*.yaml")):
        try:
            profile = HazardProfile.model_validate(read_yaml(path))
        except ValidationError as exc:
            raise RegionPackError(f"{path}: {exc}") from exc
        if profile.key != path.stem:
            raise RegionPackError(f"{path}: key {profile.key!r} must match the file name")
        profiles[profile.key] = profile
    return profiles


def load_aqi_standards(config_dir: Path) -> dict[str, AqiStandard]:
    standards: dict[str, AqiStandard] = {}
    for path in sorted((config_dir / AQI_DIR).glob("*.yaml")):
        try:
            standard = AqiStandard.model_validate(read_yaml(path))
        except ValidationError as exc:
            raise RegionPackError(f"{path}: {exc}") from exc
        if standard.key != path.stem:
            raise RegionPackError(f"{path}: key {standard.key!r} must match the file name")
        standards[standard.key] = standard
    return standards
