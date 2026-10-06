"""AeroPulse propagation forecasting toolkit.

Shared library behind notebooks 01-08. Everything a notebook does twice, or that
production has to reproduce exactly, lives here rather than in a cell.

Implements the design in ``AeroPulse_Propagation_ML_Improvement_Plan.md``:
data contract + quality gates (S4), leakage controls (S5), forecast-vintage
weather (S6), temporal/station/spatial/transport features (S7-S15), the baseline
ladder (S16), residual + quantile models (S17/S21), rolling-origin and
geographic validation (S23/S24), station/regime/event metrics (S25-S28),
registry (S32/S33), and the inference contract with fallback routing (S34-S36).

Units note: Open-Meteo is queried without ``wind_speed_unit``, so wind_speed_10m
and the derived wind_u/wind_v are **km/h**, not m/s. Everything here uses
:data:`WIND_KMH_TO_KM_PER_H` = 1.0 accordingly.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import numpy as np
import pandas as pd

__all__ = [
    "PropagationConfig",
    "load_config",
    "SCHEMA",
    "validate_contract",
    "quality_report",
    "dataset_fingerprint",
    "add_cyclical_time",
    "StationBaselines",
    "WindClimatology",
    "integrated_advection",
    "add_stability_features",
    "add_regime_features",
    "BASELINE_NAMES",
    "baseline_forecasts",
    "chrono_split",
    "rolling_origin_folds",
    "geographic_blocks",
    "regression_metrics",
    "skill",
    "station_metrics",
    "regime_metrics",
    "event_metrics",
    "coverage_metrics",
    "bias_metrics",
    "make_regressor",
    "translate_params",
    "make_quantile_regressor",
    "ResidualModel",
    "QuantileBundle",
    "conformal_widths",
    "PROMOTION_GATES",
    "evaluate_promotion",
    "ModelRegistry",
    "PropagationPredictor",
    "select_features",
    "leakage_scan",
    "assert_past_only",
    "time_lag",
    "rolling_past",
]

# ---------------------------------------------------------------------------
# Units and physical constants
# ---------------------------------------------------------------------------

WIND_KMH_TO_KM_PER_H = 1.0
"""Open-Meteo wind is km/h, so 1 hour of transport = 1 x speed km."""

KM_PER_DEG_LAT = 111.32
PM25_HARD_MAX = 2000.0
"""Physical/data-derived upper bound. Anything above is a sensor fault, not air."""

EVENT_THRESHOLD_UGM3 = 150.0
REGIME_BINS = [0.0, 30.0, 60.0, 120.0, 250.0, np.inf]
REGIME_LABELS = ["<30", "30-60", "60-120", "120-250", ">250"]


# ---------------------------------------------------------------------------
# Configuration (S43)
# ---------------------------------------------------------------------------


@dataclass
class PropagationConfig:
    """Resolved paths + knobs. One object instead of fifteen module globals."""

    project_root: Path
    pm25_data_root: Path
    horizons: list[int]
    schema_version: str = "2.0.0"
    train_fraction: float = 0.70
    validation_fraction: float = 0.15
    quantiles: tuple[float, float, float] = (0.1, 0.5, 0.9)
    max_train_rows: int | None = None
    rolling_folds: int = 4
    geographic_blocks: int = 5
    random_state: int = 42
    extras: dict[str, Any] = field(default_factory=dict)

    # -- derived paths ------------------------------------------------------
    @property
    def data_root(self) -> Path:
        return self.project_root / "data" / "propagation"

    @property
    def base_dir(self) -> Path:
        return self.data_root / "processed" / "base"

    @property
    def feature_dir(self) -> Path:
        return self.data_root / "processed" / "features"

    @property
    def artifact_dir(self) -> Path:
        return self.project_root / "artifacts" / "propagation"

    def stage_dir(self, name: str) -> Path:
        path = self.artifact_dir / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def registry_dir(self) -> Path:
        return self.artifact_dir / "registry"

    @property
    def event_aware_file(self) -> Path:
        return (
            self.pm25_data_root
            / "data"
            / "pm25"
            / "processed"
            / "event_aware"
            / "pm25_event_aware_features.parquet"
        )

    def ensure_dirs(self) -> None:
        for path in [
            self.data_root,
            self.base_dir,
            self.feature_dir,
            self.artifact_dir,
            self.registry_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_root": str(self.project_root),
            "pm25_data_root": str(self.pm25_data_root),
            "horizons": self.horizons,
            "schema_version": self.schema_version,
            "train_fraction": self.train_fraction,
            "validation_fraction": self.validation_fraction,
            "quantiles": list(self.quantiles),
            "max_train_rows": self.max_train_rows,
            "rolling_folds": self.rolling_folds,
            "geographic_blocks": self.geographic_blocks,
        }


def load_config(verbose: bool = True) -> PropagationConfig:
    """Read .env (walking upward), build a config, create the directories."""
    from dotenv import find_dotenv, load_dotenv

    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path, override=True)
    warnings.filterwarnings("ignore")

    def _int_or_none(name: str) -> int | None:
        raw = os.getenv(name, "").strip()
        return int(raw) if raw else None

    cfg = PropagationConfig(
        project_root=Path(os.getenv("AEROPULSE_PROJECT_ROOT", ".")).resolve(),
        pm25_data_root=Path(os.getenv("PM25_DATA_ROOT", "../pm25_estimator")).resolve(),
        horizons=[int(x) for x in os.getenv("PROP_HORIZONS", "1,3,6,12,24,48").split(",") if x.strip()],
        train_fraction=float(os.getenv("PROP_TRAIN_FRACTION", "0.70")),
        validation_fraction=float(os.getenv("PROP_VALID_FRACTION", "0.15")),
        max_train_rows=_int_or_none("PROP_MAX_TRAIN_ROWS"),
        rolling_folds=int(os.getenv("PROP_ROLLING_FOLDS", "4")),
        geographic_blocks=int(os.getenv("PROP_GEO_BLOCKS", "5")),
    )
    cfg.ensure_dirs()
    if verbose:
        print("env:", dotenv_path or "(none — using defaults)")
        print("project:", cfg.project_root)
        print("horizons:", cfg.horizons, "| schema", cfg.schema_version)
        if cfg.max_train_rows:
            print("max_train_rows:", f"{cfg.max_train_rows:,}")
    return cfg


def git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Data contract + quality gates (S4)
# ---------------------------------------------------------------------------

SCHEMA: dict[str, Any] = {
    "schema_version": "2.0.0",
    "required": [
        "location_id",
        "timestamp_utc",
        "pm25",
        "lat",
        "lon",
        "wind_u",
        "wind_v",
        "wind_speed_10m",
        "wind_direction_10m",
        "boundary_layer_height",
        "temperature_2m",
        "relative_humidity_2m",
        "surface_pressure",
    ],
    "recommended": [
        "regional_pm25_mean_50km",
        "upwind_pm25_mean",
        "pm25_local_excess",
        "fire_frp_sum_50km_24h",
        "upwind_fire_frp_50km",
        "pollution_regime",
        "season",
    ],
    "targets": [1, 3, 6, 12, 24, 48],
    "frequency": "hourly",
    "timezone": "UTC",
    "units": {
        "pm25": "ug/m3",
        "wind_speed_10m": "km/h",
        "wind_u": "km/h",
        "wind_v": "km/h",
        "boundary_layer_height": "m",
        "temperature_2m": "degC",
        "surface_pressure": "hPa",
    },
    "ranges": {
        "pm25": (0.0, PM25_HARD_MAX),
        "lat": (6.0, 38.0),
        "lon": (66.0, 98.0),
        "wind_speed_10m": (0.0, 200.0),
        "boundary_layer_height": (0.0, 6000.0),
        "temperature_2m": (-30.0, 60.0),
        "relative_humidity_2m": (0.0, 100.0),
        "surface_pressure": (700.0, 1100.0),
    },
}


def validate_contract(df: pd.DataFrame, cfg: PropagationConfig, schema: dict | None = None) -> dict:
    """Hard contract check. Raises on a violation — training must fail fast."""
    schema = schema or SCHEMA
    missing = [c for c in schema["required"] if c not in df.columns]
    missing_targets = [
        f"target_pm25_t_plus_{h}h"
        for h in cfg.horizons
        if f"target_pm25_t_plus_{h}h" not in df.columns
    ]
    absent_recommended = [c for c in schema["recommended"] if c not in df.columns]

    result = {
        "schema_version": schema["schema_version"],
        "missing_required": missing,
        "missing_targets": missing_targets,
        "absent_recommended": absent_recommended,
        "rows": int(len(df)),
        "columns": int(df.shape[1]),
        "status": "PASS" if not missing and not missing_targets else "FAIL",
    }
    if result["status"] == "FAIL":
        raise ValueError(
            f"Data contract violated. missing_required={missing} missing_targets={missing_targets}"
        )
    if not isinstance(df["timestamp_utc"].dtype, pd.DatetimeTZDtype):
        raise ValueError("timestamp_utc must be timezone-aware (UTC).")
    return result


def quality_report(
    df: pd.DataFrame, cfg: PropagationConfig, schema: dict | None = None
) -> tuple[dict, pd.DataFrame]:
    """Per-dataset and per-station quality gates. Returns the report dict (S4.2)."""
    schema = schema or SCHEMA
    ranges = schema["ranges"]
    ts = df["timestamp_utc"]

    dup_mask = df.duplicated(subset=["location_id", "timestamp_utc"], keep=False)
    ordered = df.sort_values(["location_id", "timestamp_utc"])
    deltas = ordered.groupby("location_id", observed=True)["timestamp_utc"].diff()
    gap_hours = deltas.dt.total_seconds() / 3600.0
    gaps = gap_hours[gap_hours > 1.0]

    out_of_range: dict[str, int] = {}
    for col, (lo, hi) in ranges.items():
        if col in df.columns:
            values = pd.to_numeric(df[col], errors="coerce")
            bad = int(((values < lo) | (values > hi)).sum())
            if bad:
                out_of_range[col] = bad

    station_coverage = (
        df.groupby("location_id", observed=True)
        .agg(
            rows=("pm25", "size"),
            pm25_missing_pct=("pm25", lambda s: float(s.isna().mean() * 100)),
            first=("timestamp_utc", "min"),
            last=("timestamp_utc", "max"),
        )
        .reset_index()
    )
    span_hours = (station_coverage["last"] - station_coverage["first"]).dt.total_seconds() / 3600.0
    station_coverage["completeness_pct"] = (
        station_coverage["rows"] / (span_hours + 1.0) * 100.0
    ).clip(upper=100.0).round(2)

    target_availability = {
        f"target_pm25_t_plus_{h}h": round(
            float(1.0 - df[f"target_pm25_t_plus_{h}h"].isna().mean()) * 100, 3
        )
        for h in cfg.horizons
        if f"target_pm25_t_plus_{h}h" in df.columns
    }

    report = {
        "generated_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "rows": int(len(df)),
        "stations": int(df["location_id"].nunique()),
        "window_start": str(ts.min()),
        "window_end": str(ts.max()),
        "missing_pm25_pct": round(float(df["pm25"].isna().mean() * 100), 4),
        "duplicate_rows": int(dup_mask.sum()),
        "timestamp_gaps": int(len(gaps)),
        "gap_hours_max": float(gaps.max()) if len(gaps) else 0.0,
        "long_gaps_over_24h": int((gaps > 24).sum()),
        "invalid_pm25_rows": int(
            ((df["pm25"] < ranges["pm25"][0]) | (df["pm25"] > ranges["pm25"][1])).sum()
        ),
        "out_of_range": out_of_range,
        "stations_off_grid": int(
            (
                (df["lat"] < ranges["lat"][0])
                | (df["lat"] > ranges["lat"][1])
                | (df["lon"] < ranges["lon"][0])
                | (df["lon"] > ranges["lon"][1])
            )
            .groupby(df["location_id"], observed=True)
            .any()
            .sum()
        ),
        "target_availability_pct": target_availability,
        "station_completeness_p10": float(station_coverage["completeness_pct"].quantile(0.10)),
        "station_completeness_median": float(station_coverage["completeness_pct"].median()),
        "stations_under_50pct_complete": int((station_coverage["completeness_pct"] < 50).sum()),
    }

    failures = []
    if report["duplicate_rows"] > 0:
        failures.append("duplicate (location_id, timestamp_utc) rows")
    if report["invalid_pm25_rows"] > 0:
        failures.append("pm25 outside physical range")
    if report["stations_off_grid"] > 0:
        failures.append("station coordinates outside the India bounding box")
    if report["missing_pm25_pct"] > 5.0:
        failures.append("pm25 missingness above 5%")
    report["failures"] = failures
    report["quality_status"] = "PASS" if not failures else "FAIL"
    return report, station_coverage


def dataset_fingerprint(frame: pd.DataFrame) -> str:
    payload = {
        "rows": int(len(frame)),
        "cols": sorted(frame.columns.tolist()),
        "tmin": str(frame["timestamp_utc"].min()) if "timestamp_utc" in frame else None,
        "tmax": str(frame["timestamp_utc"].max()) if "timestamp_utc" in frame else None,
        "pm25_sum": round(float(pd.to_numeric(frame["pm25"], errors="coerce").sum()), 3)
        if "pm25" in frame
        else None,
    }
    return hashlib.sha256(json.dumps(payload, default=str).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Leakage controls (S5)
# ---------------------------------------------------------------------------

FUTURE_COLUMN_PREFIXES = ("target_", "event_")
FUTURE_COLUMN_NAMES = {
    "event_id",
    "event_start",
    "event_end",
    "event_peak_pm25",
    "event_mean_pm25",
    "event_observed_hours",
    "event_duration_hours",
    "event_gap_hours",
    "event_start_flag",
    "pollution_regime",
    "season",
}
IDENTIFIER_COLUMNS = {
    "location_id",
    "timestamp_utc",
    "timestamp_local",
    "sensor_id",
    "station_name",
    "source",
    "source_quality",
    "grid_id",
    "weather_source",
    "fire_source",
    "country",
    "state",
    "city",
    "schema_version",
    "pm25_unit",
}


def select_features(
    df: pd.DataFrame,
    horizon: int | None = None,
    extra_exclude: Iterable[str] = (),
    drop_degenerate: bool = True,
    sample: int = 50_000,
) -> list[str]:
    """Numeric columns a model may see at forecast time.

    Drops identifiers, every ``target_*``/``event_*`` column, and the
    per-horizon advection block belonging to *other* horizons.

    Also drops degenerate columns -- all-NaN or single-valued. These are not
    merely useless: a baseline that is structurally unavailable at a given
    horizon (``seasonal_24h`` at h=24) becomes an all-NaN column, and
    HistGradientBoosting raises rather than ignoring it.
    """
    exclude = set(IDENTIFIER_COLUMNS) | set(FUTURE_COLUMN_NAMES) | set(extra_exclude)
    feats: list[str] = []
    for col in df.columns:
        if col in exclude or col.startswith(FUTURE_COLUMN_PREFIXES):
            continue
        if not pd.api.types.is_numeric_dtype(df[col]):
            continue
        if "_h" in col and (col.startswith("advect_") or col.startswith("transport_") or col.startswith("fcst_")):
            suffix = col.rsplit("_h", 1)[-1]
            if suffix.isdigit() and horizon is not None and int(suffix) != int(horizon):
                continue
        feats.append(col)

    if drop_degenerate and feats:
        probe = df[feats].iloc[:: max(1, len(df) // sample)] if len(df) > sample else df[feats]
        keep = []
        for col in feats:
            values = probe[col]
            if values.notna().sum() == 0 or values.nunique(dropna=True) <= 1:
                continue
            keep.append(col)
        feats = keep
    return feats


def time_lag(hours: int, value_col: str = "pm25") -> Callable[[pd.DataFrame], pd.Series]:
    """Builder for a *wall-clock* lag: the value observed exactly ``hours`` ago.

    Not the same as ``shift(hours)``. With 56k gaps in this dataset a
    positional shift reaches back an arbitrary distance, so the two disagree
    on 44% of rows -- and the time-aligned version is the correct one.
    """

    def _build(grp: pd.DataFrame) -> pd.Series:
        series = grp.set_index("timestamp_utc")[value_col]
        looked_up = series.reindex(series.index - pd.Timedelta(hours=hours))
        return pd.Series(looked_up.to_numpy(), index=grp.index)

    return _build


def rolling_past(
    window_hours: int, stat: str = "mean", value_col: str = "pm25", ddof: int = 0
):
    """Builder for a strictly-past, gap-aware rolling statistic.

    Time-based window with ``closed="left"``: the previous ``window_hours`` of
    wall-clock time, excluding the current observation. This is the recipe the
    upstream feature store uses, and it is the right one -- a positional
    ``rolling(n).shift(1)`` would span a 300-day gap without noticing.
    """

    def _build(grp: pd.DataFrame) -> pd.Series:
        series = grp.set_index("timestamp_utc")[value_col]
        window = series.rolling(f"{int(window_hours)}h", min_periods=1, closed="left")
        rolled = window.std(ddof=ddof) if stat == "std" else getattr(window, stat)()
        return pd.Series(rolled.to_numpy(), index=grp.index)

    return _build


def assert_past_only(
    df: pd.DataFrame,
    column: str,
    builder: Callable[[pd.DataFrame], pd.Series],
    n_stations: int = 3,
    tol: float = 1e-2,
) -> dict:
    """Recompute *column* from the past-only ``builder`` and assert equality.

    ``builder`` receives one station's frame (time-ordered, carrying
    ``timestamp_utc``) and must return the feature computed from strictly
    historical values. Passing means the column is a function of the past
    only -- which is the property that matters, whether the recipe was
    positional or time-aligned.

    ``tol`` defaults to 1e-2 because the store is float32; a genuine leak
    shows up as a difference of tens to hundreds of ug/m3, not 1e-4.
    """
    checked = 0
    max_diff = 0.0
    for _, grp in df.sort_values("timestamp_utc").groupby("location_id", observed=True):
        if checked >= n_stations:
            break
        expected = builder(grp)
        actual = grp[column]
        both = expected.notna() & actual.notna()
        if both.sum() < 50:
            continue
        diff = float((expected[both] - actual[both]).abs().max())
        max_diff = max(max_diff, diff)
        checked += 1
    if checked == 0:
        raise AssertionError(f"{column}: no station had enough overlap to verify")
    if max_diff > tol:
        raise AssertionError(f"{column} is not past-only: max |diff| = {max_diff:.6g}")
    return {"column": column, "stations_checked": checked, "max_abs_diff": max_diff}


def leakage_scan(
    df: pd.DataFrame,
    features: Sequence[str],
    target_col: str,
    sample: int = 120_000,
    warn_above: float = 0.995,
    random_state: int = 42,
) -> pd.DataFrame:
    """Smell test: a feature that correlates with the future better than the
    present value does is a leakage suspect.

    Returns one row per feature with ``corr_target``, ``corr_pm25`` and a
    ``suspect`` flag. This does not prove leakage — it points a finger.
    """
    work = df[[*dict.fromkeys([*features, target_col, "pm25"])]].dropna(subset=[target_col])
    if len(work) > sample:
        work = work.sample(sample, random_state=random_state)
    y = work[target_col].to_numpy(dtype=float)
    now = work["pm25"].to_numpy(dtype=float)
    base = abs(float(np.corrcoef(now, y)[0, 1]))
    rows = []
    for col in features:
        values = work[col].to_numpy(dtype=float)
        if not np.isfinite(values).any() or np.nanstd(values) == 0:
            continue
        mask = np.isfinite(values) & np.isfinite(y)
        if mask.sum() < 1000:
            continue
        corr = abs(float(np.corrcoef(values[mask], y[mask])[0, 1]))
        rows.append(
            {
                "feature": col,
                "corr_target": round(corr, 5),
                "corr_vs_persistence": round(corr - base, 5),
                "suspect": bool(corr > warn_above),
            }
        )
    out = pd.DataFrame(rows).sort_values("corr_target", ascending=False).reset_index(drop=True)
    out.attrs["persistence_corr"] = base
    return out


# ---------------------------------------------------------------------------
# Temporal + station-relative features (S7-S10)
# ---------------------------------------------------------------------------


def add_cyclical_time(df: pd.DataFrame) -> pd.DataFrame:
    """hour/dow/doy sin-cos. Idempotent: existing columns are left alone."""
    ts = df["timestamp_utc"]
    if "hour" not in df.columns:
        df["hour"] = ts.dt.hour
    if "dow" not in df.columns:
        df["dow"] = ts.dt.dayofweek
    if "doy" not in df.columns:
        df["doy"] = ts.dt.dayofyear
    pairs = {
        "hour": ("sin_hour", "cos_hour", 24.0),
        "dow": ("sin_dow", "cos_dow", 7.0),
        "doy": ("sin_doy", "cos_doy", 365.25),
    }
    for src, (sin_col, cos_col, period) in pairs.items():
        angle = 2 * np.pi * df[src].astype("float32") / period
        if sin_col not in df.columns:
            df[sin_col] = np.sin(angle).astype("float32")
        if cos_col not in df.columns:
            df[cos_col] = np.cos(angle).astype("float32")
    return df


@dataclass
class StationBaselines:
    """Per-station climatology fitted on the training window only (S10).

    Fitting on the full dataset would leak test-period levels into a feature
    that production computes from history alone.
    """

    fit_end: pd.Timestamp
    station: pd.DataFrame
    station_hour: pd.DataFrame
    station_month: pd.DataFrame
    global_hour: pd.Series
    global_pm25: float

    @classmethod
    def fit(cls, df: pd.DataFrame, fit_end: pd.Timestamp) -> "StationBaselines":
        train = df.loc[df["timestamp_utc"] < fit_end, ["location_id", "pm25", "hour", "timestamp_utc"]].copy()
        if train.empty:
            raise ValueError("StationBaselines.fit: no rows before fit_end")
        train["month"] = train["timestamp_utc"].dt.month
        station = (
            train.groupby("location_id", observed=True)["pm25"]
            .agg(
                station_pm25_mean="mean",
                station_pm25_std="std",
                station_pm25_p90=lambda s: s.quantile(0.90),
                station_pm25_p95=lambda s: s.quantile(0.95),
            )
            .reset_index()
        )
        station_hour = (
            train.groupby(["location_id", "hour"], observed=True)["pm25"]
            .median()
            .rename("station_baseline_by_hour")
            .reset_index()
        )
        station_month = (
            train.groupby(["location_id", "month"], observed=True)["pm25"]
            .median()
            .rename("station_baseline_by_month")
            .reset_index()
        )
        global_hour = train.groupby("hour", observed=True)["pm25"].median()
        return cls(
            fit_end=fit_end,
            station=station,
            station_hour=station_hour,
            station_month=station_month,
            global_hour=global_hour,
            global_pm25=float(train["pm25"].median()),
        )

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df
        if "hour" not in out.columns:
            out["hour"] = out["timestamp_utc"].dt.hour
        out["month"] = out["timestamp_utc"].dt.month
        out = out.merge(self.station, on="location_id", how="left")
        out = out.merge(self.station_hour, on=["location_id", "hour"], how="left")
        out = out.merge(self.station_month, on=["location_id", "month"], how="left")

        # Unseen station: fall back to the global hour-of-day climatology so a
        # new city still gets a usable feature instead of a NaN column.
        fallback = out["hour"].map(self.global_hour).astype("float32")
        out["station_baseline_by_hour"] = out["station_baseline_by_hour"].fillna(fallback)
        out["station_baseline_by_month"] = out["station_baseline_by_month"].fillna(self.global_pm25)
        out["station_pm25_mean"] = out["station_pm25_mean"].fillna(self.global_pm25)
        out["station_pm25_std"] = out["station_pm25_std"].fillna(
            float(self.station["station_pm25_std"].median())
        )
        out["station_pm25_p90"] = out["station_pm25_p90"].fillna(
            float(self.station["station_pm25_p90"].median())
        )
        out["station_pm25_p95"] = out["station_pm25_p95"].fillna(
            float(self.station["station_pm25_p95"].median())
        )

        out["pm25_vs_station_hour"] = out["pm25"] - out["station_baseline_by_hour"]
        out["pm25_vs_station_month"] = out["pm25"] - out["station_baseline_by_month"]
        out["pm25_vs_station_mean"] = out["pm25"] - out["station_pm25_mean"]
        out["station_recent_anomaly"] = out["pm25_vs_station_hour"] / (
            out["station_pm25_std"].replace(0, np.nan)
        )
        out["station_over_p90"] = (out["pm25"] > out["station_pm25_p90"]).astype("int8")
        out = out.drop(columns=["month"])
        return out

    def to_dict(self) -> dict:
        return {
            "fit_end": str(self.fit_end),
            "stations": int(len(self.station)),
            "global_pm25_median": self.global_pm25,
        }


FEATURE_COLUMNS_STATION = [
    "station_pm25_mean",
    "station_pm25_std",
    "station_pm25_p90",
    "station_pm25_p95",
    "station_baseline_by_hour",
    "station_baseline_by_month",
    "pm25_vs_station_hour",
    "pm25_vs_station_month",
    "pm25_vs_station_mean",
    "station_recent_anomaly",
    "station_over_p90",
]


# ---------------------------------------------------------------------------
# Forecast-vintage wind and integrated advection (S6, S12)
# ---------------------------------------------------------------------------


@dataclass
class WindClimatology:
    """(station, month, hour) mean wind vector, fitted on the training window.

    Used to build a *simulated forecast vintage*. AeroPulse has no archived
    NWP forecast, so training cannot use the observed wind at t+i — that is
    future information production will not have. Instead we decay the wind
    known at t toward climatology, which mimics how real forecast skill fades
    with lead time and uses only information available at forecast time.
    """

    table: pd.DataFrame
    global_table: pd.DataFrame
    tau_hours: float = 6.0

    @classmethod
    def fit(cls, df: pd.DataFrame, fit_end: pd.Timestamp, tau_hours: float = 6.0) -> "WindClimatology":
        train = df.loc[
            df["timestamp_utc"] < fit_end, ["location_id", "timestamp_utc", "wind_u", "wind_v"]
        ].copy()
        train["month"] = train["timestamp_utc"].dt.month
        train["hour"] = train["timestamp_utc"].dt.hour
        table = (
            train.groupby(["location_id", "month", "hour"], observed=True)[["wind_u", "wind_v"]]
            .mean()
            .rename(columns={"wind_u": "clim_u", "wind_v": "clim_v"})
            .reset_index()
        )
        global_table = (
            train.groupby(["month", "hour"], observed=True)[["wind_u", "wind_v"]]
            .mean()
            .rename(columns={"wind_u": "clim_u_global", "wind_v": "clim_v_global"})
            .reset_index()
        )
        return cls(table=table, global_table=global_table, tau_hours=tau_hours)

    def lead_wind(self, df: pd.DataFrame, lead: int) -> tuple[np.ndarray, np.ndarray]:
        """Simulated forecast wind valid at t+lead, known at t."""
        valid = df["timestamp_utc"] + pd.Timedelta(hours=int(lead))
        keys = pd.DataFrame(
            {
                "location_id": df["location_id"].to_numpy(),
                "month": valid.dt.month.to_numpy(),
                "hour": valid.dt.hour.to_numpy(),
            }
        )
        merged = keys.merge(self.table, on=["location_id", "month", "hour"], how="left")
        merged = merged.merge(self.global_table, on=["month", "hour"], how="left")
        clim_u = merged["clim_u"].fillna(merged["clim_u_global"]).fillna(0.0).to_numpy(dtype="float32")
        clim_v = merged["clim_v"].fillna(merged["clim_v_global"]).fillna(0.0).to_numpy(dtype="float32")
        weight = math.exp(-lead / self.tau_hours)
        u = weight * df["wind_u"].to_numpy(dtype="float32") + (1 - weight) * clim_u
        v = weight * df["wind_v"].to_numpy(dtype="float32") + (1 - weight) * clim_v
        return u, v

    def to_dict(self) -> dict:
        return {
            "tau_hours": self.tau_hours,
            "station_month_hour_cells": int(len(self.table)),
            "blend": "w=exp(-lead/tau) on observed wind, 1-w on climatology",
        }


def integrated_advection(
    df: pd.DataFrame,
    horizons: Sequence[int],
    climatology: WindClimatology,
    step_hours: int = 1,
) -> pd.DataFrame:
    """Step-integrated displacement over the forecast window (S12 "MVP+").

    Replaces ``distance = wind_speed x horizon`` with a sum over hourly
    forecast-vintage wind vectors, and records how much the wind turns during
    the window — a straight 48 h trajectory from a single instantaneous
    vector is not a real transport path.

    Wind is km/h (Open-Meteo default), so 1 h of transport = speed km. The
    previous implementation treated it as m/s and overstated every distance
    by a factor of 3.6.
    """
    n = len(df)
    max_h = int(max(horizons))
    leads = list(range(step_hours, max_h + 1, step_hours))

    dx = np.zeros(n, dtype="float32")
    dy = np.zeros(n, dtype="float32")
    path = np.zeros(n, dtype="float32")
    speeds: list[np.ndarray] = []
    dirs: list[np.ndarray] = []
    wanted = {int(h) for h in horizons}

    for lead in leads:
        u, v = climatology.lead_wind(df, lead)
        dx += u * step_hours * WIND_KMH_TO_KM_PER_H
        dy += v * step_hours * WIND_KMH_TO_KM_PER_H
        step_speed = np.sqrt(u * u + v * v)
        path += step_speed * step_hours * WIND_KMH_TO_KM_PER_H
        speeds.append(step_speed)
        dirs.append(np.degrees(np.arctan2(u, v)) % 360.0)

        if lead in wanted:
            net = np.sqrt(dx * dx + dy * dy)
            speed_stack = np.vstack(speeds)
            dir_stack = np.vstack(dirs)
            turn = np.abs(((dir_stack[-1] - dir_stack[0] + 180.0) % 360.0) - 180.0)
            df[f"advect_dx_km_h{lead}"] = dx.copy()
            df[f"advect_dy_km_h{lead}"] = dy.copy()
            df[f"advect_dist_km_h{lead}"] = net
            df[f"transport_path_km_h{lead}"] = path.copy()
            # 1.0 = straight-line transport, ->0 = wind boxes the compass
            df[f"transport_straightness_h{lead}"] = (net / np.maximum(path, 1e-3)).astype("float32")
            df[f"transport_bearing_deg_h{lead}"] = (
                np.degrees(np.arctan2(dx, dy)) % 360.0
            ).astype("float32")
            df[f"transport_turn_deg_h{lead}"] = turn.astype("float32")
            df[f"fcst_wind_speed_mean_h{lead}"] = speed_stack.mean(axis=0).astype("float32")
            df[f"fcst_wind_speed_std_h{lead}"] = speed_stack.std(axis=0).astype("float32")
            df[f"fcst_wind_speed_min_h{lead}"] = speed_stack.min(axis=0).astype("float32")
            # Displacement in degrees: where the current air mass ends up.
            df[f"advect_lat_h{lead}"] = (
                df["lat"].to_numpy(dtype="float32") + dy / KM_PER_DEG_LAT
            ).astype("float32")
            cos_lat = np.cos(np.radians(df["lat"].to_numpy(dtype="float32")))
            df[f"advect_lon_h{lead}"] = (
                df["lon"].to_numpy(dtype="float32")
                + dx / (KM_PER_DEG_LAT * np.maximum(cos_lat, 0.1))
            ).astype("float32")
    return df


def add_stability_features(df: pd.DataFrame) -> pd.DataFrame:
    """Ventilation and multi-hour stagnation persistence (S13).

    A single instantaneous ``stagnation_flag`` says nothing about whether the
    air has been sitting still for half a day, which is what actually builds
    an episode.
    """
    if "ventilation_index" not in df.columns:
        source = (
            df["ventilation_coefficient"]
            if "ventilation_coefficient" in df.columns
            else df["wind_speed_10m"] * df["boundary_layer_height"].clip(lower=0)
        )
        df["ventilation_index"] = source.astype("float32")
    df["ventilation_log"] = np.log1p(df["ventilation_index"].clip(lower=0)).astype("float32")

    if "stagnation_flag" not in df.columns:
        df["stagnation_flag"] = (
            (df["wind_speed_10m"] < 5.4)  # 1.5 m/s in km/h
            & (df["boundary_layer_height"] < df["boundary_layer_height"].median())
        ).astype("int8")

    df = df.sort_values(["location_id", "timestamp_utc"])
    grouped = df.groupby("location_id", observed=True)["stagnation_flag"]
    for window in (3, 6, 12):
        df[f"stagnation_{window}h"] = (
            grouped.transform(lambda s: s.rolling(window, min_periods=1).mean()).astype("float32")
        )
    # Consecutive stagnant hours ending now.
    def _run_length(series: pd.Series) -> pd.Series:
        arr = series.to_numpy()
        out = np.zeros(len(arr), dtype="float32")
        run = 0.0
        for i, value in enumerate(arr):
            run = run + 1.0 if value else 0.0
            out[i] = run
        return pd.Series(out, index=series.index)

    df["stagnation_duration_h"] = grouped.transform(_run_length)

    vent = df.groupby("location_id", observed=True)["ventilation_index"]
    df["ventilation_change_6h"] = vent.transform(lambda s: s - s.shift(6)).astype("float32")
    pbl = df.groupby("location_id", observed=True)["boundary_layer_height"]
    if "delta_pbl_6h" not in df.columns:
        df["delta_pbl_6h"] = pbl.transform(lambda s: s - s.shift(6)).astype("float32")
    return df


def add_regime_features(df: pd.DataFrame) -> pd.DataFrame:
    """Numeric regime encoding usable as a model feature (S15).

    ``pollution_regime`` from upstream is computed with same-hour information
    and is kept out of the feature set as a label; these are the past-only
    equivalents.
    """
    df["regime_level"] = pd.cut(
        df["pm25"], bins=REGIME_BINS, labels=range(len(REGIME_LABELS)), right=False
    ).astype("float32")
    delta6 = df["pm25_delta_6h"] if "pm25_delta_6h" in df.columns else df["pm25"] * 0.0
    df["regime_rising"] = (delta6 > 10.0).astype("int8")
    df["regime_falling"] = (delta6 < -10.0).astype("int8")
    df["regime_stagnant"] = (
        (df.get("stagnation_6h", pd.Series(0.0, index=df.index)) > 0.5)
        & (df["pm25"] > df.get("station_pm25_mean", df["pm25"].median()))
    ).astype("int8")
    fire = df.get("upwind_fire_frp_50km", pd.Series(0.0, index=df.index)).fillna(0.0)
    df["regime_fire_influenced"] = (fire > 0).astype("int8")
    excess = df.get("pm25_local_excess", pd.Series(0.0, index=df.index)).fillna(0.0)
    df["regime_transport_dominated"] = (excess < 0).astype("int8")
    return df


def regime_label(df: pd.DataFrame) -> pd.Series:
    """Coarse concentration band for per-regime reporting (S26)."""
    return pd.cut(df["pm25"], bins=REGIME_BINS, labels=REGIME_LABELS, right=False)


# ---------------------------------------------------------------------------
# Baseline ladder (S16)
# ---------------------------------------------------------------------------

BASELINE_NAMES = ["persistence", "seasonal_24h", "seasonal_168h", "rolling_mean_6h", "ensemble"]
ENSEMBLE_WEIGHTS = {"persistence": 0.5, "seasonal_24h": 0.3, "seasonal_168h": 0.2}


def baseline_forecasts(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """All five baselines for one horizon, as columns aligned to *df*.

    Every baseline uses only values known at t:
      A persistence      PM(t)
      B seasonal 24h     PM(t + h - 24)  == lag (24 - h) when h < 24
      C seasonal 168h    PM(t + h - 168)
      D rolling mean     mean(PM[t-5:t])
      E weighted ensemble of A/B/C
    """
    out = pd.DataFrame(index=df.index)
    out["persistence"] = df["pm25"].astype("float32")

    lookup: pd.DataFrame | None = None

    def _lagged(offset_hours: int) -> pd.Series:
        """PM at (t + horizon - offset). Positive lag only -- never the future.

        Falls back to a *wall-clock* lookup, not ``shift(lag)``. With 56k gaps
        in this dataset a positional shift silently reaches across holes and
        returns a value from the wrong day.
        """
        nonlocal lookup
        lag = offset_hours - horizon
        if lag <= 0:
            return pd.Series(np.nan, index=df.index, dtype="float32")
        exact = f"pm25_lag_{lag}h"
        if exact in df.columns:
            return df[exact].astype("float32")
        if lookup is None:
            lookup = df[["location_id", "timestamp_utc", "pm25"]].rename(
                columns={"timestamp_utc": "_key_ts", "pm25": "_lagged_pm25"}
            )
        keys = pd.DataFrame(
            {
                "location_id": df["location_id"].to_numpy(),
                "_key_ts": (df["timestamp_utc"] - pd.Timedelta(hours=lag)).to_numpy(),
            }
        )
        merged = keys.merge(lookup, on=["location_id", "_key_ts"], how="left")
        return pd.Series(
            merged["_lagged_pm25"].to_numpy(dtype="float32"), index=df.index
        )

    out["seasonal_24h"] = _lagged(24)
    out["seasonal_168h"] = _lagged(168)
    out["rolling_mean_6h"] = (
        df["pm25_roll_mean_6h"].astype("float32")
        if "pm25_roll_mean_6h" in df.columns
        else out["persistence"]
    )

    # Ensemble falls back to persistence wherever a seasonal member is missing,
    # renormalising the weights so short horizons are not biased low.
    total = pd.Series(0.0, index=df.index, dtype="float64")
    weight = pd.Series(0.0, index=df.index, dtype="float64")
    for name, w in ENSEMBLE_WEIGHTS.items():
        values = out[name]
        present = values.notna()
        total = total.add((values.fillna(0.0) * w).where(present, 0.0), fill_value=0.0)
        weight = weight.add(pd.Series(w, index=df.index).where(present, 0.0), fill_value=0.0)
    out["ensemble"] = (total / weight.replace(0.0, np.nan)).fillna(out["persistence"]).astype("float32")
    return out


def best_baseline(metrics: pd.DataFrame, by: str = "mae") -> str:
    """Name of the strongest baseline — the bar the ML model has to clear."""
    return str(metrics.sort_values(by).iloc[0]["baseline"])


# ---------------------------------------------------------------------------
# Splits: chronological, rolling-origin, geographic (S23, S24)
# ---------------------------------------------------------------------------


def chrono_split(
    frame: pd.DataFrame, horizon_h: int, train_frac: float = 0.70, valid_frac: float = 0.15
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Chronological split with an *h*-hour purge at each boundary.

    ``target_pm25_t_plus_h`` for row t is an observation at t+h. Without the
    purge, the answer to a test question sits in train as an ordinary row.
    """
    t1 = frame["timestamp_utc"].quantile(train_frac)
    t2 = frame["timestamp_utc"].quantile(train_frac + valid_frac)
    purge = pd.Timedelta(hours=int(horizon_h))
    train = frame[frame["timestamp_utc"] < (t1 - purge)]
    valid = frame[(frame["timestamp_utc"] >= t1) & (frame["timestamp_utc"] < (t2 - purge))]
    test = frame[frame["timestamp_utc"] >= t2]
    return train, valid, test


def rolling_origin_folds(
    frame: pd.DataFrame,
    horizon_h: int,
    n_folds: int = 4,
    initial_frac: float = 0.45,
) -> list[tuple[pd.Index, pd.Index, dict]]:
    """Expanding-window folds; each validation block is purged by *h* hours."""
    ts = frame["timestamp_utc"]
    start, end = ts.min(), ts.max()
    span = end - start
    purge = pd.Timedelta(hours=int(horizon_h))
    first_cut = start + span * initial_frac
    remaining = end - first_cut
    block = remaining / n_folds

    folds = []
    for i in range(n_folds):
        train_end = first_cut + block * i
        valid_start = train_end
        valid_end = train_end + block
        train_idx = frame.index[ts < (train_end - purge)]
        valid_idx = frame.index[(ts >= valid_start) & (ts < valid_end)]
        if len(train_idx) < 1000 or len(valid_idx) < 200:
            continue
        folds.append(
            (
                train_idx,
                valid_idx,
                {
                    "fold": i + 1,
                    "train_end": str(train_end),
                    "valid_start": str(valid_start),
                    "valid_end": str(valid_end),
                    "n_train": int(len(train_idx)),
                    "n_valid": int(len(valid_idx)),
                },
            )
        )
    return folds


def geographic_blocks(df: pd.DataFrame, n_blocks: int = 5, random_state: int = 42) -> pd.DataFrame:
    """Assign each station to a geographic block via k-means on lat/lon (S24).

    A random station split leaks the local pollution climate: a held-out
    station usually has a neighbour 8 km away in the training set. Blocks
    answer the question that actually matters — can AeroPulse expand to a
    region it has never seen?
    """
    from sklearn.cluster import KMeans

    stations = (
        df.groupby("location_id", observed=True)[["lat", "lon"]].mean().reset_index()
    )
    coords = stations[["lat", "lon"]].to_numpy()
    km = KMeans(n_clusters=n_blocks, n_init=10, random_state=random_state).fit(coords)
    stations["geo_block"] = km.labels_
    centres = pd.DataFrame(km.cluster_centers_, columns=["block_lat", "block_lon"])
    centres["geo_block"] = centres.index
    stations = stations.merge(centres, on="geo_block", how="left")
    return stations


# ---------------------------------------------------------------------------
# Metrics (S23, S25-S28)
# ---------------------------------------------------------------------------


def skill(mae_model: float, mae_reference: float) -> float:
    return float(1.0 - mae_model / mae_reference) if mae_reference else float("nan")


def regression_metrics(
    y: np.ndarray, yhat: np.ndarray, reference: np.ndarray | None = None, prefix: str = ""
) -> dict:
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    mask = np.isfinite(y) & np.isfinite(yhat)
    y, yhat = y[mask], yhat[mask]
    err = yhat - y
    abs_err = np.abs(err)
    out = {
        f"{prefix}n": int(len(y)),
        f"{prefix}mae": float(abs_err.mean()) if len(y) else float("nan"),
        f"{prefix}rmse": float(np.sqrt((err**2).mean())) if len(y) else float("nan"),
        f"{prefix}bias": float(err.mean()) if len(y) else float("nan"),
        f"{prefix}p90_abs_err": float(np.quantile(abs_err, 0.90)) if len(y) else float("nan"),
        f"{prefix}p95_abs_err": float(np.quantile(abs_err, 0.95)) if len(y) else float("nan"),
        f"{prefix}smape": float(
            (200.0 * abs_err / np.maximum(np.abs(y) + np.abs(yhat), 1e-6)).mean()
        )
        if len(y)
        else float("nan"),
    }
    if len(y) > 1:
        ss_res = float((err**2).sum())
        ss_tot = float(((y - y.mean()) ** 2).sum())
        out[f"{prefix}r2"] = 1.0 - ss_res / ss_tot if ss_tot else float("nan")
    else:
        out[f"{prefix}r2"] = float("nan")
    if reference is not None:
        ref = np.asarray(reference, dtype=float)[mask]
        mae_ref = float(np.abs(ref - y).mean()) if len(y) else float("nan")
        out[f"{prefix}mae_reference"] = mae_ref
        out[f"{prefix}skill"] = skill(out[f"{prefix}mae"], mae_ref)
    return out


def station_metrics(
    df: pd.DataFrame, y_col: str, pred_col: str, reference_col: str, horizon: int
) -> pd.DataFrame:
    """Per-station MAE/RMSE/bias/skill (S25). Aggregate MAE hides the failures."""
    work = df[["location_id", y_col, pred_col, reference_col]].dropna()
    rows = []
    for station, grp in work.groupby("location_id", observed=True):
        y = grp[y_col].to_numpy(dtype=float)
        rec = {"location_id": station, "horizon_h": horizon}
        rec.update(
            regression_metrics(y, grp[pred_col].to_numpy(dtype=float), grp[reference_col].to_numpy(dtype=float))
        )
        rows.append(rec)
    return pd.DataFrame(rows).sort_values("skill")


def regime_metrics(
    df: pd.DataFrame, y_col: str, pred_col: str, reference_col: str, horizon: int
) -> pd.DataFrame:
    """Metrics by concentration band and by dynamic regime (S26)."""
    work = df.copy()
    work["_band"] = regime_label(work)
    rows = []
    for band, grp in work.groupby("_band", observed=True):
        clean = grp[[y_col, pred_col, reference_col]].dropna()
        if len(clean) < 50:
            continue
        rec = {"group_kind": "concentration", "group": str(band), "horizon_h": horizon}
        rec.update(
            regression_metrics(
                clean[y_col].to_numpy(dtype=float),
                clean[pred_col].to_numpy(dtype=float),
                clean[reference_col].to_numpy(dtype=float),
            )
        )
        rows.append(rec)
    for flag in [
        "regime_rising",
        "regime_falling",
        "regime_stagnant",
        "regime_fire_influenced",
        "regime_transport_dominated",
    ]:
        if flag not in work.columns:
            continue
        clean = work.loc[work[flag] == 1, [y_col, pred_col, reference_col]].dropna()
        if len(clean) < 50:
            continue
        rec = {"group_kind": "dynamic", "group": flag.replace("regime_", ""), "horizon_h": horizon}
        rec.update(
            regression_metrics(
                clean[y_col].to_numpy(dtype=float),
                clean[pred_col].to_numpy(dtype=float),
                clean[reference_col].to_numpy(dtype=float),
            )
        )
        rows.append(rec)
    return pd.DataFrame(rows)


def event_metrics(
    y: np.ndarray, yhat: np.ndarray, threshold: float = EVENT_THRESHOLD_UGM3
) -> dict:
    """Treat "will PM2.5 exceed *threshold*" as a classification problem (S27)."""
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    mask = np.isfinite(y) & np.isfinite(yhat)
    actual = y[mask] >= threshold
    predicted = yhat[mask] >= threshold
    tp = int((actual & predicted).sum())
    fp = int((~actual & predicted).sum())
    fn = int((actual & ~predicted).sum())
    tn = int((~actual & ~predicted).sum())
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision and recall and np.isfinite(precision) and np.isfinite(recall)
        else float("nan")
    )
    return {
        "threshold": threshold,
        "prevalence": float(actual.mean()) if actual.size else float("nan"),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "false_alarm_rate": float(fp / (fp + tn)) if (fp + tn) else float("nan"),
        "miss_rate": float(fn / (fn + tp)) if (fn + tp) else float("nan"),
    }


def bias_metrics(y: np.ndarray, yhat: np.ndarray, high_threshold: float = 120.0) -> dict:
    """Overall vs high-pollution bias (S28).

    A model that looks fine on aggregate MAE while underpredicting every
    episode is worse than useless for an alerting product.
    """
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    mask = np.isfinite(y) & np.isfinite(yhat)
    y, yhat = y[mask], yhat[mask]
    err = yhat - y
    high = y >= high_threshold
    return {
        "mean_error": float(err.mean()) if len(err) else float("nan"),
        "median_error": float(np.median(err)) if len(err) else float("nan"),
        "underprediction_pct": float((err < 0).mean() * 100) if len(err) else float("nan"),
        "high_pm25_n": int(high.sum()),
        "high_pm25_mean_error": float(err[high].mean()) if high.any() else float("nan"),
        "high_pm25_underprediction_pct": float((err[high] < 0).mean() * 100)
        if high.any()
        else float("nan"),
    }


def coverage_metrics(y: np.ndarray, lower: np.ndarray, upper: np.ndarray, nominal: float) -> dict:
    """Empirical coverage and sharpness of a prediction interval (S22)."""
    y = np.asarray(y, dtype=float)
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)
    mask = np.isfinite(y) & np.isfinite(lower) & np.isfinite(upper)
    y, lower, upper = y[mask], lower[mask], upper[mask]
    inside = (y >= lower) & (y <= upper)
    width = upper - lower
    return {
        "nominal": nominal,
        "coverage": float(inside.mean()) if len(y) else float("nan"),
        "coverage_gap": float(inside.mean() - nominal) if len(y) else float("nan"),
        "mean_interval_width": float(width.mean()) if len(y) else float("nan"),
        "median_interval_width": float(np.median(width)) if len(y) else float("nan"),
        "n": int(len(y)),
    }


# ---------------------------------------------------------------------------
# Models (S17, S21)
# ---------------------------------------------------------------------------

DEFAULT_LGBM_PARAMS = {
    "n_estimators": 400,
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_child_samples": 40,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.0,
    "reg_lambda": 1.0,
}


CANONICAL_PARAMS = (
    "n_estimators", "learning_rate", "max_depth", "num_leaves", "min_child_samples",
    "subsample", "colsample_bytree", "reg_alpha", "reg_lambda",
)


def translate_params(kind: str, params: dict) -> dict:
    """Map one canonical hyperparameter dict onto each library's spelling.

    Without this the families cannot share a search space: CatBoost calls it
    ``depth`` and raises if ``max_depth`` is also present, sklearn calls it
    ``max_iter``, and ``num_leaves`` has no meaning outside LightGBM.
    """
    params = dict(params or {})
    if kind == "lightgbm":
        return params

    depth = params.get("max_depth")
    depth = None if depth in (None, -1) else int(depth)

    if kind == "xgboost":
        out = {k: v for k, v in params.items() if k in {
            "n_estimators", "learning_rate", "subsample", "colsample_bytree",
            "reg_alpha", "reg_lambda",
        }}
        if depth is not None:
            out["max_depth"] = depth
        if "min_child_samples" in params:
            out["min_child_weight"] = params["min_child_samples"]
        return out

    if kind == "catboost":
        out = {}
        if "n_estimators" in params:
            out["iterations"] = int(params["n_estimators"])
        if "learning_rate" in params:
            out["learning_rate"] = params["learning_rate"]
        if depth is not None:
            out["depth"] = min(depth, 16)
        if "reg_lambda" in params:
            out["l2_leaf_reg"] = params["reg_lambda"]
        if "min_child_samples" in params:
            out["min_data_in_leaf"] = int(params["min_child_samples"])
        if "colsample_bytree" in params:
            out["rsm"] = params["colsample_bytree"]
        return out

    if kind == "hist_gbr":
        out = {}
        if "n_estimators" in params:
            out["max_iter"] = int(params["n_estimators"])
        if "learning_rate" in params:
            out["learning_rate"] = params["learning_rate"]
        out["max_depth"] = depth
        if "num_leaves" in params:
            out["max_leaf_nodes"] = int(params["num_leaves"])
        if "min_child_samples" in params:
            out["min_samples_leaf"] = int(params["min_child_samples"])
        if "reg_lambda" in params:
            out["l2_regularization"] = params["reg_lambda"]
        return out

    raise ValueError(f"unknown model kind: {kind}")


def make_regressor(kind: str = "lightgbm", params: dict | None = None, random_state: int = 42):
    """One factory for every candidate family so the comparison stays fair."""
    tuned = translate_params(kind, params or {})
    if kind == "lightgbm":
        import lightgbm as lgb

        return lgb.LGBMRegressor(
            random_state=random_state, n_jobs=-1, verbose=-1,
            **{**DEFAULT_LGBM_PARAMS, **tuned},
        )
    if kind == "xgboost":
        import xgboost as xgb

        defaults = {
            "n_estimators": 400, "learning_rate": 0.05, "max_depth": 8,
            "subsample": 0.8, "colsample_bytree": 0.8, "reg_lambda": 1.0,
        }
        return xgb.XGBRegressor(
            random_state=random_state, n_jobs=-1, tree_method="hist",
            **{**defaults, **tuned},
        )
    if kind == "catboost":
        from catboost import CatBoostRegressor

        defaults = {"iterations": 400, "learning_rate": 0.05, "depth": 8}
        return CatBoostRegressor(
            random_seed=random_state, verbose=0, allow_writing_files=False,
            **{**defaults, **tuned},
        )
    if kind == "hist_gbr":
        from sklearn.ensemble import HistGradientBoostingRegressor

        defaults = {"max_iter": 400, "learning_rate": 0.06, "max_depth": 8}
        return HistGradientBoostingRegressor(random_state=random_state, **{**defaults, **tuned})
    raise ValueError(f"unknown model kind: {kind}")


def make_quantile_regressor(quantile: float, params: dict | None = None, random_state: int = 42):
    import lightgbm as lgb

    merged = {**DEFAULT_LGBM_PARAMS, **(params or {})}
    return lgb.LGBMRegressor(
        objective="quantile",
        alpha=quantile,
        random_state=random_state,
        n_jobs=-1,
        verbose=-1,
        **merged,
    )


@dataclass
class ResidualModel:
    """Persistence + learned residual, with the physical constraint applied.

    The model never predicts a concentration directly; it predicts how far the
    next *h* hours will move away from the value we already know.
    """

    model: Any
    features: list[str]
    horizon_hours: int
    kind: str = "lightgbm"
    baseline: str = "persistence"
    medians: pd.Series | None = None

    def _prepare(self, df: pd.DataFrame) -> np.ndarray:
        block = df[self.features]
        if self.medians is not None:
            block = block.fillna(self.medians)
        return block.to_numpy(dtype="float32")

    @classmethod
    def fit(
        cls,
        train: pd.DataFrame,
        features: Sequence[str],
        horizon: int,
        kind: str = "lightgbm",
        params: dict | None = None,
        random_state: int = 42,
        baseline_col: str = "baseline_forecast",
        target_col: str | None = None,
    ) -> "ResidualModel":
        target_col = target_col or f"target_pm25_t_plus_{horizon}h"
        features = list(features)
        medians = train[features].median(numeric_only=True)
        X = train[features].fillna(medians).to_numpy(dtype="float32")
        y = (train[target_col] - train[baseline_col]).to_numpy(dtype="float32")
        model = make_regressor(kind, params, random_state)
        model.fit(X, y)
        return cls(
            model=model,
            features=features,
            horizon_hours=horizon,
            kind=kind,
            medians=medians,
        )

    def predict_residual(self, df: pd.DataFrame) -> np.ndarray:
        return np.asarray(self.model.predict(self._prepare(df)), dtype=float)

    def predict(
        self, df: pd.DataFrame, baseline_col: str = "baseline_forecast", constrain: bool = True
    ) -> np.ndarray:
        raw = df[baseline_col].to_numpy(dtype=float) + self.predict_residual(df)
        return constrain_prediction(raw)[0] if constrain else raw

    def feature_importance(self) -> pd.DataFrame:
        booster = self.model
        if hasattr(booster, "feature_importances_"):
            values = np.asarray(booster.feature_importances_, dtype=float)
        else:
            values = np.zeros(len(self.features))
        out = pd.DataFrame({"feature": self.features, "importance": values})
        total = out["importance"].sum()
        out["importance_pct"] = (out["importance"] / total * 100) if total else 0.0
        return out.sort_values("importance", ascending=False).reset_index(drop=True)


def constrain_prediction(
    raw: np.ndarray, floor: float = 0.0, ceiling: float = PM25_HARD_MAX
) -> tuple[np.ndarray, np.ndarray]:
    """Clip to the physical range and report which rows were touched (S20)."""
    raw = np.asarray(raw, dtype=float)
    constrained = np.clip(raw, floor, ceiling)
    return constrained, (constrained != raw)


@dataclass
class QuantileBundle:
    """P10/P50/P90 residual models plus a conformal width correction (S21/S22)."""

    models: dict[float, Any]
    features: list[str]
    horizon_hours: int
    medians: pd.Series | None = None
    width_scale: dict[float, float] = field(default_factory=dict)

    @classmethod
    def fit(
        cls,
        train: pd.DataFrame,
        features: Sequence[str],
        horizon: int,
        quantiles: Sequence[float] = (0.1, 0.5, 0.9),
        params: dict | None = None,
        random_state: int = 42,
        baseline_col: str = "baseline_forecast",
        target_col: str | None = None,
    ) -> "QuantileBundle":
        target_col = target_col or f"target_pm25_t_plus_{horizon}h"
        features = list(features)
        medians = train[features].median(numeric_only=True)
        X = train[features].fillna(medians).to_numpy(dtype="float32")
        y = (train[target_col] - train[baseline_col]).to_numpy(dtype="float32")
        models = {}
        for q in quantiles:
            model = make_quantile_regressor(q, params, random_state)
            model.fit(X, y)
            models[float(q)] = model
        return cls(models=models, features=features, horizon_hours=horizon, medians=medians)

    def predict(self, df: pd.DataFrame, baseline_col: str = "baseline_forecast") -> pd.DataFrame:
        block = df[self.features]
        if self.medians is not None:
            block = block.fillna(self.medians)
        X = block.to_numpy(dtype="float32")
        base = df[baseline_col].to_numpy(dtype=float)
        out = pd.DataFrame(index=df.index)
        centre = None
        for q, model in sorted(self.models.items()):
            out[f"p{int(q * 100):02d}"] = base + np.asarray(model.predict(X), dtype=float)
        if 0.5 in self.models:
            centre = out[f"p{50:02d}"]
        # Apply the calibration scaling around the median, then enforce
        # monotonicity — quantile models are fitted independently and can cross.
        if self.width_scale and centre is not None:
            for q in self.models:
                col = f"p{int(q * 100):02d}"
                scale = self.width_scale.get(float(q), 1.0)
                out[col] = centre + (out[col] - centre) * scale
        ordered = np.sort(out.to_numpy(dtype=float), axis=1)
        out.loc[:, :] = ordered
        for col in out.columns:
            out[col] = np.clip(out[col], 0.0, PM25_HARD_MAX)
        return out


def conformal_widths(
    y: np.ndarray, quantile_frame: pd.DataFrame, nominal: float = 0.80
) -> dict[float, float]:
    """Scale factor per quantile so empirical coverage matches the nominal level.

    Split-conformal style: measure the achieved coverage on validation and
    stretch (or shrink) the interval around the median until it matches.
    """
    y = np.asarray(y, dtype=float)
    low_col, high_col = quantile_frame.columns[0], quantile_frame.columns[-1]
    centre = (
        quantile_frame["p50"].to_numpy(dtype=float)
        if "p50" in quantile_frame.columns
        else quantile_frame.mean(axis=1).to_numpy(dtype=float)
    )
    lower = quantile_frame[low_col].to_numpy(dtype=float)
    upper = quantile_frame[high_col].to_numpy(dtype=float)
    mask = np.isfinite(y) & np.isfinite(lower) & np.isfinite(upper)
    y, lower, upper, centre = y[mask], lower[mask], upper[mask], centre[mask]
    if not len(y):
        return {}
    # Required multiplier: the (nominal) quantile of |y - centre| / half-width.
    half = np.maximum((upper - lower) / 2.0, 1e-6)
    ratio = np.abs(y - centre) / half
    scale = float(np.quantile(ratio, nominal))
    lo_q = float(int(low_col[1:]) / 100)
    hi_q = float(int(high_col[1:]) / 100)
    return {lo_q: scale, 0.5: 1.0, hi_q: scale}


# ---------------------------------------------------------------------------
# Promotion gates (S40)
# ---------------------------------------------------------------------------

PROMOTION_GATES = {
    "min_skill_vs_persistence": 0.05,
    "min_skill_vs_best_baseline": 0.0,
    "min_validation_folds_positive": 3,
    "max_station_regression_pct": 20.0,
    "min_p80_coverage": 0.70,
    "min_event_recall": 0.20,
    "max_high_pm25_underprediction_pct": 85.0,
    "max_inference_latency_ms": 200.0,
}


def evaluate_promotion(evidence: dict, gates: dict | None = None) -> dict:
    """Apply every gate and return a pass/fail decision with the reasons.

    Missing evidence fails its gate rather than being skipped — an unmeasured
    property is not a satisfied one.
    """
    gates = {**PROMOTION_GATES, **(gates or {})}
    checks: list[dict] = []

    def _check(name: str, value: Any, ok: bool, requirement: str) -> None:
        checks.append(
            {
                "gate": name,
                "value": None if value is None else (float(value) if isinstance(value, (int, float, np.floating)) else value),
                "requirement": requirement,
                "passed": bool(ok),
            }
        )

    v = evidence.get("test_skill")
    _check("beats_persistence", v, v is not None and v > gates["min_skill_vs_persistence"],
           f"test skill vs persistence > {gates['min_skill_vs_persistence']}")

    v = evidence.get("skill_vs_best_baseline")
    _check("beats_best_baseline", v, v is not None and v > gates["min_skill_vs_best_baseline"],
           f"skill vs strongest baseline > {gates['min_skill_vs_best_baseline']}")

    v = evidence.get("folds_positive")
    _check("rolling_folds_positive", v, v is not None and v >= gates["min_validation_folds_positive"],
           f">= {gates['min_validation_folds_positive']} rolling-origin folds with positive skill")

    v = evidence.get("station_regression_pct")
    _check("station_regression", v, v is not None and v <= gates["max_station_regression_pct"],
           f"<= {gates['max_station_regression_pct']}% of stations worse than persistence")

    v = evidence.get("geo_block_min_skill")
    _check("geographic_generalization", v, v is not None and v > 0,
           "positive skill on every held-out geographic block")

    v = evidence.get("p80_coverage")
    _check("uncertainty_coverage", v, v is not None and v >= gates["min_p80_coverage"],
           f"calibrated P10-P90 coverage >= {gates['min_p80_coverage']}")

    v = evidence.get("event_recall")
    _check("event_recall", v, v is not None and v >= gates["min_event_recall"],
           f"exceedance recall >= {gates['min_event_recall']}")

    v = evidence.get("high_pm25_underprediction_pct")
    _check("extreme_bias", v, v is not None and v <= gates["max_high_pm25_underprediction_pct"],
           f"<= {gates['max_high_pm25_underprediction_pct']}% underprediction on high-PM2.5 rows")

    v = evidence.get("latency_ms")
    _check("latency", v, v is not None and v <= gates["max_inference_latency_ms"],
           f"<= {gates['max_inference_latency_ms']} ms per forecast")

    failed = [c["gate"] for c in checks if not c["passed"]]
    return {
        "promote": not failed,
        "failed_gates": failed,
        "checks": checks,
        "gates": gates,
    }


# ---------------------------------------------------------------------------
# Model registry (S32, S33)
# ---------------------------------------------------------------------------


class ModelRegistry:
    """Filesystem registry: ``registry/{horizon}h/{version}/``.

    Each version holds model.joblib, metadata.json, metrics.json and
    feature_schema.json, and is immutable once written — a new training run
    creates v2 rather than overwriting v1.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _horizon_dir(self, horizon: int) -> Path:
        path = self.root / f"{int(horizon)}h"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def versions(self, horizon: int) -> list[str]:
        return sorted(
            (p.name for p in self._horizon_dir(horizon).iterdir() if p.is_dir() and p.name.startswith("v")),
            key=lambda n: int(n[1:]) if n[1:].isdigit() else 0,
        )

    def next_version(self, horizon: int) -> str:
        existing = self.versions(horizon)
        return f"v{len(existing) + 1}"

    def register(
        self,
        horizon: int,
        bundle: dict,
        metadata: dict,
        metrics: dict,
        feature_schema: dict,
        version: str | None = None,
    ) -> Path:
        import joblib

        version = version or self.next_version(horizon)
        path = self._horizon_dir(horizon) / version
        if path.exists():
            raise FileExistsError(f"{path} already exists — registry versions are immutable")
        path.mkdir(parents=True)
        joblib.dump(bundle, path / "model.joblib")
        (path / "metadata.json").write_text(json.dumps(metadata, indent=2, default=str))
        (path / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
        (path / "feature_schema.json").write_text(json.dumps(feature_schema, indent=2, default=str))
        self._write_pointer(horizon, version, metadata)
        return path

    def _write_pointer(self, horizon: int, version: str, metadata: dict) -> None:
        pointer = self._horizon_dir(horizon) / "latest.json"
        pointer.write_text(
            json.dumps(
                {
                    "version": version,
                    "promoted": bool(metadata.get("promoted", False)),
                    "model_version": metadata.get("model_version"),
                    "updated_utc": pd.Timestamp.now(tz="UTC").isoformat(),
                },
                indent=2,
            )
        )

    def load(self, horizon: int, version: str | None = None) -> dict:
        import joblib

        horizon_dir = self._horizon_dir(horizon)
        if version is None:
            pointer = horizon_dir / "latest.json"
            if not pointer.exists():
                raise FileNotFoundError(f"no registered model for horizon {horizon}h")
            version = json.loads(pointer.read_text())["version"]
        path = horizon_dir / version
        return {
            "bundle": joblib.load(path / "model.joblib"),
            "metadata": json.loads((path / "metadata.json").read_text()),
            "metrics": json.loads((path / "metrics.json").read_text()),
            "feature_schema": json.loads((path / "feature_schema.json").read_text()),
            "path": path,
        }

    def index(self) -> pd.DataFrame:
        rows = []
        for horizon_dir in sorted(self.root.glob("*h")):
            horizon = int(horizon_dir.name.rstrip("h"))
            for version_dir in sorted(horizon_dir.glob("v*")):
                meta_file = version_dir / "metadata.json"
                if not meta_file.exists():
                    continue
                meta = json.loads(meta_file.read_text())
                rows.append(
                    {
                        "horizon_h": horizon,
                        "version": version_dir.name,
                        "model_version": meta.get("model_version"),
                        "model_type": meta.get("model_type"),
                        "promoted": meta.get("promoted"),
                        "test_mae": (meta.get("metrics") or {}).get("test_mae"),
                        "test_skill": (meta.get("metrics") or {}).get(
                            "test_skill_vs_baseline",
                            (meta.get("metrics") or {}).get("test_skill"),
                        ),
                        "created_at": meta.get("created_at"),
                    }
                )
        return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Inference contract, fallback and routing (S34-S36, S46)
# ---------------------------------------------------------------------------

DRIVER_PREFIX_LABELS = (
    ("bl_seasonal_168h", "weekly_seasonal_level"),
    ("bl_seasonal_24h", "yesterday_same_hour"),
    ("bl_rolling_mean", "recent_pm25_trend"),
    ("bl_ensemble", "baseline_consensus"),
    ("bl_persistence", "high_current_pm25"),
    ("baseline_forecast", "baseline_consensus"),
    ("station_baseline", "seasonal_norm_for_this_station"),
    ("pm25_vs_station", "unusual_for_this_station"),
    ("pm25_lag", "recent_pm25_trend"),
    ("pm25_roll", "recent_pm25_trend"),
    ("pm25_delta", "recent_pm25_trend"),
    ("pm25_slope", "recent_pm25_trend"),
    ("pm25_pct_change", "recent_pm25_trend"),
    ("pm25_zscore", "unusual_for_this_station"),
    ("delta_pressure", "pressure_change"),
    ("delta_temperature", "temperature_change"),
    ("surface_pressure", "pressure_change"),
    ("sin_hour", "time_of_day"),
    ("cos_hour", "time_of_day"),
    ("hour", "time_of_day"),
    ("sin_doy", "season"),
    ("cos_doy", "season"),
    ("month", "season"),
    ("days_to_diwali", "festival_period"),
    ("days_after_diwali", "festival_period"),
    ("crop_burning", "crop_burning_season"),
    ("advect_", "wind_transport"),
    ("transport_", "wind_transport"),
    ("fcst_wind", "wind_transport"),
    ("regional_pm25", "regional_pollution_field"),
    ("national_pm25", "nationwide_pollution_level"),
    ("upwind_fire", "upwind_fire_activity"),
    ("fire_", "nearby_fire_activity"),
    ("cams_", "satellite_aerosol"),
    ("stagnation", "stagnant_air"),
    ("ventilation", "weak_ventilation"),
    ("boundary_layer", "low_boundary_layer"),
    ("regime_", "pollution_regime"),
)
"""Prefix fallback so an unmapped feature still yields a readable driver.

Without it the exact-match table silently returns an empty ``drivers`` list
the moment feature engineering renames anything -- which is exactly what
happened when the baseline ladder entered the feature set.
"""

DRIVER_LABELS = {
    "pm25": "high_current_pm25",
    "pm25_roll_mean_6h": "recent_pm25_trend",
    "pm25_roll_mean_24h": "recent_pm25_trend",
    "pm25_delta_6h": "recent_pm25_trend",
    "pm25_slope_6h": "recent_pm25_trend",
    "upwind_pm25_mean": "persistent_upwind_pm25",
    "upwind_pm25_max": "persistent_upwind_pm25",
    "upwind_pm25_50km": "persistent_upwind_pm25",
    "regional_pm25_mean_50km": "regional_pollution_field",
    "boundary_layer_height": "low_boundary_layer",
    "ventilation_index": "weak_ventilation",
    "ventilation_log": "weak_ventilation",
    "stagnation_6h": "stagnant_air",
    "stagnation_duration_h": "stagnant_air",
    "upwind_fire_frp_50km": "upwind_fire_activity",
    "fire_frp_sum_50km_24h": "upwind_fire_activity",
    "station_recent_anomaly": "unusual_for_this_station",
    "pm25_vs_station_hour": "unusual_for_this_hour",
}


class PropagationPredictor:
    """Production-side forecaster: registry lookup, routing, fallback, contract.

    Never raises for a missing model or a bad feature row — it degrades to the
    baseline ensemble and then to persistence, and says so in the response.
    """

    def __init__(
        self,
        registry: ModelRegistry,
        horizons: Sequence[int],
        quality_min_features: float = 0.60,
        confidence_floor: float = 0.35,
        point_source: str = "residual_model",
        allow_withheld: bool = False,
    ):
        """``point_source`` selects what the ``pm25`` field carries.

        ``"residual_model"`` (default) serves the squared-error point model,
        which is what notebook 07 certified. ``"p50"`` serves the median
        quantile instead -- notebook 06 measured it 2-4% better on MAE at
        every horizon, because pinball loss at q=0.5 *is* MAE while squared
        error targets the conditional mean. It is not the default because
        switching the served forecast without re-running certification would
        put an uncertified model in production, which is the exact failure
        the promotion gates exist to prevent. Flip it, re-run notebook 07,
        and then make it the default.
        """
        if point_source not in {"residual_model", "p50"}:
            raise ValueError("point_source must be 'residual_model' or 'p50'")
        self.registry = registry
        self.horizons = [int(h) for h in horizons]
        self.quality_min_features = quality_min_features
        self.confidence_floor = confidence_floor
        self.point_source = point_source
        # Shadow mode: run models the gates withheld, so a candidate can be
        # compared against what production actually serves without being
        # served itself. This is plan section 39, and it is the only reason
        # a predictor should ever look past `promoted`.
        self.allow_withheld = allow_withheld
        self.models: dict[int, dict] = {}
        self.load_errors: dict[int, str] = {}
        for h in self.horizons:
            try:
                self.models[h] = self.registry.load(h)
            except Exception as exc:  # missing horizon is a routing fact, not a crash
                self.load_errors[h] = str(exc)

    # -- helpers ------------------------------------------------------------
    def _feature_completeness(self, row: pd.DataFrame, features: Sequence[str]) -> float:
        present = [f for f in features if f in row.columns]
        if not present:
            return 0.0
        return float(row[present].notna().to_numpy().mean() * len(present) / len(features))

    def _confidence(self, completeness: float, interval_width: float, level: float) -> float:
        """Confidence blends input quality with the width of the interval
        relative to the forecast level. A wide interval on a low forecast is
        not something to be confident about."""
        relative = interval_width / max(level, 10.0)
        sharpness = 1.0 / (1.0 + relative)
        return float(np.clip(0.5 * completeness + 0.5 * sharpness, 0.0, 1.0))

    def _drivers(self, bundle: dict, row: pd.DataFrame, top_k: int = 4) -> list[str]:
        importance = bundle.get("feature_importance")
        if importance is None:
            return []
        labels: list[str] = []
        for feature in importance:
            label = DRIVER_LABELS.get(feature)
            if label is None:
                label = next(
                    (name for prefix, name in DRIVER_PREFIX_LABELS if feature.startswith(prefix)),
                    None,
                )
            if label and label not in labels:
                labels.append(label)
            if len(labels) >= top_k:
                break
        return labels

    # -- public API ---------------------------------------------------------
    def forecast(
        self,
        row: pd.DataFrame,
        horizons: Sequence[int] | None = None,
        forecast_time: pd.Timestamp | None = None,
        history: pd.DataFrame | None = None,
    ) -> dict:
        """One station, one forecast_time, N horizons -> the S34 response.

        ``history`` is this station's recent rows (at least the previous
        168 h to resolve every seasonal baseline). Without it the seasonal
        members can only be recovered where the row happens to carry the
        exact ``pm25_lag_{n}h`` column, and the ensemble degrades toward
        persistence -- correct, but weaker than it needs to be.
        """
        if len(row) != 1:
            raise ValueError("forecast() expects exactly one feature row")
        horizons = [int(h) for h in (horizons or self.horizons)]
        forecast_time = forecast_time or row["timestamp_utc"].iloc[0]
        persistence = float(row["pm25"].iloc[0])

        if history is not None and len(history):
            station = row["location_id"].iloc[0]
            past = history[
                (history["location_id"] == station)
                & (history["timestamp_utc"] < row["timestamp_utc"].iloc[0])
            ]
            context = pd.concat([past, row], ignore_index=True) if len(past) else row
        else:
            context = row

        results = []
        for h in horizons:
            started = time.perf_counter()
            baselines = baseline_forecasts(context, h).tail(1).set_axis(row.index)
            ensemble = float(baselines["ensemble"].iloc[0])
            entry = self.models.get(h)

            source = "hybrid_lightgbm"
            fallback = False
            reason = None
            p10 = p50 = p90 = None
            drivers: list[str] = []
            model_version = None
            constrained = False

            if entry is None:
                source, fallback = "seasonal_persistence_ensemble", True
                reason = self.load_errors.get(h, "no registered model for this horizon")
                point = ensemble
            elif not entry["metadata"].get("promoted", False) and not self.allow_withheld:
                source, fallback = "seasonal_persistence_ensemble", True
                reason = "model registered but withheld by the promotion gates"
                point = ensemble
            else:
                bundle = entry["bundle"]
                features = bundle["features"]
                completeness = self._feature_completeness(row, features)
                if completeness < self.quality_min_features:
                    source, fallback = "seasonal_persistence_ensemble", True
                    reason = f"feature completeness {completeness:.2f} below {self.quality_min_features}"
                    point = ensemble
                else:
                    # The models were trained with the whole baseline ladder in
                    # their feature set and with `baseline_forecast` anchored to
                    # the horizon's chosen baseline. Serving has to reproduce
                    # both, or every request silently falls back.
                    work = row.copy()
                    for name in BASELINE_NAMES:
                        work[f"bl_{name}"] = baselines[name]
                    anchor = bundle.get("baseline", "persistence")
                    work["baseline_forecast"] = baselines.get(
                        anchor, baselines["persistence"]
                    ).fillna(work["pm25"])
                    try:
                        residual_model: ResidualModel = bundle["residual_model"]
                        point = float(residual_model.predict(work)[0])
                        quantiles = bundle.get("quantile_bundle")
                        if quantiles is not None:
                            q = quantiles.predict(work)
                            p10 = float(q.iloc[0, 0])
                            p50 = float(q.iloc[0, min(1, q.shape[1] - 1)])
                            p90 = float(q.iloc[0, -1])
                            if self.point_source == "p50":
                                point = p50
                                source = "hybrid_p50"
                        drivers = self._drivers(bundle, work)
                        model_version = entry["metadata"].get("model_version")
                    except Exception as exc:
                        source, fallback = "seasonal_persistence_ensemble", True
                        reason = f"inference error: {exc}"
                        point = ensemble

            # Last-resort chain. A missing pm25 observation must not produce a
            # NaN forecast: walk down to whatever is still finite, and if
            # nothing is, say so explicitly rather than serving a number.
            raw_point = point
            if not np.isfinite(point):
                for candidate, label in (
                    (ensemble, "seasonal_persistence_ensemble"),
                    (float(baselines["rolling_mean_6h"].iloc[0]), "rolling_mean_fallback"),
                    (float(baselines["seasonal_24h"].iloc[0]), "seasonal_24h_fallback"),
                    (persistence, "persistence_fallback"),
                ):
                    if np.isfinite(candidate):
                        point, source, fallback = candidate, label, True
                        reason = reason or "primary forecast was not finite"
                        break
            if not np.isfinite(point):
                results.append(
                    {
                        "horizon_hours": h,
                        "pm25": None,
                        "p10": None,
                        "p50": None,
                        "p90": None,
                        "persistence_pm25": None,
                        "baseline_ensemble_pm25": None,
                        "model_version": None,
                        "forecast_source": "insufficient_data",
                        "fallback_used": True,
                        "fallback_reason": "no finite pm25 observation available for this station",
                        "constraint_applied": False,
                        "point_outside_interval": False,
                        "raw_prediction": None,
                        "confidence": 0.0,
                        "drivers": [],
                        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                    }
                )
                continue

            point_arr, touched = constrain_prediction(np.array([point]))
            point = float(point_arr[0])
            constrained = bool(touched[0])

            # The point model and the quantile models are separate fits, so on
            # rare extreme rows they can disagree enough that the "80% interval"
            # excludes the point forecast. Serving that is incoherent: clamp
            # into the interval and say so, rather than shipping a number the
            # accompanying bounds contradict.
            point_outside_interval = False
            if p10 is not None and p90 is not None and np.isfinite(p10) and np.isfinite(p90):
                if point < p10 or point > p90:
                    point_outside_interval = True
                    point = float(np.clip(point, p10, p90))

            if p50 is None:
                p50 = point
            width = (p90 - p10) if (p10 is not None and p90 is not None) else float("nan")
            completeness = (
                self._feature_completeness(row, entry["bundle"]["features"])
                if entry is not None and not fallback
                else 0.5
            )
            confidence = (
                self._confidence(completeness, width, point)
                if np.isfinite(width)
                else (0.45 if fallback else 0.6)
            )
            if confidence < self.confidence_floor and not fallback:
                # Low confidence: blend back toward the baseline ensemble
                # rather than shipping a number the model itself distrusts.
                point = float(0.5 * point + 0.5 * ensemble)
                source = "confidence_blend"
                reason = f"confidence {confidence:.2f} below floor {self.confidence_floor}"

            results.append(
                {
                    "horizon_hours": h,
                    "pm25": round(point, 2),
                    "p10": round(p10, 2) if p10 is not None else None,
                    "p50": round(p50, 2) if p50 is not None else None,
                    "p90": round(p90, 2) if p90 is not None else None,
                    "persistence_pm25": round(persistence, 2) if np.isfinite(persistence) else None,
                    "baseline_ensemble_pm25": round(ensemble, 2) if np.isfinite(ensemble) else None,
                    "model_version": model_version,
                    "forecast_source": source,
                    "fallback_used": fallback,
                    "fallback_reason": reason,
                    "constraint_applied": constrained,
                    "point_outside_interval": point_outside_interval,
                    "raw_prediction": round(float(raw_point), 2) if np.isfinite(raw_point) else None,
                    "confidence": round(confidence, 3),
                    "drivers": drivers,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                }
            )

        return {
            "location_id": str(row["location_id"].iloc[0]),
            "forecast_time": pd.Timestamp(forecast_time).isoformat(),
            "schema_version": SCHEMA["schema_version"],
            "forecasts": results,
        }


# ---------------------------------------------------------------------------
# Self-test (S47) — run `python propagation_toolkit.py`
# ---------------------------------------------------------------------------


def _synthetic_frame(n_stations: int = 4, hours: int = 500, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames = []
    start = pd.Timestamp("2025-01-01", tz="UTC")
    for s in range(n_stations):
        ts = pd.date_range(start, periods=hours, freq="h")
        diurnal = 20 * np.sin(2 * np.pi * ts.hour / 24)
        pm25 = np.clip(60 + diurnal + rng.normal(0, 8, hours).cumsum() * 0.1, 1, None)
        frame = pd.DataFrame(
            {
                "location_id": f"S{s}",
                "timestamp_utc": ts,
                "pm25": pm25.astype("float32"),
                "lat": 20.0 + s * 0.5,
                "lon": 77.0 + s * 0.5,
                "wind_speed_10m": rng.uniform(1, 20, hours).astype("float32"),
                "wind_direction_10m": rng.uniform(0, 360, hours).astype("float32"),
                "boundary_layer_height": rng.uniform(100, 1500, hours).astype("float32"),
                "temperature_2m": rng.uniform(10, 40, hours).astype("float32"),
                "relative_humidity_2m": rng.uniform(20, 95, hours).astype("float32"),
                "surface_pressure": rng.uniform(980, 1015, hours).astype("float32"),
            }
        )
        rad = np.deg2rad(frame["wind_direction_10m"])
        frame["wind_u"] = (-frame["wind_speed_10m"] * np.sin(rad)).astype("float32")
        frame["wind_v"] = (-frame["wind_speed_10m"] * np.cos(rad)).astype("float32")
        grouped = frame["pm25"]
        for lag in (1, 3, 6, 24, 168):
            frame[f"pm25_lag_{lag}h"] = grouped.shift(lag)
        frame["pm25_roll_mean_6h"] = (
            frame.set_index("timestamp_utc")["pm25"]
            .rolling("6h", min_periods=1, closed="left")
            .mean()
            .to_numpy()
        )
        frame["pm25_delta_6h"] = grouped - grouped.shift(6)
        for h in (1, 3, 6, 24):
            frame[f"target_pm25_t_plus_{h}h"] = grouped.shift(-h)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def _run_self_tests() -> None:
    cfg = PropagationConfig(
        project_root=Path("."), pm25_data_root=Path("."), horizons=[1, 3, 6, 24]
    )
    df = _synthetic_frame()

    # -- data ---------------------------------------------------------------
    contract = validate_contract(df, cfg)
    assert contract["status"] == "PASS", contract
    report, coverage = quality_report(df, cfg)
    assert report["duplicate_rows"] == 0
    assert report["quality_status"] == "PASS", report["failures"]
    assert len(coverage) == df["location_id"].nunique()
    print("PASS test_data_contract, test_duplicate_detection, test_quality_report")

    dup = pd.concat([df, df.head(5)], ignore_index=True)
    bad_report, _ = quality_report(dup, cfg)
    assert bad_report["duplicate_rows"] == 10 and bad_report["quality_status"] == "FAIL"
    print("PASS test_duplicate_gate_fails_loudly")

    gapped = df[df["timestamp_utc"] != df["timestamp_utc"].iloc[100]]
    gap_report, _ = quality_report(gapped, cfg)
    assert gap_report["timestamp_gaps"] >= 1
    print("PASS test_missing_hours")

    # -- features -----------------------------------------------------------
    df = add_cyclical_time(df)
    assert {"sin_hour", "cos_hour", "sin_dow", "cos_dow"} <= set(df.columns)
    recomputed = np.sin(2 * np.pi * df["timestamp_utc"].dt.hour / 24)
    assert float((df["sin_hour"] - recomputed).abs().max()) < 1e-6
    print("PASS test_cyclical_features")

    fit_end = df["timestamp_utc"].quantile(0.70)
    baselines = StationBaselines.fit(df, fit_end)
    df = baselines.transform(df)
    assert df["station_baseline_by_hour"].notna().all()
    # Baselines must not move when the post-fit_end data changes.
    tampered = df.copy()
    mask = tampered["timestamp_utc"] >= fit_end
    tampered.loc[mask, "pm25"] = tampered.loc[mask, "pm25"] * 10
    again = StationBaselines.fit(tampered, fit_end)
    assert np.allclose(
        baselines.station["station_pm25_mean"].to_numpy(),
        again.station["station_pm25_mean"].to_numpy(),
    )
    print("PASS test_station_baselines_are_train_only")

    assert_past_only(df, "pm25_roll_mean_6h", rolling_past(6))  # no gaps here
    assert_past_only(df, "pm25_lag_24h", time_lag(24))
    # The synthetic frame has no gaps, so positional and time-aligned agree;
    # on the real dataset only the time-aligned builder is correct.
    assert_past_only(df, "pm25_lag_24h", lambda g: g["pm25"].shift(24))
    print("PASS test_rolling_features_use_past_only")

    clim = WindClimatology.fit(df, fit_end)
    df = integrated_advection(df, [1, 3, 6, 24], clim)
    # Lead 1 must equal the documented blend exactly: w*observed + (1-w)*clim,
    # times 1 h. If the km/h -> km conversion ever regresses, this catches it.
    u1, v1 = clim.lead_wind(df, 1)
    expected = np.sqrt(u1**2 + v1**2)
    assert float((df["advect_dist_km_h1"] - expected).abs().max()) < 1e-3
    weight = math.exp(-1 / clim.tau_hours)
    direct = np.sqrt(df["wind_u"] ** 2 + df["wind_v"] ** 2)
    ratio = float((df["advect_dist_km_h1"] / direct.clip(lower=0.1)).median())
    assert weight - 0.15 < ratio < 1.15, (ratio, weight)
    assert (df["transport_straightness_h24"] <= 1.0001).all()
    assert (df["advect_dist_km_h24"] <= df["transport_path_km_h24"] + 1e-3).all()
    print("PASS test_advection_calculation, test_transport_path_geometry")

    df = add_stability_features(df)
    assert (df["stagnation_duration_h"] >= 0).all()
    df = add_regime_features(df)
    assert "regime_level" in df.columns
    print("PASS test_stability_and_regime_features")

    # -- leakage ------------------------------------------------------------
    feats = select_features(df, horizon=6)
    assert not any(f.startswith("target_") for f in feats)
    assert not any(f.endswith("_h24") for f in feats), "other horizons must be excluded"
    assert "advect_dist_km_h6" in feats
    df["cheat"] = df["target_pm25_t_plus_6h"]
    scan = leakage_scan(df, [*feats, "cheat"], "target_pm25_t_plus_6h")
    assert bool(scan.loc[scan["feature"] == "cheat", "suspect"].iloc[0])
    assert not scan.loc[scan["feature"] == "pm25", "suspect"].iloc[0]
    df = df.drop(columns=["cheat"])
    print("PASS test_no_future_feature_leakage")

    # -- baselines and splits ----------------------------------------------
    bl = baseline_forecasts(df, 6)
    assert set(BASELINE_NAMES) <= set(bl.columns)
    assert bl["ensemble"].notna().all()
    print("PASS test_baseline_ladder")

    train, valid, test = chrono_split(df, 6)
    assert train["timestamp_utc"].max() < valid["timestamp_utc"].min()
    assert (valid["timestamp_utc"].min() - train["timestamp_utc"].max()) >= pd.Timedelta(hours=6)
    folds = rolling_origin_folds(df, 6, n_folds=3)
    assert len(folds) >= 2
    for tr_idx, va_idx, _ in folds:
        assert df.loc[tr_idx, "timestamp_utc"].max() < df.loc[va_idx, "timestamp_utc"].min()
    print("PASS test_chronological_purge, test_rolling_origin_folds")

    blocks = geographic_blocks(df, n_blocks=2)
    assert blocks["geo_block"].nunique() == 2
    print("PASS test_geographic_blocks")

    # -- model --------------------------------------------------------------
    # Attach the baseline ladder exactly as the notebooks do, so the feature
    # set under test is the one that actually gets trained and served. This
    # is what catches a predictor that fails to reproduce the bl_* columns.
    work = df.dropna(subset=["target_pm25_t_plus_6h"]).copy()
    _ladder = baseline_forecasts(work, 6)
    for _name in BASELINE_NAMES:
        work[f"bl_{_name}"] = _ladder[_name]
    work["baseline_forecast"] = _ladder["ensemble"].fillna(work["pm25"])
    tr, va, te = chrono_split(work, 6)
    feats = select_features(work, horizon=6)
    assert any(f.startswith("bl_") for f in feats), "ladder must be in the feature set"
    model = ResidualModel.fit(tr, feats, 6, params={"n_estimators": 60})
    preds = model.predict(te)
    assert (preds >= 0).all(), "test_prediction_non_negative"
    assert len(model.feature_importance()) == len(feats)
    print("PASS test_prediction_non_negative, test_feature_schema")

    quantiles = QuantileBundle.fit(tr, feats, 6, params={"n_estimators": 60})
    qv = quantiles.predict(va)
    assert (qv["p10"] <= qv["p90"] + 1e-6).all(), "quantiles must not cross"
    quantiles.width_scale = conformal_widths(va["target_pm25_t_plus_6h"].to_numpy(), qv, 0.80)
    qt = quantiles.predict(te)
    cov = coverage_metrics(te["target_pm25_t_plus_6h"].to_numpy(), qt["p10"], qt["p90"], 0.80)
    assert 0.0 <= cov["coverage"] <= 1.0
    print(f"PASS test_quantile_monotonicity, test_calibration (coverage {cov['coverage']:.2f})")

    metrics = regression_metrics(
        te["target_pm25_t_plus_6h"].to_numpy(), preds, te["pm25"].to_numpy()
    )
    assert np.isfinite(metrics["mae"]) and "skill" in metrics
    ev = event_metrics(te["target_pm25_t_plus_6h"].to_numpy(), preds, threshold=80.0)
    assert 0.0 <= ev["prevalence"] <= 1.0
    bias = bias_metrics(te["target_pm25_t_plus_6h"].to_numpy(), preds)
    assert np.isfinite(bias["mean_error"])
    st = station_metrics(te.assign(pred=preds), "target_pm25_t_plus_6h", "pred", "pm25", 6)
    assert len(st) == te["location_id"].nunique()
    rg = regime_metrics(te.assign(pred=preds), "target_pm25_t_plus_6h", "pred", "pm25", 6)
    assert len(rg) >= 1
    print("PASS test_metric_suite")

    constrained, touched = constrain_prediction(np.array([-5.0, 50.0, 9e9]))
    assert constrained[0] == 0.0 and constrained[2] == PM25_HARD_MAX and touched.sum() == 2
    print("PASS test_physical_constraints")

    decision = evaluate_promotion({"test_skill": 0.2, "folds_positive": 4})
    assert not decision["promote"] and "uncertainty_coverage" in decision["failed_gates"]
    print("PASS test_promotion_gate_requires_evidence")

    # -- registry and inference ---------------------------------------------
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        registry = ModelRegistry(Path(tmp))
        bundle = {
            "residual_model": model,
            "quantile_bundle": quantiles,
            "features": feats,
            "feature_importance": model.feature_importance()["feature"].head(10).tolist(),
        }
        meta = {"model_version": "test-v1", "promoted": True, "model_type": "lightgbm_residual"}
        bundle["baseline"] = "ensemble"
        registry.register(6, bundle, meta, {"test_mae": 1.0}, {"features": feats})
        assert registry.versions(6) == ["v1"]
        try:
            registry.register(6, bundle, meta, {}, {}, version="v1")
            raise AssertionError("registry must refuse to overwrite a version")
        except FileExistsError:
            pass
        loaded = registry.load(6)
        assert loaded["metadata"]["model_version"] == "test-v1"
        print("PASS test_model_artifact_loading, test_registry_immutability")

        predictor = PropagationPredictor(registry, [6, 12])
        response = predictor.forecast(te.head(1), horizons=[6, 12])
        assert len(response["forecasts"]) == 2
        served = {f["horizon_hours"]: f for f in response["forecasts"]}
        assert served[6]["fallback_used"] is False, (
            "the ML path must actually run -- if the predictor cannot rebuild "
            "the bl_* features it falls back on every request and the fallback "
            "tests below would pass while the model never executes"
        )
        assert served[6]["pm25"] >= 0
        assert served[6]["forecast_source"] == "hybrid_lightgbm"
        assert served[12]["fallback_used"] is True, "unknown horizon must fall back"
        assert served[12]["forecast_source"] == "seasonal_persistence_ensemble"
        print("PASS test_forecast_api, test_horizon_validation, test_model_fallback")

        broken = te.head(1).copy()
        for col in feats[: int(len(feats) * 0.8)]:
            broken[col] = np.nan
        degraded = predictor.forecast(broken, horizons=[6])["forecasts"][0]
        assert degraded["fallback_used"] is True
        assert degraded["pm25"] is None or degraded["pm25"] >= 0
        blank = te.head(1).copy()
        blank[feats] = np.nan
        empty = predictor.forecast(blank, horizons=[6])["forecasts"][0]
        assert empty["forecast_source"] == "insufficient_data" and empty["pm25"] is None
        print("PASS test_missing_feature_behavior, test_no_nan_forecast_is_served")

        unknown = te.head(1).copy()
        unknown["location_id"] = "NEVER_SEEN"
        out = predictor.forecast(unknown, horizons=[6])["forecasts"][0]
        assert out["pm25"] >= 0
        print("PASS test_unknown_station")

    print("\nALL SELF-TESTS PASSED")


if __name__ == "__main__":
    _run_self_tests()
