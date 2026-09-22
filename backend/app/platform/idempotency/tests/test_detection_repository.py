"""Duplicate detections, queried by operation type and detection window.

The three acceptance criteria this covers are about what the query returns and
what it must not conflate:

  individual records matching operation_type and time range
  a detected duplicate is returned here without being classified as a violation
  violations are served independently of these rows

The last two are one property from two directions, and the test that proves it
is ``test_a_detection_writes_no_violation_to_the_audit_log`` — it asserts the
absence of the thing that would make a detection look like a failure.

The window filters ``detected_at``, not ``original_executed_at``. A duplicate of
a months-old original caught yesterday belongs in yesterday's window; the two
timestamps are deliberately different columns and the wrong one would quietly
return the wrong set.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.platform.configuration.config import get_settings
from app.platform.idempotency.audit_repository import MAX_PAGE_SIZE
from app.platform.idempotency.detection_models import DuplicateDetection
from app.platform.idempotency.detection_repository import DuplicateDetectionRepository

NOW = datetime.now(UTC)


@pytest.fixture(scope="module")
def sync_engine():
    engine = create_engine(get_settings().DATABASE_SYNC_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(sync_engine):
    session = sessionmaker(bind=sync_engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def seeded(db_session):
    """Seeds detections, then removes them with the immutability trigger disabled."""
    ids: list[uuid.UUID] = []

    def _seed(
        *,
        operation_type: str,
        detected_at: datetime | None = None,
        original_executed_at: datetime | None = None,
        caller_identity: str = "probe-caller",
    ) -> DuplicateDetection:
        detection_id = uuid.uuid4()
        detected = detected_at or NOW
        original = original_executed_at or (detected - timedelta(milliseconds=250))
        row = DuplicateDetection(
            id=detection_id,
            idempotency_key=str(uuid.uuid4()),
            scope_id=str(uuid.uuid4()),
            operation_type=operation_type,
            original_request_ref=uuid.uuid4(),
            original_executed_at=original,
            detected_at=detected,
            caller_identity=caller_identity,
            correlation_id=str(uuid.uuid4()),
            time_since_original_ms=int((detected - original).total_seconds() * 1000),
            returned_result_ref=uuid.uuid4(),
        )
        db_session.add(row)
        db_session.flush()
        ids.append(detection_id)
        return row

    yield _seed

    db_session.rollback()
    db_session.execute(
        text(
            "ALTER TABLE ledger.duplicate_detection "
            "DISABLE TRIGGER duplicate_detection_immutable"
        )
    )
    try:
        for detection_id in ids:
            db_session.execute(
                text("DELETE FROM ledger.duplicate_detection WHERE id = :id"),
                {"id": str(detection_id)},
            )
    finally:
        db_session.execute(
            text(
                "ALTER TABLE ledger.duplicate_detection "
                "ENABLE TRIGGER duplicate_detection_immutable"
            )
        )
    db_session.commit()


# ── Matching operation type and window ────────────────────────────────────────


async def test_returns_the_individual_detections_for_an_operation(
    db_session, seeded
) -> None:
    operation = f"op-{uuid.uuid4()}"
    first = seeded(operation_type=operation, detected_at=NOW - timedelta(minutes=5))
    second = seeded(operation_type=operation, detected_at=NOW - timedelta(minutes=1))
    db_session.commit()

    page = await DuplicateDetectionRepository(db_session).list_by_operation(operation)

    assert page.total == 2
    # Newest first: an investigation starts from what just happened.
    assert [d.id for d in page.detections] == [second.id, first.id]


async def test_another_operation_type_is_not_returned(db_session, seeded) -> None:
    wanted = f"op-{uuid.uuid4()}"
    seeded(operation_type=wanted)
    seeded(operation_type=f"other-{uuid.uuid4()}")
    db_session.commit()

    page = await DuplicateDetectionRepository(db_session).list_by_operation(wanted)

    assert page.total == 1


async def test_the_window_bounds_detected_at(db_session, seeded) -> None:
    """Not original_executed_at — a duplicate of an old original caught today
    belongs to today."""
    operation = f"op-{uuid.uuid4()}"
    seeded(operation_type=operation, detected_at=NOW - timedelta(days=90))
    inside = seeded(
        operation_type=operation,
        detected_at=NOW - timedelta(hours=1),
        original_executed_at=NOW - timedelta(days=200),
    )
    db_session.commit()

    page = await DuplicateDetectionRepository(db_session).list_by_operation(
        operation, since=NOW - timedelta(days=1), until=NOW
    )

    assert [d.id for d in page.detections] == [inside.id]


async def test_every_field_survives_the_read(db_session, seeded) -> None:
    """The console renders these; a dropped column here is an empty cell there."""
    operation = f"op-{uuid.uuid4()}"
    row = seeded(operation_type=operation, caller_identity="the-retrying-service")
    db_session.commit()

    detection = (
        await DuplicateDetectionRepository(db_session).list_by_operation(operation)
    ).detections[0]

    assert detection.id == row.id
    assert detection.idempotency_key == row.idempotency_key
    assert detection.scope_id == row.scope_id
    assert detection.operation_type == operation
    assert detection.original_request_ref == row.original_request_ref
    assert detection.original_executed_at == row.original_executed_at
    assert detection.detected_at == row.detected_at
    assert detection.caller_identity == "the-retrying-service"
    assert detection.correlation_id == row.correlation_id
    assert detection.time_since_original_ms == row.time_since_original_ms
    assert detection.returned_result_ref == row.returned_result_ref


async def test_an_unknown_operation_returns_an_empty_page(db_session) -> None:
    page = await DuplicateDetectionRepository(db_session).list_by_operation(
        f"never-{uuid.uuid4()}"
    )
    assert page.total == 0
    assert page.detections == []


# ── Not violations ────────────────────────────────────────────────────────────


async def test_a_detection_writes_no_violation_to_the_audit_log(
    db_session, seeded
) -> None:
    """The criterion, from the direction that can actually fail.

    A detection is the control working. If recording one also produced a
    violation event, every routine client retry would page the SRE on-call.
    """
    operation = f"op-{uuid.uuid4()}"
    row = seeded(operation_type=operation)
    db_session.commit()

    violations = db_session.execute(
        text(
            "SELECT count(*) FROM audit.audit_events "
            "WHERE event_type LIKE '%violation%' "
            "AND payload::text LIKE :key"
        ),
        {"key": f"%{row.idempotency_key}%"},
    ).scalar_one()

    assert violations == 0


async def test_the_detection_shape_carries_no_violation_semantics() -> None:
    """No execution_count, no involved_object_ids, no severity.

    A detection records that an operation did *not* run twice. Any field
    implying it did would invite the console to render it as a failure.
    """
    from app.platform.idempotency.detection_repository import DetectionRecord

    fields = set(DetectionRecord.__dataclass_fields__)
    for violation_only in ("execution_count", "involved_object_ids", "severity", "violation_hash"):
        assert violation_only not in fields


# ── Pagination ────────────────────────────────────────────────────────────────


async def test_pagination_walks_without_repeating_or_skipping(
    db_session, seeded
) -> None:
    operation = f"op-{uuid.uuid4()}"
    for minute in range(6):
        seeded(operation_type=operation, detected_at=NOW - timedelta(minutes=minute))
    db_session.commit()

    repo = DuplicateDetectionRepository(db_session)
    seen: list[uuid.UUID] = []
    for offset in (0, 2, 4):
        page = await repo.list_by_operation(operation, limit=2, offset=offset)
        assert page.total == 6
        seen.extend(d.id for d in page.detections)

    assert len(seen) == 6
    assert len(set(seen)) == 6


async def test_the_page_size_is_capped(db_session, seeded) -> None:
    operation = f"op-{uuid.uuid4()}"
    seeded(operation_type=operation)
    db_session.commit()

    page = await DuplicateDetectionRepository(db_session).list_by_operation(
        operation, limit=MAX_PAGE_SIZE * 10
    )
    assert page.limit == MAX_PAGE_SIZE
