"""Score one region's serving frame with the model or rule the resolver chose.

Each function returns the records and the ``Served`` that actually answered:
if a served model fails at run time, the rule answers this cycle and the
returned ``Served`` says so (``degraded=true`` with the failure as reason).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

import numpy as np
import pandas as pd
from aeropulse_common.errors import TrainingError
from aeropulse_contracts import AnomalyFlag, CellForecast, HazardState, SourceLikelihoodV2
from aeropulse_observability import get_logger
from aeropulse_regions import RegionCatalog

from aeropulse_ml import postprocess
from aeropulse_ml.serving.resolver import Served
from aeropulse_ml.serving.rules import RULE_VERSIONS, anomaly_rule, forecast_rule, hazard_rule

log = get_logger(__name__)

Rule = Callable[[pd.DataFrame], pd.DataFrame]


def serve_forecasts(served: Served, frame: pd.DataFrame) -> tuple[list[CellForecast], Served]:
    prediction, used = _predict(served, frame, forecast_rule)
    return postprocess.forecast_states(frame, prediction, used), used


def serve_hazard(served: Served, frame: pd.DataFrame) -> tuple[list[HazardState], Served]:
    prediction, used = _predict(served, frame, hazard_rule)
    return postprocess.hazard_states(frame, prediction, used), used


def serve_anomalies(
    served: Served,
    frame: pd.DataFrame,
    prior_forecasts: Sequence[CellForecast] = (),
) -> tuple[list[AnomalyFlag], Served]:
    """``prior_forecasts`` are earlier cycles' forecasts; their P90 for this hour wins."""
    scored = _with_prior_forecast(frame, prior_forecasts) if served.uses_model else frame
    prediction, used = _predict(served, scored, anomaly_rule)
    return postprocess.anomaly_flags(scored, prediction, used), used


def serve_source_likelihood(
    catalog: RegionCatalog, region_id: str, frame: pd.DataFrame
) -> list[SourceLikelihoodV2]:
    return postprocess.source_likelihoods(
        frame, catalog.hazards_for(region_id), region_id=region_id
    )


def _predict(served: Served, frame: pd.DataFrame, rule: Rule) -> tuple[pd.DataFrame, Served]:
    if served.plugin is None or served.model is None or frame.empty:
        return rule(frame), served
    try:
        return served.plugin.predict(served.model, frame), served
    except (TrainingError, ValueError, KeyError) as exc:
        log.error(
            "served_model_failed",
            family=served.family,
            region_id=served.region_id,
            model_version=served.model_version,
            error=str(exc),
        )
        fallback = replace(
            served,
            model_version=RULE_VERSIONS[served.family],
            feature_version=None,
            degraded=True,
            degraded_reason=f"model {served.model_version} failed at serving: {exc}",
            calibrated=False,
            plugin=None,
            model=None,
        )
        return rule(frame), fallback


def _with_prior_forecast(frame: pd.DataFrame, forecasts: Sequence[CellForecast]) -> pd.DataFrame:
    """Attach the shortest-lead, model-served forecast whose valid hour is the row's hour."""
    usable = [f for f in forecasts if not f.degraded and f.p90 is not None]
    if not usable or frame.empty:
        return frame
    table = pd.DataFrame(
        {
            "cell": [f.grid_id for f in usable],
            "t": pd.to_datetime([f.valid_at for f in usable], utc=True),
            "lead": [f.horizon_hours for f in usable],
            "forecast_p10": [np.nan if f.p10 is None else f.p10 for f in usable],
            "forecast_p50": [np.nan if f.p50 is None else f.p50 for f in usable],
            "forecast_p90": [f.p90 for f in usable],
        }
    )
    table = table.sort_values("lead").drop_duplicates(["cell", "t"]).drop(columns="lead")
    keys = frame[["cell", "t"]].copy()
    keys["t"] = pd.to_datetime(keys["t"], utc=True)
    merged = keys.merge(table, on=["cell", "t"], how="left")
    merged.index = frame.index
    out = frame.copy()
    for name in ("forecast_p10", "forecast_p50", "forecast_p90"):
        out[name] = merged[name]
    return out
