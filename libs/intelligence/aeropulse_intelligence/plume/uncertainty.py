"""Wind forecast uncertainty from the region's own errors (Global LLD 7.4).

Pairs each observed site-hour with the forecast for the same site-hour and
measures the error by lead time. Until enough days of pairs exist the spread
is zero and the plume says so: a guessed spread would look like knowledge.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import timedelta

import numpy as np
from aeropulse_contracts import MeteoForecast, MeteorologicalObservation

#: Settings.
MIN_PAIR_DAYS = 7
#: Lead-time buckets (hours, upper edge inclusive).
LEAD_BUCKETS_HOURS: tuple[float, ...] = (6.0, 12.0, 24.0, 48.0)
#: Below this speed (m/s) a direction is noise and is not compared.
MIN_SPEED_FOR_DIRECTION = 1.0
MIN_PAIRS_PER_BUCKET = 24

UNMEASURED_REASON = "wind_uncertainty_unmeasured"


@dataclass(frozen=True)
class LeadError:
    max_lead_hours: float
    speed_sd: float  # fractional speed error (dimensionless)
    direction_sd_deg: float
    pairs: int


@dataclass(frozen=True)
class WindUncertainty:
    """Per-lead spread; empty means unmeasured (zero spread, degraded)."""

    by_lead: tuple[LeadError, ...] = ()
    pair_days: float = 0.0

    @property
    def measured(self) -> bool:
        return bool(self.by_lead)

    def at_lead(self, lead_hours: float) -> tuple[float, float]:
        """``(speed_sd, direction_sd_rad)`` for a lead time; zero when unmeasured."""
        for bucket in self.by_lead:
            if lead_hours <= bucket.max_lead_hours:
                return bucket.speed_sd, float(np.radians(bucket.direction_sd_deg))
        if self.by_lead:
            last = self.by_lead[-1]
            return last.speed_sd, float(np.radians(last.direction_sd_deg))
        return 0.0, 0.0


def _site_hour(lat: float, lon: float, hour_epoch: float) -> tuple[float, float, int]:
    return round(lat, 4), round(lon, 4), round(hour_epoch)


def measure(
    forecasts: Iterable[MeteoForecast],
    weather: Iterable[MeteorologicalObservation],
    *,
    min_pair_days: int = MIN_PAIR_DAYS,
    buckets: Sequence[float] = LEAD_BUCKETS_HOURS,
) -> WindUncertainty:
    """Forecast-vs-observed 10 m wind errors per lead bucket."""
    observed: dict[tuple[float, float, int], tuple[float, float]] = {}
    for wx in weather:
        if wx.wind_u is None or wx.wind_v is None:
            continue
        hour = wx.observed_at.replace(minute=0, second=0, microsecond=0)
        if wx.observed_at != hour:
            hour += timedelta(hours=1)
        observed[_site_hour(wx.location.lat, wx.location.lon, hour.timestamp())] = (
            wx.wind_u,
            wx.wind_v,
        )

    speed_err: dict[float, list[float]] = {b: [] for b in buckets}
    dir_err: dict[float, list[float]] = {b: [] for b in buckets}
    hours: set[int] = set()
    for fc in forecasts:
        if fc.wind_u_10m is None or fc.wind_v_10m is None:
            continue
        key = _site_hour(fc.location.lat, fc.location.lon, fc.valid_at.timestamp())
        obs = observed.get(key)
        if obs is None:
            continue
        bucket = next((b for b in buckets if fc.lead_hours <= b), None)
        if bucket is None:
            continue
        fs = float(np.hypot(fc.wind_u_10m, fc.wind_v_10m))
        os_ = float(np.hypot(*obs))
        speed_err[bucket].append((os_ - fs) / max(fs, MIN_SPEED_FOR_DIRECTION))
        if fs >= MIN_SPEED_FOR_DIRECTION and os_ >= MIN_SPEED_FOR_DIRECTION:
            diff = np.arctan2(obs[1], obs[0]) - np.arctan2(fc.wind_v_10m, fc.wind_u_10m)
            dir_err[bucket].append(float(np.angle(np.exp(1j * diff))))
        hours.add(key[2])

    pair_days = (max(hours) - min(hours)) / 86400.0 if hours else 0.0
    if pair_days < min_pair_days:
        return WindUncertainty(pair_days=pair_days)
    errors = [
        LeadError(
            max_lead_hours=b,
            speed_sd=float(np.std(speed_err[b])),
            direction_sd_deg=float(np.degrees(np.std(dir_err[b]))) if dir_err[b] else 0.0,
            pairs=len(speed_err[b]),
        )
        for b in buckets
        if len(speed_err[b]) >= MIN_PAIRS_PER_BUCKET
    ]
    return WindUncertainty(by_lead=tuple(errors), pair_days=pair_days)
