"""
Observability package — the three pillars (metrics, traces, logs) wired to a
single correlation key.

- ``metrics``  : Prometheus instrumentation and business counters/histograms.
- ``app.platform.observability.tracing`` : OpenTelemetry tracing (OTLP → Collector) + log trace-context.

Business code should never import Prometheus directly; it emits domain signals
through the helpers here (``record_event``) or through the ``EventProducer``
choke point, keeping instrumentation in one place.
"""
from app.platform.observability.metrics import record_event, setup_metrics

__all__ = ["record_event", "setup_metrics"]
