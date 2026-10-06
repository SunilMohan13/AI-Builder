"""Interval scheduler for the connector process.

The repo had two competing schedule declarations and honoured neither:
``config/sources.yaml`` carried cron strings while every connector's
``metadata.yaml`` carried ``{mode: interval, interval_seconds: N}``. This
converges on intervals and computes phase alignment arithmetically, which
buys cron's one real benefit — firing on the hour, which matters because
upstreams publish hourly — without a parser or a second vocabulary.

    next_run = ceil(now / interval) * interval

For 900 and 3600 that lands exactly on :00/:15/:30/:45.

The class is pure and takes an injected clock so its behaviour is testable
without sleeping, mirroring ``RateLimiter``.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Any

import yaml
from aeropulse_observability.logging import get_logger

logger = get_logger("aeropulse.connector.scheduler")

#: Used when neither the registry nor a connector's metadata says otherwise.
FALLBACK_INTERVAL_SECONDS = 3600


@dataclass(frozen=True)
class SourceSchedule:
    """How often one source should run.

    Attributes:
        source_id: Registry id.
        interval_seconds: Seconds between runs.
    """

    source_id: str
    interval_seconds: int


class Scheduler:
    """Decides which sources are due, and how long to sleep.

    Args:
        schedules: Per-source cadence.
        clock: Epoch-seconds source, injected for tests.
    """

    def __init__(
        self,
        schedules: list[SourceSchedule],
        *,
        clock: Callable[[], float] = time,
    ) -> None:
        self._schedules = {s.source_id: s for s in schedules}
        self._clock = clock
        self._last_run: dict[str, float] = {}

    @property
    def source_ids(self) -> list[str]:
        """Every scheduled source id."""
        return list(self._schedules)

    def interval_for(self, source_id: str) -> int:
        """Return a source's cadence in seconds."""
        schedule = self._schedules.get(source_id)
        return schedule.interval_seconds if schedule else FALLBACK_INTERVAL_SECONDS

    def next_run_after(self, source_id: str, now: float) -> float:
        """Return the next aligned firing time at or after ``now``."""
        interval = self.interval_for(source_id)
        return math.ceil(now / interval) * interval

    def due(self, now: float | None = None) -> list[str]:
        """Return the sources whose aligned slot has arrived.

        A source that has never run is due immediately, so a cold start does
        not wait out a full interval before ingesting anything.
        """
        moment = self._clock() if now is None else now
        ready: list[str] = []
        for source_id in self._schedules:
            last = self._last_run.get(source_id)
            if last is None:
                ready.append(source_id)
                continue
            interval = self.interval_for(source_id)
            # Compare against the aligned slot boundary rather than
            # last + interval, so runs stay on :00/:15/:30/:45 instead of
            # drifting by however long each cycle took.
            if moment >= math.floor(last / interval) * interval + interval:
                ready.append(source_id)
        return ready

    def record_run(self, source_id: str, now: float | None = None) -> None:
        """Note that a source just ran."""
        self._last_run[source_id] = self._clock() if now is None else now

    def seconds_until_next(self, now: float | None = None) -> float:
        """Return how long to sleep before any source is next due.

        Returns:
            Seconds to wait; ``0.0`` when something is already due.
        """
        moment = self._clock() if now is None else now
        if self.due(moment):
            return 0.0
        waits: list[float] = []
        for source_id in self._schedules:
            last = self._last_run.get(source_id)
            interval = self.interval_for(source_id)
            boundary = (
                self.next_run_after(source_id, moment)
                if last is None
                else math.floor(last / interval) * interval + interval
            )
            waits.append(max(0.0, boundary - moment))
        return min(waits) if waits else float(FALLBACK_INTERVAL_SECONDS)


def load_schedules(
    config_path: Path,
    *,
    source_ids: list[str],
    default_interval_seconds: int = FALLBACK_INTERVAL_SECONDS,
    metadata_intervals: dict[str, int] | None = None,
) -> list[SourceSchedule]:
    """Build schedules for the enabled sources.

    Precedence is registry -> connector metadata -> platform default, so an
    operator can retune one source without editing its package.

    Args:
        config_path: Path to `config/sources.yaml`.
        source_ids: Sources the runner knows how to build.
        default_interval_seconds: Platform-wide fallback.
        metadata_intervals: Per-source cadence declared in connector
            ``metadata.yaml``.

    Returns:
        One schedule per enabled, buildable source.
    """
    metadata_intervals = metadata_intervals or {}
    try:
        raw = yaml.safe_load(config_path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("scheduler.config_unreadable", path=str(config_path), error=str(exc))
        raw = None

    entries: dict[str, dict[str, Any]] = {}
    sources = (raw or {}).get("sources")
    if isinstance(sources, list):
        for entry in sources:
            if isinstance(entry, dict) and "id" in entry:
                entries[str(entry["id"])] = entry

    schedules: list[SourceSchedule] = []
    for source_id in source_ids:
        entry = entries.get(source_id)
        # An unreadable or silent registry must not stop ingestion, so a
        # source missing from it is treated as enabled.
        if entry is not None and not entry.get("enabled", True):
            continue
        interval = None
        if entry is not None:
            interval = entry.get("interval_seconds")
        if interval is None:
            interval = metadata_intervals.get(source_id)
        if interval is None:
            interval = default_interval_seconds
        schedules.append(SourceSchedule(source_id, max(1, int(interval))))
    return schedules
