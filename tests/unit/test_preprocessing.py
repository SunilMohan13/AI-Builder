"""Shared preprocessing: quality, region, leak rules, dedup, precedence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aeropulse_contracts import (
    FireObservation,
    Location,
    Measurement,
    MeteoForecast,
    Observation,
    Provenance,
    ProvenanceClass,
    Quality,
    RasterObservation,
)
from aeropulse_contracts.fire import FireProperties
from aeropulse_geospatial import to_grid_id
from aeropulse_ml.preprocessing import (
    AsOfCutoff,
    Deduplicate,
    LatestForecastIssue,
    PreprocessContext,
    PreprocessingPipeline,
    QualityControl,
    RecordBatch,
    RegionFilter,
    StationsOutrankModel,
    label_observations,
)
from aeropulse_regions import load_catalog

T = datetime(2026, 9, 8, 12, tzinfo=UTC)
LAT, LON = 28.61, 77.21
CTX = PreprocessContext(
    region_id="in-north",
    as_of=T,
    ground_truth_sources=frozenset({"openaq", "cpcb"}),
    model_derived_sources=frozenset({"openmeteo"}),
)


def _prov(cls: ProvenanceClass | None, provider: str = "test") -> Provenance:
    return Provenance(provider=provider, connector_version="0", provenance_class=cls)


def obs(
    rid: str,
    *,
    at: datetime = T - timedelta(hours=1),
    value: float = 80.0,
    source: str = "openaq",
    cls: ProvenanceClass | None = ProvenanceClass.MEASURED,
    region: str | None = "in-north",
    score: float = 1.0,
    lat: float = LAT,
    lon: float = LON,
    parameter: str = "pm25",
    dedup: str | None = None,
) -> Observation:
    return Observation(
        observation_id=f"obs_{rid}",
        source_id=source,
        source_record_id=rid,
        observed_at=at,
        received_at=at + timedelta(minutes=10),
        location=Location(lat=lat, lon=lon),
        measurement=Measurement(parameter=parameter, value=value, unit="ug/m3"),
        quality=Quality(quality_flag="valid", quality_score=score),
        provenance=_prov(cls),
        region_id=region,
        grid_id=to_grid_id(lat, lon),
        dedup_key=dedup,
    )


def forecast(
    *, issued: datetime, valid: datetime, site: str = "s1", region: str = "in-north"
) -> MeteoForecast:
    return MeteoForecast(
        forecast_id=f"fc_{site}_{issued:%H}_{valid:%H}",
        source_id="openmeteo",
        site_id=site,
        issued_at=issued,
        valid_at=valid,
        location=Location(lat=LAT, lon=LON),
        wind_u_10m=1.0,
        wind_v_10m=0.5,
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=_prov(ProvenanceClass.MODEL_DERIVED),
        region_id=region,
    )


def raster(*, processed: datetime, acquired: datetime | None = None) -> RasterObservation:
    acquired = acquired or processed - timedelta(hours=20)
    return RasterObservation(
        observation_id=f"ras_{processed:%d%H}",
        source_id="earthengine",
        source_record_id=f"s5p_{processed:%d%H}",
        product_id="s5p_aer_ai",
        acquisition_time=acquired,
        processing_time=processed,
        bbox=(LON, LAT, LON, LAT),
        resolution="h3r8",
        object_uri="",
        checksum="",
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=_prov(ProvenanceClass.MEASURED),
        region_id="in-north",
    )


def fire(rid: str, *, frp: float = 12.0, at: datetime = T - timedelta(hours=2)) -> FireObservation:
    return FireObservation(
        observation_id=f"fire_{rid}",
        source_id="firms",
        source_record_id=rid,
        observed_at=at,
        received_at=at + timedelta(hours=3),
        location=Location(lat=LAT, lon=LON),
        fire=FireProperties(frp=frp, confidence=0.8, sensor="VIIRS"),
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=_prov(ProvenanceClass.MEASURED),
        region_id="in-north",
    )


def ids(records: Any) -> list[str]:
    return [r.source_record_id for r in records]


# --- leak rules ------------------------------------------------------------


def test_nothing_observed_after_as_of_survives() -> None:
    batch = RecordBatch(observations=(obs("past"), obs("future", at=T + timedelta(minutes=1))))
    out, dropped = AsOfCutoff().apply(batch, CTX)
    assert ids(out.observations) == ["past"]
    assert dropped == {"leak:observed_after_as_of": 1}


def test_forecast_is_kept_when_issued_by_as_of_even_if_valid_later() -> None:
    kept = forecast(issued=T, valid=T + timedelta(hours=6))
    late = forecast(issued=T + timedelta(hours=1), valid=T + timedelta(hours=6), site="s2")
    out, dropped = AsOfCutoff().apply(RecordBatch(forecasts=(kept, late)), CTX)
    assert out.forecasts == (kept,)
    assert dropped == {"leak:forecast_issued_after_as_of": 1}


def test_daily_raster_counts_from_processing_not_acquisition() -> None:
    ready = raster(processed=T - timedelta(hours=1))
    not_ready = raster(processed=T + timedelta(hours=3), acquired=T - timedelta(hours=10))
    out, dropped = AsOfCutoff().apply(RecordBatch(rasters=(ready, not_ready)), CTX)
    assert out.rasters == (ready,)
    assert dropped == {"leak:raster_processed_after_as_of": 1}


def test_training_context_defers_the_cutoff_to_the_feature_pipeline() -> None:
    training = PreprocessContext(region_id=None, as_of=None)
    batch = RecordBatch(observations=(obs("future", at=T + timedelta(days=3)),))
    out, dropped = AsOfCutoff().apply(batch, training)
    assert out == batch
    assert not dropped


def test_latest_issue_wins_only_among_issues_known_at_as_of() -> None:
    valid = T + timedelta(hours=6)
    early = forecast(issued=T - timedelta(hours=6), valid=valid)
    latest = forecast(issued=T, valid=valid)
    after = forecast(issued=T + timedelta(hours=1), valid=valid)
    out, _ = PreprocessingPipeline().run(RecordBatch(forecasts=(early, after, latest)), CTX)
    assert out.forecasts == (latest,)


def test_latest_issue_is_not_chosen_over_history_in_training() -> None:
    valid = T + timedelta(hours=6)
    early = forecast(issued=T - timedelta(hours=6), valid=valid)
    later = forecast(issued=T, valid=valid)
    out, _ = LatestForecastIssue().apply(
        RecordBatch(forecasts=(early, later)), PreprocessContext(as_of=None)
    )
    assert out.forecasts == (early, later)


def test_cams_is_never_a_label() -> None:
    station = obs("station")
    cams = obs("cams", source="openmeteo", cls=ProvenanceClass.MODEL_DERIVED)
    unlabelled_cams = obs("cams-legacy", source="openmeteo", cls=None)
    stamped_wrong = obs("relabelled", source="openaq", cls=ProvenanceClass.MODEL_DERIVED)
    batch = RecordBatch(observations=(station, cams, unlabelled_cams, stamped_wrong))
    assert ids(label_observations(batch, CTX)) == ["station"]


def test_region_without_ground_truth_has_no_labels() -> None:
    pack = load_catalog(extra_region_dirs=(Path("tests/fixtures/regions"),)).get("zz-synthetic")
    ctx = PreprocessContext.for_region(pack, as_of=T)
    batch = RecordBatch(observations=(obs("a", region="zz-synthetic"),))
    assert label_observations(batch, ctx) == ()


# --- quality, region, dedup, precedence ------------------------------------


def test_quality_control_drops_invalid_and_rescores_the_rest() -> None:
    batch = RecordBatch(
        observations=(obs("ok", score=0.1), obs("neg", value=-5.0)),
        fires=(fire("f1"),),
    )
    out, dropped = QualityControl().apply(batch, CTX)
    assert ids(out.observations) == ["ok"]
    assert out.observations[0].quality.quality_score > 0.9
    assert ids(out.fires) == ["f1"]
    assert dropped == {"qc:negative_concentration": 1}


def test_quality_control_does_not_mutate_its_input() -> None:
    original = obs("ok", score=0.1)
    QualityControl().apply(RecordBatch(observations=(original,)), CTX)
    assert original.quality.quality_score == 0.1


def test_region_filter_drops_other_and_unstamped_regions() -> None:
    batch = RecordBatch(
        observations=(obs("mine"), obs("theirs", region="au-nsw"), obs("legacy", region=None))
    )
    out, dropped = RegionFilter().apply(batch, CTX)
    assert ids(out.observations) == ["mine"]
    assert dropped == {"region:other_region": 1, "region:unstamped": 1}


def test_dedup_keeps_the_higher_quality_copy_in_first_seen_order() -> None:
    low = obs("a", score=0.6, dedup="k1")
    other = obs("b", dedup="k2")
    high = obs("a2", score=0.9, dedup="k1")
    out, dropped = Deduplicate().apply(RecordBatch(observations=(low, other, high)), CTX)
    assert ids(out.observations) == ["b", "a2"]
    assert dropped == {"dedup:duplicate": 1}


def test_dedup_without_a_key_uses_the_canonical_identity() -> None:
    out, _ = Deduplicate().apply(RecordBatch(observations=(obs("a"), obs("a"))), CTX)
    assert len(out.observations) == 1


def test_station_outranks_cams_in_the_same_cell_hour_only() -> None:
    station = obs("station", at=T - timedelta(minutes=50))
    cams_same = obs(
        "cams-same",
        source="openmeteo",
        cls=ProvenanceClass.MODEL_DERIVED,
        at=T - timedelta(minutes=30),
    )
    cams_other_hour = obs(
        "cams-other",
        source="openmeteo",
        cls=ProvenanceClass.MODEL_DERIVED,
        at=T - timedelta(hours=3),
    )
    cams_other_cell = obs(
        "cams-far", source="openmeteo", cls=ProvenanceClass.MODEL_DERIVED, lat=30.9, lon=75.85
    )
    batch = RecordBatch(observations=(station, cams_same, cams_other_hour, cams_other_cell))
    out, dropped = StationsOutrankModel().apply(batch, CTX)
    assert ids(out.observations) == ["station", "cams-other", "cams-far"]
    assert dropped == {"precedence:outranked_by_station": 1}


def test_station_does_not_outrank_a_different_parameter() -> None:
    station = obs("station", parameter="pm25")
    cams_pm10 = obs(
        "cams-pm10", source="openmeteo", cls=ProvenanceClass.MODEL_DERIVED, parameter="pm10"
    )
    out, _ = StationsOutrankModel().apply(RecordBatch(observations=(station, cams_pm10)), CTX)
    assert ids(out.observations) == ["station", "cams-pm10"]


# --- pipeline --------------------------------------------------------------


def test_pipeline_is_idempotent_and_reports_every_step() -> None:
    records = [
        obs("a"),
        obs("a"),
        obs("future", at=T + timedelta(hours=2)),
        obs("cams", source="openmeteo", cls=ProvenanceClass.MODEL_DERIVED),
        obs("elsewhere", region="sg-singapore"),
        forecast(issued=T, valid=T + timedelta(hours=3)),
        fire("f1"),
    ]
    pipeline = PreprocessingPipeline.for_display()
    once, report = pipeline.run_records(records, CTX)
    twice, again = pipeline.run(once, CTX)
    assert twice == once
    assert not again.dropped
    assert [s.step for s in report.steps] == pipeline.step_names
    assert report.dropped == {
        "region:other_region": 1,
        "leak:observed_after_as_of": 1,
        "dedup:duplicate": 1,
        "precedence:outranked_by_station": 1,
    }
    assert ids(once.observations) == ["a"]
    assert len(once.forecasts) == 1
    assert ids(once.fires) == ["f1"]


def test_shared_steps_keep_cams_as_a_feature_at_station_cells() -> None:
    station = obs("station")
    cams = obs("cams", source="openmeteo", cls=ProvenanceClass.MODEL_DERIVED)
    shared, _ = PreprocessingPipeline().run(RecordBatch(observations=(station, cams)), CTX)
    assert ids(shared.observations) == ["station", "cams"]
    display, _ = PreprocessingPipeline.for_display().run(
        RecordBatch(observations=(station, cams)), CTX
    )
    assert ids(display.observations) == ["station"]


def test_a_later_station_reading_never_removes_an_earlier_cams_value() -> None:
    cams = obs("cams", source="openmeteo", cls=ProvenanceClass.MODEL_DERIVED, at=T)
    later = obs("station", at=T + timedelta(minutes=30))
    out, _ = StationsOutrankModel().apply(RecordBatch(observations=(cams, later)), CTX)
    assert ids(out.observations) == ["cams", "station"]
