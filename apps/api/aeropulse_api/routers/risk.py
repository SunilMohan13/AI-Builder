"""Exposure/risk query (LLD section 18.5)."""

import json
from pathlib import Path

from aeropulse_auth.jwt import TokenClaims
from aeropulse_intelligence.risk import risk_band, score_risk
from fastapi import APIRouter, Depends, Query

from aeropulse_api.deps import get_claims

router = APIRouter(prefix="/api/v1/risk", tags=["risk"])


def _population_fixture() -> dict:
    """Load the provider-neutral population contract used by local E2E."""
    for root in (Path("/app"), Path(".")):
        path = root / "fixtures" / "population" / "density.json"
        if path.exists():
            return json.loads(path.read_text())
    return {"cells": [], "provider": "unavailable"}


@router.get("")
def get_risk(
    pm25: float = Query(..., ge=0),
    exposure_hours: float = Query(6.0, ge=0),
    lat: float | None = Query(None, ge=-90, le=90),
    lon: float | None = Query(None, ge=-180, le=180),
    population_density: float | None = Query(None, ge=0),
    _claims: TokenClaims = Depends(get_claims),
) -> dict:
    """Return pollution_severity vs population_risk for a location.

    Supplying ``lat``/``lon`` resolves population density from the reference
    layer. Without them the response still answers, using the documented
    fallback, and reports ``population_measured: false`` so the caller can
    tell an exposure estimate from an exposure assumption.
    """
    return score_risk(
        pm25,
        exposure_duration_hours=exposure_hours,
        population_density_per_km2=population_density,
        lat=lat,
        lon=lon,
    ).model_dump(mode="json")


@router.get("/areas")
def get_risk_areas(
    pm25: float = Query(180.0, ge=0),
    exposure_hours: float = Query(6.0, ge=0),
    _claims: TokenClaims = Depends(get_claims),
) -> dict:
    """Score each population cell with provider and provenance metadata."""
    population = _population_fixture()
    areas = []
    for cell in population.get("cells", []):
        # The fixture supplies a real density for the cell, so it is passed
        # explicitly rather than looked up from lat/lon: an explicit value
        # always wins, and `population_measured` comes back true.
        result = score_risk(
            pm25,
            exposure_duration_hours=exposure_hours,
            population_density_per_km2=float(cell["density_per_km2"]),
        )
        areas.append(
            {
                "cell_id": cell["cell_id"],
                "name": cell["name"],
                "lat": cell["lat"],
                "lon": cell["lon"],
                "population": cell["population"],
                "population_density": cell["density_per_km2"],
                "risk": risk_band(result.population_risk),
                "population_risk": result.population_risk,
                "pollution_severity": result.pollution_severity,
            }
        )
    areas.sort(key=lambda area: area["population_risk"], reverse=True)
    for rank, area in enumerate(areas, start=1):
        area["rank"] = rank
    return {
        "items": areas,
        "total": len(areas),
        "risk_bands": {
            "note": (
                "Presentation thresholds over a bounded composite index, not a validated "
                "risk classification. The index range depends on the exposure window, so "
                "these are calibrated for the endpoint's default."
            ),
            "severe": 0.10,
            "high": 0.05,
            "medium": 0.02,
        },
        "population_source": {
            "provider": population.get("provider"),
            "provider_version": population.get("provider_version"),
            "license": population.get("license"),
            "source_uri": population.get("source_uri"),
        },
    }
