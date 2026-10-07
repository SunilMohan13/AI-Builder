"""Source likelihood as weighted evidence (LLD APAC 7.6). Deterministic.

For each hazard profile enabled in a region, ``score = logistic(bias + sum(w * x))``
where each ``x`` is a signal normalised to [0, 1] from the cell's feature row
and the weights come from the profile YAML. Scores rank classes; they do not
sum to 1 and are never calibrated, because no gold label set exists.

A signal whose inputs are missing contributes nothing and is listed in the
evidence with ``value=None``, so a reader sees what was not known.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from aeropulse_contracts.likelihood import EvidenceItem, SourceLikelihoodV2, SourceScore
from aeropulse_regions.models import SEASONAL_PRIOR_SIGNAL, HazardProfile

Row = Mapping[str, float | None]

# Normalisation scales. Settings chosen so a signal saturates at a level an
# analyst would call strong; they are not fitted and are versioned with the
# method. Changing one changes the method version in the profiles.
FRP_SATURATION_MW = 500.0
TRANSPORT_SATURATION = 100.0
AEROSOL_INDEX_LOW = 1.0
AEROSOL_INDEX_HIGH = 3.0
HIGH_WIND_FROM_MS = 5.0
HIGH_WIND_FULL_MS = 10.0
LOW_WIND_BELOW_MS = 3.0
DRY_BELOW_PERCENT = 40.0
DRY_FULL_PERCENT = 10.0
PM25_DOUBLING = 1.0
POPULATION_SATURATION_PER_KM2 = 10_000.0
RUSH_HOURS_LOCAL = ((7.0, 10.0), (17.0, 21.0))


def _value(row: Row, name: str) -> float | None:
    v = row.get(name)
    if v is None:
        return None
    f = float(v)
    return None if math.isnan(f) else f


def _ramp(value: float, start: float, full: float) -> float:
    if full == start:
        return float(value >= full)
    return max(0.0, min(1.0, (value - start) / (full - start)))


def _wind_speed(row: Row) -> float | None:
    u, v = _value(row, "wind_u_now"), _value(row, "wind_v_now")
    if u is None or v is None:
        return None
    return math.hypot(u, v)


def _local_hour(row: Row) -> float | None:
    s, c = _value(row, "sin_hour_local"), _value(row, "cos_hour_local")
    if s is None or c is None:
        return None
    return (math.atan2(s, c) % (2 * math.pi)) * 24 / (2 * math.pi)


@dataclass(frozen=True)
class Signal:
    """One evidence signal: what it reads, where that comes from, how it maps."""

    name: str
    source_id: str
    unit: str | None
    #: Raw value shown in the evidence list (``None`` if unknown).
    raw: Callable[[Row], float | None]
    #: Normalised strength in [0, 1] from the raw value and the row.
    strength: Callable[[float, Row], float]


def _season_flag(row: Row) -> float:
    return float((_value(row, "is_stubble_season") or 0) or (_value(row, "is_haze_season") or 0))


def _no_fire(row: Row) -> bool | None:
    count = _value(row, "fire_count_50km_24h")
    transport = _value(row, "transport_weighted_frp")
    if count is None and transport is None:
        return None
    return (count or 0.0) == 0.0 and (transport or 0.0) == 0.0


def _pm25_ratio(row: Row) -> float | None:
    now, mean = _value(row, "pm25"), _value(row, "pm25_roll_24h")
    if now is None or mean is None or mean <= 0:
        return None
    return now / mean


def _aerosol_without_fire(row: Row) -> float | None:
    ai = _value(row, "s5p_aerosol_index")
    no_fire = _no_fire(row)
    if ai is None or no_fire is None:
        return None
    return ai if no_fire else 0.0


def _no_upwind_fire(row: Row) -> float | None:
    no_fire = _no_fire(row)
    return None if no_fire is None else float(no_fire)


SIGNALS: dict[str, Signal] = {
    s.name: s
    for s in (
        Signal(
            "fire_frp_in_season",
            "firms",
            "MW",
            lambda r: _value(r, "fire_frp_50km_24h"),
            lambda x, r: _ramp(x, 0.0, FRP_SATURATION_MW) * _season_flag(r),
        ),
        Signal(
            "fire_frp_intensity",
            "firms",
            "MW",
            lambda r: _value(r, "fire_frp_50km_24h"),
            lambda x, r: _ramp(x, 0.0, FRP_SATURATION_MW),
        ),
        Signal(
            "upwind_fire_transport",
            "firms",
            "MW (transport-weighted)",
            lambda r: _value(r, "transport_weighted_frp"),
            lambda x, r: _ramp(x, 0.0, TRANSPORT_SATURATION),
        ),
        Signal(
            "upwind_fire_frp_on_back_trajectory",
            "firms",
            "MW (transport-weighted)",
            lambda r: _value(r, "transport_weighted_frp"),
            lambda x, r: _ramp(x, 0.0, TRANSPORT_SATURATION),
        ),
        # "Anomaly" is measured against a fixed level until a per-region
        # aerosol climatology exists.
        Signal(
            "s5p_aerosol_index_anomaly",
            "earthengine",
            "index",
            lambda r: _value(r, "s5p_aerosol_index"),
            lambda x, r: _ramp(x, AEROSOL_INDEX_LOW, AEROSOL_INDEX_HIGH),
        ),
        Signal(
            "s5p_aerosol_index_without_fire",
            "earthengine",
            "index",
            _aerosol_without_fire,
            lambda x, r: _ramp(x, AEROSOL_INDEX_LOW, AEROSOL_INDEX_HIGH),
        ),
        Signal(
            "pm25_above_expected",
            "stations",
            "ratio to 24 h mean",
            _pm25_ratio,
            lambda x, r: _ramp(x, 1.0, 1.0 + PM25_DOUBLING),
        ),
        Signal(
            "high_wind",
            "openmeteo",
            "m/s",
            _wind_speed,
            lambda x, r: _ramp(x, HIGH_WIND_FROM_MS, HIGH_WIND_FULL_MS),
        ),
        Signal(
            "low_wind",
            "openmeteo",
            "m/s",
            _wind_speed,
            lambda x, r: _ramp(LOW_WIND_BELOW_MS - x, 0.0, LOW_WIND_BELOW_MS),
        ),
        Signal(
            "low_humidity",
            "openmeteo",
            "%",
            lambda r: _value(r, "humidity_now"),
            lambda x, r: _ramp(DRY_BELOW_PERCENT - x, 0.0, DRY_BELOW_PERCENT - DRY_FULL_PERCENT),
        ),
        Signal(
            "population_density",
            "population",
            "people/km2",
            lambda r: _value(r, "population_density"),
            lambda x, r: _ramp(x, 0.0, POPULATION_SATURATION_PER_KM2),
        ),
        Signal(
            "time_of_day",
            "clock",
            "local hour",
            _local_hour,
            lambda x, r: float(any(lo <= x < hi for lo, hi in RUSH_HOURS_LOCAL)),
        ),
        Signal(
            "no_upwind_fire",
            "firms",
            None,
            _no_upwind_fire,
            lambda x, r: x,
        ),
    )
}


def _seasonal(profile: HazardProfile, row: Row) -> tuple[float | None, float]:
    if profile.seasonal_prior is None:
        return None, 0.0
    flag = _value(row, profile.seasonal_prior.feature)
    return flag, (flag or 0.0)


@dataclass(frozen=True)
class ClassEvidence:
    """Score of one class with the strength of each of its signals."""

    score: SourceScore
    strengths: dict[str, float | None]
    raw: dict[str, float | None]


def score_class(profile: HazardProfile, row: Row) -> ClassEvidence | None:
    """Score one hazard class, or ``None`` if the profile carries no weights."""
    if profile.likelihood is None:
        return None
    z = profile.likelihood.bias
    strengths: dict[str, float | None] = {}
    raw: dict[str, float | None] = {}
    contributions: list[tuple[float, str]] = []
    for name, weight in profile.likelihood.weights.items():
        if name == SEASONAL_PRIOR_SIGNAL:
            value, x = _seasonal(profile, row)
        else:
            signal = SIGNALS.get(name)
            if signal is None:
                raise KeyError(f"hazard profile {profile.key!r} names unknown signal {name!r}")
            value = signal.raw(row)
            x = None if value is None else signal.strength(value, row)
        raw[name] = value
        strengths[name] = x
        if x:
            z += weight * x
            contributions.append((weight * x, name))
    score = 1.0 / (1.0 + math.exp(-z))
    contributions.sort(reverse=True)
    return ClassEvidence(
        score=SourceScore(
            source_class=profile.source_class,
            score=round(score, 6),
            contributing_signals=[n for c, n in contributions if c > 0],
        ),
        strengths=strengths,
        raw=raw,
    )


def method_version(profiles: Sequence[HazardProfile]) -> str:
    versions = sorted({p.likelihood.method_version for p in profiles if p.likelihood})
    return "+".join(versions) if versions else "none"


def rank_sources(
    profiles: Sequence[HazardProfile],
    row: Row,
    *,
    region_id: str,
    grid_id: str,
    valid_at: datetime,
    observed_at: datetime | None = None,
) -> SourceLikelihoodV2:
    """Ranked classes for one cell-hour, with the evidence behind them."""
    scored = [e for p in profiles if (e := score_class(p, row)) is not None]
    scored.sort(key=lambda e: (-e.score.score, e.score.source_class))
    evidence: dict[str, EvidenceItem] = {}
    for e in scored:
        for name, value in e.raw.items():
            if name in evidence:
                continue
            signal = SIGNALS.get(name)
            evidence[name] = EvidenceItem(
                signal=name,
                source_id=signal.source_id if signal else "region_pack",
                value=None if value is None else round(value, 6),
                unit=signal.unit if signal else None,
                observed_at=observed_at,
            )
    return SourceLikelihoodV2(
        region_id=region_id,
        grid_id=grid_id,
        valid_at=valid_at,
        method_version=method_version(profiles),
        ranking=[e.score for e in scored],
        evidence=list(evidence.values()),
    )
