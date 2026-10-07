"""``source_likelihood``: weighted evidence from hazard profiles (LLD APAC 7.6).

A transparent heuristic, not a trained model: weights are settings in
``config/hazard_profiles/*.yaml`` and no gold label set exists. Evaluation
is descriptive (how often each class ranks first, how often nothing is
known), and the gate always reports that there is nothing to promote.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd
from aeropulse_contracts import ModelFamily, StrategyResult
from aeropulse_contracts.feature_spec import HAZARD_24H, ML_FEATURE_VERSION
from aeropulse_intelligence.source_evidence import method_version, score_class
from aeropulse_regions import RegionCatalog

from aeropulse_ml.baselines import Baseline
from aeropulse_ml.models.base import FittedModel, Metrics

GROUP = "all"
NOT_PROMOTABLE = (
    "source likelihood is a heuristic with no gold label set; it is served as a "
    "ranked, uncalibrated heuristic and never promoted as a model"
)


class SourceLikelihoodPlugin:
    family: ModelFamily = "source_likelihood"
    feature_set = HAZARD_24H
    label = "hazard_24h_target"
    trained = False
    uses_calibration = False
    algorithm = "logistic of weighted evidence per hazard profile (settings, uncalibrated)"
    version_prefix = "evidence-weights"

    def __init__(self, catalog: RegionCatalog) -> None:
        self._catalog = catalog

    def fit(
        self, train: pd.DataFrame, calibration: pd.DataFrame | None, *, model_version: str
    ) -> FittedModel:
        regions = sorted(train["region_id"].unique()) if not train.empty else []
        profiles = {r: [p.key for p in self._catalog.hazards_for(r)] for r in regions}
        all_profiles = [p for r in regions for p in self._catalog.hazards_for(r)]
        return FittedModel(
            family=self.family,
            model_version=method_version(all_profiles),
            algorithm=self.algorithm,
            feature_names=self.feature_set.names,
            ml_feature_version=ML_FEATURE_VERSION,
            calibrated=False,
            payload={"profiles": profiles},
        )

    def predict(self, model: FittedModel, frame: pd.DataFrame) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        records = frame.to_dict("records")
        for record in records:
            scores: dict[str, object] = {}
            best: tuple[float, str] | None = None
            evidence = 0
            for profile in self._catalog.hazards_for(str(record["region_id"])):
                scored = score_class(profile, record)  # type: ignore[arg-type]
                if scored is None:
                    continue
                value = scored.score.score
                scores[f"score:{profile.source_class}"] = value
                evidence += len(scored.score.contributing_signals)
                if best is None or value > best[0]:
                    best = (value, profile.source_class)
            scores["top_class"] = best[1] if best else None
            scores["top_score"] = best[0] if best else np.nan
            scores["signals_used"] = float(evidence)
            rows.append(scores)
        return pd.DataFrame(rows, index=frame.index)

    def baselines(self) -> list[Baseline]:
        return []

    def evaluate(
        self,
        model: FittedModel,
        test: pd.DataFrame,
        prediction: pd.DataFrame,
        baselines: Mapping[str, np.ndarray],
    ) -> Metrics:
        if prediction.empty:
            return {}
        block: dict[str, float | None] = {
            "rows": float(len(prediction)),
            "no_evidence_share": round(float((prediction["signals_used"] == 0).mean()), 6),
        }
        top = prediction["top_class"].dropna()
        for cls, share in top.value_counts(normalize=True).sort_index().items():
            block[f"top_share:{cls}"] = round(float(share), 6)
        return {GROUP: {"heuristic": block}}

    def gate(self, strategies: Mapping[str, StrategyResult]) -> list[str]:
        return [NOT_PROMOTABLE]

    def region_calibrated(
        self, model: FittedModel, strategies: Mapping[str, StrategyResult]
    ) -> bool:
        return False
