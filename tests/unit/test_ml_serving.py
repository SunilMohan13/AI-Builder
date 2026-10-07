"""Serving gates: model_serving.yaml, ModelResolver, rules, post-processing (LLD APAC 7.7)."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml
from aeropulse_common.errors import ModelServingError
from aeropulse_contracts import (
    MODEL_FAMILIES,
    CellForecast,
    DatasetLineage,
    GateReport,
    RegionGate,
)
from aeropulse_contracts.feature_spec import HAZARD_24H, ML_FEATURE_VERSION, PM25_FORECAST
from aeropulse_ml import postprocess
from aeropulse_ml.cli import main as ml_main
from aeropulse_ml.features import FeatureContext, FeaturePipeline
from aeropulse_ml.models import AnomalyPlugin, Pm25ForecastPlugin, save_model
from aeropulse_ml.serving import (
    ANOMALY_RULE_VERSION,
    FORECAST_RULE_VERSION,
    HAZARD_RULE_VERSION,
    LocalArtifactReader,
    ModelResolver,
    Served,
    ServingConfig,
    ServingEntry,
    load_serving_config,
    serve_anomalies,
    serve_forecasts,
    serve_hazard,
    serve_source_likelihood,
)
from aeropulse_ml.serving.rules import anomaly_rule, hazard_rule
from aeropulse_ml.testing import synthetic_batch
from aeropulse_regions import load_catalog
from pydantic import ValidationError

START = datetime(2026, 1, 5, tzinfo=UTC)
REPO_CONFIG = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture(scope="module")
def catalog() -> Any:
    return load_catalog(REPO_CONFIG)


def _frame(catalog: Any, feature_set: Any) -> pd.DataFrame:
    ctx = FeatureContext.for_region(catalog, "in-north", as_of=None)
    return FeaturePipeline(feature_set).build(
        synthetic_batch("in-north", start=START, hours=168), ctx, labels=True
    )


@pytest.fixture(scope="module")
def forecast_frame(catalog: Any) -> pd.DataFrame:
    return _frame(catalog, PM25_FORECAST)


@pytest.fixture(scope="module")
def hazard_frame(catalog: Any) -> pd.DataFrame:
    return _frame(catalog, HAZARD_24H)


@pytest.fixture(scope="module")
def trained(forecast_frame: pd.DataFrame, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real forecast artifact plus a gate report saying in-north passed."""
    root = tmp_path_factory.mktemp("run")
    labelled = pd.DataFrame(forecast_frame.loc[forecast_frame["pm25_target"].notna()])
    model = Pm25ForecastPlugin().fit(labelled, None, model_version="hgbq-forecast-test")
    sha = save_model(model, root / "model.joblib")
    _write_report(root, _report(sha))
    return root


def _report(sha: str | None, **changes: Any) -> GateReport:
    region = RegionGate(region_id="in-north", passed=True, labelled_rows=100, calibrated=False)
    base = GateReport(
        run_id="run-1",
        family="pm25_forecast",
        model_version="hgbq-forecast-test",
        algorithm="test",
        ml_feature_version=ML_FEATURE_VERSION,
        feature_names=list(PM25_FORECAST.names),
        calibrated=False,
        servable=True,
        artifact_uri="model.joblib",
        artifact_sha256=sha,
        code_commit="abc",
        trained_at=START,
        dataset=DatasetLineage(
            uri="parquet://history",
            kind="parquet",
            fingerprint="f",
            rows=100,
            labelled_rows=100,
            regions=["in-north"],
            preprocessing_version="preprocessing-1.1.0",
        ),
        regions=[region],
    )
    return base.model_copy(update=changes)


def _write_report(root: Path, report: GateReport, name: str = "gate.json") -> None:
    (root / name).write_text(report.model_dump_json(), encoding="utf-8")


def _entry(**changes: Any) -> ServingEntry:
    values: dict[str, Any] = {
        "family": "pm25_forecast",
        "region_id": "in-north",
        "model_version": "hgbq-forecast-test",
        "artifact_uri": "model.joblib",
        "gate_report_uri": "gate.json",
        "calibrated": False,
    }
    return ServingEntry(**{**values, **changes})


def _resolver(catalog: Any, root: Path, *entries: ServingEntry) -> ModelResolver:
    return ModelResolver(ServingConfig(entries=entries), catalog, reader=LocalArtifactReader(root))


# --- config ------------------------------------------------------------------


def test_repo_serving_file_parses_and_serves_only_rules(catalog: Any) -> None:
    resolver = ModelResolver.from_config_dir(catalog, config_dir=REPO_CONFIG)
    assert resolver.refusals == []
    for region_id in catalog.region_ids():
        served = resolver.served_models(region_id)
        assert [m.family for m in served] == list(MODEL_FAMILIES)
        for m in served:
            assert m.model_version
            assert m.calibrated is False
            if m.family == "source_likelihood":
                assert m.degraded is False
            else:
                assert m.degraded is True and m.degraded_reason


def test_missing_file_means_nothing_is_served(tmp_path: Path) -> None:
    assert load_serving_config(tmp_path / "model_serving.yaml").entries == ()


@pytest.mark.parametrize(
    "body",
    [
        "entries: [1, 2",
        "- just a list",
        "schema_version: model_serving.v1\nentries:\n  - family: pm10_magic\n"
        "    region_id: in-north\n    model_version: v\n    artifact_uri: a\n"
        "    gate_report_uri: g\n",
        "schema_version: model_serving.v1\nentries: []\nsurprise: true\n",
    ],
)
def test_invalid_serving_file_is_an_error(tmp_path: Path, body: str) -> None:
    path = tmp_path / "model_serving.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ModelServingError):
        load_serving_config(path)


def test_one_entry_per_family_and_region() -> None:
    with pytest.raises(ValidationError, match="two entries"):
        ServingConfig(entries=(_entry(), _entry(model_version="other")))


# --- resolver ----------------------------------------------------------------


def test_a_passing_entry_serves_the_model(catalog: Any, trained: Path) -> None:
    served = _resolver(catalog, trained, _entry()).resolve("pm25_forecast", "in-north")
    assert served.uses_model and served.degraded is False
    assert served.model_version == "hgbq-forecast-test"
    assert served.feature_version == ML_FEATURE_VERSION


def test_an_entry_serves_only_its_own_region(catalog: Any, trained: Path) -> None:
    resolver = _resolver(catalog, trained, _entry())
    other = resolver.resolve("pm25_forecast", "sg-singapore")
    assert not other.uses_model and other.model_version == FORECAST_RULE_VERSION


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        (
            {
                "regions": [
                    RegionGate(
                        region_id="in-north",
                        passed=False,
                        labelled_rows=9,
                        failures=["skill vs persistence <= 0"],
                    )
                ]
            },
            "failed its gate: skill vs persistence",
        ),
        ({"regions": []}, "no result for in-north"),
        ({"ml_feature_version": "ml-features-2.0.0"}, "feature version ml-features-2.0.0"),
        ({"feature_names": ["pm25"]}, "feature names differ"),
        ({"servable": False, "servable_reason": "no final model"}, "not servable: no final"),
        ({"family": "anomaly"}, "gate report is for anomaly"),
        ({"model_version": "other"}, "gate report is for other"),
        ({"artifact_sha256": None}, "pins no artifact"),
        ({"artifact_sha256": "0" * 64}, "hash mismatch"),
    ],
)
def test_a_bad_gate_report_is_refused_with_its_reason(
    catalog: Any, trained: Path, changes: dict[str, Any], reason: str
) -> None:
    good = GateReport.model_validate_json((trained / "gate.json").read_text())
    _write_report(trained, good.model_copy(update=changes), "bad.json")
    resolver = _resolver(catalog, trained, _entry(gate_report_uri="bad.json"))
    served = resolver.resolve("pm25_forecast", "in-north")
    assert not served.uses_model and served.degraded
    assert served.model_version == FORECAST_RULE_VERSION
    assert served.degraded_reason is not None
    assert served.degraded_reason.startswith("model hgbq-forecast-test refused:")
    assert reason in served.degraded_reason
    assert len(resolver.refusals) == 1


def test_synthetic_training_data_is_never_served(catalog: Any, trained: Path) -> None:
    good = GateReport.model_validate_json((trained / "gate.json").read_text())
    lineage = good.dataset.model_copy(update={"kind": "synthetic"})
    _write_report(trained, good.model_copy(update={"dataset": lineage}), "synthetic.json")
    served = _resolver(catalog, trained, _entry(gate_report_uri="synthetic.json")).resolve(
        "pm25_forecast", "in-north"
    )
    assert served.degraded_reason is not None and "synthetic data" in served.degraded_reason


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"artifact_uri": "missing.joblib"}, "file not found"),
        ({"artifact_uri": "gs://bucket/model.joblib"}, "no reader configured for gs://"),
        ({"gate_report_uri": "nowhere.json"}, "file not found"),
        ({"calibrated": True}, "claims calibrated"),
        ({"region_id": "atlantis"}, "unknown region"),
        ({"model_version": "other"}, "entry names other"),
    ],
)
def test_a_bad_entry_is_refused(
    catalog: Any, trained: Path, changes: dict[str, Any], reason: str
) -> None:
    resolver = _resolver(catalog, trained, _entry(**changes))
    assert len(resolver.refusals) == 1
    assert reason in resolver.refusals[0].reason


def test_a_tampered_artifact_is_refused_before_unpickling(catalog: Any, trained: Path) -> None:
    tampered = trained / "tampered.joblib"
    tampered.write_bytes((trained / "model.joblib").read_bytes() + b"\0")
    resolver = _resolver(catalog, trained, _entry(artifact_uri="tampered.joblib"))
    assert "hash mismatch" in resolver.refusals[0].reason


def test_source_likelihood_is_never_served_as_a_model(catalog: Any, trained: Path) -> None:
    resolver = _resolver(catalog, trained, _entry(family="source_likelihood"))
    assert "heuristic" in resolver.refusals[0].reason
    served = resolver.resolve("source_likelihood", "in-north")
    assert served.model_version == "evidence-weights-1.0"
    assert served.calibrated is False


def test_no_entry_reasons_follow_the_region_pack(catalog: Any, tmp_path: Path) -> None:
    resolver = _resolver(catalog, tmp_path)
    assert resolver.resolve("pm25_forecast", "in-north").degraded_reason == (
        "no model passed the gate for in-north"
    )
    hazard = resolver.resolve("pm25_hazard_24h", "sg-singapore")
    assert hazard.model_version == HAZARD_RULE_VERSION
    assert hazard.degraded_reason is not None and "AQI standard unconfirmed" in (
        hazard.degraded_reason
    )
    assert resolver.resolve("anomaly", "in-north").model_version == ANOMALY_RULE_VERSION
    with pytest.raises(ModelServingError, match="unknown model family"):
        resolver.resolve("pm10_magic", "in-north")


# --- rules and post-processing -------------------------------------------------


def _rows(**columns: Any) -> pd.DataFrame:
    n = len(next(iter(columns.values())))
    base = {
        "region_id": ["in-north"] * n,
        "cell": [f"c{i}" for i in range(n)],
        "t": pd.to_datetime(["2026-01-10T00:00Z"] * n, utc=True),
    }
    return pd.DataFrame({**base, **columns})


def _rule_served(family: str, version: str) -> Served:
    return Served(
        family=family,
        region_id="in-north",
        model_version=version,
        degraded=True,
        degraded_reason="no model passed the gate for in-north",
        calibrated=False,
    )


def test_forecast_rule_is_persistence_without_an_interval() -> None:
    rows = _rows(pm25=[80.0, np.nan], horizon_hours=[6.0, 6.0])
    states, used = serve_forecasts(_rule_served("pm25_forecast", FORECAST_RULE_VERSION), rows)
    assert len(states) == 1
    (state,) = states
    assert state.p50 == 80.0 and state.p10 is None and state.p90 is None
    assert state.valid_at == datetime(2026, 1, 10, 6, tzinfo=UTC)
    assert state.degraded and state.degraded_reason == used.degraded_reason
    assert state.model_version == FORECAST_RULE_VERSION


def test_hazard_rule_is_a_ramp_rank_and_needs_a_threshold() -> None:
    rows = _rows(pm25=[0.0, 60.0, 500.0, 60.0], region_threshold_ugm3=[121.0, 121.0, 121.0, np.nan])
    prediction = hazard_rule(rows)
    assert prediction["score"].iloc[0] == 0.0 and prediction["score"].iloc[2] == 1.0
    assert 0.0 < prediction["score"].iloc[1] < 1.0
    states, _ = serve_hazard(_rule_served("pm25_hazard_24h", HAZARD_RULE_VERSION), rows)
    assert [s.grid_id for s in states] == ["c0", "c1", "c2"]
    assert all(s.calibrated is False and s.degraded for s in states)


def test_anomaly_rule_flags_at_or_above_the_threshold() -> None:
    rows = _rows(pm25=[121.0, 120.9, 400.0], region_threshold_ugm3=[121.0, 121.0, 121.0])
    flags, _ = serve_anomalies(_rule_served("anomaly", ANOMALY_RULE_VERSION), rows)
    assert [f.grid_id for f in flags] == ["c0", "c2"]
    assert flags[0].score == 0.0 and flags[1].score == 1.0
    assert flags[1].expected_high == 121.0 and "absolute_threshold" in flags[1].reason
    assert bool(anomaly_rule(rows)["p50"].isna().all())


def test_postprocess_orders_quantiles_clips_negatives_and_keeps_missing_as_none() -> None:
    rows = _rows(horizon_hours=[1.0, 1.0])
    prediction = pd.DataFrame({"p10": [30.0, np.nan], "p50": [-5.0, 12.0], "p90": [20.0, np.nan]})
    served = _rule_served("pm25_forecast", "v")
    first, second = postprocess.forecast_states(rows, prediction, served)
    assert (first.p10, first.p50, first.p90) == (0.0, 20.0, 30.0)
    assert (second.p10, second.p50, second.p90) == (None, 12.0, None)


def test_hazard_is_a_probability_only_when_served_calibrated() -> None:
    rows = _rows(region_threshold_ugm3=[121.0])
    prediction = pd.DataFrame({"score": [0.8]})
    for calibrated in (False, True):
        served = Served(
            family="pm25_hazard_24h",
            region_id="in-north",
            model_version="hgb-hazard-x",
            degraded=False,
            degraded_reason=None,
            calibrated=calibrated,
        )
        (state,) = postprocess.hazard_states(rows, prediction, served)
        assert state.calibrated is calibrated and state.degraded is False


def test_a_model_that_fails_at_serving_falls_back_to_the_rule(catalog: Any, trained: Path) -> None:
    served = _resolver(catalog, trained, _entry()).resolve("pm25_forecast", "in-north")

    class Broken:
        def predict(self, model: Any, frame: pd.DataFrame) -> pd.DataFrame:
            raise ValueError("input has 3 features, expected 46")

    broken = Served(**{**served.__dict__, "plugin": Broken()})
    rows = _rows(pm25=[50.0], horizon_hours=[1.0])
    states, used = serve_forecasts(broken, rows)
    assert used.degraded and used.model_version == FORECAST_RULE_VERSION
    assert used.degraded_reason is not None and "failed at serving" in used.degraded_reason
    assert states[0].p50 == 50.0 and states[0].degraded


def test_served_model_output_carries_its_version(
    catalog: Any, trained: Path, forecast_frame: pd.DataFrame
) -> None:
    served = _resolver(catalog, trained, _entry()).resolve("pm25_forecast", "in-north")
    rows = pd.DataFrame(forecast_frame.tail(20))
    states, used = serve_forecasts(served, rows)
    assert used is served and states
    for s in states:
        assert s.model_version == "hgbq-forecast-test" and s.degraded is False
        assert s.feature_version == ML_FEATURE_VERSION
        assert s.p10 is not None and s.p50 is not None and s.p90 is not None
        assert 0.0 <= s.p10 <= s.p50 <= s.p90


def test_anomaly_model_uses_the_prior_forecast_p90_for_the_hour(
    hazard_frame: pd.DataFrame,
) -> None:
    plugin = AnomalyPlugin()
    model = plugin.fit(hazard_frame, None, model_version="quantile-anomaly-x")
    served = Served(
        family="anomaly",
        region_id="in-north",
        model_version="quantile-anomaly-x",
        degraded=False,
        degraded_reason=None,
        calibrated=False,
        plugin=plugin,
        model=model,
    )
    row = pd.DataFrame(hazard_frame.tail(1)).copy()
    row["pm25"] = 50.0
    t: datetime = pd.Timestamp(row["t"].iloc[0]).to_pydatetime()  # type: ignore[assignment]

    def forecast(p90: float, *, degraded: bool, horizon: int) -> CellForecast:
        return CellForecast(
            grid_id=str(row["cell"].iloc[0]),
            horizon_hours=horizon,
            valid_at=t,
            p10=1.0,
            p50=2.0,
            p90=p90,
            model_version="m",
            degraded=degraded,
        )

    prior = [
        forecast(40.0, degraded=False, horizon=1),
        forecast(99.0, degraded=False, horizon=6),
        forecast(1.0, degraded=True, horizon=1),
    ]
    flags, _ = serve_anomalies(served, row, prior)
    assert len(flags) == 1
    assert flags[0].expected_high == 40.0 and "forecast_p90" in flags[0].reason


def test_source_likelihood_records_are_heuristic(hazard_frame: pd.DataFrame, catalog: Any) -> None:
    records = serve_source_likelihood(catalog, "in-north", pd.DataFrame(hazard_frame.tail(3)))
    allowed = {p.source_class for p in catalog.hazards_for("in-north")}
    assert len(records) == 3
    for r in records:
        assert r.provenance_class == "heuristic" and r.calibrated is False
        assert r.method_version == "evidence-weights-1.0"
        assert {s.source_class for s in r.ranking} <= allowed


# --- CLI ---------------------------------------------------------------------


def test_serving_cli_reports_rules_and_strict_fails_on_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config"
    shutil.copytree(REPO_CONFIG, config)
    assert ml_main(["serving", "--config-dir", str(config)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert set(report["served"]) == {"au-nsw", "in-north", "sg-singapore"}
    assert report["refused"] == []

    bad = {
        "schema_version": "model_serving.v1",
        "entries": [
            {
                "family": "pm25_forecast",
                "region_id": "in-north",
                "model_version": "v",
                "artifact_uri": "missing.joblib",
                "gate_report_uri": "missing.json",
            }
        ],
    }
    (config / "model_serving.yaml").write_text(yaml.safe_dump(bad), encoding="utf-8")
    assert ml_main(["serving", "--config-dir", str(config)]) == 0
    assert ml_main(["serving", "--config-dir", str(config), "--strict"]) == 1
    out = capsys.readouterr().out
    assert "file not found" in out

    (config / "model_serving.yaml").write_text("entries: [", encoding="utf-8")
    assert ml_main(["serving", "--config-dir", str(config)]) == 1


def test_an_entry_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        ServingEntry.model_validate({**_entry().model_dump(), "valid_until": timedelta(days=1)})
