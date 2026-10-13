"""Local Parquet datasets in either of two layouts.

* Export layout: ``<root>/<region_id>/<kind>.parquet`` (``write_parquet_dataset``).
* Cycle layout: ``<root>/raw/<table>/*.parquet``, what the cycle's local
  analytics store writes (``var/aeropulse/analytics``), with every region's
  rows together. Tables are the BigQuery raw table names, so the same history
  trains locally and on Google Cloud.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
from aeropulse_common.errors import DatasetError
from aeropulse_contracts import CanonicalRecord

from aeropulse_ml.datasets.base import DatasetKind
from aeropulse_ml.datasets.bigquery import TABLES
from aeropulse_ml.datasets.records import (
    COLUMNS,
    KINDS,
    batch_from_rows,
    decode,
    encode,
    window,
)
from aeropulse_ml.preprocessing.batch import RecordBatch


@dataclass(frozen=True)
class ParquetDatasetSource:
    root: Path
    kind: DatasetKind = "parquet"
    #: Keep only these observation parameters, filtered before decoding.
    #: Decoding is what costs memory: 60 days of every pollutant is ~1M records.
    observation_parameters: frozenset[str] | None = None

    @property
    def uri(self) -> str:
        uri = f"parquet://{self.root.resolve()}"
        if self.observation_parameters is not None:
            uri += f"?observations={','.join(sorted(self.observation_parameters))}"
        return uri

    def load(
        self, region_id: str, *, start: datetime | None = None, end: datetime | None = None
    ) -> RecordBatch:
        if (self.root / "raw").is_dir():
            return self._load_cycle_layout(region_id, start=start, end=end)
        region_dir = self.root / region_id
        if not region_dir.is_dir():
            raise DatasetError(f"no Parquet dataset for {region_id} under {self.root}")
        rows: dict[str, list[str]] = {}
        for kind in KINDS:
            path = region_dir / f"{kind}.parquet"
            if not path.exists():
                continue
            frame = window(pd.read_parquet(path), start=start, end=end)
            rows[kind] = self._kept(kind, frame["record"])
        return batch_from_rows(rows)

    def time_span(self, region_id: str) -> tuple[datetime, datetime] | None:
        """First and last ``known_at`` of the region's observations, reading only those columns."""
        shared = (self.root / "raw").is_dir()
        if shared:
            paths = sorted((self.root / "raw" / TABLES["observations"]).glob("*.parquet"))
        else:
            paths = [p for p in [self.root / region_id / "observations.parquet"] if p.exists()]
        first: pd.Timestamp | None = None
        last: pd.Timestamp | None = None
        for path in paths:
            frame = pd.read_parquet(path, columns=["region_id", "known_at"])
            if shared:
                frame = frame.loc[frame["region_id"] == region_id]
            times = pd.to_datetime(frame["known_at"], utc=True, format="ISO8601")
            if times.empty:
                continue
            first = times.min() if first is None else min(first, times.min())
            last = times.max() if last is None else max(last, times.max())
        if first is None or last is None:
            return None
        return first.to_pydatetime(), last.to_pydatetime()

    def _load_cycle_layout(
        self, region_id: str, *, start: datetime | None, end: datetime | None
    ) -> RecordBatch:
        """Decode one file at a time, so only one file's JSON is ever held
        next to the decoded records."""
        kinds: dict[str, tuple[CanonicalRecord, ...]] = {}
        for kind, table in TABLES.items():
            files = sorted((self.root / "raw" / table).glob("*.parquet"))
            if not files:
                continue
            records: list[CanonicalRecord] = []
            for path in files:
                frame = pd.read_parquet(path, columns=list(COLUMNS))
                frame = frame.loc[frame["region_id"] == region_id].copy()
                frame["known_at"] = pd.to_datetime(frame["known_at"], utc=True, format="ISO8601")
                payloads = self._kept(kind, window(frame, start=start, end=end)["record"])
                del frame
                try:
                    records.extend(decode(kind, payloads))
                except DatasetError as exc:
                    raise DatasetError(f"{path.name}: {exc}") from exc
            kinds[kind] = tuple(records)
        if not kinds:
            raise DatasetError(f"no raw history under {self.root / 'raw'}")
        return RecordBatch().with_(**kinds)

    def _kept(self, kind: str, payloads: Iterable[str]) -> list[str]:
        wanted = self.observation_parameters
        if kind != "observations" or wanted is None:
            return list(payloads)
        return [p for p in payloads if json.loads(p)["measurement"]["parameter"] in wanted]


def write_parquet_dataset(batch: RecordBatch, root: Path, region_id: str) -> Path:
    """Write one region's batch in the export layout :class:`ParquetDatasetSource` reads."""
    region_dir = root / region_id
    region_dir.mkdir(parents=True, exist_ok=True)
    for kind in KINDS:
        records = getattr(batch, kind)
        if records:
            encode(records).to_parquet(region_dir / f"{kind}.parquet", index=False)
    return region_dir
