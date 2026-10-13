"""Read a region's raw history back from analytics as one ``RecordBatch``."""

from __future__ import annotations

from collections.abc import Collection
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
    kinds: Collection[str] | None = None,
    sources: Collection[str] | None = None,
) -> RecordBatch:
    """Every raw record of ``region_id`` known in ``[start, end)``.

    ``kinds`` limits the batch fields read (the rest stay empty) and
    ``sources`` the source ids, so a caller that needs a few station series
    does not decode a region's whole model grid.
    """
    unknown = set(kinds or ()) - set(RAW_TABLES)
    if unknown:
        raise ValueError(f"unknown raw kinds: {sorted(unknown)}")
    params: dict[str, Any] = {"region_id": region_id, "start": start, "end": end}
    batch: dict[str, tuple[Any, ...]] = {}
    for kind, table in RAW_TABLES.items():
        if kinds is not None and kind not in kinds:
            continue
        if sources is None:
            rows = analytics.query(f"raw.{table}.window", params, max_bytes=max_bytes)
            batch[kind] = tuple(decode(kind, (str(r["record"]) for r in rows)))
            continue
        records: list[Any] = []
        for source_id in sorted(set(sources)):
            rows = analytics.query(
                f"raw.{table}.source_window",
                {**params, "source_id": source_id},
                max_bytes=max_bytes,
            )
            decoded = decode(kind, (str(r["record"]) for r in rows))
            records.extend(r for r in decoded if getattr(r, "source_id", None) == source_id)
        batch[kind] = tuple(records)
    return RecordBatch().with_(**batch)
