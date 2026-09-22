"""Reads idempotency violations out of the audit log.

Satisfies ``app.platform.idempotency.ports.ViolationSource`` structurally, without
importing it. The violation detector writes each detection to ``audit_events`` with
event type ``IDEMPOTENCY_VIOLATION_EVENT_TYPE``; this is the read side, and it goes
through ``AuditEventRepository.query`` — the same newest-first filtered read the
audit API itself uses — rather than a second copy of that SQL.

WHICH CORRELATION ID
The detector stores the correlation ID twice: the original string in the payload,
and in the ``correlation_id`` column a UUID *derived* from it (uuid5) when the
original is not already a UUID, because the column is typed uuid. The derived value
matches nothing in any log line. The payload's is the one that traces end to end,
so that is the one returned.

A MALFORMED ROW DOES NOT FAIL THE PAGE
The payload is written by another component and read here as schemaless JSON. If a
row is missing a field, it is returned with that field empty and logged, rather than
raising — an investigation tool that 500s during an incident because one audit row
is short a key has failed at the one moment it was needed.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.domain.entities.audit import AuditEvent
from app.modules.audit.infrastructure.repository import AuditEventRepository
from app.shared.constants.idempotency import IDEMPOTENCY_VIOLATION_EVENT_TYPE
from app.shared.contracts.idempotency import ViolationPage, ViolationRecord

logger = structlog.get_logger(__name__)

#: Payload keys the detector writes and the investigation console depends on.
#: Checked on read so a writer that drops one shows up in the logs.
_EXPECTED_KEYS = (
    "key_value",
    "scope",
    "operation_type",
    "execution_count",
    "involved_object_ids",
    "correlation_id",
)


def _to_record(event: AuditEvent) -> ViolationRecord:
    payload: dict[str, Any] = event.payload if isinstance(event.payload, dict) else {}

    missing = [key for key in _EXPECTED_KEYS if key not in payload]
    if missing:
        logger.warning(
            "idempotency_violation_payload_incomplete",
            audit_event_id=str(event.id),
            missing_keys=missing,
        )

    count = payload.get("execution_count")
    involved = payload.get("involved_object_ids")
    return ViolationRecord(
        id=event.id,
        detected_at=event.created_at,
        key_value=payload.get("key_value"),
        scope=payload.get("scope"),
        operation_type=payload.get("operation_type"),
        execution_count=int(count) if count is not None else None,
        involved_object_ids=[str(i) for i in involved] if isinstance(involved, list) else [],
        correlation_id=payload.get("correlation_id"),
        violation_hash=payload.get("violation_hash"),
        already_alerted=payload.get("already_alerted"),
    )


class AuditViolationSource:
    """Newest-first, paginated violation records from the audit log."""

    def __init__(self, db: AsyncSession) -> None:
        self._events = AuditEventRepository(db)

    async def list_violations(self, *, limit: int, offset: int) -> ViolationPage:
        """Every recorded violation, most recent first.

        Every record, not one per incident. The detector re-records a violation on
        each scheduled run that still finds it, so an unresolved incident appears
        once per run with the same ``violation_hash``. Collapsing them here would
        make an audit log answer a question it was not asked; the hash is
        returned so a caller that wants one row per incident can group by it.
        """
        events = await self._events.query(
            event_type=IDEMPOTENCY_VIOLATION_EVENT_TYPE, skip=offset, limit=limit
        )
        total = await self._events.count(event_type=IDEMPOTENCY_VIOLATION_EVENT_TYPE)
        return ViolationPage(
            total=total,
            limit=limit,
            offset=offset,
            violations=[_to_record(event) for event in events],
        )
