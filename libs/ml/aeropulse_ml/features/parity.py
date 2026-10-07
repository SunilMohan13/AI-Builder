"""Training/serving parity for ``ml-features-3.0.0``.

Training builds every row from the whole history (``as_of=None``). Serving
builds the row at ``t`` from data preprocessed with ``as_of=t``. Both call the
same :class:`FeaturePipeline`, so any disagreement means a feature reads
something not knowable at ``t`` (a leak) or something serving cannot see.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from aeropulse_contracts.feature_spec import FeatureSet

from aeropulse_ml.features.pipeline import FeatureContext, FeaturePipeline
from aeropulse_ml.preprocessing import RecordBatch

DEFAULT_TOLERANCE = 1e-6


@dataclass
class FamilyParityReport:
    family: str
    region_id: str
    times_checked: int = 0
    rows_compared: int = 0
    mismatches: dict[str, int] = field(default_factory=dict)
    examples: dict[str, dict[str, object]] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.rows_compared > 0 and not self.mismatches

    def to_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "region_id": self.region_id,
            "times_checked": self.times_checked,
            "rows_compared": self.rows_compared,
            "passed": self.passed,
            "mismatches": dict(sorted(self.mismatches.items())),
            "examples": self.examples,
        }


def _sample_times(times: Sequence[pd.Timestamp], sample: int) -> list[pd.Timestamp]:
    ordered = sorted(set(times))
    if len(ordered) <= sample:
        return ordered
    picks = np.linspace(0, len(ordered) - 1, sample).round().astype(int)
    return [ordered[i] for i in sorted(set(picks))]


def check_family_parity(
    batch: RecordBatch,
    context: FeatureContext,
    feature_set: FeatureSet,
    *,
    sample: int = 12,
    tolerance: float = DEFAULT_TOLERANCE,
) -> FamilyParityReport:
    pipeline = FeaturePipeline(feature_set)
    report = FamilyParityReport(family=feature_set.name, region_id=context.region_id)
    offline = pipeline.build(batch, context.at(None))
    if offline.empty:
        return report
    keys = ["cell", "t", *(["horizon_hours"] if pipeline.per_horizon else [])]
    for t in _sample_times(list(offline["t"]), sample):
        rows = offline.loc[offline["t"] == t, ["cell", "t"]].drop_duplicates()
        online = pipeline.build(batch, context.at(t.to_pydatetime()), rows=rows)
        left = offline[offline["t"] == t].set_index(keys).sort_index()
        right = online.set_index(keys).sort_index()
        report.times_checked += 1
        report.rows_compared += len(left)
        for name in feature_set.names:
            if name == "horizon_hours":
                continue
            a = np.asarray(pd.to_numeric(left[name], errors="coerce"), dtype=np.float64)
            b = np.asarray(
                pd.to_numeric(right[name].reindex(left.index), errors="coerce"), dtype=np.float64
            )
            null_mismatch = np.isnan(a) != np.isnan(b)
            value_mismatch = ~np.isnan(a) & ~np.isnan(b) & (np.abs(a - b) > tolerance)
            bad = null_mismatch | value_mismatch
            if bad.any():
                report.mismatches[name] = report.mismatches.get(name, 0) + int(bad.sum())
                i = int(np.argmax(bad))
                report.examples.setdefault(
                    name, {"t": t.isoformat(), "offline": float(a[i]), "online": float(b[i])}
                )
    return report
