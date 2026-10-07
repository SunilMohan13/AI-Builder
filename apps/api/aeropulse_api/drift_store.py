"""Request-scoped drift reader; the reader itself lives in ``aeropulse_ml.drift_store``."""

from __future__ import annotations

from collections.abc import Generator

from aeropulse_common.settings import get_settings
from aeropulse_ml.drift_store import DRIFT_SIGNALS, DriftReader, TimescaleDriftReader
from fastapi import HTTPException

__all__ = ["DRIFT_SIGNALS", "DriftReader", "TimescaleDriftReader", "get_drift_reader"]


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
