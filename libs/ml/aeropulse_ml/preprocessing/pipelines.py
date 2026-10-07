"""The one preprocessing pipeline definition, used by training and the cycle.

Training passes ``as_of=None`` (the feature pipeline cuts per row); the cycle
passes its cycle time. The step list is the same either way, so the two
cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from aeropulse_contracts import CanonicalRecord
from aeropulse_observability.logging import get_logger

from aeropulse_ml.preprocessing.batch import (
    PreprocessContext,
    PreprocessReport,
    RecordBatch,
    StepReport,
)
from aeropulse_ml.preprocessing.steps import (
    AsOfCutoff,
    Deduplicate,
    LatestForecastIssue,
    PreprocessingStep,
    QualityControl,
    RegionFilter,
    StationsOutrankModel,
)

logger = get_logger("aeropulse.ml.preprocessing")

#: Bump when a step is added, removed, reordered, or changes behaviour.
PREPROCESSING_VERSION = "preprocessing-1.1.0"


def default_steps(*, display: bool = False) -> tuple[PreprocessingStep, ...]:
    """The shared steps; ``display=True`` adds the served-cell-value rules."""
    shared: tuple[PreprocessingStep, ...] = (
        RegionFilter(),
        AsOfCutoff(),
        QualityControl(),
        Deduplicate(),
        LatestForecastIssue(),
    )
    return (*shared, StationsOutrankModel()) if display else shared


class PreprocessingPipeline:
    def __init__(self, steps: Sequence[PreprocessingStep] | None = None) -> None:
        self.steps: tuple[PreprocessingStep, ...] = tuple(steps or default_steps())

    @classmethod
    def for_display(cls) -> PreprocessingPipeline:
        return cls(default_steps(display=True))

    @property
    def step_names(self) -> list[str]:
        return [s.name for s in self.steps]

    def run(
        self, batch: RecordBatch, context: PreprocessContext
    ) -> tuple[RecordBatch, PreprocessReport]:
        report = PreprocessReport()
        for step in self.steps:
            rows_in = len(batch)
            batch, dropped = step.apply(batch, context)
            report.steps.append(StepReport(step.name, rows_in, len(batch), dropped))
        if report.dropped:
            logger.info(
                "preprocessing.dropped",
                region_id=context.region_id,
                dropped=dict(report.dropped),
            )
        return batch, report

    def run_records(
        self, records: Iterable[CanonicalRecord], context: PreprocessContext
    ) -> tuple[RecordBatch, PreprocessReport]:
        return self.run(RecordBatch.from_records(records), context)
