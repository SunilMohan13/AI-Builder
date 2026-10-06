"""The deterministic serving baselines, as real registry records.

Before this module there were two registries: a hardcoded Python list in
``aeropulse_intelligence.model_registry`` that ``GET /api/v1/models`` reported,
and the filesystem :class:`~aeropulse_ml.registry.ModelRegistry` that training
actually wrote to. The hardcoded list labelled all three baselines
``PRODUCTION`` unconditionally, which was true — they *are* what the worker
serves — but it could not report a real trained champion once one existed, and
it could not report a baseline being superseded.

One registry wins, and it is the filesystem one. The baselines are registered
into it as ordinary records so the endpoint tells the whole truth from a single
source: which baseline serves each family, whether a trained champion has
displaced it, and what was measured on anything that has not.

A baseline record carries no artifact. Its behaviour lives in code
(``libs/intelligence``), not in a pickle, so ``artifact_uri`` stays empty and
``runtime_role`` distinguishes it from a loadable model.
"""

from __future__ import annotations

from datetime import UTC, datetime

from aeropulse_intelligence.anomaly import ANOMALY_VERSION
from aeropulse_intelligence.estimator import ESTIMATOR_VERSION
from aeropulse_intelligence.forecast import FORECAST_MODEL
from aeropulse_intelligence.likelihood import LIKELIHOOD_VERSION

from aeropulse_ml.registry import ModelRecord, ModelRegistry, ModelStage

#: Marker written to ``ModelRecord.algorithm`` so a baseline is identifiable
#: without string-matching its version.
BASELINE_ALGORITHM_PREFIX = "deterministic:"

#: Registered at a fixed timestamp rather than "now": these are code, not
#: training runs, so a changing registration time would imply a retrain that
#: never happened.
_BASELINE_REGISTERED_AT = datetime(2026, 9, 1, tzinfo=UTC)

_BASELINES: tuple[tuple[str, str, str], ...] = (
    ("pm25_estimator", ESTIMATOR_VERSION, "inverse-distance-weighted interpolation"),
    ("anomaly_detector", ANOMALY_VERSION, "trailing-quantile threshold"),
    ("source_likelihood", LIKELIHOOD_VERSION, "fixed priors over fire/wind/pollutant evidence"),
    ("propagation_forecast", FORECAST_MODEL, "kinematic wind advection with dilution"),
)


def baseline_records() -> list[ModelRecord]:
    """Return the deterministic baselines as registry records.

    Returns:
        One record per model family the worker serves deterministically, each
        at :attr:`~aeropulse_ml.registry.ModelStage.PRODUCTION` because that is
        genuinely what answers a request today.
    """
    return [
        ModelRecord(
            model_id=version,
            model_name=family,
            version=version,
            stage=ModelStage.PRODUCTION,
            algorithm=f"{BASELINE_ALGORITHM_PREFIX} {description}",
            training_time=_BASELINE_REGISTERED_AT,
            notes=(
                "Deterministic baseline implemented in libs/intelligence. It has no "
                "trained artifact and no holdout metrics because it was not fitted to "
                "data; it is the fallback a trained champion must beat to replace."
            ),
        )
        for family, version, description in _BASELINES
    ]


def is_baseline(record: ModelRecord) -> bool:
    """Return True when a record describes a deterministic baseline.

    Args:
        record: Registry record.

    Returns:
        True for a code-implemented baseline, False for a trained artifact.
    """
    return record.algorithm.startswith(BASELINE_ALGORITHM_PREFIX)


def sync_baselines(registry: ModelRegistry) -> list[ModelRecord]:
    """Ensure every deterministic baseline is present in the registry.

    Idempotent: a baseline already registered is left untouched, so repeated
    calls from an API process cannot churn the index or reset a stage an
    operator set deliberately.

    A baseline is registered at PRODUCTION only when its family has no other
    production record. Where a trained champion has already been promoted the
    baseline is registered as RETIRED instead, because it genuinely has been
    superseded — writing it at PRODUCTION would put two champions in one
    family and break the invariant ``transition()`` exists to hold.

    Args:
        registry: Registry to populate.

    Returns:
        The records that were newly registered, empty when all were present.
    """
    existing_records = registry.list_models()
    existing_ids = {record.model_id for record in existing_records}
    families_with_champion = {
        record.model_name for record in existing_records if record.stage is ModelStage.PRODUCTION
    }

    added: list[ModelRecord] = []
    for record in baseline_records():
        if record.model_id in existing_ids:
            continue
        if record.model_name in families_with_champion:
            record = record.model_copy(
                update={
                    "stage": ModelStage.RETIRED,
                    "notes": (
                        record.notes + " Superseded: a trained champion is already promoted for "
                        "this family."
                    ),
                }
            )
        registry.register(record)
        added.append(record)
    return added
