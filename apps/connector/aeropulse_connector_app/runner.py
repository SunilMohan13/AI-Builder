"""Connector runner: fetch, normalize and publish one cycle per source.

Sources are declared in :mod:`aeropulse_connector_app.registry` rather than
hardcoded here, and the Kafka topic is derived from the contract a connector
actually produced. That is what lets one source emit several contracts, and
it is why Open-Meteo could not be wired into the previous shape.

Every source runs inside its own guard: a missing fixture, an upstream
outage, or a malformed payload degrades that one source and leaves the rest
of the cycle intact.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from aeropulse_common.ids import new_ulid
from aeropulse_common.objects import put_raw_json
from aeropulse_common.settings import get_settings
from aeropulse_connector_sdk.contracts import FetchRequest
from aeropulse_connector_sdk.cursor import Cursor, advance, encode_cursor, parse_cursor
from aeropulse_connector_sdk.live_http import CircuitOpenError, LiveModeDisabledError
from aeropulse_connector_sdk.testing import FixtureMissingError
from aeropulse_contracts.envelope import KafkaEnvelope, ProcessingMode
from aeropulse_contracts.fire import FireObservation
from aeropulse_contracts.meteo import MeteorologicalObservation
from aeropulse_contracts.observation import Observation
from aeropulse_contracts.raster import RasterObservation
from aeropulse_observability.logging import get_logger

from aeropulse_connector_app.registry import SOURCE_SPECS, SourceSpec, topic_for

logger = get_logger("aeropulse.connector")

PublishFn = Callable[[str, KafkaEnvelope], None]
DEFAULT_SOURCES_CONFIG = Path("config/sources.yaml")

CanonicalObservation = Observation | FireObservation | MeteorologicalObservation | RasterObservation


class SourceStatus(StrEnum):
    """Outcome of one source's run, recorded on ``source_health``.

    These are deliberately distinct: an operator needs to tell "this source
    is configured but you gave it no key" apart from "this source is failing"
    and from "this source is replaying a fixture on purpose".
    """

    HEALTHY = "HEALTHY"
    REPLAY = "REPLAY"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    DEGRADED = "DEGRADED"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    FIXTURE_MISSING = "FIXTURE_MISSING"
    REPLAY_EXHAUSTED = "REPLAY_EXHAUSTED"
    DISABLED = "DISABLED"


@dataclass
class SourceRun:
    """What one source did this cycle.

    Attributes:
        source_id: Registry id.
        status: Outcome, for source health.
        records: Observations published.
        mode: ``live`` or ``replay`` as actually resolved, not as requested.
        max_observed_at: Newest observation timestamp published, which
            becomes the watermark for a live source.
        error: Short failure description, when there was one.
        latency_ms: Wall-clock duration of the run.
    """

    source_id: str
    status: SourceStatus
    records: int = 0
    mode: str = "replay"
    max_observed_at: datetime | None = None
    error: str | None = None
    latency_ms: int = 0


@dataclass
class CycleResult:
    """Aggregate of one full cycle."""

    runs: list[SourceRun] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        """Published record counts keyed by source id."""
        return {run.source_id: run.records for run in self.runs}

    def by_status(self, status: SourceStatus) -> list[SourceRun]:
        """Runs that ended in a given status."""
        return [run for run in self.runs if run.status is status]


def _persist_health(repo: Any | None, run: SourceRun) -> None:
    """Write one SourceRun to source_health when a Timescale repo is available."""
    if repo is None or not hasattr(repo, "upsert_source_health"):
        return
    try:
        repo.upsert_source_health(
            run.source_id,
            run.records,
            run.status.value,
            latency_ms=run.latency_ms,
            error=run.error,
            processing_mode=run.mode,
        )
    except Exception:
        logger.warning("connector.health.persist_failed", source_id=run.source_id)


def _checkpoint_repository() -> Any | None:
    """Return the Timescale-backed checkpoint repository when configured."""
    settings = get_settings()
    if not settings.database_url:
        return None
    try:
        import psycopg
        from aeropulse_worker.db import TimescaleRepository

        return TimescaleRepository(psycopg.connect(settings.database_url))
    except Exception:
        logger.warning("connector.checkpoint.unavailable")
        return None


def _checkpoint_key(source_id: str, provider: str | None) -> str:
    """Construct a provider-aware checkpoint identity for a source."""
    if provider is None or provider == "":
        return source_id
    return f"{source_id}: {provider}"


def _checkpoint_cursor(repo: Any | None, source_id: str, provider: str | None) -> str | None:
    """Read the latest checkpoint, falling back to the legacy source-only key."""
    if repo is None:
        return None
    key = _checkpoint_key(source_id, provider)
    cursor = repo.get_checkpoint(key)
    if cursor is not None:
        return cursor
    if provider is not None:
        return repo.get_checkpoint(source_id)
    return None


def _persist_checkpoint(
    repo: Any | None, source_id: str, provider: str | None, cursor: str
) -> None:
    """Persist the updated cursor using the provider-aware key."""
    if repo is None:
        return
    repo.upsert_checkpoint(_checkpoint_key(source_id, provider), cursor)


def _enabled_source_ids(config_path: Path) -> set[str] | None:
    """Read `config/sources.yaml` and return the set of enabled source ids.

    Returns ``None`` (meaning "treat everything as enabled") if the file is
    missing or malformed, so a misconfigured registry never silently stops
    ingestion.
    """
    try:
        raw = yaml.safe_load(config_path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("connector.sources_config.unreadable", path=str(config_path), error=str(exc))
        return None
    sources = (raw or {}).get("sources")
    if not isinstance(sources, list):
        logger.warning("connector.sources_config.invalid", path=str(config_path))
        return None
    return {
        s["id"] for s in sources if isinstance(s, dict) and s.get("enabled", True) and "id" in s
    }


def _credential_present(spec: SourceSpec) -> bool:
    """Whether this source's credential is configured.

    Reads presence only. The value never leaves ``Settings``.
    """
    if spec.credential_setting is None:
        return True
    value = getattr(get_settings(), spec.credential_setting, None)
    if value is None:
        return False
    secret = getattr(value, "get_secret_value", None)
    return bool(secret() if callable(secret) else value)


def _resolve_live(spec: SourceSpec, connector: Any) -> bool:
    """Whether this source runs live this cycle.

    A connector may expose ``is_live()``; otherwise the global mode decides.
    """
    if not spec.live_capable:
        return False
    probe = getattr(connector, "is_live", None)
    if callable(probe):
        return bool(probe())
    return get_settings().connector_mode == "live"


def _observed_at(observation: CanonicalObservation) -> datetime | None:
    """Return the canonical timestamp for any contract type."""
    if isinstance(observation, RasterObservation):
        return observation.acquisition_time
    return observation.observed_at


def run_cycle(
    fixtures_root: Path,
    publish: PublishFn,
    *,
    processing_mode: ProcessingMode = ProcessingMode.BACKFILL,
    sources_config: Path = DEFAULT_SOURCES_CONFIG,
    specs: tuple[SourceSpec, ...] = SOURCE_SPECS,
    overlap_seconds: int | None = None,
    repo: Any | None = None,
) -> CycleResult:
    """Run every enabled source once and publish what they produce.

    Args:
        fixtures_root: Directory containing per-source fixture folders.
        publish: Callback ``(topic, envelope)``.
        processing_mode: LIVE or BACKFILL, stamped on the envelope.
        sources_config: Path to `config/sources.yaml`.
        specs: Source registry; overridable for tests.
        overlap_seconds: Rewind applied to a live watermark before fetching.
        repo: Checkpoint/health repository. Tests inject a fake; production
            opens Timescale when ``AEROPULSE_DATABASE_URL`` is set.

    Returns:
        A :class:`CycleResult` with one :class:`SourceRun` per source.
    """
    enabled = _enabled_source_ids(sources_config)
    repo = repo if repo is not None else _checkpoint_repository()
    overlap = (
        overlap_seconds
        if overlap_seconds is not None
        else get_settings().connector_watermark_overlap_seconds
    )
    result = CycleResult()

    for spec in specs:
        if enabled is not None and spec.source_id not in enabled:
            run = SourceRun(spec.source_id, SourceStatus.DISABLED)
            _persist_health(repo, run)
            result.runs.append(run)
            continue
        run = _run_source(
            spec,
            fixtures_root,
            publish,
            processing_mode=processing_mode,
            repo=repo,
            overlap_seconds=overlap,
        )
        _persist_health(repo, run)
        result.runs.append(run)

    logger.info("connector.cycle.completed", **result.counts())
    return result


def _run_source(
    spec: SourceSpec,
    fixtures_root: Path,
    publish: PublishFn,
    *,
    processing_mode: ProcessingMode,
    repo: Any | None,
    overlap_seconds: int,
) -> SourceRun:
    """Run one source, converting any failure into a status rather than raising."""
    started = datetime.now(UTC)

    def elapsed_ms() -> int:
        return int((datetime.now(UTC) - started).total_seconds() * 1000)

    try:
        connector = spec.build(fixtures_root)
    except Exception as exc:
        logger.exception("connector.build_failed", source_id=spec.source_id)
        return SourceRun(
            spec.source_id, SourceStatus.DEGRADED, error=str(exc), latency_ms=elapsed_ms()
        )

    live = _resolve_live(spec, connector)
    mode = "live" if live else "replay"

    if live and not _credential_present(spec):
        # No silent fixture substitution: serving yesterday's fixture under a
        # live banner is the failure this codebase exists to avoid.
        logger.warning(
            "connector.credential_missing",
            source_id=spec.source_id,
            setting=spec.credential_setting,
        )
        return SourceRun(
            spec.source_id,
            SourceStatus.NOT_CONFIGURED,
            mode=mode,
            error=f"{spec.credential_setting} is not set",
            latency_ms=elapsed_ms(),
        )

    provider = None
    try:
        provider = connector.metadata().provider
    except Exception:
        logger.warning("connector.metadata_unavailable", source_id=spec.source_id)

    stored = _checkpoint_cursor(repo, spec.source_id, provider)
    cursor = parse_cursor(stored)
    request = _build_request(cursor, processing_mode, provider, live, overlap_seconds)

    raw_uri = _archive_raw(spec, fixtures_root) if spec.archive_raw else None

    try:
        records, newest = _publish_source(connector, request, publish, processing_mode, raw_uri)
    except FixtureMissingError as exc:
        logger.warning("connector.fixture_missing", source_id=spec.source_id, path=str(exc.path))
        return SourceRun(
            spec.source_id,
            SourceStatus.FIXTURE_MISSING,
            mode=mode,
            error=str(exc),
            latency_ms=elapsed_ms(),
        )
    except CircuitOpenError as exc:
        logger.warning("connector.circuit_open", source_id=spec.source_id)
        return SourceRun(
            spec.source_id,
            SourceStatus.CIRCUIT_OPEN,
            mode=mode,
            error=str(exc),
            latency_ms=elapsed_ms(),
        )
    except LiveModeDisabledError as exc:
        return SourceRun(
            spec.source_id,
            SourceStatus.REPLAY,
            mode="replay",
            error=str(exc),
            latency_ms=elapsed_ms(),
        )
    except Exception as exc:
        logger.exception("connector.fetch_failed", source_id=spec.source_id)
        # The cursor is deliberately not advanced: the same window is retried
        # next tick rather than being skipped.
        return SourceRun(
            spec.source_id,
            SourceStatus.DEGRADED,
            mode=mode,
            error=str(exc),
            latency_ms=elapsed_ms(),
        )

    _persist_checkpoint(
        repo,
        spec.source_id,
        provider,
        encode_cursor(advance(cursor, live=live, records_emitted=records, max_observed_at=newest)),
    )

    status = _classify(live, records, cursor)
    return SourceRun(
        spec.source_id,
        status,
        records=records,
        mode=mode,
        max_observed_at=newest,
        latency_ms=elapsed_ms(),
    )


def _classify(live: bool, records: int, cursor: Cursor) -> SourceStatus:
    """Pick the health status for a successful run.

    A replay source that has consumed its whole fixture reports
    ``REPLAY_EXHAUSTED`` rather than ``HEALTHY``: under a scheduler it would
    otherwise sit there looking fine while emitting nothing forever.
    """
    if live:
        return SourceStatus.HEALTHY
    if records == 0 and cursor.as_offset() > 0:
        return SourceStatus.REPLAY_EXHAUSTED
    return SourceStatus.REPLAY


def _build_request(
    cursor: Cursor,
    processing_mode: ProcessingMode,
    provider: str | None,
    live: bool,
    overlap_seconds: int,
) -> FetchRequest:
    """Build the fetch request, windowing by time for a live source."""
    if live:
        start = cursor.window_start(overlap_seconds)
        if start is not None:
            return FetchRequest(
                processing_mode=processing_mode.value,
                provider=provider,
                start_time=start,
                end_time=datetime.now(UTC),
            )
        return FetchRequest(processing_mode=processing_mode.value, provider=provider)
    return FetchRequest(
        processing_mode=processing_mode.value,
        cursor=encode_cursor(cursor),
        provider=provider,
    )


def _archive_raw(spec: SourceSpec, fixtures_root: Path) -> str | None:
    """Copy a source's raw payload to object storage, returning its URI."""
    path = spec.fixture_path(fixtures_root)
    if path is None or not path.exists():
        return None
    try:
        return put_raw_json(spec.source_id, path.name, path.read_bytes())
    except Exception:
        logger.warning("connector.raw_archive_failed", source_id=spec.source_id)
        return None


def _publish_source(
    connector: Any,
    request: FetchRequest,
    publish: PublishFn,
    mode: ProcessingMode,
    raw_uri: str | None,
) -> tuple[int, datetime | None]:
    """Fetch, normalize and publish, returning the count and newest timestamp."""
    count = 0
    newest: datetime | None = None
    for raw in connector.fetch(request):
        if raw_uri:
            raw.raw_uri = raw_uri
        for obs in connector.normalize(raw):
            if raw_uri:
                obs.provenance.raw_object_uri = raw_uri
            _publish_observation(publish, topic_for(obs), obs, mode)
            count += 1
            observed = _observed_at(obs)
            if observed is not None and (newest is None or observed > newest):
                newest = observed
    return count, newest


def _publish_observation(
    publish: PublishFn,
    topic: str,
    obs: CanonicalObservation,
    mode: ProcessingMode,
) -> None:
    envelope = KafkaEnvelope(
        correlation_id=new_ulid("corr"),
        source_id=obs.source_id,
        processing_mode=mode,
        produced_at=datetime.now(UTC),
        payload=obs.model_dump(mode="json"),
    )
    publish(topic, envelope)


def replay_all(
    fixtures_root: Path,
    publish: PublishFn,
    *,
    processing_mode: ProcessingMode = ProcessingMode.BACKFILL,
    sources_config: Path = DEFAULT_SOURCES_CONFIG,
) -> dict[str, int]:
    """Run one cycle and return per-source published counts.

    Retained with its original signature and return type because the API's
    backfill route and the existing replay tests both call it.

    Args:
        fixtures_root: Directory containing per-source fixture folders.
        publish: Callback ``(topic, envelope)``.
        processing_mode: LIVE or BACKFILL.
        sources_config: Path to `config/sources.yaml`.

    Returns:
        Counts of published observations per source (skipped sources read 0).
    """
    result = run_cycle(
        fixtures_root,
        publish,
        processing_mode=processing_mode,
        sources_config=sources_config,
    )
    return result.counts()
