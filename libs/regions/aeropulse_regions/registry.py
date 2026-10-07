"""The loaded, validated set of regions the process serves."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from aeropulse_common.errors import RegionNotFoundError, RegionPackError
from aeropulse_common.settings import get_settings

from aeropulse_regions.loader import (
    REGIONS_DIR,
    find_config_dir,
    load_aqi_standards,
    load_hazard_profiles,
    load_packs,
)
from aeropulse_regions.models import AqiStandard, HazardProfile, RegionPack
from aeropulse_regions.validator import catalog_issues


@dataclass(frozen=True)
class RegionCatalog:
    """Region Packs plus the hazard profiles and AQI standards they reference."""

    config_dir: Path
    packs: dict[str, RegionPack]
    hazard_profiles: dict[str, HazardProfile]
    aqi_standards: dict[str, AqiStandard]
    region_dirs: dict[str, Path]

    def get(self, region_id: str) -> RegionPack:
        try:
            return self.packs[region_id]
        except KeyError as exc:
            raise RegionNotFoundError(region_id) from exc

    def region_ids(self) -> list[str]:
        return sorted(self.packs)

    def hazards_for(self, region_id: str) -> list[HazardProfile]:
        return [self.hazard_profiles[h] for h in self.get(region_id).hazards]

    def aqi_for(self, region_id: str) -> AqiStandard:
        return self.aqi_standards[self.get(region_id).aqi_standard]

    def region_dir(self, region_id: str) -> Path:
        """Directory holding the pack and its onboarding outputs."""
        self.get(region_id)
        return self.region_dirs[region_id]

    def seasonal_months(self, region_id: str) -> dict[str, frozenset[int]]:
        """``{feature_name: months}`` from the region's hazard profiles."""
        months: dict[str, set[int]] = {}
        for profile in self.hazards_for(region_id):
            if profile.seasonal_prior is not None:
                prior = profile.seasonal_prior
                months.setdefault(prior.feature, set()).update(prior.months)
        return {k: frozenset(v) for k, v in months.items()}


def load_catalog(
    config_dir: Path | None = None,
    *,
    extra_region_dirs: Iterable[Path] = (),
    known_source_ids: Iterable[str] | None = None,
) -> RegionCatalog:
    """Load and validate the whole catalog, raising on the first invalid file.

    Args:
        config_dir: The ``config/`` directory. Defaults to settings.
        extra_region_dirs: Additional ``regions/`` roots (test packs).
        known_source_ids: Installed connector ids; when given, every source a
            pack names must be one of them.
    """
    root = find_config_dir(config_dir or get_settings().config_dir)
    region_roots = [root / REGIONS_DIR, *extra_region_dirs]
    packs = load_packs(*region_roots)
    hazards = load_hazard_profiles(root)
    standards = load_aqi_standards(root)
    issues = catalog_issues(
        packs,
        hazard_profiles=hazards,
        aqi_standards=standards,
        known_source_ids=known_source_ids,
    )
    if issues:
        raise RegionPackError("; ".join(issues))
    region_dirs: dict[str, Path] = {}
    for base in region_roots:
        for region_id in packs:
            candidate = base / region_id
            if (candidate / "region.yaml").is_file():
                region_dirs[region_id] = candidate
    return RegionCatalog(
        config_dir=root,
        packs=packs,
        hazard_profiles=hazards,
        aqi_standards=standards,
        region_dirs=region_dirs,
    )


@lru_cache(maxsize=1)
def get_catalog() -> RegionCatalog:
    """Process-wide catalog from ``AEROPULSE_CONFIG_DIR``."""
    return load_catalog()
