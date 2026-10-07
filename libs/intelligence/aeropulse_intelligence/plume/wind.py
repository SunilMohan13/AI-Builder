"""Time-varying wind over a region's weather sites (Global LLD 7.2).

Sites are the H3 resolution-5 centroids the weather connectors sample. A
particle reads the wind by inverse distance in space and linearly in time.
Hours the input does not cover are persisted from the nearest covered hour
and reported, never filled with a guess.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

import numpy as np
from aeropulse_contracts import MeteoForecast, MeteorologicalObservation

from aeropulse_intelligence.plume.geo import Array, haversine_km

SECONDS_PER_HOUR = 3600.0
#: Setting: inverse-distance weights use ``1 / max(d, floor)^2`` so a particle
#: sitting on a site does not divide by zero.
IDW_FLOOR_KM = 0.5

Level = Literal["10m", "100m"]
LevelWeights = Mapping[Level, float]


def _epoch(moment: datetime) -> float:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return aware.timestamp()


def _hour_label(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, UTC).strftime("%Y-%m-%dT%HZ")


@dataclass(frozen=True)
class WindField:
    """Hourly wind at sites.

    Attributes:
        site_lat: ``[S]`` site latitudes.
        site_lon: ``[S]`` site longitudes.
        times: ``[T]`` valid hours, epoch seconds, ascending.
        u: ``[T, S]`` east wind (m/s) after the level blend; NaN where unknown.
        v: ``[T, S]`` north wind (m/s).
        cloud: ``[T, S]`` cloud cover (%); NaN where unknown.
        precip: ``[T, S]`` precipitation (mm/h); NaN where unknown.
        issued_at: Newest model run used, for forecast fields.
        reasons: Degraded reasons found while building the field.
    """

    site_lat: Array
    site_lon: Array
    times: Array
    u: Array
    v: Array
    cloud: Array
    precip: Array
    issued_at: datetime | None = None
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def empty(self) -> bool:
        return self.times.size == 0 or not np.isfinite(self.u).any()

    def at_time(self, t: float) -> tuple[Array, Array, Array, Array]:
        """Site values at ``t`` (linear in time, clamped to the covered hours)."""
        if t <= self.times[0]:
            return self.u[0], self.v[0], self.cloud[0], self.precip[0]
        if t >= self.times[-1]:
            return self.u[-1], self.v[-1], self.cloud[-1], self.precip[-1]
        hi = int(np.searchsorted(self.times, t, side="right"))
        lo = hi - 1
        frac = (t - self.times[lo]) / (self.times[hi] - self.times[lo])
        return tuple(  # type: ignore[return-value]
            _lerp(a[lo], a[hi], frac) for a in (self.u, self.v, self.cloud, self.precip)
        )

    def sample(self, lat: Array, lon: Array, t: float) -> tuple[Array, Array, Array, Array]:
        """``(u, v, cloud, precip)`` at particle positions; NaN where no site has a value."""
        u_s, v_s, cloud_s, precip_s = self.at_time(t)
        d = haversine_km(lat[:, None], lon[:, None], self.site_lat[None, :], self.site_lon[None, :])
        w = 1.0 / np.maximum(d, IDW_FLOOR_KM) ** 2
        return (
            _idw(w, u_s),
            _idw(w, v_s),
            _idw(w, cloud_s),
            _idw(w, precip_s),
        )


def _lerp(a: Array, b: Array, frac: float) -> Array:
    """Linear in time; where one end is unknown the other is used."""
    mixed = (1.0 - frac) * a + frac * b
    return np.where(np.isfinite(a) & np.isfinite(b), mixed, np.where(np.isfinite(a), a, b))


def _idw(w: Array, values: Array) -> Array:
    ok = np.isfinite(values)
    weights = np.where(ok[None, :], w, 0.0)
    total = weights.sum(axis=1)
    filled = np.where(ok, values, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = (weights * filled[None, :]).sum(axis=1) / total
    return np.where(total > 0, out, np.nan)


def _site(lat: float, lon: float) -> tuple[float, float]:
    return round(lat, 4), round(lon, 4)


def _coverage_reasons(times: list[float], start: float, end: float) -> list[str]:
    """Hours in ``[start, end]`` the field does not cover, as degraded reasons."""
    reasons: list[str] = []
    if not times:
        return ["no_wind_for_window"]
    first_needed = np.floor(start / SECONDS_PER_HOUR) * SECONDS_PER_HOUR
    last_needed = np.ceil(end / SECONDS_PER_HOUR) * SECONDS_PER_HOUR
    if times[-1] < last_needed:
        reasons.append(f"persisted_wind_after_{_hour_label(times[-1])}")
    if times[0] > first_needed:
        reasons.append(f"persisted_wind_before_{_hour_label(times[0])}")
    have = {round(t) for t in times}
    inside = np.arange(
        max(first_needed, times[0]), min(last_needed, times[-1]) + 1, SECONDS_PER_HOUR
    )
    gaps = [t for t in inside if round(t) not in have]
    if gaps:
        reasons.append(f"wind_missing_hours_{len(gaps)}")
    return reasons


def _assemble(
    values: Mapping[tuple[float, float], Mapping[float, tuple[float, float, float, float]]],
    reasons: list[str],
    issued_at: datetime | None,
) -> WindField:
    sites = sorted(values)
    times = sorted({t for per_site in values.values() for t in per_site})
    shape = (len(times), len(sites))
    arrays = [np.full(shape, np.nan) for _ in range(4)]
    t_index = {t: i for i, t in enumerate(times)}
    for j, site in enumerate(sites):
        for t, row in values[site].items():
            for k in range(4):
                arrays[k][t_index[t], j] = row[k]
    return WindField(
        site_lat=np.array([s[0] for s in sites], dtype=np.float64),
        site_lon=np.array([s[1] for s in sites], dtype=np.float64),
        times=np.array(times, dtype=np.float64),
        u=arrays[0],
        v=arrays[1],
        cloud=arrays[2],
        precip=arrays[3],
        issued_at=issued_at,
        reasons=tuple(reasons),
    )


def _nan(value: float | None) -> float:
    return float("nan") if value is None else float(value)


def forecast_wind(
    forecasts: Iterable[MeteoForecast],
    *,
    as_of: datetime,
    start: datetime,
    end: datetime,
    level_weights: LevelWeights,
    observed: Iterable[MeteorologicalObservation] = (),
) -> WindField:
    """Forward wind: per site and valid hour, the newest run issued by ``as_of``.

    The 10 m and 100 m winds are blended by the hazard profile's weights. A
    site-hour missing its 100 m wind uses 10 m alone and says so. Observed
    hours up to ``as_of`` fill site-hours no forecast covers (Global LLD 7.2),
    so with no forecast at all the last observed wind is persisted and the
    field carries ``persisted_wind_after_<hour>``.
    """
    w10 = float(level_weights.get("10m", 0.0))
    w100 = float(level_weights.get("100m", 0.0))
    t0, t1 = _epoch(start), _epoch(end)
    newest: dict[tuple[tuple[float, float], float], MeteoForecast] = {}
    for fc in forecasts:
        if fc.issued_at > as_of:
            continue
        t = _epoch(fc.valid_at)
        if not (t0 - SECONDS_PER_HOUR <= t <= t1 + SECONDS_PER_HOUR):
            continue
        key = (_site(fc.location.lat, fc.location.lon), t)
        held = newest.get(key)
        if held is None or fc.issued_at > held.issued_at:
            newest[key] = fc

    values: dict[tuple[float, float], dict[float, tuple[float, float, float, float]]] = {}
    single_level = 0
    for (site, t), fc in newest.items():
        u, v = fc.wind_u_10m, fc.wind_v_10m
        if u is None or v is None:
            continue
        u100, v100 = fc.wind_u_100m, fc.wind_v_100m
        if w100 > 0 and u100 is not None and v100 is not None:
            u, v = w10 * u + w100 * u100, w10 * v + w100 * v100
        elif w100 > 0:
            single_level += 1
        values.setdefault(site, {})[t] = (u, v, _nan(fc.cloud_cover), _nan(fc.precipitation))

    filled = 0
    for site, t, row in _observed_rows(observed, t0 - SECONDS_PER_HOUR, _epoch(as_of)):
        if t not in values.setdefault(site, {}):
            values[site][t] = row
            filled += 1

    times = sorted({t for per_site in values.values() for t in per_site})
    reasons = _coverage_reasons(times, t0, t1)
    if single_level:
        reasons.append("no_100m_wind_10m_used")
    if filled:
        reasons.append("observed_wind_10m_only")
    issued = max((fc.issued_at for fc in newest.values()), default=None)
    return _assemble(values, reasons, issued)


def observed_wind(
    weather: Iterable[MeteorologicalObservation],
    *,
    start: datetime,
    end: datetime,
    forecasts: Iterable[MeteoForecast] = (),
) -> WindField:
    """Backward wind from observed hours in ``[start, end]``.

    Observations carry 10 m wind only, so the profile's level blend cannot be
    applied and the field says so. Cloud cover comes from forecast rows for
    the same site-hour when present (it is not observed).
    """
    t0, t1 = _epoch(start), _epoch(end)
    cloud: dict[tuple[tuple[float, float], float], tuple[datetime, float]] = {}
    for fc in forecasts:
        if fc.cloud_cover is None:
            continue
        t = _epoch(fc.valid_at)
        if fc.valid_at > end or not (t0 - SECONDS_PER_HOUR <= t <= t1):
            continue
        key = (_site(fc.location.lat, fc.location.lon), t)
        held = cloud.get(key)
        if held is None or fc.issued_at > held[0]:
            cloud[key] = (fc.issued_at, fc.cloud_cover)

    values: dict[tuple[float, float], dict[float, tuple[float, float, float, float]]] = {}
    for site, t, (u, v, _, rain) in _observed_rows(weather, t0 - SECONDS_PER_HOUR, t1):
        c = cloud.get((site, t))
        values.setdefault(site, {})[t] = (u, v, c[1] if c is not None else float("nan"), rain)
    times = sorted({t for per_site in values.values() for t in per_site})
    reasons = [*_coverage_reasons(times, t0, t1), "observed_wind_10m_only"]
    return _assemble(values, reasons, None)


def _observed_rows(
    weather: Iterable[MeteorologicalObservation], lo: float, hi: float
) -> Iterator[tuple[tuple[float, float], float, tuple[float, float, float, float]]]:
    """``(site, hour-ending epoch, (u, v, cloud=NaN, rain))`` for wind rows in ``[lo, hi]``."""
    for wx in weather:
        if wx.wind_u is None or wx.wind_v is None:
            continue
        hour = wx.observed_at.replace(minute=0, second=0, microsecond=0)
        if wx.observed_at != hour:
            hour += timedelta(hours=1)
        t = _epoch(hour)
        if lo <= t <= hi:
            yield (
                _site(wx.location.lat, wx.location.lon),
                t,
                (wx.wind_u, wx.wind_v, float("nan"), _nan(wx.rainfall)),
            )
