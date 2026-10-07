"""Deterministic event detection as a cycle stage (no language model here).

The rules are the intelligence library's, unchanged. The cycle adds what the
long-lived worker used to hold in memory: open events from the previous
snapshot, and each cell's PM2.5 history so the anomaly score has a baseline.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from aeropulse_contracts import Alert, EventStatus, PollutionEvent, RegionSnapshot
from aeropulse_intelligence.detect import process_snapshot
from aeropulse_intelligence.engine import EventStore, IdFactory
from aeropulse_intelligence.snapshot import FeatureSnapshot
from aeropulse_ml.preprocessing.batch import RecordBatch

#: Settings: a cell whose newest PM2.5 is older than this is not evaluated.
DETECTION_MAX_AGE_HOURS = 3
CLOSED = frozenset({EventStatus.RESOLVED, EventStatus.REJECTED})


@dataclass
class DetectionResult:
    events: list[PollutionEvent] = field(default_factory=list)
    changed: list[PollutionEvent] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    store: EventStore = field(default_factory=EventStore)


def cycle_ids(region_id: str, cycle_time: datetime) -> IdFactory:
    """Ids derived from what they name, so a re-run of the cycle reproduces them."""
    stamp = cycle_time.isoformat()

    def make(prefix: str, key: str) -> str:
        digest = hashlib.sha256(f"{region_id}|{stamp}|{prefix}|{key}".encode()).hexdigest()
        return f"{prefix}_{digest[:24]}"

    return make


def seed_store(
    previous: RegionSnapshot | None,
    *,
    region_id: str | None = None,
    cycle_time: datetime | None = None,
) -> EventStore:
    """An event store holding the previous cycle's still-open events.

    With ``region_id`` and ``cycle_time`` the store stamps new events at the
    cycle time and gives them content-derived ids.
    """
    if region_id is not None and cycle_time is not None:
        store = EventStore(clock=lambda: cycle_time, ids=cycle_ids(region_id, cycle_time))
    else:
        store = EventStore()
    if previous is None:
        return store
    for event in previous.events:
        if event.status in CLOSED:
            continue
        copy = event.model_copy(deep=True)
        store.events[copy.event_id] = copy
        for grid_id in copy.grid_ids:
            store.open_by_grid[grid_id] = copy.event_id
    return store


def detect(
    batch: RecordBatch,
    *,
    cycle_time: datetime,
    previous: RegionSnapshot | None,
    model_derived_sources: Iterable[str],
    region_id: str | None = None,
) -> DetectionResult:
    """Score every fresh cell and update events; ``batch`` is preprocessed at ``cycle_time``."""
    pm25 = [o for o in batch.observations if o.measurement.parameter == "pm25"]
    newest: dict[str, datetime] = {}
    for obs in pm25:
        if obs.grid_id is not None:
            newest[obs.grid_id] = max(newest.get(obs.grid_id, obs.observed_at), obs.observed_at)
    oldest = cycle_time - timedelta(hours=DETECTION_MAX_AGE_HOURS)
    fresh = {cell for cell, seen in newest.items() if seen > oldest}
    snapshot = FeatureSnapshot(
        air_quality=[
            o.model_copy()
            for o in batch.observations
            if o.grid_id in fresh or o.measurement.parameter != "pm25"
        ],
        fires=list(batch.fires),
        weather=list(batch.weather),
        rasters=list(batch.rasters),
        generated_at=cycle_time,
    )
    store = seed_store(previous, region_id=region_id, cycle_time=cycle_time)
    changed = process_snapshot(
        snapshot,
        store,
        history_by_grid=_history(snapshot, fresh),
        model_derived_sources=model_derived_sources,
    )
    return DetectionResult(
        events=sorted(store.events.values(), key=lambda e: e.event_id),
        changed=changed,
        alerts=sorted(store.alerts.values(), key=lambda a: a.alert_id),
        store=store,
    )


def _history(snapshot: FeatureSnapshot, cells: set[str]) -> dict[str, list[float]]:
    """Each cell's hourly PM2.5 before its newest hour, oldest first."""
    out: dict[str, list[float]] = {}
    for cell in cells:
        series = snapshot.pm25_history(cell)
        if len(series) < 2:
            continue
        hours = sorted(series)[:-1]
        out[cell] = [series[h] for h in hours]
    return out
