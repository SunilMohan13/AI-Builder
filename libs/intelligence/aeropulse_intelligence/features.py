"""Deterministic grid-hour feature builder (LLD §15, §17)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from aeropulse_contracts.feature import FEATURE_VERSION, GridFeature
from aeropulse_contracts.raster import RasterObservation
from aeropulse_geospatial.population import population_density

from aeropulse_intelligence.geometry import (
    bearing_deg,
    cosine_alignment,
    haversine_km,
    wind_direction_from,
    wind_direction_to,
    wind_speed,
)
from aeropulse_intelligence.snapshot import FeatureSnapshot, precedence

FIRE_RADIUS_KM = 100.0
#: Shorter FIRMS rings. A single 100 km ring cannot distinguish a fire in the
#: next village from one at the edge of the domain, and the two imply very
#: different arrival times.
FIRE_RING_25_KM = 25.0
FIRE_RING_50_KM = 50.0
WEATHER_RADIUS_KM = 300.0
#: Radius for the neighbour concentration field. Matched to the 100 km
#: neighbour blend the anomaly pipeline's alert policy uses, and far wider than
#: the H3 k-ring: at resolution 8 an adjacent cell is ~1 km away, and two
#: stations are almost never that close, so a k-ring neighbour field would be
#: empty on real data.
NEIGHBOUR_RADIUS_KM = 100.0
#: Minimum cosine alignment for a neighbour to count as upwind. 0.5 is a 60°
#: half-angle: wide enough to find a neighbour in a sparse network, narrow
#: enough that a crosswind cell is not called an upwind source.
UPWIND_MIN_ALIGNMENT = 0.5
#: Reference ventilation index (m/s x m) treated as fully ventilated. 6000
#: corresponds to roughly 4 m/s through a 1500 m mixed layer, an ordinary
#: well-dispersed afternoon in the corridor. It sets the scale of
#: `stagnation_score` only; it is not a threshold anything is alerted on.
VENTILATION_REFERENCE = 6000.0
#: Meteorology older than this is not attached to a feature row. Wind and
#: boundary-layer height change materially within a few hours, so a stale
#: record would misinform advection rather than merely add noise.
WEATHER_MAX_AGE_HOURS = 3.0
#: Satellite point samples are matched to a cell within this radius. Kept tight
#: because AOD varies over short distances and a loose match would smear an
#: unrelated column into the cell.
RASTER_RADIUS_KM = 25.0


def hour_bucket(ts: datetime) -> datetime:
    """Floor a timestamp to the UTC hour."""
    aware = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    return aware.replace(minute=0, second=0, microsecond=0)


def build_features(
    grid_id: str,
    timestamp: datetime,
    snapshot: FeatureSnapshot,
    *,
    center_lat: float,
    center_lon: float,
) -> GridFeature:
    """Assemble a grid-hour feature vector from available observations.

    Industry, urban and agriculture fields stay explicit nulls: no connector
    supplies them. Satellite is populated when a raster sample matches the
    cell-hour, and population when the cell falls near a reference point.
    A null always means "not known", never "zero".

    Args:
        grid_id: H3 cell.
        timestamp: Feature timestamp (floored to hour).
        snapshot: In-scope observations.
        center_lat: Cell centroid latitude.
        center_lon: Cell centroid longitude.

    Returns:
        ``GridFeature`` with ``feature_version`` set.
    """
    ts = hour_bucket(timestamp)
    # Selection is by cell AND hour. Without the hour filter a multi-hour
    # snapshot (backfill, replay or training window) collapses to whichever
    # observation happened to be last in the list, producing a feature row that
    # is constant in time. The snapshot indexes itself so this stays O(1).
    aq = snapshot.air_quality_at(grid_id, ts)
    pollutants: dict[str, float] = {}
    station_distance: float | None = None
    quality_scores: list[float] = []
    # Sorting by precedence makes the last write the winner: a ground-station
    # reading beats a CAMS-derived model value for the same cell-hour, and the
    # newest wins within a tier. Without this the value depended on list order,
    # so an Open-Meteo site sharing an H3 cell with a CPCB station could
    # silently replace the station's measurement.
    for obs in sorted(aq, key=precedence):
        pollutants[obs.measurement.parameter] = obs.measurement.value
        dist = haversine_km(center_lat, center_lon, obs.location.lat, obs.location.lon)
        station_distance = dist if station_distance is None else min(station_distance, dist)
        quality_scores.append(obs.quality.quality_score)

    nearest_wx = _nearest_weather(center_lat, center_lon, ts, snapshot)
    wu = nearest_wx.wind_u if nearest_wx else None
    wv = nearest_wx.wind_v if nearest_wx else None
    speed = wind_speed(wu, wv) if wu is not None and wv is not None else None
    wdir_from = wind_direction_from(wu, wv) if wu is not None and wv is not None else None
    wdir_to = wind_direction_to(wu, wv) if wu is not None and wv is not None else None

    fire_distances = [
        (f, haversine_km(center_lat, center_lon, f.location.lat, f.location.lon))
        for f in snapshot.fires
    ]
    nearby_fires = [f for f, d in fire_distances if d <= FIRE_RADIUS_KM]
    fire_count = len(nearby_fires)
    fire_frp = sum(f.fire.frp for f in nearby_fires)
    fire_conf = sum(f.fire.confidence for f in nearby_fires) / fire_count if fire_count else None
    fire_count_25km = sum(1 for _, d in fire_distances if d <= FIRE_RING_25_KM)
    fire_count_50km = sum(1 for _, d in fire_distances if d <= FIRE_RING_50_KM)
    fire_frp_50km = sum(f.fire.frp for f, d in fire_distances if d <= FIRE_RING_50_KM)
    upwind = 0.0
    upwind_frp = 0.0
    if wdir_to is not None and nearby_fires:
        scores = []
        for fire in nearby_fires:
            bearing_to_cell = bearing_deg(
                fire.location.lat, fire.location.lon, center_lat, center_lon
            )
            alignment = cosine_alignment(wdir_to, bearing_to_cell)
            scores.append(alignment)
            # FRP weighted by how directly the wind carries that fire here, so
            # a large upwind fire outranks a larger crosswind one.
            upwind_frp += alignment * fire.fire.frp
        upwind = sum(scores) / len(scores)

    satellite = _nearest_raster(center_lat, center_lon, ts, snapshot)

    pm25 = pollutants.get("pm25")
    lag_1h = _lag_pm25(snapshot, grid_id, ts, hours=1)
    lag_3h = _lag_pm25(snapshot, grid_id, ts, hours=3)
    lag_6h = _lag_pm25(snapshot, grid_id, ts, hours=6)
    lag_24h = _lag_pm25(snapshot, grid_id, ts, hours=24)
    roll_6h = _roll_pm25(snapshot, grid_id, ts, hours=6)
    roll_24h = _roll_pm25(snapshot, grid_id, ts, hours=24)
    window_6h = _trailing_window(snapshot, grid_id, ts, hours=6)
    window_24h = _trailing_window(snapshot, grid_id, ts, hours=24)
    roll_max_6h = round(max(window_6h), 4) if window_6h else None
    roll_max_24h = round(max(window_24h), 4) if window_24h else None
    roll_std_24h = _stdev(window_24h)
    trend_3h = round(lag_1h - lag_3h, 4) if lag_1h is not None and lag_3h is not None else None
    trend_24h = round(lag_1h - lag_24h, 4) if lag_1h is not None and lag_24h is not None else None
    delta_1h = round(pm25 - lag_1h, 4) if pm25 is not None and lag_1h is not None else None
    pct_rank_24h = _percentile_rank(pm25, window_24h)

    ventilation = (
        round(speed * nearest_wx.boundary_layer_height, 4)
        if speed is not None and nearest_wx is not None and nearest_wx.boundary_layer_height
        else None
    )
    stagnation = _stagnation_score(ventilation)

    neighbours = _neighbour_field(grid_id, center_lat, center_lon, ts, snapshot, wdir_from)

    # Exposure weighting. Only a measured lookup populates the field: an
    # unmatched cell keeps an explicit null rather than the fallback constant,
    # so a model cannot learn from a value that is really "we don't know".
    population = population_density(center_lat, center_lon)

    nullable = [
        pollutants.get("pm25"),
        nearest_wx,
        fire_count or None,
        lag_1h,
        lag_3h,
    ]
    missing = sum(1 for v in nullable if v is None)
    sources = sum(
        [
            1 if aq else 0,
            1 if nearest_wx else 0,
            1 if nearby_fires else 0,
        ]
    )

    return GridFeature(
        grid_id=grid_id,
        timestamp=ts,
        center_lat=center_lat,
        center_lon=center_lon,
        pm25=pm25,
        pm10=pollutants.get("pm10"),
        no2=pollutants.get("no2"),
        so2=pollutants.get("so2"),
        co=pollutants.get("co"),
        o3=pollutants.get("o3"),
        station_distance=station_distance,
        aod=satellite.sample_aod if satellite else None,
        satellite_no2=satellite.sample_no2 if satellite else None,
        cloud_fraction=satellite.cloud_fraction if satellite else None,
        wind_u=wu,
        wind_v=wv,
        wind_speed=speed,
        wind_direction=wdir_from,
        temperature=nearest_wx.temperature if nearest_wx else None,
        humidity=nearest_wx.humidity if nearest_wx else None,
        pressure=nearest_wx.pressure if nearest_wx else None,
        rainfall=nearest_wx.rainfall if nearest_wx else None,
        boundary_layer_height=nearest_wx.boundary_layer_height if nearest_wx else None,
        fire_count=fire_count,
        fire_frp=fire_frp,
        fire_confidence=fire_conf,
        upwind_fire_score=round(upwind, 4),
        fire_count_25km=fire_count_25km,
        fire_count_50km=fire_count_50km,
        fire_frp_50km=round(fire_frp_50km, 4),
        upwind_fire_frp=round(upwind_frp, 4),
        pm25_lag_1h=lag_1h,
        pm25_lag_3h=lag_3h,
        pm25_lag_6h=lag_6h,
        pm25_lag_24h=lag_24h,
        pm25_roll_6h=roll_6h,
        pm25_roll_24h=roll_24h,
        pm25_roll_max_6h=roll_max_6h,
        pm25_roll_max_24h=roll_max_24h,
        pm25_roll_std_24h=roll_std_24h,
        pm25_trend_3h=trend_3h,
        pm25_trend_24h=trend_24h,
        pm25_delta_1h=delta_1h,
        pm25_pct_rank_24h=pct_rank_24h,
        ventilation_index=ventilation,
        stagnation_score=stagnation,
        neighbor_pm25_mean=neighbours.mean,
        neighbor_pm25_max=neighbours.maximum,
        neighbor_count=neighbours.count,
        upwind_pm25=neighbours.upwind,
        population=population.density_per_km2 if population.measured else None,
        quality_score=sum(quality_scores) / len(quality_scores) if quality_scores else None,
        source_count=sources,
        missing_feature_count=missing,
        feature_version=FEATURE_VERSION,
        feature_generated_at=datetime.now(UTC),
    )


def _nearest_weather(
    lat: float,
    lon: float,
    ts: datetime,
    snapshot: FeatureSnapshot,
):
    """Return the closest weather observation in space, then in time.

    Selection is time-aware: the same-hour record wins, and older records are
    only used within :data:`WEATHER_MAX_AGE_HOURS`. A time-blind nearest-station
    lookup would attach an arbitrary hour's meteorology to every feature row,
    which is invisible in a single-hour snapshot but corrupts any window.

    Args:
        lat: Cell centroid latitude.
        lon: Cell centroid longitude.
        ts: Hour-floored feature timestamp.
        snapshot: In-scope observations.

    Returns:
        The best weather observation, or None when none is close enough.
    """
    best = None
    best_key: tuple[float, float] | None = None
    for wx in snapshot.weather_within(ts, WEATHER_MAX_AGE_HOURS):
        distance = haversine_km(lat, lon, wx.location.lat, wx.location.lon)
        if distance > WEATHER_RADIUS_KM:
            continue
        age_hours = abs((hour_bucket(wx.observed_at) - ts).total_seconds()) / 3600.0
        if age_hours > WEATHER_MAX_AGE_HOURS:
            continue
        # Time proximity dominates: stale meteorology is worse than distant
        # meteorology for advection and stability features.
        key = (age_hours, distance)
        if best_key is None or key < best_key:
            best, best_key = wx, key
    return best


def _nearest_raster(
    lat: float,
    lon: float,
    ts: datetime,
    snapshot: FeatureSnapshot,
) -> RasterObservation | None:
    """Return the closest satellite sample for this cell-hour, if any.

    Matching is on the same hour bucket and on centroid proximity. Satellite
    products are sparse and cloud-limited, so an unmatched cell keeps an
    explicit null rather than borrowing a neighbouring hour's value.

    Args:
        lat: Cell centroid latitude.
        lon: Cell centroid longitude.
        ts: Hour-floored feature timestamp.
        snapshot: In-scope observations.

    Returns:
        Nearest in-hour raster sample within :data:`RASTER_RADIUS_KM`, else None.
    """
    best: RasterObservation | None = None
    best_d = RASTER_RADIUS_KM
    for raster in snapshot.rasters_at(ts):
        min_lon, min_lat, max_lon, max_lat = raster.bbox
        centre_lat = (min_lat + max_lat) / 2.0
        centre_lon = (min_lon + max_lon) / 2.0
        distance = haversine_km(lat, lon, centre_lat, centre_lon)
        if distance <= best_d:
            best, best_d = raster, distance
    return best


def _cell_pm25_history(
    snapshot: FeatureSnapshot, grid_id: str, ts: datetime
) -> dict[datetime, float]:
    """Return this cell's PM2.5 by hour bucket, strictly before ``ts``.

    Excluding the current hour keeps every derived lag and window usable at
    inference time without peeking at the value being predicted.

    Args:
        snapshot: In-scope observations.
        grid_id: H3 cell.
        ts: Hour-floored reference timestamp.

    Returns:
        Hour bucket to PM2.5 value. Later observations win within an hour.
    """
    return {
        bucket: value for bucket, value in snapshot.pm25_history(grid_id).items() if bucket < ts
    }


def _roll_pm25(snapshot: FeatureSnapshot, grid_id: str, ts: datetime, hours: int) -> float | None:
    """Mean PM2.5 over the ``hours`` buckets immediately preceding ``ts``.

    Args:
        snapshot: In-scope observations.
        grid_id: H3 cell.
        ts: Hour-floored feature timestamp, excluded from the window.
        hours: Window length in hours.

    Returns:
        Trailing mean, or ``None`` when the window holds no observation.
    """
    history = _cell_pm25_history(snapshot, grid_id, ts)
    window = [
        value for bucket, value in history.items() if ts - timedelta(hours=hours) <= bucket < ts
    ]
    if not window:
        return None
    return round(sum(window) / len(window), 4)


def _trailing_window(
    snapshot: FeatureSnapshot, grid_id: str, ts: datetime, hours: int
) -> list[float]:
    """Return this cell's PM2.5 values in the ``hours`` before ``ts``.

    Selection is by hour bucket rather than by list position. The two disagree
    whenever the series has gaps, which real station data always does, so a
    positional ``shift(n)`` here would compute a different feature from the one
    the model was trained on.

    Args:
        snapshot: In-scope observations.
        grid_id: H3 cell.
        ts: Hour-floored feature timestamp, excluded from the window.
        hours: Window length in hours.

    Returns:
        Observed values in the window, oldest first. Empty when unobserved.
    """
    history = _cell_pm25_history(snapshot, grid_id, ts)
    start = ts - timedelta(hours=hours)
    return [value for bucket, value in sorted(history.items()) if start <= bucket < ts]


def _stdev(values: list[float]) -> float | None:
    """Return the sample standard deviation, or None below two points.

    Args:
        values: Observations.

    Returns:
        Sample standard deviation rounded to 4 places, or None.
    """
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return round(math.sqrt(variance), 4)


def _percentile_rank(value: float | None, window: list[float]) -> float | None:
    """Return where ``value`` falls within ``window``, on [0, 1].

    Args:
        value: Current observation.
        window: Trailing observations to rank against.

    Returns:
        Fraction of the window at or below ``value``, or None when either
        input is missing.
    """
    if value is None or not window:
        return None
    return round(sum(1 for v in window if v <= value) / len(window), 4)


def _stagnation_score(ventilation_index: float | None) -> float | None:
    """Map a ventilation index onto a bounded stagnation score.

    Ventilation index is wind speed times mixing height; the lower it is, the
    less atmosphere there is to dilute a given emission. The score inverts it
    onto [0, 1] against a reference value so that it is comparable across
    cells and seasons rather than carrying raw units.

    Args:
        ventilation_index: Wind speed multiplied by boundary-layer height, or
            None when either input is missing.

    Returns:
        Stagnation on [0, 1] where 1 is fully stagnant, or None.
    """
    if ventilation_index is None:
        return None
    return round(
        max(0.0, min(1.0, 1.0 - ventilation_index / VENTILATION_REFERENCE)),
        4,
    )


@dataclass(frozen=True)
class _NeighbourField:
    """Summary of PM2.5 in surrounding cells at one hour."""

    mean: float | None
    maximum: float | None
    count: int
    upwind: float | None


def _neighbour_field(
    grid_id: str,
    lat: float,
    lon: float,
    ts: datetime,
    snapshot: FeatureSnapshot,
    wind_from_deg: float | None,
) -> _NeighbourField:
    """Summarise PM2.5 observed in other cells this hour.

    These are other cells' concentrations, never this cell's own, so they stay
    valid inputs to a model whose target is this cell's PM2.5 — which is the
    case the estimator exists for, a cell with no station of its own.

    Args:
        grid_id: H3 cell being built, excluded from the summary.
        lat: Cell centroid latitude.
        lon: Cell centroid longitude.
        ts: Hour-floored feature timestamp.
        snapshot: In-scope observations.
        wind_from_deg: Meteorological wind direction (the bearing the wind
            blows *from*), or None when wind is unavailable.

    Returns:
        Mean, maximum, count and the best-aligned upwind value.
    """
    values: list[float] = []
    best_upwind: tuple[float, float] | None = None
    for cell, cell_lat, cell_lon, value in snapshot.pm25_cells_at(ts):
        if cell == grid_id:
            continue
        distance = haversine_km(lat, lon, cell_lat, cell_lon)
        if distance > NEIGHBOUR_RADIUS_KM:
            continue
        values.append(value)
        if wind_from_deg is None:
            continue
        # A cell is upwind when it lies in the direction the wind comes from.
        alignment = cosine_alignment(wind_from_deg, bearing_deg(lat, lon, cell_lat, cell_lon))
        if alignment < UPWIND_MIN_ALIGNMENT:
            continue
        if best_upwind is None or alignment > best_upwind[0]:
            best_upwind = (alignment, value)

    if not values:
        return _NeighbourField(mean=None, maximum=None, count=0, upwind=None)
    return _NeighbourField(
        mean=round(sum(values) / len(values), 4),
        maximum=round(max(values), 4),
        count=len(values),
        upwind=round(best_upwind[1], 4) if best_upwind else None,
    )


def _lag_pm25(snapshot: FeatureSnapshot, grid_id: str, ts: datetime, hours: int) -> float | None:
    """Return this cell's PM2.5 exactly ``hours`` before ``ts``.

    Args:
        snapshot: In-scope observations.
        grid_id: H3 cell.
        ts: Hour-floored feature timestamp.
        hours: Lag in hours.

    Returns:
        The lagged value, or None when that hour was not observed.
    """
    return snapshot.pm25_history(grid_id).get(ts - timedelta(hours=hours))
