"""AeroPulse source-likelihood toolkit.

Shared library behind notebooks 01-09. Implements the architecture in
``AeroPulse_Source_Likelihood_ML_Improvement_Plan.md``: multi-label source
hypotheses (S4/S22), independent labeling functions with reliability weights
(S5/S6), weak-label aggregation (S23), conflict detection and abstention
(S7/S33), evidence provenance and availability (S9-S12/S38), source-specific
classifiers and calibration (S21/S25), event/temporal/spatial validation
(S29-S31), a registry (S40) and an explainable inference contract (S34/S35).

The single most important thing this module changes about the previous
implementation: **source labels are no longer mutually exclusive.** The old
``weak_source_labels`` assigned one class per row through a priority chain in
which later rules overwrote earlier ones, so a row with both fire evidence
and transport evidence came out as ``biomass_burning`` only. Every function
here produces one score per source, independently.

Scientific constraint, repeated because it governs how every output may be
used: these are **likelihoods derived from heuristics**, not measured source
attribution. No public ground-truth attribution catalogue exists for this
dataset. A model that scores well here has reproduced its own labeling
system, which is not the same as being right.
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
    "SourceConfig",
    "load_config",
    "SOURCES",
    "SCHEMA",
    "validate_contract",
    "quality_report",
    "dataset_fingerprint",
    "EVIDENCE_PROVENANCE",
    "add_evidence_availability",
    "add_pollutant_features",
    "add_transport_features",
    "add_station_context",
    "LabelingFunction",
    "LABELING_FUNCTIONS",
    "apply_labeling_functions",
    "aggregate_weak_labels",
    "conflict_report",
    "select_features",
    "assert_no_label_leakage",
    "chrono_split",
    "event_split",
    "geographic_blocks",
    "build_events",
    "make_classifier",
    "SourceClassifier",
    "calibration_metrics",
    "reliability_curve",
    "tune_thresholds",
    "PROMOTION_GATES",
    "evaluate_promotion",
    "SourceRegistry",
    "SourceLikelihoodPredictor",
    "gold_set_sample",
]

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SOURCES = (
    "biomass_burning",
    "traffic",
    "industrial",
    "dust",
    "regional_transport",
)
"""The five source hypotheses. ``mixed_unknown`` is deliberately NOT here.

Plan section 8: "unknown" means the evidence is insufficient or inseparable,
which is a statement about our knowledge rather than about the atmosphere.
Modelling it as a sixth competing class makes the classifier learn "predict
unknown" as a winning strategy, because it is the majority label. It is
derived at the end instead, from the absence of confident source scores.
"""

SCHEMA: dict[str, Any] = {
    "schema_version": "2.0.0",
    "label_schema_version": "2.0.0",
    "sources": list(SOURCES),
    "required": [
        "timestamp_utc",
        "location_id",
        "lat",
        "lon",
        "pm25",
        "temperature_2m",
        "relative_humidity_2m",
        "wind_speed_10m",
        "wind_direction_10m",
    ],
    "evidence": [
        "cams_no2",
        "cams_co",
        "cams_so2",
        "cams_o3",
        "cams_pm10",
        "cams_dust",
        "upwind_fire_frp_50km",
        "upwind_pm25_mean",
        "boundary_layer_height",
    ],
    "ranges": {
        "pm25": (0.0, 2000.0),
        "lat": (6.0, 38.0),
        "lon": (66.0, 98.0),
        "wind_speed_10m": (0.0, 200.0),
        "relative_humidity_2m": (0.0, 100.0),
        "cams_pm10": (0.0, 10000.0),
        "cams_no2": (0.0, 1000.0),
    },
    "units": {
        "pm25": "ug/m3",
        "cams_pm10": "ug/m3",
        "cams_no2": "ug/m3",
        "cams_co": "ug/m3",
        "cams_so2": "ug/m3",
        "cams_o3": "ug/m3",
        "wind_speed_10m": "km/h",
        "wind_direction_10m": "degrees_from",
    },
}


# ---------------------------------------------------------------------------
# Provenance and availability (S9-S12, S38)
# ---------------------------------------------------------------------------

EVIDENCE_PROVENANCE = {
    "pm25": {
        "measurement_source": "CPCB/OpenAQ",
        "kind": "measurement",
        "latency_minutes": 60,
        "reliability": 0.95,
    },
    "cams_*": {
        "measurement_source": "CAMS (Open-Meteo air quality)",
        "kind": "model_analysis",
        "latency_minutes": 300,
        "reliability": 0.55,
        "caveat": (
            "CAMS is chemical-transport model output driven by an emissions "
            "inventory, not a measurement. Using cams_no2 as traffic evidence "
            "partly reads back CAMS's own traffic inventory -- treat any "
            "co-pollutant-driven likelihood as weaker than its number suggests."
        ),
    },
    "fire_*": {
        "measurement_source": "NASA FIRMS (VIIRS/MODIS)",
        "kind": "satellite_detection",
        "latency_minutes": 180,
        "reliability": 0.90,
    },
    "weather_*": {
        "measurement_source": "Open-Meteo / ERA5",
        "kind": "reanalysis",
        "latency_minutes": 60,
        "reliability": 0.85,
    },
    "upwind_*": {
        "measurement_source": "derived from the station network",
        "kind": "derived",
        "latency_minutes": 60,
        "reliability": 0.75,
    },
}


def add_evidence_availability(df: pd.DataFrame) -> pd.DataFrame:
    """Availability flags per evidence family (S12, S38).

    Missing evidence and negative evidence are different claims. "No fire was
    detected" supports *against* biomass burning; "the fire feed was down"
    supports nothing at all. Without these flags a labeling function cannot
    tell them apart, and the model inherits false confidence.
    """
    df["evidence_pm25_available"] = df["pm25"].notna().astype("int8")

    copollutants = [c for c in ("cams_no2", "cams_co", "cams_so2", "cams_o3", "cams_pm10") if c in df.columns]
    df["evidence_copollutant_available"] = (
        df[copollutants].notna().all(axis=1).astype("int8") if copollutants else np.int8(0)
    )
    for column in copollutants:
        df[f"{column}_available"] = df[column].notna().astype("int8")

    fire_cols = [c for c in df.columns if c.startswith("fire_count_")]
    df["evidence_fire_available"] = (
        df[fire_cols].notna().any(axis=1).astype("int8") if fire_cols else np.int8(0)
    )
    weather_cols = [c for c in ("wind_speed_10m", "wind_direction_10m", "relative_humidity_2m",
                                "boundary_layer_height") if c in df.columns]
    df["evidence_weather_available"] = df[weather_cols].notna().all(axis=1).astype("int8")
    df["evidence_upwind_available"] = (
        df["upwind_pm25_mean"].notna().astype("int8")
        if "upwind_pm25_mean" in df.columns
        else np.int8(0)
    )
    if "satellite_observation_available" in df.columns:
        df["evidence_satellite_available"] = (
            df["satellite_observation_available"].fillna(0).astype("int8")
        )
    else:
        df["evidence_satellite_available"] = np.int8(0)

    families = [
        "evidence_pm25_available",
        "evidence_copollutant_available",
        "evidence_fire_available",
        "evidence_weather_available",
        "evidence_upwind_available",
    ]
    df["evidence_coverage"] = df[families].mean(axis=1).astype("float32")
    return df


EVIDENCE_QUALITY_BINS = [0.0, 0.5, 0.8, 1.01]
EVIDENCE_QUALITY_LABELS = ["LOW", "MEDIUM", "HIGH"]


def evidence_quality(coverage: pd.Series) -> pd.Series:
    """HIGH/MEDIUM/LOW from evidence coverage (S37)."""
    return pd.cut(coverage, bins=EVIDENCE_QUALITY_BINS,
                  labels=EVIDENCE_QUALITY_LABELS, right=False)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class SourceConfig:
    project_root: Path
    pm25_data_root: Path
    schema_version: str = "2.0.0"
    train_fraction: float = 0.70
    validation_fraction: float = 0.15
    max_train_rows: int | None = None
    geographic_blocks: int = 5
    gold_set_size: int = 300
    random_state: int = 42
    enable_copollutants: bool = False

    @property
    def data_root(self) -> Path:
        return self.project_root / "data" / "source"

    @property
    def base_dir(self) -> Path:
        return self.data_root / "processed" / "base"

    @property
    def feature_dir(self) -> Path:
        return self.data_root / "processed" / "features"

    @property
    def label_dir(self) -> Path:
        return self.data_root / "processed" / "labels"

    @property
    def artifact_dir(self) -> Path:
        return self.project_root / "artifacts" / "source"

    @property
    def registry_dir(self) -> Path:
        return self.artifact_dir / "registry"

    @property
    def event_aware_file(self) -> Path:
        return (self.pm25_data_root / "data" / "pm25" / "processed"
                / "event_aware" / "pm25_event_aware_features.parquet")

    def stage_dir(self, name: str) -> Path:
        path = self.artifact_dir / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_dirs(self) -> None:
        for path in [self.data_root, self.base_dir, self.feature_dir,
                     self.label_dir, self.artifact_dir, self.registry_dir]:
            path.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict:
        return {
            "project_root": str(self.project_root),
            "pm25_data_root": str(self.pm25_data_root),
            "schema_version": self.schema_version,
            "train_fraction": self.train_fraction,
            "validation_fraction": self.validation_fraction,
            "max_train_rows": self.max_train_rows,
            "geographic_blocks": self.geographic_blocks,
            "gold_set_size": self.gold_set_size,
        }


def load_config(verbose: bool = True) -> SourceConfig:
    from dotenv import find_dotenv, load_dotenv

    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path, override=True)
    warnings.filterwarnings("ignore")

    raw_cap = os.getenv("SOURCE_MAX_TRAIN_ROWS", "").strip()
    cfg = SourceConfig(
        project_root=Path(os.getenv("AEROPULSE_PROJECT_ROOT", ".")).resolve(),
        pm25_data_root=Path(os.getenv("PM25_DATA_ROOT", "../pm25_estimator")).resolve(),
        train_fraction=float(os.getenv("SOURCE_TRAIN_FRACTION", "0.70")),
        validation_fraction=float(os.getenv("SOURCE_VALID_FRACTION", "0.15")),
        max_train_rows=int(raw_cap) if raw_cap else None,
        geographic_blocks=int(os.getenv("SOURCE_GEO_BLOCKS", "5")),
        gold_set_size=int(os.getenv("SOURCE_GOLD_SET_SIZE", "300")),
        enable_copollutants=os.getenv("SOURCE_ENABLE_COPOLLUTANTS", "0") == "1",
    )
    cfg.ensure_dirs()
    if verbose:
        print("env:", dotenv_path or "(none — using defaults)")
        print("project:", cfg.project_root)
        print("sources:", list(SOURCES))
        if cfg.max_train_rows:
            print("max_train_rows:", f"{cfg.max_train_rows:,}")
    return cfg


def git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5, check=False)
        return out.stdout.strip() or None
    except Exception:
        return None


def dataset_fingerprint(frame: pd.DataFrame) -> str:
    payload = {
        "rows": int(len(frame)),
        "cols": sorted(frame.columns.tolist()),
        "tmin": str(frame["timestamp_utc"].min()) if "timestamp_utc" in frame else None,
        "tmax": str(frame["timestamp_utc"].max()) if "timestamp_utc" in frame else None,
        "pm25_sum": round(float(pd.to_numeric(frame["pm25"], errors="coerce").sum()), 3)
        if "pm25" in frame else None,
    }
    return hashlib.sha256(json.dumps(payload, default=str).encode()).hexdigest()


def validate_contract(df: pd.DataFrame, schema: dict | None = None) -> dict:
    schema = schema or SCHEMA
    missing = [c for c in schema["required"] if c not in df.columns]
    absent_evidence = [c for c in schema["evidence"] if c not in df.columns]
    result = {
        "schema_version": schema["schema_version"],
        "label_schema_version": schema["label_schema_version"],
        "missing_required": missing,
        "absent_evidence": absent_evidence,
        "rows": int(len(df)),
        "columns": int(df.shape[1]),
        "status": "PASS" if not missing else "FAIL",
    }
    if missing:
        raise ValueError(f"Data contract violated. missing_required={missing}")
    if not isinstance(df["timestamp_utc"].dtype, pd.DatetimeTZDtype):
        raise ValueError("timestamp_utc must be timezone-aware (UTC).")
    return result


def quality_report(df: pd.DataFrame, schema: dict | None = None) -> tuple[dict, pd.DataFrame]:
    schema = schema or SCHEMA
    out_of_range = {}
    for column, (lo, hi) in schema["ranges"].items():
        if column in df.columns:
            values = pd.to_numeric(df[column], errors="coerce")
            bad = int(((values < lo) | (values > hi)).sum())
            if bad:
                out_of_range[column] = bad

    coverage = (
        df.groupby("location_id", observed=True)
        .agg(rows=("pm25", "size"),
             first=("timestamp_utc", "min"),
             last=("timestamp_utc", "max"))
        .reset_index()
    )
    evidence_missing = {
        column: round(float(df[column].isna().mean() * 100), 3)
        for column in schema["evidence"] if column in df.columns
    }
    report = {
        "generated_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "rows": int(len(df)),
        "stations": int(df["location_id"].nunique()),
        "window_start": str(df["timestamp_utc"].min()),
        "window_end": str(df["timestamp_utc"].max()),
        "duplicate_rows": int(df.duplicated(subset=["location_id", "timestamp_utc"]).sum()),
        "missing_pm25_pct": round(float(df["pm25"].isna().mean() * 100), 4),
        "out_of_range": out_of_range,
        "evidence_missing_pct": evidence_missing,
    }
    failures = []
    if report["duplicate_rows"]:
        failures.append("duplicate (location_id, timestamp_utc) rows")
    if report["missing_pm25_pct"] > 5:
        failures.append("pm25 missingness above 5%")
    if out_of_range:
        failures.append(f"values outside physical range: {sorted(out_of_range)}")
    report["failures"] = failures
    report["quality_status"] = "PASS" if not failures else "FAIL"
    return report, coverage


# ---------------------------------------------------------------------------
# Evidence features (S13-S20)
# ---------------------------------------------------------------------------


def add_pollutant_features(df: pd.DataFrame) -> pd.DataFrame:
    """Co-pollutant ratios, changes and rolling correlations (S13).

    All temporal terms are computed on past observations only, grouped by
    station and aligned on wall-clock time rather than row position.
    """
    pm = df["pm25"].clip(lower=1.0)
    for pollutant in ("no2", "co", "so2", "o3", "pm10"):
        column = f"cams_{pollutant}"
        if column in df.columns:
            df[f"{pollutant}_pm25_ratio"] = (df[column] / pm).astype("float32")

    df = df.sort_values(["location_id", "timestamp_utc"])
    grouped = df.groupby("location_id", observed=True)
    for column, short in (("cams_no2", "no2"), ("cams_co", "co"), ("pm25", "pm25")):
        if column not in df.columns:
            continue
        for lag in (1, 3):
            df[f"{short}_change_{lag}h"] = grouped[column].transform(
                lambda s, l=lag: s - s.shift(l)
            ).astype("float32")

    # Rolling correlation between NO2 and PM2.5 over the previous 24 h. A
    # traffic signature is the two rising together, which neither level nor
    # ratio captures on its own.
    if "cams_no2" in df.columns:
        def _rolling_corr(group: pd.DataFrame) -> pd.Series:
            return (
                group["cams_no2"].rolling(24, min_periods=6)
                .corr(group["pm25"]).shift(1)
            )

        df["rolling_corr_no2_pm25"] = (
            df.groupby("location_id", observed=True)[["cams_no2", "pm25"]]
            .apply(_rolling_corr).reset_index(level=0, drop=True)
            .replace([np.inf, -np.inf], np.nan).astype("float32")
        )
    if "cams_co" in df.columns:
        def _rolling_corr_co(group: pd.DataFrame) -> pd.Series:
            return (
                group["cams_co"].rolling(24, min_periods=6)
                .corr(group["pm25"]).shift(1)
            )

        df["rolling_corr_co_pm25"] = (
            df.groupby("location_id", observed=True)[["cams_co", "pm25"]]
            .apply(_rolling_corr_co).reset_index(level=0, drop=True)
            .replace([np.inf, -np.inf], np.nan).astype("float32")
        )
    return df


def add_transport_features(df: pd.DataFrame, window_hours: int = 6) -> pd.DataFrame:
    """Wind-direction persistence and transport consistency (S17, S18).

    A single wind observation is weak transport evidence. A direction that has
    held for six hours, with elevated PM2.5 upwind, is a much stronger claim.
    Consistency is the resultant length of the unit wind vectors over the
    window: 1.0 = perfectly steady, 0.0 = boxing the compass.
    """
    df = df.sort_values(["location_id", "timestamp_utc"])
    radians = np.deg2rad(df["wind_direction_10m"].astype("float32"))
    df["_wind_dir_sin"] = np.sin(radians)
    df["_wind_dir_cos"] = np.cos(radians)

    grouped = df.groupby("location_id", observed=True)
    sin_mean = grouped["_wind_dir_sin"].transform(
        lambda s: s.rolling(window_hours, min_periods=2).mean()
    )
    cos_mean = grouped["_wind_dir_cos"].transform(
        lambda s: s.rolling(window_hours, min_periods=2).mean()
    )
    df["transport_direction_consistency"] = np.sqrt(
        sin_mean**2 + cos_mean**2
    ).astype("float32")
    df["wind_direction_variability"] = (1.0 - df["transport_direction_consistency"]).astype("float32")
    df["transport_mean_direction_deg"] = (
        np.degrees(np.arctan2(sin_mean, cos_mean)) % 360.0
    ).astype("float32")

    df["wind_speed_mean_6h"] = grouped["wind_speed_10m"].transform(
        lambda s: s.rolling(window_hours, min_periods=1).mean()
    ).astype("float32")
    # km/h * hours = km. Open-Meteo returns km/h; treating it as m/s would
    # overstate the distance 3.6x, which is a mistake made elsewhere in this
    # repository and fixed there.
    df["transport_distance_6h"] = (df["wind_speed_mean_6h"] * window_hours).astype("float32")

    if "upwind_pm25_mean" in df.columns and "pm25" in df.columns:
        df["upwind_pm25_excess"] = (
            df["upwind_pm25_mean"] - df["pm25"]
        ).astype("float32")
    df = df.drop(columns=["_wind_dir_sin", "_wind_dir_cos"])
    return df


def add_station_context(df: pd.DataFrame, fit_end: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Derive a station-type proxy from behaviour, fitted on train only (S20).

    True station classifications (traffic / industrial / background) are not
    in this dataset. What is available is each station's own behavioural
    signature, which carries some of the same information:

    - a strong weekday-morning peak looks like a traffic-exposed site
    - a high night-to-day ratio looks like an industrial or stagnation site
    - a low ratio to its regional neighbours looks like a background site

    This is a *feature*, never a label, and it is fitted before the training
    cutoff so it cannot import test-period behaviour.
    """
    train = df[df["timestamp_utc"] < fit_end]
    if train.empty:
        raise ValueError("add_station_context: no rows before fit_end")

    hour = train["timestamp_utc"].dt.hour
    weekday = train["timestamp_utc"].dt.dayofweek < 5
    frame = pd.DataFrame({
        "location_id": train["location_id"].to_numpy(),
        "pm25": train["pm25"].to_numpy(),
        "hour": hour.to_numpy(),
        "weekday": weekday.to_numpy(),
    })

    overall = frame.groupby("location_id", observed=True)["pm25"].mean()
    morning = frame[frame["weekday"] & frame["hour"].between(6, 10)].groupby(
        "location_id", observed=True)["pm25"].mean()
    night = frame[frame["hour"].isin(list(range(22, 24)) + list(range(0, 5)))].groupby(
        "location_id", observed=True)["pm25"].mean()
    weekend = frame[~frame["weekday"]].groupby("location_id", observed=True)["pm25"].mean()

    context = pd.DataFrame({"station_mean_pm25": overall})
    context["station_morning_ratio"] = (morning / overall).reindex(context.index)
    context["station_night_ratio"] = (night / overall).reindex(context.index)
    context["station_weekend_ratio"] = (weekend / overall).reindex(context.index)
    context = context.fillna(1.0).reset_index()

    # Percentile ranks make the proxy comparable across the network rather
    # than across absolute concentration, which is dominated by geography.
    for column in ("station_morning_ratio", "station_night_ratio", "station_weekend_ratio"):
        context[f"{column}_rank"] = context[column].rank(pct=True).astype("float32")

    context["station_type_proxy"] = np.select(
        [
            context["station_morning_ratio_rank"] > 0.75,
            context["station_night_ratio_rank"] > 0.75,
            context["station_weekend_ratio_rank"] > 0.75,
        ],
        ["traffic_like", "industrial_like", "residential_like"],
        default="background_like",
    )
    # Ratio enrichment. A raw X/PM2.5 ratio is dominated by its denominator:
    # every ratio falls monotonically as PM2.5 rises, so "high NO2:PM2.5" is
    # largely a statement that PM2.5 is low. Dividing by the station's own
    # train-period median ratio asks the question that was actually intended
    # -- is this station unusually NO2-rich *for itself* right now.
    # Pollutant LEVEL anomalies, not ratios.
    #
    # Every X/PM2.5 ratio has PM2.5 in its denominator, so it falls
    # monotonically as PM2.5 rises -- "high NO2:PM2.5" mostly means "PM2.5 is
    # low". Dividing by the station's own median ratio removes the
    # between-station level difference but NOT that denominator effect: the
    # enrichment still decays across concentration bands. Measured, not
    # assumed; notebook 02 prints both tables.
    #
    # The quantity that actually answers "is this station unusually NO2-rich
    # right now" is the pollutant's own level against its own normal, with
    # PM2.5 nowhere in the expression.
    level_columns = [c for c in ("cams_no2", "cams_co", "cams_so2", "cams_o3", "cams_pm10")
                     if c in df.columns]
    if level_columns:
        medians = (
            train.groupby("location_id", observed=True)[level_columns]
            .median()
            .rename(columns={c: f"{c}_station_median" for c in level_columns})
            .reset_index()
        )
        context = context.merge(medians, on="location_id", how="left")

    merged = df.merge(context, on="location_id", how="left")
    for column in level_columns:
        fallback = float(train[column].median())
        reference = merged[f"{column}_station_median"].replace(0, np.nan).fillna(fallback)
        short = column.replace("cams_", "")
        merged[f"{short}_level_anomaly"] = (merged[column] / reference).astype("float32")

    # PM10:PM2.5 stays a ratio on purpose -- coarse-versus-fine *is* a ratio
    # question, and the coarse fraction is the physical quantity of interest.
    if "pm10_pm25_ratio" in merged.columns:
        pm10_reference = float(train["pm10_pm25_ratio"].median())
        merged["coarse_fraction_anomaly"] = (
            merged["pm10_pm25_ratio"] / pm10_reference
        ).astype("float32")
    for column in ("station_mean_pm25", "station_morning_ratio", "station_night_ratio",
                   "station_weekend_ratio"):
        merged[column] = merged[column].fillna(float(context[column].median()))
    merged["station_type_proxy"] = merged["station_type_proxy"].fillna("background_like")
    return merged, context


# ---------------------------------------------------------------------------
# Labeling functions (S5, S6)
# ---------------------------------------------------------------------------


@dataclass
class LabelingFunction:
    """One independent heuristic voting on one source.

    Returns +1 (supports), 0 (abstains) or -1 (contradicts) per row, together
    with a reliability weight. Abstention is first-class: a function with no
    opinion must say so rather than voting against, or absent evidence turns
    into negative evidence (plan section 45).
    """

    name: str
    source: str
    reliability: float
    requires: tuple[str, ...]
    description: str
    fn: Callable[[pd.DataFrame, dict], pd.Series]

    def __call__(self, df: pd.DataFrame, thresholds: dict) -> pd.Series:
        missing = [c for c in self.requires if c not in df.columns]
        if missing:
            return pd.Series(0, index=df.index, dtype="int8")
        votes = self.fn(df, thresholds).fillna(0).astype("int8")
        # Any row whose required evidence is null must abstain, not vote.
        available = df[list(self.requires)].notna().all(axis=1)
        return votes.where(available, 0).astype("int8")


def _q(frame: pd.DataFrame, thresholds: dict, key: str, default: float) -> float:
    value = thresholds.get(key, default)
    return default if value is None or (isinstance(value, float) and math.isnan(value)) else value


def fit_thresholds(train: pd.DataFrame) -> dict:
    """Quantile thresholds for the labeling functions, fitted on train only."""

    def _quantile(column: str, q: float, default: float) -> float:
        if column not in train.columns:
            return default
        values = pd.to_numeric(train[column], errors="coerce")
        if not values.notna().any():
            return default
        return float(values.quantile(q))

    return {
        "pm25_high": _quantile("pm25", 0.80, 60.0),
        "pm25_low": _quantile("pm25", 0.40, 20.0),
        "wind_high": _quantile("wind_speed_10m", 0.75, 12.0),
        "wind_low": _quantile("wind_speed_10m", 0.25, 5.0),
        "rh_low": _quantile("relative_humidity_2m", 0.25, 40.0),
        "no2_anomaly_high": _quantile("no2_level_anomaly", 0.80, 1.5),
        "no2_anomaly_low": _quantile("no2_level_anomaly", 0.20, 0.6),
        "so2_anomaly_high": _quantile("so2_level_anomaly", 0.85, 1.6),
        "co_anomaly_high": _quantile("co_level_anomaly", 0.80, 1.5),
        "coarse_high": _quantile("coarse_fraction_anomaly", 0.75, 1.4),
        "coarse_low": _quantile("coarse_fraction_anomaly", 0.25, 0.7),
        "dust_high": _quantile("cams_dust", 0.85, 100.0),
        "upwind_frp_high": _quantile("upwind_fire_frp_50km", 0.90, 10.0),
        "upwind_pm25_high": _quantile("upwind_pm25_mean", 0.75, 45.0),
        "consistency_high": _quantile("transport_direction_consistency", 0.60, 0.8),
        "corr_high": 0.4,
    }


def _lf_fire_upwind(df, t):
    high_pm = df["pm25"] >= _q(df, t, "pm25_high", 60.0)
    frp = df["upwind_fire_frp_50km"].fillna(0.0)
    supports = (frp >= _q(df, t, "upwind_frp_high", 10.0)) & high_pm
    contradicts = (frp <= 0) & high_pm
    return pd.Series(np.select([supports, contradicts], [1, -1], 0), index=df.index)


def _lf_fire_local(df, t):
    high_pm = df["pm25"] >= _q(df, t, "pm25_high", 60.0)
    count = df["fire_count_20km_24h"].fillna(0.0)
    return pd.Series(np.where((count > 0) & high_pm, 1, 0), index=df.index)


def _lf_crop_season(df, t):
    high_pm = df["pm25"] >= _q(df, t, "pm25_high", 60.0)
    window = df["crop_burning_window"].fillna(0).astype(bool)
    return pd.Series(np.where(window & high_pm, 1, 0), index=df.index)


def _lf_no2_ratio(df, t):
    """NO2 enrichment relative to this station's own normal, not the raw ratio."""
    ratio = df["no2_level_anomaly"]
    high = ratio >= _q(df, t, "no2_anomaly_high", 1.5)
    low = ratio <= _q(df, t, "no2_anomaly_low", 0.6)
    return pd.Series(np.select([high, low], [1, -1], 0), index=df.index)


def _lf_traffic_diurnal(df, t):
    hour = df["hour"]
    weekend = df["is_weekend"].fillna(0).astype(bool)
    rush = hour.isin([7, 8, 9, 18, 19, 20])
    high_pm = df["pm25"] >= _q(df, t, "pm25_high", 60.0)
    supports = rush & (~weekend) & high_pm
    # Same clock hour on a weekend is evidence *against* a traffic signature.
    contradicts = rush & weekend & high_pm
    return pd.Series(np.select([supports, contradicts], [1, -1], 0), index=df.index)


def _lf_no2_corr(df, t):
    corr = df["rolling_corr_no2_pm25"]
    return pd.Series(np.select([corr >= _q(df, t, "corr_high", 0.4), corr <= -0.2],
                               [1, -1], 0), index=df.index)


def _lf_dust_cams(df, t):
    return pd.Series(np.where(df["cams_dust"] >= _q(df, t, "dust_high", 100.0), 1, 0),
                     index=df.index)


def _lf_dust_meteorology(df, t):
    windy = df["wind_speed_10m"] >= _q(df, t, "wind_high", 12.0)
    dry = df["relative_humidity_2m"] <= _q(df, t, "rh_low", 40.0)
    high_pm = df["pm25"] >= _q(df, t, "pm25_high", 60.0)
    pre_monsoon = df["season"].astype(str) == "pre_monsoon"
    return pd.Series(np.where(windy & dry & high_pm & pre_monsoon, 1, 0), index=df.index)


def _lf_coarse_ratio(df, t):
    ratio = df["coarse_fraction_anomaly"]
    coarse = ratio >= _q(df, t, "coarse_high", 1.4)
    fine = ratio <= _q(df, t, "coarse_low", 0.7)
    return pd.Series(np.select([coarse, fine], [1, -1], 0), index=df.index)


def _lf_transport_upwind(df, t):
    upwind_high = df["upwind_pm25_mean"] >= _q(df, t, "upwind_pm25_high", 45.0)
    windy = df["wind_speed_10m"] >= _q(df, t, "wind_high", 12.0)
    high_pm = df["pm25"] >= _q(df, t, "pm25_high", 60.0)
    supports = upwind_high & windy & high_pm
    # Local air much dirtier than upwind means the source is here, not there.
    local_excess = df["pm25"] - df["upwind_pm25_mean"]
    contradicts = high_pm & (local_excess > df["pm25"] * 0.5)
    return pd.Series(np.select([supports, contradicts], [1, -1], 0), index=df.index)


def _lf_transport_consistency(df, t):
    consistent = df["transport_direction_consistency"] >= _q(df, t, "consistency_high", 0.8)
    upwind_high = df["upwind_pm25_mean"] >= _q(df, t, "upwind_pm25_high", 45.0)
    return pd.Series(np.where(consistent & upwind_high, 1, 0), index=df.index)


def _lf_stagnation_not_transport(df, t):
    stagnant = df["stagnation_flag"].fillna(0).astype(bool)
    high_pm = df["pm25"] >= _q(df, t, "pm25_high", 60.0)
    return pd.Series(np.where(stagnant & high_pm, -1, 0), index=df.index)


def _lf_so2_industrial(df, t):
    ratio = df["so2_level_anomaly"]
    return pd.Series(np.where(ratio >= _q(df, t, "so2_anomaly_high", 1.6), 1, 0), index=df.index)


def _lf_industrial_nocturnal(df, t):
    hour = df["hour"]
    night = hour.isin(list(range(22, 24)) + list(range(0, 5)))
    stagnant = df["stagnation_flag"].fillna(0).astype(bool)
    high_pm = df["pm25"] >= _q(df, t, "pm25_high", 60.0)
    fire = df["fire_active_flag"].fillna(0).astype(bool)
    return pd.Series(np.where(night & stagnant & high_pm & (~fire), 1, 0), index=df.index)


def _lf_industrial_weekend_persistence(df, t):
    """Industry runs through the weekend; traffic does not.

    A station whose weekend PM2.5 holds up relative to its own weekday level
    is behaving more like an industrial neighbourhood than a commuter one.
    """
    weekend = df["is_weekend"].fillna(0).astype(bool)
    high_pm = df["pm25"] >= _q(df, t, "pm25_high", 60.0)
    persistent = df["station_weekend_ratio"] >= 1.0
    return pd.Series(np.where(weekend & high_pm & persistent, 1, 0), index=df.index)


LABELING_FUNCTIONS: tuple[LabelingFunction, ...] = (
    LabelingFunction("LF_FIRE_UPWIND", "biomass_burning", 0.90,
                     ("pm25", "upwind_fire_frp_50km"),
                     "Upwind fire radiative power high with elevated PM2.5; contradicts when no upwind fire at all",
                     _lf_fire_upwind),
    LabelingFunction("LF_FIRE_LOCAL", "biomass_burning", 0.75,
                     ("pm25", "fire_count_20km_24h"),
                     "Any fire detection within 20 km in the last 24 h with elevated PM2.5",
                     _lf_fire_local),
    LabelingFunction("LF_CROP_SEASON", "biomass_burning", 0.50,
                     ("pm25", "crop_burning_window"),
                     "Inside the kharif/rabi stubble-burning calendar window with elevated PM2.5",
                     _lf_crop_season),
    LabelingFunction("LF_NO2_RATIO", "traffic", 0.65,
                     ("no2_level_anomaly",),
                     "NO2 level above this station's own normal; contradicts when below",
                     _lf_no2_ratio),
    LabelingFunction("LF_TRAFFIC_DIURNAL", "traffic", 0.60,
                     ("pm25", "hour", "is_weekend"),
                     "Weekday rush hour with elevated PM2.5; contradicts on weekends at the same hour",
                     _lf_traffic_diurnal),
    LabelingFunction("LF_NO2_PM25_CORR", "traffic", 0.55,
                     ("rolling_corr_no2_pm25",),
                     "NO2 and PM2.5 rising together over the previous 24 h",
                     _lf_no2_corr),
    LabelingFunction("LF_DUST_CAMS", "dust", 0.80,
                     ("cams_dust",),
                     "CAMS dust mixing ratio in the top 15%",
                     _lf_dust_cams),
    LabelingFunction("LF_DUST_METEOROLOGY", "dust", 0.60,
                     ("pm25", "wind_speed_10m", "relative_humidity_2m", "season"),
                     "Pre-monsoon, windy, dry and dirty",
                     _lf_dust_meteorology),
    LabelingFunction("LF_COARSE_RATIO", "dust", 0.70,
                     ("coarse_fraction_anomaly",),
                     "Coarse fraction above normal implies dust; below normal contradicts it",
                     _lf_coarse_ratio),
    LabelingFunction("LF_TRANSPORT_UPWIND", "regional_transport", 0.80,
                     ("pm25", "upwind_pm25_mean", "wind_speed_10m"),
                     "Upwind PM2.5 elevated with sustained wind; contradicts on large local excess",
                     _lf_transport_upwind),
    LabelingFunction("LF_TRANSPORT_CONSISTENCY", "regional_transport", 0.60,
                     ("transport_direction_consistency", "upwind_pm25_mean"),
                     "Wind direction steady over 6 h while upwind PM2.5 is elevated",
                     _lf_transport_consistency),
    LabelingFunction("LF_STAGNATION_NOT_TRANSPORT", "regional_transport", 0.55,
                     ("pm25", "stagnation_flag"),
                     "Stagnant air with high PM2.5 argues against long-range transport",
                     _lf_stagnation_not_transport),
    LabelingFunction("LF_SO2_INDUSTRIAL", "industrial", 0.70,
                     ("so2_level_anomaly",),
                     "SO2 level above this station's own normal, a combustion marker",
                     _lf_so2_industrial),
    LabelingFunction("LF_INDUSTRIAL_NOCTURNAL", "industrial", 0.45,
                     ("pm25", "hour", "stagnation_flag", "fire_active_flag"),
                     "Night-time stagnant high PM2.5 with no fire",
                     _lf_industrial_nocturnal),
    LabelingFunction("LF_INDUSTRIAL_WEEKEND", "industrial", 0.45,
                     ("pm25", "is_weekend", "station_weekend_ratio"),
                     "Weekend PM2.5 holds up at a station whose weekend level does not drop",
                     _lf_industrial_weekend_persistence),
)


def labeling_function_table() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "name": lf.name,
            "source": lf.source,
            "reliability": lf.reliability,
            "requires": ", ".join(lf.requires),
            "description": lf.description,
        }
        for lf in LABELING_FUNCTIONS
    ])


# ---------------------------------------------------------------------------
# Weak-label aggregation (S23, S7, S8, S33)
# ---------------------------------------------------------------------------

LF_EVIDENCE_FAMILIES: dict[str, tuple[str, ...]] = {
    # An LF input drags its whole evidence family with it. Excluding only the
    # exact column is not enough: `upwind_fire_count_50km` is a near-duplicate
    # of `upwind_fire_frp_50km`, and `pm25_lag_1h` is a near-duplicate of
    # `pm25`. Leaving those available let the classifier reach PR-AUC 0.9999
    # on biomass -- a number that says the leakage guard was too narrow, not
    # that the model was good.
    "pm25": ("pm25", "national_pm25", "regional_pm25", "neighbour_pm25",
             "low_pbl_x_high_pm25", "low_wind_x_high_pm25", "humidity_x_pm25",
             "stagnation_x_upwind_pm25", "station_mean_pm25"),
    "upwind_fire_frp_50km": ("fire_", "upwind_fire", "crosswind_fire", "downwind_fire",
                             "rain_x_fire", "low_pbl_x_fire"),
    "fire_count_20km_24h": ("fire_", "upwind_fire", "crosswind_fire", "downwind_fire",
                            "rain_x_fire", "low_pbl_x_fire"),
    "upwind_pm25_mean": ("upwind_pm25", "upwind_"),
    "no2_level_anomaly": ("cams_no2", "no2_"),
    "so2_level_anomaly": ("cams_so2", "so2_"),
    "coarse_fraction_anomaly": ("cams_pm10", "pm10_", "coarse_"),
    "cams_dust": ("cams_dust",),
    # wind_u / wind_v are the same vector the LFs read, decomposed.
    "wind_speed_10m": ("wind_speed", "wind_u", "wind_v", "delta_wind"),
    "relative_humidity_2m": ("relative_humidity", "humidity_x"),
    "hour": ("hour", "sin_hour", "cos_hour"),
    "is_weekend": ("is_weekend", "dow", "sin_dow", "cos_dow"),
    "stagnation_flag": ("stagnation", "low_wind_flag", "low_pbl_flag"),
    "transport_direction_consistency": ("transport_", "wind_direction"),
    "crop_burning_window": ("crop_burning",),
    "rolling_corr_no2_pm25": ("rolling_corr",),
    "station_weekend_ratio": ("station_weekend",),
    "season": ("season",),
}


def _lf_family_prefixes(inputs: Iterable[str]) -> tuple[str, ...]:
    """Prefixes covering every evidence family a labeling function reads."""
    prefixes: set[str] = set()
    for column in inputs:
        prefixes.update(LF_EVIDENCE_FAMILIES.get(column, (column,)))
    return tuple(sorted(prefixes))


def _lf_parent_columns(inputs: Iterable[str]) -> set[str]:
    """Columns an LF input is deterministically derived from.

    ``no2_pm25_ratio_enrichment`` is ``no2_pm25_ratio`` divided by a
    per-station constant, so leaving the raw ratio in the feature set would
    hand the classifier the same information under a different name. Same for
    the station median it was divided by.
    """
    parents: set[str] = set()
    for column in inputs:
        if column.endswith("_level_anomaly"):
            short = column[: -len("_level_anomaly")]
            parents |= {f"cams_{short}", f"cams_{short}_station_median",
                        f"{short}_pm25_ratio"}
        if column == "coarse_fraction_anomaly":
            parents |= {"pm10_pm25_ratio", "cams_pm10", "cams_pm10_station_median"}
    return parents


_RAW_LF_INPUTS = {column for lf in LABELING_FUNCTIONS for column in lf.requires}
LF_INPUT_COLUMNS: tuple[str, ...] = tuple(sorted(
    _RAW_LF_INPUTS | _lf_parent_columns(_RAW_LF_INPUTS)
))
LF_EXCLUDED_PREFIXES: tuple[str, ...] = _lf_family_prefixes(_RAW_LF_INPUTS)
"""Every column any labeling function reads.

These are forbidden as classifier features. If the classifier can see them it
does not learn source signals — it re-derives the heuristic, and the
evaluation then measures nothing but that re-derivation (plan section 27).
"""


def apply_labeling_functions(
    df: pd.DataFrame, thresholds: dict, functions: Sequence[LabelingFunction] | None = None
) -> pd.DataFrame:
    """Run every LF and return one int8 column per function."""
    functions = functions or LABELING_FUNCTIONS
    votes = {lf.name: lf(df, thresholds) for lf in functions}
    return pd.DataFrame(votes, index=df.index)


def aggregate_weak_labels(
    votes: pd.DataFrame,
    functions: Sequence[LabelingFunction] | None = None,
    sources: Sequence[str] = SOURCES,
    positive_threshold: float = 0.5,
) -> pd.DataFrame:
    """Reliability-weighted aggregation into per-source probabilistic labels.

    For each source, ``score = sum(reliability * vote) / sum(reliability of
    functions that did not abstain)``, which lands in [-1, 1]. Dividing by
    the *participating* weight rather than the total is what keeps abstention
    neutral: a source judged by one confident function is not penalised for
    the silence of the others.

    The score is squashed to a probability, and three extra quantities come
    out of the same pass:

    ``*_coverage``  how much of the available reliability weight voted at all
    ``*_conflict``  disagreement among the functions for that one source
    ``conflict_score`` cross-source competition (plan section 7)
    """
    functions = functions or LABELING_FUNCTIONS
    by_source: dict[str, list[LabelingFunction]] = {s: [] for s in sources}
    for lf in functions:
        if lf.source in by_source:
            by_source[lf.source].append(lf)

    out = pd.DataFrame(index=votes.index)
    for source, lfs in by_source.items():
        if not lfs:
            continue
        weights = np.array([lf.reliability for lf in lfs], dtype="float32")
        block = votes[[lf.name for lf in lfs]].to_numpy(dtype="float32")
        participating = (block != 0).astype("float32") @ weights
        weighted = block @ weights
        total_weight = float(weights.sum())

        voted = participating > 0
        score = np.divide(weighted, participating,
                          out=np.zeros_like(weighted), where=voted)
        # Logistic squash. The gain of 2.5 maps a unanimous +1 to ~0.92 rather
        # than 1.0 -- a heuristic consensus is strong evidence, not certainty.
        probability = 1.0 / (1.0 + np.exp(-2.5 * score))
        # A source on which every function abstained has NO opinion. Leaving
        # it at score 0 -> probability 0.5 would make silence read as
        # half-support, which then clears a 0.5 positive threshold and makes
        # abstention indistinguishable from evidence. It is NaN instead, and
        # every downstream statistic is NaN-aware.
        probability = np.where(voted, probability, np.nan)

        out[f"{source}_score"] = np.where(voted, score, np.nan).astype("float32")
        out[f"{source}_weak_prob"] = probability.astype("float32")
        out[f"{source}_coverage"] = (participating / total_weight).astype("float32")

        positives = ((block > 0).astype("float32") @ weights)
        negatives = ((block < 0).astype("float32") @ weights)
        denominator = np.maximum(positives + negatives, 1e-6)
        out[f"{source}_conflict"] = np.where(
            voted, 2.0 * np.minimum(positives, negatives) / denominator, np.nan
        ).astype("float32")
        out[f"y_{source}"] = (
            (probability >= positive_threshold) & voted
        ).astype("int8")

    prob_cols = [f"{s}_weak_prob" for s in sources if f"{s}_weak_prob" in out.columns]
    probs = out[prob_cols].to_numpy(dtype="float32")
    any_opinion = np.isfinite(probs).any(axis=1)

    ordered = np.sort(np.where(np.isfinite(probs), probs, -np.inf), axis=1)[:, ::-1]
    top = np.where(any_opinion, ordered[:, 0], 0.0)
    second = ordered[:, 1] if ordered.shape[1] > 1 else np.full_like(top, -np.inf)
    second = np.where(np.isfinite(second), second, 0.0)

    primary_index = np.nanargmax(np.where(np.isfinite(probs), probs, -np.inf), axis=1)
    out["primary_source"] = np.where(
        any_opinion,
        np.array([c.replace("_weak_prob", "") for c in prob_cols])[primary_index],
        None,
    )
    out["primary_prob"] = top.astype("float32")
    # Two sources both looking likely is the conflict the plan asks us to
    # surface rather than resolve by priority order.
    out["conflict_score"] = np.where(top > 0, second / np.maximum(top, 1e-6), 0.0).astype("float32")
    out["n_sources_supported"] = (
        np.nan_to_num(probs, nan=0.0) >= positive_threshold
    ).sum(axis=1).astype("int8")
    out["n_sources_evaluated"] = np.isfinite(probs).sum(axis=1).astype("int8")
    out["max_coverage"] = out[[f"{s}_coverage" for s in sources
                               if f"{s}_coverage" in out.columns]].max(axis=1).astype("float32")

    # Unknown is derived, never a competing class (plan section 8).
    out["unknown_probability"] = (
        (1.0 - top) * (1.0 - 0.5 * out["max_coverage"])
    ).clip(0.0, 1.0).astype("float32")
    out["attribution_confidence"] = (
        top * (1.0 - out["conflict_score"]) * out["max_coverage"]
    ).clip(0.0, 1.0).astype("float32")
    out["is_unknown"] = (out["n_sources_supported"] == 0).astype("int8")
    return out


def conflict_report(labels: pd.DataFrame, sources: Sequence[str] = SOURCES) -> pd.DataFrame:
    """How often each pair of sources is simultaneously supported (S7)."""
    rows = []
    for i, a in enumerate(sources):
        for b in sources[i + 1:]:
            ya, yb = f"y_{a}", f"y_{b}"
            if ya not in labels.columns or yb not in labels.columns:
                continue
            both = int(((labels[ya] == 1) & (labels[yb] == 1)).sum())
            either = int(((labels[ya] == 1) | (labels[yb] == 1)).sum())
            rows.append({
                "source_a": a,
                "source_b": b,
                "co_occurrence": both,
                "jaccard": round(both / either, 4) if either else 0.0,
            })
    return pd.DataFrame(rows).sort_values("co_occurrence", ascending=False)


# ---------------------------------------------------------------------------
# Leakage control
# ---------------------------------------------------------------------------

IDENTIFIER_COLUMNS = {
    "timestamp_utc", "timestamp_local", "location_id", "sensor_id", "station_name",
    "source", "source_quality", "pm25_unit", "country", "state", "city", "grid_id",
    "weather_source", "fire_source", "schema_version", "season", "pollution_regime",
    "event_id", "event_start", "event_end", "station_type_proxy",
    "source_label", "source_label_global", "primary_source",
}
LABEL_OUTPUT_PREFIXES = ("y_", "target_", "event_")
LABEL_OUTPUT_SUFFIXES = ("_score", "_weak_prob", "_coverage", "_conflict")
LABEL_DERIVED_COLUMNS = {
    "unknown_probability", "attribution_confidence", "conflict_score",
    "is_unknown", "n_sources_supported", "n_sources_evaluated",
    "primary_prob", "max_coverage",
}


def select_features(
    df: pd.DataFrame,
    extra_exclude: Iterable[str] = (),
    drop_degenerate: bool = True,
    sample: int = 50_000,
) -> list[str]:
    """Numeric columns a source classifier is allowed to see.

    Excludes identifiers, every labeling-function input, every aggregation
    output, and the upstream event columns. What remains is weather,
    cyclical time, geography, PM2.5 dynamics not read by any LF, and the
    station-context proxies.
    """
    exclude = set(IDENTIFIER_COLUMNS) | set(LF_INPUT_COLUMNS) | set(extra_exclude)
    exclude |= LABEL_DERIVED_COLUMNS
    feats: list[str] = []
    for column in df.columns:
        if column in exclude:
            continue
        if column.startswith(LABEL_OUTPUT_PREFIXES):
            continue
        if column.endswith(LABEL_OUTPUT_SUFFIXES):
            continue
        # Whole-family exclusion, not just the exact LF input column.
        if column.startswith(LF_EXCLUDED_PREFIXES):
            continue
        # Any X/PM2.5 ratio carries PM2.5, which is an LF input.
        if column.endswith("_pm25_ratio") or column.endswith("_pm25_ratio_station_median"):
            continue
        # The availability flags decide whether an LF abstains, so they
        # predict the label through the labeling mechanism itself. The
        # predictor uses them for routing; the classifier may not.
        if column.startswith("evidence_"):
            continue
        if not pd.api.types.is_numeric_dtype(df[column]):
            continue
        feats.append(column)

    if drop_degenerate and feats:
        probe = df[feats].iloc[:: max(1, len(df) // sample)] if len(df) > sample else df[feats]
        feats = [c for c in feats
                 if probe[c].notna().sum() > 0 and probe[c].nunique(dropna=True) > 1]
    return feats


def assert_no_label_leakage(features: Sequence[str]) -> dict:
    """Fail loudly if any labeling-function evidence reached the feature set."""
    leaked = sorted(set(features) & set(LF_INPUT_COLUMNS))
    derived = sorted(f for f in features
                     if f.startswith(LABEL_OUTPUT_PREFIXES)
                     or f.endswith(LABEL_OUTPUT_SUFFIXES)
                     or f in LABEL_DERIVED_COLUMNS)
    family = sorted(
        f for f in features
        if f.startswith(LF_EXCLUDED_PREFIXES)
        or f.endswith("_pm25_ratio")
        or f.startswith("evidence_")
    )
    if leaked or derived or family:
        raise AssertionError(
            f"label inputs leaked: {leaked}; label outputs leaked: {derived}; "
            f"same-family evidence leaked: {family}"
        )
    return {
        "n_features": len(features),
        "lf_inputs_excluded": len(LF_INPUT_COLUMNS),
        "excluded_families": len(LF_EXCLUDED_PREFIXES),
    }


# ---------------------------------------------------------------------------
# Splits and events (S29-S31)
# ---------------------------------------------------------------------------


def chrono_split(frame, train_frac=0.70, valid_frac=0.15):
    t1 = frame["timestamp_utc"].quantile(train_frac)
    t2 = frame["timestamp_utc"].quantile(train_frac + valid_frac)
    return (frame[frame["timestamp_utc"] < t1],
            frame[(frame["timestamp_utc"] >= t1) & (frame["timestamp_utc"] < t2)],
            frame[frame["timestamp_utc"] >= t2])


def build_events(df: pd.DataFrame, labels: pd.DataFrame | None = None) -> pd.DataFrame:
    """Collapse hourly rows into pollution episodes (S29).

    Uses the upstream ``event_id`` where present. An event is the unit
    AeroPulse actually reports on, and it is also the unit that must not be
    split across train and test — hours within one episode are so correlated
    that a random row split leaks the answer.
    """
    if "event_id" not in df.columns:
        raise ValueError("build_events needs the upstream event_id column")
    work = df[df["event_id"].notna()].copy()
    if labels is not None:
        work = work.join(labels, how="left", rsuffix="_lbl")

    aggregations = {
        "location_id": ("location_id", "first"),
        "event_start": ("timestamp_utc", "min"),
        "event_end": ("timestamp_utc", "max"),
        "n_hours": ("pm25", "size"),
        "peak_pm25": ("pm25", "max"),
        "mean_pm25": ("pm25", "mean"),
        "lat": ("lat", "first"),
        "lon": ("lon", "first"),
    }
    for source in SOURCES:
        column = f"{source}_weak_prob"
        if column in work.columns:
            aggregations[f"{source}_mean_prob"] = (column, "mean")
            aggregations[f"{source}_max_prob"] = (column, "max")
    if "attribution_confidence" in work.columns:
        aggregations["mean_confidence"] = ("attribution_confidence", "mean")

    # Group by (location_id, event_id). The upstream event_id is not unique
    # across stations -- grouping on it alone merges every station's episode
    # into one row and produces "events" lasting months.
    aggregations.pop("location_id", None)
    events = (
        work.groupby(["location_id", "event_id"], observed=True)
        .agg(**aggregations)
        .reset_index()
    )
    events["event_key"] = (
        events["location_id"].astype(str) + "::" + events["event_id"].astype(str)
    )
    prob_cols = [f"{s}_mean_prob" for s in SOURCES if f"{s}_mean_prob" in events.columns]
    if prob_cols:
        events["dominant_source"] = [
            prob_cols[i].replace("_mean_prob", "")
            for i in events[prob_cols].to_numpy().argmax(axis=1)
        ]
        events["dominant_prob"] = events[prob_cols].max(axis=1)
    events["duration_hours"] = (
        (events["event_end"] - events["event_start"]).dt.total_seconds() / 3600.0
    )
    return events


def event_split(df: pd.DataFrame, events: pd.DataFrame,
                train_frac: float = 0.70, valid_frac: float = 0.15):
    """Split by event start time so no episode straddles a boundary (S30)."""
    ordered = events.sort_values("event_start")
    n = len(ordered)
    key = "event_key" if "event_key" in ordered.columns else "event_id"
    train_ids = set(ordered.iloc[: int(n * train_frac)][key])
    valid_ids = set(ordered.iloc[int(n * train_frac): int(n * (train_frac + valid_frac))][key])
    test_ids = set(ordered.iloc[int(n * (train_frac + valid_frac)):][key])

    work = df[df["event_id"].notna()].copy()
    work["_key"] = (work["location_id"].astype(str) + "::" + work["event_id"].astype(str)
                    if key == "event_key" else work["event_id"])
    return (work[work["_key"].isin(train_ids)].drop(columns=["_key"]),
            work[work["_key"].isin(valid_ids)].drop(columns=["_key"]),
            work[work["_key"].isin(test_ids)].drop(columns=["_key"]))


def geographic_blocks(df: pd.DataFrame, n_blocks: int = 5, random_state: int = 42) -> pd.DataFrame:
    """k-means blocks over station coordinates (S31)."""
    from sklearn.cluster import KMeans

    stations = df.groupby("location_id", observed=True)[["lat", "lon"]].mean().reset_index()
    km = KMeans(n_clusters=n_blocks, n_init=10, random_state=random_state).fit(
        stations[["lat", "lon"]].to_numpy()
    )
    stations["geo_block"] = km.labels_
    centres = pd.DataFrame(km.cluster_centers_, columns=["block_lat", "block_lon"])
    centres["geo_block"] = centres.index
    return stations.merge(centres, on="geo_block", how="left")


def gold_set_sample(events: pd.DataFrame, size: int = 300, random_state: int = 42) -> pd.DataFrame:
    """Stratified event sample for human review (S28).

    Returns an annotation sheet, not labels. Sampling is stratified over the
    weak-label dominant source and confidence tercile so a reviewer sees the
    cases the system is unsure about, not just the easy ones. **This produces
    an empty label column on purpose** — filling it from the heuristics would
    make the gold set a copy of the thing it is supposed to audit.
    """
    work = events.copy()
    if "dominant_source" not in work.columns:
        raise ValueError("gold_set_sample needs events built with weak-label probabilities")
    work["confidence_tercile"] = pd.qcut(
        work.get("mean_confidence", work["dominant_prob"]).rank(method="first"),
        3, labels=["low", "medium", "high"]
    )
    strata = work.groupby(["dominant_source", "confidence_tercile"], observed=True)
    per_stratum = max(1, size // max(len(strata), 1))
    sampled = strata.apply(
        lambda g: g.sample(min(len(g), per_stratum), random_state=random_state),
        include_groups=False,
    ).reset_index()

    sheet = sampled.rename(columns={"level_2": "_row"})
    keep = [c for c in ["event_id", "location_id", "event_start", "event_end", "n_hours",
                        "peak_pm25", "mean_pm25", "dominant_source", "dominant_prob",
                        "confidence_tercile"] if c in sheet.columns]
    sheet = sheet[keep].copy()
    sheet["expert_primary_source"] = ""
    sheet["expert_secondary_sources"] = ""
    sheet["expert_confidence"] = ""
    sheet["reviewer"] = ""
    sheet["review_notes"] = ""
    return sheet.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Classifiers and calibration (S21, S25, S26)
# ---------------------------------------------------------------------------


def make_classifier(kind: str = "logistic", params: dict | None = None, random_state: int = 42):
    """One binary classifier per source, comparable across families (S21)."""
    params = dict(params or {})
    if kind == "logistic":
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        return Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=1000, class_weight="balanced",
                                       random_state=random_state, **params)),
        ])
    if kind == "lightgbm":
        import lightgbm as lgb

        defaults = {"n_estimators": 300, "learning_rate": 0.05, "num_leaves": 63,
                    "min_child_samples": 50, "subsample": 0.8, "subsample_freq": 1,
                    "colsample_bytree": 0.8, "class_weight": "balanced"}
        return lgb.LGBMClassifier(random_state=random_state, n_jobs=-1, verbose=-1,
                                  **{**defaults, **params})
    if kind == "xgboost":
        import xgboost as xgb

        defaults = {"n_estimators": 300, "learning_rate": 0.05, "max_depth": 7,
                    "subsample": 0.8, "colsample_bytree": 0.8}
        return xgb.XGBClassifier(random_state=random_state, n_jobs=-1,
                                 tree_method="hist", eval_metric="logloss",
                                 **{**defaults, **params})
    if kind == "catboost":
        from catboost import CatBoostClassifier

        defaults = {"iterations": 300, "learning_rate": 0.05, "depth": 7}
        return CatBoostClassifier(random_seed=random_state, verbose=0,
                                  allow_writing_files=False, **{**defaults, **params})
    raise ValueError(f"unknown classifier kind: {kind}")


@dataclass
class SourceClassifier:
    """A calibrated binary classifier for one source."""

    source: str
    model: Any
    features: list[str]
    kind: str
    medians: pd.Series | None = None
    calibrator: Any = None
    calibration_method: str = "none"
    threshold: float = 0.5

    def _prepare(self, df: pd.DataFrame) -> np.ndarray:
        block = df[self.features]
        if self.medians is not None:
            block = block.fillna(self.medians)
        return block.to_numpy(dtype="float32")

    @classmethod
    def fit(cls, train: pd.DataFrame, features: Sequence[str], source: str,
            kind: str = "logistic", params: dict | None = None,
            random_state: int = 42) -> "SourceClassifier":
        features = list(features)
        medians = train[features].median(numeric_only=True)
        X = train[features].fillna(medians).to_numpy(dtype="float32")
        y = train[f"y_{source}"].to_numpy(dtype="int8")
        positives = int(y.sum())
        if positives == 0 or positives == len(y):
            raise ValueError(
                f"y_{source} is single-class in this split "
                f"({positives}/{len(y)} positive) — a classifier cannot be fitted. "
                "Either the labeling functions never fire for this source, or "
                "they always do; both are label-design problems, not model ones."
            )
        model = make_classifier(kind, params, random_state)
        model.fit(X, y)
        return cls(source=source, model=model, features=features, kind=kind, medians=medians)

    def raw_proba(self, df: pd.DataFrame) -> np.ndarray:
        proba = self.model.predict_proba(self._prepare(df))
        return np.asarray(proba)[:, 1]

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        """Calibrated P(source | evidence). Every calibrator takes 1-D input."""
        raw = self.raw_proba(df)
        if self.calibrator is None:
            return raw
        return np.clip(np.asarray(self.calibrator.predict(raw), dtype=float), 0.0, 1.0)

    def calibrate(self, valid: pd.DataFrame, method: str = "isotonic") -> "SourceClassifier":
        """Fit a calibrator on validation only (plan section 25)."""
        raw = self.raw_proba(valid)
        y = valid[f"y_{self.source}"].to_numpy(dtype="int8")
        if len(np.unique(y)) < 2:
            self.calibrator, self.calibration_method = None, "skipped_single_class"
            return self
        if method == "isotonic":
            from sklearn.isotonic import IsotonicRegression

            calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            calibrator.fit(raw, y)
        elif method == "sigmoid":
            from sklearn.linear_model import LogisticRegression

            calibrator = LogisticRegression(max_iter=1000)
            calibrator.fit(raw.reshape(-1, 1), y)
            calibrator = _SigmoidWrapper(calibrator)
        elif method == "beta":
            calibrator = _BetaCalibrator().fit(raw, y)
        elif method == "none":
            calibrator = None
        else:
            raise ValueError(f"unknown calibration method: {method}")
        self.calibrator, self.calibration_method = calibrator, method
        return self


class _SigmoidWrapper:
    """Platt scaling with a 1-D ``predict`` interface."""

    def __init__(self, model):
        self.model = model

    def predict(self, x):
        x = np.asarray(x).reshape(-1, 1)
        return self.model.predict_proba(x)[:, 1]


class _BetaCalibrator:
    """Beta calibration (Kull et al.).

    More flexible than Platt and less prone to isotonic's step artifacts on
    small validation sets, which matters here because the rare sources have
    few positives.
    """

    def __init__(self):
        self.model = None

    def fit(self, raw, y):
        from sklearn.linear_model import LogisticRegression

        eps = 1e-6
        p = np.clip(np.asarray(raw, dtype=float), eps, 1 - eps)
        design = np.column_stack([np.log(p), -np.log(1 - p)])
        self.model = LogisticRegression(max_iter=1000).fit(design, y)
        return self

    def predict(self, raw):
        eps = 1e-6
        p = np.clip(np.asarray(raw, dtype=float).ravel(), eps, 1 - eps)
        design = np.column_stack([np.log(p), -np.log(1 - p)])
        return self.model.predict_proba(design)[:, 1]


def calibration_metrics(y_true: np.ndarray, proba: np.ndarray, n_bins: int = 15) -> dict:
    """PR-AUC, ROC-AUC, Brier, log loss, ECE and MCE (S26)."""
    from sklearn.metrics import (average_precision_score, brier_score_loss,
                                 log_loss, roc_auc_score)

    y_true = np.asarray(y_true, dtype=int)
    proba = np.clip(np.asarray(proba, dtype=float), 1e-7, 1 - 1e-7)
    mask = np.isfinite(proba)
    y_true, proba = y_true[mask], proba[mask]
    prevalence = float(y_true.mean()) if len(y_true) else float("nan")

    out = {"n": int(len(y_true)), "prevalence": prevalence}
    if len(np.unique(y_true)) < 2:
        out.update({"pr_auc": float("nan"), "roc_auc": float("nan"),
                    "brier": float("nan"), "log_loss": float("nan"),
                    "ece": float("nan"), "mce": float("nan"),
                    "pr_auc_lift": float("nan")})
        return out

    out["pr_auc"] = float(average_precision_score(y_true, proba))
    out["roc_auc"] = float(roc_auc_score(y_true, proba))
    out["brier"] = float(brier_score_loss(y_true, proba))
    out["log_loss"] = float(log_loss(y_true, proba, labels=[0, 1]))
    # PR-AUC on its own is unreadable without the prevalence it must beat.
    out["pr_auc_lift"] = float(out["pr_auc"] / prevalence) if prevalence > 0 else float("nan")

    bins = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.digitize(proba, bins) - 1
    ece, mce = 0.0, 0.0
    for b in range(n_bins):
        in_bin = idx == b
        if not in_bin.any():
            continue
        gap = abs(proba[in_bin].mean() - y_true[in_bin].mean())
        ece += in_bin.mean() * gap
        mce = max(mce, gap)
    out["ece"] = float(ece)
    out["mce"] = float(mce)
    return out


def reliability_curve(y_true: np.ndarray, proba: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    y_true = np.asarray(y_true, dtype=int)
    proba = np.asarray(proba, dtype=float)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.digitize(proba, bins) - 1
    rows = []
    for b in range(n_bins):
        in_bin = idx == b
        if not in_bin.any():
            continue
        rows.append({
            "bin_lower": round(float(bins[b]), 3),
            "bin_upper": round(float(bins[b + 1]), 3),
            "n": int(in_bin.sum()),
            "mean_predicted": round(float(proba[in_bin].mean()), 4),
            "observed_rate": round(float(y_true[in_bin].mean()), 4),
        })
    return pd.DataFrame(rows)


def tune_thresholds(y_true: np.ndarray, proba: np.ndarray,
                    grid: np.ndarray | None = None, objective: str = "f1") -> dict:
    """Per-source operating point chosen on validation (S32).

    A single P > 0.5 across sources is wrong when prevalence differs by an
    order of magnitude between them.
    """
    from sklearn.metrics import f1_score, precision_score, recall_score

    grid = grid if grid is not None else np.arange(0.05, 0.96, 0.01)
    y_true = np.asarray(y_true, dtype=int)
    proba = np.asarray(proba, dtype=float)
    if len(np.unique(y_true)) < 2:
        return {"threshold": 0.5, "f1": float("nan"), "precision": float("nan"),
                "recall": float("nan"), "note": "single-class validation slice"}
    best = {"threshold": 0.5, "f1": -1.0}
    for threshold in grid:
        pred = (proba >= threshold).astype(int)
        score = f1_score(y_true, pred, zero_division=0)
        if score > best["f1"]:
            best = {
                "threshold": round(float(threshold), 3),
                "f1": round(float(score), 4),
                "precision": round(float(precision_score(y_true, pred, zero_division=0)), 4),
                "recall": round(float(recall_score(y_true, pred, zero_division=0)), 4),
            }
    return best


# ---------------------------------------------------------------------------
# Promotion gates (S48)
# ---------------------------------------------------------------------------

PROMOTION_GATES = {
    "min_pr_auc_lift": 2.0,
    "min_sources_meeting_lift": 4,
    "max_ece": 0.10,
    "min_spatial_pr_auc_lift": 1.5,
    "min_event_agreement": 0.50,
    "max_unknown_rate": 0.90,
    "min_unknown_rate": 0.01,
    "max_inference_latency_ms": 200.0,
    "require_gold_set": True,
}


def evaluate_promotion(evidence: dict, gates: dict | None = None) -> dict:
    """Apply every gate; missing evidence fails rather than being skipped."""
    gates = {**PROMOTION_GATES, **(gates or {})}
    checks: list[dict] = []

    def _check(name, value, ok, requirement):
        checks.append({
            "gate": name,
            "value": (float(value) if isinstance(value, (int, float, np.floating))
                      else value),
            "requirement": requirement,
            "passed": bool(ok),
        })

    v = evidence.get("sources_meeting_lift")
    _check("weak_label_reproduction", v,
           v is not None and v >= gates["min_sources_meeting_lift"],
           f">= {gates['min_sources_meeting_lift']} sources with PR-AUC lift >= {gates['min_pr_auc_lift']}")

    v = evidence.get("worst_temporal_pr_auc_lift")
    _check("temporal_validation", v, v is not None and v >= gates["min_pr_auc_lift"],
           f"worst-source temporal PR-AUC lift >= {gates['min_pr_auc_lift']}")

    v = evidence.get("worst_spatial_pr_auc_lift")
    _check("spatial_validation", v, v is not None and v >= gates["min_spatial_pr_auc_lift"],
           f"worst geographic-block PR-AUC lift >= {gates['min_spatial_pr_auc_lift']}")

    v = evidence.get("gold_set_labelled")
    _check("gold_set", v, bool(v) if gates["require_gold_set"] else True,
           "a human-reviewed gold set exists and has been scored")

    v = evidence.get("worst_ece")
    _check("calibration", v, v is not None and v <= gates["max_ece"],
           f"worst-source ECE <= {gates['max_ece']}")

    v = evidence.get("sources_below_lift")
    _check("no_source_degradation", v, v is not None and v == 0,
           "no source below the PR-AUC lift floor")

    v = evidence.get("unknown_rate")
    _check("abstention_behaviour", v,
           v is not None and gates["min_unknown_rate"] <= v <= gates["max_unknown_rate"],
           f"unknown rate within [{gates['min_unknown_rate']}, {gates['max_unknown_rate']}]")

    v = evidence.get("missing_evidence_tested")
    _check("missing_evidence", v, bool(v),
           "missing-evidence behaviour exercised by a test")

    v = evidence.get("latency_ms")
    _check("latency", v, v is not None and v <= gates["max_inference_latency_ms"],
           f"<= {gates['max_inference_latency_ms']} ms per request")

    v = evidence.get("artifact_reproducible")
    _check("reproducible_artifact", v, bool(v),
           "bundle reloads and reproduces its recorded metrics")

    failed = [c["gate"] for c in checks if not c["passed"]]
    return {"promote": not failed, "failed_gates": failed, "checks": checks, "gates": gates}


# ---------------------------------------------------------------------------
# Registry (S39, S40)
# ---------------------------------------------------------------------------


class SourceRegistry:
    """Immutable filesystem registry: ``registry/v{n}/``."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def versions(self) -> list[str]:
        return sorted((p.name for p in self.root.iterdir()
                       if p.is_dir() and p.name.startswith("v")),
                      key=lambda n: int(n[1:]) if n[1:].isdigit() else 0)

    def next_version(self) -> str:
        return f"v{len(self.versions()) + 1}"

    def register(self, bundle: dict, metadata: dict, metrics: dict,
                 feature_schema: dict, label_schema: dict,
                 calibration: dict, version: str | None = None) -> Path:
        import joblib

        version = version or self.next_version()
        path = self.root / version
        if path.exists():
            raise FileExistsError(f"{path} already exists — registry versions are immutable")
        path.mkdir(parents=True)
        joblib.dump(bundle, path / "model.joblib")
        for name, payload in (("metadata", metadata), ("metrics", metrics),
                              ("feature_schema", feature_schema),
                              ("label_schema", label_schema),
                              ("calibration", calibration)):
            (path / f"{name}.json").write_text(json.dumps(payload, indent=2, default=str))
        (self.root / "latest.json").write_text(json.dumps({
            "version": version,
            "model_version": metadata.get("model_version"),
            "promoted": bool(metadata.get("promoted", False)),
            "updated_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        }, indent=2))
        return path

    def load(self, version: str | None = None) -> dict:
        import joblib

        if version is None:
            pointer = self.root / "latest.json"
            if not pointer.exists():
                raise FileNotFoundError("no registered source-likelihood model")
            version = json.loads(pointer.read_text())["version"]
        path = self.root / version
        return {
            "bundle": joblib.load(path / "model.joblib"),
            "metadata": json.loads((path / "metadata.json").read_text()),
            "metrics": json.loads((path / "metrics.json").read_text()),
            "feature_schema": json.loads((path / "feature_schema.json").read_text()),
            "label_schema": json.loads((path / "label_schema.json").read_text()),
            "calibration": json.loads((path / "calibration.json").read_text()),
            "path": path,
        }

    def index(self) -> pd.DataFrame:
        rows = []
        for version_dir in sorted(self.root.glob("v*")):
            meta_file = version_dir / "metadata.json"
            if not meta_file.exists():
                continue
            meta = json.loads(meta_file.read_text())
            rows.append({
                "version": version_dir.name,
                "model_version": meta.get("model_version"),
                "model_type": meta.get("model_type"),
                "promoted": meta.get("promoted"),
                "created_at": meta.get("created_at"),
            })
        return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Inference (S33-S35, S38, S45)
# ---------------------------------------------------------------------------

EVIDENCE_PHRASES = {
    "biomass_burning": [
        ("upwind_fire_frp_50km", "high upwind fire radiative power", 0.0, "gt"),
        ("fire_count_20km_24h", "active fires detected within 20 km", 0.0, "gt"),
        ("crop_burning_window", "inside the stubble-burning calendar window", 0.5, "gt"),
    ],
    "traffic": [
        ("no2_level_anomaly", "NO2 above this station\u2019s normal", None, "high"),
        ("rolling_corr_no2_pm25", "NO2 and PM2.5 rising together", 0.4, "gt"),
        ("hour", "within commuting hours", None, "rush"),
    ],
    "industrial": [
        ("so2_level_anomaly", "SO2 above this station\u2019s normal", None, "high"),
        ("stagnation_flag", "stagnant air", 0.5, "gt"),
        ("station_weekend_ratio", "pollution persists through the weekend", 1.0, "gt"),
    ],
    "dust": [
        ("cams_dust", "high modelled dust concentration", None, "high"),
        ("coarse_fraction_anomaly", "coarse-dominated particle mix", 1.4, "gt"),
        ("relative_humidity_2m", "dry air", 40.0, "lt"),
    ],
    "regional_transport": [
        ("upwind_pm25_mean", "elevated PM2.5 upwind", None, "high"),
        ("transport_direction_consistency", "persistent transport direction", 0.8, "gt"),
        ("wind_speed_10m", "sustained wind", None, "high"),
    ],
}

SOURCE_EVIDENCE_FAMILY = {
    "biomass_burning": "evidence_fire_available",
    "traffic": "evidence_copollutant_available",
    "industrial": "evidence_copollutant_available",
    "dust": "evidence_copollutant_available",
    "regional_transport": "evidence_upwind_available",
}


class SourceLikelihoodPredictor:
    """Production source-likelihood service.

    Returns independent per-source likelihoods with supporting evidence,
    abstains when the evidence cannot separate anything, and degrades rather
    than failing when a feed is missing. It never converts missing evidence
    into negative evidence (plan section 45) — an unavailable family lowers
    confidence and is reported as ``unavailable``.
    """

    def __init__(self, registry: SourceRegistry, version: str | None = None,
                 min_evidence_coverage: float = 0.4,
                 unknown_threshold: float = 0.35):
        self.registry = registry
        self.min_evidence_coverage = min_evidence_coverage
        self.unknown_threshold = unknown_threshold
        self.entry = registry.load(version)
        self.bundle = self.entry["bundle"]
        self.classifiers: dict[str, SourceClassifier] = self.bundle["classifiers"]
        self.metadata = self.entry["metadata"]

    def _evidence_for(self, source: str, row: pd.Series) -> list[str]:
        phrases = []
        for column, phrase, threshold, mode in EVIDENCE_PHRASES.get(source, []):
            if column not in row.index or pd.isna(row[column]):
                continue
            value = float(row[column]) if not isinstance(row[column], str) else np.nan
            if mode == "gt" and threshold is not None and value > threshold:
                phrases.append(phrase)
            elif mode == "lt" and threshold is not None and value < threshold:
                phrases.append(phrase)
            elif mode == "rush" and int(value) in (7, 8, 9, 18, 19, 20):
                phrases.append(phrase)
            elif mode == "high":
                reference = self.bundle.get("evidence_reference", {}).get(column)
                if reference is not None and value >= reference:
                    phrases.append(phrase)
        return phrases

    def predict(self, row: pd.DataFrame) -> dict:
        if len(row) != 1:
            raise ValueError("predict() expects exactly one feature row")
        started = time.perf_counter()
        series = row.iloc[0]

        likelihoods: dict[str, dict] = {}
        for source, classifier in self.classifiers.items():
            family = SOURCE_EVIDENCE_FAMILY.get(source)
            available = bool(series.get(family, 1)) if family else True
            try:
                probability = float(classifier.predict_proba(row)[0])
                status = "available" if available else "unavailable"
            except Exception as exc:  # a broken feature row must not 500
                probability, status = float("nan"), f"error: {exc}"

            entry = {
                "likelihood": None if not np.isfinite(probability) else round(probability, 4),
                "evidence_status": status,
                "threshold": classifier.threshold,
                "supported": bool(np.isfinite(probability)
                                  and probability >= classifier.threshold
                                  and available),
                "evidence": self._evidence_for(source, series) if available else [],
            }
            if not available:
                # Missing evidence lowers confidence; it never argues against.
                entry["note"] = "evidence family unavailable — likelihood is uninformative"
            likelihoods[source] = entry

        usable = {s: e for s, e in likelihoods.items()
                  if e["likelihood"] is not None and e["evidence_status"] == "available"}
        coverage = float(series.get("evidence_coverage", 0.0))

        if usable:
            ranked = sorted(usable.items(), key=lambda kv: kv[1]["likelihood"], reverse=True)
            primary, primary_entry = ranked[0]
            top = primary_entry["likelihood"]
            second = ranked[1][1]["likelihood"] if len(ranked) > 1 else 0.0
            secondary = [s for s, e in ranked[1:] if e["supported"]]
            conflict = float(second / top) if top > 0 else 0.0
        else:
            primary, top, second, secondary, conflict = None, 0.0, 0.0, [], 0.0

        confidence = float(np.clip(top * (1.0 - conflict) * max(coverage, 0.1), 0.0, 1.0))
        unknown_probability = float(np.clip((1.0 - top) * (1.0 - 0.5 * coverage), 0.0, 1.0))

        abstain = (
            not usable
            or coverage < self.min_evidence_coverage
            or top < self.unknown_threshold
            or not any(e["supported"] for e in usable.values())
        )
        if abstain:
            reason = (
                "no source model could be evaluated" if not usable
                else "insufficient evidence coverage" if coverage < self.min_evidence_coverage
                else "no source exceeded its operating threshold"
            )
            primary_out, secondary = None, []
        else:
            reason = None
            primary_out = primary

        return {
            "location_id": str(series.get("location_id", "unknown")),
            "timestamp": pd.Timestamp(series["timestamp_utc"]).isoformat(),
            "schema_version": SCHEMA["schema_version"],
            "label_schema_version": SCHEMA["label_schema_version"],
            "source_likelihoods": {s: e["likelihood"] for s, e in likelihoods.items()},
            "evidence_status": {s: e["evidence_status"] for s, e in likelihoods.items()},
            "primary_source": primary_out,
            "secondary_sources": secondary,
            "attribution_confidence": round(confidence, 4),
            "unknown_probability": round(unknown_probability, 4),
            "conflict_score": round(conflict, 4),
            "abstained": bool(abstain),
            "abstain_reason": reason,
            "evidence_coverage": round(coverage, 3),
            "evidence_quality": str(evidence_quality(pd.Series([coverage])).iloc[0]),
            "evidence": {s: e["evidence"] for s, e in likelihoods.items() if e["evidence"]},
            "model_version": self.metadata.get("model_version"),
            "statement": self._statement(primary_out, secondary, abstain),
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }

    @staticmethod
    def _statement(primary: str | None, secondary: list[str], abstain: bool) -> str:
        """Wording is a safety control, not presentation (plan section 47)."""
        if abstain or primary is None:
            return ("Available evidence is insufficient to indicate a likely "
                    "contributing source.")
        readable = primary.replace("_", " ")
        text = (f"{readable.capitalize()} is the most likely contributing source "
                f"based on available evidence.")
        if secondary:
            others = ", ".join(s.replace("_", " ") for s in secondary)
            text += f" {others.capitalize()} may also be contributing."
        return text


# ---------------------------------------------------------------------------
# Self-test (S48 "artifact reproducible", and the leakage rules above)
# Run: python source_toolkit.py
# ---------------------------------------------------------------------------


def _synthetic_frame(n_stations: int = 4, hours: int = 8760, seed: int = 0) -> pd.DataFrame:
    """A full synthetic year.

    The span matters: LF_CROP_SEASON and LF_DUST_METEOROLOGY are gated on the
    stubble-burning and pre-monsoon calendar windows, so a frame shorter than
    a year leaves them permanently silent and the "every LF fires" assertion
    would be testing the calendar rather than the code.
    """
    rng = np.random.default_rng(seed)
    frames = []
    start = pd.Timestamp("2025-01-01", tz="UTC")
    for s in range(n_stations):
        ts = pd.date_range(start, periods=hours, freq="h")
        diurnal = 15 * np.sin(2 * np.pi * (ts.hour - 6) / 24)
        pm25 = np.clip(45 + diurnal + rng.normal(0, 10, hours).cumsum() * 0.12, 2, None)
        frame = pd.DataFrame({
            "location_id": f"S{s}",
            "timestamp_utc": ts,
            "pm25": pm25.astype("float32"),
            "lat": 20.0 + s * 0.8,
            "lon": 76.0 + s * 0.7,
            "temperature_2m": rng.uniform(12, 40, hours).astype("float32"),
            "relative_humidity_2m": rng.uniform(15, 95, hours).astype("float32"),
            "wind_speed_10m": rng.uniform(1, 25, hours).astype("float32"),
            "wind_direction_10m": (rng.uniform(0, 360, hours)).astype("float32"),
            "boundary_layer_height": rng.uniform(80, 2000, hours).astype("float32"),
            "surface_pressure": rng.uniform(960, 1010, hours).astype("float32"),
            "cams_no2": rng.uniform(2, 60, hours).astype("float32"),
            "cams_co": rng.uniform(100, 900, hours).astype("float32"),
            "cams_so2": rng.uniform(1, 40, hours).astype("float32"),
            "cams_o3": rng.uniform(20, 150, hours).astype("float32"),
            "cams_pm10": (pm25 * rng.uniform(0.8, 4.0, hours)).astype("float32"),
            "cams_dust": rng.exponential(60, hours).astype("float32"),
            "upwind_fire_frp_50km": (rng.random(hours) < 0.15) * rng.exponential(40, hours),
            "fire_count_20km_24h": (rng.random(hours) < 0.1) * rng.integers(0, 8, hours),
            "upwind_pm25_mean": (pm25 * rng.uniform(0.5, 1.6, hours)).astype("float32"),
            "crop_burning_window": (ts.month.isin([10, 11])).astype("int8"),
            "elevation_m": 200.0 + s * 30,
        })
        frame["hour"] = frame["timestamp_utc"].dt.hour
        frame["is_weekend"] = (frame["timestamp_utc"].dt.dayofweek >= 5).astype("int8")
        month = frame["timestamp_utc"].dt.month
        frame["season"] = np.select(
            [month.isin([12, 1, 2]), month.isin([3, 4, 5]), month.isin([6, 7, 8, 9])],
            ["winter", "pre_monsoon", "monsoon"], default="post_monsoon")
        frame["stagnation_flag"] = (
            (frame["wind_speed_10m"] < 5.0) & (frame["boundary_layer_height"] < 400)
        ).astype("int8")
        frame["fire_active_flag"] = (frame["fire_count_20km_24h"] > 0).astype("int8")
        # Episodes: contiguous runs above the station's 80th percentile.
        high = frame["pm25"] > frame["pm25"].quantile(0.80)
        group = (high != high.shift()).cumsum()
        frame["event_id"] = np.where(high, f"S{s}_" + group.astype(str), None)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def _run_self_tests() -> None:
    import tempfile

    df = _synthetic_frame()

    # -- contract and quality ----------------------------------------------
    contract = validate_contract(df)
    assert contract["status"] == "PASS", contract
    report, coverage = quality_report(df)
    assert report["quality_status"] == "PASS", report["failures"]
    assert len(coverage) == df["location_id"].nunique()
    print("PASS test_data_contract, test_quality_report")

    df = add_evidence_availability(df)
    assert {"evidence_fire_available", "evidence_copollutant_available",
            "evidence_coverage"} <= set(df.columns)
    assert df["evidence_coverage"].between(0, 1).all()
    print("PASS test_evidence_availability")

    # Missing evidence must not read as negative evidence.
    blind = df.copy()
    blind["upwind_fire_frp_50km"] = np.nan
    blind = add_evidence_availability(blind)
    thresholds = fit_thresholds(df)
    votes_full = apply_labeling_functions(df, thresholds)
    votes_blind = apply_labeling_functions(blind, thresholds)
    assert (votes_blind["LF_FIRE_UPWIND"] == 0).all(), "an LF voted on absent evidence"
    assert (votes_full["LF_FIRE_UPWIND"] != 0).any()
    print("PASS test_missing_evidence_abstains_not_contradicts")

    # -- features -----------------------------------------------------------
    df = add_pollutant_features(df)
    assert {"no2_pm25_ratio", "pm10_pm25_ratio", "rolling_corr_no2_pm25"} <= set(df.columns)
    df = add_transport_features(df)
    assert df["transport_direction_consistency"].dropna().between(0, 1.0001).all()
    fit_end = df["timestamp_utc"].quantile(0.70)
    df, context = add_station_context(df, fit_end)
    assert df["station_type_proxy"].notna().all()
    print("PASS test_pollutant_features, test_transport_consistency, test_station_context")

    tampered = df[["location_id", "timestamp_utc", "pm25"]].copy()
    future = tampered["timestamp_utc"] >= fit_end
    tampered.loc[future, "pm25"] *= 20
    _, context_again = add_station_context(tampered, fit_end)
    assert np.allclose(context["station_mean_pm25"].to_numpy(),
                       context_again["station_mean_pm25"].to_numpy())
    print("PASS test_station_context_is_train_only")

    # -- labeling functions -------------------------------------------------
    thresholds = fit_thresholds(df[df["timestamp_utc"] < fit_end])
    votes = apply_labeling_functions(df, thresholds)
    assert votes.shape[1] == len(LABELING_FUNCTIONS)
    assert set(np.unique(votes.to_numpy())) <= {-1, 0, 1}
    assert (votes != 0).any(axis=0).all(), "an LF never fired on synthetic data"
    print(f"PASS test_labeling_functions ({votes.shape[1]} functions, "
          f"{float((votes != 0).mean().mean()):.1%} non-abstain rate)")

    labels = aggregate_weak_labels(votes)
    for source in SOURCES:
        assert f"y_{source}" in labels.columns
        probs = labels[f"{source}_weak_prob"]
        assert probs.dropna().between(0, 1).all()
        # Abstention must be NaN, never a 0.5 that clears the threshold.
        abstained = labels[f"{source}_coverage"] == 0
        assert probs[abstained].isna().all(), f"{source}: abstention leaked a probability"
        assert (labels.loc[abstained, f"y_{source}"] == 0).all(), (
            f"{source}: a fully-abstaining row was labelled positive"
        )
    print("PASS test_weak_label_aggregation, test_abstention_is_not_support")

    # THE architectural fix: labels must be able to co-occur.
    multi = int((labels[[f"y_{s}" for s in SOURCES]].sum(axis=1) > 1).sum())
    assert multi > 0, (
        "no row supports two sources — the labels are still mutually exclusive, "
        "which is the exact defect this rewrite exists to fix"
    )
    print(f"PASS test_labels_are_multi_label ({multi:,} rows support 2+ sources)")

    assert labels["unknown_probability"].between(0, 1).all()
    assert "mixed_unknown" not in SOURCES
    assert (labels.loc[labels["is_unknown"] == 1,
                       [f"y_{s}" for s in SOURCES]].sum(axis=1) == 0).all()
    print("PASS test_unknown_is_derived_not_a_class")

    conflicts = conflict_report(labels)
    assert len(conflicts) == len(SOURCES) * (len(SOURCES) - 1) // 2
    print("PASS test_conflict_report")

    # -- leakage ------------------------------------------------------------
    work = df.join(labels)
    features = select_features(work)
    assert_no_label_leakage(features)
    for banned in ("pm25", "cams_dust", "upwind_fire_frp_50km", "no2_level_anomaly",
                   "cams_no2", "no2_pm25_ratio", "cams_no2_station_median",
                   "n_sources_evaluated", "pm25_lag_1h", "upwind_fire_count_50km",
                   "upwind_pm25_mean", "pm25_local_excess", "wind_u", "wind_v",
                   "co_pm25_ratio", "evidence_upwind_available", "station_mean_pm25"):
        assert banned not in features, f"{banned} reaches the classifier"
    try:
        assert_no_label_leakage(features + ["pm25"])
        raise AssertionError("leakage check failed to fire")
    except AssertionError as exc:
        assert "leaked" in str(exc)
    print(f"PASS test_no_label_leakage ({len(features)} features, "
          f"{len(LF_INPUT_COLUMNS)} LF inputs excluded)")

    # -- events and splits --------------------------------------------------
    events = build_events(work, labels)
    assert len(events) > 10 and "dominant_source" in events.columns
    tr, va, te = event_split(work, events)
    def _keys(part):
        return set(part["location_id"].astype(str) + "::" + part["event_id"].astype(str))

    assert not (_keys(tr) & _keys(te)), "an event straddles the train/test boundary"
    print(f"PASS test_event_split ({len(events)} events, no straddling)")

    blocks = geographic_blocks(work, n_blocks=3)
    assert blocks["geo_block"].nunique() == 3
    print("PASS test_geographic_blocks")

    sheet = gold_set_sample(events, size=30)
    assert (sheet["expert_primary_source"] == "").all(), (
        "the gold sheet must ship unlabelled — prefilling it from the "
        "heuristics would make it a copy of the system it audits"
    )
    assert "review_notes" in sheet.columns
    print(f"PASS test_gold_set_sheet_is_unlabelled ({len(sheet)} events sampled)")

    # -- models -------------------------------------------------------------
    ctr, cva, cte = chrono_split(work)
    # Pick the most *balanced* source, not the most positive one: a source
    # that is positive on every training row cannot be fitted at all.
    def _balance(s):
        y = ctr[f"y_{s}"]
        return min(int(y.sum()), int((1 - y).sum()))

    source = max(SOURCES, key=_balance)
    assert _balance(source) > 50, "no source is balanced enough to fit in the synthetic frame"
    clf = SourceClassifier.fit(ctr, features, source, kind="logistic")
    raw = clf.raw_proba(cte)
    assert ((raw >= 0) & (raw <= 1)).all()
    metrics = calibration_metrics(cte[f"y_{source}"].to_numpy(), raw)
    assert np.isfinite(metrics["pr_auc"]) and np.isfinite(metrics["ece"])
    print(f"PASS test_classifier_fit ({source}: PR-AUC {metrics['pr_auc']:.3f}, "
          f"lift {metrics['pr_auc_lift']:.2f}x)")

    for method in ("sigmoid", "isotonic", "beta"):
        candidate = SourceClassifier.fit(ctr, features, source, kind="logistic")
        candidate.calibrate(cva, method=method)
        proba = candidate.predict_proba(cte)
        assert ((proba >= 0) & (proba <= 1)).all(), f"{method} produced out-of-range probability"
    print("PASS test_calibration_methods (sigmoid, isotonic, beta)")

    curve = reliability_curve(cte[f"y_{source}"].to_numpy(), raw)
    assert len(curve) > 1 and {"mean_predicted", "observed_rate"} <= set(curve.columns)
    best = tune_thresholds(cva[f"y_{source}"].to_numpy(), clf.raw_proba(cva))
    assert 0.0 < best["threshold"] < 1.0
    print(f"PASS test_reliability_curve, test_threshold_tuning (t={best['threshold']})")

    decision = evaluate_promotion({"sources_meeting_lift": 5, "worst_ece": 0.02})
    assert not decision["promote"] and "gold_set" in decision["failed_gates"]
    print("PASS test_promotion_requires_gold_set")

    # -- registry and inference ---------------------------------------------
    classifiers = {}
    for src in SOURCES:
        if _balance(src) < 30:
            continue
        model = SourceClassifier.fit(ctr, features, src, kind="logistic")
        model.calibrate(cva, method="isotonic")
        model.threshold = tune_thresholds(cva[f"y_{src}"].to_numpy(),
                                          model.raw_proba(cva))["threshold"]
        classifiers[src] = model
    assert classifiers, "no source had enough positives in the synthetic frame"

    with tempfile.TemporaryDirectory() as tmp:
        registry = SourceRegistry(Path(tmp))
        bundle = {"classifiers": classifiers, "features": features,
                  "evidence_reference": {c: float(work[c].quantile(0.75))
                                         for c in ("no2_pm25_ratio", "so2_pm25_ratio",
                                                   "cams_dust", "upwind_pm25_mean",
                                                   "wind_speed_10m") if c in work.columns}}
        registry.register(bundle,
                          {"model_version": "test-v1", "promoted": True,
                           "model_type": "per_source_logistic"},
                          {"note": "self-test"}, {"features": features},
                          {"sources": list(SOURCES)}, {"method": "isotonic"})
        assert registry.versions() == ["v1"]
        try:
            registry.register(bundle, {}, {}, {}, {}, {}, version="v1")
            raise AssertionError("registry overwrote an immutable version")
        except FileExistsError:
            pass
        print("PASS test_registry_immutability")

        predictor = SourceLikelihoodPredictor(registry)
        response = predictor.predict(cte.head(1))
        assert set(response["source_likelihoods"]) == set(classifiers)
        assert response["statement"]
        assert "proven" not in response["statement"].lower()
        assert "caused by" not in response["statement"].lower()
        print(f"PASS test_predict_contract, test_statement_wording")
        print(f"      statement: {response['statement']}")

        # Independence: likelihoods must not be forced to sum to 1.
        values = [v for v in response["source_likelihoods"].values() if v is not None]
        assert abs(sum(values) - 1.0) > 1e-6 or len(values) == 1, (
            "likelihoods sum to 1 — that is a softmax, not independent likelihoods"
        )
        print("PASS test_likelihoods_are_independent")

        # Missing evidence: reported as unavailable, never as a low likelihood.
        blind_row = cte.head(1).copy()
        blind_row["evidence_fire_available"] = 0
        blind_out = predictor.predict(blind_row)
        if "biomass_burning" in classifiers:
            assert blind_out["evidence_status"]["biomass_burning"] == "unavailable"
        print("PASS test_missing_evidence_reported_not_penalised")

        empty = cte.head(1).copy()
        for column in features:
            empty[column] = np.nan
        empty["evidence_coverage"] = 0.0
        out = predictor.predict(empty)
        assert out["abstained"] and out["primary_source"] is None
        assert "insufficient" in out["statement"].lower()
        print("PASS test_abstention_on_no_evidence")

        latency = out["latency_ms"]
        assert latency < 200, f"latency {latency} ms over SLA"
        print(f"PASS test_latency ({latency:.1f} ms)")

    print("\nALL SELF-TESTS PASSED")


if __name__ == "__main__":
    _run_self_tests()
