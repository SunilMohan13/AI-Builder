"""Worker throughput guards: detection debouncing and snapshot retention.

Detection is a whole-snapshot recompute. Running it per message is invisible
at replay volume and quadratic once live sources arrive, so these tests pin
the batching behaviour and the retention window that bounds the snapshot.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from aeropulse_contracts.observation import (
    Location,
    Measurement,
    Observation,
    Provenance,
    Quality,
)
from aeropulse_worker.main import DetectionTrigger, _start_consumer
from aeropulse_worker.pipeline import InMemoryRepository, process_air_quality

BASE_TIME = datetime(2026, 9, 8, 5, 15, tzinfo=UTC)


async def _no_sleep(_seconds: float) -> None:
    """Collapse backoff so retry tests stay fast."""
    return None


class FakeClock:
    """Monotonic clock the test advances by hand."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _obs(index: int, *, observed_at: datetime | None = None) -> Observation:
    when = observed_at or BASE_TIME
    return Observation(
        observation_id=f"obs_{index}",
        source_id="cpcb",
        source_record_id=f"DL{index:03d}_{when.isoformat()}_pm25",
        observed_at=when,
        received_at=when + timedelta(minutes=2),
        location=Location(lat=28.628, lon=77.241),
        measurement=Measurement(parameter="pm25", value=142.3, unit="ug/m3"),
        quality=Quality(quality_flag="valid", quality_score=1.0),
        provenance=Provenance(provider="CPCB", connector_version="1.0.0"),
    )


def test_no_sweep_when_nothing_pending() -> None:
    trigger = DetectionTrigger(interval_seconds=30.0, max_batch=500, clock=FakeClock())
    assert trigger.should_run() is False


def test_first_observation_sweeps_immediately() -> None:
    """A cold worker must not wait out the interval before its first sweep."""
    trigger = DetectionTrigger(interval_seconds=30.0, max_batch=500, clock=FakeClock())
    trigger.record()
    assert trigger.should_run() is True


def test_batch_threshold_forces_a_sweep_before_the_interval() -> None:
    clock = FakeClock()
    trigger = DetectionTrigger(interval_seconds=30.0, max_batch=5, clock=clock)
    trigger.record()
    trigger.mark_run()

    for _ in range(4):
        trigger.record()
    assert trigger.should_run() is False, "under the batch size and inside the interval"

    trigger.record()
    assert trigger.should_run() is True, "batch size reached"


def test_interval_elapsing_forces_a_sweep_below_the_batch_size() -> None:
    clock = FakeClock()
    trigger = DetectionTrigger(interval_seconds=30.0, max_batch=500, clock=clock)
    trigger.record()
    trigger.mark_run()

    trigger.record()
    assert trigger.should_run() is False

    clock.advance(30.0)
    assert trigger.should_run() is True


def test_mark_run_reports_and_clears_the_batch() -> None:
    trigger = DetectionTrigger(interval_seconds=30.0, max_batch=500, clock=FakeClock())
    for _ in range(7):
        trigger.record()

    assert trigger.mark_run() == 7
    assert trigger.pending == 0
    assert trigger.should_run() is False


def test_one_sweep_covers_a_whole_batch() -> None:
    """500 observations must cost one sweep, not 500."""
    clock = FakeClock()
    trigger = DetectionTrigger(interval_seconds=30.0, max_batch=500, clock=clock)
    sweeps = 0

    for _ in range(500):
        trigger.record()
        if trigger.should_run():
            trigger.mark_run()
            sweeps += 1

    assert sweeps == 1


def test_snapshot_evicts_observations_outside_the_retention_window() -> None:
    repo = InMemoryRepository(retention_hours=48)

    process_air_quality(_obs(1, observed_at=BASE_TIME), repo)
    assert len(repo.air_quality) == 1

    # Three days later: the first observation falls outside the window.
    process_air_quality(_obs(2, observed_at=BASE_TIME + timedelta(hours=72)), repo)
    assert len(repo.air_quality) == 1
    remaining = next(iter(repo.air_quality.values()))
    assert remaining.observation_id == "obs_2"


def test_snapshot_keeps_observations_inside_the_window() -> None:
    repo = InMemoryRepository(retention_hours=48)

    process_air_quality(_obs(1, observed_at=BASE_TIME), repo)
    process_air_quality(_obs(2, observed_at=BASE_TIME + timedelta(hours=24)), repo)

    assert len(repo.air_quality) == 2


def test_retention_is_measured_against_the_newest_observation_not_wall_clock() -> None:
    """A historical backfill must not evict itself the moment it arrives."""
    repo = InMemoryRepository(retention_hours=48)
    long_ago = datetime(2020, 1, 1, tzinfo=UTC)

    process_air_quality(_obs(1, observed_at=long_ago), repo)
    process_air_quality(_obs(2, observed_at=long_ago + timedelta(hours=1)), repo)

    assert len(repo.air_quality) == 2


def test_unbounded_repository_is_the_default_for_tests() -> None:
    repo = InMemoryRepository()

    process_air_quality(_obs(1, observed_at=BASE_TIME), repo)
    process_air_quality(_obs(2, observed_at=BASE_TIME + timedelta(days=400)), repo)

    assert len(repo.air_quality) == 2


class FlakyConsumer:
    """Fails ``start()`` a set number of times, then succeeds."""

    def __init__(self, failures: int) -> None:
        self.remaining_failures = failures
        self.attempts = 0

    async def start(self) -> None:
        self.attempts += 1
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise ConnectionError("broker not ready")


async def test_consumer_start_retries_until_the_broker_is_up(monkeypatch) -> None:
    """A cold `compose up` races the broker; the worker must wait, not die."""
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    consumer = FlakyConsumer(failures=3)

    await _start_consumer(consumer, attempts=10)

    assert consumer.attempts == 4


async def test_consumer_start_raises_after_exhausting_attempts(monkeypatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    consumer = FlakyConsumer(failures=99)

    with pytest.raises(ConnectionError):
        await _start_consumer(consumer, attempts=3)

    assert consumer.attempts == 3


async def test_consumer_start_does_not_sleep_when_the_broker_is_healthy(monkeypatch) -> None:
    slept: list[float] = []

    async def _record(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _record)
    consumer = FlakyConsumer(failures=0)

    await _start_consumer(consumer)

    assert consumer.attempts == 1
    assert slept == []
