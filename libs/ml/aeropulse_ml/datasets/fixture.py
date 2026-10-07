"""Committed replay fixtures, run through each region's real connectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from aeropulse_regions import RegionCatalog
from aeropulse_regions.ingest import ingest_region

from aeropulse_ml.datasets.base import DatasetKind
from aeropulse_ml.preprocessing.batch import RecordBatch


@dataclass(frozen=True)
class FixtureDatasetSource:
    catalog: RegionCatalog
    root: Path = Path("fixtures")
    now: datetime = field(default_factory=lambda: datetime.now(UTC))
    kind: DatasetKind = "fixture"

    @property
    def uri(self) -> str:
        return f"fixture://{self.root}"

    def load(
        self, region_id: str, *, start: datetime | None = None, end: datetime | None = None
    ) -> RecordBatch:
        outcomes = ingest_region(
            self.catalog.get(region_id), mode="replay", now=self.now, fixtures_root=self.root
        )
        return RecordBatch.from_records(r for o in outcomes for r in o.records)
