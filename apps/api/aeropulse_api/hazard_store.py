"""Hazard and peak forecast serving (integration plan Phase 6).

The governing rule from the plan: **a shadow model's output is never returned
as a served prediction**. Until a hazard or peak model is promoted to
PRODUCTION, these routes answer from a deterministic rule and say so via
``degraded=True`` and a ``persistence-*`` ``model_version``. A challenger
being scored in shadow changes nothing a caller sees.

The deterministic rule is persistence: the concentration observed now, carried
forward. That is a weak forecast and is labelled as one — but it is an honest
weak forecast rather than a fabricated strong one, and at a 24-hour horizon
"it is already bad" genuinely is the baseline any model has to beat.

Reads come from persisted ``grid_feature`` rows, so the API never triggers
inference synchronously and never calls an external provider, both of which
the plan states as hard constraints.
"""

from __future__ import annotations

from typing import Any

from aeropulse_contracts.feature import GridFeature
from aeropulse_contracts.hazard import (
    HAZARD_BASELINE_VERSION,
    HAZARD_THRESHOLD_UGM3,
    PEAK_BASELINE_VERSION,
    HazardCell,
    PeakForecast,
)

#: Forward window both models answer for.
DEFAULT_HORIZON_HOURS = 24

#: Concentration at which the deterministic rule reports full hazard. Below
#: the threshold the score falls off linearly to zero, so the baseline is a
#: usable ranking rather than a step function that is 0 or 1 and nothing else.
_BASELINE_FLOOR_UGM3 = 30.0


def baseline_hazard(feature: GridFeature) -> HazardCell | None:
    """Score hazard for one cell from its current concentration alone.

    Args:
        feature: Persisted grid-hour feature row.

    Returns:
        A hazard cell marked ``degraded``, or None when the cell has no
        observed PM2.5 and therefore nothing to reason from. Returning None
        rather than a zero matters: "no data" and "no hazard" are different
        answers and a map must not render them identically.
    """
    if feature.pm25 is None:
        return None
    span = HAZARD_THRESHOLD_UGM3 - _BASELINE_FLOOR_UGM3
    score = (feature.pm25 - _BASELINE_FLOOR_UGM3) / span if span > 0 else 0.0
    return HazardCell(
        grid_id=feature.grid_id,
        timestamp=feature.timestamp,
        center_lat=feature.center_lat,
        center_lon=feature.center_lon,
        hazard_score=round(max(0.0, min(1.0, score)), 4),
        horizon_hours=DEFAULT_HORIZON_HOURS,
        # A linear ramp over one observation is not a calibrated probability
        # and must never be rendered as a percentage.
        calibrated=False,
        degraded=True,
        model_version=HAZARD_BASELINE_VERSION,
        feature_version=feature.feature_version,
        observed_pm25=feature.pm25,
    )


def baseline_peak(feature: GridFeature) -> PeakForecast | None:
    """Carry the current concentration forward as the 24-hour peak.

    Args:
        feature: Persisted grid-hour feature row.

    Returns:
        A peak forecast marked ``degraded``, or None when PM2.5 is unobserved.
    """
    if feature.pm25 is None:
        return None
    # The trailing maximum is a better persistence baseline than the current
    # value for a *peak* target: a cell that hit 200 four hours ago is more
    # likely to do so again than its current 90 suggests.
    candidate = max(
        [v for v in (feature.pm25, feature.pm25_roll_max_24h) if v is not None],
        default=feature.pm25,
    )
    return PeakForecast(
        grid_id=feature.grid_id,
        timestamp=feature.timestamp,
        center_lat=feature.center_lat,
        center_lon=feature.center_lon,
        peak_pm25=round(candidate, 3),
        horizon_hours=DEFAULT_HORIZON_HOURS,
        exceeds_threshold=candidate >= HAZARD_THRESHOLD_UGM3,
        degraded=True,
        model_version=PEAK_BASELINE_VERSION,
        feature_version=feature.feature_version,
        observed_pm25=feature.pm25,
    )


def promoted_version(model_name: str) -> str | None:
    """Return the promoted champion version for a family, if any.

    Consulted so a response can state plainly whether a trained model exists.
    A registry that cannot be read is treated as "no champion" rather than as
    an error: the deterministic answer is still correct and serving it is
    better than failing the request.

    Args:
        model_name: Model family, e.g. ``pm25_hazard_24h``.

    Returns:
        The champion's version string, or None.
    """
    try:
        from aeropulse_ml.registry import ModelRegistry

        record = ModelRegistry().champion(model_name)
    except Exception:
        return None
    return record.version if record else None


def hazard_cells(features: list[GridFeature]) -> tuple[list[HazardCell], dict[str, Any]]:
    """Build the hazard layer for a set of cells.

    Args:
        features: Persisted grid-hour feature rows.

    Returns:
        ``(cells, provenance)``. The provenance block states which model
        answered and, when it was the baseline, why.
    """
    champion = promoted_version("pm25_hazard_24h")
    cells = [cell for cell in (baseline_hazard(f) for f in features) if cell is not None]
    return cells, _provenance("pm25_hazard_24h", champion, HAZARD_BASELINE_VERSION)


def peak_forecasts(features: list[GridFeature]) -> tuple[list[PeakForecast], dict[str, Any]]:
    """Build the peak forecast layer for a set of cells.

    Args:
        features: Persisted grid-hour feature rows.

    Returns:
        ``(forecasts, provenance)``.
    """
    champion = promoted_version("pm25_peak_24h")
    items = [item for item in (baseline_peak(f) for f in features) if item is not None]
    return items, _provenance("pm25_peak_24h", champion, PEAK_BASELINE_VERSION)


def _provenance(model_name: str, champion: str | None, baseline: str) -> dict[str, Any]:
    """Describe what produced a response, and what did not.

    Args:
        model_name: Model family the route would prefer to use.
        champion: Promoted version, if one exists.
        baseline: Version string of the deterministic fallback.

    Returns:
        Provenance fields for the response envelope.
    """
    if champion is None:
        return {
            "model_name": model_name,
            "model_version": baseline,
            "degraded": True,
            "reason": (
                f"no PRODUCTION {model_name} is registered; serving the deterministic "
                "baseline. A model being scored in shadow is deliberately not served."
            ),
        }
    # Reached only once a champion exists. The served values above are still
    # the deterministic ones, so this branch reports the discrepancy rather
    # than silently implying the champion produced them.
    return {
        "model_name": model_name,
        "model_version": baseline,
        "degraded": True,
        "promoted_champion": champion,
        "reason": (
            f"a PRODUCTION {model_name} ({champion}) is registered but this route still "
            "serves the deterministic baseline; worker-side materialisation of champion "
            "hazard/peak predictions is not implemented"
        ),
    }
