"""Contract tests for the Open-Meteo connector.

These run against a committed fixture holding verbatim upstream payloads, so
they exercise the same parsing path the live mode uses. No network, no
credential.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from aeropulse_connector_openmeteo import (
    AQ_VARIABLES,
    OpenMeteoConnector,
    wind_components,
)
from aeropulse_connector_sdk.contracts import FetchRequest
from aeropulse_contracts.meteo import MeteorologicalObservation
from aeropulse_contracts.observation import Observation
from aeropulse_intelligence.geometry import wind_direction_from, wind_speed

FIXTURE = Path("fixtures/openmeteo/observations.json")


@pytest.fixture
def connector() -> OpenMeteoConnector:
    """Connector bound to the committed replay fixture."""
    return OpenMeteoConnector(FIXTURE)


@pytest.fixture
def normalized(connector: OpenMeteoConnector) -> list[object]:
    """All canonical records produced from the fixture."""
    out: list[object] = []
    for record in connector.fetch(FetchRequest()):
        out.extend(connector.normalize(record))
    return out


def test_replay_is_the_default_mode(connector: OpenMeteoConnector) -> None:
    """A test run must never silently reach the network."""
    assert connector.is_live() is False


def test_fixture_exists_and_carries_attribution() -> None:
    """Open-Meteo requires attribution; the fixture must retain it."""
    import json

    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert "Open-Meteo" in doc["_attribution"]
    assert doc["records"]


def test_emits_both_contracts(normalized: list[object]) -> None:
    """One connector legitimately produces air quality and meteorology."""
    assert any(isinstance(o, Observation) for o in normalized)
    assert any(isinstance(o, MeteorologicalObservation) for o in normalized)


def test_schema_versions_are_pinned(normalized: list[object]) -> None:
    """Downstream consumers dispatch on schema_version."""
    for obj in normalized:
        if isinstance(obj, Observation):
            assert obj.schema_version == "observation.v1"
        elif isinstance(obj, MeteorologicalObservation):
            assert obj.schema_version == "meteo.v1"


def test_all_timestamps_are_utc_aware(normalized: list[object]) -> None:
    """Naive timestamps are how time-series pipelines silently corrupt."""
    from datetime import timedelta

    assert normalized
    for obj in normalized:
        # Raster products carry acquisition_time; point observations observed_at.
        stamp = getattr(obj, "observed_at", None) or getattr(obj, "acquisition_time", None)
        assert stamp is not None
        assert stamp.tzinfo is not None
        assert stamp.utcoffset() == timedelta(0)


def test_carbon_monoxide_is_converted_to_platform_unit(normalized: list[object]) -> None:
    """CO arrives as ug/m3 upstream but the platform's canonical unit is mg/m3.

    Mixing units across sources would corrupt the fused feature vector, because
    the feature builder reads pollutant values without consulting their unit.
    """
    co = [o for o in normalized if isinstance(o, Observation) and o.measurement.parameter == "co"]
    assert co, "fixture must contain CO"
    assert {o.measurement.unit for o in co} == {"mg/m3"}
    # Ambient CO in mg/m3 sits well under 100; in ug/m3 it would be in the
    # hundreds or thousands, so this range check catches a missing conversion.
    assert max(o.measurement.value for o in co) < 100.0


def test_pollutant_units_are_consistent_per_parameter(normalized: list[object]) -> None:
    """Each canonical parameter must report exactly one unit."""
    by_param: dict[str, set[str]] = {}
    for obj in normalized:
        if isinstance(obj, Observation):
            by_param.setdefault(obj.measurement.parameter, set()).add(obj.measurement.unit)
    for param, units in by_param.items():
        assert len(units) == 1, f"{param} reported inconsistent units {units}"


def test_aod_is_not_emitted_as_a_pollutant_measurement(normalized: list[object]) -> None:
    """LLD 18.1 and caveat 65.5: AOD must never become a surface measurement."""
    params = {o.measurement.parameter for o in normalized if isinstance(o, Observation)}
    assert "aod" not in params
    assert "aerosol_optical_depth" not in params
    assert params <= {p for p, _, _ in AQ_VARIABLES.values()}


def test_pollutant_values_are_physically_plausible(normalized: list[object]) -> None:
    """A negative concentration means a parsing or scaling error."""
    for obj in normalized:
        if isinstance(obj, Observation):
            assert obj.measurement.value >= 0.0


def test_weather_populates_rainfall_and_blh(normalized: list[object]) -> None:
    """Both fields were previously unreachable dead schema."""
    wx = [o for o in normalized if isinstance(o, MeteorologicalObservation)]
    assert any(o.rainfall is not None for o in wx)
    assert any(o.boundary_layer_height is not None for o in wx)


def test_wind_components_round_trip(normalized: list[object]) -> None:
    """Reconstructed u/v must invert the platform's own direction helper.

    An inverted sign here would send every advection forecast the wrong way,
    and no unit test of the forecast module alone would catch it.
    """
    wx = [
        o for o in normalized if isinstance(o, MeteorologicalObservation) and o.wind_u and o.wind_v
    ]
    assert wx, "fixture must contain wind"
    for obs in wx[:20]:
        assert obs.wind_u is not None and obs.wind_v is not None
        speed = wind_speed(obs.wind_u, obs.wind_v)
        assert speed > 0
        # Direction must be recoverable; compare via components to avoid
        # wrap-around comparisons at 0/360.
        direction = wind_direction_from(obs.wind_u, obs.wind_v)
        u2, v2 = wind_components(speed, direction)
        assert math.isclose(u2, obs.wind_u, abs_tol=1e-3)
        assert math.isclose(v2, obs.wind_v, abs_tol=1e-3)


@pytest.mark.parametrize(
    ("direction", "expected_u", "expected_v"),
    [
        (0.0, 0.0, -1.0),  # from north -> blows south
        (90.0, -1.0, 0.0),  # from east  -> blows west
        (180.0, 0.0, 1.0),  # from south -> blows north
        (270.0, 1.0, 0.0),  # from west  -> blows east
    ],
)
def test_wind_cardinal_directions(direction: float, expected_u: float, expected_v: float) -> None:
    """Pin the sign convention against hand-computed cardinal cases."""
    u, v = wind_components(1.0, direction)
    assert math.isclose(u, expected_u, abs_tol=1e-9)
    assert math.isclose(v, expected_v, abs_tol=1e-9)


def test_source_record_ids_are_unique(normalized: list[object]) -> None:
    """Duplicate record ids would defeat the dedup_key idempotency guard."""
    ids = [o.source_record_id for o in normalized]  # type: ignore[attr-defined]
    assert len(ids) == len(set(ids))


def test_provenance_marks_model_output_not_ground_truth(normalized: list[object]) -> None:
    """The CAMS-derived caveat must survive into the evidence graph."""
    for obj in normalized:
        provider = obj.provenance.provider  # type: ignore[attr-defined]
        assert "Open-Meteo" in provider
        assert "model output" in provider


def test_null_upstream_hours_are_skipped_not_imputed() -> None:
    """Missingness must stay visible to the quality engine."""
    connector = OpenMeteoConnector()
    record = _synthetic_record(pm25=[10.0, None, 30.0])
    observations = [
        o
        for o in connector.normalize(record)
        if isinstance(o, Observation) and o.measurement.parameter == "pm25"
    ]
    assert [o.measurement.value for o in observations] == [10.0, 30.0]


def test_missing_wind_yields_null_components_not_zero() -> None:
    """Zero wind is a physical claim; absent wind is not."""
    connector = OpenMeteoConnector()
    record = _synthetic_record(pm25=[10.0], wind=False)
    wx = [o for o in connector.normalize(record) if isinstance(o, MeteorologicalObservation)]
    assert wx[0].wind_u is None
    assert wx[0].wind_v is None


def _synthetic_record(*, pm25: list[float | None], wind: bool = True):
    """Build a minimal upstream-shaped payload for edge-case tests."""
    from datetime import UTC, datetime

    from aeropulse_connector_sdk.contracts import RawRecord

    times = [f"2026-09-08T{h:02d}:00" for h in range(len(pm25))]
    weather: dict[str, object] = {"time": times, "temperature_2m": [30.0] * len(pm25)}
    if wind:
        weather["wind_speed_10m"] = [2.0] * len(pm25)
        weather["wind_direction_10m"] = [90.0] * len(pm25)
    return RawRecord(
        source_id="openmeteo",
        source_record_id="synthetic",
        payload={
            "site": {"site_id": "synthetic", "name": "Synthetic", "lat": 28.6, "lon": 77.2},
            "air_quality": {"hourly": {"time": times, "pm2_5": pm25}},
            "weather": {"hourly": weather},
        },
        fetched_at=datetime.now(UTC),
    )
