"""Read repositories for operational GeoJSON map layers."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any, Protocol

from aeropulse_common.settings import get_settings
from aeropulse_geospatial.grid import grid_boundary, grid_center
from fastapi import HTTPException


class MapReader(Protocol):
    """Read contract for recent operational map observations."""

    def air_quality(self, bbox: list[float] | None, limit: int) -> list[dict]: ...

    def fire(self, bbox: list[float] | None, limit: int) -> list[dict]: ...

    def weather(self, bbox: list[float] | None, limit: int) -> list[dict]: ...

    def forecast(self, limit: int, horizon_hours: int | None = None) -> list[dict]: ...

    def grid(self, limit: int) -> list[dict]: ...

    def satellite(self, limit: int) -> list[dict]: ...


class FixtureMapReader:
    """DB-free fallback matching the committed connector fixtures."""

    def __init__(self, air_quality: list[dict], fire: list[dict], weather: list[dict]) -> None:
        self._air_quality = air_quality
        self._fire = fire
        self._weather = weather

    def air_quality(self, bbox: list[float] | None, limit: int) -> list[dict]:
        return _filter_bbox(self._air_quality, bbox)[:limit]

    def fire(self, bbox: list[float] | None, limit: int) -> list[dict]:
        return _filter_bbox(self._fire, bbox)[:limit]

    def weather(self, bbox: list[float] | None, limit: int) -> list[dict]:
        return _filter_bbox(self._weather, bbox)[:limit]

    def forecast(self, limit: int, horizon_hours: int | None = None) -> list[dict]:
        """Advection forecast points, optionally for one horizon.

        ``grid_predictions[0]`` is the origin cell at horizon 0 and the rest
        line up with ``horizons`` in order (forecast.py builds them that way).
        The horizon was previously dropped here, which is why a map scrubbed
        to "+12h" could only ever redraw the present.
        """
        from aeropulse_api.event_store import current_store

        features: list[dict] = []
        for forecast in current_store().forecasts.values():
            horizons = [0, *forecast.horizons]
            for index, cell in enumerate(forecast.grid_predictions):
                if cell.center_lon is None or cell.center_lat is None:
                    continue
                cell_horizon = horizons[index] if index < len(horizons) else None
                if horizon_hours is not None and cell_horizon != horizon_hours:
                    continue
                features.append(
                    _point(
                        cell.center_lon,
                        cell.center_lat,
                        {
                            "grid_id": cell.grid_id,
                            "pm25": cell.pm25,
                            "confidence": cell.confidence,
                            "horizon_hours": cell_horizon,
                            "event_id": forecast.event_id,
                            "model_version": forecast.model_version,
                            "cams_applied": forecast.cams_applied,
                        },
                    )
                )
        return features[:limit]

    def grid(self, limit: int) -> list[dict]:
        return []

    def satellite(self, limit: int) -> list[dict]:
        return []


class TimescaleMapReader:
    """Read latest station/source observations from TimescaleDB."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def air_quality(self, bbox: list[float] | None, limit: int) -> list[dict]:
        where, params = _bbox_where(bbox)
        sql = f"""
        SELECT source_id, parameter, value, unit, time, longitude, latitude,
               quality_flag, quality_score, grid_id
        FROM (
            SELECT DISTINCT ON (source_id, source_record_id, parameter)
                source_id, source_record_id, parameter, value, unit, time,
                longitude, latitude, quality_flag, quality_score, grid_id
            FROM air_quality_observation{where}
            ORDER BY source_id, source_record_id, parameter, time DESC
        ) latest
        ORDER BY time DESC LIMIT %s
        """
        return self._features(sql, [*params, limit], _aq_properties, 5, 6)

    def fire(self, bbox: list[float] | None, limit: int) -> list[dict]:
        where, params = _bbox_where(bbox)
        sql = f"""
        SELECT source_id, frp, confidence, sensor, time, longitude, latitude,
               quality_score, grid_id
        FROM (
            SELECT DISTINCT ON (source_id, source_record_id)
                source_id, source_record_id, frp, confidence, sensor, time,
                longitude, latitude, quality_score, grid_id
            FROM fire_observation{where}
            ORDER BY source_id, source_record_id, time DESC
        ) latest
        ORDER BY time DESC LIMIT %s
        """
        return self._features(sql, [*params, limit], _fire_properties, 5, 6)

    def weather(self, bbox: list[float] | None, limit: int) -> list[dict]:
        where, params = _bbox_where(bbox)
        sql = f"""
        SELECT source_id, wind_u, wind_v, temperature, humidity, pressure,
               boundary_layer_height, time, longitude, latitude, quality_score, grid_id
        FROM (
            SELECT DISTINCT ON (source_id, source_record_id)
                source_id, source_record_id, wind_u, wind_v, temperature, humidity,
                pressure, boundary_layer_height, time, longitude, latitude,
                quality_score, grid_id
            FROM weather_observation{where}
            ORDER BY source_id, source_record_id, time DESC
        ) latest
        ORDER BY time DESC LIMIT %s
        """
        return self._features(sql, [*params, limit], _weather_properties, 8, 9)

    def forecast(self, limit: int, horizon_hours: int | None = None) -> list[dict]:
        sql = """
        SELECT event_id, grid_id, horizon_hours, pm25, confidence, model_version,
               cams_applied, time
        FROM (
            SELECT DISTINCT ON (event_id, horizon_hours)
                event_id, grid_id, horizon_hours, pm25, confidence, model_version,
                cams_applied, time
            FROM forecast_value
            WHERE event_id IS NOT NULL
              AND (%s::int IS NULL OR horizon_hours = %s::int)
            ORDER BY event_id, horizon_hours, time DESC
        ) latest
        ORDER BY time DESC, event_id, horizon_hours LIMIT %s
        """
        with self.connection.cursor() as cursor:
            cursor.execute(sql, (horizon_hours, horizon_hours, limit))
            rows = cursor.fetchall()
        features: list[dict] = []
        for row in rows:
            lat, lon = grid_center(row[1])
            features.append(
                _point(
                    lon,
                    lat,
                    {
                        "event_id": row[0],
                        "grid_id": row[1],
                        "horizon_hours": row[2],
                        "pm25": row[3],
                        "confidence": row[4],
                        "model_version": row[5],
                        "cams_applied": row[6],
                        "generated_at": row[7].isoformat(),
                    },
                )
            )
        return features

    def grid(self, limit: int) -> list[dict]:
        sql = """
        SELECT grid_id, time, feature_version, pm25, pm25_estimate,
               anomaly_score, quality_score
        FROM (
            SELECT DISTINCT ON (grid_id)
                grid_id, time, feature_version, pm25, pm25_estimate,
                anomaly_score, quality_score
            FROM grid_feature
            ORDER BY grid_id, time DESC
        ) latest
        ORDER BY time DESC, grid_id LIMIT %s
        """
        with self.connection.cursor() as cursor:
            cursor.execute(sql, (limit,))
            rows = cursor.fetchall()
        return [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [grid_boundary(row[0])]},
                "properties": {
                    "grid_id": row[0],
                    "observed_at": row[1].isoformat(),
                    "feature_version": row[2],
                    "pm25": row[3],
                    "pm25_estimate": row[4],
                    "anomaly_score": row[5],
                    "quality_score": row[6],
                },
            }
            for row in rows
        ]

    def satellite(self, limit: int) -> list[dict]:
        sql = """
        SELECT source_id, product_id, acquisition_time, min_lon, min_lat,
               max_lon, max_lat, resolution, object_uri, cloud_fraction,
               quality_score, sample_aod, sample_no2, sample_pm25
        FROM (
            SELECT DISTINCT ON (source_id, product_id)
                source_id, product_id, acquisition_time, min_lon, min_lat,
                max_lon, max_lat, resolution, object_uri, cloud_fraction,
                quality_score, sample_aod, sample_no2, sample_pm25
            FROM raster_observation
            ORDER BY source_id, product_id, acquisition_time DESC
        ) latest
        ORDER BY acquisition_time DESC, source_id, product_id LIMIT %s
        """
        with self.connection.cursor() as cursor:
            cursor.execute(sql, (limit,))
            rows = cursor.fetchall()
        return [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [row[3], row[4]],
                            [row[5], row[4]],
                            [row[5], row[6]],
                            [row[3], row[6]],
                            [row[3], row[4]],
                        ]
                    ],
                },
                "properties": {
                    "source_id": row[0],
                    "product_id": row[1],
                    "acquisition_time": row[2].isoformat(),
                    "resolution": row[7],
                    "object_uri": row[8],
                    "cloud_fraction": row[9],
                    "quality_score": row[10],
                    "sample_aod": row[11],
                    "sample_no2": row[12],
                    "sample_pm25": row[13],
                    "note": "AOD is not surface PM2.5",
                },
            }
            for row in rows
        ]

    def _features(
        self,
        sql: str,
        params: list[Any],
        properties: Any,
        longitude_index: int,
        latitude_index: int,
    ) -> list[dict]:
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        return [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [row[longitude_index], row[latitude_index]],
                },
                "properties": properties(row),
            }
            for row in rows
        ]


def _bbox_where(bbox: list[float] | None) -> tuple[str, list[float]]:
    if bbox is None:
        return "", []
    min_lon, min_lat, max_lon, max_lat = bbox
    return (
        " WHERE longitude BETWEEN %s AND %s AND latitude BETWEEN %s AND %s",
        [min_lon, max_lon, min_lat, max_lat],
    )


def _filter_bbox(features: list[dict], bbox: list[float] | None) -> list[dict]:
    if bbox is None:
        return list(features)
    min_lon, min_lat, max_lon, max_lat = bbox
    return [
        feature
        for feature in features
        if min_lon <= feature["geometry"]["coordinates"][0] <= max_lon
        and min_lat <= feature["geometry"]["coordinates"][1] <= max_lat
    ]


def _point(lon: float, lat: float, properties: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": properties,
    }


def _aq_properties(row: tuple[Any, ...]) -> dict:
    return {
        "source_id": row[0],
        "parameter": row[1],
        "value": row[2],
        "unit": row[3],
        "observed_at": row[4].isoformat(),
        "quality_flag": row[7],
        "quality_score": row[8],
        "grid_id": row[9],
    }


def _fire_properties(row: tuple[Any, ...]) -> dict:
    return {
        "source_id": row[0],
        "frp": row[1],
        "confidence": row[2],
        "sensor": row[3],
        "observed_at": row[4].isoformat(),
        "quality_score": row[7],
        "grid_id": row[8],
    }


def _weather_properties(row: tuple[Any, ...]) -> dict:
    return {
        "source_id": row[0],
        "wind_u": row[1],
        "wind_v": row[2],
        "temperature": row[3],
        "humidity": row[4],
        "pressure": row[5],
        "boundary_layer_height": row[6],
        "observed_at": row[7].isoformat(),
        "quality_score": row[10],
        "grid_id": row[11],
    }


class ReplayFallbackMapReader:
    """Timescale when it has fire or station rows; otherwise corridor fixtures."""

    def __init__(self, primary: MapReader, fallback: MapReader) -> None:
        self.primary = primary
        self.fallback = fallback
        self._use_fallback: bool | None = None

    def _source(self) -> MapReader:
        if self._use_fallback is None:
            self._use_fallback = not self.primary.fire(None, 1) and not self.primary.air_quality(
                None, 1
            )
        return self.fallback if self._use_fallback else self.primary

    def air_quality(self, bbox: list[float] | None, limit: int) -> list[dict]:
        return self._source().air_quality(bbox, limit)

    def fire(self, bbox: list[float] | None, limit: int) -> list[dict]:
        return self._source().fire(bbox, limit)

    def weather(self, bbox: list[float] | None, limit: int) -> list[dict]:
        return self._source().weather(bbox, limit)

    def forecast(self, limit: int, horizon_hours: int | None = None) -> list[dict]:
        return self._source().forecast(limit, horizon_hours)

    def grid(self, limit: int) -> list[dict]:
        return self._source().grid(limit)

    def satellite(self, limit: int) -> list[dict]:
        return self._source().satellite(limit)


def get_map_reader() -> Generator[MapReader, None, None]:
    """Use Timescale when configured, otherwise the fixture fallback."""
    settings = get_settings()
    from aeropulse_api.map_fixtures import air_quality_features, fire_features, weather_features

    fixtures = FixtureMapReader(air_quality_features(), fire_features(), weather_features())
    if not settings.database_url:
        yield fixtures
        return
    try:
        import psycopg

        connection = psycopg.connect(settings.database_url)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Map database unavailable") from exc
    try:
        yield ReplayFallbackMapReader(TimescaleMapReader(connection), fixtures)
    finally:
        connection.close()
