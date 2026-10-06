"""Independent source likelihood scores (LLD §18.3). Not mutually exclusive."""

from __future__ import annotations

from aeropulse_contracts.feature import GridFeature, SourceLikelihood

LIKELIHOOD_VERSION = "source-likelihood-0.1"

# Honest priors while industrial/traffic inventories are absent.
INDUSTRIAL_PRIOR = 0.11
TRAFFIC_PRIOR = 0.04
DUST_PRIOR = 0.03


def score_sources(feature: GridFeature) -> SourceLikelihood:
    """Score biomass burning and regional transport from fire + wind + PM2.5.

    Industrial/traffic/dust stay as documented priors until those layers exist.
    Scores are independent and may sum to more than 1.0.
    """
    fire_intensity = _clip(feature.fire_frp / 120.0)
    fire_presence = 1.0 if feature.fire_count > 0 else 0.0
    biomass = _clip(0.55 * fire_presence + 0.30 * fire_intensity + 0.15 * feature.upwind_fire_score)

    transport = 0.0
    if feature.wind_speed is not None:
        transport = _clip((feature.wind_speed / 8.0) * 0.5)
        if feature.pm25 is not None and feature.pm25 >= 80:
            transport = _clip(transport + 0.25)
        if feature.upwind_fire_score > 0.4:
            transport = _clip(transport + 0.35 * feature.upwind_fire_score)

    return SourceLikelihood(
        biomass_burning=round(biomass, 4),
        industrial=INDUSTRIAL_PRIOR,
        traffic=TRAFFIC_PRIOR,
        dust=DUST_PRIOR,
        regional_transport=round(transport, 4),
    )


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))
