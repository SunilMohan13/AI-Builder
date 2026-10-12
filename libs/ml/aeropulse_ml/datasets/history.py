"""Read a region's raw history back from analytics as one ``RecordBatch``."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from aeropulse_ml.datasets.bigquery import TABLES as RAW_TABLES
from aeropulse_ml.datasets.records import decode
from aeropulse_ml.preprocessing.batch import RecordBatch

#: Run-id suffix of ``aeropulse-cycle --mode history``. Raw archive keys carry
#: the run id, so ``provenance.raw_object_uri`` shows a record was loaded from
#: a provider archive after the fact rather than seen by a live cycle.
HISTORY_RUN_SUFFIX = "_history"


def loaded_after_the_fact(record: Any) -> bool:
    """True when ``record`` came from a history backfill, not a live cycle."""
    uri = getattr(getattr(record, "provenance", None), "raw_object_uri", None) or ""
    return f"{HISTORY_RUN_SUFFIX}." in uri


class _Analytics(Protocol):
    def query(
        self, template_id: str, params: dict[str, Any], *, max_bytes: int = ...
    ) -> list[dict[str, Any]]: ...


def read_raw_window(
    analytics: _Analytics,
    region_id: str,
    *,
    start: datetime,
    end: datetime,
    max_bytes: int,
) -> RecordBatch:
    """Every raw record of ``region_id`` known in ``[start, end)``."""
    params = {"region_id": region_id, "start": start, "end": end}
    kinds: dict[str, tuple[Any, ...]] = {}
    for kind, table in RAW_TABLES.items():
        rows = analytics.query(f"raw.{table}.window", params, max_bytes=max_bytes)
        kinds[kind] = tuple(decode(kind, (str(r["record"]) for r in rows)))
    return RecordBatch().with_(**kinds)
