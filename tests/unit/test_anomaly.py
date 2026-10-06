"""Anomaly detector tests."""

from datetime import UTC, datetime

from aeropulse_intelligence.anomaly import detect_anomaly

TS = datetime(2026, 9, 8, 5, tzinfo=UTC)


def test_threshold_triggers_without_history() -> None:
    result = detect_anomaly("g", TS, 186.0, [], quality_score=0.9)
    assert result.event_trigger is True
    assert result.anomaly_score > 0.5


def test_low_quality_does_not_trigger() -> None:
    result = detect_anomaly("g", TS, 186.0, [], quality_score=0.2)
    assert result.event_trigger is False


def test_quantile_history() -> None:
    history = [40.0] * 10
    result = detect_anomaly("g", TS, 120.0, history, quality_score=0.95)
    assert result.event_trigger is True
    assert result.baseline_pm25 is not None
    assert result.residual is not None and result.residual > 0
