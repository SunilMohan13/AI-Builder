"""Lagrangian ensemble plume (APAC LLD 8.8)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import h3
import numpy as np
import pytest
from aeropulse_contracts import (
    FireCluster,
    Location,
    MeteoForecast,
    MeteorologicalObservation,
    Provenance,
    ProvenanceClass,
    Quality,
)
from aeropulse_contracts.plume import Plume, PlumeOrigin, PlumeSummary
from aeropulse_intelligence.geometry import haversine_km
from aeropulse_intelligence.plume import (
    MODEL_VERSION,
    EnsembleSettings,
    Place,
    PlumeInputError,
    PlumeInputs,
    PopulationIndex,
    WindField,
    WindUncertainty,
    forecast_wind,
    measure,
    observed_wind,
    simulate,
)
from aeropulse_intelligence.plume.stability import (
    NEUTRAL_CLASS,
    solar_elevation_deg,
    stability_class,
)
from aeropulse_intelligence.plume.uncertainty import UNMEASURED_REASON, LeadError
from aeropulse_intelligence.plume.wind import LevelWeights

T0 = datetime(2026, 10, 1, 6, tzinfo=UTC)
LAT, LON = 30.0, 76.0
DOMAIN = (60.0, 15.0, 95.0, 42.0)
DISPLAY = (74.0, 28.0, 78.0, 32.0)
NO_SPREAD = EnsembleSettings(diffusion_scale=0.0)
HOUR = 3600.0


def field(
    wind: Callable[[float], tuple[float, float]],
    *,
    hours: range = range(-60, 61),
    precip: float = 0.0,
    reasons: tuple[str, ...] = (),
) -> WindField:
    """A spatially uniform field over a 3x3 site grid; ``wind(hours_from_T0)``."""
    lats = np.array([25.0, 30.0, 35.0] * 3)
    lons = np.repeat([70.0, 76.0, 82.0], 3)
    times = np.array([T0.timestamp() + h * HOUR for h in hours])
    uv = np.array([wind(float(h)) for h in hours])
    shape = (len(times), lats.size)
    return WindField(
        site_lat=lats,
        site_lon=lons,
        times=times,
        u=np.repeat(uv[:, :1], lats.size, axis=1),
        v=np.repeat(uv[:, 1:], lats.size, axis=1),
        cloud=np.full(shape, np.nan),
        precip=np.full(shape, precip),
        reasons=reasons,
    )


def origin(lat: float = LAT, lon: float = LON, kind: str = "operator") -> PlumeOrigin:
    return PlumeOrigin(kind=kind, lat=lat, lon=lon)  # type: ignore[arg-type]


def run(
    wind: WindField,
    *,
    horizons: tuple[float, ...] = (1, 3, 6, 12),
    direction: str = "forward",
    at: PlumeOrigin | None = None,
    release: datetime = T0,
    settings: EnsembleSettings = NO_SPREAD,
    **inputs: object,
) -> Plume:
    return simulate(
        region_id="in-north",
        cycle_time=T0,
        direction=direction,  # type: ignore[arg-type]
        origin=at or origin(),
        horizons_hours=horizons,
        inputs=PlumeInputs(wind=wind, domain=DOMAIN, display=DISPLAY, **inputs),  # type: ignore[arg-type]
        settings=settings,
        release_time=release,
    )


def centre(plume: Plume, horizon: float) -> tuple[float, float]:
    h = next(h for h in plume.horizons if h.horizon_hours == horizon)
    assert h.centroid_lat is not None and h.centroid_lon is not None
    return h.centroid_lat, h.centroid_lon


# --- LLD 8.8 -------------------------------------------------------------


def test_uniform_wind_moves_speed_times_time_with_no_cap() -> None:
    plume = run(field(lambda _h: (10.0, 0.0)))
    lat, lon = centre(plume, 12)
    travelled = haversine_km(LAT, LON, lat, lon)
    assert travelled == pytest.approx(10.0 * 12 * 3.6, rel=0.01)  # 432 km, far past 37 km
    assert lat == pytest.approx(LAT, abs=0.05)
    assert lon > LON
    assert plume.model_version == MODEL_VERSION
    assert plume.provenance_class == "simulated" and plume.experimental


def test_wind_turning_ninety_degrees_bends_the_centreline() -> None:
    plume = run(field(lambda h: (5.0, 0.0) if h <= 6 else (0.0, 5.0)))
    lat6, lon6 = centre(plume, 6)
    lat12, lon12 = centre(plume, 12)
    assert lat6 == pytest.approx(LAT, abs=0.05)  # due east first
    east_km = haversine_km(LAT, LON, LAT, lon6)
    assert east_km == pytest.approx(5 * 6 * 3.6, rel=0.05)
    north_km = haversine_km(lat6, lon12, lat12, lon12)
    assert north_km == pytest.approx(5 * 6 * 3.6, rel=0.1)  # then north
    assert lon12 - lon6 < 0.15  # only the turning hour adds east motion


def test_zero_spread_collapses_footprints_to_the_centreline() -> None:
    plume = run(field(lambda _h: (6.0, 2.0)))
    for h in plume.horizons:
        assert h.p50_cells == h.p90_cells
        assert len(h.p90_cells) == 1
        assert h.centroid_lat is not None and h.centroid_lon is not None
        resolution = h3.get_resolution(h.p90_cells[0])
        assert h3.latlng_to_cell(h.centroid_lat, h.centroid_lon, resolution) == h.p90_cells[0]

    spread = run(field(lambda _h: (6.0, 2.0)), settings=EnsembleSettings())
    widest = max(spread.horizons, key=lambda h: h.horizon_hours)
    assert len(widest.p90_cells) > 1
    assert set(widest.p50_cells) <= set(widest.p90_cells)


@pytest.mark.parametrize("settings", [NO_SPREAD, EnsembleSettings()])
def test_backward_then_forward_returns_near_the_origin(settings: EnsembleSettings) -> None:
    wind = field(lambda _h: (7.0, -3.0))
    back = run(wind, direction="backward", horizons=(6,), settings=settings)
    blat, blon = centre(back, 6)
    assert haversine_km(LAT, LON, blat, blon) > 100
    forward = run(
        wind,
        horizons=(6,),
        at=origin(blat, blon),
        release=T0 - timedelta(hours=6),
        settings=settings,
    )
    flat, flon = centre(forward, 6)
    tolerance = 1.0 if settings.diffusion_scale == 0 else 15.0
    assert haversine_km(LAT, LON, flat, flon) < tolerance


def _forecast(valid: datetime, *, u: float = 4.0, v: float = 1.0, **extra: object) -> MeteoForecast:
    return MeteoForecast(
        forecast_id=f"fc_{valid:%d%H}",
        source_id="openmeteo",
        site_id="s1",
        issued_at=T0 - timedelta(hours=6),
        valid_at=valid,
        location=Location(lat=LAT, lon=LON),
        wind_u_10m=u,
        wind_v_10m=v,
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=Provenance(
            provider="test", connector_version="0", provenance_class=ProvenanceClass.MODEL_DERIVED
        ),
        region_id="in-north",
        **extra,  # type: ignore[arg-type]
    )


def test_missing_forecast_hours_set_the_degraded_reason() -> None:
    weights: LevelWeights = {"10m": 1.0}
    covered = [_forecast(T0 + timedelta(hours=h)) for h in range(0, 13)]
    full = forecast_wind(
        covered, as_of=T0, start=T0, end=T0 + timedelta(hours=12), level_weights=weights
    )
    assert full.reasons == ()

    short = forecast_wind(
        covered[:4], as_of=T0, start=T0, end=T0 + timedelta(hours=12), level_weights=weights
    )
    plume = run(short)
    assert plume.degraded
    assert any(r.startswith("persisted_wind_after_") for r in plume.degraded_reasons)

    gappy = forecast_wind(
        [f for i, f in enumerate(covered) if i not in (5, 6)],
        as_of=T0,
        start=T0,
        end=T0 + timedelta(hours=12),
        level_weights=weights,
    )
    assert "wind_missing_hours_2" in gappy.reasons


def test_without_forecasts_the_last_observed_wind_is_persisted() -> None:
    weather = [_weather(T0 - timedelta(hours=h), 4.0, 0.0) for h in range(0, 3)]
    late = _weather(T0 + timedelta(hours=1), -50.0, 0.0)  # after as_of: never used
    wind = forecast_wind(
        [],
        as_of=T0,
        start=T0,
        end=T0 + timedelta(hours=6),
        level_weights={"10m": 1.0},
        observed=[*weather, late],
    )
    assert not wind.empty
    assert f"persisted_wind_after_{T0:%Y-%m-%dT%HZ}" in wind.reasons
    assert "observed_wind_10m_only" in wind.reasons
    plume = run(wind, horizons=(6,))
    lat, lon = centre(plume, 6)
    assert haversine_km(LAT, LON, lat, lon) == pytest.approx(4.0 * 6 * 3.6, rel=0.01)


def test_forecast_wind_takes_the_newest_issue_and_blends_levels() -> None:
    old = _forecast(T0 + timedelta(hours=1), u=1.0, wind_u_100m=3.0, wind_v_100m=1.0)
    new = old.model_copy(
        update={"issued_at": T0 - timedelta(hours=1), "wind_u_10m": 2.0, "forecast_id": "n"}
    )
    future = old.model_copy(update={"issued_at": T0 + timedelta(hours=1), "wind_u_10m": 99.0})
    wind = forecast_wind(
        [old, new, future],
        as_of=T0,
        start=T0,
        end=T0 + timedelta(hours=1),
        level_weights={"10m": 0.5, "100m": 0.5},
    )
    assert wind.issued_at == T0 - timedelta(hours=1)
    assert wind.u[0, 0] == pytest.approx(0.5 * 2.0 + 0.5 * 3.0)

    single = forecast_wind(
        [_forecast(T0 + timedelta(hours=1))],
        as_of=T0,
        start=T0,
        end=T0 + timedelta(hours=1),
        level_weights={"10m": 0.3, "100m": 0.7},
    )
    assert "no_100m_wind_10m_used" in single.reasons


def test_no_wind_raises() -> None:
    empty = forecast_wind(
        [], as_of=T0, start=T0, end=T0 + timedelta(hours=6), level_weights={"10m": 1.0}
    )
    assert empty.empty
    with pytest.raises(PlumeInputError):
        run(empty)


def test_exposure_is_zero_over_an_empty_population_raster() -> None:
    plume = run(
        field(lambda _h: (5.0, 0.0)),
        population=PopulationIndex.from_cells({}, source="worldpop", year=2020),
    )
    assert [e.population_p90 for e in plume.exposure] == [0.0] * len(plume.horizons)
    assert {e.population_source for e in plume.exposure} == {"worldpop"}

    unbuilt = run(field(lambda _h: (5.0, 0.0)))
    assert unbuilt.exposure == []


def test_exposure_counts_people_under_the_p90_footprint() -> None:
    plume = run(field(lambda _h: (5.0, 0.0)), horizons=(3,))
    cell = plume.horizons[0].p90_cells[0]
    far = h3.latlng_to_cell(10.0, 10.0, 8)
    coarse_parent = h3.cell_to_parent(cell, 5)
    population = PopulationIndex.from_cells(
        {cell: 1200.0, far: 9999.0, coarse_parent: 7.0**3 * 10},
        source="worldpop",
        year=2020,
    )
    exposed = run(field(lambda _h: (5.0, 0.0)), horizons=(3,), population=population)
    # The cell's own people plus its 1/7^3 area share of the resolution-5 cell.
    assert exposed.exposure[0].population_p90 == pytest.approx(1210.0)


def test_backward_runs_list_only_fires_inside_the_back_trajectory() -> None:
    def cluster(cid: str, lat: float, lon: float) -> FireCluster:
        return FireCluster(
            cluster_id=cid,
            lat=lat,
            lon=lon,
            detection_count=3,
            frp_total=40.0,
            first_seen=T0 - timedelta(hours=10),
            last_seen=T0 - timedelta(hours=8),
            parent_cell=h3.latlng_to_cell(lat, lon, 6),
        )

    upwind = cluster("upwind", LAT, LON - 1.0)  # ~96 km west: air came from there
    downwind = cluster("downwind", LAT, LON + 1.0)
    aside = cluster("aside", LAT + 1.5, LON - 1.0)
    plume = run(
        field(lambda _h: (5.0, 0.0)),
        direction="backward",
        horizons=(6, 12),
        fires=[upwind, downwind, aside],
        settings=EnsembleSettings(),
    )
    ids = [c.fire_cluster_id for c in plume.source_candidates]
    assert ids == ["upwind"]
    candidate = plume.source_candidates[0]
    assert candidate.particle_fraction > 0.2
    assert candidate.bearing_deg == pytest.approx(270.0, abs=2.0)
    assert candidate.distance_km == pytest.approx(96.3, rel=0.02)
    assert plume.arrivals == []


def test_arrivals_report_probability_and_median_eta() -> None:
    lat_e, lon_e = LAT, LON + (5 * 6 * 3.6) / (111.195 * np.cos(np.radians(LAT)))
    places = [
        Place("p_east", "East town", lat_e, lon_e, radius_km=10.0, population=50000.0),
        Place("p_north", "North town", LAT + 2.0, LON, radius_km=10.0),
    ]
    plume = run(field(lambda _h: (5.0, 0.0)), places=places)
    assert [a.place_id for a in plume.arrivals] == ["p_east"]
    arrival = plume.arrivals[0]
    assert arrival.probability == pytest.approx(1.0)
    assert arrival.eta_hours_median == pytest.approx(5.5, abs=0.6)  # 10 km radius before 6 h
    assert arrival.population == 50000.0


def test_rain_removes_weight_forward_only() -> None:
    wet = run(field(lambda _h: (5.0, 0.0), precip=2.0), horizons=(6,))
    dry = run(field(lambda _h: (5.0, 0.0)), horizons=(6,))
    assert wet.horizons[0].weight_remaining < 1.0
    assert wet.horizons[0].weight_remaining == pytest.approx(np.exp(-5.0e-5 * 6 * 3600), rel=1e-6)
    assert dry.horizons[0].weight_remaining == 1.0


def test_unmeasured_wind_uncertainty_is_degraded_and_measured_spreads_wider() -> None:
    wind = field(lambda _h: (6.0, 0.0))
    plain = run(wind, horizons=(12,))
    assert UNMEASURED_REASON in plain.degraded_reasons

    measured = WindUncertainty(
        by_lead=(LeadError(max_lead_hours=48, speed_sd=0.3, direction_sd_deg=25.0, pairs=500),),
        pair_days=10,
    )
    wide = run(wind, horizons=(12,), uncertainty=measured)
    assert UNMEASURED_REASON not in wide.degraded_reasons
    assert len(wide.horizons[0].p90_cells) > len(plain.horizons[0].p90_cells)
    assert wide.settings["wind_uncertainty"] == "measured"


def test_particles_leaving_the_wind_domain_are_reported() -> None:
    plume = simulate(
        region_id="in-north",
        cycle_time=T0,
        direction="forward",
        origin=origin(),
        horizons_hours=(12,),
        inputs=PlumeInputs(
            wind=field(lambda _h: (10.0, 0.0)), domain=(75.0, 29.0, 77.0, 31.0), display=DISPLAY
        ),
        settings=NO_SPREAD,
    )
    assert "left_wind_domain_100pct" in plume.degraded_reasons
    assert plume.horizons[0].p90_cells == []


def test_same_inputs_same_plume() -> None:
    wind = field(lambda h: (5.0, 0.2 * h))
    a = run(wind, settings=EnsembleSettings())
    b = run(wind, settings=EnsembleSettings())
    assert a.plume_id == b.plume_id and a.plume_id.startswith("plm_")
    assert a.model_dump() == b.model_dump()
    summary = PlumeSummary.from_plume(a)
    assert summary.max_horizon_hours == 12 and summary.experimental


# --- inputs --------------------------------------------------------------


def test_stability_classes_follow_the_pasquill_table() -> None:
    def cls(speed: float, elevation: float, cloud: float) -> float:
        return float(
            stability_class(np.array([speed]), np.array([elevation]), np.array([cloud]))[0]
        )

    assert cls(1.0, 70.0, 0.0) == 0.0  # A: light wind, strong sun
    assert cls(2.5, 45.0, 0.0) == 1.0  # B
    assert cls(2.5, 45.0, 60.0) == 2.0  # cloud lowers insolation one step: C
    assert cls(2.5, -10.0, 10.0) == 5.0  # F: clear night
    assert cls(4.0, -10.0, 60.0) == 3.0  # D: cloudy night
    assert cls(1.0, 70.0, 95.0) == NEUTRAL_CLASS  # heavy overcast
    assert cls(3.0, 50.0, float("nan")) == NEUTRAL_CLASS  # unknown cloud


def test_solar_elevation_is_high_at_local_noon_and_negative_at_midnight() -> None:
    noon = datetime(2026, 6, 21, 12, tzinfo=UTC).timestamp() - LON / 15 * 3600
    assert solar_elevation_deg(np.array([LAT]), np.array([LON]), noon)[0] == pytest.approx(
        90 - LAT + 23.44, abs=1.0
    )
    assert solar_elevation_deg(np.array([LAT]), np.array([LON]), noon + 12 * 3600)[0] < 0


def _weather(at: datetime, u: float, v: float) -> MeteorologicalObservation:
    return MeteorologicalObservation(
        observation_id=f"wx_{at:%m%d%H}",
        source_id="openmeteo",
        source_record_id=f"wx_{at:%m%d%H}",
        observed_at=at,
        received_at=at,
        location=Location(lat=LAT, lon=LON),
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=Provenance(provider="test", connector_version="0"),
        parameter="wind",
        wind_u=u,
        wind_v=v,
    )


def test_wind_uncertainty_needs_seven_days_of_pairs() -> None:
    def pairs(days: int) -> tuple[list[MeteoForecast], list[MeteorologicalObservation]]:
        fcs, wxs = [], []
        for i in range(days * 24):
            valid = T0 + timedelta(hours=i)
            fc = _forecast(valid, u=5.0, v=0.0).model_copy(
                update={"issued_at": valid - timedelta(hours=3), "forecast_id": f"f{i}"}
            )
            fcs.append(fc)
            wxs.append(_weather(valid, 5.0 + (1.0 if i % 2 else -1.0), 0.0))
        return fcs, wxs

    short = measure(*pairs(3))
    assert not short.measured and short.at_lead(3) == (0.0, 0.0)

    stats = measure(*pairs(8))
    assert stats.measured and stats.pair_days >= 7
    speed_sd, dir_sd = stats.at_lead(3)
    assert speed_sd == pytest.approx(0.2)  # +-1 m/s on 5 m/s
    assert dir_sd == pytest.approx(0.0)


def test_observed_wind_is_ten_metre_only_and_says_so() -> None:
    weather = [_weather(T0 - timedelta(hours=h), 3.0, 0.0) for h in range(0, 7)]
    wind = observed_wind(weather, start=T0 - timedelta(hours=6), end=T0)
    assert "observed_wind_10m_only" in wind.reasons
    assert not any(r.startswith("persisted") for r in wind.reasons)
    plume = run(wind, direction="backward", horizons=(6,))
    assert plume.degraded and "observed_wind_10m_only" in plume.degraded_reasons
    _, lon = centre(plume, 6)
    assert lon < LON
