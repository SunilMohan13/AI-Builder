"""Connector scheduler: interval alignment, precedence, cold start."""

from pathlib import Path

from aeropulse_connector_app.scheduler import (
    FALLBACK_INTERVAL_SECONDS,
    Scheduler,
    SourceSchedule,
    load_schedules,
)


class FakeClock:
    """Epoch-seconds clock the test advances by hand."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _scheduler(*schedules: SourceSchedule, now: float = 0.0) -> tuple[Scheduler, FakeClock]:
    clock = FakeClock(now)
    return Scheduler(list(schedules), clock=clock), clock


# --- due set ---


def test_a_source_that_has_never_run_is_due_immediately() -> None:
    """A cold start must ingest now, not after a full interval."""
    scheduler, _ = _scheduler(SourceSchedule("openaq", 900))
    assert scheduler.due() == ["openaq"]


def test_a_source_is_not_due_again_inside_its_interval() -> None:
    scheduler, clock = _scheduler(SourceSchedule("openaq", 900), now=900.0)
    scheduler.record_run("openaq")

    clock.advance(600)
    assert scheduler.due() == []


def test_a_source_becomes_due_at_its_next_aligned_slot() -> None:
    scheduler, clock = _scheduler(SourceSchedule("openaq", 900), now=900.0)
    scheduler.record_run("openaq")

    clock.advance(900)
    assert scheduler.due() == ["openaq"]


def test_sources_with_different_cadences_come_due_independently() -> None:
    scheduler, clock = _scheduler(
        SourceSchedule("openaq", 900),
        SourceSchedule("openmeteo", 3600),
        now=3600.0,
    )
    scheduler.record_run("openaq")
    scheduler.record_run("openmeteo")

    clock.advance(900)
    assert scheduler.due() == ["openaq"]

    clock.advance(2700)
    assert set(scheduler.due()) == {"openaq", "openmeteo"}


# --- alignment ---


def test_next_run_lands_on_a_quarter_hour_boundary() -> None:
    """Upstreams publish hourly; aligned firing is why intervals beat cron here."""
    scheduler, _ = _scheduler(SourceSchedule("openaq", 900))
    # 10:07:00 -> 10:15:00
    assert scheduler.next_run_after("openaq", 36420.0) == 36900.0


def test_next_run_lands_on_the_hour_for_hourly_sources() -> None:
    scheduler, _ = _scheduler(SourceSchedule("openmeteo", 3600))
    assert scheduler.next_run_after("openmeteo", 36420.0) == 39600.0


def test_a_slow_cycle_does_not_drift_the_schedule() -> None:
    """Comparing against the slot boundary, not last+interval, prevents drift."""
    scheduler, clock = _scheduler(SourceSchedule("openaq", 900), now=900.0)
    # A cycle that overruns by 200s still leaves the next slot at 1800.
    scheduler.record_run("openaq", now=1100.0)

    clock.now = 1799.0
    assert scheduler.due() == []
    clock.now = 1800.0
    assert scheduler.due() == ["openaq"]


# --- sleep ---


def test_seconds_until_next_is_zero_when_something_is_due() -> None:
    scheduler, _ = _scheduler(SourceSchedule("openaq", 900))
    assert scheduler.seconds_until_next() == 0.0


def test_seconds_until_next_reports_the_soonest_source() -> None:
    scheduler, clock = _scheduler(
        SourceSchedule("openaq", 900),
        SourceSchedule("modis", 86400),
        now=900.0,
    )
    scheduler.record_run("openaq")
    scheduler.record_run("modis")

    clock.advance(100)
    assert scheduler.seconds_until_next() == 800.0


# --- config precedence ---


def test_registry_interval_wins_over_connector_metadata(tmp_path: Path) -> None:
    config = tmp_path / "sources.yaml"
    config.write_text("sources:\n  - {id: openaq, enabled: true, interval_seconds: 300}\n")

    schedules = load_schedules(config, source_ids=["openaq"], metadata_intervals={"openaq": 900})

    assert schedules[0].interval_seconds == 300


def test_connector_metadata_is_used_when_the_registry_is_silent(tmp_path: Path) -> None:
    config = tmp_path / "sources.yaml"
    config.write_text("sources:\n  - {id: openaq, enabled: true}\n")

    schedules = load_schedules(config, source_ids=["openaq"], metadata_intervals={"openaq": 900})

    assert schedules[0].interval_seconds == 900


def test_platform_default_is_the_last_resort(tmp_path: Path) -> None:
    config = tmp_path / "sources.yaml"
    config.write_text("sources:\n  - {id: openaq, enabled: true}\n")

    schedules = load_schedules(config, source_ids=["openaq"])

    assert schedules[0].interval_seconds == FALLBACK_INTERVAL_SECONDS


def test_disabled_sources_are_never_scheduled(tmp_path: Path) -> None:
    config = tmp_path / "sources.yaml"
    config.write_text(
        "sources:\n"
        "  - {id: openaq, enabled: true, interval_seconds: 900}\n"
        "  - {id: imd, enabled: false, interval_seconds: 3600}\n"
    )

    schedules = load_schedules(config, source_ids=["openaq", "imd"])

    assert [s.source_id for s in schedules] == ["openaq"]


def test_an_unreadable_registry_still_schedules_everything(tmp_path: Path) -> None:
    """A missing config must not silently stop ingestion."""
    schedules = load_schedules(tmp_path / "does-not-exist.yaml", source_ids=["openaq", "firms"])
    assert {s.source_id for s in schedules} == {"openaq", "firms"}


def test_the_real_registry_disables_imd_and_schedules_openaq() -> None:
    """IMD is fixture-only by decision; OpenAQ carries live ground truth."""
    schedules = load_schedules(
        Path("config/sources.yaml"),
        source_ids=["openaq", "openmeteo", "firms", "imd"],
    )
    scheduled = {s.source_id for s in schedules}
    assert "imd" not in scheduled
    assert {"openaq", "openmeteo", "firms"} <= scheduled
