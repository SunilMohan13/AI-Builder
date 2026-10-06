"""Load region packs from config. Missing standards are not filled in."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from aeropulse_regions.models import AqiStandard, HazardProfile, RegionPack


class PackError(ValueError):
    """A pack, profile, or standard failed validation."""


def load_packs(config_root: Path) -> dict[str, RegionPack]:
    """Load every region directory under ``config_root/regions``."""
    profiles = _load_profiles(config_root / "hazard_profiles")
    standards = _load_standards(config_root / "aqi_standards")
    packs: dict[str, RegionPack] = {}
    regions_root = config_root / "regions"
    if not regions_root.is_dir():
        raise PackError(f"missing regions directory {regions_root}")
    for path in sorted(regions_root.glob("*/region.yaml")):
        pack = _load_region(path, profiles, standards)
        packs[pack.region_id] = pack
    return packs


def load_pack(config_root: Path, region_id: str) -> RegionPack:
    """Load one pack by id."""
    packs = load_packs(config_root)
    try:
        return packs[region_id]
    except KeyError as exc:
        raise PackError(f"unknown region {region_id}") from exc


def label_pm25(standard: AqiStandard, value: float) -> str | None:
    """Return the official band, or None when the standard is not confirmed."""
    if not standard.confirmed:
        return None
    for band in standard.bands:
        high = band.high
        if value >= band.low and (high is None or value < high):
            return band.label
    return standard.bands[-1].label if standard.bands else None


def _load_region(
    path: Path,
    profiles: dict[str, HazardProfile],
    standards: dict[str, AqiStandard],
) -> RegionPack:
    raw = _read_yaml(path)
    try:
        pack = RegionPack.model_validate(raw)
    except ValidationError as exc:
        raise PackError(f"{path}: {exc}") from exc
    missing = [key for key in pack.hazards if key not in profiles]
    if missing:
        raise PackError(f"{path}: unknown hazard profiles {missing}")
    if pack.aqi_standard not in standards:
        raise PackError(f"{path}: unknown aqi standard {pack.aqi_standard}")
    return pack


def _load_profiles(root: Path) -> dict[str, HazardProfile]:
    profiles: dict[str, HazardProfile] = {}
    if not root.is_dir():
        raise PackError(f"missing hazard profiles {root}")
    for path in sorted(root.glob("*.yaml")):
        try:
            profile = HazardProfile.model_validate(_read_yaml(path))
        except ValidationError as exc:
            raise PackError(f"{path}: {exc}") from exc
        profiles[profile.key] = profile
    return profiles


def _load_standards(root: Path) -> dict[str, AqiStandard]:
    standards: dict[str, AqiStandard] = {}
    if not root.is_dir():
        raise PackError(f"missing aqi standards {root}")
    for path in sorted(root.glob("*.yaml")):
        try:
            standard = AqiStandard.model_validate(_read_yaml(path))
        except ValidationError as exc:
            raise PackError(f"{path}: {exc}") from exc
        standards[standard.key] = standard
    return standards


def _read_yaml(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise PackError(f"{path}: expected a mapping")
    return loaded
