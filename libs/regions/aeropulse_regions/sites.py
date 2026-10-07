"""Deterministic wind-site placement and display-cell tiling from a pack.

Display area: H3 resolution-5 centroids. Rest of the source domain: the
pack's ``wind_site_resolution``. When a set exceeds its budget, sites are
chosen by farthest-point sampling (seeded at the cell nearest the bbox
centre), so they stay spatially uniform and use the whole budget. The source
domain is never tiled at resolution 8.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import h3

from aeropulse_regions.models import BBox, RegionPack, bbox_contains_point

DISPLAY_SITE_RESOLUTION = 5
#: Share of ``max_wind_sites`` reserved for the display area.
DISPLAY_SITE_SHARE = 0.5
#: Candidate cap before sampling; coarsen the candidate grid above this.
_MAX_CANDIDATES = 6000


@dataclass(frozen=True)
class WindSite:
    site_id: str
    lat: float
    lon: float
    resolution: int
    in_display: bool


def _bbox_poly(bbox: BBox) -> h3.LatLngPoly:
    min_lon, min_lat, max_lon, max_lat = bbox
    return h3.LatLngPoly(
        [(min_lat, min_lon), (min_lat, max_lon), (max_lat, max_lon), (max_lat, min_lon)]
    )


def cells_in_bbox(bbox: BBox, resolution: int) -> list[str]:
    """H3 cells whose centres fall inside ``bbox``, sorted for determinism."""
    cells = h3.polygon_to_cells(_bbox_poly(bbox), resolution)
    if not cells:
        min_lon, min_lat, max_lon, max_lat = bbox
        cells = [h3.latlng_to_cell((min_lat + max_lat) / 2, (min_lon + max_lon) / 2, resolution)]
    return sorted(cells)


def _candidates(bbox: BBox, resolution: int) -> tuple[int, list[str]]:
    res = resolution
    cells = cells_in_bbox(bbox, res)
    while len(cells) > _MAX_CANDIDATES and res > 0:
        res -= 1
        cells = cells_in_bbox(bbox, res)
    return res, cells


def _chord(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    x = math.cos(lat2) * math.cos(lon2) - math.cos(lat1) * math.cos(lon1)
    y = math.cos(lat2) * math.sin(lon2) - math.cos(lat1) * math.sin(lon1)
    z = math.sin(lat2) - math.sin(lat1)
    return x * x + y * y + z * z


def farthest_point_sample(cells: list[str], budget: int, centre: tuple[float, float]) -> list[str]:
    """Pick ``budget`` cells spread as evenly as possible; deterministic."""
    if len(cells) <= budget:
        return cells
    points = [h3.cell_to_latlng(c) for c in cells]
    first = min(range(len(cells)), key=lambda i: (_chord(points[i], centre), cells[i]))
    chosen = [first]
    nearest = [_chord(p, points[first]) for p in points]
    while len(chosen) < budget:
        nxt = max(range(len(cells)), key=lambda i: (nearest[i], cells[i]))
        chosen.append(nxt)
        for i, p in enumerate(points):
            d = _chord(p, points[nxt])
            if d < nearest[i]:
                nearest[i] = d
    return [cells[i] for i in chosen]


def _centre(bbox: BBox) -> tuple[float, float]:
    return (bbox[1] + bbox[3]) / 2, (bbox[0] + bbox[2]) / 2


def wind_sites(pack: RegionPack) -> list[WindSite]:
    """Sites where wind forecasts are fetched for ``pack``."""
    budget = pack.source_domain.max_wind_sites
    same_domain = pack.source_domain.bbox == pack.geometry.bbox
    display_budget = budget if same_domain else max(1, int(budget * DISPLAY_SITE_SHARE))

    res_d, cand_d = _candidates(pack.geometry.bbox, DISPLAY_SITE_RESOLUTION)
    picked_d = farthest_point_sample(cand_d, display_budget, _centre(pack.geometry.bbox))
    sites = [
        WindSite(c, *h3.cell_to_latlng(c), resolution=res_d, in_display=True) for c in picked_d
    ]
    remaining = budget - len(sites)
    if remaining <= 0 or same_domain:
        return sites

    res_s, cand_s = _candidates(pack.source_domain.bbox, pack.source_domain.wind_site_resolution)
    outside = [
        c for c in cand_s if not bbox_contains_point(pack.geometry.bbox, *h3.cell_to_latlng(c))
    ]
    picked_s = farthest_point_sample(outside, remaining, _centre(pack.source_domain.bbox))
    sites.extend(
        WindSite(c, *h3.cell_to_latlng(c), resolution=res_s, in_display=False) for c in picked_s
    )
    return sites


def display_cells(pack: RegionPack) -> list[str]:
    """Resolution-8 cells materialised for the display area."""
    return cells_in_bbox(pack.geometry.bbox, pack.h3_resolution)
