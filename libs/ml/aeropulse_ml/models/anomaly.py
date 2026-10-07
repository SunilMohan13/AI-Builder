"""``anomaly``: observed PM2.5 against its expected range (LLD APAC 7.1).

At serving, the expected range is the forecast's own P10-P90 for that hour
when a served forecast exists (columns ``forecast_p10/p50/p90``). Otherwise,
and always in evaluation, it is a local hour-of-week quantile table per
station fitted on training rows only, falling back to coarser bins. No label
is trained on; the gate measures agreement with the hazard label.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd
from aeropulse_common.errors import TrainingError
from aeropulse_contracts import ModelFamily, StrategyResult
from aeropulse_contracts.feature_spec import HAZARD_24H, ML_FEATURE_VERSION

from aeropulse_ml.baselines import Baseline, anomaly_baselines
from aeropulse_ml.evaluation.metrics import alert_metrics
from aeropulse_ml.features.local_time import local_hour, local_hour_of_week
from aeropulse_ml.gates import MIN_DETECTION_F1
from aeropulse_ml.models.base import (
    MIN_EVALUATED_FOLDS,
    FittedModel,
    Metrics,
    column,
    folds_evaluated,
    metric,
)

GROUP = "24h"
QUANTILES = (0.1, 0.5, 0.9)
#: A quantile bin needs this many training values; otherwise a coarser bin answers.
MIN_BIN_ROWS = 8
#: Finest first.
LEVELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cell_hour_of_week", ("cell", "how")),
    ("cell_hour", ("cell", "hod")),
    ("region_hour", ("region_id", "hod")),
    ("region", ("region_id",)),
)
#: Below this spread the score's denominator is floored, in ug/m3.
MIN_SPREAD_UGM3 = 1.0


def _keys(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region_id": frame["region_id"].to_numpy(),
            "cell": frame["cell"].to_numpy(),
            "how": local_hour_of_week(frame),
            "hod": np.floor(local_hour(frame)),
        },
        index=frame.index,
    )


class AnomalyPlugin:
    family: ModelFamily = "anomaly"
    feature_set = HAZARD_24H
    label = "hazard_24h_target"
    trained = True
    uses_calibration = False
    algorithm = "hour-of-week quantile table per station (P10/P50/P90), forecast P90 when served"
    version_prefix = "quantile-anomaly"

    def fit(
        self, train: pd.DataFrame, calibration: pd.DataFrame | None, *, model_version: str
    ) -> FittedModel:
        data = _keys(train)
        data["pm25"] = column(train, "pm25")
        data["t"] = train["t"].to_numpy()
        data = data.dropna(subset=["pm25"]).drop_duplicates(["cell", "t"])
        if data.empty:
            raise TrainingError("anomaly: no training rows with current PM2.5")
        tables: dict[str, pd.DataFrame] = {}
        for name, keys in LEVELS:
            grouped = data.groupby(list(keys))["pm25"]
            table = grouped.quantile(list(QUANTILES)).unstack()
            table.columns = ["p10", "p50", "p90"]
            table["n"] = grouped.size()
            table = table[table["n"] >= MIN_BIN_ROWS].drop(columns="n").reset_index()
            tables[name] = table
        if all(t.empty for t in tables.values()):
            raise TrainingError(
                f"anomaly: no bin reached {MIN_BIN_ROWS} training values of current PM2.5"
            )
        return FittedModel(
            family=self.family,
            model_version=model_version,
            algorithm=self.algorithm,
            feature_names=(
                "pm25",
                "sin_hour_local",
                "cos_hour_local",
                "sin_dow_local",
                "cos_dow_local",
            ),
            ml_feature_version=ML_FEATURE_VERSION,
            calibrated=False,
            payload={"tables": tables},
            params={"quantiles": list(QUANTILES), "min_bin_rows": MIN_BIN_ROWS},
        )

    def predict(self, model: FittedModel, frame: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(
            {"p10": np.nan, "p50": np.nan, "p90": np.nan, "basis": None}, index=frame.index
        )
        if frame.empty:
            return out.assign(score=np.nan, is_anomaly=np.nan)
        keys = _keys(frame)
        for name, cols in LEVELS:
            table = model.payload["tables"][name]
            if table.empty:
                continue
            merged = keys[list(cols)].merge(table, on=list(cols), how="left")
            merged.index = frame.index
            fill = out["p90"].isna() & merged["p90"].notna()
            for c in ("p10", "p50", "p90"):
                out.loc[fill, c] = merged.loc[fill, c]
            out.loc[fill, "basis"] = f"hour_of_week:{name}"
        if "forecast_p90" in frame.columns:
            fc90 = column(frame, "forecast_p90")
            use = np.isfinite(fc90)
            out.loc[use, "p90"] = fc90[use]
            for c in ("p10", "p50"):
                fc = column(frame, f"forecast_{c}")
                take = use & np.isfinite(fc)
                out.loc[take, c] = fc[take]
            out.loc[use, "basis"] = "forecast_p90"
        pm25 = column(frame, "pm25")
        p50 = out["p50"].to_numpy(dtype=float)
        p90 = out["p90"].to_numpy(dtype=float)
        spread = np.maximum(p90 - p50, MIN_SPREAD_UGM3)
        out["score"] = (pm25 - p50) / spread
        flag = (pm25 > p90).astype(float)
        flag[~(np.isfinite(pm25) & np.isfinite(p90))] = np.nan
        out["is_anomaly"] = flag
        return out

    def baselines(self) -> list[Baseline]:
        return anomaly_baselines()

    def evaluate(
        self,
        model: FittedModel,
        test: pd.DataFrame,
        prediction: pd.DataFrame,
        baselines: Mapping[str, np.ndarray],
    ) -> Metrics:
        y = column(test, self.label)
        flag = prediction["is_anomaly"].to_numpy(dtype=float)
        scored = np.isfinite(y) & np.isfinite(flag)
        if not scored.any():
            return {}
        model_block: dict[str, float | None] = dict(alert_metrics(y[scored], flag[scored], 0.5))
        model_block["rows_scored"] = float(scored.sum())
        group: dict[str, dict[str, float | None]] = {}
        for name, values in baselines.items():
            mask = scored & np.isfinite(values)
            base = alert_metrics(y[mask], values[mask], 0.5)
            group[name] = dict(base)
            mine = alert_metrics(y[mask], flag[mask], 0.5)
            if base and mine:
                model_block[f"f1_margin_vs_{name}"] = round(mine["f1"] - base["f1"], 6)
        group["model"] = model_block
        return {GROUP: group}

    def gate(self, strategies: Mapping[str, StrategyResult]) -> list[str]:
        rolling = strategies.get("purged_rolling_origin")
        if rolling is None or not rolling.available:
            reason = rolling.reason if rolling else "not run"
            return [f"purged rolling-origin not available: {reason}"]
        n = folds_evaluated(rolling, GROUP)
        if n < MIN_EVALUATED_FOLDS:
            return [f"{n} evaluated folds (need {MIN_EVALUATED_FOLDS})"]
        failures: list[str] = []
        f1 = metric(rolling, GROUP, "model", "f1")
        if f1 is None or f1 < MIN_DETECTION_F1:
            failures.append(
                f"detection F1 against the hazard label is {f1} (must reach {MIN_DETECTION_F1})"
            )
        for name in (b.name for b in anomaly_baselines()):
            margin = metric(rolling, GROUP, "model", f"f1_margin_vs_{name}")
            if margin is None:
                failures.append(f"no rows to compare against {name}")
            elif margin <= 0:
                failures.append(f"F1 margin vs {name} is {margin:+.4f} (must exceed 0)")
        return failures

    def region_calibrated(
        self, model: FittedModel, strategies: Mapping[str, StrategyResult]
    ) -> bool:
        return False
