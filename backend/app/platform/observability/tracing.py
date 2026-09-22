"""
OpenTelemetry tracing wiring.

- ``configure_telemetry`` sets up the tracer provider, the OTLP/HTTP exporter
  (traces flow to the OpenTelemetry Collector, which forwards to Jaeger), and
  auto-instruments FastAPI + SQLAlchemy. It is a no-op unless ``OTEL_ENABLED``.
- ``add_trace_context`` is a structlog processor that stamps the active
  ``trace_id``/``span_id`` onto every log line, so logs, metrics, and traces all
  share one key alongside the request ``correlation_id``.
- ``set_span_correlation_id`` tags the current request span with the
  correlation ID so a trace is searchable by the same ID the client sees.

Everything degrades gracefully: if OTel is disabled or its packages are missing,
the processor/helpers become cheap no-ops and the app runs unchanged.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def add_trace_context(_logger, _method_name, event_dict: dict) -> dict:
    """structlog processor: inject the active OTel trace/span id into logs."""
    try:
        from opentelemetry import trace
    except ImportError:
        return event_dict

    span = trace.get_current_span()
    ctx = span.get_span_context() if span else None
    if ctx is not None and ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def set_span_correlation_id(correlation_id: str) -> None:
    """Tag the current request span with the correlation ID (best-effort)."""
    try:
        from opentelemetry import trace
    except ImportError:
        return
    span = trace.get_current_span()
    if span is not None and span.get_span_context().is_valid:
        span.set_attribute("correlation_id", correlation_id)


def configure_telemetry(app: object) -> None:
    from app.platform.configuration.config import settings

    if not settings.OTEL_ENABLED:
        logger.debug("OpenTelemetry disabled — skipping instrumentation")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("OpenTelemetry packages not available — skipping instrumentation")
        return

    resource = Resource.create(
        {
            SERVICE_NAME: settings.OTEL_SERVICE_NAME,
            "service.version": settings.APP_VERSION,
            "deployment.environment": settings.ENVIRONMENT,
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=f"{settings.OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        # /metrics and health probes are high-frequency and low-signal — exclude
        # them from tracing to keep trace storage focused on business requests.
        FastAPIInstrumentor.instrument_app(
            app,  # type: ignore[arg-type]
            excluded_urls="/metrics,/api/v1/health,/api/v1/health/ready",
        )
    except ImportError:
        logger.warning("FastAPI OTel instrumentation not available")

    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        from app.platform.database.services import engine

        # Instrument the specific async engine so DB spans nest under request spans.
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    except ImportError:
        logger.warning("SQLAlchemy OTel instrumentation not available")

    logger.info(
        "OpenTelemetry configured (service=%s endpoint=%s)",
        settings.OTEL_SERVICE_NAME,
        settings.OTEL_EXPORTER_OTLP_ENDPOINT,
    )
