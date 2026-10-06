"""Worker entrypoint: consume Kafka envelopes and persist observations.

When Kafka is unavailable the process still starts and logs readiness failures.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
import time
from typing import Any

from aeropulse_common.settings import get_settings
from aeropulse_common.topics import (
    OBSERVATION_AQ,
    OBSERVATION_FIRE,
    OBSERVATION_RASTER,
    OBSERVATION_WEATHER,
)
from aeropulse_contracts.fire import FireObservation
from aeropulse_contracts.meteo import MeteorologicalObservation
from aeropulse_contracts.observation import Observation
from aeropulse_contracts.raster import RasterObservation
from aeropulse_observability.logging import bind_context, configure_logging, get_logger
from aeropulse_observability.metrics import (
    MODEL_FEATURE_COMPLETENESS,
    SHADOW_PREDICTIONS,
)
from aeropulse_observability.telemetry import configure_telemetry

from aeropulse_worker.pipeline import (
    InMemoryRepository,
    ObservationRepository,
    process_air_quality,
    process_fire,
    process_weather,
    run_detection,
)

logger = get_logger("aeropulse.worker")

#: Challenger scorer, warmed once at start. Module-level because it holds
#: deserialised model bundles: rebuilding it per message would pay the 1.3 s
#: cold-load cost on every snapshot. None until `_init_shadow_scorer` runs,
#: and left as None when no challenger is registered, which is the normal
#: case and must not be treated as an error.
_SHADOW_SCORER: Any | None = None


def _init_shadow_scorer() -> Any | None:
    """Build and warm the shadow scorer, or return None if unavailable.

    Shadow scoring is strictly additive observability. Any failure to set it
    up is logged and swallowed, because a worker that refuses to ingest
    observations over a challenger it was only going to record is a far worse
    outcome than having no shadow rows.

    Returns:
        A warmed ``ShadowScorer``, or None when none could be built.
    """
    try:
        from aeropulse_ml.registry import ModelRegistry
        from aeropulse_ml.shadow import ShadowScorer

        scorer = ShadowScorer(ModelRegistry())
        errors = scorer.warm()
        if errors:
            logger.warning("worker.shadow.load_errors", **errors)
        challengers = scorer.challengers
        if challengers:
            logger.info("worker.shadow.warmed", **challengers)
        else:
            logger.info("worker.shadow.no_challengers")
        return scorer
    except Exception:
        logger.exception("worker.shadow.unavailable")
        return None


class DetectionTrigger:
    """Decides when a detection sweep is worth running.

    ``run_detection`` rebuilds a ``FeatureSnapshot`` over the entire in-memory
    repository, so its cost scales with the snapshot, not with the message
    that triggered it. Running it per message was invisible at ~20 records per
    replay cycle and is quadratic once live sources arrive. Detection is a
    pure recompute, so one sweep per batch produces the same answer as one
    sweep per message.
    """

    def __init__(self, *, interval_seconds: float, max_batch: int, clock: Any = None) -> None:
        """Create a trigger.

        Args:
            interval_seconds: Minimum wall-clock gap between sweeps.
            max_batch: Force a sweep after this many pending observations.
            clock: Monotonic time source, injected for tests.
        """
        self._interval = interval_seconds
        self._max_batch = max_batch
        self._clock = clock or time.monotonic
        self._pending = 0
        self._last_run: float | None = None

    def record(self) -> None:
        """Note one newly persisted observation."""
        self._pending += 1

    def should_run(self) -> bool:
        """True when either the batch or the interval threshold is reached."""
        if self._pending == 0:
            return False
        if self._pending >= self._max_batch:
            return True
        if self._last_run is None:
            return True
        return (self._clock() - self._last_run) >= self._interval

    def mark_run(self) -> int:
        """Reset the batch counter and report how many observations it covered."""
        covered = self._pending
        self._pending = 0
        self._last_run = self._clock()
        return covered

    @property
    def pending(self) -> int:
        """Observations persisted since the last sweep."""
        return self._pending


async def _start_consumer(consumer: Any, *, attempts: int = 30) -> None:
    """Start a Kafka consumer, retrying while the broker comes up.

    The worker previously died on the first failed ``start()``, which under
    ``restart: unless-stopped`` turned a broker blip into a crash loop and,
    on a cold ``compose up``, a race the worker usually lost.

    Args:
        consumer: An ``AIOKafkaConsumer``.
        attempts: Maximum attempts before giving up.

    Raises:
        Exception: The final failure, when every attempt is exhausted.
    """
    delay = 1.0
    for attempt in range(1, attempts + 1):
        try:
            await consumer.start()
            return
        except Exception as exc:
            if attempt == attempts:
                logger.error("worker.kafka.unavailable", attempts=attempts, error=str(exc))
                raise
            logger.warning(
                "worker.kafka.retry", attempt=attempt, delay_seconds=round(delay, 2), error=str(exc)
            )
            await asyncio.sleep(delay + random.uniform(0, 0.5))
            delay = min(delay * 2, 30.0)


def _repository() -> ObservationRepository:
    """Prefer Timescale; fall back to in-memory if the database is down."""
    settings = get_settings()
    try:
        import psycopg

        from aeropulse_worker.db import TimescaleRepository

        if not settings.database_url:
            return InMemoryRepository()
        conn = psycopg.connect(settings.database_url)
        logger.info("worker.db.connected")
        return TimescaleRepository(conn)
    except Exception:
        logger.exception("worker.db.unavailable")
        return InMemoryRepository()


async def _run() -> None:
    settings = get_settings()
    settings.service_name = "aeropulse-worker"  # type: ignore[misc]
    configure_logging(settings)
    configure_telemetry(settings)
    from prometheus_client import start_http_server

    start_http_server(settings.worker_metrics_port)
    logger.info(
        "worker.starting",
        kafka=settings.kafka_bootstrap_servers,
        metrics_port=settings.worker_metrics_port,
    )
    persist = _repository()
    snapshot_repo = (
        persist
        if isinstance(persist, InMemoryRepository)
        else InMemoryRepository(retention_hours=settings.worker_snapshot_hours)
    )
    trigger = DetectionTrigger(
        interval_seconds=settings.worker_detection_interval_seconds,
        max_batch=settings.worker_detection_max_batch,
    )
    global _SHADOW_SCORER
    _SHADOW_SCORER = _init_shadow_scorer()

    try:
        from aiokafka import AIOKafkaConsumer
    except ImportError:
        logger.error("worker.aiokafka_missing")
        return

    consumer = AIOKafkaConsumer(
        OBSERVATION_AQ,
        OBSERVATION_FIRE,
        OBSERVATION_WEATHER,
        OBSERVATION_RASTER,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="aeropulse-worker",
        enable_auto_commit=True,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )
    await _start_consumer(consumer)
    logger.info("worker.consuming")
    try:
        async for msg in consumer:
            if not isinstance(msg.value, dict):
                continue
            _handle(msg.topic, msg.value, persist, snapshot_repo, trigger)
            if trigger.should_run():
                _sweep(persist, snapshot_repo, trigger)
    finally:
        # A partial batch still holds unswept observations; detection on the
        # way out keeps a clean shutdown from silently dropping them.
        if trigger.pending:
            _sweep(persist, snapshot_repo, trigger)
        await consumer.stop()


def _abort_txn(persist: ObservationRepository) -> None:
    """Clear an aborted Postgres transaction so the next message can run."""
    conn = getattr(persist, "conn", None)
    if conn is None:
        return
    with contextlib.suppress(Exception):
        conn.rollback()


def _sweep(
    persist: ObservationRepository,
    snapshot_repo: InMemoryRepository,
    trigger: DetectionTrigger,
) -> None:
    """Run one detection pass and persist what it produced."""
    covered = trigger.mark_run()
    try:
        detection = run_detection(snapshot_repo)
        logger.info("worker.detection", observations=covered, **detection)
        _persist_intelligence(persist, snapshot_repo)
    except Exception:
        logger.exception("worker.detection_failed", observations=covered)


def _handle(
    topic: str,
    value: dict[str, Any],
    persist: ObservationRepository,
    snapshot_repo: InMemoryRepository,
    trigger: DetectionTrigger | None = None,
) -> None:
    correlation = value.get("correlation_id", "")
    bind_context(**{"correlation.id": correlation})
    payload = value.get("payload") or value
    try:
        dual = persist is not snapshot_repo
        if topic == OBSERVATION_AQ:
            obs = Observation.model_validate(payload)
            result = process_air_quality(obs, persist)
            if dual:
                process_air_quality(obs, snapshot_repo)
        elif topic == OBSERVATION_FIRE:
            obs_f = FireObservation.model_validate(payload)
            result = process_fire(obs_f, persist)
            if dual:
                process_fire(obs_f, snapshot_repo)
        elif topic == OBSERVATION_RASTER:
            raster = RasterObservation.model_validate(payload)
            snapshot_repo.add_raster(raster)
            writer = getattr(persist, "upsert_raster", None)
            inserted = writer(raster) if writer is not None else True
            result = {"status": "persisted" if inserted else "duplicate", "grid_id": None}
        else:
            obs_w = MeteorologicalObservation.model_validate(payload)
            result = process_weather(obs_w, persist)
            if dual:
                process_weather(obs_w, snapshot_repo)
        logger.info("worker.processed", topic=topic, status=result["status"])
        if result.get("status") == "persisted":
            if trigger is None:
                # No trigger supplied (unit tests, single-shot callers): keep
                # the original sweep-per-observation behaviour.
                detection = run_detection(snapshot_repo)
                logger.info("worker.detection", **detection)
                _persist_intelligence(persist, snapshot_repo)
            else:
                trigger.record()
    except Exception:
        logger.exception("worker.failed", topic=topic)
        _abort_txn(persist)


def _persist_intelligence(persist: ObservationRepository, snapshot: InMemoryRepository) -> None:
    """Best-effort Timescale write for events, graphs, forecasts, features, and health."""
    writer = getattr(persist, "upsert_event", None)
    if writer is None:
        return
    store = snapshot.event_store
    try:
        for event in store.events.values():
            persist.upsert_event(event)  # type: ignore[attr-defined]
            persist.insert_evidence(event.event_id, store.evidence.get(event.event_id, []))  # type: ignore[attr-defined]
            graph = store.graphs.get(event.event_id)
            if graph is not None:
                persist.insert_graph(graph)  # type: ignore[attr-defined]
            forecast = store.forecasts.get(event.event_id)
            if forecast is not None:
                persist.insert_forecast(forecast)  # type: ignore[attr-defined]
        if hasattr(persist, "upsert_grid_feature"):
            for feature in store.latest_features.values():
                persist.upsert_grid_feature(feature)  # type: ignore[attr-defined]
        if hasattr(persist, "upsert_grid_prediction"):
            for prediction in store.latest_predictions.values():
                persist.upsert_grid_prediction(prediction)  # type: ignore[attr-defined]
        if hasattr(persist, "upsert_alert"):
            # The event engine raises these into the in-process store; they
            # only reach the API once they are persisted.
            for alert in store.alerts.values():
                persist.upsert_alert(alert)  # type: ignore[attr-defined]
    except Exception:
        logger.exception("worker.intelligence_persist_failed")
        _abort_txn(persist)

    _score_shadow(persist, snapshot)


def _score_shadow(persist: ObservationRepository, snapshot: InMemoryRepository) -> None:
    """Score registered challengers on this pass and record the result.

    Runs *after* the served answer has already been computed and persisted,
    and catches everything. A challenger must never be able to affect, delay
    or fail the prediction that reaches a user (LLD §40, integration plan
    Phase 4).

    Args:
        persist: Persistence adapter; skipped when it cannot store shadow rows.
        snapshot: Repository holding this pass's features and predictions.
    """
    scorer = _SHADOW_SCORER
    if scorer is None or not scorer.challengers:
        return
    writer = getattr(persist, "upsert_shadow_prediction", None)
    if writer is None:
        return

    store = snapshot.event_store
    try:
        for grid_id, feature in store.latest_features.items():
            prediction = store.latest_predictions.get(grid_id)
            champion_values = {
                # The deterministic estimator is the incumbent for the only
                # family with a directly comparable champion today. The peak
                # and hazard families have no deterministic counterpart, so
                # their champion value stays None rather than being paired
                # with an unrelated number.
                "pm25_estimator": prediction.pm25_estimate if prediction else None,
            }
            for row in scorer.score(feature, champion_values=champion_values):
                writer(row)
                SHADOW_PREDICTIONS.labels(
                    model_name=row.model_name,
                    outcome="error" if row.error else "scored",
                ).inc()
                MODEL_FEATURE_COMPLETENESS.labels(model_name=row.model_name).observe(
                    row.feature_completeness
                )
    except Exception:
        logger.exception("worker.shadow_persist_failed")


def main() -> None:
    """CLI entrypoint."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
