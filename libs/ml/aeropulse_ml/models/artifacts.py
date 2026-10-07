"""Save and load fitted models.

Artifacts are joblib (pickle) files, so loading one runs code. ``load_model``
therefore checks the file's SHA-256 against the value pinned in the gate
report *before* unpickling, and the serving path always passes it.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

import joblib
from aeropulse_common.errors import ModelServingError

from aeropulse_ml.models.base import FittedModel

ARTIFACT_SCHEMA = "model_artifact.v1"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_model(model: FittedModel, path: Path) -> str:
    """Write ``model`` and return the artifact's SHA-256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"schema": ARTIFACT_SCHEMA, **asdict(model)}, path)
    return file_sha256(path)


def load_model(path: Path, *, expected_sha256: str | None) -> FittedModel:
    """Load an artifact whose hash matches ``expected_sha256``.

    ``expected_sha256=None`` is allowed only for local inspection of a file
    you produced; serving never passes ``None``.
    """
    if not path.is_file():
        raise ModelServingError(f"artifact not found: {path}")
    if expected_sha256 is not None:
        actual = file_sha256(path)
        if actual != expected_sha256:
            raise ModelServingError(
                f"artifact hash mismatch for {path.name}: gate report pins "
                f"{expected_sha256[:12]}..., file is {actual[:12]}..."
            )
    payload: dict[str, Any] = joblib.load(path)
    if payload.pop("schema", None) != ARTIFACT_SCHEMA:
        raise ModelServingError(f"{path.name} is not a {ARTIFACT_SCHEMA} artifact")
    payload["feature_names"] = tuple(payload["feature_names"])
    return FittedModel(**payload)
