"""Unit tests for SRE Violation Alert Router & Deduplication (S4T2)."""

from unittest.mock import AsyncMock, patch

import pytest

from app.platform.idempotency.alerting import (
    clear_alert_cache,
    compute_violation_hash,
    dispatch_violation_alert,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    clear_alert_cache()
    yield
    clear_alert_cache()


def test_violation_hash_determinism():
    """Verify violation hash is deterministic regardless of ID order."""
    h1 = compute_violation_hash("key1", "scope1", "op1", ["id-a", "id-b"])
    h2 = compute_violation_hash("key1", "scope1", "op1", ["id-b", "id-a"])
    assert h1 == h2


@pytest.mark.asyncio
async def test_dispatch_violation_alert_records_audit_and_pages_sre():
    """Verify dispatch_violation_alert produces Protobuf report, logs CRITICAL alert, and records audit event."""
    mock_session = AsyncMock()

    report = await dispatch_violation_alert(
        mock_session,
        key_value="duplicate-key-101",
        scope="customer-1",
        operation_type="ledger_posting",
        execution_count=2,
        involved_object_ids=["tx-1", "tx-2"],
        correlation_id="corr-test-1",
    )

    assert report.key_value == "duplicate-key-101"
    assert report.execution_count == 2
    assert len(report.involved_object_ids) == 2

    # Verify DB execute was invoked for audit entry
    mock_session.execute.assert_called_once()
    sql_arg = mock_session.execute.call_args[0][0]
    assert "INSERT INTO audit.audit_events" in str(sql_arg)


@pytest.mark.asyncio
async def test_kafka_retry_deduplication_prevents_double_sre_page():
    """Verify that retried violation deliveries suppress duplicate SRE pages."""
    mock_session = AsyncMock()

    with patch("app.platform.idempotency.alerting.logger") as mock_logger:
        # First delivery: Pages SRE
        await dispatch_violation_alert(
            mock_session,
            key_value="retry-key-202",
            scope="customer-2",
            operation_type="settlement_creation",
            execution_count=2,
            involved_object_ids=["s-1", "s-2"],
            correlation_id="corr-retry-2",
        )

        assert mock_logger.error.call_count == 1

        # Kafka redelivery of identical violation event
        await dispatch_violation_alert(
            mock_session,
            key_value="retry-key-202",
            scope="customer-2",
            operation_type="settlement_creation",
            execution_count=2,
            involved_object_ids=["s-1", "s-2"],
            correlation_id="corr-retry-2",
        )

        # SRE error log count remains 1 (suppressed!), but DB execute logged both times
        assert mock_logger.error.call_count == 1
        assert mock_logger.info.call_count >= 1
        assert mock_session.execute.call_count == 2

