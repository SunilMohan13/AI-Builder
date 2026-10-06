"""Timescale value windows for feature and prediction drift monitoring."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from typing import Any, Protocol

from aeropulse_common.settings import get_settings
from fastapi import HTTPException

DRIFT_SIGNALS: dict[str, tuple[str, str]] = {
    "feature.pm25": ("grid_feature", "pm25"),
    "feature.pm10": ("grid_feature", "pm10"),
    "feature.wind_speed": ("grid_feature", "wind_speed"),
    "feature.temperature": ("grid_feature", "temperature"),
    "feature.humidity": ("grid_feature", "humidity"),
    "feature.fire_count": ("grid_feature", "fire_count"),
    "feature.quality_score": ("grid_feature", "quality_score"),
    "feature.source_count": ("grid_feature", "source_count"),
    "feature.missing_feature_count": ("grid_feature", "missing_feature_count"),
    "prediction.pm25_estimate": ("grid_prediction", "pm25_estimate"),
    "prediction.confidence": ("grid_prediction", "confidence"),
}


class DriftReader(Protocol):
    """Read one bounded numeric signal window."""

    def values(
        self,
        signal: str,
        start: datetime,
        end: datetime,
        grid_id: str | None,
        model_version: str | None,
        limit: int,
    ) -> list[float]: ...


class TimescaleDriftReader:
    """Read whitelisted feature or prediction values from TimescaleDB."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def values(
        self,
        signal: str,
        start: datetime,
        end: datetime,
        grid_id: str | None,
        model_version: str | None,
        limit: int,
    ) -> list[float]:
        table, column = DRIFT_SIGNALS[signal]
        clauses = ["time >= %s", "time < %s", f"{column} IS NOT NULL"]
        params: list[Any] = [start, end]
        if grid_id is not None:
            clauses.append("grid_id = %s")
            params.append(grid_id)
        if model_version is not None:
            if table != "grid_prediction":
                raise ValueError("model_version only applies to prediction signals")
            clauses.append("model_version = %s")
            params.append(model_version)
        params.append(limit)
        sql = (
            f"SELECT {column} FROM {table} WHERE {' AND '.join(clauses)} "
            "ORDER BY time DESC LIMIT %s"
        )
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            return [float(row[0]) for row in cursor.fetchall()]


def get_drift_reader() -> Generator[DriftReader, None, None]:
    """Provide a request-scoped Timescale drift reader."""
    database_url = get_settings().database_url
    if not database_url:
        raise HTTPException(status_code=503, detail="Drift database not configured")
    try:
        import psycopg

        connection = psycopg.connect(database_url)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Drift database unavailable") from exc
    try:
        yield TimescaleDriftReader(connection)
    finally:
        connection.close()
