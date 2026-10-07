"""One plume run, forward or backward, as a ``plume.v1`` (APAC LLD 8).

Deterministic physics, no language model. The id and the random stream both
derive from the run's inputs, so the same cycle reproduces the same plume.
Every plume is ``simulated`` and experimental until the Section 8.7
evaluation exists; anything the inputs could not support is a degraded reason.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from aeropulse_contracts import FireCluster
from aeropulse_contracts.plume import HorizonExposure, Plume, PlumeDirection, PlumeOrigin

from aeropulse_intelligence.plume.ensemble import Domain, EnsembleSettings, run_ensemble
from aeropulse_intelligence.plume.outputs import (
    INNER_RESOLUTION,
    OUTER_RESOLUTION,
    Place,
    PopulationIndex,
    exposed_population,
    horizon_footprint,
    place_arrivals,
    source_candidates,
)
from aeropulse_intelligence.plume.uncertainty import UNMEASURED_REASON, WindUncertainty
from aeropulse_intelligence.plume.wind import LevelWeights, WindField

MODEL_VERSION = "lagrangian-ens-1.0"
#: Footprint and arrival maths, cited in ``stability.py``.
DIFFUSION_METHOD = "briggs-rural-1973/pasquill-turner-1970"


class PlumeInputError(ValueError):
    """The inputs cannot support any plume (no wind at all)."""


@dataclass(frozen=True)
class PlumeInputs:
    """Everything a run reads besides its origin."""

    wind: WindField
    domain: Domain
    display: Domain
    uncertainty: WindUncertainty | None = None
    population: PopulationIndex | None = None
    places: Sequence[Place] = ()
    fires: Sequence[FireCluster] = ()
    level_weights: LevelWeights = field(default_factory=dict)


def plume_id(
    region_id: str, cycle_time: datetime, direction: PlumeDirection, origin: PlumeOrigin
) -> str:
    """Keyed by what is simulated, not by ``ref_id``: a re-run overwrites its own plume."""
    key = "|".join(
        [
            region_id,
            cycle_time.isoformat(),
            direction,
            origin.kind,
            f"{origin.lat:.4f}",
            f"{origin.lon:.4f}",
            f"{origin.initial_spread_km:.3f}",
        ]
    )
    return "plm_" + hashlib.sha256(key.encode()).hexdigest()[:20]


def simulate(
    *,
    region_id: str,
    cycle_time: datetime,
    direction: PlumeDirection,
    origin: PlumeOrigin,
    horizons_hours: Sequence[float],
    inputs: PlumeInputs,
    settings: EnsembleSettings | None = None,
    release_time: datetime | None = None,
) -> Plume:
    """Run the ensemble and summarise it per horizon."""
    if not horizons_hours:
        raise PlumeInputError("a plume needs at least one horizon")
    if inputs.wind.empty:
        raise PlumeInputError("no wind covers the plume window")
    cfg = settings or EnsembleSettings()
    release = release_time or cycle_time
    pid = plume_id(region_id, cycle_time, direction, origin)
    rng = np.random.default_rng(int(hashlib.sha256(pid.encode()).hexdigest()[:16], 16))
    backward = direction == "backward"
    horizons = sorted(float(h) for h in horizons_hours)

    reasons: list[str] = list(inputs.wind.reasons)
    uncertainty = None if backward else inputs.uncertainty
    if not backward and (uncertainty is None or not uncertainty.measured):
        reasons.append(UNMEASURED_REASON)

    run = run_ensemble(
        origin.lat,
        origin.lon,
        release.timestamp(),
        inputs.wind,
        max_hours=horizons[-1],
        backward=backward,
        domain=inputs.domain,
        settings=cfg,
        rng=rng,
        uncertainty=uncertainty,
        issued_epoch=inputs.wind.issued_at.timestamp() if inputs.wind.issued_at else None,
        initial_spread_km=origin.initial_spread_km,
    )
    left = 1.0 - float(run.active[-1].mean())
    if left > 0:
        reasons.append(f"left_wind_domain_{round(100 * left)}pct")

    footprints = [horizon_footprint(run, h, inputs.display) for h in horizons]
    exposure: list[HorizonExposure] = []
    if inputs.population is not None:
        exposure = [
            HorizonExposure(
                horizon_hours=f.horizon_hours,
                population_p90=round(exposed_population(f.p90_cells, inputs.population), 1),
                population_source=inputs.population.source,
                population_year=inputs.population.year,
            )
            for f in footprints
        ]

    weights = ",".join(f"{k}={v:g}" for k, v in sorted(inputs.level_weights.items()))
    recorded: dict[str, float | int | str] = {
        **cfg.as_dict(),
        "diffusion": DIFFUSION_METHOD,
        "inner_resolution": INNER_RESOLUTION,
        "outer_resolution": OUTER_RESOLUTION,
        "level_weights": weights or "none",
        "wind_uncertainty": "measured"
        if uncertainty is not None and uncertainty.measured
        else "none",
    }
    return Plume(
        plume_id=pid,
        region_id=region_id,
        cycle_time=cycle_time,
        model_version=MODEL_VERSION,
        direction=direction,
        origin=origin,
        release_time=release,
        wind_issued_at=inputs.wind.issued_at,
        horizons=footprints,
        arrivals=[] if backward else place_arrivals(run, inputs.places, horizons[-1]),
        exposure=exposure,
        source_candidates=(
            source_candidates(run, inputs.fires, origin.lat, origin.lon) if backward else []
        ),
        settings=recorded,
        degraded=bool(reasons),
        degraded_reasons=list(dict.fromkeys(reasons)),
    )


def wind_window(
    release: datetime, horizons_hours: Sequence[float], direction: PlumeDirection
) -> tuple[datetime, datetime]:
    """``(start, end)`` of wind a run needs."""
    span = timedelta(hours=max(horizons_hours))
    return (release - span, release) if direction == "backward" else (release, release + span)
