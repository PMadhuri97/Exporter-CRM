"""Integration tests for S4T2 Idempotency Violation Detection & Alerting against a REAL Postgres database."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.database import services as database
from app.platform.idempotency.alerting import (
    clear_alert_cache,
    dispatch_violation_alert,
)
from app.platform.idempotency.models import (
    IdempotencyKeyType,
    IdempotencyRecord,
    IdempotencyStatus,
)
from app.platform.idempotency.proto import ViolationReport
from app.platform.idempotency.stream_processor import IdempotencyViolationStreamProcessor
from app.platform.idempotency.violation_detector import ScheduledViolationDetector
from app.platform.messaging.schemas import EventEnvelope, EventType, Topic


@pytest.fixture(autouse=True)
def _reset_alert_cache():
    clear_alert_cache()
    yield
    clear_alert_cache()


@pytest.fixture
async def db():
    """Function-scoped AsyncSession using standard test database session factory."""
    async with database.AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@pytest.mark.asyncio
async def test_protobuf_binary_roundtrip():
    """Verify strictly-typed Protobuf ViolationReport binary serialization & deserialization."""
    report = ViolationReport(
        key_value="key-integration-100",
        scope="customer-account-500",
        operation_type="ledger_posting",
        execution_count=3,
        involved_object_ids=["obj-1", "obj-2", "obj-3"],
        correlation_id="corr-integration-999",
    )

    data_bytes = report.SerializeToString()
    assert isinstance(data_bytes, bytes)
    assert len(data_bytes) > 0

    restored = ViolationReport().ParseFromString(data_bytes)
    assert restored.key_value == "key-integration-100"
    assert restored.scope == "customer-account-500"
    assert restored.execution_count == 3
    assert restored.involved_object_ids == ["obj-1", "obj-2", "obj-3"]
    assert restored.correlation_id == "corr-integration-999"


@pytest.mark.asyncio
async def test_real_db_audit_log_insertion_casts(db: AsyncSession):
    """Verify dispatch_violation_alert executes SQL insert into real Postgres audit.audit_events with CAST syntax."""
    corr_id_str = f"corr-audit-test-{uuid.uuid4()}"
    key_val = f"key-audit-{uuid.uuid4()}"

    try:
        report = await dispatch_violation_alert(
            db,
            key_value=key_val,
            scope="customer-test-1",
            operation_type="ledger_posting",
            execution_count=2,
            involved_object_ids=["id-1", "id-2"],
            correlation_id=corr_id_str,
        )
        await db.commit()

        # Query real PostgreSQL audit.audit_events table
        query = text("""
            SELECT event_type, actor_type::text, correlation_id::text, payload
            FROM audit.audit_events
            WHERE payload->>'key_value' = :key_val;
        """)
        res = await db.execute(query, {"key_val": key_val})
        row = res.fetchone()

        assert row is not None
        assert row.event_type == "idempotency.violation_detected"
        assert row.actor_type == "SYSTEM"
        assert report.key_value == key_val
    finally:
        await db.rollback()


@pytest.mark.asyncio
async def test_real_db_ledger_drifted_key_duplicate_detected(db: AsyncSession):
    """Same settlement leg posted twice under two different idempotency_key formats
    (posting_key() vs. derive_internal_key()) must be detected — this is the actual
    "key deduplication failed" scenario: uq_ledger_txn_idem can't catch it because
    the two rows' idempotency_key values genuinely differ."""
    settlement_id = uuid.uuid4()
    corr_id = f"corr-ledger-dup-{uuid.uuid4()}"

    sql_insert = text("""
        INSERT INTO ledger.ledger_transaction (
            id, idempotency_key, transaction_type, status, correlation_id,
            settlement_id, created_by, metadata, posted_at
        ) VALUES (
            :id, :key, CAST('settlement_credit' AS ledger.ledger_transaction_type_enum),
            CAST('posted' AS ledger.ledger_transaction_status_enum), :corr_id,
            :settlement_id, 'integration-test', CAST(:metadata AS jsonb), NOW()
        );
    """)

    try:
        # posting_key() format
        await db.execute(sql_insert, {
            "id": uuid.uuid4(),
            "key": f"settle:{settlement_id}:customer_credit",
            "corr_id": corr_id,
            "settlement_id": settlement_id,
            "metadata": '{"leg": "customer_credit"}',
        })
        # derive_internal_key() format — same settlement, same leg, different key string
        await db.execute(sql_insert, {
            "id": uuid.uuid4(),
            "key": f"{settlement_id}:settlement_credit",
            "corr_id": corr_id,
            "settlement_id": settlement_id,
            "metadata": '{"leg": "customer_credit"}',
        })
        await db.commit()

        detector = ScheduledViolationDetector(db)
        result = await detector.run_scheduled_check()
        await db.commit()

        assert result.ran is True
        matching_violations = [
            d for d in result.details if d.get("key_value") == f"settle:{settlement_id}:customer_credit"
        ]
        assert len(matching_violations) == 1, f"Expected 1 matching violation, found {result.details=}"
        assert matching_violations[0]["execution_count"] == 2
        assert matching_violations[0]["operation_type"] == "ledger_posting"

    finally:
        await db.rollback()
        await db.execute(
            text("UPDATE ledger.ledger_transaction SET status = 'failed'::ledger.ledger_transaction_status_enum WHERE settlement_id = :settlement_id"),
            {"settlement_id": settlement_id},
        )
        await db.commit()


@pytest.mark.asyncio
async def test_real_db_ledger_legitimate_multi_leg_not_flagged(db: AsyncSession):
    """A normal settlement posting several distinct legs under one correlation_id
    (exactly what post_customer_debit/post_conversion/post_customer_credit do in
    ledger_postings.py) must NOT be flagged — only a repeated *leg* is a violation,
    not a repeated correlation_id."""
    settlement_id = uuid.uuid4()
    corr_id = f"corr-legit-multi-leg-{uuid.uuid4()}"

    sql_insert = text("""
        INSERT INTO ledger.ledger_transaction (
            id, idempotency_key, transaction_type, status, correlation_id,
            settlement_id, created_by, metadata, posted_at
        ) VALUES (
            :id, :key, CAST(:ttype AS ledger.ledger_transaction_type_enum),
            CAST('posted' AS ledger.ledger_transaction_status_enum), :corr_id,
            :settlement_id, 'integration-test', CAST(:metadata AS jsonb), NOW()
        );
    """)

    legs = [
        ("customer_debit", "settlement_debit", '{"leg": "customer_debit"}'),
        ("usdc_bridge", "fx_conversion", '{"leg": "usdc_bridge"}'),
        ("inr_conversion", "fx_conversion", '{"leg": "inr_conversion"}'),
        ("customer_credit", "settlement_credit", '{"leg": "customer_credit"}'),
    ]

    try:
        for leg_name, ttype, metadata in legs:
            await db.execute(sql_insert, {
                "id": uuid.uuid4(),
                "key": f"settle:{settlement_id}:{leg_name}",
                "ttype": ttype,
                "corr_id": corr_id,
                "settlement_id": settlement_id,
                "metadata": metadata,
            })
        await db.commit()

        detector = ScheduledViolationDetector(db)
        result = await detector.run_scheduled_check()
        await db.commit()

        matching_violations = [
            d for d in result.details if str(settlement_id) in d.get("key_value", "")
        ]
        assert matching_violations == [], (
            f"A legitimate 4-leg settlement must not be flagged as a violation, "
            f"found {matching_violations=}"
        )

    finally:
        await db.rollback()
        await db.execute(
            text("UPDATE ledger.ledger_transaction SET status = 'failed'::ledger.ledger_transaction_status_enum WHERE settlement_id = :settlement_id"),
            {"settlement_id": settlement_id},
        )
        await db.commit()


@pytest.mark.asyncio
async def test_real_db_settlement_duplicate_detection(db: AsyncSession):
    """Insert duplicate non-terminal settlement rows sharing correlation_id into real Postgres and run detector."""
    corr_id = f"corr-settle-dup-{uuid.uuid4()}"
    sender_id = uuid.uuid4()
    beneficiary_id = uuid.uuid4()

    sql_account = text("""
        INSERT INTO ledger.ledger_account (
            id, account_type, asset_code, precision, entity_id, entity_type, status, created_at
        ) VALUES (
            :id, 'clearing'::ledger.ledger_account_type_enum, :asset, 2, gen_random_uuid(), 'customer'::ledger.ledger_entity_type_enum, 'active'::ledger.ledger_account_status_enum, NOW()
        );
    """)

    sql_settlement = text("""
        INSERT INTO settlement.settlement (
            id, idempotency_key, correlation_id, status, sender_account_id, beneficiary_account_id, send_amount, send_asset_code, receive_asset_code, purpose_code, sector_code, edd_required, created_by, created_at
        ) VALUES (
            gen_random_uuid(), :key, :corr_id, 'initiated'::settlement.settlement_status_enum, :sender_id, :beneficiary_id, 5000, 'USD', 'INR', 'P0102', 'S001', false, 'integration-test', NOW()
        );
    """)

    try:
        await db.execute(sql_account, {"id": sender_id, "asset": "USD"})
        await db.execute(sql_account, {"id": beneficiary_id, "asset": "INR"})
        await db.execute(
            sql_settlement,
            {
                "key": f"s-key1-{uuid.uuid4()}",
                "corr_id": corr_id,
                "sender_id": sender_id,
                "beneficiary_id": beneficiary_id,
            },
        )
        await db.execute(
            sql_settlement,
            {
                "key": f"s-key2-{uuid.uuid4()}",
                "corr_id": corr_id,
                "sender_id": sender_id,
                "beneficiary_id": beneficiary_id,
            },
        )
        await db.commit()

        detector = ScheduledViolationDetector(db)
        result = await detector.run_scheduled_check()
        await db.commit()

        assert result.ran is True
        matching_violations = [
            d for d in result.details if d.get("correlation_id") == corr_id
        ]
        assert len(matching_violations) == 1, f"Expected 1 matching violation for {corr_id}, found {matching_violations=}"
        assert matching_violations[0]["execution_count"] == 2
        assert matching_violations[0]["operation_type"] == "settlement_creation"

    finally:
        await db.rollback()
        await db.execute(
            text("UPDATE settlement.settlement SET status = 'settled'::settlement.settlement_status_enum WHERE correlation_id = :corr_id"),
            {"corr_id": corr_id},
        )
        await db.execute(
            text("UPDATE ledger.ledger_account SET status = 'closed'::ledger.ledger_account_status_enum WHERE id IN (:id1, :id2)"),
            {"id1": sender_id, "id2": beneficiary_id},
        )
        await db.commit()


@pytest.mark.asyncio
async def test_real_db_stream_processor_replay_detection(db: AsyncSession):
    """Insert real completed IdempotencyRecord into Postgres and verify stream processor detects replay violation."""
    rec_id = uuid.uuid4()
    key_val = f"stream-replay-key-{uuid.uuid4()}"
    orig_corr = f"corr-orig-{uuid.uuid4()}"
    new_corr = f"corr-replay-{uuid.uuid4()}"

    rec = IdempotencyRecord(
        id=rec_id,
        key_value=key_val,
        scope_id="cust-stream-scope",
        key_type=IdempotencyKeyType.CUSTOMER_KEY,
        operation_type="settlement_creation",
        status=IdempotencyStatus.COMPLETED,
        correlation_id=orig_corr,
        completed_at=datetime.now(UTC),
    )

    try:
        db.add(rec)
        await db.commit()

        envelope = EventEnvelope(
            event_id=f"evt-{uuid.uuid4()}",
            topic=Topic.SETTLEMENT,
            event_type=EventType.PAYMENT_CREATED,
            partition_key=key_val,
            correlation_id=new_corr,  # Different correlation ID replay!
            payload={
                "idempotency_key": key_val,
                "scope_id": "cust-stream-scope",
            },
        )

        processor = IdempotencyViolationStreamProcessor()
        await processor.handle(db, envelope)
        await db.commit()

        # Verify audit event recorded for stream processor replay violation
        query = text("""
            SELECT payload FROM audit.audit_events
            WHERE payload->>'key_value' = :key_val;
        """)
        res = await db.execute(query, {"key_val": key_val})
        row = res.fetchone()

        assert row is not None
        assert row.payload["key_value"] == key_val
        assert row.payload["correlation_id"] == new_corr

    finally:
        await db.rollback()
        await db.execute(
            text("DELETE FROM ledger.idempotency_record WHERE id = :rec_id"),
            {"rec_id": rec_id},
        )
        await db.commit()
