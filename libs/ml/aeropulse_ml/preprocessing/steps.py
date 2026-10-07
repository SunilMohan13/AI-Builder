"""Preprocessing steps shared by the cycle, training and replay.

Each step is a pure function of ``(batch, context)``: it returns a new batch
and a count of what it dropped, by reason. Steps that touch time have leak
tests in ``tests/unit/test_preprocessing.py``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Protocol, TypeVar

from aeropulse_common.hashing import dedup_key
from aeropulse_connector_sdk.quality import QualityResult, evaluate_observation
from aeropulse_contracts import (
    CanonicalRecord,
    FireObservation,
    MeteoForecast,
    MeteorologicalObservation,
    Observation,
    ProvenanceClass,
    RasterObservation,
)
from aeropulse_geospatial import to_grid_id

from aeropulse_ml.preprocessing.batch import PreprocessContext, RecordBatch

R = TypeVar("R", bound=CanonicalRecord)
StepOutput = tuple[RecordBatch, Counter[str]]


class PreprocessingStep(Protocol):
    name: str

    def apply(self, batch: RecordBatch, context: PreprocessContext) -> StepOutput: ...


def _keep(
    records: Sequence[R], verdict: Callable[[R], str | None], dropped: Counter[str]
) -> tuple[R, ...]:
    """Keep records whose verdict is ``None``; count the rest by reason."""
    kept: list[R] = []
    for record in records:
        reason = verdict(record)
        if reason is None:
            kept.append(record)
        else:
            dropped[reason] += 1
    return tuple(kept)


# --- quality control -------------------------------------------------------


def _with_quality(record: R, qc: QualityResult) -> R:
    quality = record.quality.model_copy(
        update={"quality_flag": qc.quality_flag, "quality_score": qc.quality_score}
    )
    return record.model_copy(update={"quality": quality})


class QualityControl:
    """Score point records with the connector SDK's rules; drop ``invalid``.

    The same rules the worker applied on the live path, now applied once for
    every consumer. ``suspect`` records are kept with their score.
    """

    name = "quality_control"

    def apply(self, batch: RecordBatch, context: PreprocessContext) -> StepOutput:
        dropped: Counter[str] = Counter()
        observations = _qc(
            batch.observations, lambda o: (o.measurement.parameter, o.measurement.value), dropped
        )
        fires = _qc(batch.fires, lambda f: ("frp", f.fire.frp), dropped)
        weather = _qc(
            batch.weather,
            lambda w: ("humidity", w.humidity) if w.humidity is not None else ("weather", 0.0),
            dropped,
        )
        return batch.with_(observations=observations, fires=fires, weather=weather), dropped


P = TypeVar("P", Observation, FireObservation, MeteorologicalObservation)


def _qc(
    records: Sequence[P], measure: Callable[[P], tuple[str, float]], dropped: Counter[str]
) -> tuple[P, ...]:
    out: list[P] = []
    for record in records:
        if record.quality.quality_flag == "invalid":
            dropped["qc:flagged_invalid_upstream"] += 1
            continue
        parameter, value = measure(record)
        qc = evaluate_observation(
            parameter=parameter,
            value=value,
            lat=record.location.lat,
            lon=record.location.lon,
            observed_at=record.observed_at,
            received_at=record.received_at,
        )
        if qc.quality_flag == "invalid":
            dropped[f"qc:{qc.reasons[0] if qc.reasons else 'invalid'}"] += 1
            continue
        out.append(_with_quality(record, qc))
    return tuple(out)


# --- region ----------------------------------------------------------------


class RegionFilter:
    """Drop records stamped with another region, or unstamped in a region run."""

    name = "region_filter"

    def apply(self, batch: RecordBatch, context: PreprocessContext) -> StepOutput:
        dropped: Counter[str] = Counter()
        if context.region_id is None:
            return batch, dropped

        def verdict(record: CanonicalRecord) -> str | None:
            if record.region_id is None:
                return "region:unstamped"
            if record.region_id != context.region_id:
                return "region:other_region"
            return None

        return _map_all(batch, verdict, dropped), dropped


def _map_all(
    batch: RecordBatch, verdict: Callable[[CanonicalRecord], str | None], dropped: Counter[str]
) -> RecordBatch:
    return RecordBatch(
        observations=_keep(batch.observations, verdict, dropped),
        weather=_keep(batch.weather, verdict, dropped),
        forecasts=_keep(batch.forecasts, verdict, dropped),
        fires=_keep(batch.fires, verdict, dropped),
        rasters=_keep(batch.rasters, verdict, dropped),
    )


# --- time: the leak rules --------------------------------------------------


def known_at(record: CanonicalRecord) -> datetime:
    """When ``record`` became knowable.

    Point records: when observed. Forecasts: when issued (``valid_at`` may be
    later; that is the point of a forecast). Rasters: when processed, since a
    daily product exists only after its processing run.
    """
    if isinstance(record, MeteoForecast):
        return record.issued_at
    if isinstance(record, RasterObservation):
        return record.processing_time
    return record.observed_at


class AsOfCutoff:
    """Drop everything not knowable at ``context.as_of`` (LLD 7.3).

    No-op when ``as_of`` is ``None``: in training the feature pipeline applies
    the same cut-off per row, because each row has its own ``t``.
    """

    name = "as_of_cutoff"

    def apply(self, batch: RecordBatch, context: PreprocessContext) -> StepOutput:
        dropped: Counter[str] = Counter()
        as_of = context.as_of
        if as_of is None:
            return batch, dropped

        def verdict(record: CanonicalRecord) -> str | None:
            if known_at(record) <= as_of:
                return None
            if isinstance(record, MeteoForecast):
                return "leak:forecast_issued_after_as_of"
            if isinstance(record, RasterObservation):
                return "leak:raster_processed_after_as_of"
            return "leak:observed_after_as_of"

        return _map_all(batch, verdict, dropped), dropped


class LatestForecastIssue:
    """For each (source, site, valid hour) keep the latest issue ``<= as_of``.

    Must run after :class:`AsOfCutoff`. No-op in training (``as_of is None``):
    picking the latest issue over the whole history would hand an early row a
    forecast issued after it.
    """

    name = "latest_forecast_issue"

    def apply(self, batch: RecordBatch, context: PreprocessContext) -> StepOutput:
        dropped: Counter[str] = Counter()
        if context.as_of is None:
            return batch, dropped
        best: dict[tuple[str, str, datetime], MeteoForecast] = {}
        for forecast in batch.forecasts:
            key = (forecast.source_id, forecast.site_id, forecast.valid_at)
            current = best.get(key)
            if current is None or forecast.issued_at > current.issued_at:
                if current is not None:
                    dropped["forecast:superseded_issue"] += 1
                best[key] = forecast
            else:
                dropped["forecast:superseded_issue"] += 1
        kept = tuple(f for f in batch.forecasts if best[(f.source_id, f.site_id, f.valid_at)] is f)
        return batch.with_(forecasts=kept), dropped


# --- dedup -----------------------------------------------------------------


def identity(record: CanonicalRecord) -> str:
    """Canonical identity; matches the ingest pipeline's dedup key."""
    if isinstance(record, RasterObservation):
        return f"raster|{record.source_id}|{record.source_record_id}"
    if isinstance(record, MeteoForecast):
        return (
            f"forecast|{record.source_id}|{record.site_id}|"
            f"{record.issued_at.isoformat()}|{record.valid_at.isoformat()}"
        )
    if record.dedup_key:
        return record.dedup_key
    if isinstance(record, Observation):
        parameter = record.measurement.parameter
    elif isinstance(record, FireObservation):
        parameter = "frp"
    else:
        parameter = record.parameter
    return dedup_key(
        record.source_id, record.source_record_id, record.observed_at.isoformat(), parameter
    )


def _dedup(records: Sequence[R], dropped: Counter[str]) -> tuple[R, ...]:
    best: dict[str, int] = {}
    for index, record in enumerate(records):
        key = identity(record)
        kept = best.get(key)
        if kept is None:
            best[key] = index
            continue
        dropped["dedup:duplicate"] += 1
        if record.quality.quality_score > records[kept].quality.quality_score:
            best[key] = index
    chosen = sorted(best.values())
    return tuple(records[i] for i in chosen)


class Deduplicate:
    """One record per identity; the higher quality score wins, then the first seen."""

    name = "deduplicate"

    def apply(self, batch: RecordBatch, context: PreprocessContext) -> StepOutput:
        dropped: Counter[str] = Counter()
        return (
            RecordBatch(
                observations=_dedup(batch.observations, dropped),
                weather=_dedup(batch.weather, dropped),
                forecasts=_dedup(batch.forecasts, dropped),
                fires=_dedup(batch.fires, dropped),
                rasters=_dedup(batch.rasters, dropped),
            ),
            dropped,
        )


# --- provenance precedence -------------------------------------------------


def hour_ending(moment: datetime) -> datetime:
    """The hour bucket ``(tau - 1h, tau]`` that ``moment`` falls in, as ``tau``.

    Hour-ending buckets keep a bucket's value knowable at ``tau``: every record
    in it was observed at or before ``tau``.
    """
    floor = moment.replace(minute=0, second=0, microsecond=0)
    return floor if floor == moment else floor + timedelta(hours=1)


class StationsOutrankModel:
    """Ground stations outrank model-derived values for the same cell-hour.

    For each (H3 cell, hour-ending bucket, parameter) with at least one
    station measurement, model-derived values (CAMS via Open-Meteo) are
    dropped. Elsewhere they stay, labelled ``model_derived``.

    A display step, not a shared one: CAMS stays a model *feature* at
    station cells, so the feature pipeline must still see it there.
    """

    name = "stations_outrank_model"

    def apply(self, batch: RecordBatch, context: PreprocessContext) -> StepOutput:
        dropped: Counter[str] = Counter()

        def key(o: Observation) -> tuple[str, datetime, str]:
            cell = o.grid_id or to_grid_id(o.location.lat, o.location.lon)
            return cell, hour_ending(o.observed_at), o.measurement.parameter

        def is_station(o: Observation) -> bool:
            if context.is_model_derived(o):
                return False
            return o.provenance.provenance_class in (ProvenanceClass.MEASURED, None)

        covered = {key(o) for o in batch.observations if is_station(o)}

        def verdict(o: Observation) -> str | None:
            if context.is_model_derived(o) and key(o) in covered:
                return "precedence:outranked_by_station"
            return None

        return batch.with_(observations=_keep(batch.observations, verdict, dropped)), dropped


# --- labels ----------------------------------------------------------------


def label_observations(
    batch: RecordBatch, context: PreprocessContext, *, parameter: str = "pm25"
) -> tuple[Observation, ...]:
    """Observations allowed to be labels: ground-truth stations only.

    CAMS-derived values are features, never labels (AGENTS.md).
    """
    return tuple(
        o
        for o in batch.observations
        if o.measurement.parameter == parameter and context.is_ground_truth(o)
    )
