"""Filesystem-backed model registry with an explicit promotion lifecycle.

Implements the LLD §19 metadata set and stage machine without taking on MLflow
as a dependency. The interface is deliberately the shape MLflow exposes
(register, list, transition, resolve champion) so that swapping the backend
later does not touch calling code:

    TRAINING -> VALIDATION -> SHADOW -> CANARY -> PRODUCTION -> RETIRED

``artifact_uri`` is a local path today and an ``s3://`` key once MinIO
credentials are configured; callers must treat it as opaque.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

REGISTRY_DIRNAME = "models"
INDEX_FILENAME = "index.json"


class ModelStage(StrEnum):
    """Promotion stages from LLD §19."""

    TRAINING = "TRAINING"
    VALIDATION = "VALIDATION"
    SHADOW = "SHADOW"
    CANARY = "CANARY"
    PRODUCTION = "PRODUCTION"
    RETIRED = "RETIRED"


#: Legal stage transitions. Promotion must be gradual: a freshly trained model
#: cannot jump straight to PRODUCTION, which is what makes SHADOW/CANARY
#: meaningful rather than decorative.
ALLOWED_TRANSITIONS: dict[ModelStage, frozenset[ModelStage]] = {
    ModelStage.TRAINING: frozenset({ModelStage.VALIDATION, ModelStage.RETIRED}),
    ModelStage.VALIDATION: frozenset({ModelStage.SHADOW, ModelStage.RETIRED}),
    ModelStage.SHADOW: frozenset({ModelStage.CANARY, ModelStage.RETIRED}),
    ModelStage.CANARY: frozenset({ModelStage.PRODUCTION, ModelStage.RETIRED}),
    ModelStage.PRODUCTION: frozenset({ModelStage.RETIRED}),
    ModelStage.RETIRED: frozenset(),
}


class PromotionError(RuntimeError):
    """Raised when a stage transition is not permitted."""


def code_commit() -> str:
    """Return the current git commit, or ``unknown`` outside a checkout.

    Recorded on every artifact so a prediction can be traced to the code that
    produced it (LLD §5.3).

    Returns:
        Short commit sha, or ``unknown``.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


class ModelRecord(BaseModel):
    """Registry metadata for one trained model version (LLD §19)."""

    model_config = {"extra": "forbid"}

    model_id: str
    model_name: str
    version: str
    stage: ModelStage = ModelStage.TRAINING
    algorithm: str = ""
    feature_version: str = ""
    ml_feature_version: str = ""
    feature_names: list[str] = Field(default_factory=list)
    training_dataset_version: str = ""
    dataset: dict[str, Any] = Field(default_factory=dict)
    code_commit: str = ""
    training_time: datetime | None = None
    geography: str = "punjab-haryana-delhi-ncr"
    season: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifact_uri: str = ""
    notes: str = ""

    # --- Fields the notebook bundle schema already carried and the production
    # one did not. The convergence extends this record rather than flattening
    # the richer artifact, so nothing a research run measured is discarded on
    # the way into the registry.
    #: Hash of the training frame. Two records with the same fingerprint were
    #: fitted on identical data, which is what makes a rerun verifiable.
    dataset_fingerprint: str = ""
    #: Probability calibration applied, e.g. ``isotonic``, ``sigmoid``,
    #: ``beta`` or ``none``. ``none`` on a classifier means its scores rank
    #: but are not probabilities.
    calibration: str = ""
    #: Estimator hyperparameters and target construction, for reproduction.
    regression_config: dict[str, Any] = Field(default_factory=dict)
    #: Lead time this model is built for, in hours. ``None`` for nowcasts.
    primary_horizon_h: int | None = None
    #: Why this record is not serving, when it is not. Populated from the
    #: promotion gate so a reader never has to guess whether a VALIDATION
    #: record was blocked or merely not yet considered.
    gate_failures: list[str] = Field(default_factory=list)


class ModelRegistry:
    """Append-only registry of model versions rooted at a directory.

    Args:
        root: Directory holding artifacts and the index. Defaults to
            ``$AEROPULSE_MODEL_DIR`` or ``./models``.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or os.environ.get("AEROPULSE_MODEL_DIR", REGISTRY_DIRNAME))
        self.index_path = self.root / INDEX_FILENAME

    def _load(self) -> list[ModelRecord]:
        if not self.index_path.exists():
            return []
        raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        return [ModelRecord.model_validate(item) for item in raw.get("models", [])]

    def _save(self, records: list[ModelRecord]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now(UTC).isoformat(),
            "models": [json.loads(r.model_dump_json()) for r in records],
        }
        self.index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def list_models(self, *, model_name: str | None = None) -> list[ModelRecord]:
        """Return registered models, newest first.

        Args:
            model_name: Restrict to one model family.

        Returns:
            Matching records.
        """
        records = self._load()
        if model_name:
            records = [r for r in records if r.model_name == model_name]
        return sorted(
            records,
            key=lambda r: r.training_time or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )

    def get(self, model_id: str) -> ModelRecord | None:
        """Return one record by id, or None."""
        for record in self._load():
            if record.model_id == model_id:
                return record
        return None

    def register(self, record: ModelRecord) -> ModelRecord:
        """Add or replace a model version.

        Args:
            record: Metadata to store.

        Returns:
            The stored record.
        """
        records = [r for r in self._load() if r.model_id != record.model_id]
        records.append(record)
        self._save(records)
        return record

    def transition(self, model_id: str, stage: ModelStage, *, force: bool = False) -> ModelRecord:
        """Move a model to a new stage, enforcing the lifecycle.

        Promoting to PRODUCTION retires the incumbent champion of the same
        family, so exactly one production model exists per family at any time.

        Args:
            model_id: Model to transition.
            stage: Target stage.
            force: Bypass the transition table. Intended for rollback drills.

        Returns:
            The updated record.

        Raises:
            KeyError: If the model is unknown.
            PromotionError: If the transition is not allowed.
        """
        records = self._load()
        by_id = {r.model_id: r for r in records}
        record = by_id.get(model_id)
        if record is None:
            raise KeyError(f"unknown model_id {model_id!r}")
        if not force and stage not in ALLOWED_TRANSITIONS[record.stage]:
            allowed = sorted(ALLOWED_TRANSITIONS[record.stage])
            raise PromotionError(
                f"cannot move {model_id!r} from {record.stage} to {stage}; allowed: {allowed}"
            )
        if stage is ModelStage.PRODUCTION:
            for other in records:
                if (
                    other.model_name == record.model_name
                    and other.model_id != model_id
                    and other.stage is ModelStage.PRODUCTION
                ):
                    other.stage = ModelStage.RETIRED
        record.stage = stage
        self._save(records)
        return record

    def promote_to_production(self, model_id: str) -> ModelRecord:
        """Walk a model through the full lifecycle to PRODUCTION.

        Convenience for automated retraining where shadow and canary evaluation
        are performed in one batch run rather than over days of traffic. The
        intermediate stages are still recorded.

        Args:
            model_id: Model to promote.

        Returns:
            The updated record.
        """
        path = [
            ModelStage.VALIDATION,
            ModelStage.SHADOW,
            ModelStage.CANARY,
            ModelStage.PRODUCTION,
        ]
        record = self.get(model_id)
        if record is None:
            raise KeyError(f"unknown model_id {model_id!r}")
        for stage in path:
            if record.stage is ModelStage.PRODUCTION:
                break
            if stage in ALLOWED_TRANSITIONS[record.stage]:
                record = self.transition(model_id, stage)
        return record

    def champion(self, model_name: str) -> ModelRecord | None:
        """Return the loadable PRODUCTION model for a family, if any.

        Records with no ``artifact_uri`` are skipped. Since the deterministic
        baselines were registered as real records they sit at PRODUCTION —
        correctly, because they are what serves — but their behaviour lives in
        ``libs/intelligence`` rather than in a pickle. Returning one here would
        hand the bundle loader a record with nothing to load and turn a clean
        "no trained champion, use the baseline" into a spurious load error.

        Args:
            model_name: Model family, e.g. ``pm25_estimator``.

        Returns:
            The champion record, or None when no trained model is promoted.
            Callers must treat None as "fall back to the deterministic
            baseline" rather than as an error (LLD §40).
        """
        for record in self.list_models(model_name=model_name):
            if record.stage is ModelStage.PRODUCTION and record.artifact_uri:
                return record
        return None

    def stage_models(self, model_name: str, stage: ModelStage) -> list[ModelRecord]:
        """Return a family's loadable records at one stage, newest first.

        Used by the shadow path to find challengers. Artifact-less records are
        excluded for the same reason as in :meth:`champion`.

        Args:
            model_name: Model family.
            stage: Stage to filter on.

        Returns:
            Matching records with a resolvable artifact.
        """
        return [
            record
            for record in self.list_models(model_name=model_name)
            if record.stage is stage and record.artifact_uri
        ]

    def artifact_path(self, record: ModelRecord) -> Path:
        """Resolve a record's artifact to a local path.

        Args:
            record: Registry record.

        Returns:
            Path to the serialised artifact.
        """
        uri = record.artifact_uri
        if uri.startswith("s3://"):
            # Object-store retrieval is a later phase; the local mirror is
            # authoritative in the current runtime.
            return self.root / Path(uri).name
        path = Path(uri)
        return path if path.is_absolute() else self.root / path.name
