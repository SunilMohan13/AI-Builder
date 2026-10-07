"""The one feature pipeline (``ml-features-3.0.0``) for training and serving.

``FeaturePipeline.build`` runs the shared preprocessing, turns records into
hourly tables, and computes every column of a family's
:class:`~aeropulse_contracts.feature_spec.FeatureSet` for the requested
``(cell, t)`` rows. Training calls it with ``as_of=None`` over history;
serving calls it with ``as_of`` = the cycle time. Each value at row ``t`` uses
only buckets ending ``<= t``, forecasts issued ``<= t`` and rasters processed
``<= t``, which ``aeropulse-ml parity`` verifies by recomputing sampled rows
from data truncated at ``t``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

import h3
import numpy as np
import pandas as pd
from aeropulse_contracts.feature_spec import (
    FIRE_RINGS_KM,
    FIRE_WINDOW_HOURS,
    HAZARD_PROFILE_IDS,
    ML_FEATURE_VERSION,
    NEAREST_SITE_MAX_KM,
    SATELLITE_MAX_AGE_HOURS,
    SEASONAL_FLAG_NAMES,
    TRANSPORT_BACK_HOURS,
    TRANSPORT_INITIAL_SPREAD_KM,
    TRANSPORT_SPREAD_FRACTION,
    FeatureSet,
)
from aeropulse_intelligence.plume import (
    SiteWindField,
    haversine_km,
    integrate,
    nearest_index,
    puff_weights,
)
from aeropulse_regions import RegionCatalog

from aeropulse_ml.features.tables import FeatureTables, build_tables, utc_ns
from aeropulse_ml.preprocessing import PreprocessContext, PreprocessingPipeline, RecordBatch

DEFAULT_HORIZONS = (1, 3, 6, 12, 24)
HAZARD_WINDOW_HOURS = 24
ID_COLUMNS = ("region_id", "cell", "t")
HOUR = pd.Timedelta(hours=1)


@dataclass(frozen=True)
class FeatureContext:
    region_id: str
    timezone: str
    hazards: frozenset[str]
    seasonal_months: Mapping[str, frozenset[int]]
    threshold_ugm3: float | None
    averaging: Literal["1h", "24h"] | None
    averaging_min_hours: int | None
    preprocess: PreprocessContext

    @classmethod
    def for_region(
        cls, catalog: RegionCatalog, region_id: str, *, as_of: datetime | None
    ) -> FeatureContext:
        pack = catalog.get(region_id)
        aqi = catalog.aqi_for(region_id)
        return cls(
            region_id=region_id,
            timezone=pack.timezone,
            hazards=frozenset(pack.hazards),
            seasonal_months=catalog.seasonal_months(region_id),
            threshold_ugm3=aqi.hazard_threshold_ugm3,
            averaging=aqi.averaging,
            averaging_min_hours=aqi.averaging_min_hours,
            preprocess=PreprocessContext.for_region(pack, as_of=as_of),
        )

    @property
    def as_of(self) -> datetime | None:
        return self.preprocess.as_of

    def at(self, as_of: datetime | None) -> FeatureContext:
        return replace(self, preprocess=replace(self.preprocess, as_of=as_of))


class FeaturePipeline:
    def __init__(
        self,
        feature_set: FeatureSet,
        *,
        horizons: Sequence[int] = DEFAULT_HORIZONS,
        preprocessing: PreprocessingPipeline | None = None,
    ) -> None:
        self.feature_set = feature_set
        self.horizons = tuple(horizons)
        self.preprocessing = preprocessing or PreprocessingPipeline()

    @property
    def per_horizon(self) -> bool:
        return "horizon_hours" in self.feature_set.names

    @property
    def label_column(self) -> str:
        return self.feature_set.target

    # --- entry points -------------------------------------------------

    def prepare(self, batch: RecordBatch, context: FeatureContext) -> FeatureTables:
        cleaned, _ = self.preprocessing.run(batch, context.preprocess)
        return build_tables(cleaned, context.preprocess)

    def build(
        self,
        batch: RecordBatch,
        context: FeatureContext,
        rows: pd.DataFrame | None = None,
        *,
        labels: bool = False,
    ) -> pd.DataFrame:
        """Feature frame for ``rows`` (``cell``, ``t``); default rows by mode.

        Training (``as_of is None``): every station bucket. Serving: station
        cells seen in the last day, at the hour ending at or before ``as_of``.
        """
        tables = self.prepare(batch, context)
        if rows is None:
            rows = (
                training_rows(tables)
                if context.as_of is None
                else serving_rows(tables, context.as_of)
            )
        return self.compute(tables, context, rows, labels=labels)

    def compute(
        self,
        tables: FeatureTables,
        context: FeatureContext,
        rows: pd.DataFrame,
        *,
        labels: bool = False,
    ) -> pd.DataFrame:
        frame = rows[["cell", "t"]].drop_duplicates().reset_index(drop=True)
        frame["t"] = utc_ns(frame["t"])
        if self.per_horizon:
            frame = frame.merge(
                pd.DataFrame({"horizon_hours": [float(h) for h in self.horizons]}), how="cross"
            )
        frame.insert(0, "region_id", context.region_id)
        if frame.empty:
            return self._empty(labels)

        wide = _station_wide(tables.stations, frame)
        columns: dict[str, np.ndarray] = {}
        columns.update(_history(wide, frame))
        columns.update(_context(frame, context))
        cells = _CellSites(frame["cell"].unique(), tables)
        columns.update(_weather_now(frame, tables, cells))
        columns.update(_cams_now(frame, tables, cells))
        columns.update(_forecast_at_h(frame, tables, cells))
        columns.update(_forecast_24h(frame, tables, cells))
        columns.update(_fires(frame, tables, cells))
        columns.update(_satellite(frame, tables))
        if self.per_horizon:
            columns["horizon_hours"] = frame["horizon_hours"].to_numpy(dtype=float)

        out = frame[list(ID_COLUMNS)].copy()
        for name in self.feature_set.names:
            out[name] = columns[name]
        if labels:
            out[self.label_column] = self._labels(wide, frame, context, tables)
        out["ml_feature_version"] = ML_FEATURE_VERSION
        return out

    def _labels(
        self,
        wide: pd.DataFrame,
        frame: pd.DataFrame,
        context: FeatureContext,
        tables: FeatureTables,
    ) -> np.ndarray:
        if self.per_horizon:
            target_t = frame["t"] + pd.to_timedelta(frame["horizon_hours"], unit="h")
            return _lookup(wide, frame["cell"], target_t)
        return _hazard_label(wide, frame, context, tables)

    def _empty(self, labels: bool) -> pd.DataFrame:
        names = [*ID_COLUMNS, *self.feature_set.names]
        if labels:
            names.append(self.label_column)
        return pd.DataFrame(columns=[*names, "ml_feature_version"])


# --- rows ------------------------------------------------------------------


def training_rows(tables: FeatureTables) -> pd.DataFrame:
    return tables.stations.rename(columns={"tau": "t"})[["cell", "t"]]


def serving_rows(tables: FeatureTables, as_of: datetime) -> pd.DataFrame:
    t = pd.Timestamp(as_of).tz_convert("UTC").floor("h")
    recent = tables.stations[(tables.stations["tau"] > t - pd.Timedelta(days=1))]
    recent = recent[recent["tau"] <= t]
    rows = pd.DataFrame({"cell": sorted(recent["cell"].unique())})
    rows["t"] = t
    return rows


# --- history and labels ----------------------------------------------------


def _station_wide(stations: pd.DataFrame, frame: pd.DataFrame) -> pd.DataFrame:
    """Hourly station PM2.5, one column per cell, on a gap-free index.

    The index spans the data and the rows (plus a day each side), so
    trailing windows at ``t`` and label look-ups at ``t + 24h`` resolve
    whether or not ``t`` itself has data.
    """
    if stations.empty:
        return pd.DataFrame()
    wide = stations.pivot_table(index="tau", columns="cell", values="value", aggfunc="mean")
    start = min(wide.index.min(), frame["t"].min()) - pd.Timedelta(days=1)
    end = max(wide.index.max(), frame["t"].max()) + pd.Timedelta(days=1)
    return wide.reindex(pd.date_range(start, end, freq="h"))


def _lookup(wide: pd.DataFrame, cells: pd.Series, times: pd.Series) -> np.ndarray:
    out = np.full(len(cells), np.nan)
    if wide.empty:
        return out
    ri = wide.index.get_indexer(pd.DatetimeIndex(times))
    ci = wide.columns.get_indexer(cells.to_numpy())
    ok = (ri >= 0) & (ci >= 0)
    out[ok] = wide.to_numpy(dtype=float)[ri[ok], ci[ok]]
    return out


def _history(wide: pd.DataFrame, frame: pd.DataFrame) -> dict[str, np.ndarray]:
    cells, t = frame["cell"], frame["t"]
    cols = {"pm25": _lookup(wide, cells, t)}
    for lag in (1, 3, 6, 24):
        cols[f"pm25_lag_{lag}h"] = _lookup(wide, cells, t - lag * HOUR)
    prev = wide.shift(1) if not wide.empty else wide
    for hours in (6, 24):
        window = prev.rolling(hours, min_periods=1) if not prev.empty else None
        mean = window.mean() if window is not None else prev
        peak = window.max() if window is not None else prev
        cols[f"pm25_roll_{hours}h"] = _lookup(mean, cells, t)
        cols[f"pm25_roll_max_{hours}h"] = _lookup(peak, cells, t)
    return cols


def _hazard_label(
    wide: pd.DataFrame, frame: pd.DataFrame, context: FeatureContext, tables: FeatureTables
) -> np.ndarray:
    """1 if the standard's concentration reaches the threshold in ``t+1 .. t+24``.

    Missing where the region's standard has no threshold, where the window
    runs past the last station bucket, or where no hour in it has a value.
    """
    n = len(frame)
    if context.threshold_ugm3 is None or wide.empty:
        return np.full(n, np.nan)
    if context.averaging == "24h":
        conc = wide.rolling(24, min_periods=context.averaging_min_hours or 24).mean()
    else:
        conc = wide
    ahead = conc.iloc[::-1].rolling(HAZARD_WINDOW_HOURS, min_periods=1).max().iloc[::-1].shift(-1)
    peak = _lookup(ahead, frame["cell"], frame["t"])
    label = np.where(np.isnan(peak), np.nan, (peak >= context.threshold_ugm3).astype(float))
    last = tables.stations["tau"].max()
    complete = (frame["t"] + HAZARD_WINDOW_HOURS * HOUR <= last).to_numpy()
    return np.where(complete, label, np.nan)


# --- region and time -------------------------------------------------------


def _context(frame: pd.DataFrame, context: FeatureContext) -> dict[str, np.ndarray]:
    local = frame["t"].dt.tz_convert(context.timezone)
    hour = (local.dt.hour + local.dt.minute / 60.0).to_numpy(dtype=float)
    dow = local.dt.dayofweek.to_numpy(dtype=float)
    month = local.dt.month.to_numpy()
    tau = 2.0 * np.pi
    cols: dict[str, np.ndarray] = {
        "sin_hour_local": np.sin(tau * hour / 24.0),
        "cos_hour_local": np.cos(tau * hour / 24.0),
        "sin_dow_local": np.sin(tau * dow / 7.0),
        "cos_dow_local": np.cos(tau * dow / 7.0),
        "sin_month_local": np.sin(tau * (month - 1) / 12.0),
        "cos_month_local": np.cos(tau * (month - 1) / 12.0),
    }
    for name in SEASONAL_FLAG_NAMES:
        months = context.seasonal_months.get(name, frozenset())
        cols[name] = np.isin(month, sorted(months)).astype(float)
    for hazard in HAZARD_PROFILE_IDS:
        cols[f"hazard_{hazard}"] = np.full(len(frame), float(hazard in context.hazards))
    threshold = np.nan if context.threshold_ugm3 is None else context.threshold_ugm3
    cols["region_threshold_ugm3"] = np.full(len(frame), threshold)
    return cols


# --- nearest wind site -----------------------------------------------------


class _CellSites:
    """Nearest site per row cell for each site-based table."""

    def __init__(self, cells: np.ndarray, tables: FeatureTables) -> None:
        self.cells = cells
        centres = np.array([h3.cell_to_latlng(c) for c in cells], dtype=float).reshape(-1, 2)
        self.lat, self.lon = centres[:, 0], centres[:, 1]
        self.weather = self._map(tables.weather)
        self.cams = self._map(tables.cams)
        self.forecasts = self._map(tables.forecasts)

    def _map(self, table: pd.DataFrame) -> dict[str, str | None]:
        sites = table[["site", "lat", "lon"]].drop_duplicates("site")
        idx = nearest_index(
            self.lat,
            self.lon,
            sites["lat"].to_numpy(dtype=float),
            sites["lon"].to_numpy(dtype=float),
            NEAREST_SITE_MAX_KM,
        )
        keys = sites["site"].to_numpy()
        return {c: (keys[i] if i >= 0 else None) for c, i in zip(self.cells, idx, strict=True)}


def _merge_on_site(
    frame: pd.DataFrame,
    sites: Mapping[str, str | None],
    table: pd.DataFrame,
    time_column: str,
    values: Sequence[str],
) -> pd.DataFrame:
    keys = pd.DataFrame({"site": frame["cell"].map(sites), time_column: frame["t"]})
    merged = keys.merge(table[["site", time_column, *values]], on=["site", time_column], how="left")
    return merged


def _weather_now(
    frame: pd.DataFrame, tables: FeatureTables, cells: _CellSites
) -> dict[str, np.ndarray]:
    merged = _merge_on_site(
        frame,
        cells.weather,
        tables.weather,
        "tau",
        ["wind_u", "wind_v", "boundary_layer_height", "temperature", "humidity", "precipitation"],
    )
    return {
        "wind_u_now": merged["wind_u"].to_numpy(dtype=float),
        "wind_v_now": merged["wind_v"].to_numpy(dtype=float),
        "boundary_layer_height_now": merged["boundary_layer_height"].to_numpy(dtype=float),
        "temperature_now": merged["temperature"].to_numpy(dtype=float),
        "humidity_now": merged["humidity"].to_numpy(dtype=float),
        "precipitation_now": merged["precipitation"].to_numpy(dtype=float),
    }


def _cams_now(
    frame: pd.DataFrame, tables: FeatureTables, cells: _CellSites
) -> dict[str, np.ndarray]:
    merged = _merge_on_site(frame, cells.cams, tables.cams, "tau", ["value"])
    return {"cams_pm25_now": merged["value"].to_numpy(dtype=float)}


def _latest_issue(
    sites: pd.Series, issued_cut: pd.Series, valid_at: pd.Series, forecasts: pd.DataFrame
) -> pd.DataFrame:
    """Per row, the forecast for ``(site, valid_at)`` issued latest ``<= issued_cut``."""
    left = pd.DataFrame(
        {
            "_row": np.arange(len(sites)),
            "site": sites.to_numpy(),
            "valid_at": pd.DatetimeIndex(valid_at),
            "issued_cut": pd.DatetimeIndex(issued_cut),
        }
    )
    have = left["site"].notna()
    result = pd.DataFrame(index=left["_row"], columns=forecasts.columns, dtype=float)
    if not have.any() or forecasts.empty:
        return result.reset_index(drop=True)
    right = forecasts.sort_values("issued_at")
    matched = pd.merge_asof(
        left[have].sort_values("issued_cut"),
        right,
        left_on="issued_cut",
        right_on="issued_at",
        by=["site", "valid_at"],
        direction="backward",
    ).set_index("_row")
    return matched.reindex(left["_row"]).reset_index(drop=True)


def _forecast_at_h(
    frame: pd.DataFrame, tables: FeatureTables, cells: _CellSites
) -> dict[str, np.ndarray]:
    names = (
        "fc_wind_u_10m",
        "fc_wind_v_10m",
        "fc_wind_u_100m",
        "fc_wind_v_100m",
        "fc_boundary_layer_height",
        "fc_temperature",
        "fc_humidity",
        "fc_precipitation",
        "cams_pm25_at_h",
    )
    if "horizon_hours" not in frame:
        return {}
    valid = frame["t"] + pd.to_timedelta(frame["horizon_hours"], unit="h")
    matched = _latest_issue(frame["cell"].map(cells.forecasts), frame["t"], valid, tables.forecasts)
    source = (
        "wind_u_10m",
        "wind_v_10m",
        "wind_u_100m",
        "wind_v_100m",
        "boundary_layer_height",
        "temperature",
        "humidity",
        "precipitation",
        "cams_pm25",
    )
    return {
        name: pd.to_numeric(matched[col], errors="coerce").to_numpy(dtype=float)
        for name, col in zip(names, source, strict=True)
    }


def _forecast_24h(
    frame: pd.DataFrame, tables: FeatureTables, cells: _CellSites
) -> dict[str, np.ndarray]:
    pairs = pd.DataFrame({"site": frame["cell"].map(cells.forecasts), "t": frame["t"]})
    unique = pairs.drop_duplicates().reset_index(drop=True)
    names = (
        "fc_wind_speed_mean_24h",
        "fc_boundary_layer_height_min_24h",
        "fc_precipitation_sum_24h",
        "cams_pm25_max_24h",
    )
    unique = unique[unique["site"].notna()].reset_index(drop=True)
    if unique.empty or tables.forecasts.empty:
        return {n: np.full(len(frame), np.nan) for n in names}
    steps = pd.DataFrame({"k": np.arange(1, HAZARD_WINDOW_HOURS + 1)})
    expanded = unique.merge(steps, how="cross")
    valid = expanded["t"] + pd.to_timedelta(expanded["k"], unit="h")
    matched = _latest_issue(expanded["site"], expanded["t"], valid, tables.forecasts)
    expanded["speed"] = np.hypot(
        pd.to_numeric(matched["wind_u_10m"], errors="coerce").to_numpy(dtype=float),
        pd.to_numeric(matched["wind_v_10m"], errors="coerce").to_numpy(dtype=float),
    )
    for col in ("boundary_layer_height", "precipitation", "cams_pm25"):
        expanded[col] = pd.to_numeric(matched[col], errors="coerce").to_numpy(dtype=float)
    grouped = expanded.groupby(["site", "t"], dropna=False).agg(
        fc_wind_speed_mean_24h=("speed", "mean"),
        fc_boundary_layer_height_min_24h=("boundary_layer_height", "min"),
        fc_precipitation_sum_24h=("precipitation", lambda s: s.sum(min_count=1)),
        cams_pm25_max_24h=("cams_pm25", "max"),
    )
    joined = pairs.merge(grouped.reset_index(), on=["site", "t"], how="left")
    return {n: joined[n].to_numpy(dtype=float) for n in names}


# --- fire ------------------------------------------------------------------


def _wind_field(weather: pd.DataFrame) -> SiteWindField:
    sites = weather[["site", "lat", "lon"]].drop_duplicates("site").reset_index(drop=True)
    order = {s: i for i, s in enumerate(sites["site"])}
    hours: dict[datetime, tuple[np.ndarray, np.ndarray]] = {}
    for tau, group in weather.groupby("tau"):
        u = np.full(len(sites), np.nan)
        v = np.full(len(sites), np.nan)
        idx = group["site"].map(order).to_numpy()
        u[idx] = group["wind_u"].to_numpy(dtype=float)
        v[idx] = group["wind_v"].to_numpy(dtype=float)
        hours[pd.Timestamp(tau).to_pydatetime()] = (u, v)
    return SiteWindField(
        site_lat=sites["lat"].to_numpy(dtype=float),
        site_lon=sites["lon"].to_numpy(dtype=float),
        hours=hours,
        max_site_km=NEAREST_SITE_MAX_KM,
    )


def _fires(frame: pd.DataFrame, tables: FeatureTables, cells: _CellSites) -> dict[str, np.ndarray]:
    near, far = FIRE_RINGS_KM
    per_cell_t = frame[["cell", "t"]].drop_duplicates().reset_index(drop=True)
    count_near = np.zeros(len(per_cell_t))
    count_far = np.zeros(len(per_cell_t))
    frp_far = np.zeros(len(per_cell_t))
    transport = np.zeros(len(per_cell_t))
    fires = tables.fires.sort_values("observed_at").reset_index(drop=True)
    if not fires.empty:
        times = fires["observed_at"].to_numpy(dtype="datetime64[ns]")
        f_lat = fires["lat"].to_numpy(dtype=float)
        f_lon = fires["lon"].to_numpy(dtype=float)
        f_frp = fires["frp"].to_numpy(dtype=float)
        wind = _wind_field(tables.weather)
        centre = {
            c: (lat, lon) for c, lat, lon in zip(cells.cells, cells.lat, cells.lon, strict=True)
        }
        for t, group in per_cell_t.groupby("t"):
            t_ns = np.datetime64(pd.Timestamp(t).tz_convert("UTC").tz_localize(None), "ns")
            lo = np.searchsorted(times, t_ns - np.timedelta64(FIRE_WINDOW_HOURS, "h"), side="right")
            hi = np.searchsorted(times, t_ns, side="right")
            if hi <= lo:
                continue
            rows = group.index.to_numpy()
            lat = np.array([centre[c][0] for c in group["cell"]])
            lon = np.array([centre[c][1] for c in group["cell"]])
            d = haversine_km(lat[:, None], lon[:, None], f_lat[None, lo:hi], f_lon[None, lo:hi])
            count_near[rows] = (d <= near).sum(axis=1)
            count_far[rows] = (d <= far).sum(axis=1)
            frp_far[rows] = np.where(d <= far, f_frp[None, lo:hi], 0.0).sum(axis=1)
            start = pd.Timestamp(t).to_pydatetime()
            trajectory = integrate(lat, lon, start, wind, TRANSPORT_BACK_HOURS, backward=True)
            age = (t_ns - times[lo:hi]).astype("timedelta64[s]").astype(float) / 3600.0
            weights = puff_weights(
                trajectory,
                f_lat[lo:hi],
                f_lon[lo:hi],
                age,
                initial_spread_km=TRANSPORT_INITIAL_SPREAD_KM,
                spread_fraction=TRANSPORT_SPREAD_FRACTION,
            )
            transport[rows] = weights @ f_frp[lo:hi]
    per_cell_t["fire_count_25km_24h"] = count_near
    per_cell_t["fire_count_50km_24h"] = count_far
    per_cell_t["fire_frp_50km_24h"] = frp_far
    per_cell_t["transport_weighted_frp"] = transport
    joined = frame[["cell", "t"]].merge(per_cell_t, on=["cell", "t"], how="left")
    return {
        n: joined[n].to_numpy(dtype=float)
        for n in (
            "fire_count_25km_24h",
            "fire_count_50km_24h",
            "fire_frp_50km_24h",
            "transport_weighted_frp",
        )
    }


# --- satellite -------------------------------------------------------------


def _satellite(frame: pd.DataFrame, tables: FeatureTables) -> dict[str, np.ndarray]:
    n = len(frame)
    index = np.full(n, np.nan)
    fraction = np.full(n, np.nan)
    rasters = tables.rasters
    if rasters.empty:
        return {"s5p_aerosol_index": index, "s5p_valid_fraction": fraction}
    cell_res = {c: h3.get_resolution(c) for c in frame["cell"].unique()}
    # Finest resolution first, so a coarser product only fills gaps.
    for res in sorted(rasters["resolution"].unique(), reverse=True):
        right = rasters[rasters["resolution"] == res].sort_values("processing_time")
        parents = frame["cell"].map(
            lambda c, r=int(res): h3.cell_to_parent(c, r) if cell_res[c] >= r else None
        )
        left = pd.DataFrame({"_row": np.arange(n), "parent": parents, "t": frame["t"]})
        left = left[left["parent"].notna()].sort_values("t")
        if left.empty:
            continue
        matched = pd.merge_asof(
            left,
            right.rename(columns={"cell": "parent"}),
            left_on="t",
            right_on="processing_time",
            by="parent",
            direction="backward",
            tolerance=pd.Timedelta(hours=SATELLITE_MAX_AGE_HOURS),
        )
        rows = matched["_row"].to_numpy()
        ai = matched["aerosol_index"].to_numpy(dtype=float)
        vf = matched["valid_fraction"].to_numpy(dtype=float)
        fill = np.isnan(index[rows]) & ~np.isnan(ai)
        index[rows[fill]] = ai[fill]
        fraction[rows[fill]] = vf[fill]
    return {"s5p_aerosol_index": index, "s5p_valid_fraction": fraction}
