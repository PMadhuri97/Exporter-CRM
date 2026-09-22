"""Unit tests for Violation Detector Liveness Meta-Monitoring (S4T2)."""

import time
from unittest.mock import patch

from app.platform.idempotency.liveness import check_detector_liveness
from app.platform.observability.metrics import (
    IDEMPOTENCY_SCHEDULED_CHECK_LAST_RUN,
    IDEMPOTENCY_STREAM_PROCESSOR_LAST_RUN,
)


def test_check_detector_liveness_healthy_state():
    """Verify healthy status when scheduled check and stream processor have run recently."""
    now = time.time()
    IDEMPOTENCY_SCHEDULED_CHECK_LAST_RUN.set(now - 300)  # 5 minutes ago (healthy)
    IDEMPOTENCY_STREAM_PROCESSOR_LAST_RUN.set(now - 30)  # 30 seconds ago (healthy)

    status = check_detector_liveness(now_timestamp=now)
    assert status["scheduled_check_healthy"] is True
    assert status["stream_processor_healthy"] is True


def test_check_detector_liveness_triggers_sre_alert_when_scheduled_check_stale():
    """Verify CRITICAL alert raised if scheduled check does not run within 20 minutes (1200s)."""
    now = time.time()
    IDEMPOTENCY_SCHEDULED_CHECK_LAST_RUN.set(now - 1500)  # 25 minutes ago (> 20 min threshold!)
    IDEMPOTENCY_STREAM_PROCESSOR_LAST_RUN.set(now - 10)

    with patch("app.platform.idempotency.liveness.logger") as mock_logger:
        status = check_detector_liveness(now_timestamp=now)

        assert status["scheduled_check_healthy"] is False
        mock_logger.error.assert_called_once()
        call_kwargs = mock_logger.error.call_args[1]
        assert call_kwargs["alert_severity"] == "CRITICAL"
        assert call_kwargs["alert_action"] == "PAGE_SRE_ONCALL"
        assert call_kwargs["component"] == "scheduled_check"
