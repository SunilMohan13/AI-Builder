"""Timescale-backed operational map layer tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aeropulse_api.app import create_app
from aeropulse_api.map_store import TimescaleMapReader, get_map_reader
from aeropulse_auth.jwt import Role, encode_token
from aeropulse_common.settings import get_settings
from fastapi.testclient import TestClient

NOW = datetime(2026, 9, 14, 5, 0, tzinfo=UTC)


class _Cursor:
    def __init__(self, rows: list[tuple[Any, ...]], calls: list[tuple[str, Any]]) -> None:
        self.rows = rows
        self.calls = calls

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: Any) -> None:
        self.calls.append((" ".join(sql.split()), params))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class _Connection:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, Any]] = []

    def cursor(self) -> _Cursor:
        return _Cursor(self.rows, self.calls)


def test_timescale_air_quality_maps_latest_rows_to_geojson() -> None:
    connection = _Connection(
        [("cpcb", "pm25", 142.3, "ug/m3", NOW, 77.241, 28.628, "valid", 0.9, "grid_a")]
    )
    reader = TimescaleMapReader(connection)

    features = reader.air_quality([77.0, 28.0, 78.0, 29.0], 100)

    assert features[0]["geometry"]["coordinates"] == [77.241, 28.628]
    assert features[0]["properties"]["parameter"] == "pm25"
    assert features[0]["properties"]["observed_at"] == NOW.isoformat()
    sql, params = connection.calls[0]
    assert "DISTINCT ON (source_id, source_record_id, parameter)" in sql
    assert "longitude BETWEEN %s AND %s" in sql
    assert params == [77.0, 78.0, 28.0, 29.0, 100]


def test_timescale_forecast_maps_latest_event_horizons_to_h3_centers() -> None:
    connection = _Connection(
        [
            (
                "evt_1",
                "883da11415fffff",
                3,
                135.0,
                0.8,
                "wind-advection-0.1",
                False,
                NOW,
            )
        ]
    )
    reader = TimescaleMapReader(connection)

    features = reader.forecast(100)

    coordinates = features[0]["geometry"]["coordinates"]
    assert 77.0 < coordinates[0] < 78.0
    assert 28.0 < coordinates[1] < 29.0
    assert features[0]["properties"]["horizon_hours"] == 3
    assert features[0]["properties"]["event_id"] == "evt_1"
    sql, params = connection.calls[0]
    assert "DISTINCT ON (event_id, horizon_hours)" in sql
    # No horizon requested: both filter placeholders bind NULL so the SQL
    # returns every horizon, then the limit.
    assert params == (None, None, 100)


def test_timescale_grid_maps_latest_features_to_closed_h3_polygons() -> None:
    connection = _Connection(
        [("883da11415fffff", NOW, "grid-features-0.4.0", 142.3, 140.0, 0.7, 0.9)]
    )
    reader = TimescaleMapReader(connection)

    features = reader.grid(100)

    ring = features[0]["geometry"]["coordinates"][0]
    assert features[0]["geometry"]["type"] == "Polygon"
    assert len(ring) == 7
    assert ring[0] == ring[-1]
    assert features[0]["properties"]["pm25"] == 142.3
    sql, params = connection.calls[0]
    assert "DISTINCT ON (grid_id)" in sql
    assert params == (100,)


def test_timescale_satellite_maps_latest_raster_metadata_to_footprints() -> None:
    connection = _Connection(
        [
            (
                "modis",
                "MCD19A2_20260908",
                NOW,
                73.5,
                27.0,
                78.5,
                32.5,
                "1km",
                "s3://aeropulse/raw/modis/product.hdf",
                0.18,
                0.77,
                0.62,
                None,
                None,
            )
        ]
    )
    reader = TimescaleMapReader(connection)

    features = reader.satellite(100)

    ring = features[0]["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1]
    assert features[0]["properties"]["sample_aod"] == 0.62
    assert features[0]["properties"]["note"] == "AOD is not surface PM2.5"
    sql, params = connection.calls[0]
    assert "DISTINCT ON (source_id, product_id)" in sql
    assert params == (100,)


class _FakeMapReader:
    def air_quality(self, bbox, limit):
        return [_feature("cpcb", 77.241, 28.628, {"parameter": "pm25", "value": 142.3})]

    def fire(self, bbox, limit):
        return [_feature("firms", 75.71, 30.12, {"frp": 82.4, "confidence": 0.91})]

    def weather(self, bbox, limit):
        return [_feature("imd", 77.206, 28.585, {"wind_u": -2.1, "temperature": 25.1})]

    def forecast(self, limit, horizon_hours=None):
        return [
            _feature(
                "forecast",
                77.3,
                28.7,
                {"event_id": "evt_1", "horizon_hours": 3, "pm25": 135.0},
            )
        ]

    def grid(self, limit):
        return [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [77.2, 28.6],
                            [77.3, 28.6],
                            [77.35, 28.7],
                            [77.3, 28.8],
                            [77.2, 28.8],
                            [77.15, 28.7],
                            [77.2, 28.6],
                        ]
                    ],
                },
                "properties": {"grid_id": "883da11415fffff", "pm25": 142.3},
            }
        ]

    def satellite(self, limit):
        return [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [73.5, 27.0],
                            [78.5, 27.0],
                            [78.5, 32.5],
                            [73.5, 32.5],
                            [73.5, 27.0],
                        ]
                    ],
                },
                "properties": {
                    "source_id": "modis",
                    "sample_aod": 0.62,
                    "note": "AOD is not surface PM2.5",
                },
            }
        ]


def _feature(source_id: str, lon: float, lat: float, properties: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"source_id": source_id, **properties},
    }


def _client() -> tuple[TestClient, dict[str, str]]:
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_map_reader] = lambda: _FakeMapReader()
    token = encode_token("map-test", [Role.VIEWER])
    return TestClient(app), {"Authorization": f"Bearer {token}"}


def test_operational_map_endpoints_use_repository_geojson() -> None:
    client, headers = _client()

    air_quality = client.get("/api/v1/map/air-quality?limit=10", headers=headers)
    fire = client.get("/api/v1/map/fire?limit=10", headers=headers)
    weather = client.get("/api/v1/map/weather?limit=10", headers=headers)
    forecast = client.get("/api/v1/map/forecast?limit=10", headers=headers)
    grid = client.get("/api/v1/map/grid?limit=10", headers=headers)
    satellite = client.get("/api/v1/map/satellite?limit=10", headers=headers)

    assert air_quality.status_code == fire.status_code == weather.status_code == 200
    assert forecast.status_code == 200
    assert grid.status_code == 200
    assert satellite.status_code == 200
    assert air_quality.json()["features"][0]["properties"]["value"] == 142.3
    assert fire.json()["features"][0]["properties"]["frp"] == 82.4
    assert weather.json()["features"][0]["properties"]["temperature"] == 25.1
    assert forecast.json()["features"][0]["properties"]["horizon_hours"] == 3
    assert grid.json()["features"][0]["geometry"]["type"] == "Polygon"
    assert satellite.json()["features"][0]["properties"]["sample_aod"] == 0.62


def test_map_bbox_validation_returns_422() -> None:
    client, headers = _client()

    assert client.get("/api/v1/map/air-quality?bbox=bad", headers=headers).status_code == 422
    assert client.get("/api/v1/map/fire?bbox=1,2,3", headers=headers).status_code == 422
    assert client.get("/api/v1/map/weather?bbox=5,4,3,2", headers=headers).status_code == 422
