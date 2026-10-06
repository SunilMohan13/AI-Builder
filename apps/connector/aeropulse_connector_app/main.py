"""Connector process entrypoint: a scheduled ingestion loop.

This used to run one replay cycle and exit, with ``restart: "no"`` in Compose
to match. Live sources need a cadence, so the process now stays up and runs
each source on its own interval until it is asked to stop.

There is deliberately no stdout publishing fallback. It published to nothing
that any consumer read, and in live mode it would burn a source's rate budget
producing records nobody stored. If the broker is unreachable the cycle is
skipped and retried, which is visible; silently generating orphaned output is
not.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import signal
from pathlib import Path

from aeropulse_common.settings import get_settings
from aeropulse_contracts.envelope import KafkaEnvelope, ProcessingMode
from aeropulse_observability.logging import configure_logging, get_logger
from aeropulse_observability.telemetry import configure_telemetry

from aeropulse_connector_app.registry import SOURCE_SPECS, SPECS_BY_ID
from aeropulse_connector_app.runner import DEFAULT_SOURCES_CONFIG, run_cycle
from aeropulse_connector_app.scheduler import Scheduler, load_schedules

logger = get_logger("aeropulse.connector")

#: Bound on a single cycle so one slow upstream cannot stall the loop forever.
CYCLE_TIMEOUT_SECONDS = 600.0


def _fixtures_root() -> Path:
    """Resolve the fixtures directory inside the image or the working tree.

    ``SourceSpec.fixture_rel`` is ``cpcb/stations.json``, so this must be the
    ``fixtures/`` directory itself, not its parent. ``/app/fixtures`` exists
    in the image because the Dockerfile copies that tree there.
    """
    image = Path("/app/fixtures")
    if image.is_dir():
        return image
    local = Path.cwd() / "fixtures"
    if local.is_dir():
        return local
    return Path.cwd()


def _metadata_intervals() -> dict[str, int]:
    """Read each connector's declared cadence from its own metadata."""
    intervals: dict[str, int] = {}
    for spec in SOURCE_SPECS:
        try:
            metadata = spec.factory(None).metadata()
        except Exception:
            continue
        schedule = getattr(metadata, "schedule", None)
        if isinstance(schedule, dict):
            value = schedule.get("interval_seconds")
            if isinstance(value, int) and value > 0:
                intervals[spec.source_id] = value
    return intervals


class KafkaPublisher:
    """Streams envelopes to Kafka, holding one producer for the process.

    The previous implementation started a producer per cycle and buffered
    every envelope in a list before sending. At live volume that buffer is
    thousands of records held for no reason.
    """

    def __init__(self, bootstrap: str) -> None:
        self._bootstrap = bootstrap
        self._producer = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        """Create and start the shared producer."""
        from aiokafka import AIOKafkaProducer

        self._loop = asyncio.get_running_loop()
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            acks="all",
        )
        await self._producer.start()

    async def stop(self) -> None:
        """Flush and close the producer."""
        if self._producer is None:
            return
        with contextlib.suppress(Exception):
            await self._producer.flush()
        with contextlib.suppress(Exception):
            await self._producer.stop()
        self._producer = None

    def publish(self, topic: str, envelope: KafkaEnvelope) -> None:
        """Send one envelope. Called synchronously from the runner."""
        if self._producer is None or self._loop is None:
            raise RuntimeError("publisher not started")
        future = asyncio.run_coroutine_threadsafe(
            self._producer.send_and_wait(topic, envelope.model_dump(mode="json")),
            self._loop,
        )
        future.result()


def _stdout_publish(topic: str, envelope: KafkaEnvelope) -> None:
    """Print an envelope instead of publishing it.

    Only reachable through the explicit ``AEROPULSE_CONNECTOR_PUBLISH=stdout``
    dry-run switch, never as a failure fallback.
    """
    print(json.dumps({"topic": topic, "envelope": envelope.model_dump(mode="json")}))


async def _run_once(publish, fixtures_root: Path, source_ids: list[str]) -> None:
    """Run one cycle for the given sources, off the event loop thread."""
    specs = tuple(SPECS_BY_ID[s] for s in source_ids if s in SPECS_BY_ID)
    if not specs:
        return
    result = await asyncio.to_thread(
        run_cycle,
        fixtures_root,
        publish,
        processing_mode=ProcessingMode.LIVE,
        sources_config=DEFAULT_SOURCES_CONFIG,
        specs=specs,
    )
    for run in result.runs:
        logger.info(
            "connector.source.completed",
            source_id=run.source_id,
            status=run.status.value,
            records=run.records,
            mode=run.mode,
            latency_ms=run.latency_ms,
            error=run.error,
        )


async def _loop(stop: asyncio.Event) -> None:
    settings = get_settings()
    fixtures_root = _fixtures_root()
    scheduler = Scheduler(
        load_schedules(
            DEFAULT_SOURCES_CONFIG,
            source_ids=[spec.source_id for spec in SOURCE_SPECS],
            default_interval_seconds=settings.connector_default_interval_seconds,
            metadata_intervals=_metadata_intervals(),
        )
    )
    logger.info(
        "connector.scheduler.ready",
        sources=len(scheduler.source_ids),
        mode=settings.connector_mode,
    )

    dry_run = getattr(settings, "connector_publish", "kafka") == "stdout"
    publisher = None if dry_run else KafkaPublisher(settings.kafka_bootstrap_servers)

    try:
        while not stop.is_set():
            due = scheduler.due()
            if due:
                if publisher is not None and publisher._producer is None:
                    try:
                        await publisher.start()
                    except Exception as exc:
                        # Skip the cycle rather than emit orphaned records.
                        logger.error("connector.kafka.unavailable", error=str(exc))
                        await _sleep_or_stop(stop, 30.0)
                        continue
                publish = _stdout_publish if publisher is None else publisher.publish
                try:
                    await asyncio.wait_for(
                        _run_once(publish, fixtures_root, due),
                        timeout=CYCLE_TIMEOUT_SECONDS,
                    )
                except TimeoutError:
                    logger.error("connector.cycle.timeout", sources=due)
                except Exception:
                    logger.exception("connector.cycle.failed", sources=due)
                for source_id in due:
                    scheduler.record_run(source_id)

            if stop.is_set():
                break
            await _sleep_or_stop(stop, max(1.0, scheduler.seconds_until_next()))
    finally:
        if publisher is not None:
            await publisher.stop()
        logger.info("connector.stopped")


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    """Wait, but wake immediately on shutdown."""
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


async def _amain() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    await _loop(stop)


def main() -> None:
    """Run the scheduled ingestion loop until signalled to stop."""
    settings = get_settings()
    settings.service_name = "aeropulse-connector"  # type: ignore[misc]
    configure_logging(settings)
    configure_telemetry(settings)
    logger.info("connector.starting", mode=settings.connector_mode)
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
