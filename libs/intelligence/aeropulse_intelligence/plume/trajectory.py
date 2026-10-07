"""Deterministic trajectory integration over a gridded or site wind field.

Shared by the plume engine and by the ``transport_weighted_frp`` feature, so a
fire the feature calls "upwind" is upwind by the same physics the plume map
shows.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from aeropulse_intelligence.plume.geo import Array, displace, haversine_km, nearest_index

SECONDS_PER_HOUR = 3600.0


class WindField(Protocol):
    def uv(self, lat: Array, lon: Array, bucket: datetime) -> tuple[Array, Array]:
        """Wind (m/s, u east, v north) during the hour ending at ``bucket``.

        NaN where the wind is unknown; a trajectory stops there.
        """
        ...


@dataclass(frozen=True)
class SiteWindField:
    """Nearest-site wind, one value per site per hour-ending bucket.

    Attributes:
        site_lat: Site latitudes.
        site_lon: Site longitudes.
        hours: ``bucket -> (u[sites], v[sites])``; NaN where a site has no value.
        max_site_km: Points farther than this from every site get NaN.
    """

    site_lat: Array
    site_lon: Array
    hours: Mapping[datetime, tuple[Array, Array]]
    max_site_km: float

    def uv(self, lat: Array, lon: Array, bucket: datetime) -> tuple[Array, Array]:
        nan = np.full(lat.shape, np.nan)
        winds = self.hours.get(bucket)
        if winds is None:
            return nan, nan.copy()
        idx = nearest_index(lat, lon, self.site_lat, self.site_lon, self.max_site_km)
        ok = idx >= 0
        u, v = nan.copy(), nan.copy()
        u[ok] = winds[0][idx[ok]]
        v[ok] = winds[1][idx[ok]]
        return u, v


@dataclass(frozen=True)
class Trajectory:
    """Positions at ``start - k hours`` (backward) or ``start + k hours`` (forward).

    Arrays are ``[k, point]``; ``k = 0`` is the start. NaN once wind is unknown.
    ``travelled_km`` is cumulative path length.
    """

    lat: Array
    lon: Array
    travelled_km: Array


def integrate(
    lat: Array,
    lon: Array,
    start: datetime,
    wind: WindField,
    hours: int,
    *,
    backward: bool,
) -> Trajectory:
    """Hourly Euler steps through ``wind`` from ``start``.

    Backward: the step from ``start - k`` to ``start - k - 1`` uses the wind of
    the hour ending at ``start - k``, which is known at ``start``.
    Forward: the step from ``start + k`` uses the hour ending at ``start + k + 1``.
    """
    n = lat.size
    out_lat = np.full((hours + 1, n), np.nan)
    out_lon = np.full((hours + 1, n), np.nan)
    travelled = np.full((hours + 1, n), np.nan)
    out_lat[0], out_lon[0], travelled[0] = lat, lon, 0.0
    sign = -1.0 if backward else 1.0
    for k in range(hours):
        bucket = start - timedelta(hours=k) if backward else start + timedelta(hours=k + 1)
        cur_lat, cur_lon = out_lat[k], out_lon[k]
        u, v = wind.uv(cur_lat, cur_lon, bucket)
        east = sign * u * SECONDS_PER_HOUR / 1000.0
        north = sign * v * SECONDS_PER_HOUR / 1000.0
        next_lat, next_lon = displace(cur_lat, cur_lon, east, north)
        out_lat[k + 1], out_lon[k + 1] = next_lat, next_lon
        travelled[k + 1] = travelled[k] + np.hypot(east, north)
    return Trajectory(out_lat, out_lon, travelled)


def puff_weights(
    trajectory: Trajectory,
    fire_lat: Array,
    fire_lon: Array,
    fire_age_hours: Array,
    *,
    initial_spread_km: float,
    spread_fraction: float,
) -> NDArray[np.float64]:
    """Gaussian puff weight of each fire under each point's back-trajectory.

    For fire ``j`` seen ``a`` hours before the start, the weight for point
    ``i`` is ``exp(-d^2 / 2 sigma^2)`` where ``d`` is the distance from the fire
    to the trajectory position ``round(a)`` hours back and ``sigma`` grows with
    distance travelled. This is the ensemble-mean limit of the particle
    engine. Returns ``[point, fire]`` in [0, 1]; 0 where wind was unknown.
    """
    n_points = trajectory.lat.shape[1]
    steps = trajectory.lat.shape[0] - 1
    weights = np.zeros((n_points, fire_lat.size))
    if fire_lat.size == 0 or n_points == 0:
        return weights
    k = np.clip(np.rint(fire_age_hours).astype(np.int64), 0, steps)
    pos_lat = trajectory.lat[k, :].T
    pos_lon = trajectory.lon[k, :].T
    sigma = initial_spread_km + spread_fraction * trajectory.travelled_km[k, :].T
    d = haversine_km(pos_lat, pos_lon, fire_lat[None, :], fire_lon[None, :])
    w = np.exp(-(d**2) / (2.0 * sigma**2))
    weights[:] = np.where(np.isfinite(w), w, 0.0)
    return weights
