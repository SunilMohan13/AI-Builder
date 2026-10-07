"""Model or rule output -> served contracts, with version and provenance.

Shared by the model path and the rule path, so both obey the same rules:
concentrations are never negative, quantiles never cross, a missing value is
``None`` (never 0), and every record carries the served version, whether it
is degraded and why. A hazard score is a probability only when the served
entry is calibrated.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from aeropulse_contracts import (
    AnomalyFlag,
    CellForecast,
    HazardState,
    ProvenanceClass,
    SourceLikelihoodV2,
)
from aeropulse_intelligence.source_evidence import rank_sources
from aeropulse_regions import HazardProfile

from aeropulse_ml.models.anomaly import MIN_SPREAD_UGM3

if TYPE_CHECKING:
    from aeropulse_ml.serving.resolver import Served

ROUND = 2


def forecast_states(
    frame: pd.DataFrame, prediction: pd.DataFrame, served: Served
) -> list[CellForecast]:
    out: list[CellForecast] = []
    for idx, row in frame.iterrows():
        values = [_number(prediction.at[idx, c]) for c in ("p10", "p50", "p90")]
        if all(v is None for v in values):
            continue
        p10, p50, p90 = _ordered(values)
        horizon = int(row["horizon_hours"])
        t = _utc(row["t"])
        out.append(
            CellForecast(
                grid_id=str(row["cell"]),
                horizon_hours=horizon,
                valid_at=t + pd.Timedelta(hours=horizon).to_pytimedelta(),
                p10=p10,
                p50=p50,
                p90=p90,
                model_version=served.model_version,
                feature_version=served.feature_version,
                degraded=served.degraded,
                degraded_reason=served.degraded_reason,
                provenance_class=ProvenanceClass.PREDICTED,
            )
        )
    return out


def hazard_states(
    frame: pd.DataFrame, prediction: pd.DataFrame, served: Served
) -> list[HazardState]:
    out: list[HazardState] = []
    for idx, row in frame.iterrows():
        score = _number(prediction.at[idx, "score"], digits=4)
        threshold = _number(row.get("region_threshold_ugm3"))
        if score is None or threshold is None:
            continue
        out.append(
            HazardState(
                grid_id=str(row["cell"]),
                score=min(1.0, max(0.0, score)),
                calibrated=served.calibrated,
                threshold_ugm3=threshold,
                model_version=served.model_version,
                feature_version=served.feature_version,
                degraded=served.degraded,
                degraded_reason=served.degraded_reason,
                provenance_class=ProvenanceClass.PREDICTED,
            )
        )
    return out


def anomaly_flags(
    frame: pd.DataFrame, prediction: pd.DataFrame, served: Served
) -> list[AnomalyFlag]:
    """Only flagged rows. ``score`` is how far past the expected high, capped at 1."""
    out: list[AnomalyFlag] = []
    for idx, row in frame.iterrows():
        if _number(prediction.at[idx, "is_anomaly"]) != 1.0:
            continue
        pm25 = _number(row.get("pm25"))
        high = _number(prediction.at[idx, "p90"])
        if pm25 is None or high is None:
            continue
        mid = _number(prediction.at[idx, "p50"])
        spread = max((high - mid) if mid is not None else high, MIN_SPREAD_UGM3)
        basis = str(prediction.at[idx, "basis"])
        out.append(
            AnomalyFlag(
                grid_id=str(row["cell"]),
                observed_at=_utc(row["t"]),
                observed_pm25=pm25,
                expected_low=_number(prediction.at[idx, "p10"]),
                expected_high=high,
                score=round(min(1.0, max(0.0, (pm25 - high) / spread)), 4),
                reason=f"PM2.5 {pm25:g} at or above expected high {high:g} ({basis})",
                method_version=served.model_version,
                degraded=served.degraded,
                degraded_reason=served.degraded_reason,
                provenance_class=ProvenanceClass.PREDICTED,
            )
        )
    return out


def source_likelihoods(
    frame: pd.DataFrame, profiles: Sequence[HazardProfile], *, region_id: str
) -> list[SourceLikelihoodV2]:
    out: list[SourceLikelihoodV2] = []
    for _, row in frame.iterrows():
        values = {k: _number(v, digits=None) for k, v in row.items() if _numeric(v)}
        t = _utc(row["t"])
        out.append(
            rank_sources(
                profiles, values, region_id=region_id, grid_id=str(row["cell"]), valid_at=t
            )
        )
    return out


def _ordered(values: list[float | None]) -> tuple[float | None, float | None, float | None]:
    present = sorted(max(0.0, v) for v in values if v is not None)
    it = iter(present)
    p10, p50, p90 = (next(it) if v is not None else None for v in values)
    return p10, p50, p90


def _number(value: Any, digits: int | None = ROUND) -> float | None:
    if value is None or not _numeric(value):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return round(number, digits) if digits is not None else number


def _numeric(value: Any) -> bool:
    return isinstance(value, int | float | np.integer | np.floating) and not isinstance(value, bool)


def _utc(value: Any) -> datetime:
    stamp = pd.Timestamp(value)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    return stamp.to_pydatetime()
