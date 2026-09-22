import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.api_core.exceptions import Forbidden

from app.platform.audit_framework.services import AuditDispatcher
from app.platform.audit_framework.sink import AuditSinkLogger, verify_bucket_immutability


@pytest.fixture(autouse=True)
def clear_audit_sink():
    AuditSinkLogger.clear_recorded_entries()
    yield
    AuditSinkLogger.clear_recorded_entries()


def test_audit_sink_logger_emits_to_test_list():
    # Force test environment variable so it records in memory
    with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": "test_env"}):
        logger = AuditSinkLogger()
        logger.emit_audit_entry(
            idempotency_key="idemp-key-1",
            correlation_id="corr-id-1",
            transaction_type="posting",
            outcome="SUCCESS",
            rejection_reason=None,
        )

        entries = AuditSinkLogger.get_recorded_entries()
        assert len(entries) == 1
        assert entries[0]["idempotency_key"] == "idemp-key-1"
        assert entries[0]["outcome"] == "SUCCESS"


def test_verify_bucket_immutability_non_retention_forbidden_bubbles():
    # Mocking storage client to raise a non-retention Forbidden error
    with patch("google.cloud.storage.Client") as mock_client:
        mock_instance = mock_client.return_value
        mock_bucket = mock_instance.bucket.return_value
        mock_blob = mock_bucket.blob.return_value

        # Forbidden but with permission denied error (not retention)
        mock_blob.delete.side_effect = Forbidden("Access Denied: Missing permissions")

        with pytest.raises(Forbidden):
            verify_bucket_immutability("test-object.json")


def test_verify_bucket_immutability_retention_forbidden_caught():
    # Mocking storage client to raise a retention lock Forbidden error
    with patch("google.cloud.storage.Client") as mock_client:
        mock_instance = mock_client.return_value
        mock_bucket = mock_instance.bucket.return_value
        mock_blob = mock_bucket.blob.return_value

        mock_blob.delete.side_effect = Forbidden("Object is subject to bucket's retention policy (retentionPolicyNotMet)")

        res = verify_bucket_immutability("test-object.json")
        assert res["deleted"] is False
        assert res["immutable"] is True
        assert "retentionPolicyNotMet" in res["reason"]


@pytest.mark.asyncio
async def test_audit_dispatcher_acquires_lock_and_syncs():
    # Create dispatcher
    dispatcher = AuditDispatcher()

    # Mock DB session and execution
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    # 1. Advisory lock returned True
    mock_lock_res = MagicMock()
    mock_lock_res.scalar.return_value = True

    # 2. Query for AuditEvents (returns mock raw SQL rows)
    event_id = uuid.uuid4()
    mock_event = MagicMock()
    mock_event.id = event_id
    mock_event.event_type = "ledger.transaction.posted"
    mock_event.correlation_id = uuid.uuid4()
    mock_event.payload = {
        "idempotency_key": "idemp-key-123",
        "transaction_type": "posting",
    }
    mock_event.created_at = MagicMock()
    mock_event.created_at.isoformat.return_value = "2026-08-06T12:00:00Z"

    mock_query_res = MagicMock()
    mock_query_res.fetchall.return_value = [mock_event]

    # Setup execution return values:
    # First execute is pg_try_advisory_lock
    # Second execute is select audit_events SQL
    # Third execute is update audit_events SQL
    # Fourth execute is pg_advisory_unlock
    mock_session.execute.side_effect = [mock_lock_res, mock_query_res, MagicMock(), MagicMock()]

    # Mock AsyncSessionLocal to yield our session
    with patch("app.platform.audit_framework.services.AsyncSessionLocal", return_value=mock_session):
        with patch("app.platform.audit_framework.services.get_audit_sink_logger") as mock_sink_logger_getter:
            mock_sink_logger = mock_sink_logger_getter.return_value

            await dispatcher.sync_pending_events()

            # Assert that lock, select, update, and unlock were called
            assert mock_session.execute.call_count >= 4

            # Assert sink logger got the entry
            mock_sink_logger.emit_audit_entry.assert_called_once_with(
                idempotency_key="idemp-key-123",
                correlation_id=str(mock_event.correlation_id),
                transaction_type="posting",
                outcome="SUCCESS",
                rejection_reason=None,
                calling_service_identity=None,
                timestamp="2026-08-06T12:00:00Z",
                extra_fields={},
                event_type="ledger.transaction.posted",
            )

            # Assert update was called with the correct event id
            update_call = mock_session.execute.call_args_list[-2]
            assert "UPDATE audit.audit_events" in update_call[0][0].text
            assert update_call[0][1]["ids"] == [event_id]
            mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_sync_pending_events_lock_failed():
    # Test that if pg_try_advisory_lock returns False, the function returns early
    dispatcher = AuditDispatcher()

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.execute = AsyncMock()

    mock_lock_res = MagicMock()
    mock_lock_res.scalar.return_value = False
    mock_session.execute.side_effect = [mock_lock_res]

    with patch("app.platform.audit_framework.services.AsyncSessionLocal", return_value=mock_session):
        await dispatcher.sync_pending_events()

        # Verify pg_try_advisory_lock was called, but no select query, and no advisory unlock
        assert mock_session.execute.call_count == 1
        call_text = mock_session.execute.call_args_list[0][0][0].text
        assert "pg_try_advisory_lock" in call_text


@pytest.mark.asyncio
async def test_sync_pending_events_no_events():
    # Test that if lock is acquired but no events are fetched, the function releases the lock and returns
    dispatcher = AuditDispatcher()

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.execute = AsyncMock()

    mock_lock_res = MagicMock()
    mock_lock_res.scalar.return_value = True

    mock_query_res = MagicMock()
    mock_query_res.fetchall.return_value = []

    mock_session.execute.side_effect = [mock_lock_res, mock_query_res, MagicMock()]

    with patch("app.platform.audit_framework.services.AsyncSessionLocal", return_value=mock_session):
        await dispatcher.sync_pending_events()

        # Lock, Select, and Unlock were executed
        assert mock_session.execute.call_count == 3

        call_lock = mock_session.execute.call_args_list[0][0][0].text
        assert "pg_try_advisory_lock" in call_lock

        call_select = mock_session.execute.call_args_list[1][0][0].text
        assert "SELECT id, payload" in call_select

        call_unlock = mock_session.execute.call_args_list[2][0][0].text
        assert "pg_advisory_unlock" in call_unlock


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_type,expected_outcome",
    [
        ("ledger.transaction.posted", "SUCCESS"),
        ("ledger.transaction.failed", "FAILED"),
        ("ledger.transaction.rejected", "REJECTED"),
    ]
)
async def test_sync_pending_events_outcome_mapping(event_type, expected_outcome):
    # Test that event_type is mapped correctly to outcome
    dispatcher = AuditDispatcher()

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_lock_res = MagicMock()
    mock_lock_res.scalar.return_value = True

    mock_event = MagicMock()
    mock_event.id = uuid.uuid4()
    mock_event.event_type = event_type
    mock_event.correlation_id = uuid.uuid4()
    mock_event.payload = {
        "idempotency_key": "idemp-outcome-key",
        "transaction_type": "outcome-test",
    }
    mock_event.created_at = MagicMock()
    mock_event.created_at.isoformat.return_value = "2026-08-06T12:00:00Z"

    mock_query_res = MagicMock()
    mock_query_res.fetchall.return_value = [mock_event]

    mock_session.execute.side_effect = [mock_lock_res, mock_query_res, MagicMock(), MagicMock()]

    with patch("app.platform.audit_framework.services.AsyncSessionLocal", return_value=mock_session):
        with patch("app.platform.audit_framework.services.get_audit_sink_logger") as mock_sink_logger_getter:
            mock_sink_logger = mock_sink_logger_getter.return_value

            await dispatcher.sync_pending_events()

            mock_sink_logger.emit_audit_entry.assert_called_once_with(
                idempotency_key="idemp-outcome-key",
                correlation_id=str(mock_event.correlation_id),
                transaction_type="outcome-test",
                outcome=expected_outcome,
                rejection_reason=None,
                calling_service_identity=None,
                timestamp="2026-08-06T12:00:00Z",
                extra_fields={},
                event_type=event_type,
            )


@pytest.mark.asyncio
async def test_sync_pending_events_query_scoped_to_ledger_posting_event_types():
    # audit_events is shared by every module. The SELECT must filter to
    # ledger-posting event types, or it will forward compliance/settlement/
    # onboarding/etc. audit history to the ledger-posting GCP sink.
    dispatcher = AuditDispatcher()

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.execute = AsyncMock()

    mock_lock_res = MagicMock()
    mock_lock_res.scalar.return_value = True

    mock_query_res = MagicMock()
    mock_query_res.fetchall.return_value = []

    mock_session.execute.side_effect = [mock_lock_res, mock_query_res, MagicMock()]

    with patch("app.platform.audit_framework.services.AsyncSessionLocal", return_value=mock_session):
        await dispatcher.sync_pending_events()

        select_call = mock_session.execute.call_args_list[1]
        select_sql = select_call[0][0].text
        select_params = select_call[0][1]

        assert "event_type = ANY(:event_types)" in select_sql
        assert set(select_params["event_types"]) == {
            "ledger.transaction.posted",
            "ledger.transaction.failed",
            "ledger.transaction.rejected",
        }


@pytest.mark.asyncio
async def test_sync_pending_events_skips_unexpected_event_type():
    # Defensive path: even if a non-ledger row somehow reaches the loop (the
    # WHERE clause should prevent this — this simulates the query being wrong
    # in a future change), it must never be forwarded to GCP or marked synced.
    dispatcher = AuditDispatcher()

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_lock_res = MagicMock()
    mock_lock_res.scalar.return_value = True

    mock_event = MagicMock()
    mock_event.id = uuid.uuid4()
    mock_event.event_type = "compliance.screening.completed"
    mock_event.correlation_id = uuid.uuid4()
    mock_event.payload = {"idempotency_key": "should-not-be-sent"}
    mock_event.created_at = MagicMock()
    mock_event.created_at.isoformat.return_value = "2026-08-06T12:00:00Z"

    mock_query_res = MagicMock()
    mock_query_res.fetchall.return_value = [mock_event]

    # Lock, select, unlock — no UPDATE call expected, since nothing gets synced.
    mock_session.execute.side_effect = [mock_lock_res, mock_query_res, MagicMock()]

    with patch("app.platform.audit_framework.services.AsyncSessionLocal", return_value=mock_session):
        with patch("app.platform.audit_framework.services.get_audit_sink_logger") as mock_sink_logger_getter:
            mock_sink_logger = mock_sink_logger_getter.return_value

            await dispatcher.sync_pending_events()

            mock_sink_logger.emit_audit_entry.assert_not_called()
            mock_session.commit.assert_not_called()
            # Only 3 execute calls: lock, select, unlock — no UPDATE.
            assert mock_session.execute.call_count == 3


@pytest.mark.asyncio
async def test_sync_pending_events_correlation_and_rejection_extraction():
    # Test extraction of correlation_id and rejection_reason from different payload variations
    dispatcher = AuditDispatcher()

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_lock_res = MagicMock()
    mock_lock_res.scalar.return_value = True

    # Event 1: No DB correlation_id, uses payload correlation_id, uses payload rejection_reason
    mock_event_1 = MagicMock()
    mock_event_1.id = uuid.uuid4()
    mock_event_1.event_type = "ledger.transaction.rejected"
    mock_event_1.correlation_id = None
    mock_event_1.payload = {
        "idempotency_key": "idemp-1",
        "correlation_id": "payload-corr-id-1",
        "rejection_reason": "Limit exceeded",
    }
    mock_event_1.created_at = MagicMock()
    mock_event_1.created_at.isoformat.return_value = "2026-08-06T12:00:00Z"

    # Event 2: Uses DB correlation_id, uses payload reason instead of rejection_reason
    mock_event_2 = MagicMock()
    mock_event_2.id = uuid.uuid4()
    mock_event_2.event_type = "ledger.transaction.rejected"
    mock_event_2.correlation_id = uuid.UUID("11111111-2222-3333-4444-555555555555")
    mock_event_2.payload = {
        "idempotency_key": "idemp-2",
        "reason": "Insufficient balance",
    }
    mock_event_2.created_at = MagicMock()
    mock_event_2.created_at.isoformat.return_value = "2026-08-06T13:00:00Z"

    mock_query_res = MagicMock()
    mock_query_res.fetchall.return_value = [mock_event_1, mock_event_2]

    mock_session.execute.side_effect = [mock_lock_res, mock_query_res, MagicMock(), MagicMock()]

    with patch("app.platform.audit_framework.services.AsyncSessionLocal", return_value=mock_session):
        with patch("app.platform.audit_framework.services.get_audit_sink_logger") as mock_sink_logger_getter:
            mock_sink_logger = mock_sink_logger_getter.return_value

            await dispatcher.sync_pending_events()

            assert mock_sink_logger.emit_audit_entry.call_count == 2

            # Assert Event 1 calls
            mock_sink_logger.emit_audit_entry.assert_any_call(
                idempotency_key="idemp-1",
                correlation_id="payload-corr-id-1",
                transaction_type="posting",
                outcome="REJECTED",
                rejection_reason="Limit exceeded",
                calling_service_identity=None,
                timestamp="2026-08-06T12:00:00Z",
                extra_fields={},
                event_type="ledger.transaction.rejected",
            )

            # Assert Event 2 calls
            mock_sink_logger.emit_audit_entry.assert_any_call(
                idempotency_key="idemp-2",
                correlation_id="11111111-2222-3333-4444-555555555555",
                transaction_type="posting",
                outcome="REJECTED",
                rejection_reason="Insufficient balance",
                calling_service_identity=None,
                timestamp="2026-08-06T13:00:00Z",
                extra_fields={"reason": "Insufficient balance"},
                event_type="ledger.transaction.rejected",
            )


@pytest.mark.asyncio
async def test_sync_pending_events_extra_fields_filtering():
    # Test that extra details payload fields are correctly filtered and passed
    dispatcher = AuditDispatcher()

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_lock_res = MagicMock()
    mock_lock_res.scalar.return_value = True

    mock_event = MagicMock()
    mock_event.id = uuid.uuid4()
    mock_event.event_type = "ledger.transaction.posted"
    mock_event.correlation_id = uuid.uuid4()
    mock_event.payload = {
        "idempotency_key": "idemp-key",
        "correlation_id": "ignore-this-correlation-id",
        "transaction_type": "posting",
        "outcome": "ignore-this-outcome",
        "rejection_reason": "ignore-this",
        "calling_service_identity": "ignore-this",
        "custom_metadata_field": "val1",
        "nested_info": {"nested_key": "nested_val"},
    }
    mock_event.created_at = MagicMock()
    mock_event.created_at.isoformat.return_value = "2026-08-06T12:00:00Z"

    mock_query_res = MagicMock()
    mock_query_res.fetchall.return_value = [mock_event]

    mock_session.execute.side_effect = [mock_lock_res, mock_query_res, MagicMock(), MagicMock()]

    with patch("app.platform.audit_framework.services.AsyncSessionLocal", return_value=mock_session):
        with patch("app.platform.audit_framework.services.get_audit_sink_logger") as mock_sink_logger_getter:
            mock_sink_logger = mock_sink_logger_getter.return_value

            await dispatcher.sync_pending_events()

            mock_sink_logger.emit_audit_entry.assert_called_once_with(
                idempotency_key="idemp-key",
                correlation_id=str(mock_event.correlation_id),
                transaction_type="posting",
                outcome="SUCCESS",
                rejection_reason="ignore-this",
                calling_service_identity="ignore-this",
                timestamp="2026-08-06T12:00:00Z",
                extra_fields={
                    "custom_metadata_field": "val1",
                    "nested_info": {"nested_key": "nested_val"},
                },
                event_type="ledger.transaction.posted",
            )


@pytest.mark.asyncio
async def test_sync_pending_events_dispatch_exception_skips_event_but_continues_batch():
    # A single event that fails to dispatch (e.g. a transient GCP error, or a
    # permanently malformed row) must not block every other event behind it in
    # the batch — only the failing event is skipped and left for retry next
    # cycle; events after it still get a chance to dispatch this cycle.
    dispatcher = AuditDispatcher()

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_lock_res = MagicMock()
    mock_lock_res.scalar.return_value = True

    event_1_id = uuid.uuid4()
    mock_event_1 = MagicMock()
    mock_event_1.id = event_1_id
    mock_event_1.event_type = "ledger.transaction.posted"
    mock_event_1.correlation_id = uuid.uuid4()
    mock_event_1.payload = {"idempotency_key": "idemp-key-1"}
    mock_event_1.created_at = MagicMock()
    mock_event_1.created_at.isoformat.return_value = "2026-08-06T12:00:00Z"

    # event_2 is the poison pill — it raises every time it's attempted.
    event_2_id = uuid.uuid4()
    mock_event_2 = MagicMock()
    mock_event_2.id = event_2_id
    mock_event_2.event_type = "ledger.transaction.posted"
    mock_event_2.correlation_id = uuid.uuid4()
    mock_event_2.payload = {"idempotency_key": "idemp-key-2"}
    mock_event_2.created_at = MagicMock()
    mock_event_2.created_at.isoformat.return_value = "2026-08-06T13:00:00Z"

    # event_3 is behind the poison pill in the batch and must still dispatch.
    event_3_id = uuid.uuid4()
    mock_event_3 = MagicMock()
    mock_event_3.id = event_3_id
    mock_event_3.event_type = "ledger.transaction.posted"
    mock_event_3.correlation_id = uuid.uuid4()
    mock_event_3.payload = {"idempotency_key": "idemp-key-3"}
    mock_event_3.created_at = MagicMock()
    mock_event_3.created_at.isoformat.return_value = "2026-08-06T14:00:00Z"

    mock_query_res = MagicMock()
    mock_query_res.fetchall.return_value = [mock_event_1, mock_event_2, mock_event_3]

    mock_session.execute.side_effect = [mock_lock_res, mock_query_res, MagicMock(), MagicMock()]

    with patch("app.platform.audit_framework.services.AsyncSessionLocal", return_value=mock_session):
        with patch("app.platform.audit_framework.services.get_audit_sink_logger") as mock_sink_logger_getter:
            mock_sink_logger = mock_sink_logger_getter.return_value

            mock_sink_logger.emit_audit_entry.side_effect = [
                {"status": "emitted"},
                Exception("GCP Log Sink connection timeout"),
                {"status": "emitted"},
            ]

            await dispatcher.sync_pending_events()

            # All three were attempted — the failure on event_2 didn't stop the loop.
            assert mock_sink_logger.emit_audit_entry.call_count == 3

            # event_1 and event_3 are marked synced; event_2 (the poison pill) is not,
            # so it's retried next cycle instead of jamming everything behind it.
            update_call = mock_session.execute.call_args_list[-2]
            assert "UPDATE audit.audit_events" in update_call[0][0].text
            assert set(update_call[0][1]["ids"]) == {event_1_id, event_3_id}
            mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_sync_pending_events_db_exception_rolls_back():
    # Test that DB exception during dispatching rolls back transaction and bubbles exception up
    dispatcher = AuditDispatcher()

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.execute = AsyncMock()
    mock_session.commit = MagicMock()
    mock_session.rollback = AsyncMock()

    mock_lock_res = MagicMock()
    mock_lock_res.scalar.return_value = True

    # Query execute raises DB API Exception
    mock_session.execute.side_effect = [
        mock_lock_res,
        Exception("Postgres connection dropped unexpectedly"),
        MagicMock() # for unlock
    ]

    with patch("app.platform.audit_framework.services.AsyncSessionLocal", return_value=mock_session):
        with pytest.raises(Exception, match="Postgres connection dropped unexpectedly"):
            await dispatcher.sync_pending_events()

        mock_session.rollback.assert_called_once()
        # Verify unlock is always executed in the finally block
        unlock_call = mock_session.execute.call_args_list[-1]
        assert "pg_advisory_unlock" in unlock_call[0][0].text
