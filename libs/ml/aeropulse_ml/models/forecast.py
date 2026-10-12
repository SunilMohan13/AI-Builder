"""``pm25_forecast``: pooled quantile regression, P10/P50/P90 (LLD APAC 7.1).

The LLD names LightGBM; this build uses scikit-learn's histogram gradient
boosting with quantile loss, which is the same model class and is already a
dependency. One model per quantile, pooled over regions and horizons
(``horizon_hours`` is a feature).

Where the station's current value is known, the quantiles are of the change
from it (``pm25_target - pm25``), added back at prediction time, so the model
starts from persistence and learns only the correction. Rows without a current
value use quantiles of the level itself.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd
from aeropulse_common.errors import TrainingError
from aeropulse_contracts import ModelFamily, StrategyResult
from aeropulse_contracts.feature_spec import ML_FEATURE_VERSION, PM25_FORECAST
from sklearn.ensemble import HistGradientBoostingRegressor

from aeropulse_ml.baselines import Baseline, forecast_baselines
from aeropulse_ml.evaluation.holdouts import regression_metrics
from aeropulse_ml.evaluation.metrics import forecast_metrics, skill
from aeropulse_ml.models.base import (
    MIN_EVALUATED_FOLDS,
    MIN_FIT_ROWS,
    RANDOM_STATE,
    FittedModel,
    Metrics,
    column,
    fit_matrix,
    folds_evaluated,
    matrix,
    metric,
)

QUANTILES = (0.1, 0.5, 0.9)
#: Nominal P10-P90 coverage is 0.80; below this the interval is not honest.
MIN_INTERVAL_COVERAGE = 0.70
#: Persistence is always computable where a label exists, so it must be beaten.
REQUIRED_BASELINE = "persistence"
#: The station bucket ending at ``t``: what persistence predicts.
CURRENT = "pm25"


def _group(h: float) -> str:
    return f"h={int(h)}"


def _quantile_models(x: np.ndarray, y: np.ndarray) -> dict[float, HistGradientBoostingRegressor]:
    return {
        q: HistGradientBoostingRegressor(
            loss="quantile", quantile=q, random_state=RANDOM_STATE
        ).fit(x, y)
        for q in QUANTILES
    }


def _quantiles(models: Mapping[float, HistGradientBoostingRegressor], x: np.ndarray) -> np.ndarray:
    stacked = np.column_stack([models[q].predict(x) for q in QUANTILES])
    # Independent quantile models can cross; sorting restores P10<=P50<=P90.
    stacked.sort(axis=1)
    return stacked


class Pm25ForecastPlugin:
    family: ModelFamily = "pm25_forecast"
    feature_set = PM25_FORECAST
    label = "pm25_target"
    trained = True
    uses_calibration = False
    algorithm = (
        "sklearn.HistGradientBoostingRegressor(loss=quantile) P10/P50/P90 of the change "
        "from current PM2.5 (level where unknown), pooled"
    )
    version_prefix = "hgbq-forecast"

    def fit(
        self, train: pd.DataFrame, calibration: pd.DataFrame | None, *, model_version: str
    ) -> FittedModel:
        y = column(train, self.label)
        keep = np.isfinite(y)
        if keep.sum() < MIN_FIT_ROWS:
            raise TrainingError(
                f"pm25_forecast: {int(keep.sum())} labelled rows, need {MIN_FIT_ROWS}"
            )
        x, missing = fit_matrix(train.loc[keep], self.feature_set.names)
        payload: dict[str, object] = {"quantiles": _quantile_models(x, y[keep])}
        now = column(train, CURRENT)
        has_now = keep & np.isfinite(now)
        if has_now.sum() >= MIN_FIT_ROWS:
            x_now, _ = fit_matrix(train.loc[has_now], self.feature_set.names)
            payload["change"] = _quantile_models(x_now, (y - now)[has_now])
        return FittedModel(
            family=self.family,
            model_version=model_version,
            algorithm=self.algorithm,
            feature_names=self.feature_set.names,
            ml_feature_version=ML_FEATURE_VERSION,
            calibrated=False,
            payload=payload,
            params={
                "quantiles": list(QUANTILES),
                "random_state": RANDOM_STATE,
                "missing_in_training": missing,
                "change_rows": int(has_now.sum()) if "change" in payload else 0,
            },
        )

    def predict(self, model: FittedModel, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(columns=["p10", "p50", "p90"], index=frame.index)
        x = matrix(frame, model.feature_names)
        stacked = _quantiles(model.payload["quantiles"], x)
        change = model.payload.get("change")
        if change is not None:
            now = column(frame, CURRENT)
            has_now = np.isfinite(now)
            if has_now.any():
                stacked[has_now] = now[has_now, None] + _quantiles(change, x[has_now])
        return pd.DataFrame(stacked, columns=["p10", "p50", "p90"], index=frame.index)

    def baselines(self) -> list[Baseline]:
        return forecast_baselines()

    def evaluate(
        self,
        model: FittedModel,
        test: pd.DataFrame,
        prediction: pd.DataFrame,
        baselines: Mapping[str, np.ndarray],
    ) -> Metrics:
        out: Metrics = {}
        horizons = column(test, "horizon_hours")
        y_all = column(test, self.label)
        threshold_all = column(test, "region_threshold_ugm3")
        for h in sorted(set(horizons[np.isfinite(horizons)].tolist())):
            sel = horizons == h
            y = y_all[sel]
            p10, p50, p90 = (
                prediction[c].to_numpy(dtype=float)[sel] for c in ("p10", "p50", "p90")
            )
            model_block = dict(
                forecast_metrics(y, p50, p10=p10, p90=p90, threshold=threshold_all[sel])
            )
            if not model_block:
                continue
            group: dict[str, dict[str, float | None]] = {}
            for name, values in baselines.items():
                b = values[sel]
                mask = np.isfinite(b) & np.isfinite(y) & np.isfinite(p50)
                base = regression_metrics(y[mask], b[mask])
                group[name] = dict(base)
                model_on_mask = regression_metrics(y[mask], p50[mask])
                model_block[f"skill_rmse_vs_{name}"] = skill(
                    model_on_mask.get("rmse"), base.get("rmse")
                )
            group["model"] = model_block
            out[_group(h)] = group
        return out

    def gate(self, strategies: Mapping[str, StrategyResult]) -> list[str]:
        failures: list[str] = []
        rolling = strategies.get("purged_rolling_origin")
        if rolling is None or not rolling.available:
            reason = rolling.reason if rolling else "not run"
            return [f"purged rolling-origin not available: {reason}"]
        groups = sorted(g for g in rolling.metrics if g.startswith("h="))
        if not groups:
            return ["purged rolling-origin evaluated no horizon"]
        for group in groups:
            n = folds_evaluated(rolling, group)
            if n < MIN_EVALUATED_FOLDS:
                failures.append(f"{group}: {n} evaluated folds (need {MIN_EVALUATED_FOLDS})")
                continue
            for name in (b.name for b in forecast_baselines()):
                value = metric(rolling, group, "model", f"skill_rmse_vs_{name}")
                if value is None:
                    if name == REQUIRED_BASELINE:
                        failures.append(f"{group}: no rows to compare against {name}")
                    continue
                if value <= 0:
                    failures.append(
                        f"{group}: RMSE skill vs {name} is {value:+.4f} (must exceed 0)"
                    )
            coverage = metric(rolling, group, "model", "coverage_p10_p90")
            if coverage is None or coverage < MIN_INTERVAL_COVERAGE:
                failures.append(
                    f"{group}: P10-P90 coverage is {coverage} (must reach {MIN_INTERVAL_COVERAGE})"
                )
        transfer = strategies.get("leave_region_out")
        if transfer is not None and transfer.available:
            for group in sorted(g for g in transfer.metrics if g.startswith("h=")):
                value = metric(transfer, group, "model", f"skill_rmse_vs_{REQUIRED_BASELINE}")
                if value is not None and value <= 0:
                    failures.append(
                        f"leave-region-out {group}: skill vs persistence is {value:+.4f}; "
                        "the model does not transfer to this region"
                    )
        return failures

    def region_calibrated(
        self, model: FittedModel, strategies: Mapping[str, StrategyResult]
    ) -> bool:
        return False
