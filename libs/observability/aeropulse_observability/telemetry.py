"""OpenTelemetry tracer bootstrap.

When ``AEROPULSE_OTEL_EXPORTER_OTLP_ENDPOINT`` is unset, spans are no-op.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from aeropulse_common.settings import Settings, get_settings
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import Span, Status, StatusCode

_PROVIDER_SET = False


def configure_telemetry(settings: Settings | None = None) -> None:
    """Configure a TracerProvider for this process.

    Args:
        settings: Optional settings override.
    """
    global _PROVIDER_SET
    if _PROVIDER_SET:
        return
    cfg = settings or get_settings()
    resource = Resource.create(
        {
            "service.name": cfg.service_name,
            "service.version": cfg.service_version,
            "deployment.environment": cfg.environment,
        }
    )
    provider = TracerProvider(resource=resource)
    if cfg.otel_exporter_otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=cfg.otel_exporter_otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        # Keep a console exporter only when explicitly debugging; default is silent.
        if cfg.log_level.upper() == "DEBUG":
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _PROVIDER_SET = True


@contextmanager
def start_span(name: str, **attributes: object) -> Iterator[Span]:
    """Start a tracing span with AeroPulse attributes.

    Args:
        name: Span name (e.g. ``connector.fetch``).
        **attributes: Additional span attributes (source.id, kafka.topic, ...).
    """
    if not _PROVIDER_SET:
        configure_telemetry()
    tracer = trace.get_tracer("aeropulse")
    with tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)  # type: ignore[arg-type]
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
