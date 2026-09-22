"""Reads the duplicate detection log.

Separate from ``IdempotencyAuditRepository`` because it reads a different thing.
That repository spans the hot registry and its archive as one collection;
``duplicate_detection`` is a single append-only table with no archive tier, so a
union here would be machinery with one branch.

A detection is the idempotency mechanism working — a key was re-presented and the
operation was not executed again. It is not a violation, which is a key that
failed to deduplicate and let a real duplicate through. Violations are recorded
in the audit log by the detection system and are read through a different
method; nothing in this module touches them, and nothing here should ever
present a detection as one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.platform.idempotency.audit_repository import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.platform.idempotency.detection_models import DuplicateDetection


@dataclass(frozen=True)
class DetectionRecord:
    """One duplicate that was recognised and short-circuited."""

    id: uuid.UUID
    idempotency_key: str
    scope_id: str
    operation_type: str
    original_request_ref: uuid.UUID
    original_executed_at: datetime
    detected_at: datetime
    caller_identity: str | None
    correlation_id: str | None
    time_since_original_ms: int
    returned_result_ref: uuid.UUID | None


@dataclass(frozen=True)
class DetectionPage:
    """A page of detections. ``total`` counts every match, independent of paging."""

    total: int
    limit: int
    offset: int
    detections: list[DetectionRecord]


def _to_record(row: DuplicateDetection) -> DetectionRecord:
    return DetectionRecord(
        id=row.id,
        idempotency_key=row.idempotency_key,
        scope_id=row.scope_id,
        operation_type=row.operation_type,
        original_request_ref=row.original_request_ref,
        original_executed_at=row.original_executed_at,
        detected_at=row.detected_at,
        caller_identity=row.caller_identity,
        correlation_id=row.correlation_id,
        time_since_original_ms=row.time_since_original_ms,
        returned_result_ref=row.returned_result_ref,
    )


class DuplicateDetectionRepository:
    """Read-only access to the duplicate detection log."""

    def __init__(self, db: AsyncSession | Session) -> None:
        self._db = db

    async def _execute(self, stmt: Any) -> Any:
        # Both session flavours, the same branch the rest of this package carries:
        # read-only tests use a plain Session so a never-committed SELECT does not
        # hold an asyncpg connection open into fixture teardown.
        if isinstance(self._db, AsyncSession):
            return await self._db.execute(stmt)
        return self._db.execute(stmt)

    async def list_by_operation(
        self,
        operation_type: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> DetectionPage:
        """Detections for this operation type in this window, most recent first.

        The predicate is equality on ``operation_type`` with a range on
        ``detected_at``, which is the shape ``ix_duplicate_detection_operation_detected``
        was built for — leading equality column, range and ordering on the second.

        Newest first, because an investigation starts from what just happened.
        ``id`` breaks ties: two detections of the same key from parallel callers
        can share a timestamp, and an ambiguous order would make paging skip and
        repeat rows depending on the plan.
        """
        limit = max(1, min(limit, MAX_PAGE_SIZE))
        offset = max(0, offset)

        criteria = [DuplicateDetection.operation_type == operation_type]
        if since is not None:
            criteria.append(DuplicateDetection.detected_at >= since)
        if until is not None:
            criteria.append(DuplicateDetection.detected_at <= until)

        page = (
            select(DuplicateDetection)
            .where(*criteria)
            .order_by(DuplicateDetection.detected_at.desc(), DuplicateDetection.id.desc())
            .limit(limit)
            .offset(offset)
        )
        counted = (
            select(func.count()).select_from(DuplicateDetection).where(*criteria)
        )

        rows = (await self._execute(page)).scalars().all()
        total = (await self._execute(counted)).scalar_one()
        return DetectionPage(
            total=total,
            limit=limit,
            offset=offset,
            detections=[_to_record(r) for r in rows],
        )
