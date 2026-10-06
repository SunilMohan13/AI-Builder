"""Small deterministic geometry helpers used by features and likelihoods."""

from __future__ import annotations

import math


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlmb = math.radians(lon2 - lon1)
    x = math.sin(dlmb) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlmb)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def wind_speed(u: float, v: float) -> float:
    """Wind speed from u/v components (m/s)."""
    return math.hypot(u, v)


def wind_direction_from(u: float, v: float) -> float:
    """Meteorological direction the wind blows FROM, degrees from north."""
    return (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0


def wind_direction_to(u: float, v: float) -> float:
    """Direction the wind blows TOWARD, degrees from north."""
    return (math.degrees(math.atan2(u, v)) + 360.0) % 360.0


def cosine_alignment(deg_a: float, deg_b: float) -> float:
    """1.0 if two bearings match, 0.0 if opposite. Mapped to [0, 1]."""
    delta = abs((deg_a - deg_b + 180.0) % 360.0 - 180.0)
    return max(0.0, math.cos(math.radians(delta)))
