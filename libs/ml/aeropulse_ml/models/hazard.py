"""``pm25_hazard_24h``: classifier with isotonic calibration (LLD APAC 7.1).

The label uses each region's own AQI standard and averaging period. The
calibration map and the alerting threshold are both fitted on the
calibration slice, never on test. Without enough positives in that slice the
model stays uncalibrated and its score is a rank, not a probability.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd
from aeropulse_common.errors import TrainingError
from aeropulse_contracts import ModelFamily, StrategyResult
from aeropulse_contracts.feature_spec import HAZARD_24H, ML_FEATURE_VERSION
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression

from aeropulse_ml.baselines import Baseline, hazard_baselines
from aeropulse_ml.evaluation.holdouts import ranking_metrics
from aeropulse_ml.evaluation.metrics import choose_operating_threshold, hazard_metrics
from aeropulse_ml.gates import MAX_HAZARD_FALSE_ALERT_RATE, MIN_HAZARD_PR_AUC_MARGIN
from aeropulse_ml.models.base import (
    MIN_EVALUATED_FOLDS,
    MIN_FIT_ROWS,
    RANDOM_STATE,
    FittedModel,
    Metrics,
    column,
    fit_matrix,
    flatten,
    folds_evaluated,
    matrix,
    metric,
)

GROUP = "24h"
#: Each class needs this many rows in the calibration slice before an
#: isotonic map is fitted; fewer would calibrate to noise.
MIN_CALIBRATION_CLASS_ROWS = 10
#: A calibrated score is shown as a probability only if its measured
#: expected calibration error on held-out folds stays within this.
MAX_CALIBRATED_ECE = 0.05


class Pm25Hazard24hPlugin:
    family: ModelFamily = "pm25_hazard_24h"
    feature_set = HAZARD_24H
    label = "hazard_24h_target"
    trained = True
    uses_calibration = True
    algorithm = "sklearn.HistGradientBoostingClassifier + isotonic calibration, pooled"
    version_prefix = "hgb-hazard"

    def fit(
        self, train: pd.DataFrame, calibration: pd.DataFrame | None, *, model_version: str
    ) -> FittedModel:
        y = column(train, self.label)
        keep = np.isfinite(y)
        labels = y[keep].astype(int)
        if keep.sum() < MIN_FIT_ROWS:
            raise TrainingError(
                f"pm25_hazard_24h: {int(keep.sum())} labelled rows, need {MIN_FIT_ROWS}"
            )
        if len(set(labels.tolist())) < 2:
            raise TrainingError("pm25_hazard_24h: training rows hold a single hazard class")
        x, missing = fit_matrix(train.loc[keep], self.feature_set.names)
        clf = HistGradientBoostingClassifier(random_state=RANDOM_STATE)
        clf.fit(x, labels)
        payload: dict[str, object] = {
            "classifier": clf,
            "isotonic": None,
            "operating_threshold": None,
        }
        calibrated = False
        if calibration is not None and not calibration.empty:
            cy = column(calibration, self.label)
            ck = np.isfinite(cy)
            raw = _positive_score(clf, matrix(calibration, self.feature_set.names)[ck])
            cy = cy[ck]
            positives, negatives = int(cy.sum()), int((1 - cy).sum())
            score = raw
            if min(positives, negatives) >= MIN_CALIBRATION_CLASS_ROWS:
                iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
                iso.fit(raw, cy)
                payload["isotonic"] = iso
                calibrated = True
                score = iso.predict(raw)
            payload["operating_threshold"] = choose_operating_threshold(
                cy, score, max_false_alert_rate=MAX_HAZARD_FALSE_ALERT_RATE
            )
        return FittedModel(
            family=self.family,
            model_version=model_version,
            algorithm=self.algorithm,
            feature_names=self.feature_set.names,
            ml_feature_version=ML_FEATURE_VERSION,
            calibrated=calibrated,
            payload=payload,
            params={
                "random_state": RANDOM_STATE,
                "max_false_alert_rate": MAX_HAZARD_FALSE_ALERT_RATE,
                "min_calibration_class_rows": MIN_CALIBRATION_CLASS_ROWS,
                "missing_in_training": missing,
            },
        )

    def predict(self, model: FittedModel, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(columns=["score"], index=frame.index)
        score = _positive_score(model.payload["classifier"], matrix(frame, model.feature_names))
        iso = model.payload.get("isotonic")
        if iso is not None:
            score = iso.predict(score)
        return pd.DataFrame({"score": score}, index=frame.index)

    def baselines(self) -> list[Baseline]:
        return hazard_baselines()

    def evaluate(
        self,
        model: FittedModel,
        test: pd.DataFrame,
        prediction: pd.DataFrame,
        baselines: Mapping[str, np.ndarray],
    ) -> Metrics:
        y = column(test, self.label)
        score = prediction["score"].to_numpy(dtype=float)
        threshold = model.payload.get("operating_threshold")
        model_block = flatten("", hazard_metrics(y, score, operating_threshold=threshold))
        if not model_block:
            return {}
        model_block["calibrated"] = float(model.calibrated)
        group: dict[str, dict[str, float | None]] = {}
        for name, values in baselines.items():
            mask = np.isfinite(values) & np.isfinite(y) & np.isfinite(score)
            base = ranking_metrics(y[mask], values[mask])
            group[name] = dict(base)
            mine = ranking_metrics(y[mask], score[mask])
            if base.get("pr_auc") is not None and mine.get("pr_auc") is not None:
                model_block[f"pr_auc_margin_vs_{name}"] = round(mine["pr_auc"] - base["pr_auc"], 6)
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
        compared = 0
        for name in (b.name for b in hazard_baselines()):
            margin = metric(rolling, GROUP, "model", f"pr_auc_margin_vs_{name}")
            if margin is None:
                continue
            compared += 1
            if margin < MIN_HAZARD_PR_AUC_MARGIN:
                failures.append(
                    f"PR-AUC margin vs {name} is {margin:+.4f} "
                    f"(must reach {MIN_HAZARD_PR_AUC_MARGIN})"
                )
        if compared == 0:
            failures.append("no baseline could be compared on the held-out rows")
        false_alerts = metric(rolling, GROUP, "model", "at_operating_point.false_alert_rate")
        if false_alerts is None:
            failures.append(
                "no operating point: the calibration slice could not choose a threshold"
            )
        elif false_alerts > MAX_HAZARD_FALSE_ALERT_RATE:
            failures.append(
                f"false-alert rate is {false_alerts:.4f} at the operating point "
                f"(must not exceed {MAX_HAZARD_FALSE_ALERT_RATE})"
            )
        transfer = strategies.get("leave_region_out")
        if transfer is not None and transfer.available:
            margin = metric(transfer, GROUP, "model", "pr_auc_margin_vs_current_pm25")
            if margin is not None and margin < MIN_HAZARD_PR_AUC_MARGIN:
                failures.append(
                    f"leave-region-out PR-AUC margin vs current_pm25 is {margin:+.4f}; "
                    "the model does not transfer to this region"
                )
        return failures

    def region_calibrated(
        self, model: FittedModel, strategies: Mapping[str, StrategyResult]
    ) -> bool:
        rolling = strategies.get("purged_rolling_origin")
        every_fold = metric(rolling, GROUP, "model", "calibrated") == 1.0
        ece = metric(rolling, GROUP, "model", "ece")
        return bool(
            model.calibrated and every_fold and ece is not None and ece <= MAX_CALIBRATED_ECE
        )


def _positive_score(clf: HistGradientBoostingClassifier, x: np.ndarray) -> np.ndarray:
    if len(x) == 0:
        return np.empty(0)
    classes = [int(c) for c in np.asarray(clf.classes_).tolist()]
    return clf.predict_proba(x)[:, classes.index(1)]
