"""Contracts frozen on day 1 of the APAC migration (LLD APAC 15.1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from aeropulse_contracts import (
    CitizenReportDocument,
    FieldStatus,
    Location,
    MeteoForecast,
    Plume,
    PlumeHorizon,
    PlumeOrigin,
    PlumeSummary,
    Provenance,
    ProvenanceClass,
    Quality,
    RegionSnapshot,
    SourceLikelihoodV2,
    VisualObservation,
)
from aeropulse_contracts.provenance import NON_MEASURED_CLASSES
from pydantic import ValidationError

T0 = datetime(2026, 10, 1, 6, tzinfo=UTC)


def _quality() -> Quality:
    return Quality(quality_score=1.0)


def _provenance() -> Provenance:
    return Provenance(
        provider="open-meteo",
        connector_version="test",
        provenance_class=ProvenanceClass.MODEL_DERIVED,
    )


def test_provenance_classes_are_the_lld_set() -> None:
    assert {c.value for c in ProvenanceClass} == {
        "measured",
        "model_derived",
        "predicted",
        "simulated",
        "heuristic",
        "ai_observation",
        "citizen",
    }
    assert ProvenanceClass.MEASURED not in NON_MEASURED_CLASSES


def test_meteo_forecast_requires_issued_before_valid() -> None:
    common = {
        "forecast_id": "f1",
        "source_id": "openmeteo",
        "region_id": "sg-singapore",
        "site_id": "s1",
        "location": Location(lat=1.3, lon=103.8),
        "quality": _quality(),
        "provenance": _provenance(),
        "dedup_key": "k",
    }
    ok = MeteoForecast(issued_at=T0, valid_at=T0 + timedelta(hours=6), **common)
    assert ok.lead_hours == 6.0
    with pytest.raises(ValidationError):
        MeteoForecast(issued_at=T0, valid_at=T0 - timedelta(hours=1), **common)


def test_source_likelihood_v2_cannot_claim_calibration() -> None:
    payload = {
        "region_id": "in-north",
        "grid_id": "8828308281fffff",
        "valid_at": T0,
        "method_version": "heuristic-1",
        "ranking": [],
        "evidence": [],
    }
    SourceLikelihoodV2.model_validate(payload)
    with pytest.raises(ValidationError):
        SourceLikelihoodV2.model_validate({**payload, "calibrated": True})
    with pytest.raises(ValidationError):
        SourceLikelihoodV2.model_validate({**payload, "provenance_class": "measured"})


def test_plume_is_always_simulated_and_summarises() -> None:
    plume = Plume(
        plume_id="p1",
        region_id="sg-singapore",
        cycle_time=T0,
        model_version="lagrangian-ens-1.0",
        direction="forward",
        origin=PlumeOrigin(kind="fire_cluster", ref_id="c1", lat=1.0, lon=102.0),
        release_time=T0,
        horizons=[
            PlumeHorizon(
                horizon_hours=1, p50_cells=["a"], p90_cells=["a", "b"], weight_remaining=1
            ),
            PlumeHorizon(
                horizon_hours=6, p50_cells=["c"], p90_cells=["c", "d"], weight_remaining=0.9
            ),
        ],
    )
    summary = PlumeSummary.from_plume(plume)
    assert summary.max_horizon_hours == 6
    assert summary.p90_cells_at_max == ["c", "d"]
    assert summary.provenance_class == "simulated"
    assert summary.experimental is True
    with pytest.raises(ValidationError):
        Plume.model_validate({**plume.model_dump(), "provenance_class": "measured"})


def test_visual_observation_has_no_numeric_fields() -> None:
    numeric = {
        name
        for name, field in VisualObservation.model_fields.items()
        if field.annotation in (int, float, int | None, float | None)
    }
    assert numeric == set()
    obs = VisualObservation(
        visual_class="smoke_plume",
        visual_certainty="medium",
        likely_source_type="agricultural_field",
        image_quality="good",
        scene_summary="Grey smoke rising over a field.",
        observer_version="gemini-observer-1",
    )
    assert obs.provenance_class == "ai_observation"


def test_citizen_document_defaults_to_awaiting_media() -> None:
    doc = CitizenReportDocument(
        report_id="r1",
        region_id="in-north",
        reporter_hash="h",
        claimed_lat=30.0,
        claimed_lon=76.0,
        created_at=T0,
    )
    assert doc.status == "awaiting_media"
    assert doc.analysis is None


def test_region_snapshot_mode_cannot_be_demo() -> None:
    base = {
        "region_id": "in-north",
        "cycle_time": T0,
        "cycle_id": "c1",
        "pack_version": "1",
        "generated_at": T0,
        "field_status": [FieldStatus(field="hazard", reason="no model").model_dump()],
    }
    snap = RegionSnapshot.model_validate({**base, "mode": "live"})
    assert snap.schema_version == "region_snapshot.v1"
    with pytest.raises(ValidationError):
        RegionSnapshot.model_validate({**base, "mode": "demo"})


def test_region_snapshot_round_trips_json() -> None:
    snap = RegionSnapshot(
        region_id="au-nsw",
        cycle_time=T0,
        cycle_id="c1",
        pack_version="1",
        mode="backfill",
        generated_at=T0,
    )
    assert RegionSnapshot.model_validate_json(snap.model_dump_json()) == snap
