"""Unit tests for ScheduledViolationDetector (S4T2)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.platform.idempotency.violation_detector import ScheduledViolationDetector


@pytest.mark.asyncio
async def test_scheduled_check_advisory_lock_skipped_if_already_running():
    """Verify check skips if another replica holds advisory lock."""
    mock_session = AsyncMock()
    mock_scalar = MagicMock()
    mock_scalar.scalar_one.return_value = False
    mock_session.execute.return_value = mock_scalar

    detector = ScheduledViolationDetector(mock_session)
    res = await detector.run_scheduled_check()

    assert res.ran is False
    assert res.violations_detected == 0


@pytest.mark.asyncio
async def test_scheduled_check_detects_ledger_duplicate_and_dispatches_alert():
    """Verify duplicate ledger transaction produces violation alert."""
    mock_session = AsyncMock()

    # Lock result: acquired (True)
    lock_res = MagicMock()
    lock_res.scalar_one.return_value = True

    # Query 1 (ledger_transaction, same settlement_id + leg under a drifted key): duplicate found
    ledger_row = MagicMock()
    ledger_row.settlement_id = "22222222-2222-2222-2222-222222222222"
    ledger_row.leg = "customer_credit"
    ledger_row.execution_count = 2
    ledger_row.involved_object_ids = ["tx-1", "tx-2"]
    ledger_row.scope = "service-a"
    ledger_row.correlation_id = "corr-ledger-1"
    ledger_res = MagicMock()
    ledger_res.fetchall.return_value = [ledger_row]

    # Query 2A (settlement join): Empty
    empty_res2 = MagicMock()
    empty_res2.fetchall.return_value = []

    # Query 2B (settlement correlation duplicates): Empty
    empty_res3 = MagicMock()
    empty_res3.fetchall.return_value = []

    # Query 3 (rails): Empty
    empty_res4 = MagicMock()
    empty_res4.fetchall.return_value = []

    mock_session.execute.side_effect = [
        lock_res,
        ledger_res,
        empty_res2,
        empty_res3,
        empty_res4,
    ]

    detector = ScheduledViolationDetector(mock_session)

    with patch(
        "app.platform.idempotency.violation_detector.dispatch_violation_alert",
        new_callable=AsyncMock,
    ) as mock_alert:
        res = await detector.run_scheduled_check()

        assert res.ran is True
        assert res.violations_detected == 1
        assert res.details[0]["key_value"] == "settle:22222222-2222-2222-2222-222222222222:customer_credit"
        assert res.details[0]["operation_type"] == "ledger_posting"

        mock_alert.assert_called_once()
        kwargs = mock_alert.call_args[1]
        assert kwargs["key_value"] == "settle:22222222-2222-2222-2222-222222222222:customer_credit"
        assert kwargs["execution_count"] == 2
