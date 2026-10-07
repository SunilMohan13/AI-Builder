"""Synthetic history for exercising the training path. TEST DATA ONLY.

Gate reports built from this source are marked not servable (see
:data:`~aeropulse_ml.datasets.base.NON_SERVABLE_KINDS`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from aeropulse_ml.datasets.base import DatasetKind
from aeropulse_ml.preprocessing.batch import RecordBatch
from aeropulse_ml.testing import SYNTHETIC_PLACES, synthetic_batch


@dataclass(frozen=True)
class SyntheticDatasetSource:
    hours: int = 24 * 10
    seed: int = 7
    start: datetime = datetime(2026, 10, 1, tzinfo=UTC)
    kind: DatasetKind = "synthetic"

    @property
    def uri(self) -> str:
        return f"synthetic://?hours={self.hours}&seed={self.seed}"

    def load(
        self, region_id: str, *, start: datetime | None = None, end: datetime | None = None
    ) -> RecordBatch:
        if region_id not in SYNTHETIC_PLACES:
            return RecordBatch()
        return synthetic_batch(
            region_id, start=start or self.start, hours=self.hours, seed=self.seed
        )
