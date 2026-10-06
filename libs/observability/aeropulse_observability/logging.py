"""JSON structured logging using structlog.

Every log line includes service.name, service.version, and correlation.id when bound.
Never log secrets, credentials, or raw citizen PII.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from aeropulse_common.settings import Settings, get_settings
from opentelemetry import trace

_CONFIGURED = False

# httpx logs every request at INFO including the full URL. FIRMS carries its
# MAP_KEY in the URL *path*, and other providers use query parameters, so an
# enabled httpx logger writes credentials into logs (against LLD §35.2). This
# belongs in the shared logging setup, not in one entry point: the connector
# process is the one that actually makes credentialed upstream calls.
_NOISY_CREDENTIAL_BEARING_LOGGERS = ("httpx", "httpcore")


def suppress_credential_bearing_loggers() -> None:
    """Silence HTTP client loggers that echo full request URLs.

    Safe to call on its own by entry points that must not adopt the full JSON
    logging setup — the ML CLI writes machine-readable JSON to stdout and
    cannot have INFO records interleaved with it.
    """
    for noisy in _NOISY_CREDENTIAL_BEARING_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def configure_logging(settings: Settings | None = None) -> None:
    """Configure process-wide JSON logging.

    Args:
        settings: Optional settings override. Defaults to ``get_settings()``.
    """
    global _CONFIGURED
    cfg = settings or get_settings()
    level = getattr(logging, cfg.log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
        force=True,
    )

    suppress_credential_bearing_loggers()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
            _add_service_fields(cfg),
            _add_trace_context,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def _add_trace_context(_logger: Any, _method: str, event_dict: Any) -> Any:
    """Bind `trace_id`/`span_id` from the active OTel span, when one exists (LLD §33.1).

    A no-op when telemetry is unconfigured or no span is active, so log lines
    are unaffected outside of a traced request.
    """
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.is_valid:
        event_dict.setdefault("trace_id", format(ctx.trace_id, "032x"))
        event_dict.setdefault("span_id", format(ctx.span_id, "016x"))
    return event_dict


def _add_service_fields(settings: Settings):
    def processor(_logger: Any, _method: str, event_dict: Any) -> Any:
        event_dict.setdefault("service.name", settings.service_name)
        event_dict.setdefault("service.version", settings.service_version)
        event_dict.setdefault("deployment.environment", settings.environment)
        event_dict.setdefault("logger", _logger)
        return event_dict

    return processor


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger.

    Args:
        name: Optional logger name stored as ``logger``.
    """
    if not _CONFIGURED:
        configure_logging()
    logger = structlog.get_logger()
    if name:
        return logger.bind(logger=name)
    return logger


def bind_context(**kwargs: Any) -> None:
    """Bind request-scoped fields such as ``correlation.id`` into log context."""
    structlog.contextvars.bind_contextvars(**kwargs)
