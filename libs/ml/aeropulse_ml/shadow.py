"""Shadow serving: score challengers against live traffic without serving them.

The MLOps design records ``SHADOW`` and ``CANARY`` as promotion stages but
nothing routed traffic to a challenger, which made the middle of the lifecycle
decorative: a model could only move from "never exercised on production data"
to "answering the public". This module is the missing step.

Two rules govern everything here.

**The champion's answer is never affected.** A challenger runs after the
deterministic baseline has already produced the served result, and every
failure mode — missing artifact, contract mismatch, corrupt pickle, an
exception inside ``predict`` — is caught and recorded as a failed shadow row
rather than propagated. If this module raised, it would convert a healthy
system into an outage in exchange for a metric.

**A shadow row must be comparable after the fact.** Each row carries the
champion value, the challenger value, and a hash of the exact feature vector
both saw, so champion and challenger can be compared on identical inputs
weeks later without re-deriving features whose upstream data has since
changed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import joblib
import pandas as pd
from aeropulse_contracts.feature import GridFeature
from aeropulse_contracts.feature_spec import FEATURE_SETS, ML_FEATURE_VERSION, to_feature_dict

from aeropulse_ml.inference import (
    FEATURE_SET_BY_MODEL,
    LoadedModel,
    ModelBundleCache,
    feature_completeness,
    predict_hazard_24h,
    predict_peak_24h,
    predict_pm25,
    validate_feature_contract,
)
from aeropulse_ml.registry import ModelRecord, ModelRegistry, ModelStage

#: Stages whose models are scored in shadow. CANARY is included because a
#: canary is still being evaluated; only PRODUCTION answers a request.
SHADOW_STAGES = (ModelStage.SHADOW, ModelStage.CANARY)

#: Prediction entry points by family. A family absent here has no shadow
#: implementation yet and is skipped rather than guessed at.
_PREDICTORS = {
    "pm25_estimator": predict_pm25,
    "pm25_peak_24h": predict_peak_24h,
    "pm25_hazard_24h": predict_hazard_24h,
}

#: Field read from each family's payload as the headline scalar, so a
#: comparison report does not have to special-case every model's schema.
_VALUE_KEYS = {
    "pm25_estimator": "pm25_estimate",
    "pm25_peak_24h": "peak_pm25",
    "pm25_hazard_24h": "hazard_score",
}


def feature_vector_hash(feature: GridFeature) -> str:
    """Return a stable hash of every derivable input for one grid-hour.

    Args:
        feature: Canonical grid-hour feature record.

    Returns:
        Short hex digest over the sorted feature mapping. Two rows with the
        same digest were computed from identical inputs.
    """
    flat = to_feature_dict(feature)
    payload = json.dumps(
        {k: flat[k] for k in sorted(flat)}, sort_keys=True, default=str, allow_nan=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ShadowPrediction:
    """One challenger's output for one grid-hour, alongside the champion's.

    Attributes:
        timestamp: Feature timestamp.
        grid_id: H3 cell.
        model_name: Challenger family.
        model_version: Challenger version.
        stage: Challenger stage at scoring time.
        shadow_value: Headline scalar the challenger produced, or None when it
            declined or failed.
        champion_value: What actually served, for row-by-row comparison.
        feature_hash: Hash of the vector both saw.
        feature_completeness: Fraction of the challenger's inputs populated.
        error: Why the challenger produced nothing, when it did not.
        payload: The challenger's full response, kept for later analysis.
    """

    timestamp: datetime
    grid_id: str
    model_name: str
    model_version: str
    stage: str
    shadow_value: float | None
    champion_value: float | None
    feature_hash: str
    feature_completeness: float
    error: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class ShadowScorer:
    """Scores every registered challenger against the live feature stream.

    Args:
        registry: Registry to resolve challengers from.
        stages: Stages treated as challengers.
    """

    def __init__(
        self,
        registry: ModelRegistry,
        *,
        stages: tuple[ModelStage, ...] = SHADOW_STAGES,
    ) -> None:
        self.registry = registry
        self.stages = stages
        self._cache = ModelBundleCache(registry)
        self._bundles: dict[str, tuple[LoadedModel, ModelStage]] = {}
        self.load_errors: dict[str, str] = {}
        self.warmed = False

    def warm(self) -> dict[str, str]:
        """Load every challenger artifact up front.

        Cold loading measured 1.3 s against 0.69 ms warm, so doing this lazily
        would put a two-orders-of-magnitude latency spike on whichever
        snapshot happened to arrive first. Called once at worker start.

        Returns:
            Model family to the reason it could not be loaded, empty when all
            challengers loaded or none are registered.
        """
        self._bundles.clear()
        self.load_errors.clear()
        for family in FEATURE_SETS:
            if family not in _PREDICTORS:
                continue
            record = None
            stage_found = None
            for stage in self.stages:
                candidates = self.registry.stage_models(family, stage)
                if candidates:
                    record, stage_found = candidates[0], stage
                    break
            if record is None or stage_found is None:
                continue
            try:
                bundle = self._load(record, family)
            except Exception as exc:  # a bad artifact must never stop the worker
                self.load_errors[family] = f"{type(exc).__name__}: {exc}"
                continue
            self._bundles[family] = (LoadedModel(record=record, bundle=bundle), stage_found)
        self.warmed = True
        return dict(self.load_errors)

    def _load(self, record: ModelRecord, family: str) -> dict[str, Any]:
        """Load and contract-check one challenger artifact.

        Args:
            record: Registry record naming the artifact.
            family: Model family, used to select the expected feature set.

        Returns:
            The deserialised bundle.

        Raises:
            Exception: Any load or validation failure, caught by the caller.
        """
        path = self.registry.artifact_path(record)
        # joblib is pickle-based and executes code from its payload. Safe here
        # for exactly one reason: AEROPULSE_MODEL_DIR is deployment-controlled
        # and written only by this package's training runs. Shadow serving does
        # not widen that boundary — it reads the same controlled root, never a
        # user-supplied path. See the trust-boundary note in inference.py.
        bundle = joblib.load(path)
        validate_feature_contract(family, bundle)
        return bundle

    @property
    def challengers(self) -> dict[str, str]:
        """Return the loaded challengers as family to version."""
        return {family: loaded.record.version for family, (loaded, _) in self._bundles.items()}

    def score(
        self,
        feature: GridFeature,
        *,
        champion_values: dict[str, float | None] | None = None,
    ) -> list[ShadowPrediction]:
        """Score every loaded challenger for one grid-hour.

        Never raises. A challenger that fails produces a row carrying the
        failure, which is itself the signal an operator needs: a challenger
        that silently produced nothing for a month is not evidence of anything.

        Args:
            feature: Canonical grid-hour feature record.
            champion_values: What the served path produced for each family, so
                the two are recorded on the same row.

        Returns:
            One prediction per loaded challenger, possibly empty.
        """
        if not self._bundles:
            return []
        champions = champion_values or {}
        row = pd.Series(
            {
                **to_feature_dict(feature),
                "grid_id": feature.grid_id,
                "timestamp": feature.timestamp,
            }
        )
        digest = feature_vector_hash(feature)

        results: list[ShadowPrediction] = []
        for family, (loaded, stage) in self._bundles.items():
            completeness = feature_completeness(row, FEATURE_SET_BY_MODEL[family])
            value: float | None = None
            error: str | None = None
            payload: dict[str, Any] = {}
            try:
                payload = _PREDICTORS[family](row, _PinnedCache(self._cache, family, loaded))
                if payload.get("available"):
                    raw = payload.get(_VALUE_KEYS[family])
                    value = float(raw) if raw is not None else None
                else:
                    error = str(payload.get("reason", "declined"))
            except Exception as exc:  # failure isolation is the whole point
                error = f"{type(exc).__name__}: {exc}"

            results.append(
                ShadowPrediction(
                    timestamp=feature.timestamp,
                    grid_id=feature.grid_id,
                    model_name=family,
                    model_version=loaded.record.version,
                    stage=stage.value,
                    shadow_value=value,
                    champion_value=champions.get(family),
                    feature_hash=digest,
                    feature_completeness=float(completeness["ratio"]),
                    error=error,
                    payload=payload,
                )
            )
        return results


class _PinnedCache:
    """Adapter presenting one preloaded challenger through the cache interface.

    The predictors in :mod:`aeropulse_ml.inference` resolve their model via
    ``cache.get(name)``, which returns the *champion*. Shadow scoring needs the
    same prediction code pointed at a challenger instead, and duplicating each
    predictor to take a bundle directly would be two implementations of one
    calculation — exactly the divergence this codebase keeps eliminating.

    Args:
        parent: Cache supplying errors for any other family.
        family: Family this adapter overrides.
        loaded: Challenger to return for that family.
    """

    def __init__(self, parent: ModelBundleCache, family: str, loaded: LoadedModel) -> None:
        self._parent = parent
        self._family = family
        self._loaded = loaded

    @property
    def load_errors(self) -> dict[str, str]:
        """Return the parent cache's recorded load failures."""
        return self._parent.load_errors

    def get(self, model_name: str) -> LoadedModel | None:
        """Return the pinned challenger, or defer to the parent cache."""
        if model_name == self._family:
            return self._loaded
        return self._parent.get(model_name)


def comparison_report(predictions: list[ShadowPrediction]) -> dict[str, Any]:
    """Summarise accumulated shadow rows, per challenger.

    Args:
        predictions: Shadow rows to summarise.

    Returns:
        Per-family counts, error rate, and mean absolute difference from the
        champion where both values exist. The difference measures *divergence
        from the incumbent*, not accuracy: neither side is ground truth, so a
        large gap says the two disagree, not which one is right.
    """
    report: dict[str, Any] = {"ml_feature_version": ML_FEATURE_VERSION, "models": {}}
    by_family: dict[str, list[ShadowPrediction]] = {}
    for prediction in predictions:
        by_family.setdefault(prediction.model_name, []).append(prediction)

    for family, rows in sorted(by_family.items()):
        scored = [r for r in rows if r.shadow_value is not None]
        paired = [r for r in scored if r.champion_value is not None]
        diffs = [abs(r.shadow_value - r.champion_value) for r in paired]  # type: ignore[operator]
        report["models"][family] = {
            "rows": len(rows),
            "scored": len(scored),
            "failed": len(rows) - len(scored),
            "error_rate": round((len(rows) - len(scored)) / len(rows), 4) if rows else 0.0,
            "versions": sorted({r.model_version for r in rows}),
            "paired_with_champion": len(paired),
            "mean_abs_diff_vs_champion": round(sum(diffs) / len(diffs), 4) if diffs else None,
            "mean_feature_completeness": (
                round(sum(r.feature_completeness for r in rows) / len(rows), 4) if rows else 0.0
            ),
            "first_error": next((r.error for r in rows if r.error), None),
        }
    report["generated_at"] = datetime.now(UTC).isoformat()
    return report
