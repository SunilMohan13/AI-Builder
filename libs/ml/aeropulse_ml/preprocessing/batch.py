"""The unit every preprocessing step reads and returns.

A ``RecordBatch`` holds canonical records (post-normalize contracts), split
by kind. Steps return a new batch and never mutate the one they were given,
so the cycle, training and replay can share a batch safely.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime

from aeropulse_contracts import (
    CanonicalRecord,
    FireObservation,
    MeteoForecast,
    MeteorologicalObservation,
    Observation,
    ProvenanceClass,
    RasterObservation,
)
from aeropulse_regions import RegionPack


@dataclass(frozen=True)
class RecordBatch:
    observations: tuple[Observation, ...] = ()
    weather: tuple[MeteorologicalObservation, ...] = ()
    forecasts: tuple[MeteoForecast, ...] = ()
    fires: tuple[FireObservation, ...] = ()
    rasters: tuple[RasterObservation, ...] = ()

    @classmethod
    def from_records(cls, records: Iterable[CanonicalRecord]) -> RecordBatch:
        buckets: dict[type, list[CanonicalRecord]] = {
            Observation: [],
            MeteorologicalObservation: [],
            MeteoForecast: [],
            FireObservation: [],
            RasterObservation: [],
        }
        for record in records:
            buckets[type(record)].append(record)
        return cls(
            observations=tuple(buckets[Observation]),  # type: ignore[arg-type]
            weather=tuple(buckets[MeteorologicalObservation]),  # type: ignore[arg-type]
            forecasts=tuple(buckets[MeteoForecast]),  # type: ignore[arg-type]
            fires=tuple(buckets[FireObservation]),  # type: ignore[arg-type]
            rasters=tuple(buckets[RasterObservation]),  # type: ignore[arg-type]
        )

    def records(self) -> list[CanonicalRecord]:
        return [
            *self.observations,
            *self.weather,
            *self.forecasts,
            *self.fires,
            *self.rasters,
        ]

    def __len__(self) -> int:
        return (
            len(self.observations)
            + len(self.weather)
            + len(self.forecasts)
            + len(self.fires)
            + len(self.rasters)
        )

    def with_(self, **kinds: tuple[CanonicalRecord, ...]) -> RecordBatch:
        return replace(self, **kinds)


@dataclass(frozen=True)
class PreprocessContext:
    """What a step may know about the run.

    Attributes:
        region_id: Records stamped with another region are dropped. ``None``
            keeps every region (pooled training).
        as_of: The cycle time. Anything not knowable at ``as_of`` is dropped.
            ``None`` in training, where the feature pipeline applies the
            cut-off per row instead.
        ground_truth_sources: Sources whose observations may be labels.
        model_derived_sources: Sources whose values are model output.
    """

    region_id: str | None = None
    as_of: datetime | None = None
    ground_truth_sources: frozenset[str] = frozenset()
    model_derived_sources: frozenset[str] = frozenset()

    @classmethod
    def for_region(cls, pack: RegionPack, *, as_of: datetime | None) -> PreprocessContext:
        return cls(
            region_id=pack.region_id,
            as_of=as_of,
            ground_truth_sources=frozenset(pack.ground_truth_sources),
            model_derived_sources=frozenset(pack.model_derived_sources),
        )

    def is_ground_truth(self, record: Observation) -> bool:
        """A station measurement from a source the region trusts as truth.

        A record with no provenance class predates the pack ingest path; the
        source list decides for it. Anything stamped non-measured never is.
        """
        if record.source_id not in self.ground_truth_sources:
            return False
        return record.provenance.provenance_class in (ProvenanceClass.MEASURED, None)

    def is_model_derived(self, record: Observation) -> bool:
        return (
            record.provenance.provenance_class == ProvenanceClass.MODEL_DERIVED
            or record.source_id in self.model_derived_sources
        )


@dataclass
class StepReport:
    step: str
    rows_in: int
    rows_out: int
    dropped: Counter[str] = field(default_factory=Counter)


@dataclass
class PreprocessReport:
    steps: list[StepReport] = field(default_factory=list)

    @property
    def dropped(self) -> Counter[str]:
        total: Counter[str] = Counter()
        for step in self.steps:
            total.update(step.dropped)
        return total

    def to_dict(self) -> dict[str, object]:
        return {
            "steps": [
                {
                    "step": s.step,
                    "rows_in": s.rows_in,
                    "rows_out": s.rows_out,
                    "dropped": dict(sorted(s.dropped.items())),
                }
                for s in self.steps
            ]
        }
