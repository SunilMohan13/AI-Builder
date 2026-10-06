"""Feature and prediction drift monitoring API (LLD §46)."""

from datetime import datetime

from aeropulse_auth.jwt import TokenClaims
from aeropulse_ml.drift import distribution_drift
from fastapi import APIRouter, Depends, HTTPException, Query

from aeropulse_api.deps import get_claims
from aeropulse_api.drift_store import DRIFT_SIGNALS, DriftReader, get_drift_reader

router = APIRouter(prefix="/api/v1/drift", tags=["drift"])


@router.get("")
def get_drift(
    reference_start: datetime,
    reference_end: datetime,
    current_start: datetime,
    current_end: datetime,
    _claims: TokenClaims = Depends(get_claims),
    reader: DriftReader = Depends(get_drift_reader),
    signal: str = Query(default="prediction.pm25_estimate"),
    grid_id: str | None = Query(default=None),
    model_version: str | None = Query(default=None),
    min_samples: int = Query(default=30, ge=10, le=1000),
    max_samples: int = Query(default=10000, ge=100, le=100000),
) -> dict:
    """Compare non-overlapping reference/current distributions using PSI and KS."""
    if signal not in DRIFT_SIGNALS:
        raise HTTPException(
            status_code=422,
            detail={"message": "Unsupported drift signal", "allowed": sorted(DRIFT_SIGNALS)},
        )
    if reference_start >= reference_end or current_start >= current_end:
        raise HTTPException(status_code=422, detail="Each drift window must have start < end")
    if reference_end > current_start:
        raise HTTPException(status_code=422, detail="Drift windows must not overlap")
    if model_version is not None and not signal.startswith("prediction."):
        raise HTTPException(
            status_code=422,
            detail="model_version only applies to prediction signals",
        )

    reference = reader.values(
        signal, reference_start, reference_end, grid_id, model_version, max_samples
    )
    current = reader.values(signal, current_start, current_end, grid_id, model_version, max_samples)
    result = distribution_drift(reference, current, min_samples=min_samples)
    return {
        "signal": signal,
        "reference_window": {
            "start": reference_start.isoformat(),
            "end": reference_end.isoformat(),
        },
        "current_window": {"start": current_start.isoformat(), "end": current_end.isoformat()},
        "scope": {"grid_id": grid_id, "model_version": model_version},
        "thresholds": {"psi_warning": 0.10, "psi_drift": 0.25, "ks_alpha": 0.05},
        **result,
        "limitations": [
            "Distribution drift does not prove model quality degradation.",
            "Error drift is unavailable until delayed ground-truth labels are persisted.",
        ],
    }
