"""``ml-features-3.0.0``: one pipeline, transferable features, no future data."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import pytest
from aeropulse_contracts import (
    FireObservation,
    Location,
    Provenance,
    ProvenanceClass,
    Quality,
)
from aeropulse_contracts import feature_spec as spec
from aeropulse_contracts.feature_spec import (
    FAMILY_FEATURE_SETS,
    HAZARD_24H,
    ML_FEATURE_VERSION,
    NON_TRANSFERABLE_NAMES,
    PM25_FORECAST,
    FeatureSet,
)
from aeropulse_contracts.fire import FireProperties
from aeropulse_geospatial import to_grid_id
from aeropulse_intelligence.plume import SiteWindField, integrate, puff_weights
from aeropulse_ml.features import FeatureContext, FeaturePipeline, training_rows
from aeropulse_ml.features import pipeline as pipeline_module
from aeropulse_ml.features.parity import check_family_parity
from aeropulse_ml.preprocessing import RecordBatch
from aeropulse_ml.testing import synthetic_batch
from aeropulse_regions import load_catalog

START = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture(scope="module")
def catalog() -> Any:
    return load_catalog()


@pytest.fixture(scope="module")
def batch() -> RecordBatch:
    return synthetic_batch("in-north", start=START, hours=24 * 4)


@pytest.fixture(scope="module")
def ctx(catalog: Any) -> FeatureContext:
    return FeatureContext.for_region(catalog, "in-north", as_of=None)


# --- spec ------------------------------------------------------------------


def test_version_is_3() -> None:
    assert ML_FEATURE_VERSION == "ml-features-3.0.0"


@pytest.mark.parametrize("fs", list(FAMILY_FEATURE_SETS.values()), ids=lambda f: f.name)
def test_family_sets_are_transferable(fs: FeatureSet) -> None:
    assert not NON_TRANSFERABLE_NAMES & set(fs.names)
    assert fs.target not in fs.names


def test_a_feature_derived_from_the_future_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = FeatureSet(name="bad", names=("pm25", "peek"), target="pm25_target")
    monkeypatch.setitem(spec.DERIVED_FROM, "peek", ("pm25@t+h",))
    monkeypatch.setattr(spec, "FAMILY_FEATURE_SETS", {"bad": bad})
    with pytest.raises(AssertionError, match="derived from the future"):
        spec._assert_family_sets_are_transferable()


def test_every_pack_hazard_and_season_has_a_spec_flag(catalog: Any) -> None:
    for profile in catalog.hazard_profiles.values():
        assert profile.key in spec.HAZARD_PROFILE_IDS
        if profile.seasonal_prior is not None:
            assert profile.seasonal_prior.feature in spec.SEASONAL_FLAG_NAMES


# --- output shape ----------------------------------------------------------


@pytest.mark.parametrize("fs", [PM25_FORECAST, HAZARD_24H], ids=lambda f: f.name)
def test_columns_follow_the_spec_order(
    batch: RecordBatch, ctx: FeatureContext, fs: FeatureSet
) -> None:
    frame = FeaturePipeline(fs).build(batch, ctx, labels=True)
    assert list(frame.columns) == [
        "region_id",
        "cell",
        "t",
        *fs.names,
        fs.target,
        "ml_feature_version",
    ]
    assert set(frame["ml_feature_version"]) == {ML_FEATURE_VERSION}
    assert set(frame["region_id"]) == {"in-north"}


def test_forecast_rows_expand_over_horizons(batch: RecordBatch, ctx: FeatureContext) -> None:
    frame = FeaturePipeline(PM25_FORECAST).build(batch, ctx)
    assert sorted(frame["horizon_hours"].unique()) == [1.0, 3.0, 6.0, 12.0, 24.0]


def test_every_group_is_populated_on_a_full_history(
    batch: RecordBatch, ctx: FeatureContext
) -> None:
    frame = FeaturePipeline(PM25_FORECAST).build(batch, ctx)
    for name in (
        "pm25",
        "pm25_lag_24h",
        "pm25_roll_max_24h",
        "wind_u_now",
        "fc_wind_u_100m",
        "cams_pm25_now",
        "cams_pm25_at_h",
        "s5p_aerosol_index",
    ):
        assert bool(frame[name].notna().any()), name
    assert bool((frame["fire_count_50km_24h"] > 0).any())
    assert bool((frame["transport_weighted_frp"] > 0).any())


# --- labels ----------------------------------------------------------------


def test_forecast_target_is_the_station_value_h_hours_later(
    batch: RecordBatch, ctx: FeatureContext
) -> None:
    pipeline = FeaturePipeline(PM25_FORECAST)
    frame = pipeline.build(batch, ctx, labels=True)
    tables = pipeline.prepare(batch, ctx)
    series = tables.stations.set_index(["cell", "tau"])["value"]
    row = frame[(frame["horizon_hours"] == 6.0) & frame["pm25_target"].notna()].iloc[0]
    expected = series[(row["cell"], row["t"] + pd.Timedelta(hours=6))]
    assert row["pm25_target"] == pytest.approx(expected)


def test_cams_is_never_the_label(batch: RecordBatch, ctx: FeatureContext) -> None:
    station = next(o for o in batch.observations if o.source_id == "openaq")
    cams_here = station.model_copy(
        update={
            "source_id": "openmeteo",
            "source_record_id": "cams-at-station",
            "dedup_key": None,
            "measurement": station.measurement.model_copy(update={"value": 999.0}),
            "provenance": station.provenance.model_copy(
                update={"provenance_class": ProvenanceClass.MODEL_DERIVED}
            ),
        }
    )
    pipeline = FeaturePipeline(PM25_FORECAST)
    plain = pipeline.prepare(batch, ctx).stations
    mixed = pipeline.prepare(
        replace(batch, observations=(*batch.observations, cams_here)), ctx
    ).stations
    pd.testing.assert_frame_equal(plain, mixed)
    assert 999.0 not in set(mixed["value"])


def test_hazard_label_uses_the_region_threshold(batch: RecordBatch, ctx: FeatureContext) -> None:
    pipeline = FeaturePipeline(HAZARD_24H)
    low = pipeline.build(batch, replace(ctx, threshold_ugm3=1.0), labels=True)
    high = pipeline.build(batch, replace(ctx, threshold_ugm3=10_000.0), labels=True)
    labelled = low["hazard_24h_target"].notna()
    assert bool(labelled.any())
    assert bool((low.loc[labelled, "hazard_24h_target"] == 1.0).all())
    assert bool((high.loc[labelled, "hazard_24h_target"] == 0.0).all())


def test_unconfirmed_standard_has_no_threshold_and_no_hazard_label(catalog: Any) -> None:
    ctx = FeatureContext.for_region(catalog, "sg-singapore", as_of=None)
    frame = FeaturePipeline(HAZARD_24H).build(
        synthetic_batch("sg-singapore", start=START, hours=72), ctx, labels=True
    )
    assert not frame.empty
    assert bool(frame["region_threshold_ugm3"].isna().all())
    assert bool(frame["hazard_24h_target"].isna().all())


def test_the_last_day_has_no_hazard_label(batch: RecordBatch, ctx: FeatureContext) -> None:
    frame = FeaturePipeline(HAZARD_24H).build(batch, ctx, labels=True)
    last = frame["t"].max()
    tail: pd.DataFrame = frame.loc[frame["t"] > last - pd.Timedelta(hours=24)]
    assert bool(tail["hazard_24h_target"].isna().all())


# --- region and time -------------------------------------------------------


def test_seasonal_and_hazard_flags_come_from_the_pack(catalog: Any) -> None:
    oct_in = FeaturePipeline(HAZARD_24H).build(
        synthetic_batch("in-north", start=START, hours=30),
        FeatureContext.for_region(catalog, "in-north", as_of=None),
    )
    assert bool((oct_in["is_stubble_season"] == 1.0).all())
    assert bool((oct_in["hazard_crop_residue_burning"] == 1.0).all())
    assert bool((oct_in["hazard_transboundary_haze"] == 0.0).all())

    sg = FeaturePipeline(HAZARD_24H).build(
        synthetic_batch("sg-singapore", start=datetime(2026, 9, 1, tzinfo=UTC), hours=30),
        FeatureContext.for_region(catalog, "sg-singapore", as_of=None),
    )
    assert bool((sg["is_haze_season"] == 1.0).all())
    assert bool((sg["is_stubble_season"] == 0.0).all())

    nsw = FeaturePipeline(HAZARD_24H).build(
        synthetic_batch("au-nsw", start=START, hours=30),
        FeatureContext.for_region(catalog, "au-nsw", as_of=None),
    )
    assert bool((nsw[["is_stubble_season", "is_haze_season"]] == 0.0).all().all())
    assert bool((nsw["hazard_bushfire_smoke"] == 1.0).all())


def test_hour_encodings_are_local_time(catalog: Any) -> None:
    rows = pd.DataFrame(
        {"cell": [to_grid_id(28.61, 77.21)], "t": [pd.Timestamp("2026-10-01T06:00Z")]}
    )
    empty = RecordBatch()
    delhi = FeaturePipeline(HAZARD_24H).build(
        empty, FeatureContext.for_region(catalog, "in-north", as_of=None), rows=rows
    )
    sydney = FeaturePipeline(HAZARD_24H).build(
        empty, FeatureContext.for_region(catalog, "au-nsw", as_of=None), rows=rows
    )
    # 06:00 UTC is 11:30 in Delhi and 16:00 in Sydney (AEST, before DST).
    assert delhi["sin_hour_local"].iloc[0] == pytest.approx(np.sin(2 * np.pi * 11.5 / 24))
    assert sydney["sin_hour_local"].iloc[0] == pytest.approx(np.sin(2 * np.pi * 16 / 24))


# --- the leak rules --------------------------------------------------------


def _shift_future(batch: RecordBatch, cut: datetime) -> RecordBatch:
    """Corrupt everything after ``cut``: scale values, add a fire, add forecast issues."""

    def obs(o: Any) -> Any:
        if o.observed_at <= cut:
            return o
        m = o.measurement.model_copy(update={"value": o.measurement.value * 10})
        return o.model_copy(update={"measurement": m})

    def met(w: Any) -> Any:
        return w if w.observed_at <= cut else w.model_copy(update={"wind_u": -w.wind_u * 5})

    def fc(f: Any) -> Any:
        if f.issued_at <= cut:
            return f
        return f.model_copy(update={"cams_pm25": 999.0, "wind_u_10m": 30.0})

    def ras(r: Any) -> Any:
        return (
            r if r.processing_time <= cut else r.model_copy(update={"sample_aerosol_index": 50.0})
        )

    first = batch.observations[0]
    big_fire = FireObservation(
        observation_id="future_fire",
        source_id="firms",
        source_record_id="future_fire",
        observed_at=cut + timedelta(minutes=30),
        received_at=cut + timedelta(hours=3),
        location=Location(lat=first.location.lat, lon=first.location.lon),
        fire=FireProperties(frp=5000.0, confidence=1.0, sensor="VIIRS"),
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=Provenance(
            provider="synthetic-test",
            connector_version="0",
            provenance_class=ProvenanceClass.MEASURED,
        ),
        region_id="in-north",
    )
    return RecordBatch(
        observations=tuple(obs(o) for o in batch.observations),
        weather=tuple(met(w) for w in batch.weather),
        forecasts=tuple(fc(f) for f in batch.forecasts),
        fires=(*batch.fires, big_fire),
        rasters=tuple(ras(r) for r in batch.rasters),
    )


@pytest.mark.parametrize("fs", [PM25_FORECAST, HAZARD_24H], ids=lambda f: f.name)
def test_changing_the_future_never_changes_a_past_row(
    batch: RecordBatch, ctx: FeatureContext, fs: FeatureSet
) -> None:
    cut = START + timedelta(hours=60)
    pipeline = FeaturePipeline(fs)
    every: pd.DataFrame = training_rows(pipeline.prepare(batch, ctx))
    rows: pd.DataFrame = every.loc[every["t"] <= pd.Timestamp(cut)]
    before = pipeline.build(batch, ctx, rows=rows)
    after = pipeline.build(_shift_future(batch, cut), ctx, rows=rows)
    pd.testing.assert_frame_equal(before, after)


@pytest.mark.parametrize("fs", [PM25_FORECAST, HAZARD_24H], ids=lambda f: f.name)
def test_training_rows_match_serving_rows(
    batch: RecordBatch, ctx: FeatureContext, fs: FeatureSet
) -> None:
    report = check_family_parity(batch, ctx, fs, sample=8)
    assert report.passed, report.to_dict()
    assert report.rows_compared > 0


def test_parity_catches_a_feature_that_peeks_ahead(
    batch: RecordBatch, ctx: FeatureContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    honest = pipeline_module._history

    def peeking(wide: Any, frame: pd.DataFrame) -> dict[str, np.ndarray]:
        cols = honest(wide, frame)
        cells = pd.Series(frame["cell"])
        times = pd.Series(frame["t"] + pd.Timedelta(hours=1))
        cols["pm25_lag_1h"] = pipeline_module._lookup(wide, cells, times)
        return cols

    monkeypatch.setattr(pipeline_module, "_history", peeking)
    report = check_family_parity(batch, ctx, HAZARD_24H, sample=8)
    assert not report.passed
    assert "pm25_lag_1h" in report.mismatches


# --- transport -------------------------------------------------------------


def _constant_wind(u: float, v: float, start: datetime, hours: int) -> SiteWindField:
    buckets = {start - timedelta(hours=k): (np.array([u]), np.array([v])) for k in range(hours + 1)}
    return SiteWindField(np.array([29.0]), np.array([76.0]), buckets, max_site_km=1000.0)


def test_back_trajectory_moves_upwind() -> None:
    start = datetime(2026, 10, 1, 12, tzinfo=UTC)
    wind = _constant_wind(5.0, 0.0, start, 6)  # blowing east at 5 m/s = 18 km/h
    traj = integrate(np.array([29.0]), np.array([76.0]), start, wind, 6, backward=True)
    assert traj.lon[6, 0] < 76.0
    assert traj.travelled_km[6, 0] == pytest.approx(6 * 18.0)
    assert traj.lat[6, 0] == pytest.approx(29.0)


def test_an_upwind_fire_outweighs_a_downwind_one() -> None:
    start = datetime(2026, 10, 1, 12, tzinfo=UTC)
    wind = _constant_wind(5.0, 0.0, start, 24)
    traj = integrate(np.array([29.0]), np.array([76.0]), start, wind, 24, backward=True)
    upwind_lon = float(traj.lon[3, 0])
    downwind_lon = 76.0 + (76.0 - upwind_lon)
    w = puff_weights(
        traj,
        np.array([29.0, 29.0]),
        np.array([upwind_lon, downwind_lon]),
        np.array([3.0, 3.0]),
        initial_spread_km=2.0,
        spread_fraction=0.25,
    )
    assert w[0, 0] == pytest.approx(1.0)
    assert w[0, 1] < 1e-3


def test_unknown_wind_gives_no_transport_weight() -> None:
    start = datetime(2026, 10, 1, 12, tzinfo=UTC)
    empty = SiteWindField(np.array([29.0]), np.array([76.0]), {}, max_site_km=1000.0)
    traj = integrate(np.array([29.0]), np.array([76.0]), start, empty, 6, backward=True)
    w = puff_weights(
        traj,
        np.array([29.0]),
        np.array([76.0]),
        np.array([3.0]),
        initial_spread_km=2.0,
        spread_fraction=0.25,
    )
    assert w[0, 0] == 0.0
