"""Read connector ``source_health`` rows for the sources API.

Telemetry is nullable. Missing database configuration returns an empty map
so the registry still lists sources; it never invents freshness or latency.
A configured database that cannot be reached is a 503, matching the other
Timescale readers.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from typing import Any, Protocol

from aeropulse_common.settings import get_settings
from fastapi import HTTPException


class SourceHealthRow:
    """One measured connector run, or the latest persisted snapshot of it."""

    __slots__ = (
        "error_rate",
        "last_error",
        "last_success_at",
        "latency_ms",
        "processing_mode",
        "quality_score",
        "records_per_run",
        "source_id",
        "status",
    )

    def __init__(
        self,
        source_id: str,
        status: str,
        last_success_at: datetime | None,
        records_per_run: int | None,
        latency_ms: int | None,
        last_error: str | None,
        processing_mode: str | None,
        quality_score: float | None = None,
        error_rate: float | None = None,
    ) -> None:
        self.source_id = source_id
        self.status = status
        self.last_success_at = last_success_at
        self.records_per_run = records_per_run
        self.latency_ms = latency_ms
        self.last_error = last_error
        self.processing_mode = processing_mode
        self.quality_score = quality_score
        self.error_rate = error_rate


class SourceHealthReader(Protocol):
    """Latest health keyed by source id."""

    def latest(self) -> dict[str, SourceHealthRow]: ...


class EmptySourceHealthReader:
    """DB-free development: registry only, no invented telemetry."""

    def latest(self) -> dict[str, SourceHealthRow]:
        return {}


class TimescaleSourceHealthReader:
    """Read the latest ``source_health`` row per source."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def latest(self) -> dict[str, SourceHealthRow]:
        sql = """
        SELECT source_id, status, last_success_at, records_per_run,
               latency_ms, last_error, processing_mode, quality_score, error_rate
        FROM source_health
        """
        with self.connection.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
        return {
            row[0]: SourceHealthRow(
                source_id=row[0],
                status=row[1],
                last_success_at=row[2],
                records_per_run=row[3],
                latency_ms=row[4],
                last_error=row[5],
                processing_mode=row[6],
                quality_score=row[7],
                error_rate=row[8],
            )
            for row in rows
        }


def get_source_health_reader() -> Generator[SourceHealthReader, None, None]:
    """Timescale when configured; otherwise an empty reader."""
    database_url = get_settings().database_url
    if not database_url:
        yield EmptySourceHealthReader()
        return
    try:
        import psycopg

        connection = psycopg.connect(database_url)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Source health database unavailable") from exc
    try:
        yield TimescaleSourceHealthReader(connection)
    finally:
        connection.close()
