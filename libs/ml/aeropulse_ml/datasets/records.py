"""Row encoding of canonical records for Parquet and BigQuery.

Each kind is one table of ``(region_id, known_at, record)`` where ``record``
is the contract's JSON. Decoding validates every row against the contract, so
a malformed row fails loudly instead of becoming a silent NaN feature.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

import pandas as pd
from aeropulse_common.errors import DatasetError
from aeropulse_contracts import (
    CanonicalRecord,
    FireObservation,
    MeteoForecast,
    MeteorologicalObservation,
    Observation,
    RasterObservation,
)
from pydantic import ValidationError

from aeropulse_ml.preprocessing.batch import RecordBatch
from aeropulse_ml.preprocessing.steps import known_at

#: Batch attribute -> contract type.
KINDS: dict[str, type[CanonicalRecord]] = {
    "observations": Observation,
    "weather": MeteorologicalObservation,
    "forecasts": MeteoForecast,
    "fires": FireObservation,
    "rasters": RasterObservation,
}

COLUMNS = ("region_id", "known_at", "record")


def encode(records: Iterable[CanonicalRecord]) -> pd.DataFrame:
    rows = [
        {
            "region_id": r.region_id,
            "known_at": pd.Timestamp(known_at(r)),
            "record": r.model_dump_json(),
        }
        for r in records
    ]
    frame = pd.DataFrame(rows, columns=list(COLUMNS))
    frame["known_at"] = pd.to_datetime(frame["known_at"], utc=True)
    return frame


def decode(kind: str, records: Iterable[str]) -> list[CanonicalRecord]:
    model = KINDS[kind]
    out: list[CanonicalRecord] = []
    for i, payload in enumerate(records):
        try:
            out.append(model.model_validate_json(payload))
        except ValidationError as exc:
            raise DatasetError(f"{kind} row {i} does not match {model.__name__}: {exc}") from exc
    return out


def batch_from_rows(rows: dict[str, Iterable[str]]) -> RecordBatch:
    kinds = {kind: tuple(decode(kind, payloads)) for kind, payloads in rows.items()}
    return RecordBatch().with_(**kinds)


def window(frame: pd.DataFrame, *, start: datetime | None, end: datetime | None) -> pd.DataFrame:
    """Rows whose ``known_at`` lies in ``[start, end]``."""
    keep = pd.Series(True, index=frame.index)
    if start is not None:
        keep &= frame["known_at"] >= pd.Timestamp(start)
    if end is not None:
        keep &= frame["known_at"] <= pd.Timestamp(end)
    return frame.loc[keep]
