"""
AeroPulse anomaly detector — shared toolkit.

Implements the "Shared Feature Layer" of the AeroPulse Anomaly Model Review &
Improvement Plan (sections 10-23). Notebooks 02-09 import from here so the
feature definitions, fold semantics, baseline hierarchy, metric definitions and
alert policy are defined exactly once.

Nothing in this module reads the network. Every function is pure w.r.t. the
frames handed to it.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

EARTH_RADIUS_KM = 6371.0088

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# CPCB NAQI PM2.5 sub-index breakpoints (24h). Used for the hazard labels.
CPCB_MODERATE = 61.0
CPCB_POOR = 91.0
CPCB_VERY_POOR = 121.0
CPCB_SEVERE = 251.0

# Fire transport geometry (plan section 12).
FIRE_RADII_KM = (5, 10, 20, 50, 100, 150)
FIRE_DECAY_HOURS = (6, 12, 24, 48)
FIRE_SECTOR_COUNT = 16
FIRE_SECTOR_WIDTH = 360.0 / FIRE_SECTOR_COUNT
# Sector-resolved (wind-relative) fire aggregation is only kept at these radii —
# a full radius x sector x hour cube at every radius would not fit in memory.
FIRE_SECTOR_RADII_KM = (50, 150)

# Wind-relative classification, degrees of angular difference between the
# bearing station->fire and the direction the wind is blowing FROM.
UPWIND_MAX_DEG = 45.0
DOWNWIND_MIN_DEG = 135.0

# Regional transport radii (plan section 13).
REGIONAL_RADII_KM = (25, 50, 100)

SEASONS = {
    "winter": (12, 1, 2),
    "pre_monsoon": (3, 4, 5),
    "monsoon": (6, 7, 8, 9),
    "post_monsoon": (10, 11),
}


def season_of(month: pd.Series) -> pd.Series:
    out = pd.Series("unknown", index=month.index, dtype=object)
    for name, months in SEASONS.items():
        out[month.isin(months)] = name
    return out


def load_config(project_root: str | Path = ".") -> dict:
    """Resolve every path and threshold the anomaly notebooks share."""
    root = Path(project_root).resolve()
    pm25_root = Path(os.getenv("PM25_DATA_ROOT", "../pm25_estimator")).resolve()
    data_root = root / "data" / "anomaly"
    artifact_root = root / "artifacts" / "anomaly"
    cfg = {
        "project_root": root,
        "pm25_data_root": pm25_root,
        "pm25_processed": pm25_root / "data" / "pm25" / "processed",
        "data_root": data_root,
        "base_dir": data_root / "processed" / "base",
        "feature_dir": data_root / "processed" / "features",
        "artifact_root": artifact_root,
        "schema_version": "2.0.0",
        "very_poor_ugm3": float(os.getenv("ANOMALY_VERY_POOR_UGM3", CPCB_VERY_POOR)),
        "poor_ugm3": float(os.getenv("ANOMALY_POOR_UGM3", CPCB_POOR)),
        "severe_ugm3": float(os.getenv("ANOMALY_SEVERE_UGM3", CPCB_SEVERE)),
        "false_alert_budget": float(os.getenv("ANOMALY_FALSE_ALERT_BUDGET", "0.05")),
        "horizon_hours": int(os.getenv("ANOMALY_HORIZON_HOURS", "24")),
    }
    for key in ("base_dir", "feature_dir", "artifact_root"):
        cfg[key].mkdir(parents=True, exist_ok=True)
    return cfg


def dataset_fingerprint(frame: pd.DataFrame) -> str:
    payload = {
        "rows": int(len(frame)),
        "cols": list(frame.columns),
        "tmin": str(frame["timestamp_utc"].min()) if "timestamp_utc" in frame else None,
        "tmax": str(frame["timestamp_utc"].max()) if "timestamp_utc" in frame else None,
        "pm25_sum": float(pd.to_numeric(frame["pm25"], errors="coerce").sum())
        if "pm25" in frame
        else None,
    }
    return hashlib.sha256(json.dumps(payload, default=str).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km. Broadcasts over numpy arrays."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def bearing_deg(lat1, lon1, lat2, lon2):
    """Initial compass bearing from point 1 to point 2, degrees in [0, 360)."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlon = lon2 - lon1
    y = np.sin(dlon) * np.cos(lat2)
    x = np.cos(lat1) * np.sin(lat2) - np.sin(lat1) * np.cos(lat2) * np.cos(dlon)
    return np.degrees(np.arctan2(y, x)) % 360.0


def angular_difference_deg(a, b):
    """Smallest absolute angle between two compass bearings, in [0, 180]."""
    return np.abs((np.asarray(a) - np.asarray(b) + 180.0) % 360.0 - 180.0)


def station_geometry(stations: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Pairwise distance (km) and bearing (deg) matrices for the station list.

    ``stations`` must be indexed 0..n-1 in the canonical station order and hold
    ``lat`` / ``lon``. Element [i, j] is measured *from* station i *to* j.
    """
    lat = stations["lat"].to_numpy(dtype="float64")
    lon = stations["lon"].to_numpy(dtype="float64")
    dist = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
    brng = bearing_deg(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
    np.fill_diagonal(dist, 0.0)
    return dist, brng


# ---------------------------------------------------------------------------
# Hour grid — the axis every cube in this module shares
# ---------------------------------------------------------------------------


@dataclass
class HourGrid:
    """Maps timestamps and station ids onto integer cube coordinates."""

    start: pd.Timestamp
    end: pd.Timestamp
    station_ids: np.ndarray
    _station_pos: dict = field(default_factory=dict, repr=False)

    @classmethod
    def build(cls, timestamps: pd.Series, station_ids) -> "HourGrid":
        ts = pd.to_datetime(timestamps, utc=True)
        ids = np.asarray(sorted(pd.unique(station_ids)))
        grid = cls(
            start=ts.min().floor("h"),
            end=ts.max().ceil("h"),
            station_ids=ids,
        )
        grid._station_pos = {sid: i for i, sid in enumerate(ids)}
        return grid

    @property
    def n_hours(self) -> int:
        return int((self.end - self.start) / pd.Timedelta(hours=1)) + 1

    @property
    def n_stations(self) -> int:
        return len(self.station_ids)

    def hour_index(self, timestamps) -> np.ndarray:
        ts = pd.to_datetime(pd.Series(timestamps), utc=True).dt.floor("h")
        return ((ts - self.start) / pd.Timedelta(hours=1)).to_numpy(dtype="int64")

    def station_index(self, station_ids) -> np.ndarray:
        return pd.Series(station_ids).map(self._station_pos).to_numpy(dtype="float64")


def trailing_sum(cube: np.ndarray, window: int, axis: int = 1) -> np.ndarray:
    """Inclusive trailing-window sum along ``axis`` (the hour axis).

    Element [.., t, ..] is the sum over hours (t - window, t]. Uses a cumulative
    sum so cost is independent of window length. Never reaches forward in time.
    """
    csum = np.cumsum(cube, axis=axis, dtype="float64")
    shifted = np.zeros_like(csum)
    sl_dst = [slice(None)] * csum.ndim
    sl_src = [slice(None)] * csum.ndim
    sl_dst[axis] = slice(window, None)
    sl_src[axis] = slice(None, -window)
    shifted[tuple(sl_dst)] = csum[tuple(sl_src)]
    return (csum - shifted).astype("float32")


# ---------------------------------------------------------------------------
# Fire transport features (plan section 12)
# ---------------------------------------------------------------------------


def build_fire_transport_cubes(
    fires: pd.DataFrame,
    stations: pd.DataFrame,
    grid: HourGrid,
    radii_km: tuple = FIRE_RADII_KM,
    sector_radii_km: tuple = FIRE_SECTOR_RADII_KM,
) -> dict:
    """Aggregate raw FIRMS detections into station x hour fire cubes.

    Returns dense cubes rather than a row-per-fire join because 1.7M detections
    x 149 stations is a many-to-many that only stays cheap once collapsed onto
    the (station, hour) grid.

    Cubes returned:
      ``count[radius]``      (station, hour) detections in that radius, that hour
      ``frp[radius]``        (station, hour) summed FRP
      ``frp_max[radius]``    (station, hour) max single-detection FRP
      ``inv_dist_frp[r]``    (station, hour) sum of FRP / max(distance, 1 km)
      ``min_dist[radius]``   (station, hour) nearest detection distance
      ``sector_frp[radius]`` (station, hour, 16) FRP by bearing sector
    """
    fires = fires.dropna(subset=["fire_lat", "fire_lon", "timestamp_utc"]).copy()
    fires["timestamp_utc"] = pd.to_datetime(fires["timestamp_utc"], utc=True)
    frp = pd.to_numeric(fires.get("frp"), errors="coerce").fillna(0.0).to_numpy("float64")

    f_hour = grid.hour_index(fires["timestamp_utc"])
    in_span = (f_hour >= 0) & (f_hour < grid.n_hours)
    fires, frp, f_hour = fires[in_span], frp[in_span], f_hour[in_span]

    f_lat = fires["fire_lat"].to_numpy("float64")
    f_lon = fires["fire_lon"].to_numpy("float64")
    s_lat = stations["lat"].to_numpy("float64")
    s_lon = stations["lon"].to_numpy("float64")

    max_radius = float(max(radii_km))
    n_s, n_h = grid.n_stations, grid.n_hours

    cubes = {
        "count": {r: np.zeros((n_s, n_h), "float32") for r in radii_km},
        "frp": {r: np.zeros((n_s, n_h), "float32") for r in radii_km},
        "frp_max": {r: np.zeros((n_s, n_h), "float32") for r in radii_km},
        "inv_dist_frp": {r: np.zeros((n_s, n_h), "float32") for r in radii_km},
        "min_dist": {r: np.full((n_s, n_h), np.nan, "float32") for r in radii_km},
        "sector_frp": {
            r: np.zeros((n_s, n_h, FIRE_SECTOR_COUNT), "float32") for r in sector_radii_km
        },
    }

    # One station at a time: a 1.7M-element distance vector is cheap, while the
    # full 1.7M x 149 cross product is not.
    for si in range(n_s):
        dist = haversine_km(s_lat[si], s_lon[si], f_lat, f_lon)
        near = dist <= max_radius
        if not near.any():
            continue
        d_near = dist[near]
        h_near = f_hour[near]
        frp_near = frp[near]
        brg = bearing_deg(s_lat[si], s_lon[si], f_lat[near], f_lon[near])
        sector = np.floor(brg / FIRE_SECTOR_WIDTH).astype("int64") % FIRE_SECTOR_COUNT

        for r in radii_km:
            m = d_near <= r
            if not m.any():
                continue
            h_r, frp_r, d_r = h_near[m], frp_near[m], d_near[m]
            cubes["count"][r][si] = np.bincount(h_r, minlength=n_h)
            cubes["frp"][r][si] = np.bincount(h_r, weights=frp_r, minlength=n_h)
            cubes["inv_dist_frp"][r][si] = np.bincount(
                h_r, weights=frp_r / np.maximum(d_r, 1.0), minlength=n_h
            )
            mx = np.zeros(n_h, "float64")
            np.maximum.at(mx, h_r, frp_r)
            cubes["frp_max"][r][si] = mx
            mn = np.full(n_h, np.inf)
            np.minimum.at(mn, h_r, d_r)
            mn[np.isinf(mn)] = np.nan
            cubes["min_dist"][r][si] = mn

            if r in sector_radii_km:
                flat = np.bincount(
                    h_r * FIRE_SECTOR_COUNT + sector[m],
                    weights=frp_r,
                    minlength=n_h * FIRE_SECTOR_COUNT,
                )
                cubes["sector_frp"][r][si] = flat.reshape(n_h, FIRE_SECTOR_COUNT)

    return cubes


def fire_features_for_rows(
    cubes: dict,
    grid: HourGrid,
    row_station_idx: np.ndarray,
    row_hour_idx: np.ndarray,
    wind_direction_deg: np.ndarray,
    radii_km: tuple = FIRE_RADII_KM,
    decay_hours: tuple = FIRE_DECAY_HOURS,
    sector_radii_km: tuple = FIRE_SECTOR_RADII_KM,
) -> pd.DataFrame:
    """Project the fire cubes onto observation rows, wind-relative.

    ``wind_direction_deg`` is the meteorological direction the wind blows FROM,
    so a fire whose bearing from the station matches the wind direction sits
    upwind and its smoke is heading toward the station.
    """
    out = {}
    valid = (row_station_idx >= 0) & (row_hour_idx >= 0) & (row_hour_idx < grid.n_hours)
    si = np.where(valid, row_station_idx, 0).astype("int64")
    hi = np.where(valid, row_hour_idx, 0).astype("int64")

    def take(cube_2d):
        vals = cube_2d[si, hi]
        return np.where(valid, vals, np.nan)

    for r in radii_km:
        out[f"fire_count_{r}km_1h"] = take(cubes["count"][r])
        out[f"fire_frp_{r}km_1h"] = take(cubes["frp"][r])
        out[f"fire_frp_max_{r}km_1h"] = take(cubes["frp_max"][r])
        out[f"fire_invdist_frp_{r}km_1h"] = take(cubes["inv_dist_frp"][r])
        out[f"fire_min_dist_{r}km"] = take(cubes["min_dist"][r])
        for w in decay_hours:
            out[f"fire_count_{r}km_{w}h"] = take(trailing_sum(cubes["count"][r], w))
            out[f"fire_frp_{r}km_{w}h"] = take(trailing_sum(cubes["frp"][r], w))
            out[f"fire_invdist_frp_{r}km_{w}h"] = take(
                trailing_sum(cubes["inv_dist_frp"][r], w)
            )

    # Wind-relative split. Sector centres are fixed, so the angular difference
    # against the row's wind direction is a 16-column broadcast.
    centres = (np.arange(FIRE_SECTOR_COUNT) + 0.5) * FIRE_SECTOR_WIDTH
    wd = np.asarray(wind_direction_deg, dtype="float64")
    angdiff = angular_difference_deg(centres[None, :], wd[:, None])
    up_mask = (angdiff <= UPWIND_MAX_DEG).astype("float32")
    down_mask = (angdiff >= DOWNWIND_MIN_DEG).astype("float32")
    cross_mask = 1.0 - up_mask - down_mask
    wind_known = np.isfinite(wd)

    for r in sector_radii_km:
        for w in decay_hours:
            cube = trailing_sum(cubes["sector_frp"][r], w, axis=1)
            sect = np.where(valid[:, None], cube[si, hi, :], np.nan)
            for label, mask in (
                ("upwind", up_mask),
                ("crosswind", cross_mask),
                ("downwind", down_mask),
            ):
                vals = np.nansum(sect * mask, axis=1)
                out[f"fire_{label}_frp_{r}km_{w}h"] = np.where(
                    valid & wind_known, vals, np.nan
                )
            total = np.nansum(sect, axis=1)
            with np.errstate(invalid="ignore", divide="ignore"):
                ratio = np.nansum(sect * up_mask, axis=1) / np.where(total > 0, total, np.nan)
            out[f"fire_upwind_share_{r}km_{w}h"] = np.where(valid & wind_known, ratio, np.nan)

    return pd.DataFrame({k: v.astype("float32") for k, v in out.items()})


# ---------------------------------------------------------------------------
# Regional / upwind PM2.5 transport (plan section 13)
# ---------------------------------------------------------------------------


def build_regional_pm25_features(
    df: pd.DataFrame,
    stations: pd.DataFrame,
    grid: HourGrid,
    radii_km: tuple = REGIONAL_RADII_KM,
    upwind_radius_km: float = 150.0,
) -> pd.DataFrame:
    """Neighbour-station PM2.5 context, including a wind-relative upwind mean.

    Every value is concurrent (hour t) rather than future, so it is available at
    prediction time. The station's own reading is always excluded from its own
    regional aggregate.
    """
    dist, brng = station_geometry(stations)
    n_s, n_h = grid.n_stations, grid.n_hours

    si = grid.station_index(df["location_id"]).astype("float64")
    hi = grid.hour_index(df["timestamp_utc"])
    ok = np.isfinite(si) & (hi >= 0) & (hi < n_h)
    si_i = np.where(ok, np.nan_to_num(si), 0).astype("int64")
    hi_i = np.where(ok, hi, 0).astype("int64")

    # Dense (station, hour) PM2.5 panel; NaN where a station did not report.
    panel = np.full((n_s, n_h), np.nan, "float32")
    panel[si_i[ok], hi_i[ok]] = df.loc[ok, "pm25"].to_numpy("float32")
    wind_panel = np.full((n_s, n_h), np.nan, "float32")
    if "wind_direction_10m" in df.columns:
        wind_panel[si_i[ok], hi_i[ok]] = df.loc[ok, "wind_direction_10m"].to_numpy("float32")

    present = np.isfinite(panel)
    filled = np.where(present, panel, 0.0).astype("float64")
    counts = present.astype("float64")

    out = {}
    for r in radii_km:
        w = ((dist <= r) & (dist > 0)).astype("float64")  # exclude self
        tot = w @ filled
        cnt = w @ counts
        mean = np.divide(tot, cnt, out=np.full_like(tot, np.nan), where=cnt > 0)
        sq = w @ np.where(present, filled**2, 0.0)
        var = np.divide(sq, cnt, out=np.full_like(sq, np.nan), where=cnt > 0) - mean**2
        std = np.sqrt(np.clip(var, 0.0, None))
        mx = np.full((n_s, n_h), np.nan)
        for i in range(n_s):
            nb = np.flatnonzero(w[i])
            if nb.size:
                mx[i] = np.nanmax(panel[nb], axis=0)
        out[f"regional_pm25_mean_{r}km"] = mean[si_i, hi_i]
        out[f"regional_pm25_std_{r}km"] = std[si_i, hi_i]
        out[f"regional_pm25_max_{r}km"] = mx[si_i, hi_i]
        out[f"regional_pm25_count_{r}km"] = cnt[si_i, hi_i]
        with np.errstate(invalid="ignore"):
            out[f"regional_pm25_gradient_{r}km"] = panel[si_i, hi_i] - mean[si_i, hi_i]

    # Upwind neighbours: bearing station->neighbour close to the wind's origin.
    up_mean = np.full((n_s, n_h), np.nan)
    up_max = np.full((n_s, n_h), np.nan)
    for i in range(n_s):
        nb = np.flatnonzero((dist[i] <= upwind_radius_km) & (dist[i] > 0))
        if nb.size == 0:
            continue
        ang = angular_difference_deg(brng[i, nb][:, None], wind_panel[i][None, :])
        mask = (ang <= UPWIND_MAX_DEG) & np.isfinite(ang) & present[nb]
        vals = np.where(mask, np.nan_to_num(panel[nb]), 0.0)
        cnt = mask.sum(axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            up_mean[i] = np.where(cnt > 0, vals.sum(axis=0) / np.maximum(cnt, 1), np.nan)
        masked = np.where(mask, panel[nb], np.nan)
        with np.errstate(invalid="ignore"):
            up_max[i] = np.nanmax(masked, axis=0) if nb.size else np.nan

    out["upwind_pm25_mean"] = up_mean[si_i, hi_i]
    out["upwind_pm25_max"] = up_max[si_i, hi_i]
    out["upwind_pm25_gradient"] = panel[si_i, hi_i] - up_mean[si_i, hi_i]

    frame = pd.DataFrame(
        {k: np.where(ok, v, np.nan).astype("float32") for k, v in out.items()},
        index=df.index,
    )
    return frame


# ---------------------------------------------------------------------------
# Hierarchical baseline (plan sections 5 and 23)
# ---------------------------------------------------------------------------


@dataclass
class HierarchicalBaseline:
    """Expected PM2.5 by station x hour-of-week, degrading gracefully.

    Resolution order for a query location:
      1. the station's own hour-of-week median (needs training history)
      2. inverse-distance weighted median of nearby *trained* stations
      3. regional (IGP / non-IGP) hour-of-week median
      4. national hour-of-week median

    Level 2 is what the flat ``location_id`` baseline lacked: it is the only
    reason a station absent from training gets anything better than a national
    average.
    """

    neighbour_radius_km: float = 150.0
    max_neighbours: int = 8
    min_rows_per_key: int = 5
    # Distance at which a neighbour estimate is trusted 50/50 against the
    # regional climatology. Set to None to use strict precedence instead.
    shrink_half_distance_km: float | None = 25.0

    station_table: pd.DataFrame | None = None
    regional_table: pd.DataFrame | None = None
    national_table: pd.DataFrame | None = None
    geometry: pd.DataFrame | None = None
    global_median: float = np.nan
    global_mad: float = np.nan

    def fit(self, train: pd.DataFrame, geometry: pd.DataFrame) -> "HierarchicalBaseline":
        """Fit on training rows only. ``geometry`` may cover unseen stations."""
        agg = (
            train.groupby(["location_id", "hour_of_week"])["pm25"]
            .agg(["median", "count", lambda s: (s - s.median()).abs().median()])
            .rename(columns={"median": "baseline_pm25", "count": "n", "<lambda_0>": "mad"})
            .reset_index()
        )
        self.station_table = agg[agg["n"] >= self.min_rows_per_key].copy()

        # The caller's frame may already carry region_key (notebook 02 merges the
        # geography in). Merging again would produce region_key_x / region_key_y
        # and the groupby below would fail on a name that no longer exists.
        region = train.drop(columns=["region_key"], errors="ignore").merge(
            geometry[["location_id", "region_key"]], on="location_id", how="left"
        )
        self.regional_table = (
            region.groupby(["region_key", "hour_of_week"])["pm25"]
            .agg(["median", lambda s: (s - s.median()).abs().median()])
            .rename(columns={"median": "region_pm25", "<lambda_0>": "region_mad"})
            .reset_index()
        )
        self.national_table = (
            train.groupby("hour_of_week")["pm25"]
            .agg(["median", lambda s: (s - s.median()).abs().median()])
            .rename(columns={"median": "national_pm25", "<lambda_0>": "national_mad"})
            .reset_index()
        )
        self.geometry = geometry.copy()
        self.global_median = float(train["pm25"].median())
        self.global_mad = float((train["pm25"] - self.global_median).abs().median())
        return self

    def _neighbour_table(self) -> pd.DataFrame:
        """Level-2 table: IDW blend of trained stations, for every location."""
        trained_ids = self.station_table["location_id"].unique()
        geom = self.geometry.set_index("location_id")
        trained = geom.reindex(trained_ids).dropna(subset=["lat", "lon"])
        if trained.empty:
            return pd.DataFrame(
                columns=["location_id", "hour_of_week", "neighbour_pm25", "neighbour_km"])

        wide = self.station_table.pivot_table(
            index="location_id", columns="hour_of_week", values="baseline_pm25"
        ).reindex(trained.index)
        vals = wide.to_numpy("float64")
        present = np.isfinite(vals)
        vals0 = np.where(present, vals, 0.0)

        t_lat = trained["lat"].to_numpy("float64")
        t_lon = trained["lon"].to_numpy("float64")
        rows = []
        for loc, row in geom.iterrows():
            d = haversine_km(row["lat"], row["lon"], t_lat, t_lon)
            # Exclude the station itself so this stays a true spatial fallback.
            cand = np.flatnonzero((d <= self.neighbour_radius_km) & (d > 1e-6))
            if cand.size == 0:
                continue
            cand = cand[np.argsort(d[cand])[: self.max_neighbours]]
            w = (1.0 / np.maximum(d[cand], 1.0) ** 2)[:, None]
            num = (vals0[cand] * w * present[cand]).sum(axis=0)
            den = (w * present[cand]).sum(axis=0)
            blended = np.divide(num, den, out=np.full_like(num, np.nan), where=den > 0)
            rows.append(
                pd.DataFrame(
                    {
                        "location_id": loc,
                        "hour_of_week": wide.columns.to_numpy(),
                        "neighbour_pm25": blended,
                        "neighbour_km": float(d[cand].min()),
                    }
                )
            )
        if not rows:
            return pd.DataFrame(
                columns=["location_id", "hour_of_week", "neighbour_pm25", "neighbour_km"])
        return pd.concat(rows, ignore_index=True).dropna(subset=["neighbour_pm25"])

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Attach ``baseline_pm25``, ``baseline_mad`` and ``baseline_level``."""
        out = frame[["location_id", "hour_of_week"]].copy()
        out = out.merge(self.station_table.drop(columns=["n"]), how="left",
                        on=["location_id", "hour_of_week"])
        out = out.merge(self._neighbour_table(), how="left",
                        on=["location_id", "hour_of_week"])
        out = out.drop(columns=["region_key"], errors="ignore").merge(
            self.geometry[["location_id", "region_key"]], how="left", on="location_id")
        out = out.merge(self.regional_table, how="left", on=["region_key", "hour_of_week"])
        out = out.merge(self.national_table, how="left", on="hour_of_week")

        level = pd.Series("global", index=out.index, dtype=object)
        value = pd.Series(self.global_median, index=out.index, dtype="float64")
        mad = pd.Series(self.global_mad, index=out.index, dtype="float64")

        for src_val, src_mad, name in (
            ("national_pm25", "national_mad", "national"),
            ("region_pm25", "region_mad", "region"),
            ("neighbour_pm25", None, "neighbour"),
            ("baseline_pm25", "mad", "station"),
        ):
            m = out[src_val].notna()
            value[m] = out.loc[m, src_val]
            level[m] = name
            if src_mad is not None:
                mad[m] = out.loc[m, src_mad]

        # Distance shrinkage. Strict precedence trusts a neighbour 300 km away
        # as much as one 5 km away, which measurably hurts on a geographic-block
        # holdout where the surviving neighbours sit in a different pollution
        # regime. Shrink the neighbour estimate toward the regional (else
        # national) climatology as the nearest contributing station recedes:
        #   w = 1 / (1 + (d / d_half)^2)
        # so w = 1 at zero distance and 0.5 at d_half.
        if self.shrink_half_distance_km:
            is_nb = (level == "neighbour").to_numpy()
            if is_nb.any():
                d = out["neighbour_km"].to_numpy("float64")
                w = 1.0 / (1.0 + (d / float(self.shrink_half_distance_km)) ** 2)
                prior = out["region_pm25"].fillna(out["national_pm25"]).fillna(
                    self.global_median).to_numpy("float64")
                nb = out["neighbour_pm25"].to_numpy("float64")
                blended = w * nb + (1.0 - w) * prior
                value[is_nb] = blended[is_nb]
                level[is_nb] = np.where(w[is_nb] >= 0.5, "neighbour", "neighbour_shrunk")

        result = pd.DataFrame(
            {
                "baseline_pm25": value.to_numpy("float32"),
                "baseline_mad": np.maximum(mad.to_numpy("float64"), 1.0).astype("float32"),
                "baseline_level": pd.Categorical(
                    level,
                    categories=["station", "neighbour", "neighbour_shrunk",
                                "region", "national", "global"],
                ),
                "baseline_neighbour_km": out["neighbour_km"].to_numpy("float32"),
            },
            index=frame.index,
        )
        return result


def build_region_key(
    geometry: pd.DataFrame, block_deg: float = 2.0, region_deg: float = 5.0
) -> pd.DataFrame:
    """Two spatial groupings at different scales.

    ``geo_block`` (default 2 degrees) is the *holdout* unit — small enough that
    dropping one removes a city cluster without gutting the training set.

    ``region_key`` (default 5 degrees, crossed with the Indo-Gangetic Plain
    flag) is the hierarchical baseline's level-3 group. It must be coarser than
    the holdout unit: if the two match, holding out a block also removes its
    entire region and the level can never fire.
    """
    g = geometry.copy()
    igp = g["is_indo_gangetic_plain"].fillna(0).astype(int) if "is_indo_gangetic_plain" in g else 0
    blk = lambda d: ((g["lat"] / d).apply(np.floor).astype(int).astype(str) + "_"
                     + (g["lon"] / d).apply(np.floor).astype(int).astype(str))
    g["geo_block"] = blk(block_deg)
    g["region_key"] = np.where(igp == 1, "IGP_", "OTH_") + blk(region_deg)
    return g


# ---------------------------------------------------------------------------
# Evaluation (plan sections 18, 19, 33)
# ---------------------------------------------------------------------------


def regression_metrics(y_true, y_pred) -> dict:
    y_true = np.asarray(y_true, dtype="float64")
    y_pred = np.asarray(y_pred, dtype="float64")
    m = np.isfinite(y_true) & np.isfinite(y_pred)
    if m.sum() == 0:
        return {"n": 0, "mae": np.nan, "rmse": np.nan, "r2": np.nan, "bias": np.nan}
    yt, yp = y_true[m], y_pred[m]
    err = yp - yt
    ss_res = float((err**2).sum())
    ss_tot = float(((yt - yt.mean()) ** 2).sum())
    return {
        "n": int(m.sum()),
        "mae": float(np.abs(err).mean()),
        "rmse": float(np.sqrt((err**2).mean())),
        "r2": float(1.0 - ss_res / ss_tot) if ss_tot > 0 else np.nan,
        "bias": float(err.mean()),
    }


def classification_metrics(y_true, y_score, threshold: float) -> dict:
    """Point metrics at one operating threshold, plus the ranking metrics."""
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

    y_true = np.asarray(y_true).astype(int)
    y_score = np.asarray(y_score, dtype="float64")
    m = np.isfinite(y_score)
    y_true, y_score = y_true[m], y_score[m]
    pred = (y_score >= threshold).astype(int)

    tp = int(((pred == 1) & (y_true == 1)).sum())
    fp = int(((pred == 1) & (y_true == 0)).sum())
    fn = int(((pred == 0) & (y_true == 1)).sum())
    tn = int(((pred == 0) & (y_true == 0)).sum())

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    out = {
        "n": int(len(y_true)),
        "positives": int(y_true.sum()),
        "prevalence": float(y_true.mean()) if len(y_true) else np.nan,
        "threshold": float(threshold),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_alert_rate": fp / (fp + tn) if (fp + tn) else 0.0,
        "alerts": tp + fp,
    }
    if 0 < y_true.sum() < len(y_true):
        out["pr_auc"] = float(average_precision_score(y_true, y_score))
        out["roc_auc"] = float(roc_auc_score(y_true, y_score))
        if y_score.min() >= 0.0 and y_score.max() <= 1.0:
            out["brier"] = float(brier_score_loss(y_true, y_score))
    else:
        out["pr_auc"] = np.nan
        out["roc_auc"] = np.nan
    return out


def alerts_per_day(y_score, timestamps, threshold: float) -> float:
    ts = pd.to_datetime(pd.Series(timestamps), utc=True)
    fired = np.asarray(y_score, dtype="float64") >= threshold
    days = max((ts.max() - ts.min()) / pd.Timedelta(days=1), 1e-9)
    return float(fired.sum() / days)


def threshold_sweep(y_true, y_score, max_points: int = 500) -> pd.DataFrame:
    """Exact precision/recall/FAR at every distinct score, thinned to a table.

    Sorting once and taking cumulative sums gives the metric at *every*
    achievable operating point in one pass. A quantile grid would be both
    slower and blind in the tail, which is exactly where a low-prevalence
    alerting threshold sits.
    """
    y_true = np.asarray(y_true).astype(int)
    y_score = np.asarray(y_score, dtype="float64")
    m = np.isfinite(y_score)
    y_true, y_score = y_true[m], y_score[m]
    if len(y_true) == 0 or y_true.sum() in (0, len(y_true)):
        return pd.DataFrame(columns=["threshold", "precision", "recall", "f1",
                                     "false_alert_rate", "alerts"])

    order = np.argsort(-y_score, kind="mergesort")
    ys, ss = y_true[order], y_score[order]
    tp = np.cumsum(ys)
    fp = np.cumsum(1 - ys)
    P, N = int(y_true.sum()), int(len(y_true) - y_true.sum())

    # Keep only the last index of each run of equal scores: a threshold cannot
    # split tied predictions, so intermediate cut points are not achievable.
    keep = np.r_[np.flatnonzero(np.diff(ss) != 0), len(ss) - 1]
    if len(keep) > max_points:
        keep = keep[np.unique(np.linspace(0, len(keep) - 1, max_points).astype(int))]

    prec = tp[keep] / np.maximum(tp[keep] + fp[keep], 1)
    rec = tp[keep] / max(P, 1)
    far = fp[keep] / max(N, 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        f1 = np.where(prec + rec > 0, 2 * prec * rec / (prec + rec), 0.0)
    return pd.DataFrame({
        "threshold": ss[keep], "precision": prec, "recall": rec, "f1": f1,
        "false_alert_rate": far, "alerts": (tp[keep] + fp[keep]).astype(int),
        "tp": tp[keep].astype(int), "fp": fp[keep].astype(int),
    })


def choose_threshold(
    y_true,
    y_score,
    budget_false_alert_rate: float | None = None,
    objective: str = "f1",
    n_points: int = 500,
) -> tuple[float, pd.DataFrame]:
    """Sweep thresholds and pick one. Always call this on validation, not test.

    With ``budget_false_alert_rate`` set, pick the highest-recall threshold
    that stays inside the budget. Otherwise maximise ``objective``.

    Note that a threshold hitting the budget exactly on validation will not
    hit it on a slice with different prevalence — see notebook 09.
    """
    sweep = threshold_sweep(y_true, y_score, max_points=n_points)
    if sweep.empty:
        return float("inf"), sweep
    if budget_false_alert_rate is not None:
        ok = sweep[sweep["false_alert_rate"] <= budget_false_alert_rate]
        pick = (ok if len(ok) else sweep).sort_values("recall", ascending=False).head(1)
    else:
        pick = sweep.sort_values(objective, ascending=False).head(1)
    return float(pick["threshold"].iloc[0]), sweep


def _to_ns(values) -> np.ndarray:
    """Datetime-like -> int64 nanoseconds since epoch, UTC.

    pandas 3 stores tz-aware columns as datetime64[us], so a bare
    ``.astype("int64")`` yields MICROseconds while ``Timestamp.value`` yields
    NANOseconds. Mixing the two silently makes every comparison false, so every
    time axis in this module goes through here.
    """
    idx = pd.DatetimeIndex(pd.to_datetime(pd.Series(values), utc=True))
    return idx.tz_convert("UTC").tz_localize(None).values.astype("datetime64[ns]").astype("int64")


def build_events(
    df: pd.DataFrame,
    threshold: float,
    min_hours: int = 3,
    max_gap_hours: int = 6,
    value_col: str = "pm25",
) -> pd.DataFrame:
    """Group consecutive exceedance hours per station into pollution episodes.

    Row-level recall hides whether a detector found an *episode* at all, which
    is what plan section 18 asks for.
    """
    frames = []
    for loc, g in df.sort_values(["location_id", "timestamp_utc"]).groupby(
        "location_id", sort=False
    ):
        over = (g[value_col] >= threshold).to_numpy()
        if not over.any():
            continue
        ts_ns = _to_ns(g["timestamp_utc"])
        idx = np.flatnonzero(over)
        gap = (np.diff(ts_ns[idx]) / 3.6e12).astype(int)
        breaks = np.flatnonzero(gap > max_gap_hours)
        starts = np.concatenate([[0], breaks + 1])
        ends = np.concatenate([breaks, [len(idx) - 1]])
        for s, e in zip(starts, ends):
            seg = g.iloc[idx[s] : idx[e] + 1]
            if len(seg) < min_hours:
                continue
            frames.append(
                {
                    "location_id": loc,
                    "event_start": seg["timestamp_utc"].iloc[0],
                    "event_end": seg["timestamp_utc"].iloc[-1],
                    "event_peak": float(seg[value_col].max()),
                    "event_mean": float(seg[value_col].mean()),
                    "duration_hours": int(len(seg)),
                }
            )
    return pd.DataFrame(frames)


def event_level_metrics(
    events: pd.DataFrame,
    predictions: pd.DataFrame,
    score_col: str,
    threshold: float,
    lead_window_hours: int = 48,
) -> dict:
    """Episode detection rate and lead time.

    An episode counts as detected if the score crosses ``threshold`` at any hour
    in [start - lead_window, end]. Lead time is measured from the first such
    crossing to the episode start; a crossing after onset gives lead time 0.
    """
    if events.empty:
        return {"events": 0, "detected": 0, "detection_rate": np.nan}

    preds = predictions.sort_values(["location_id", "timestamp_utc"])
    fired = preds[preds[score_col] >= threshold]
    # Compare in integer nanoseconds: a tz-aware Series .to_numpy() yields an
    # object array of Timestamps, which will not compare against datetime64.
    by_loc = {loc: _to_ns(g["timestamp_utc"]) for loc, g in fired.groupby("location_id")}

    ev_start = _to_ns(events["event_start"])
    ev_end = _to_ns(events["event_end"])
    lead_ns = int(lead_window_hours * 3.6e12)
    NS_PER_HOUR = 3.6e12

    leads, detected = [], 0
    for pos, (_, ev) in enumerate(events.iterrows()):
        hits = by_loc.get(ev["location_id"])
        if hits is None or len(hits) == 0:
            continue
        window = hits[(hits >= ev_start[pos] - lead_ns) & (hits <= ev_end[pos])]
        if window.size == 0:
            continue
        detected += 1
        leads.append(max((ev_start[pos] - int(window.min())) / NS_PER_HOUR, 0.0))

    span_days = max(
        (preds["timestamp_utc"].max() - preds["timestamp_utc"].min()) / pd.Timedelta(days=1),
        1e-9,
    )
    leads_arr = np.asarray(leads, dtype="float64") if leads else np.array([np.nan])
    with np.errstate(all="ignore"):
        med = float(np.nanmedian(leads_arr)) if leads else float("nan")
        p10 = float(np.nanpercentile(leads_arr, 10)) if leads else float("nan")
        p90 = float(np.nanpercentile(leads_arr, 90)) if leads else float("nan")
    return {
        "events": int(len(events)),
        "detected": int(detected),
        "missed": int(len(events) - detected),
        "detection_rate": float(detected / len(events)),
        "median_lead_hours": med,
        "p10_lead_hours": p10,
        "p90_lead_hours": p90,
        "alerts_per_day": float(len(fired) / span_days),
        "false_alerts_per_event": float(max(len(fired) - detected, 0) / max(len(events), 1)),
    }


# ---------------------------------------------------------------------------
# Rolling-origin folds (plan section 4)
# ---------------------------------------------------------------------------


def rolling_origin_folds(
    timestamps: pd.Series,
    n_folds: int = 4,
    min_train_days: int = 120,
    valid_days: int = 60,
    embargo_hours: int = 48,
) -> list[dict]:
    """Expanding-window chronological folds with a purge/embargo gap.

    The embargo drops the hours immediately after the training cut so that a
    48h rolling feature computed at the start of validation cannot overlap the
    training window.
    """
    ts = pd.to_datetime(timestamps, utc=True)
    t0, t1 = ts.min().floor("D"), ts.max().ceil("D")
    total_days = (t1 - t0) / pd.Timedelta(days=1)
    usable = total_days - min_train_days
    if usable < valid_days:
        raise ValueError(
            f"Span of {total_days:.0f} days cannot host a {min_train_days}d train "
            f"plus a {valid_days}d validation window."
        )
    n_folds = int(min(n_folds, np.floor(usable / valid_days)))
    folds = []
    for k in range(n_folds):
        train_end = t0 + pd.Timedelta(days=min_train_days + k * valid_days)
        valid_start = train_end + pd.Timedelta(hours=embargo_hours)
        valid_end = min(valid_start + pd.Timedelta(days=valid_days), t1)
        if valid_start >= valid_end:
            break
        folds.append(
            {
                "fold": k + 1,
                "train_start": t0,
                "train_end": train_end,
                "valid_start": valid_start,
                "valid_end": valid_end,
                "embargo_hours": embargo_hours,
            }
        )
    return folds


def describe_fold(df: pd.DataFrame, fold: dict, label_col: str | None = None) -> dict:
    tr = (df["timestamp_utc"] >= fold["train_start"]) & (df["timestamp_utc"] < fold["train_end"])
    va = (df["timestamp_utc"] >= fold["valid_start"]) & (df["timestamp_utc"] < fold["valid_end"])
    info = {
        "fold": fold["fold"],
        "train_rows": int(tr.sum()),
        "valid_rows": int(va.sum()),
        "valid_start": str(fold["valid_start"].date()),
        "valid_end": str(fold["valid_end"].date()),
    }
    if va.any():
        months = df.loc[va, "timestamp_utc"].dt.month
        info["valid_seasons"] = sorted(season_of(months).unique().tolist())
    if label_col and label_col in df.columns:
        info["train_prevalence"] = float(df.loc[tr, label_col].mean()) if tr.any() else np.nan
        info["valid_prevalence"] = float(df.loc[va, label_col].mean()) if va.any() else np.nan
    return info


# ---------------------------------------------------------------------------
# Alert engine (plan sections 21, 32)
# ---------------------------------------------------------------------------


def apply_alert_policy(
    df: pd.DataFrame,
    score_col: str,
    raise_threshold: float,
    clear_threshold: float | None = None,
    persistence: int = 1,
    out_col: str = "alert",
) -> pd.Series:
    """Persistence + hysteresis filter over a per-station score series.

    An alert is raised once the score has been at or above ``raise_threshold``
    for ``persistence`` consecutive hours, and only clears once it drops below
    ``clear_threshold``. That asymmetry is what stops a score hovering near the
    threshold from flapping on and off every hour.
    """
    if clear_threshold is None:
        clear_threshold = raise_threshold
    if clear_threshold > raise_threshold:
        raise ValueError("clear_threshold must be <= raise_threshold for hysteresis.")

    frame = df.sort_values(["location_id", "timestamp_utc"])
    result = pd.Series(False, index=frame.index)
    for _, g in frame.groupby("location_id", sort=False):
        s = g[score_col].to_numpy("float64")
        hot = s >= raise_threshold
        if persistence > 1:
            run = np.zeros(len(s), dtype=int)
            c = 0
            for i, h in enumerate(hot):
                c = c + 1 if h else 0
                run[i] = c
            trigger = run >= persistence
        else:
            trigger = hot
        state = np.zeros(len(s), dtype=bool)
        on = False
        for i in range(len(s)):
            if not on and trigger[i]:
                on = True
            elif on and (s[i] < clear_threshold or not np.isfinite(s[i])):
                on = False
            state[i] = on
        result.loc[g.index] = state
    return result.reindex(df.index).rename(out_col)


def operating_modes(sweep: pd.DataFrame) -> dict:
    """Pick one threshold per product mode from a validation sweep."""
    modes = {}
    hi_recall = sweep[sweep["precision"] >= 0.10]
    modes["public_health"] = float(
        (hi_recall if len(hi_recall) else sweep).sort_values("recall", ascending=False)["threshold"].iloc[0]
    )
    hi_prec = sweep[sweep["recall"] >= 0.30]
    modes["operations"] = float(
        (hi_prec if len(hi_prec) else sweep).sort_values("precision", ascending=False)["threshold"].iloc[0]
    )
    modes["balanced"] = float(sweep.sort_values("f1", ascending=False)["threshold"].iloc[0])
    return modes



def attach(df: pd.DataFrame, new) -> pd.DataFrame:
    """Concat new columns onto ``df``, replacing any that already exist.

    Notebook 02 regenerates several features the upstream pm25 table already
    carries under the same name. A bare ``pd.concat`` would leave two columns
    with one label, and every later ``df["pm25_lag_1h"]`` would silently return
    a DataFrame instead of a Series.
    """
    frame = new if isinstance(new, pd.DataFrame) else pd.DataFrame(new, index=df.index)
    frame = frame.reindex(df.index)
    overlap = [c for c in frame.columns if c in df.columns]
    if overlap:
        df = df.drop(columns=overlap)
    return pd.concat([df, frame], axis=1)


def assert_unique_columns(df: pd.DataFrame) -> None:
    dupes = df.columns[df.columns.duplicated()].tolist()
    if dupes:
        raise ValueError(f"duplicate column labels: {sorted(set(dupes))}")

def write_report(path: Path, payload: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path
