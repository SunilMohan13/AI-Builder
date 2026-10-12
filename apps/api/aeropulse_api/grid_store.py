"""Timescale read repository for materialized grid features and predictions."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from typing import Any, ClassVar, Protocol

from aeropulse_common.settings import get_settings
from aeropulse_contracts.feature import GridFeature
from aeropulse_contracts.prediction import GridPrediction
from fastapi import HTTPException

from aeropulse_api import event_store as event_store_mod
from aeropulse_api.event_store import LEGACY_REGION


class GridReader(Protocol):
    """Read contract for materialized grid intelligence."""

    def list_features(
        self,
        grid_id: str | None,
        start: datetime | None,
        end: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[GridFeature], int]: ...

    def latest_feature(self, grid_id: str) -> GridFeature | None: ...

    def list_predictions(
        self,
        grid_id: str | None,
        model_version: str | None,
        start: datetime | None,
        end: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[GridPrediction], int]: ...

    def latest_prediction(
        self, grid_id: str, model_version: str | None
    ) -> GridPrediction | None: ...


class TimescaleGridReader:
    """Read materialized feature and prediction rows from TimescaleDB."""

    data_source: ClassVar[dict[str, Any]] = {"kind": "timescale", "region_id": LEGACY_REGION}

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def list_features(
        self,
        grid_id: str | None,
        start: datetime | None,
        end: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[GridFeature], int]:
        where, params = _filters(grid_id=grid_id, start=start, end=end)
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM grid_feature{where}", params)
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"SELECT payload FROM grid_feature{where} "
                "ORDER BY time DESC, grid_id LIMIT %s OFFSET %s",
                [*params, limit, offset],
            )
            items = [GridFeature.model_validate(row[0]) for row in cursor.fetchall()]
        return items, total

    def latest_feature(self, grid_id: str) -> GridFeature | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM grid_feature WHERE grid_id = %s ORDER BY time DESC LIMIT 1",
                (grid_id,),
            )
            row = cursor.fetchone()
        return GridFeature.model_validate(row[0]) if row else None

    def list_predictions(
        self,
        grid_id: str | None,
        model_version: str | None,
        start: datetime | None,
        end: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[GridPrediction], int]:
        where, params = _filters(grid_id=grid_id, model_version=model_version, start=start, end=end)
        columns = (
            "time, grid_id, model_version, pm25_estimate, prediction_interval_low, "
            "prediction_interval_high, confidence"
        )
        with self.connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM grid_prediction{where}", params)
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f"SELECT {columns} FROM grid_prediction{where} "
                "ORDER BY time DESC, grid_id, model_version LIMIT %s OFFSET %s",
                [*params, limit, offset],
            )
            items = [_prediction(row) for row in cursor.fetchall()]
        return items, total

    def latest_prediction(self, grid_id: str, model_version: str | None) -> GridPrediction | None:
        where, params = _filters(grid_id=grid_id, model_version=model_version)
        columns = (
            "time, grid_id, model_version, pm25_estimate, prediction_interval_low, "
            "prediction_interval_high, confidence"
        )
        with self.connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {columns} FROM grid_prediction{where} ORDER BY time DESC LIMIT 1",
                params,
            )
            row = cursor.fetchone()
        return _prediction(row) if row else None


def _filters(**values: Any) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    column_by_name = {"start": "time >=", "end": "time <="}
    for name, value in values.items():
        if value is None:
            continue
        operator = column_by_name.get(name)
        clauses.append(f"{operator} %s" if operator else f"{name} = %s")
        params.append(value)
    return (f" WHERE {' AND '.join(clauses)}" if clauses else "", params)


def _prediction(row: tuple[Any, ...]) -> GridPrediction:
    return GridPrediction(
        timestamp=row[0],
        grid_id=row[1],
        model_version=row[2],
        pm25_estimate=row[3],
        prediction_interval_low=row[4],
        prediction_interval_high=row[5],
        confidence=row[6],
    )


class InMemoryGridReader:
    """Serve the replay episode's latest features when Timescale is not configured."""

    data_source: ClassVar[dict[str, Any]] = {
        "kind": "replay_episode",
        "mode": "replay",
        "region_id": LEGACY_REGION,
        "reason": "replay episode: no grid_feature rows in Timescale",
    }

    def list_features(
        self,
        grid_id: str | None,
        start: datetime | None,
        end: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[GridFeature], int]:
        items = list(event_store_mod.EVENT_STORE.latest_features.values())
        if grid_id is not None:
            items = [item for item in items if item.grid_id == grid_id]
        if start is not None:
            items = [item for item in items if item.timestamp >= start]
        if end is not None:
            items = [item for item in items if item.timestamp <= end]
        items.sort(key=lambda item: item.timestamp, reverse=True)
        total = len(items)
        return items[offset : offset + limit], total

    def latest_feature(self, grid_id: str) -> GridFeature | None:
        return event_store_mod.EVENT_STORE.latest_features.get(grid_id)

    def list_predictions(
        self,
        grid_id: str | None,
        model_version: str | None,
        start: datetime | None,
        end: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[GridPrediction], int]:
        items = list(event_store_mod.EVENT_STORE.latest_predictions.values())
        if grid_id is not None:
            items = [item for item in items if item.grid_id == grid_id]
        if model_version is not None:
            items = [item for item in items if item.model_version == model_version]
        if start is not None:
            items = [item for item in items if item.timestamp >= start]
        if end is not None:
            items = [item for item in items if item.timestamp <= end]
        total = len(items)
        return items[offset : offset + limit], total

    def latest_prediction(self, grid_id: str, model_version: str | None) -> GridPrediction | None:
        item = event_store_mod.EVENT_STORE.latest_predictions.get(grid_id)
        if item is None:
            return None
        if model_version is not None and item.model_version != model_version:
            return None
        return item


class NotConfiguredGridReader:
    """Live mode with no ``grid_feature`` rows: nothing to serve, and why."""

    def __init__(self, reason: str) -> None:
        self.data_source: dict[str, Any] = {
            "kind": "not_configured",
            "region_id": LEGACY_REGION,
            "reason": reason,
        }

    def list_features(
        self,
        grid_id: str | None,
        start: datetime | None,
        end: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[GridFeature], int]:
        return [], 0

    def latest_feature(self, grid_id: str) -> GridFeature | None:
        return None

    def list_predictions(
        self,
        grid_id: str | None,
        model_version: str | None,
        start: datetime | None,
        end: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[GridPrediction], int]:
        return [], 0

    def latest_prediction(self, grid_id: str, model_version: str | None) -> GridPrediction | None:
        return None


class ReplayFallbackGridReader:
    """Timescale when it has feature rows; otherwise ``fallback``.

    Compose always sets ``AEROPULSE_DATABASE_URL``. An empty ``grid_feature``
    table 404s ``/latest`` for every seeded event cell, so Live Overview
    renders AQI 0 at lat/lon 0. Fall back only when the table is empty; the
    fallback is the replay episode in replay mode and empty in live mode.
    """

    def __init__(self, primary: GridReader, fallback: GridReader) -> None:
        self.primary = primary
        self.fallback = fallback
        self._use_fallback: bool | None = None

    def _source(self) -> GridReader:
        if self._use_fallback is None:
            _, total = self.primary.list_features(None, None, None, 1, 0)
            self._use_fallback = total == 0
        return self.fallback if self._use_fallback else self.primary

    def list_features(
        self,
        grid_id: str | None,
        start: datetime | None,
        end: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[GridFeature], int]:
        return self._source().list_features(grid_id, start, end, limit, offset)

    def latest_feature(self, grid_id: str) -> GridFeature | None:
        return self._source().latest_feature(grid_id)

    def list_predictions(
        self,
        grid_id: str | None,
        model_version: str | None,
        start: datetime | None,
        end: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[GridPrediction], int]:
        return self._source().list_predictions(grid_id, model_version, start, end, limit, offset)

    def latest_prediction(self, grid_id: str, model_version: str | None) -> GridPrediction | None:
        return self._source().latest_prediction(grid_id, model_version)

    @property
    def data_source(self) -> dict[str, Any] | None:
        return getattr(self._source(), "data_source", None)


def get_grid_reader() -> Generator[GridReader, None, None]:
    """Timescale, else the replay episode in replay mode; live mode never serves the episode."""
    settings = get_settings()
    fallback: GridReader = (
        InMemoryGridReader()
        if settings.connector_mode == "replay"
        else NotConfiguredGridReader(
            "no grid_feature rows yet and live mode never serves the replay episode"
        )
    )
    database_url = settings.database_url
    if not database_url:
        yield fallback
        return
    try:
        import psycopg

        connection = psycopg.connect(database_url)
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="Grid intelligence database unavailable"
        ) from exc
    try:
        yield ReplayFallbackGridReader(TimescaleGridReader(connection), fallback)
    finally:
        connection.close()
