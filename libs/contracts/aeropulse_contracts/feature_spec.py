"""Canonical ML feature specification shared by training and serving.

This module is the single source of truth for the names, order and derivation of
every value handed to a model. Training reads its column list from here and
online inference builds its vector from here, so the two cannot drift apart.

Why this exists: the notebook track and the serving track previously each
defined their own feature names (``temperature_2m`` vs ``temperature``,
``fire_count_20km`` vs ``fire_count``), which made a trained artifact
unloadable by the worker. Import ``FeatureSet.names`` instead of writing a
feature list by hand.

Leakage safety: each :class:`FeatureSet` names its own ``target`` and asserts at
import time that the target is absent from its own feature names. A model can
therefore never be handed its own label as an input.

Name-level exclusion is not sufficient on its own. ``pm25_delta_1h`` is
``pm25 - pm25_lag_1h``: its name differs from the target, but handing it to a
model that predicts ``pm25`` reveals the answer exactly. :data:`DERIVED_FROM`
records each derived feature's upstream columns and the import-time assertion
walks that graph, so a feature computed *from* a set's target is refused as
firmly as the target itself.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime

from aeropulse_contracts.feature import GridFeature

#: Bumped to 2.0.0 when the servable feature families were added (integration
#: plan Phase 1). ``validate_feature_contract`` compares this exactly, so every
#: artifact trained against 1.0.0 is invalidated rather than reinterpreted
#: against a vector that no longer means the same thing.
ML_FEATURE_VERSION = "ml-features-2.0.0"

# Cyclical encodings are derived from the feature timestamp rather than stored on
# GridFeature: they are pure functions of it, so persisting them would create a
# second source of truth that could disagree.
_TEMPORAL_NAMES = ("sin_hour", "cos_hour", "sin_doy", "cos_doy")

#: Calendar flags. `is_stubble_season` is a crop-calendar proxy for the corridor
#: rather than a per-district ICAR join: the post-monsoon (Oct-Nov) and
#: post-rabi (Apr-May) residue windows. It is a coarse prior, not an
#: observation, and is named so that a reader is not misled into thinking a
#: crop connector supplies it.
_CALENDAR_NAMES = ("is_weekend", "is_stubble_season")

_SPATIAL_NAMES = ("center_lat", "center_lon", "station_distance")

_WEATHER_NAMES = (
    "temperature",
    "humidity",
    "pressure",
    "rainfall",
    "wind_u",
    "wind_v",
    "wind_speed",
    "boundary_layer_height",
)

_FIRE_NAMES = ("fire_count", "fire_frp", "upwind_fire_score")

#: Shorter FIRMS rings plus wind-weighted intensity. The notebooks aggregate
#: fire over several radii because a 100 km ring alone cannot separate "burning
#: next door" from "burning at the edge of the domain".
_FIRE_RING_NAMES = (
    "fire_count_25km",
    "fire_count_50km",
    "fire_frp_50km",
    "upwind_fire_frp",
)

_COPOLLUTANT_NAMES = ("pm10", "no2", "so2", "co", "o3")

_SATELLITE_NAMES = ("aod",)

#: Strictly trailing: every value is computed from hours before the feature
#: timestamp, so these are safe inputs even where pm25 at this hour is the
#: target.
_HISTORY_NAMES = (
    "pm25_lag_1h",
    "pm25_lag_3h",
    "pm25_lag_6h",
    "pm25_lag_24h",
    "pm25_roll_6h",
    "pm25_roll_24h",
)

_HISTORY_EXT_NAMES = (
    "pm25_roll_max_6h",
    "pm25_roll_max_24h",
    "pm25_roll_std_24h",
    "pm25_trend_3h",
    "pm25_trend_24h",
)

#: Reads pm25 at the feature timestamp. Forecast-only: see :data:`DERIVED_FROM`.
_CURRENT_DERIVED_NAMES = ("pm25_delta_1h", "pm25_pct_rank_24h")

#: Dispersion. Ventilation index is the standard wind x mixing-height product;
#: stagnation is its bounded inverse.
_STABILITY_NAMES = ("ventilation_index", "stagnation_score")

#: Other cells' concentrations. Legitimate for a nowcast at a cell with no
#: station, which is the question `pm25_estimator` exists to answer.
_NEIGHBOUR_NAMES = (
    "neighbor_pm25_mean",
    "neighbor_pm25_max",
    "neighbor_count",
    "upwind_pm25",
)

#: Feature -> the columns it is computed from. Used to refuse a feature whose
#: derivation chain reaches a set's own target. Only derived features appear;
#: anything absent is treated as a primitive observation.
DERIVED_FROM: dict[str, tuple[str, ...]] = {
    "pm25_delta_1h": ("pm25", "pm25_lag_1h"),
    "pm25_pct_rank_24h": ("pm25",),
}


def temporal_encodings(ts: datetime) -> dict[str, float]:
    """Return cyclical hour-of-day and day-of-year encodings.

    Sine/cosine pairs are used so that hour 23 sits adjacent to hour 0 rather
    than at the opposite end of a linear scale.

    Args:
        ts: Feature timestamp. Naive values are treated as UTC.

    Returns:
        Mapping with ``sin_hour``, ``cos_hour``, ``sin_doy`` and ``cos_doy``.
    """
    aware = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    hour_angle = 2.0 * math.pi * (aware.hour + aware.minute / 60.0) / 24.0
    doy_angle = 2.0 * math.pi * (aware.timetuple().tm_yday / 366.0)
    return {
        "sin_hour": math.sin(hour_angle),
        "cos_hour": math.cos(hour_angle),
        "sin_doy": math.sin(doy_angle),
        "cos_doy": math.cos(doy_angle),
    }


#: Months in which crop residue is burned in the Punjab-Haryana corridor:
#: October-November after the paddy harvest, April-May after wheat.
_STUBBLE_MONTHS = frozenset({4, 5, 10, 11})


def calendar_encodings(ts: datetime) -> dict[str, float]:
    """Return calendar flags derived from the feature timestamp.

    Both are pure functions of the timestamp, so they are computed here rather
    than persisted, for the same reason as :func:`temporal_encodings`.

    Args:
        ts: Feature timestamp. Naive values are treated as UTC.

    Returns:
        Mapping with ``is_weekend`` and ``is_stubble_season`` as 0.0/1.0.
    """
    aware = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    return {
        "is_weekend": 1.0 if aware.weekday() >= 5 else 0.0,
        "is_stubble_season": 1.0 if aware.month in _STUBBLE_MONTHS else 0.0,
    }


def to_feature_dict(feature: GridFeature) -> dict[str, float | None]:
    """Flatten a :class:`GridFeature` into every derivable model input.

    The returned mapping is a superset of any single model's feature set, so a
    caller may select whichever :class:`FeatureSet` it needs. ``pm25`` is
    included because it is a legitimate *input* to the forecast model (the
    current value is known at prediction time); sets that predict ``pm25``
    exclude it explicitly.

    Args:
        feature: Canonical grid-hour feature record.

    Returns:
        Feature name to value, with ``None`` preserved for genuinely missing
        inputs so that a downstream imputer can record missingness.
    """
    values: dict[str, float | None] = {
        "pm25": feature.pm25,
        "center_lat": feature.center_lat,
        "center_lon": feature.center_lon,
        "station_distance": feature.station_distance,
        "temperature": feature.temperature,
        "humidity": feature.humidity,
        "pressure": feature.pressure,
        "rainfall": feature.rainfall,
        "wind_u": feature.wind_u,
        "wind_v": feature.wind_v,
        "wind_speed": feature.wind_speed,
        "boundary_layer_height": feature.boundary_layer_height,
        "fire_count": float(feature.fire_count),
        "fire_frp": feature.fire_frp,
        "upwind_fire_score": feature.upwind_fire_score,
        "pm10": feature.pm10,
        "no2": feature.no2,
        "so2": feature.so2,
        "co": feature.co,
        "o3": feature.o3,
        "aod": feature.aod,
        "pm25_lag_1h": feature.pm25_lag_1h,
        "pm25_lag_3h": feature.pm25_lag_3h,
        "pm25_lag_6h": feature.pm25_lag_6h,
        "pm25_lag_24h": feature.pm25_lag_24h,
        "pm25_roll_6h": feature.pm25_roll_6h,
        "pm25_roll_24h": feature.pm25_roll_24h,
        "pm25_roll_max_6h": feature.pm25_roll_max_6h,
        "pm25_roll_max_24h": feature.pm25_roll_max_24h,
        "pm25_roll_std_24h": feature.pm25_roll_std_24h,
        "pm25_trend_3h": feature.pm25_trend_3h,
        "pm25_trend_24h": feature.pm25_trend_24h,
        "pm25_delta_1h": feature.pm25_delta_1h,
        "pm25_pct_rank_24h": feature.pm25_pct_rank_24h,
        "ventilation_index": feature.ventilation_index,
        "stagnation_score": feature.stagnation_score,
        "neighbor_pm25_mean": feature.neighbor_pm25_mean,
        "neighbor_pm25_max": feature.neighbor_pm25_max,
        "neighbor_count": float(feature.neighbor_count),
        "upwind_pm25": feature.upwind_pm25,
        "fire_count_25km": float(feature.fire_count_25km),
        "fire_count_50km": float(feature.fire_count_50km),
        "fire_frp_50km": feature.fire_frp_50km,
        "upwind_fire_frp": feature.upwind_fire_frp,
    }
    values.update(temporal_encodings(feature.timestamp))
    values.update(calendar_encodings(feature.timestamp))
    return values


@dataclass(frozen=True)
class FeatureSet:
    """An ordered, named feature list bound to exactly one prediction target.

    Attributes:
        name: Model family this set belongs to.
        names: Ordered feature names. Order is part of the contract because
            tree models are positional once serialised.
        target: Column this set predicts, which must not appear in ``names``.
    """

    name: str
    names: tuple[str, ...]
    target: str

    def vector(self, feature: GridFeature) -> list[float | None]:
        """Project a feature record onto this set, in contract order.

        Args:
            feature: Canonical grid-hour feature record.

        Returns:
            Values ordered to match :attr:`names`.
        """
        flat = to_feature_dict(feature)
        return [flat[n] for n in self.names]

    def row(self, feature: GridFeature) -> dict[str, float | None]:
        """Return this set's features as a mapping, for building dataframes.

        Args:
            feature: Canonical grid-hour feature record.

        Returns:
            Mapping restricted to :attr:`names`.
        """
        flat = to_feature_dict(feature)
        return {n: flat[n] for n in self.names}


#: Estimates surface PM2.5 without ever seeing it. Co-pollutants, AOD, weather
#: and fire proximity carry the signal; LLD §18.1 forbids treating AOD as a
#: direct PM2.5 substitute, so it enters only as one input among many.
PM25_ESTIMATOR = FeatureSet(
    name="pm25_estimator",
    names=_TEMPORAL_NAMES
    + _CALENDAR_NAMES
    + _SPATIAL_NAMES
    + _WEATHER_NAMES
    + _STABILITY_NAMES
    + _FIRE_NAMES
    + _FIRE_RING_NAMES
    + _COPOLLUTANT_NAMES
    + _SATELLITE_NAMES
    + _HISTORY_NAMES
    + _HISTORY_EXT_NAMES
    + _NEIGHBOUR_NAMES,
    target="pm25",
)

#: Predicts the deviation of observed PM2.5 from its seasonal/diurnal baseline.
#: The target is a residual computed against a baseline fitted on training rows
#: only, so the baseline itself is not a leakage channel.
ANOMALY_RESIDUAL = FeatureSet(
    name="anomaly_residual",
    names=_TEMPORAL_NAMES
    + _CALENDAR_NAMES
    + _SPATIAL_NAMES
    + _WEATHER_NAMES
    + _STABILITY_NAMES
    + _FIRE_NAMES
    + _FIRE_RING_NAMES
    + _COPOLLUTANT_NAMES
    + _HISTORY_NAMES
    + _HISTORY_EXT_NAMES
    + _NEIGHBOUR_NAMES,
    target="residual",
)

#: Scores independent source likelihoods. Deliberately excludes the raw
#: threshold inputs that a weak labeller would use, so the classifier cannot
#: simply re-derive its own label definition (LLD §18.3).
SOURCE_LIKELIHOOD = FeatureSet(
    name="source_likelihood",
    names=_TEMPORAL_NAMES
    + _CALENDAR_NAMES
    + _SPATIAL_NAMES
    + _WEATHER_NAMES
    + _STABILITY_NAMES
    + _SATELLITE_NAMES
    + _HISTORY_NAMES,
    target="source_label",
)

#: Corrects a persistence/advection baseline at a given horizon. Current pm25 is
#: a valid input because the target lies strictly in the future.
PROPAGATION_FORECAST = FeatureSet(
    name="propagation_forecast",
    names=(
        "pm25",
        *_TEMPORAL_NAMES,
        *_CALENDAR_NAMES,
        *_SPATIAL_NAMES,
        *_WEATHER_NAMES,
        *_STABILITY_NAMES,
        *_FIRE_NAMES,
        *_FIRE_RING_NAMES,
        *_HISTORY_NAMES,
        *_HISTORY_EXT_NAMES,
        *_CURRENT_DERIVED_NAMES,
        *_NEIGHBOUR_NAMES,
    ),
    target="residual_target",
)

#: Forecasts the maximum PM2.5 over the next 24 hours. A separate slot from
#: `propagation_forecast` because the target is an extremum rather than a point
#: value: the notebooks measured extreme bias -32.4 for the peak model against
#: -70.6 for the concentration model, so the peak target is materially better
#: for anything alert-shaped.
PM25_PEAK_24H = FeatureSet(
    name="pm25_peak_24h",
    names=PROPAGATION_FORECAST.names,
    target="pm25_peak_24h_target",
)

#: Classifies whether PM2.5 will reach the CPCB "Very Poor" threshold within 24
#: hours. Shares the peak model's inputs deliberately: the two answer the same
#: physical question, one as a magnitude and one as a probability, and giving
#: them different vectors would make their disagreements uninterpretable.
PM25_HAZARD_24H = FeatureSet(
    name="pm25_hazard_24h",
    names=PROPAGATION_FORECAST.names,
    target="hazard_extreme_24h",
)

FEATURE_SETS: dict[str, FeatureSet] = {
    fs.name: fs
    for fs in (
        PM25_ESTIMATOR,
        ANOMALY_RESIDUAL,
        SOURCE_LIKELIHOOD,
        PROPAGATION_FORECAST,
        PM25_PEAK_24H,
        PM25_HAZARD_24H,
    )
}


def _derivation_closure(name: str, _seen: frozenset[str] = frozenset()) -> frozenset[str]:
    """Return ``name`` plus every column it is transitively computed from.

    Args:
        name: Feature name to expand.
        _seen: Names already visited, guarding against a cyclic declaration.

    Returns:
        The transitive closure of ``name`` over :data:`DERIVED_FROM`.
    """
    if name in _seen:
        return _seen
    closure = _seen | {name}
    for parent in DERIVED_FROM.get(name, ()):
        closure |= _derivation_closure(parent, closure)
    return closure


def _assert_no_target_leakage() -> None:
    """Fail fast if any feature set contains, or is derived from, its target.

    Raises:
        AssertionError: If a set names its own target, names a feature computed
            from that target, or repeats a feature name.
    """
    for fs in FEATURE_SETS.values():
        if fs.target in fs.names:
            raise AssertionError(
                f"feature set {fs.name!r} leaks its target {fs.target!r} into its inputs"
            )
        if len(set(fs.names)) != len(fs.names):
            raise AssertionError(f"feature set {fs.name!r} has duplicate feature names")
        for feature_name in fs.names:
            if feature_name == fs.target:
                continue
            if fs.target in _derivation_closure(feature_name) - {feature_name}:
                raise AssertionError(
                    f"feature set {fs.name!r} includes {feature_name!r}, which is derived "
                    f"from its target {fs.target!r}"
                )


_assert_no_target_leakage()
