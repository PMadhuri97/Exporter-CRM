"""Meta-monitoring (liveness check) for the Violation Detection System (S4T2).

Monitors that both the scheduled check engine and stream processor run within their expected intervals.
If the scheduled check does not run within 20 minutes (1200 seconds), raises a CRITICAL alert to SRE on-call.
"""

from __future__ import annotations

import time

import structlog

from app.platform.observability.metrics import (
    IDEMPOTENCY_DETECTOR_LIVENESS_ALERTS,
    IDEMPOTENCY_SCHEDULED_CHECK_LAST_RUN,
    IDEMPOTENCY_STREAM_PROCESSOR_LAST_RUN,
)

logger = structlog.get_logger(__name__)

#: Scheduled check expected interval is 15 mins (900s). Alert threshold is 20 mins (1200s).
SCHEDULED_CHECK_MAX_INTERVAL_SECONDS = 1200.0

#: Stream processor max silence threshold before warning (300s).
STREAM_PROCESSOR_MAX_SILENCE_SECONDS = 300.0


def check_detector_liveness(now_timestamp: float | None = None) -> dict[str, bool]:
    """Inspect Prometheus metric last_run timestamps for scheduled check and stream processor."""
    now = now_timestamp if now_timestamp is not None else time.time()

    # Read current gauge values from Prometheus metrics
    scheduled_last_run = IDEMPOTENCY_SCHEDULED_CHECK_LAST_RUN._value.get()
    stream_last_run = IDEMPOTENCY_STREAM_PROCESSOR_LAST_RUN._value.get()

    status = {
        "scheduled_check_healthy": True,
        "stream_processor_healthy": True,
    }

    # Verify scheduled check liveness (must have run within 20 minutes if previously started)
    if scheduled_last_run > 0 and (now - scheduled_last_run) > SCHEDULED_CHECK_MAX_INTERVAL_SECONDS:
        status["scheduled_check_healthy"] = False
        IDEMPOTENCY_DETECTOR_LIVENESS_ALERTS.inc()
        logger.error(
            "violation_detector_liveness_failure",
            component="scheduled_check",
            alert_severity="CRITICAL",
            alert_action="PAGE_SRE_ONCALL",
            last_run_timestamp=scheduled_last_run,
            elapsed_seconds=now - scheduled_last_run,
            threshold_seconds=SCHEDULED_CHECK_MAX_INTERVAL_SECONDS,
            message="Violation detector scheduled check has not run within 20 minutes.",
        )

    # Verify stream processor liveness
    if stream_last_run > 0 and (now - stream_last_run) > STREAM_PROCESSOR_MAX_SILENCE_SECONDS:
        status["stream_processor_healthy"] = False
        logger.warning(
            "violation_detector_liveness_warning",
            component="stream_processor",
            last_run_timestamp=stream_last_run,
            elapsed_seconds=now - stream_last_run,
            threshold_seconds=STREAM_PROCESSOR_MAX_SILENCE_SECONDS,
            message="Stream processor has not processed events recently.",
        )

    return status
