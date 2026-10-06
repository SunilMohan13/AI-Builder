"""Data quality engine tests (LLD §16)."""

import importlib
from datetime import UTC, datetime, timedelta

from aeropulse_connector_sdk.quality import evaluate_observation

NOW = datetime(2026, 9, 8, 5, 20, tzinfo=UTC)
OBS = datetime(2026, 9, 8, 5, 15, tzinfo=UTC)


def test_valid_pm25() -> None:
    result = evaluate_observation(
        parameter="pm25",
        value=142.3,
        lat=28.6,
        lon=77.2,
        observed_at=OBS,
        received_at=NOW,
    )
    assert result.quality_flag == "valid"
    assert result.quality_score > 0.7


def test_negative_pm25_invalid() -> None:
    result = evaluate_observation(
        parameter="pm25",
        value=-1.0,
        lat=28.6,
        lon=77.2,
        observed_at=OBS,
        received_at=NOW,
    )
    assert result.quality_flag == "invalid"
    assert "negative_concentration" in result.reasons


def test_invalid_latitude() -> None:
    result = evaluate_observation(
        parameter="pm25",
        value=10.0,
        lat=120.0,
        lon=77.2,
        observed_at=OBS,
        received_at=NOW,
    )
    assert result.quality_flag == "invalid"
    assert "invalid_coordinates" in result.reasons


def test_future_timestamp_invalid() -> None:
    result = evaluate_observation(
        parameter="pm25",
        value=10.0,
        lat=28.6,
        lon=77.2,
        observed_at=NOW + timedelta(hours=2),
        received_at=NOW,
    )
    assert result.quality_flag == "invalid"
    assert "future_timestamp" in result.reasons


def test_humidity_out_of_range() -> None:
    result = evaluate_observation(
        parameter="humidity",
        value=140.0,
        lat=28.6,
        lon=77.2,
        observed_at=OBS,
        received_at=NOW,
    )
    assert result.quality_flag == "invalid"


def test_weights_configurable_via_env(monkeypatch) -> None:
    """LLD §16.2: weights must be config-driven, not hardcoded constants."""
    import aeropulse_connector_sdk.quality as quality_mod

    monkeypatch.setenv("AEROPULSE_QUALITY_WEIGHTS", '{"range": 0.9, "freshness": 0.01}')
    reloaded = importlib.reload(quality_mod)
    try:
        assert reloaded.QUALITY_WEIGHTS["range"] == 0.9
        assert reloaded.QUALITY_WEIGHTS["freshness"] == 0.01
        assert reloaded.QUALITY_WEIGHTS["temporal"] == 0.20  # unspecified key keeps its default
    finally:
        monkeypatch.delenv("AEROPULSE_QUALITY_WEIGHTS", raising=False)
        importlib.reload(quality_mod)


def test_weights_fall_back_to_defaults_on_malformed_env(monkeypatch) -> None:
    import aeropulse_connector_sdk.quality as quality_mod

    monkeypatch.setenv("AEROPULSE_QUALITY_WEIGHTS", "not-json")
    reloaded = importlib.reload(quality_mod)
    try:
        assert reloaded.QUALITY_WEIGHTS == quality_mod._DEFAULT_QUALITY_WEIGHTS
    finally:
        monkeypatch.delenv("AEROPULSE_QUALITY_WEIGHTS", raising=False)
        importlib.reload(quality_mod)
