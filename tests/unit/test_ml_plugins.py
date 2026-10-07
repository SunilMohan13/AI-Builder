"""Model plugins, dataset sources, the train runner and gate reports (LLD APAC 7)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from aeropulse_common.errors import DatasetError, ModelServingError, TrainingError
from aeropulse_contracts import GateReport, StrategyResult
from aeropulse_contracts.feature_spec import HAZARD_24H, ML_FEATURE_VERSION, PM25_FORECAST
from aeropulse_intelligence.source_evidence import SIGNALS, rank_sources, score_class
from aeropulse_ml.datasets import (
    BigQueryDatasetSource,
    FixtureDatasetSource,
    ParquetDatasetSource,
    SyntheticDatasetSource,
    open_dataset,
    write_parquet_dataset,
)
from aeropulse_ml.features import FeatureContext, FeaturePipeline
from aeropulse_ml.models import (
    AnomalyPlugin,
    Pm25ForecastPlugin,
    Pm25Hazard24hPlugin,
    get_plugin,
    load_model,
    save_model,
)
from aeropulse_ml.testing import synthetic_batch
from aeropulse_ml.training import promotion_snippet, train_family
from aeropulse_ml.training import runner as runner_module
from aeropulse_regions import SEASONAL_PRIOR_SIGNAL, HazardProfile, load_catalog
from pydantic import ValidationError

START = datetime(2026, 10, 1, tzinfo=UTC)
SERVING_YAML = Path("config/model_serving.yaml")


@pytest.fixture(scope="module")
def catalog() -> Any:
    return load_catalog()


@pytest.fixture(scope="module")
def hazard_frame(catalog: Any) -> pd.DataFrame:
    ctx = FeatureContext.for_region(catalog, "in-north", as_of=None)
    return FeaturePipeline(HAZARD_24H).build(
        synthetic_batch("in-north", start=START, hours=240), ctx, labels=True
    )


@pytest.fixture(scope="module")
def forecast_frame(catalog: Any) -> pd.DataFrame:
    ctx = FeatureContext.for_region(catalog, "in-north", as_of=None)
    return FeaturePipeline(PM25_FORECAST).build(
        synthetic_batch("in-north", start=START, hours=168), ctx, labels=True
    )


def _labelled(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    return pd.DataFrame(frame.loc[frame[column].notna()])


# --- plugins ---------------------------------------------------------------


def test_forecast_quantiles_never_cross(forecast_frame: pd.DataFrame) -> None:
    labelled = _labelled(forecast_frame, "pm25_target")
    plugin = Pm25ForecastPlugin()
    model = plugin.fit(labelled, None, model_version="t")
    out = plugin.predict(model, labelled)
    assert bool((out["p10"] <= out["p50"]).all()) and bool((out["p50"] <= out["p90"]).all())
    assert model.ml_feature_version == ML_FEATURE_VERSION
    assert model.feature_names == PM25_FORECAST.names


def test_forecast_refuses_too_few_rows(forecast_frame: pd.DataFrame) -> None:
    with pytest.raises(TrainingError, match="labelled rows"):
        Pm25ForecastPlugin().fit(forecast_frame.head(5), None, model_version="t")


def test_a_feature_missing_everywhere_is_reported_not_fatal(forecast_frame: pd.DataFrame) -> None:
    labelled = _labelled(forecast_frame, "pm25_target").copy()
    labelled["s5p_aerosol_index"] = np.nan
    model = Pm25ForecastPlugin().fit(labelled, None, model_version="t")
    assert "s5p_aerosol_index" in model.params["missing_in_training"]


def test_hazard_calibrates_and_picks_its_threshold_on_the_calibration_slice(
    hazard_frame: pd.DataFrame,
) -> None:
    labelled = _labelled(hazard_frame, "hazard_24h_target").sort_values("t")
    cut = len(labelled) * 3 // 4
    plugin = Pm25Hazard24hPlugin()
    model = plugin.fit(labelled.iloc[:cut], labelled.iloc[cut:], model_version="t")
    uncalibrated = plugin.fit(labelled.iloc[:cut], None, model_version="t")
    assert uncalibrated.calibrated is False
    assert uncalibrated.payload["operating_threshold"] is None
    if model.calibrated:
        assert model.payload["isotonic"] is not None
    score = plugin.predict(model, labelled)["score"]
    assert score.between(0, 1).all()


def test_hazard_refuses_a_single_class(hazard_frame: pd.DataFrame) -> None:
    rows = _labelled(hazard_frame, "hazard_24h_target").copy()
    rows["hazard_24h_target"] = 0.0
    with pytest.raises(TrainingError, match="single hazard class"):
        Pm25Hazard24hPlugin().fit(rows, None, model_version="t")


def test_anomaly_uses_the_forecast_p90_when_served(hazard_frame: pd.DataFrame) -> None:
    plugin = AnomalyPlugin()
    model = plugin.fit(hazard_frame, None, model_version="t")
    rows = hazard_frame.head(5).copy()
    table = plugin.predict(model, rows)
    assert table["basis"].str.startswith("hour_of_week:").all()
    rows["forecast_p50"], rows["forecast_p90"] = 1.0, 2.0
    served = plugin.predict(model, rows)
    assert bool((served["basis"] == "forecast_p90").all())
    assert bool((served["p90"] == 2.0).all())
    assert bool((served["is_anomaly"] == (rows["pm25"] > 2.0).astype(float)).all())


def test_anomaly_falls_back_to_coarser_bins(hazard_frame: pd.DataFrame) -> None:
    plugin = AnomalyPlugin()
    model = plugin.fit(hazard_frame, None, model_version="t")
    stranger = hazard_frame.head(3).copy()
    stranger["cell"] = "never-seen"
    out = plugin.predict(model, stranger)
    assert bool(out["basis"].isin(["hour_of_week:region_hour", "hour_of_week:region"]).all())


def test_anomaly_refuses_an_empty_training_frame(hazard_frame: pd.DataFrame) -> None:
    with pytest.raises(TrainingError, match="no training rows"):
        AnomalyPlugin().fit(hazard_frame.iloc[0:0], None, model_version="t")


# --- gates -----------------------------------------------------------------


def _rolling(metrics: dict[str, Any]) -> dict[str, StrategyResult]:
    return {
        "purged_rolling_origin": StrategyResult(
            strategy="purged_rolling_origin", available=True, metrics=metrics
        )
    }


def test_forecast_gate_requires_beating_every_baseline_and_honest_intervals() -> None:
    good = {
        "_folds": 5,
        "model": {
            "skill_rmse_vs_persistence": 0.1,
            "skill_rmse_vs_cams_forecast": 0.05,
            "skill_rmse_vs_climatology_hour_of_week": 0.2,
            "coverage_p10_p90": 0.79,
        },
    }
    plugin = Pm25ForecastPlugin()
    assert plugin.gate(_rolling({"h=24": good})) == []
    worse = {**good, "model": {**good["model"], "skill_rmse_vs_cams_forecast": -0.01}}
    assert any("cams_forecast" in f for f in plugin.gate(_rolling({"h=24": worse})))
    narrow = {**good, "model": {**good["model"], "coverage_p10_p90": 0.5}}
    assert any("coverage" in f for f in plugin.gate(_rolling({"h=24": narrow})))
    no_persistence = {**good, "model": {"coverage_p10_p90": 0.8}}
    assert any("persistence" in f for f in plugin.gate(_rolling({"h=24": no_persistence})))
    assert any("folds" in f for f in plugin.gate(_rolling({"h=24": {**good, "_folds": 2}})))
    missing = {"purged_rolling_origin": StrategyResult(strategy="x", available=False, reason="r")}
    assert plugin.gate(missing) == ["purged rolling-origin not available: r"]


def test_hazard_gate_requires_margin_and_an_operating_point() -> None:
    good = {
        "_folds": 5,
        "model": {
            "pr_auc_margin_vs_current_pm25": 0.08,
            "pr_auc_margin_vs_already_above_threshold": 0.2,
            "at_operating_point.false_alert_rate": 0.05,
        },
    }
    plugin = Pm25Hazard24hPlugin()
    assert plugin.gate(_rolling({"24h": good})) == []
    thin = {**good, "model": {**good["model"], "pr_auc_margin_vs_current_pm25": 0.01}}
    assert any("current_pm25" in f for f in plugin.gate(_rolling({"24h": thin})))
    noisy = {**good, "model": {**good["model"], "at_operating_point.false_alert_rate": 0.3}}
    assert any("false-alert" in f for f in plugin.gate(_rolling({"24h": noisy})))
    no_point = {"_folds": 5, "model": {"pr_auc_margin_vs_current_pm25": 0.2}}
    assert any("operating point" in f for f in plugin.gate(_rolling({"24h": no_point})))


def test_hazard_is_calibrated_only_with_low_measured_ece(hazard_frame: pd.DataFrame) -> None:
    plugin = Pm25Hazard24hPlugin()
    labelled = _labelled(hazard_frame, "hazard_24h_target")
    model = plugin.fit(labelled, None, model_version="t")
    model.calibrated = True
    ok = _rolling({"24h": {"_folds": 5, "model": {"calibrated": 1.0, "ece": 0.02}}})
    assert plugin.region_calibrated(model, ok)
    loose = _rolling({"24h": {"_folds": 5, "model": {"calibrated": 1.0, "ece": 0.2}}})
    assert not plugin.region_calibrated(model, loose)
    partial = _rolling({"24h": {"_folds": 5, "model": {"calibrated": 0.6, "ece": 0.02}}})
    assert not plugin.region_calibrated(model, partial)


# --- source likelihood -----------------------------------------------------


def test_every_profile_signal_is_implemented(catalog: Any) -> None:
    for region_id in catalog.region_ids():
        for profile in catalog.hazards_for(region_id):
            for name in profile.signals:
                assert name in SIGNALS, (profile.key, name)
            assert profile.likelihood is not None, profile.key


def test_weights_must_name_listed_signals() -> None:
    base = {
        "key": "x",
        "display_name": "X",
        "source_class": "x",
        "signals": ["high_wind"],
        "copy": {"explainer": "e"},
    }
    with pytest.raises(ValidationError, match="does not list"):
        HazardProfile.model_validate(
            {**base, "likelihood": {"method_version": "v", "bias": 0, "weights": {"low_wind": 1}}}
        )
    with pytest.raises(ValidationError, match="does not list"):
        HazardProfile.model_validate(
            {
                **base,
                "likelihood": {
                    "method_version": "v",
                    "bias": 0,
                    "weights": {SEASONAL_PRIOR_SIGNAL: 1},
                },
            }
        )


def test_upwind_fire_ranks_crop_burning_first_and_scores_are_a_ranking(catalog: Any) -> None:
    profiles = catalog.hazards_for("in-north")
    row = {
        "fire_frp_50km_24h": 800.0,
        "transport_weighted_frp": 150.0,
        "fire_count_50km_24h": 12.0,
        "pm25": 200.0,
        "pm25_roll_24h": 90.0,
        "is_stubble_season": 1.0,
        "wind_u_now": 1.0,
        "wind_v_now": 1.0,
        "humidity_now": 60.0,
    }
    ranked = rank_sources(profiles, row, region_id="in-north", grid_id="c", valid_at=START)
    assert ranked.ranking[0].source_class == "crop_residue_burning"
    assert ranked.calibrated is False
    assert ranked.provenance_class == "heuristic"
    assert all(0.0 <= s.score <= 1.0 for s in ranked.ranking)
    population = next(e for e in ranked.evidence if e.signal == "population_density")
    assert population.value is None


def test_missing_inputs_contribute_nothing(catalog: Any) -> None:
    crop = next(p for p in catalog.hazards_for("in-north") if p.key == "crop_residue_burning")
    empty = score_class(crop, {})
    assert empty is not None
    assert empty.score.contributing_signals == []
    assert empty.score.score == pytest.approx(1 / (1 + np.exp(3.0)), abs=1e-6)


def test_source_likelihood_is_never_promotable(catalog: Any, hazard_frame: pd.DataFrame) -> None:
    plugin = get_plugin("source_likelihood", catalog)
    assert plugin.trained is False
    model = plugin.fit(hazard_frame, None, model_version="t")
    out = plugin.predict(model, hazard_frame.head(20))
    assert bool(out["top_class"].notna().all())
    assert plugin.gate({}) and "never promoted" in plugin.gate({})[0]


# --- datasets --------------------------------------------------------------


def test_parquet_round_trip_preserves_every_record(tmp_path: Path) -> None:
    batch = synthetic_batch("sg-singapore", start=START, hours=30)
    write_parquet_dataset(batch, tmp_path, "sg-singapore")
    loaded = ParquetDatasetSource(tmp_path).load("sg-singapore")
    for kind in ("observations", "weather", "forecasts", "fires", "rasters"):
        assert getattr(loaded, kind) == getattr(batch, kind), kind
    windowed = ParquetDatasetSource(tmp_path).load(
        "sg-singapore", start=START + timedelta(hours=10), end=START + timedelta(hours=20)
    )
    assert 0 < len(windowed.observations) < len(batch.observations)
    with pytest.raises(DatasetError, match="no Parquet dataset"):
        ParquetDatasetSource(tmp_path).load("au-nsw")


def test_parquet_rejects_a_malformed_row(tmp_path: Path) -> None:
    region = tmp_path / "in-north"
    region.mkdir()
    pd.DataFrame(
        {"region_id": ["in-north"], "known_at": [pd.Timestamp(START)], "record": ['{"x": 1}']}
    ).to_parquet(region / "observations.parquet")
    with pytest.raises(DatasetError, match="does not match Observation"):
        ParquetDatasetSource(tmp_path).load("in-north")


def test_bigquery_queries_are_parameterised() -> None:
    batch = synthetic_batch("in-north", start=START, hours=3)
    by_table = {
        "air_quality": [r.model_dump_json() for r in batch.observations],
        "weather": [r.model_dump_json() for r in batch.weather],
        "meteo_forecast": [],
        "fire": [],
        "raster": [],
    }
    calls: list[tuple[str, dict[str, Any]]] = []

    def runner(sql: str, params: Any) -> list[dict[str, str]]:
        calls.append((sql, dict(params)))
        table = sql.split("`")[1].rsplit(".", 1)[1]
        return [{"record": r} for r in by_table[table]]

    source = BigQueryDatasetSource(project="demo-project", runner=runner)
    loaded = source.load("in-north", start=START)
    assert loaded.observations == batch.observations
    assert all("in-north" not in sql for sql, _ in calls)
    assert all(
        params["region_id"] == "in-north" and params["start"] == START for _, params in calls
    )
    with pytest.raises(DatasetError, match="invalid BigQuery project"):
        BigQueryDatasetSource(project="x`; DROP TABLE y; --")


def test_dataset_uris(catalog: Any, tmp_path: Path) -> None:
    assert isinstance(open_dataset("fixture", catalog=catalog), FixtureDatasetSource)
    synthetic = open_dataset("synthetic://?hours=48&seed=3", catalog=catalog)
    assert isinstance(synthetic, SyntheticDatasetSource) and synthetic.hours == 48
    bq = open_dataset("bq://demo-project/raw_v2", catalog=catalog)
    assert isinstance(bq, BigQueryDatasetSource) and bq.dataset == "raw_v2"
    assert isinstance(open_dataset(str(tmp_path), catalog=catalog), ParquetDatasetSource)
    with pytest.raises(DatasetError):
        open_dataset("s3://nope", catalog=catalog)


def test_fixture_source_replays_the_region_connectors(catalog: Any) -> None:
    batch = FixtureDatasetSource(catalog, now=datetime(2026, 9, 9, tzinfo=UTC)).load("in-north")
    assert batch.observations
    assert {r.region_id for r in batch.records()} == {"in-north"}


# --- runner ----------------------------------------------------------------


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_train_writes_report_artifact_and_metric_rows_never_serving_config(
    catalog: Any, tmp_path: Path
) -> None:
    before = _sha(SERVING_YAML)
    run = train_family(
        "pm25_hazard_24h",
        SyntheticDatasetSource(hours=24 * 12),
        ["in-north", "sg-singapore"],
        catalog=catalog,
        out_dir=tmp_path,
        n_folds=4,
        now=datetime(2026, 10, 20, tzinfo=UTC),
    )
    assert _sha(SERVING_YAML) == before
    report = GateReport.model_validate_json((run.run_dir / "gate.json").read_text())
    assert report == run.report
    assert report.servable is False
    assert report.servable_reason and "synthetic" in report.servable_reason
    assert report.ml_feature_version == ML_FEATURE_VERSION
    assert report.dataset.kind == "synthetic" and len(report.dataset.fingerprint) == 16
    assert not report.passed_for("in-north")
    sg = report.region("sg-singapore")
    assert sg is not None and sg.labelled_rows == 0
    assert sg.failures == ["AQI standard unconfirmed: no hazard threshold, so no hazard label"]
    north = report.region("in-north")
    assert north is not None
    names = {s.strategy for s in north.strategies}
    assert names == {"purged_rolling_origin", "leave_region_out", "season_check"}
    transfer = next(s for s in north.strategies if s.strategy == "leave_region_out")
    assert transfer.available is False and transfer.reason == "only one region has ground truth"

    lines = (run.run_dir / "metrics.jsonl").read_text().splitlines()
    assert len(lines) == len(run.metric_rows) > 0
    assert {json.loads(x)["region_id"] for x in lines} == {"in-north"}

    artifact = Path(report.artifact_uri)
    assert report.artifact_sha256 == _sha(artifact)
    loaded = load_model(artifact, expected_sha256=report.artifact_sha256)
    assert loaded.model_version == report.model_version
    with pytest.raises(ModelServingError, match="hash mismatch"):
        load_model(artifact, expected_sha256="0" * 64)
    assert promotion_snippet(report, "gate.json") == ""


def test_fold_models_never_see_test_rows(
    catalog: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[pd.Index, pd.Index, pd.Index]] = []
    original = runner_module._run_fold

    def spy(plugin: Any, labelled: pd.DataFrame, fold: Any, acc: Any) -> None:
        seen.append((fold.fit, fold.calibration, fold.test))
        if fold.strategy == "purged_rolling_origin":
            known = labelled.loc[fold.fit.append(fold.calibration), "t"].max()
            assert known < labelled.loc[fold.test, "t"].min() - pd.Timedelta(hours=24)
        original(plugin, labelled, fold, acc)

    monkeypatch.setattr(runner_module, "_run_fold", spy)
    train_family(
        "pm25_hazard_24h",
        SyntheticDatasetSource(hours=24 * 12),
        ["in-north"],
        catalog=catalog,
        out_dir=tmp_path,
        n_folds=4,
    )
    assert seen
    for fit, cal, test in seen:
        assert not set(fit) & set(test)
        assert not set(cal) & set(test)


def test_promotion_snippet_lists_only_servable_passes(catalog: Any, tmp_path: Path) -> None:
    run = train_family(
        "anomaly",
        SyntheticDatasetSource(hours=24 * 12),
        ["in-north"],
        catalog=catalog,
        out_dir=tmp_path,
        n_folds=4,
    )
    report = run.report.model_copy(update={"servable": True})
    gate = report.regions[0].model_copy(update={"passed": True, "failures": []})
    report = report.model_copy(update={"regions": [gate]})
    snippet = promotion_snippet(report, "gs://bucket/gate.json")
    assert "region_id: in-north" in snippet
    assert "gate_report_uri: gs://bucket/gate.json" in snippet


def test_unknown_family_is_a_training_error(catalog: Any) -> None:
    with pytest.raises(TrainingError, match="unknown model family"):
        get_plugin("pm10_magic", catalog)


def test_saved_model_round_trips(forecast_frame: pd.DataFrame, tmp_path: Path) -> None:
    labelled = _labelled(forecast_frame, "pm25_target")
    model = Pm25ForecastPlugin().fit(labelled, None, model_version="v1")
    sha = save_model(model, tmp_path / "m.joblib")
    loaded = load_model(tmp_path / "m.joblib", expected_sha256=sha)
    a = Pm25ForecastPlugin().predict(model, labelled.head(10))
    b = Pm25ForecastPlugin().predict(loaded, labelled.head(10))
    pd.testing.assert_frame_equal(a, b)
