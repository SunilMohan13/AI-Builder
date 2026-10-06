"""`/map/forecast` must be able to answer for one horizon.

Without this the map timeline could only ever redraw the present: the
scrubber changed a label and a query key, the request carried no horizon,
and identical present-tense data came back under a "+12h forecast" heading.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aeropulse_api.map_store import FixtureMapReader, TimescaleMapReader
from aeropulse_contracts.forecast import ForecastResult, GridCellForecast
from aeropulse_intelligence.engine import EventStore

NOW = datetime(2026, 9, 8, 6, 0, tzinfo=UTC)
ORIGIN = "883da11415fffff"


def _seed_forecast_into(store: EventStore) -> None:
    """One forecast: origin at horizon 0, then 3/6/12/24/48."""
    cells = [
        GridCellForecast(
            grid_id=ORIGIN, pm25=200.0, confidence=0.9, center_lat=28.6, center_lon=77.2
        )
    ]
    for index, horizon in enumerate((3, 6, 12, 24, 48), start=1):
        cells.append(
            GridCellForecast(
                grid_id=f"cell_{horizon}",
                pm25=200.0 - index * 10,
                confidence=0.8,
                center_lat=28.6 + index * 0.1,
                center_lon=77.2 + index * 0.1,
            )
        )
    store.forecasts["EVT-1"] = ForecastResult(
        event_id="EVT-1",
        origin_grid_id=ORIGIN,
        generated_at=NOW,
        grid_predictions=cells,
    )


def _reader(monkeypatch: Any) -> FixtureMapReader:
    store = EventStore()
    _seed_forecast_into(store)
    monkeypatch.setattr("aeropulse_api.event_store.current_store", lambda: store)
    return FixtureMapReader([], [], [])


def test_every_cell_carries_its_horizon(monkeypatch: Any) -> None:
    features = _reader(monkeypatch).forecast(100)

    horizons = [f["properties"]["horizon_hours"] for f in features]
    assert horizons == [0, 3, 6, 12, 24, 48]


def test_filtering_returns_only_the_requested_horizon(monkeypatch: Any) -> None:
    features = _reader(monkeypatch).forecast(100, horizon_hours=12)

    assert len(features) == 1
    assert features[0]["properties"]["horizon_hours"] == 12
    assert features[0]["properties"]["grid_id"] == "cell_12"


def test_horizon_zero_is_the_origin_cell(monkeypatch: Any) -> None:
    """The map overlays the observed frame with horizon 0."""
    features = _reader(monkeypatch).forecast(100, horizon_hours=0)

    assert len(features) == 1
    assert features[0]["properties"]["grid_id"] == ORIGIN


def test_an_unpublished_horizon_returns_nothing(monkeypatch: Any) -> None:
    """Forecasts exist at fixed horizons; +9h is not one of them."""
    assert _reader(monkeypatch).forecast(100, horizon_hours=9) == []


def test_omitting_the_horizon_returns_every_cell(monkeypatch: Any) -> None:
    assert len(_reader(monkeypatch).forecast(100)) == 6


class _Cursor:
    def __init__(self, calls: list[tuple[str, Any]]) -> None:
        self._calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self._calls.append((sql, params))

    def fetchall(self):
        return []


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def cursor(self):
        return _Cursor(self.calls)


def test_timescale_binds_the_horizon_filter() -> None:
    connection = _Connection()

    TimescaleMapReader(connection).forecast(100, horizon_hours=6)

    sql, params = connection.calls[0]
    assert "horizon_hours = %s::int" in sql
    assert params == (6, 6, 100)


def test_timescale_binds_null_when_no_horizon_is_requested() -> None:
    connection = _Connection()

    TimescaleMapReader(connection).forecast(100)

    assert connection.calls[0][1] == (None, None, 100)
