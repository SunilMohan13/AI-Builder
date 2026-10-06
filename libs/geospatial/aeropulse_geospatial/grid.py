"""Deterministic 1 km-scale grid indexing using H3 resolution 8.

H3 res 8 has average hex area ≈ 0.74 km², the closest resolution to a 1 km cell.
Do not use lat/lon rounding as a primary key.
"""

from __future__ import annotations

import h3

DEFAULT_RESOLUTION = 8

# Punjab–Haryana–Delhi NCR bounding box (min_lon, min_lat, max_lon, max_lat)
DEFAULT_AOI: tuple[float, float, float, float] = (73.5, 27.0, 78.5, 32.5)


def to_grid_id(lat: float, lon: float, resolution: int = DEFAULT_RESOLUTION) -> str:
    """Return a stable H3 cell index for a WGS84 point.

    Args:
        lat: Latitude in degrees.
        lon: Longitude in degrees.
        resolution: H3 resolution. Defaults to 8 (~1 km).

    Returns:
        H3 cell index as a hexadecimal string.
    """
    return h3.latlng_to_cell(lat, lon, resolution)


def neighbors(grid_id: str, k: int = 1) -> list[str]:
    """Return H3 cells in the k-ring around ``grid_id``, excluding itself."""
    disk = list(h3.grid_disk(grid_id, k))
    return [cell for cell in disk if cell != grid_id]


def grid_center(grid_id: str) -> tuple[float, float]:
    """Return the WGS84 latitude/longitude center of an H3 cell."""
    lat, lon = h3.cell_to_latlng(grid_id)
    return float(lat), float(lon)


def grid_boundary(grid_id: str) -> list[list[float]]:
    """Return a closed GeoJSON longitude/latitude ring for an H3 cell."""
    ring = [[float(lon), float(lat)] for lat, lon in h3.cell_to_boundary(grid_id)]
    return [*ring, ring[0]]


def in_default_aoi(lat: float, lon: float) -> bool:
    """Return True if the point lies inside the default NCR corridor AOI."""
    min_lon, min_lat, max_lon, max_lat = DEFAULT_AOI
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon
