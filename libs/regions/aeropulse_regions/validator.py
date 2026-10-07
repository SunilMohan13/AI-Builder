"""Cross-file Region Pack rules.

Single-file rules (bbox containment, ``h3_resolution`` 8, secret references,
truth vs model-derived overlap) live on the models. These need the whole
catalog: hazards and AQI standards must exist, and every source id must be a
connector that is actually installed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from aeropulse_regions.models import AqiStandard, HazardProfile, RegionPack


def pack_issues(
    pack: RegionPack,
    *,
    hazard_profiles: Mapping[str, HazardProfile],
    aqi_standards: Mapping[str, AqiStandard],
    known_source_ids: Iterable[str] | None = None,
) -> list[str]:
    """Every cross-file problem with ``pack``; empty when it is valid."""
    issues: list[str] = []
    for hazard in pack.hazards:
        if hazard not in hazard_profiles:
            issues.append(f"{pack.region_id}: hazard profile {hazard!r} does not exist")
    if pack.aqi_standard not in aqi_standards:
        issues.append(f"{pack.region_id}: AQI standard {pack.aqi_standard!r} does not exist")
    if known_source_ids is not None:
        known = set(known_source_ids)
        for entry in pack.sources:
            if entry.id not in known:
                issues.append(f"{pack.region_id}: source {entry.id!r} has no installed connector")
    return issues


def catalog_issues(
    packs: Mapping[str, RegionPack],
    *,
    hazard_profiles: Mapping[str, HazardProfile],
    aqi_standards: Mapping[str, AqiStandard],
    known_source_ids: Iterable[str] | None = None,
) -> list[str]:
    """Problems across every pack in the catalog."""
    known = list(known_source_ids) if known_source_ids is not None else None
    issues: list[str] = []
    for pack in packs.values():
        issues.extend(
            pack_issues(
                pack,
                hazard_profiles=hazard_profiles,
                aqi_standards=aqi_standards,
                known_source_ids=known,
            )
        )
    return issues
