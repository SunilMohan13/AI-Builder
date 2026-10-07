"""Lagrangian particle ensemble (Global LLD 7.3, APAC LLD 8.2).

For each particle, with ``s = +1`` forward and ``-1`` backward::

    v1    = W(x, t) (+) perturb_i
    x_mid = x + s v1 dt/2
    v2    = W(x_mid, t + s dt/2) (+) perturb_i
    x     = x + s v2 dt + sqrt(dvar(stability, travel)) xi,   xi ~ N(0, I2)
    w_i   = w_i exp(-Lambda dt)   where it rains (forward only)

RK2 (midpoint) through a time-varying field is what lets a plume bend when
the wind turns. Everything is vectorised over particles.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from aeropulse_intelligence.plume.geo import Array, displace
from aeropulse_intelligence.plume.stability import (
    briggs_a,
    solar_elevation_deg,
    stability_class,
    variance_increment_m2,
)
from aeropulse_intelligence.plume.uncertainty import WindUncertainty
from aeropulse_intelligence.plume.wind import SECONDS_PER_HOUR, WindField

#: (min_lon, min_lat, max_lon, max_lat): where the wind field is defined.
Domain = tuple[float, float, float, float]


@dataclass(frozen=True)
class EnsembleSettings:
    """Run settings (APAC LLD 8.2). Recorded on every plume."""

    particles: int = 200
    dt_minutes: float = 15.0
    #: 1 applies Briggs spread; 0 turns turbulence off (tests, diagnostics).
    diffusion_scale: float = 1.0
    #: AR(1) correlation time of each particle's wind error.
    uncertainty_corr_hours: float = 3.0
    #: Below-cloud scavenging coefficient (1/s) while it rains: the HYSPLIT
    #: user guide's default for particles. Weight only; positions are unchanged.
    scavenging_per_s: float = 5.0e-5

    def as_dict(self) -> dict[str, float | int | str]:
        return {k: v for k, v in asdict(self).items()}


@dataclass(frozen=True)
class EnsembleRun:
    """Particle paths. ``[step, particle]`` arrays; step 0 is the release.

    ``hours`` is elapsed time since release (positive in both directions).
    ``active`` is False once a particle left the wind domain or met unknown
    wind; its last position is kept but it no longer counts.
    """

    lat: Array
    lon: Array
    weight: Array
    active: np.ndarray
    hours: Array

    def step_for(self, horizon_hours: float) -> int:
        return int(np.argmin(np.abs(self.hours - horizon_hours)))


def _inside(lat: Array, lon: Array, domain: Domain) -> np.ndarray:
    min_lon, min_lat, max_lon, max_lat = domain
    return (lon >= min_lon) & (lon <= max_lon) & (lat >= min_lat) & (lat <= max_lat)


def run_ensemble(
    lat0: float,
    lon0: float,
    release_epoch: float,
    wind: WindField,
    *,
    max_hours: float,
    backward: bool,
    domain: Domain,
    settings: EnsembleSettings,
    rng: np.random.Generator,
    uncertainty: WindUncertainty | None = None,
    issued_epoch: float | None = None,
    initial_spread_km: float = 0.0,
) -> EnsembleRun:
    """Integrate ``settings.particles`` particles for ``max_hours``."""
    n = settings.particles
    dt = settings.dt_minutes * 60.0
    steps = int(np.ceil(max_hours * SECONDS_PER_HOUR / dt))
    sign = -1.0 if backward else 1.0

    lat = np.full(n, float(lat0))
    lon = np.full(n, float(lon0))
    if initial_spread_km > 0:
        lat, lon = displace(
            lat, lon, rng.normal(0, initial_spread_km, n), rng.normal(0, initial_spread_km, n)
        )
    weight = np.ones(n)
    travelled_m = np.zeros(n)
    active = _inside(lat, lon, domain)
    eta = np.zeros(n)  # AR(1) speed error state
    zeta = np.zeros(n)  # AR(1) direction error state
    rho = float(np.exp(-dt / (settings.uncertainty_corr_hours * SECONDS_PER_HOUR)))

    out_lat = np.empty((steps + 1, n))
    out_lon = np.empty((steps + 1, n))
    out_w = np.empty((steps + 1, n))
    out_active = np.empty((steps + 1, n), dtype=bool)
    out_lat[0], out_lon[0], out_w[0], out_active[0] = lat, lon, weight, active

    t = release_epoch
    for k in range(steps):
        lead = (t - issued_epoch) / SECONDS_PER_HOUR if issued_epoch is not None else 0.0
        speed_sd, dir_sd = uncertainty.at_lead(lead) if uncertainty is not None else (0.0, 0.0)
        eta = rho * eta + np.sqrt(1.0 - rho**2) * rng.standard_normal(n)
        zeta = rho * zeta + np.sqrt(1.0 - rho**2) * rng.standard_normal(n)
        factor = 1.0 + speed_sd * eta
        theta = dir_sd * zeta

        u1, v1, _, _ = wind.sample(lat, lon, t)
        u1, v1 = _perturb(u1, v1, factor, theta)
        mid_lat, mid_lon = displace(lat, lon, sign * u1 * dt / 2000.0, sign * v1 * dt / 2000.0)
        t_mid = t + sign * dt / 2.0
        u2, v2, cloud, precip = wind.sample(mid_lat, mid_lon, t_mid)
        u2, v2 = _perturb(u2, v2, factor, theta)

        east_km = sign * u2 * dt / 1000.0
        north_km = sign * v2 * dt / 1000.0
        dx_m = np.hypot(east_km, north_km) * 1000.0
        if settings.diffusion_scale > 0:
            cls = stability_class(
                np.hypot(u2, v2), solar_elevation_deg(mid_lat, mid_lon, t_mid), cloud
            )
            var = variance_increment_m2(briggs_a(cls), travelled_m, dx_m)
            sd_km = settings.diffusion_scale * np.sqrt(var) / 1000.0
            east_km = east_km + sd_km * rng.standard_normal(n)
            north_km = north_km + sd_km * rng.standard_normal(n)

        moving = active & np.isfinite(east_km) & np.isfinite(north_km)
        new_lat, new_lon = displace(
            lat, lon, np.where(moving, east_km, 0.0), np.where(moving, north_km, 0.0)
        )
        lat, lon = np.where(moving, new_lat, lat), np.where(moving, new_lon, lon)
        travelled_m = travelled_m + np.where(moving, dx_m, 0.0)
        active = moving & _inside(lat, lon, domain)
        if not backward and settings.scavenging_per_s > 0:
            raining = np.nan_to_num(precip, nan=0.0) > 0.0
            weight = np.where(
                raining & moving, weight * np.exp(-settings.scavenging_per_s * dt), weight
            )
        t += sign * dt
        out_lat[k + 1], out_lon[k + 1], out_w[k + 1], out_active[k + 1] = (
            lat,
            lon,
            weight,
            active,
        )

    hours = np.arange(steps + 1, dtype=np.float64) * (dt / SECONDS_PER_HOUR)
    return EnsembleRun(lat=out_lat, lon=out_lon, weight=out_w, active=out_active, hours=hours)


def _perturb(u: Array, v: Array, factor: Array, theta: Array) -> tuple[Array, Array]:
    cos_t, sin_t = np.cos(theta), np.sin(theta)
    return factor * (u * cos_t - v * sin_t), factor * (u * sin_t + v * cos_t)
