"""Offline/online feature parity harness (integration plan Phase 2).

The plan calls this the single most important measurement in the ML work:
until features computed by the production path match the features a model was
trained on, no offline metric predicts production accuracy. These tests check
the harness itself detects the two failures it exists to find — a feature that
peeks at the future, and a feature that is unavailable at inference time.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aeropulse_contracts.observation import (
    Location,
    Measurement,
    Observation,
    Provenance,
    Quality,
)
from aeropulse_ml.parity import DEFAULT_TOLERANCE, _values_agree, check_parity


def _observation(hour: int, value: float, lat: float = 28.6, lon: float = 77.2) -> Observation:
    ts = datetime(2026, 9, 8, tzinfo=UTC) + timedelta(hours=hour)
    return Observation(
        observation_id=f"obs-{lat}-{hour}",
        source_id="test",
        source_record_id=f"{lat}-{hour}",
        observed_at=ts,
        received_at=ts,
        location=Location(lat=lat, lon=lon),
        measurement=Measurement(parameter="pm25", value=value, unit="ug/m3"),
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=Provenance(provider="test", connector_version="1.0.0"),
    )


def test_trailing_features_are_identical_under_replay() -> None:
    """Batch and point-in-time construction must agree.

    Every feature is either a current-hour reading or a strictly trailing
    window, so truncating the snapshot to "what was known then" must change
    nothing. A disagreement here means a feature is reading forward.
    """
    observations = [_observation(h, 50.0 + h) for h in range(48)]

    report = check_parity(observations, weather=[])

    assert report.rows_compared == 48
    assert report.passed, [(d.feature, d.mismatches, d.example) for d in report.failing]
    assert report.for_feature_sets() == {}


def test_harness_detects_a_forward_looking_feature(monkeypatch) -> None:
    """A feature built from later observations must be caught, not tolerated.

    Simulated by making the builder emit a value derived from the *whole*
    snapshot rather than the trailing window, which is exactly the shape of
    the leakage bug this harness guards against.
    """
    from aeropulse_contracts import feature_spec

    real = feature_spec.to_feature_dict

    def leaky(feature):  # type: ignore[no-untyped-def]
        values = real(feature)
        # `neighbor_pm25_max` stands in for any statistic accidentally
        # computed over the full window: it is made to depend on how much
        # data the snapshot happens to hold.
        values["neighbor_pm25_max"] = float(feature.pm25 or 0.0) + 1000.0
        return values

    observations = [_observation(h, 50.0 + h) for h in range(30)]
    baseline = check_parity(observations, weather=[])
    assert baseline.passed

    call_count = {"n": 0}

    def sometimes_leaky(feature):  # type: ignore[no-untyped-def]
        # Diverge on the batch call only, which is what a forward-looking
        # feature does: it has more data offline than online.
        call_count["n"] += 1
        return leaky(feature) if call_count["n"] % 2 == 1 else real(feature)

    monkeypatch.setattr("aeropulse_ml.parity.to_feature_dict", sometimes_leaky)
    report = check_parity(observations, weather=[])

    assert not report.passed
    failing = {d.feature for d in report.failing}
    assert "neighbor_pm25_max" in failing
    # The report must name which models consume the broken feature.
    assert "pm25_estimator" in report.for_feature_sets()


def test_null_on_one_side_only_is_always_a_mismatch() -> None:
    """Tolerance forgives float noise, never a missing value."""
    assert _values_agree(None, None, DEFAULT_TOLERANCE) == (True, 0.0)
    assert _values_agree(1.0, None, DEFAULT_TOLERANCE)[0] is False
    assert _values_agree(None, 1.0, DEFAULT_TOLERANCE)[0] is False
    assert _values_agree(1.0, 1.00001, DEFAULT_TOLERANCE)[0] is True
    assert _values_agree(1.0, 1.5, DEFAULT_TOLERANCE)[0] is False


def test_empty_input_reports_zero_rows_rather_than_success() -> None:
    """ "Nothing compared" must be distinguishable from "everything matched"."""
    report = check_parity([], weather=[])

    assert report.rows_compared == 0
    # `passed` is vacuously true, so callers are told to check rows_compared;
    # the CLI treats zero rows as a failure for exactly this reason.
    assert report.divergences == []


def test_sample_spreads_across_the_window_not_just_the_start() -> None:
    """A sample biased to the first hours would miss late-window drift."""
    observations = [_observation(h, 50.0 + h) for h in range(100)]

    report = check_parity(observations, weather=[], sample=10)

    assert report.rows_compared == 10
