"""Local Parquet datasets in either of two layouts.

* Export layout: ``<root>/<region_id>/<kind>.parquet`` (``write_parquet_dataset``).
* Cycle layout: ``<root>/raw/<table>/*.parquet``, what the cycle's local
  analytics store writes (``var/aeropulse/analytics``), with every region's
  rows together. Tables are the BigQuery raw table names, so the same history
  trains locally and on Google Cloud.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
from aeropulse_common.errors import DatasetError

from aeropulse_ml.datasets.base import DatasetKind
from aeropulse_ml.datasets.bigquery import TABLES
from aeropulse_ml.datasets.records import KINDS, batch_from_rows, encode, window
from aeropulse_ml.preprocessing.batch import RecordBatch


@dataclass(frozen=True)
class ParquetDatasetSource:
    root: Path
    kind: DatasetKind = "parquet"

    @property
    def uri(self) -> str:
        return f"parquet://{self.root.resolve()}"

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
            rows[kind] = frame["record"].tolist()
        return batch_from_rows(rows)

    def _load_cycle_layout(
        self, region_id: str, *, start: datetime | None, end: datetime | None
    ) -> RecordBatch:
        rows: dict[str, list[str]] = {}
        for kind, table in TABLES.items():
            files = sorted((self.root / "raw" / table).glob("*.parquet"))
            if not files:
                continue
            frame = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
            frame = frame.loc[frame["region_id"] == region_id].copy()
            frame["known_at"] = pd.to_datetime(frame["known_at"], utc=True)
            rows[kind] = window(frame, start=start, end=end)["record"].tolist()
        if not rows:
            raise DatasetError(f"no raw history under {self.root / 'raw'}")
        return batch_from_rows(rows)


def write_parquet_dataset(batch: RecordBatch, root: Path, region_id: str) -> Path:
    """Write one region's batch in the export layout :class:`ParquetDatasetSource` reads."""
    region_dir = root / region_id
    region_dir.mkdir(parents=True, exist_ok=True)
    for kind in KINDS:
        records = getattr(batch, kind)
        if records:
            encode(records).to_parquet(region_dir / f"{kind}.parquet", index=False)
    return region_dir
