"""Unit tests for IdempotencyViolationStreamProcessor (S4T2)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.platform.idempotency.models import IdempotencyRecord, IdempotencyStatus
from app.platform.idempotency.stream_processor import IdempotencyViolationStreamProcessor
from app.platform.messaging.schemas import EventEnvelope, EventType, Topic


@pytest.mark.asyncio
async def test_stream_processor_detects_realtime_duplicate_event():
    """Verify duplicate real-time Kafka event is detected within 30 seconds and dispatches alert."""
    mock_db = AsyncMock()

    # Query returns existing completed record
    rec1 = MagicMock(spec=IdempotencyRecord)
    rec1.id = "rec-id-1"
    rec1.status = IdempotencyStatus.COMPLETED
    rec2 = MagicMock(spec=IdempotencyRecord)
    rec2.id = "rec-id-2"
    rec2.status = IdempotencyStatus.COMPLETED

    res_mock = MagicMock()
    res_mock.scalars.return_value.all.return_value = [rec1, rec2]
    mock_db.execute.return_value = res_mock

    envelope = EventEnvelope(
        event_id="evt-dup-999",
        topic=Topic.SETTLEMENT,
        event_type=EventType.PAYMENT_CREATED,
        partition_key="cust-key-999",
        correlation_id="corr-stream-999",
        producer="settlement-service",
        payload={
            "idempotency_key": "cust-key-999",
            "scope_id": "customer-123",
        },
    )


    processor = IdempotencyViolationStreamProcessor()

    with patch("app.platform.idempotency.stream_processor.dispatch_violation_alert", new_callable=AsyncMock) as mock_alert:
        await processor.handle(mock_db, envelope)

        mock_alert.assert_called_once()
        kwargs = mock_alert.call_args[1]
        assert kwargs["key_value"] == "cust-key-999"
        assert kwargs["execution_count"] >= 2
        assert kwargs["correlation_id"] == "corr-stream-999"
