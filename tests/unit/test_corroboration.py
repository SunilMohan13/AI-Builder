"""Deterministic corroboration and the decision table (LLD APAC 9.5, 9.6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import h3
import pytest
from aeropulse_contracts.citizen import CitizenReportDocument, GeoTrust
from aeropulse_contracts.snapshot import FireCluster, WindVector
from aeropulse_intelligence.corroboration import (
    Environment,
    ReportPoint,
    corroborate,
    decide,
    plume_origin,
    seeded_origin,
    watch_summary,
)
from aeropulse_regions import load_citizen_settings
from aeropulse_regions.citizen import CitizenSettings

T = datetime(2026, 9, 8, 6, tzinfo=UTC)
#: Reporter in Punjab; the fire is about 15 km due east.
REPORTER = (30.10, 75.55)
FIRE = FireCluster(
    cluster_id="fire-east",
    lat=30.10,
    lon=75.71,
    detection_count=3,
    frp_total=40.0,
    first_seen=T - timedelta(hours=1),
    last_seen=T - timedelta(hours=1),
    parent_cell=h3.latlng_to_cell(30.10, 75.71, 6),
)
#: Wind from the east (u < 0 blows toward the west), so the fire is upwind.
EASTERLY = WindVector(site_id="s", lat=30.1, lon=75.6, valid_at=T, u=-4.0, v=0.0)


@pytest.fixture(scope="module")
def settings() -> CitizenSettings:
    return load_citizen_settings(Path("config"))


def _point(direction: float | None = None) -> ReportPoint:
    return ReportPoint(
        lat=REPORTER[0],
        lon=REPORTER[1],
        reference_time=T,
        reference_is_capture=True,
        img_direction_deg=direction,
    )


def _geo(level: str = "trusted") -> GeoTrust:
    return GeoTrust(level=level, score=0.9, components={}, region_id="in-north")  # type: ignore[arg-type]


def test_haze_with_no_signals_is_uncorroborated_and_seeds_nothing(
    settings: CitizenSettings,
) -> None:
    result = corroborate(_point(), "haze", Environment(), settings.corroboration)
    assert result.level == "uncorroborated" and result.score == 0.0
    assert all(s.supports is not True for s in result.signals)
    assert result.provenance_class == "heuristic"
    assert decide(visual_class="haze", geo=_geo(), corroboration=result) == "stored_operators_only"


def test_unknown_signals_are_neutral_not_negative(settings: CitizenSettings) -> None:
    result = corroborate(_point(), "smoke_plume", Environment(), settings.corroboration)
    bearing = next(s for s in result.signals if s.signal == "fire_on_bearing")
    aerosol = next(s for s in result.signals if s.signal == "aerosol_index_elevated")
    assert bearing.supports is None, "no camera bearing: cannot be checked"
    assert aerosol.supports is None, "no aerosol reading: cannot be checked"


def test_smoke_with_a_fire_on_the_bearing_seeds_at_the_hotspot(
    settings: CitizenSettings,
) -> None:
    env = Environment(fires=[FIRE], wind=[EASTERLY])
    result = corroborate(_point(direction=90.0), "smoke_plume", env, settings.corroboration)
    supporting = {s.signal for s in result.signals if s.supports}
    assert {"fire_nearby", "fire_on_bearing", "fire_upwind"} <= supporting
    assert result.level == "corroborated" and result.matched_fire_id == "fire-east"
    assert decide(visual_class="smoke_plume", geo=_geo(), corroboration=result) == "seed_plume"

    origin = plume_origin(
        "rep1",
        _point(direction=90.0),
        result,
        [FIRE],
        reporter_spread_km=settings.decision.reporter_origin_spread_km,
    )
    assert (origin.kind, origin.ref_id) == ("citizen_report", "rep1")
    assert (origin.lat, origin.lon) == (FIRE.lat, FIRE.lon), "starts at the hotspot"


def test_without_a_bearing_the_plume_starts_at_the_reporter_with_spread(
    settings: CitizenSettings,
) -> None:
    env = Environment(fires=[FIRE], wind=[EASTERLY])
    result = corroborate(_point(), "smoke_plume", env, settings.corroboration)
    origin = plume_origin("rep2", _point(), result, [FIRE], reporter_spread_km=3.0)
    assert (origin.lat, origin.lon) == REPORTER and origin.initial_spread_km == 3.0


def test_a_fire_behind_the_camera_is_not_on_the_bearing(settings: CitizenSettings) -> None:
    env = Environment(fires=[FIRE])
    result = corroborate(_point(direction=270.0), "smoke_plume", env, settings.corroboration)
    bearing = next(s for s in result.signals if s.signal == "fire_on_bearing")
    assert bearing.supports is False


def test_an_old_fire_is_outside_the_window(settings: CitizenSettings) -> None:
    stale = FIRE.model_copy(
        update={"first_seen": T - timedelta(days=2), "last_seen": T - timedelta(days=2)}
    )
    result = corroborate(
        _point(direction=90.0), "smoke_plume", Environment(fires=[stale]), settings.corroboration
    )
    assert result.matched_fire_id is None and result.level == "uncorroborated"


@pytest.mark.parametrize(
    ("visual_class", "geo", "level", "decision"),
    [
        ("smoke_plume", "untrusted", "corroborated", "operator_queue"),
        (None, "trusted", "corroborated", "operator_queue"),
        ("fog_or_cloud", "trusted", "corroborated", "no_smoke_observed"),
        ("smoke_plume", "trusted", "uncorroborated", "stored_operators_only"),
        ("smoke_plume", "usable", "corroborated", "operator_queue"),
        ("smoke_plume", "trusted", "partial", "operator_queue"),
        ("smoke_plume", "trusted", "corroborated", "seed_plume"),
    ],
)
def test_decision_table(
    visual_class: str | None, geo: str, level: str, decision: str, settings: CitizenSettings
) -> None:
    env = Environment(fires=[FIRE], wind=[EASTERLY])
    result = corroborate(_point(direction=90.0), "smoke_plume", env, settings.corroboration)
    result = result.model_copy(update={"level": level})
    assert decide(visual_class=visual_class, geo=_geo(geo), corroboration=result) == decision


def test_an_untrusted_report_never_seeds_whatever_the_evidence(
    settings: CitizenSettings,
) -> None:
    env = Environment(fires=[FIRE], wind=[EASTERLY])
    result = corroborate(_point(direction=90.0), "flames", env, settings.corroboration)
    assert result.level == "corroborated"
    assert decide(visual_class="flames", geo=_geo("untrusted"), corroboration=result) != (
        "seed_plume"
    )


def test_stored_analysis_rebuilds_the_origin_and_public_summary(
    settings: CitizenSettings,
) -> None:
    env = Environment(fires=[FIRE], wind=[EASTERLY])
    result = corroborate(_point(direction=90.0), "smoke_plume", env, settings.corroboration)
    doc = CitizenReportDocument.model_validate(
        {
            "report_id": "rep3",
            "region_id": "in-north",
            "reporter_hash": "h",
            "claimed_lat": 30.10432,
            "claimed_lon": 75.55219,
            "created_at": T,
            "analysis": {
                "geo_trust": _geo().model_dump(),
                "corroboration": result.model_dump(),
                "decision": "seed_plume",
                "observation": {
                    "visual_class": "smoke_plume",
                    "visual_certainty": "high",
                    "likely_source_type": "agricultural_field",
                    "image_quality": "good",
                    "scene_summary": "Smoke over a field.",
                    "observer_version": "stub",
                },
            },
        }
    )
    origin = seeded_origin(doc, [FIRE], reporter_spread_km=3.0)
    assert origin is not None and (origin.lat, origin.lon) == (FIRE.lat, FIRE.lon)
    summary = watch_summary(doc, round_decimals=2, plume_id="plm_x")
    assert summary is not None
    assert (summary.lat_rounded, summary.lon_rounded) == (30.1, 75.55)
    assert summary.provenance_class == "ai_observation"
    moderated = doc.model_copy(update={"moderated_class": "haze"})
    summary = watch_summary(moderated, round_decimals=2, plume_id=None)
    assert summary is not None
    assert summary.visual_class == "haze" and summary.provenance_class == "citizen"
