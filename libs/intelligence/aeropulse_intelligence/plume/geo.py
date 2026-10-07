"""Vectorised geodesy for plume transport (spherical Earth)."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

#: IUGG mean Earth radius.
EARTH_RADIUS_KM = 6371.0088
KM_PER_DEG_LAT = np.pi * EARTH_RADIUS_KM / 180.0

Array = NDArray[np.float64]


def haversine_km(lat1: Array, lon1: Array, lat2: Array, lon2: Array) -> Array:
    """Great-circle distance; inputs broadcast against each other."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dp / 2.0) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def displace(lat: Array, lon: Array, east_km: Array, north_km: Array) -> tuple[Array, Array]:
    """Move points by a local east/north offset (small-step approximation)."""
    new_lat = lat + north_km / KM_PER_DEG_LAT
    cos_lat = np.maximum(np.cos(np.radians(lat)), 1e-6)
    new_lon = lon + east_km / (KM_PER_DEG_LAT * cos_lat)
    return new_lat, new_lon


def nearest_index(
    lat: Array, lon: Array, site_lat: Array, site_lon: Array, max_km: float
) -> NDArray[np.int64]:
    """Index of the nearest site per point, or -1 beyond ``max_km`` or with no sites."""
    if site_lat.size == 0:
        return np.full(lat.shape, -1, dtype=np.int64)
    d = haversine_km(lat[:, None], lon[:, None], site_lat[None, :], site_lon[None, :])
    idx = np.argmin(d, axis=1).astype(np.int64)
    best = d[np.arange(lat.size), idx]
    idx[~(best <= max_km)] = -1
    return idx
