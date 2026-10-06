"""A model background must never displace a ground-station measurement.

Open-Meteo air quality is CAMS-derived model output (AGENTS.md is explicit
that it is never CPCB ground truth). Its corridor sites sit in the same H3
cells as real stations, so without an explicit precedence rule the cell's
representative PM2.5 came down to dict iteration order — and a model value a
few minutes fresher would silently win.
"""

from datetime import UTC, datetime, timedelta

from aeropulse_contracts.observation import (
    Location,
    Measurement,
    Observation,
    Provenance,
    Quality,
)
from aeropulse_geospatial.grid import to_grid_id
from aeropulse_intelligence.detect import MODEL_DERIVED_SOURCES, process_snapshot
from aeropulse_intelligence.engine import EventStore
from aeropulse_intelligence.snapshot import FeatureSnapshot

# Ludhiana: CPCB station PB014 and the Open-Meteo corridor site fall in the
# same cell, which is what exposed this.
LAT, LON = 30.901, 75.857
T0 = datetime(2026, 9, 8, 5, 15, tzinfo=UTC)


def _obs(source_id: str, value: float, observed_at: datetime) -> Observation:
    return Observation(
        observation_id=f"obs_{source_id}_{observed_at.isoformat()}",
        source_id=source_id,
        source_record_id=f"{source_id}_{observed_at.isoformat()}",
        observed_at=observed_at,
        received_at=observed_at,
        location=Location(lat=LAT, lon=LON),
        measurement=Measurement(parameter="pm25", value=value, unit="ug/m3"),
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=Provenance(provider=source_id, connector_version="1.0.0"),
    )


def _run(observations: list[Observation]) -> EventStore:
    store = EventStore()
    snapshot = FeatureSnapshot(air_quality=observations, fires=[], weather=[])
    process_snapshot(snapshot, store)
    return store


def _feature_pm25(store: EventStore) -> float | None:
    grid_id = to_grid_id(LAT, LON)
    feature = store.latest_features.get(grid_id)
    return None if feature is None else feature.pm25


def test_openmeteo_is_declared_model_derived() -> None:
    assert "openmeteo" in MODEL_DERIVED_SOURCES


def test_a_station_wins_over_a_fresher_model_value() -> None:
    """The exact case that broke Punjab detection: model output 45 min newer."""
    station = _obs("cpcb", 186.0, T0)
    model = _obs("openmeteo", 52.0, T0 + timedelta(minutes=45))

    assert _feature_pm25(_run([station, model])) == 186.0
    # Order must not matter.
    assert _feature_pm25(_run([model, station])) == 186.0


def test_openaq_ground_stations_also_outrank_the_model() -> None:
    station = _obs("openaq", 174.0, T0)
    model = _obs("openmeteo", 48.0, T0 + timedelta(hours=2))

    assert _feature_pm25(_run([station, model])) == 174.0


def test_the_newest_station_wins_among_stations() -> None:
    older = _obs("cpcb", 120.0, T0)
    newer = _obs("openaq", 199.0, T0 + timedelta(minutes=30))

    assert _feature_pm25(_run([older, newer])) == 199.0
    assert _feature_pm25(_run([newer, older])) == 199.0


def test_the_newest_model_value_wins_when_no_station_covers_the_cell() -> None:
    """Model background is still better than nothing where stations are absent."""
    older = _obs("openmeteo", 40.0, T0)
    newer = _obs("openmeteo", 61.0, T0 + timedelta(hours=1))

    assert _feature_pm25(_run([older, newer])) == 61.0
    assert _feature_pm25(_run([newer, older])) == 61.0


def test_selection_is_deterministic_across_repeated_runs() -> None:
    observations = [
        _obs("openmeteo", 52.0, T0 + timedelta(minutes=45)),
        _obs("cpcb", 186.0, T0),
        _obs("openmeteo", 49.0, T0 + timedelta(minutes=15)),
    ]
    results = {_feature_pm25(_run(list(observations))) for _ in range(5)}
    assert results == {186.0}
