"""Turbulent spread: Pasquill stability class and Briggs horizontal dispersion.

Sources (cited in the model card, not tuned here):

- Stability class from 10 m wind speed and daytime insolation or night-time
  cloud: Pasquill (1961), as tabulated by Turner (1970), *Workbook of
  Atmospheric Dispersion Estimates*. Heavy overcast is neutral (D)
  day or night. Turner leaves night-time below 2 m/s blank; it is taken as F
  here, the most stable class in the table.
- Insolation from solar elevation: strong above 60 deg, moderate 35-60 deg,
  slight below 35 deg (Turner 1964). Cloud cover of at least half the sky
  lowers insolation by one step: a simplification of Turner's ceiling rule.
- Horizontal spread: Briggs (1973) open-country fits,
  ``sigma_y = a x (1 + 0.0001 x)^-1/2`` with ``x`` the travel distance in
  metres, as reproduced in Seinfeld & Pandis, *Atmospheric Chemistry and
  Physics*, chapter "Atmospheric Diffusion".
  The variance a particle gains over a step is ``sigma_y(x + dx)^2 - sigma_y(x)^2``,
  which is ``2 K_h dt`` with ``K_h = (1/2) d sigma_y^2 / dt``.
- Solar declination: Cooper (1969). The equation of time is ignored (at most
  about 16 minutes of solar time).
"""

from __future__ import annotations

import numpy as np

from aeropulse_intelligence.plume.geo import Array

#: Briggs (1973) rural ``a`` per class A..F.
BRIGGS_RURAL_A = np.array([0.22, 0.16, 0.11, 0.08, 0.06, 0.04])
BRIGGS_RURAL_B = 1.0e-4
NEUTRAL_CLASS = 3.0  # D

#: Wind-speed bins (m/s at 10 m): <2, 2-3, 3-5, 5-6, >=6.
_SPEED_EDGES = np.array([2.0, 3.0, 5.0, 6.0])
#: Pasquill table as class indices (A=0 .. F=5; x.5 is a mixed class, e.g. A-B).
#: Columns: strong, moderate, slight insolation, night cloudy (>=4/8), night clear (<=3/8).
_PASQUILL = np.array(
    [
        [0.0, 0.5, 1.0, 5.0, 5.0],
        [0.5, 1.0, 2.0, 4.0, 5.0],
        [1.0, 1.5, 2.0, 3.0, 4.0],
        [2.0, 2.5, 3.0, 3.0, 3.0],
        [2.0, 3.0, 3.0, 3.0, 3.0],
    ]
)
_STRONG, _MODERATE, _SLIGHT, _NIGHT_CLOUDY, _NIGHT_CLEAR = range(5)
OVERCAST_PERCENT = 87.5  # 7/8 of the sky and more: neutral
CLOUDY_PERCENT = 50.0  # 4/8 of the sky


def solar_elevation_deg(lat: Array, lon: Array, epoch_s: float) -> Array:
    """Solar elevation angle (degrees) at each point."""
    day = epoch_s / 86400.0
    day_of_year = (day % 365.2422) + 1.0
    declination = np.radians(23.44) * np.sin(2.0 * np.pi * (284.0 + day_of_year) / 365.0)
    utc_hours = (epoch_s % 86400.0) / 3600.0
    solar_hours = utc_hours + lon / 15.0
    hour_angle = np.radians(15.0 * (solar_hours - 12.0))
    phi = np.radians(lat)
    sin_el = np.sin(phi) * np.sin(declination) + np.cos(phi) * np.cos(declination) * np.cos(
        hour_angle
    )
    return np.degrees(np.arcsin(np.clip(sin_el, -1.0, 1.0)))


def stability_class(speed: Array, elevation_deg: Array, cloud_percent: Array) -> Array:
    """Pasquill class index per point; neutral (D) where cloud or wind is unknown."""
    row = np.searchsorted(_SPEED_EDGES, np.nan_to_num(speed, nan=0.0), side="right")
    cloudy = cloud_percent >= CLOUDY_PERCENT
    day = elevation_deg > 0.0
    insolation = np.where(
        elevation_deg > 60.0, _STRONG, np.where(elevation_deg > 35.0, _MODERATE, _SLIGHT)
    )
    insolation = np.where(cloudy, np.minimum(insolation + 1, _SLIGHT), insolation)
    col = np.where(day, insolation, np.where(cloudy, _NIGHT_CLOUDY, _NIGHT_CLEAR))
    cls = _PASQUILL[row, col]
    unknown = ~np.isfinite(cloud_percent) | ~np.isfinite(speed)
    overcast = cloud_percent >= OVERCAST_PERCENT
    return np.where(unknown | overcast, NEUTRAL_CLASS, cls)


def briggs_a(class_index: Array) -> Array:
    """Briggs ``a`` for a (possibly mixed) class index."""
    return np.interp(class_index, np.arange(6.0), BRIGGS_RURAL_A)


def sigma_y_m(a: Array, x_m: Array) -> Array:
    """Briggs rural horizontal spread (m) after ``x_m`` metres of travel."""
    x = np.maximum(x_m, 0.0)
    return a * x / np.sqrt(1.0 + BRIGGS_RURAL_B * x)


def variance_increment_m2(a: Array, x_m: Array, dx_m: Array) -> Array:
    """Horizontal variance (m^2, per axis) gained over a step of ``dx_m``."""
    return np.maximum(sigma_y_m(a, x_m + dx_m) ** 2 - sigma_y_m(a, x_m) ** 2, 0.0)
