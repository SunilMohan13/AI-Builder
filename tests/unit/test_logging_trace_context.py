"""`trace_id`/`span_id` must ride along on log lines emitted inside a span (LLD §33.1)."""

from __future__ import annotations

import json

import aeropulse_observability.logging as logging_mod
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider


def _last_json_line(raw: str) -> dict:
    lines = [line for line in raw.splitlines() if line.strip()]
    return json.loads(lines[-1])


def test_trace_id_bound_when_span_active(capsys) -> None:
    trace.set_tracer_provider(TracerProvider())
    tracer = trace.get_tracer("test")

    logging_mod._CONFIGURED = False
    logging_mod.configure_logging()
    logger = logging_mod.get_logger("test.logger")

    with tracer.start_as_current_span("test-span"):
        logger.info("event.inside_span")

    payload = _last_json_line(capsys.readouterr().out)
    assert len(payload["trace_id"]) == 32
    assert len(payload["span_id"]) == 16


def test_no_trace_id_without_active_span(capsys) -> None:
    logging_mod._CONFIGURED = False
    logging_mod.configure_logging()
    logger = logging_mod.get_logger("test.logger")

    logger.info("event.outside_span")

    payload = _last_json_line(capsys.readouterr().out)
    assert "trace_id" not in payload
    assert "span_id" not in payload
