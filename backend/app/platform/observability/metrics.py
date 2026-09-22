"""
Prometheus metrics for the Business Platform.

Two layers:

1. **HTTP metrics** — ``prometheus-fastapi-instrumentator`` attaches default
   request counters/latency histograms to every route and exposes ``/metrics``
   at the application root (Prometheus convention, unauthenticated for in-cluster
   scraping).

2. **Business metrics** — domain counters/histograms defined here as module-level
   singletons (Prometheus requires a single instance per metric name). They are
   fed from one choke point: ``EventProducer._emit`` calls :func:`record_event`
   for every one of the eight settlement-lifecycle events, so business
   instrumentation stays out of the service layer.

All metric names are prefixed ``aner_`` so they are easy to isolate in queries
and dashboards.
"""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI
from prometheus_client import Counter, Gauge, Histogram

logger = structlog.get_logger(__name__)

# ── Business metrics ─────────────────────────────────────────────────────────

# Every lifecycle event published through the EventProducer, labelled by type.
EVENTS_PUBLISHED = Counter(
    "aner_events_published_total",
    "Settlement-lifecycle events published to the event bus.",
    labelnames=("event_type",),
)

# High-signal transaction outcome counters (derived from lifecycle events).
PAYMENTS_CREATED = Counter(
    "aner_payments_created_total",
    "Payment-initiation requests that produced a transaction.",
)
SETTLEMENTS_COMPLETED = Counter(
    "aner_settlements_completed_total",
    "Settlements that reached SETTLED (INR payout confirmed).",
)
SETTLEMENTS_FAILED = Counter(
    "aner_settlements_failed_total",
    "Settlements that failed and triggered compensation.",
)
COMPENSATIONS = Counter(
    "aner_compensations_total",
    "Compensation workflows, labelled by phase (started/completed).",
    labelnames=("phase",),
)
COMPLIANCE_APPROVALS = Counter(
    "aner_compliance_approvals_total",
    "Maker-checker compliance approvals recorded.",
)

# ── Archival metrics (S3T3) ──────────────────────────────────────────────────

ARCHIVAL_RECORDS_ARCHIVED = Counter(
    "aner_archival_records_archived_total",
    "Idempotency records moved from the hot table to the archive.",
)
ARCHIVAL_HOT_TABLE_REMAINING = Gauge(
    "aner_archival_hot_table_remaining",
    "Number of records currently in the hot idempotency_record table.",
)
ARCHIVAL_HOT_TABLE_GROWTH_RATE = Gauge(
    "aner_archival_hot_table_growth_rate",
    "Estimated hot table growth rate (records per day) after last archival run.",
)
ARCHIVAL_RUNS = Counter(
    "aner_archival_runs_total",
    "Number of archival job runs, labelled by outcome.",
    labelnames=("status",),
)

# ── Idempotency metrics (S4T1) ──────────────────────────────────────────────

IDEMPOTENCY_REGISTRATIONS = Counter(
    "aner_idempotency_registrations_total",
    "New idempotency key registrations.",
    labelnames=("key_type", "operation_type"),
)
IDEMPOTENCY_DUPLICATES = Counter(
    "aner_idempotency_duplicates_total",
    "Duplicate idempotency key detections by existing record status.",
    labelnames=("key_type", "operation_type", "duplicate_status"),
)
IDEMPOTENCY_VIOLATIONS = Counter(
    "aner_idempotency_violations_total",
    "Operations executed despite a registered idempotency key (must be zero).",
)
IDEMPOTENCY_REGISTRATION_LATENCY = Histogram(
    "aner_idempotency_key_registration_latency_seconds",
    "Latency of the idempotency key registration service (DB round-trip).",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)
IDEMPOTENCY_REGISTRY_SIZE = Gauge(
    "aner_idempotency_registry_size",
    "Live record count in the hot idempotency_record table.",
    labelnames=("status",),
)
IDEMPOTENCY_EXPIRY_JOB_LAST_RUN = Gauge(
    "aner_idempotency_expiry_job_last_run_timestamp",
    "Unix epoch of the last successful expiry job run (0 = never).",
)
IDEMPOTENCY_ARCHIVAL_JOB_LAST_RUN = Gauge(
    "aner_idempotency_archival_job_last_run_timestamp",
    "Unix epoch of the last successful archival job run (0 = never).",
)
IDEMPOTENCY_SCHEDULED_CHECK_LAST_RUN = Gauge(
    "aner_idempotency_scheduled_check_last_run_timestamp",
    "Unix epoch of the last successful scheduled violation check run (0 = never).",
)
IDEMPOTENCY_STREAM_PROCESSOR_LAST_RUN = Gauge(
    "aner_idempotency_stream_processor_last_run_timestamp",
    "Unix epoch of the last successful stream processor violation check run (0 = never).",
)
IDEMPOTENCY_DETECTOR_LIVENESS_ALERTS = Counter(
    "aner_idempotency_detector_liveness_alerts_total",
    "Alerts raised when violation detector scheduled check or stream processor misses interval.",
)


# ── Idempotency lifecycle metrics (S3T2) ─────────────────────────────────────

IDEMPOTENCY_LIFECYCLE_ALREADY_PROCESSED = Counter(
    "aner_idempotency_lifecycle_already_processed_total",
    "Settlement lifecycle events skipped because every matching IDK/RR record was "
    "already in the target terminal status (at-least-once redelivery).",
    labelnames=("settlement_status",),
)

# ── Rail health metrics ──────────────────────────────────────────────────────

RAIL_HEALTH_CHECK_RESULT = Gauge(
    "aner_rail_health_check_result",
    "Rail health check result: 1 = healthy, 0 = unhealthy.",
    labelnames=("rail_id",),
)

RAIL_HEALTH_CHECK_LATENCY = Histogram(
    "aner_rail_health_check_latency_seconds",
    "Latency of rail health check calls.",
    labelnames=("rail_id",),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

RAIL_SETTLEMENT_SUCCESS_RATE = Gauge(
    "aner_rail_settlement_success_rate",
    "Percentage of submissions in the last hour that reached settled status.",
    labelnames=("rail_id",),
)

RAIL_AVERAGE_SETTLEMENT_TIME_MINUTES = Gauge(
    "aner_rail_average_settlement_time_minutes",
    "Average settlement time in minutes in the last hour vs declared SLA.",
    labelnames=("rail_id",),
)

RAIL_HEALTH_MONITOR_LAST_RUN = Gauge(
    "aner_rail_health_monitor_last_run_timestamp",
    "Unix epoch of the last successful health monitor run (0 = never).",
)


# ── Rail polling manager ─────────────────────────────────────────────────────

RAIL_LEG_STUCK = Counter(
    "aner_rail_leg_stuck_total",
    "Legs that passed the rail's declared settlement_speed_minutes_p99 without "
    "reaching a terminal status. This is the SRE-alertable half of the polling "
    "stuck_leg alert — each increment is one payment nobody is otherwise looking "
    "at. Labelled by rail_id because a single vendor's status API failing to "
    "deliver is invisible in a platform-wide total.",
    labelnames=("rail_id",),
)

def record_idempotency_registration(key_type: str, operation_type: str) -> None:
    """Record a new idempotency key registration.  Best-effort."""
    try:
        IDEMPOTENCY_REGISTRATIONS.labels(key_type=key_type, operation_type=operation_type).inc()
    except Exception as exc:  # noqa: BLE001
        logger.warning("idempotency_metric_failed", metric="registrations", error=str(exc))


def record_idempotency_duplicate(
    key_type: str, operation_type: str, duplicate_status: str,
) -> None:
    """Record a duplicate idempotency key detection.  Best-effort."""
    try:
        IDEMPOTENCY_DUPLICATES.labels(
            key_type=key_type, operation_type=operation_type, duplicate_status=duplicate_status,
        ).inc()
    except Exception as exc:  # noqa: BLE001
        logger.warning("idempotency_metric_failed", metric="duplicates", error=str(exc))


def record_idempotency_violation() -> None:
    """Record an idempotency violation (duplicate execution).  Best-effort."""
    try:
        IDEMPOTENCY_VIOLATIONS.inc()
    except Exception as exc:  # noqa: BLE001
        logger.warning("idempotency_metric_failed", metric="violations", error=str(exc))


def observe_idempotency_registration_latency(duration_seconds: float) -> None:
    """Record idempotency registration service latency.  Best-effort."""
    try:
        IDEMPOTENCY_REGISTRATION_LATENCY.observe(duration_seconds)
    except Exception as exc:  # noqa: BLE001
        logger.warning("idempotency_metric_failed", metric="registration_latency", error=str(exc))


# ── Rail performance metrics ──────────────────────────────────────────────────

RAIL_SUBMISSION_COUNT = Gauge(
    "aner_rail_submission_count",
    "Total leg submissions attempted in the last hourly aggregation window.",
    labelnames=("rail_id",),
)
RAIL_SUBMISSION_SUCCESS_RATE = Gauge(
    "aner_rail_submission_success_rate",
    "Percentage of submissions that received a submitted or pending response.",
    labelnames=("rail_id",),
)
RAIL_P95_SETTLEMENT_TIME_MINUTES = Gauge(
    "aner_rail_p95_settlement_time_minutes",
    "95th percentile settlement time for successfully settled legs (minutes).",
    labelnames=("rail_id",),
)
RAIL_TIMEOUT_RATE = Gauge(
    "aner_rail_timeout_rate",
    "Percentage of submissions that timed out at the dispatcher level.",
    labelnames=("rail_id",),
)
RAIL_FAILURE_DISTRIBUTION_COUNT = Gauge(
    "aner_rail_failure_distribution_count",
    "Count of each failure code encountered in the hourly aggregation window.",
    labelnames=("rail_id", "failure_code"),
)
RAIL_PERFORMANCE_LAST_RUN = Gauge(
    "aner_rail_performance_last_run_timestamp",
    "Unix epoch of the last successful rail performance aggregation run (0 = never).",
)


def record_rail_performance_metrics(records: list[Any]) -> None:
    """Update Prometheus gauges for rail performance hourly records."""
    import time
    for r in records:
        try:
            RAIL_SUBMISSION_COUNT.labels(rail_id=r.rail_id).set(r.submission_count)
            RAIL_SUBMISSION_SUCCESS_RATE.labels(rail_id=r.rail_id).set(r.submission_success_rate)
            RAIL_SETTLEMENT_SUCCESS_RATE.labels(rail_id=r.rail_id).set(r.settlement_success_rate)
            if r.average_settlement_time_minutes is not None:
                RAIL_AVERAGE_SETTLEMENT_TIME_MINUTES.labels(rail_id=r.rail_id).set(r.average_settlement_time_minutes)
            if r.p95_settlement_time_minutes is not None:
                RAIL_P95_SETTLEMENT_TIME_MINUTES.labels(rail_id=r.rail_id).set(r.p95_settlement_time_minutes)
            RAIL_TIMEOUT_RATE.labels(rail_id=r.rail_id).set(r.timeout_rate)
            if r.failure_distribution and isinstance(r.failure_distribution, dict):
                for code, count in r.failure_distribution.items():
                    RAIL_FAILURE_DISTRIBUTION_COUNT.labels(rail_id=r.rail_id, failure_code=str(code)).set(count)
        except Exception as exc:  # noqa: BLE001
            logger.warning("rail_performance_metric_failed", rail_id=getattr(r, "rail_id", None), error=str(exc))
    try:
        RAIL_PERFORMANCE_LAST_RUN.set(time.time())
    except Exception as exc:  # noqa: BLE001
        logger.warning("rail_performance_metric_failed", metric="last_run", error=str(exc))


# Map each lifecycle event type to the outcome counter(s) it should also bump.
# Kept as strings so this module never imports the events package (avoids an
# import cycle: producer → metrics → events). NOTE: these keys must match the
# EventType *values* in app/events/schemas.py exactly — e.g. payment creation is
# published as "transaction.initiated", not "payment.created".
_EVENT_OUTCOME_HANDLERS = {
    "transaction.initiated": lambda: PAYMENTS_CREATED.inc(),
    "compliance.approved": lambda: COMPLIANCE_APPROVALS.inc(),
    "settlement.completed": lambda: SETTLEMENTS_COMPLETED.inc(),
    "settlement.failed": lambda: SETTLEMENTS_FAILED.inc(),
    "compensation.started": lambda: COMPENSATIONS.labels(phase="started").inc(),
    "compensation.completed": lambda: COMPENSATIONS.labels(phase="completed").inc(),
}


def record_event(event_type: str) -> None:
    """
    Record a settlement-lifecycle event in Prometheus.

    Best-effort: instrumentation must never break the business operation that
    triggered it, so any error is swallowed with a warning.
    """
    try:
        EVENTS_PUBLISHED.labels(event_type=event_type).inc()
        handler = _EVENT_OUTCOME_HANDLERS.get(event_type)
        if handler is not None:
            handler()
    except Exception as exc:  # noqa: BLE001 — instrumentation is best-effort
        logger.warning("metric_record_failed", event_type=event_type, error=str(exc))


# ── HTTP instrumentation + /metrics endpoint ─────────────────────────────────

# Buckets tuned for a payments API: sub-second common, with a long tail for
# settlement-orchestrating requests.
_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def setup_metrics(app: FastAPI) -> None:
    """
    Attach default HTTP metrics to the app and expose ``GET /metrics``.

    Safe to import even if the instrumentator package is missing (metrics simply
    won't be exposed); the app continues to run.
    """
    try:
        from prometheus_fastapi_instrumentator import Instrumentator
        from prometheus_fastapi_instrumentator import metrics as fi_metrics
    except ImportError:  # pragma: no cover - dependency always present in image
        logger.warning("prometheus_fastapi_instrumentator not available — /metrics disabled")
        return

    instrumentator = Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/metrics", "/api/v1/health.*"],
        inprogress_name="aner_http_requests_inprogress",
        inprogress_labels=False,
    )
    # subsystem left empty: the base metric names already start with "http_",
    # so a "http" subsystem would double it (aner_http_http_requests_total).
    instrumentator.add(
        fi_metrics.default(
            metric_namespace="aner",
            metric_subsystem="",
            latency_highr_buckets=_LATENCY_BUCKETS,
        )
    )
    # instrument() must run before the app starts serving; expose() adds /metrics.
    instrumentator.instrument(app).expose(app, endpoint="/metrics", include_in_schema=True, tags=["Observability"])
    logger.info("prometheus_metrics_enabled", endpoint="/metrics")
