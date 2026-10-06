"""Exposure/risk scoring tests (LLD §18.5, gap analysis P1-4).

The point of the population layer is that severity and risk stop being the
same number scaled. These tests pin that, and pin the honesty flag that tells
a caller when the density behind a risk score was assumed rather than looked
up.
"""

from aeropulse_geospatial.population import (
    FALLBACK_DENSITY_PER_KM2,
    MAX_MATCH_KM,
    population_density,
)
from aeropulse_intelligence.risk import score_risk


def test_severity_and_risk_separated() -> None:
    result = score_risk(150.0, exposure_duration_hours=6.0, population_density_per_km2=8000.0)
    assert 0 < result.pollution_severity < 1
    assert 0 <= result.population_risk <= 1
    assert result.formula_version == "risk-0.2"


def test_identical_pollution_gives_different_risk_by_location() -> None:
    """The whole reason the exposure layer exists.

    With one hardcoded density, dense Delhi and sparse Karnal produced
    identical risk for identical PM2.5, which made ``population_risk`` a
    restatement of ``pollution_severity``.
    """
    delhi = score_risk(250.0, lat=28.72, lon=77.15)
    karnal = score_risk(250.0, lat=29.69, lon=76.99)

    assert delhi.pollution_severity == karnal.pollution_severity
    assert delhi.population_risk > karnal.population_risk
    assert delhi.population_measured and karnal.population_measured


def test_points_outside_the_reference_coverage_report_unmeasured() -> None:
    """The coverage limit is asserted, not hidden.

    The shared fixture covers five Delhi-to-Karnal cells, so Punjab falls
    outside it. The right behaviour is an explicit `population_measured:
    false`, never a nearest-neighbour stretched 200 km across the corridor.
    Replacing the fixture with a licensed extract is what closes this, and
    this test is what will notice when it does.
    """
    bathinda = score_risk(250.0, lat=30.2110, lon=74.9455)

    assert bathinda.population_measured is False
    assert bathinda.population_source == "fallback"


def test_a_looked_up_density_is_flagged_as_measured() -> None:
    """A caller must be able to tell an estimate from an assumption."""
    result = score_risk(120.0, lat=28.6139, lon=77.2090)

    assert result.population_measured is True
    assert result.population_source != "fallback"
    assert result.population_reference is not None
    assert result.population_density != FALLBACK_DENSITY_PER_KM2


def test_scoring_without_a_location_falls_back_and_says_so() -> None:
    """The endpoint still answers, but never pretends the density is real."""
    result = score_risk(120.0)

    assert result.population_measured is False
    assert result.population_source == "fallback"
    assert result.population_density == FALLBACK_DENSITY_PER_KM2


def test_an_explicit_density_overrides_the_lookup() -> None:
    """A caller who supplies a real number must not have it discarded."""
    result = score_risk(120.0, lat=28.6139, lon=77.2090, population_density_per_km2=250.0)

    assert result.population_density == 250.0
    assert result.population_measured is True
    assert result.population_source == "caller-supplied"


def test_a_point_far_outside_the_corridor_is_unmatched() -> None:
    """Nearest-neighbour must not stretch a district value across India."""
    # Mid Bay of Bengal: no reference point is anywhere near.
    estimate = population_density(15.0, 88.0)

    assert estimate.measured is False
    assert estimate.source == "fallback"
    assert estimate.density_per_km2 == FALLBACK_DENSITY_PER_KM2


def test_a_matched_point_reports_its_reference_and_distance() -> None:
    """Provenance, so a surprising density can be traced to its source."""
    estimate = population_density(28.62, 77.21)

    assert estimate.measured is True
    assert estimate.reference_name is not None
    assert estimate.distance_km is not None
    assert estimate.distance_km <= MAX_MATCH_KM


def test_risk_stays_bounded_at_extremes() -> None:
    """The score is a [0, 1] index and must not exceed it in dense areas."""
    extreme = score_risk(
        900.0,
        exposure_duration_hours=48.0,
        lat=28.6800,
        lon=77.2700,
        confidence=1.0,
    )

    assert 0.0 <= extreme.pollution_severity <= 1.0
    assert 0.0 <= extreme.population_risk <= 1.0


def test_the_reference_dataset_actually_ships() -> None:
    """Catch the "present locally, not in the repo" failure directly.

    A missing fixture makes every lookup fall back to a constant density,
    which is the defect this layer was added to remove — and it would fail
    silently, because every other test here still passes on a machine where
    the file happens to exist.
    """
    from aeropulse_geospatial import population as population_module

    path = population_module._resolve_path()
    assert path is not None and path.is_file(), (
        "fixtures/population/density.json was not found; the population layer "
        "would fall back to a constant for every cell"
    )

    points, source = population_module._reference_points()
    assert len(points) >= 5, "population layer is present but suspiciously sparse"
    assert source != "unavailable"


def test_one_population_source_backs_both_endpoints() -> None:
    """The lat/lon lookup and `/risk/areas` must not disagree.

    Two population datasets previously coexisted and reported different
    densities for the same city (Ghaziabad: 3,971 vs 9,800 per km2). Two
    endpoints contradicting each other is worse than either being coarse.
    """
    import json

    from aeropulse_geospatial import population as population_module

    path = population_module._resolve_path()
    assert path is not None
    fixture = json.loads(path.read_text(encoding="utf-8"))

    for cell in fixture["cells"]:
        estimate = population_density(cell["lat"], cell["lon"])
        assert estimate.measured, f"{cell['name']} is in the fixture but not resolvable"
        assert estimate.density_per_km2 == cell["density_per_km2"], (
            f"{cell['name']} disagrees between the lookup and the fixture"
        )
