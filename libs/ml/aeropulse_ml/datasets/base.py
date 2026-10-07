"""Where training records come from (LLD APAC 7.8).

A source returns canonical records for one region; the shared preprocessing
and feature pipeline turn them into rows. No source hands back feature rows,
so training cannot drift from serving through a separate feature path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from aeropulse_ml.preprocessing.batch import RecordBatch

DatasetKind = Literal["bigquery", "parquet", "fixture", "synthetic"]

#: Kinds whose rows are not real history. A gate report built from them is
#: never servable, whatever its metrics say.
NON_SERVABLE_KINDS: frozenset[str] = frozenset({"synthetic"})


@runtime_checkable
class DatasetSource(Protocol):
    @property
    def uri(self) -> str: ...

    @property
    def kind(self) -> DatasetKind: ...

    def load(
        self, region_id: str, *, start: datetime | None = None, end: datetime | None = None
    ) -> RecordBatch: ...
