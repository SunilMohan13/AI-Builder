"""Offline/online feature parity harness (integration plan Phase 2).

Training and serving already share one implementation
(:func:`aeropulse_intelligence.features.build_features`) and one feature list
(:mod:`aeropulse_contracts.feature_spec`), so the classic skew — two codebases
computing "the same" feature differently — cannot occur here. A second kind of
skew still can, and this module measures it.

Training materialises a grid-hour from a snapshot holding the *whole* window,
including observations recorded after that hour. Online inference only ever has
observations up to the current hour. Any feature whose value differs between
those two calls is either

* **leaking the future** into the training frame, if the offline value used
  later observations, or
* **unavailable online**, if the online value is null where the offline one was
  not,

and both make an offline metric a poor prediction of production accuracy. The
harness replays each grid-hour with a truncated snapshot and diffs the result
against the batch computation, so the failure is measured rather than assumed.

A tolerance is applied because rounding differs harmlessly at the last decimal;
a null appearing on only one side is always a mismatch regardless of tolerance.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from aeropulse_contracts.feature import GridFeature
from aeropulse_contracts.feature_spec import FEATURE_SETS, to_feature_dict
from aeropulse_contracts.meteo import MeteorologicalObservation
from aeropulse_contracts.observation import Observation
from aeropulse_geospatial.grid import to_grid_id
from aeropulse_intelligence.features import build_features, hour_bucket
from aeropulse_intelligence.snapshot import FeatureSnapshot

#: Absolute difference tolerated between an offline and an online value before
#: it counts as a mismatch. Set at the rounding precision the feature builder
#: itself uses (4 decimal places), so it forgives float noise and nothing else.
DEFAULT_TOLERANCE = 1e-4


@dataclass(frozen=True)
class FeatureDivergence:
    """One feature's disagreement between the batch and replayed paths.

    Attributes:
        feature: Feature name from the shared spec.
        compared: Grid-hours where the feature was compared.
        mismatches: Grid-hours whose values disagreed beyond tolerance.
        max_abs_diff: Largest absolute numeric difference observed.
        offline_only_nulls: Rows null offline but populated online.
        online_only_nulls: Rows populated offline but null online. These are
            the features a model would be trained on and then never receive.
        example: A representative disagreeing row, for triage.
    """

    feature: str
    compared: int
    mismatches: int
    max_abs_diff: float
    offline_only_nulls: int
    online_only_nulls: int
    example: dict[str, Any] | None = None

    @property
    def mismatch_rate(self) -> float:
        """Return the fraction of compared rows that disagreed."""
        return self.mismatches / self.compared if self.compared else 0.0


@dataclass
class ParityReport:
    """Result of comparing batch features against point-in-time replay.

    Attributes:
        rows_compared: Grid-hours evaluated on both paths.
        divergences: Per-feature results, worst first.
        tolerance: Absolute tolerance applied.
    """

    rows_compared: int
    divergences: list[FeatureDivergence] = field(default_factory=list)
    tolerance: float = DEFAULT_TOLERANCE

    @property
    def failing(self) -> list[FeatureDivergence]:
        """Return only the features that actually disagreed."""
        return [d for d in self.divergences if d.mismatches]

    @property
    def passed(self) -> bool:
        """Return True when no feature disagreed on any compared row."""
        return not self.failing

    def for_feature_sets(self) -> dict[str, list[str]]:
        """Map each model's feature set to the failing features it depends on.

        Returns:
            Model name to the sorted failing feature names it consumes. A
            model absent from the mapping is unaffected by this report.
        """
        failing = {d.feature for d in self.failing}
        affected: dict[str, list[str]] = {}
        for name, feature_set in FEATURE_SETS.items():
            hit = sorted(failing.intersection(feature_set.names))
            if hit:
                affected[name] = hit
        return affected

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary.

        Returns:
            Report contents including every divergence, failing or not.
        """
        return {
            "rows_compared": self.rows_compared,
            "tolerance": self.tolerance,
            "passed": self.passed,
            "failing_feature_count": len(self.failing),
            "affected_models": self.for_feature_sets(),
            "divergences": [
                {
                    "feature": d.feature,
                    "compared": d.compared,
                    "mismatches": d.mismatches,
                    "mismatch_rate": round(d.mismatch_rate, 6),
                    "max_abs_diff": d.max_abs_diff,
                    "offline_only_nulls": d.offline_only_nulls,
                    "online_only_nulls": d.online_only_nulls,
                    "example": d.example,
                }
                for d in self.divergences
            ],
        }


def _values_agree(offline: Any, online: Any, tolerance: float) -> tuple[bool, float]:
    """Compare two feature values.

    Args:
        offline: Value from the batch computation.
        online: Value from the point-in-time replay.
        tolerance: Absolute numeric tolerance.

    Returns:
        ``(agree, absolute_difference)``. The difference is 0.0 when either
        side is null, since a null mismatch is categorical rather than numeric.
    """
    if offline is None and online is None:
        return True, 0.0
    if offline is None or online is None:
        return False, 0.0
    diff = abs(float(offline) - float(online))
    return diff <= tolerance, diff


def _truncated_snapshot(base: FeatureSnapshot, cutoff: datetime) -> FeatureSnapshot:
    """Return the snapshot as it would have existed at ``cutoff``.

    Everything observed after the cutoff hour is dropped, which is precisely
    what the live path has available when it builds that hour's features.

    Args:
        base: Full snapshot.
        cutoff: Hour-floored timestamp being rebuilt, retained inclusively.

    Returns:
        A snapshot restricted to observations at or before ``cutoff``.
    """
    return FeatureSnapshot(
        air_quality=[o for o in base.air_quality if hour_bucket(o.observed_at) <= cutoff],
        weather=[w for w in base.weather if hour_bucket(w.observed_at) <= cutoff],
        fires=[f for f in base.fires if hour_bucket(f.observed_at) <= cutoff],
        rasters=[r for r in base.rasters if hour_bucket(r.acquisition_time) <= cutoff],
    )


def check_parity(
    air_quality: Iterable[Observation],
    weather: Iterable[MeteorologicalObservation],
    fires: Iterable[Any] = (),
    rasters: Iterable[Any] = (),
    *,
    sample: int | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
) -> ParityReport:
    """Compare batch-built features against point-in-time replay.

    Args:
        air_quality: Canonical air-quality observations.
        weather: Canonical meteorological observations.
        fires: Canonical fire observations.
        rasters: Canonical raster samples.
        sample: Evaluate at most this many grid-hours, taken evenly across the
            window so the sample is not biased toward its start. ``None``
            evaluates every grid-hour.
        tolerance: Absolute numeric tolerance.

    Returns:
        A :class:`ParityReport`. An empty observation set yields a report with
        zero rows compared, which :attr:`ParityReport.passed` reports as True —
        callers that need evidence must check ``rows_compared`` too.
    """
    aq = list(air_quality)
    for obs in aq:
        if obs.grid_id is None:
            obs.grid_id = to_grid_id(obs.location.lat, obs.location.lon)

    base = FeatureSnapshot(
        air_quality=aq,
        weather=list(weather),
        fires=list(fires),
        rasters=list(rasters),
    )

    targets = _target_grid_hours(aq)
    if sample is not None and 0 < sample < len(targets):
        step = len(targets) / sample
        targets = [targets[int(i * step)] for i in range(sample)]

    stats: dict[str, dict[str, Any]] = {}
    rows = 0
    for grid_id, lat, lon, hour in targets:
        offline = build_features(grid_id, hour, base, center_lat=lat, center_lon=lon)
        online = build_features(
            grid_id,
            hour,
            _truncated_snapshot(base, hour),
            center_lat=lat,
            center_lon=lon,
        )
        rows += 1
        _accumulate(stats, offline, online, grid_id, hour, tolerance)

    divergences = [
        FeatureDivergence(
            feature=name,
            compared=entry["compared"],
            mismatches=entry["mismatches"],
            max_abs_diff=round(entry["max_abs_diff"], 6),
            offline_only_nulls=entry["offline_only_nulls"],
            online_only_nulls=entry["online_only_nulls"],
            example=entry["example"],
        )
        for name, entry in stats.items()
    ]
    divergences.sort(key=lambda d: (-d.mismatches, d.feature))
    return ParityReport(rows_compared=rows, divergences=divergences, tolerance=tolerance)


def _target_grid_hours(
    observations: Sequence[Observation],
) -> list[tuple[str, float, float, datetime]]:
    """Return every observed grid-hour with its cell centroid.

    Args:
        observations: Air-quality observations with resolved grid ids.

    Returns:
        ``(grid_id, lat, lon, hour)`` sorted by cell then hour.
    """
    seen: dict[tuple[str, datetime], tuple[str, float, float, datetime]] = {}
    for obs in observations:
        grid_id = str(obs.grid_id)
        hour = hour_bucket(obs.observed_at)
        seen.setdefault((grid_id, hour), (grid_id, obs.location.lat, obs.location.lon, hour))
    return [seen[key] for key in sorted(seen)]


def _accumulate(
    stats: dict[str, dict[str, Any]],
    offline: GridFeature,
    online: GridFeature,
    grid_id: str,
    hour: datetime,
    tolerance: float,
) -> None:
    """Fold one grid-hour comparison into the running per-feature statistics.

    Args:
        stats: Mutable accumulator keyed by feature name.
        offline: Feature built from the full snapshot.
        online: Feature built from the truncated snapshot.
        grid_id: Cell being compared, recorded on the example row.
        hour: Hour being compared, recorded on the example row.
        tolerance: Absolute numeric tolerance.
    """
    offline_values = to_feature_dict(offline)
    online_values = to_feature_dict(online)
    for name, offline_value in offline_values.items():
        online_value = online_values.get(name)
        entry = stats.setdefault(
            name,
            {
                "compared": 0,
                "mismatches": 0,
                "max_abs_diff": 0.0,
                "offline_only_nulls": 0,
                "online_only_nulls": 0,
                "example": None,
            },
        )
        entry["compared"] += 1
        agree, diff = _values_agree(offline_value, online_value, tolerance)
        entry["max_abs_diff"] = max(entry["max_abs_diff"], diff)
        if agree:
            continue
        entry["mismatches"] += 1
        if offline_value is None:
            entry["offline_only_nulls"] += 1
        elif online_value is None:
            entry["online_only_nulls"] += 1
        if entry["example"] is None:
            entry["example"] = {
                "grid_id": grid_id,
                "timestamp": hour.isoformat(),
                "offline": offline_value,
                "online": online_value,
            }
