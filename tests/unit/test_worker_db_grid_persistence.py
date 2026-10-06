"""TimescaleRepository SQL construction for grid_feature/grid_prediction (LLD §13/§20).

Uses a fake psycopg-shaped connection/cursor so these are true unit tests: no
Postgres required, but every call and parameter dict the repository sends to
the driver is asserted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aeropulse_contracts.feature import GridFeature
from aeropulse_contracts.observation import Provenance, Quality
from aeropulse_contracts.prediction import GridPrediction
from aeropulse_contracts.raster import RasterObservation
from aeropulse_worker.db import TimescaleRepository

NOW = datetime(2026, 9, 8, 5, 0, tzinfo=UTC)


class _FakeCursor:
    def __init__(self, calls: list[tuple[str, Any]], read_value: str | None = None) -> None:
        self._calls = calls
        self.rowcount = 1
        self._read_value = read_value
        self._result = None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: Any) -> None:
        self._calls.append((sql, params))
        if "SELECT cursor FROM connector_checkpoint" in sql and self._read_value is not None:
            self._result = (self._read_value,)

    def fetchone(self) -> tuple[str] | None:
        result = self._result
        self._result = None
        return result


class _FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.commits = 0
        self._read_value: str | None = None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.calls, self._read_value)

    def commit(self) -> None:
        self.commits += 1


def _feature() -> GridFeature:
    return GridFeature(
        grid_id="881f1d4properly",
        timestamp=NOW,
        center_lat=30.9,
        center_lon=75.8,
        pm25=180.4,
        quality_score=0.9,
        source_count=2,
        upwind_fire_score=0.0,
    )


def test_upsert_grid_feature_sends_expected_columns() -> None:
    conn = _FakeConnection()
    repo = TimescaleRepository(conn)

    repo.upsert_grid_feature(_feature())

    assert conn.commits == 1
    sql, params = conn.calls[0]
    assert "INSERT INTO grid_feature" in sql
    assert "ON CONFLICT (time, grid_id) DO UPDATE" in sql
    assert params["grid_id"] == "881f1d4properly"
    assert params["time"] == NOW
    assert params["pm25"] == 180.4
    assert params["source_count"] == 2
    assert params["feature_version"] == _feature().feature_version


def test_upsert_grid_prediction_sends_expected_columns() -> None:
    conn = _FakeConnection()
    repo = TimescaleRepository(conn)
    prediction = GridPrediction(
        grid_id="881f1d4properly",
        timestamp=NOW,
        model_version="baseline-idw-0.1",
        pm25_estimate=175.2,
        prediction_interval_low=150.0,
        prediction_interval_high=200.0,
        confidence=0.7,
    )

    repo.upsert_grid_prediction(prediction)

    assert conn.commits == 1
    sql, params = conn.calls[0]
    assert "INSERT INTO grid_prediction" in sql
    assert "ON CONFLICT (time, grid_id, model_version) DO UPDATE" in sql
    assert params["model_version"] == "baseline-idw-0.1"
    assert params["pm25_estimate"] == 175.2
    assert params["confidence"] == 0.7


def test_upsert_raster_persists_metadata_and_samples() -> None:
    conn = _FakeConnection()
    repo = TimescaleRepository(conn)
    raster = RasterObservation(
        observation_id="ras_1",
        source_id="modis",
        source_record_id="MCD19A2_20260908",
        product_id="MCD19A2_20260908",
        acquisition_time=NOW,
        processing_time=NOW,
        bbox=(73.5, 27.0, 78.5, 32.5),
        resolution="1km",
        object_uri="s3://aeropulse/raw/modis/product.hdf",
        checksum="fixture-modis",
        cloud_fraction=0.18,
        quality=Quality(quality_flag="valid", quality_score=0.77),
        provenance=Provenance(provider="NASA MODIS", connector_version="1.0.0"),
        sample_aod=0.62,
    )

    assert repo.upsert_raster(raster) is True

    assert conn.commits == 1
    sql, params = conn.calls[0]
    assert "INSERT INTO raster_observation" in sql
    assert params["source_id"] == "modis"
    assert params["min_lon"] == 73.5
    assert params["max_lat"] == 32.5
    assert params["sample_aod"] == 0.62


def test_upsert_checkpoint_records_cursor_and_reads_it_back() -> None:
    conn = _FakeConnection()
    repo = TimescaleRepository(conn)

    repo.upsert_checkpoint("cpcb", "5")
    assert conn.commits == 1
    sql, params = conn.calls[0]
    assert "INSERT INTO connector_checkpoint" in sql
    assert params["source_id"] == "cpcb"
    assert params["cursor"] == "5"

    conn.calls.clear()
    conn._read_value = "5"
    assert repo.get_checkpoint("cpcb") == "5"
    assert "SELECT cursor FROM connector_checkpoint" in conn.calls[0][0]
