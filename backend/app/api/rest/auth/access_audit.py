"""The audit trail of who changed whose access.

Every change to a user account or a role — created, edited, activated or deactivated,
a password reset, a role's permissions replaced, a role deleted — is written to the
audit trail (`app.modules.audit`) in the same transaction as the change itself, so a
change and its record are committed together or not at all. There is no approval step:
one administrator acts and the change applies at once; this is the record of it.

Each event names its subject in the payload (``subject_type`` ``user`` or ``role``,
``subject_id``), which is what the two history routes read back, and lists what changed
as ``{"field", "from", "to"}`` — names rather than ids, so the history still reads
correctly after a role is renamed or deleted. A password is recorded as reset, never
with a value.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import ActorType, AuditService
from app.platform.authentication.models import User

USER = "user"
ROLE = "role"

USER_CREATED = "access.user_created"
USER_UPDATED = "access.user_updated"
USER_PASSWORD_RESET = "access.user_password_reset"
ROLE_CREATED = "access.role_created"
ROLE_UPDATED = "access.role_updated"
ROLE_DELETED = "access.role_deleted"

#: The events each kind of subject has — what the history lookup names, so it reads the
#: audit trail by its event-type index.
EVENT_TYPES: dict[str, frozenset[str]] = {
    USER: frozenset({USER_CREATED, USER_UPDATED, USER_PASSWORD_RESET}),
    ROLE: frozenset({ROLE_CREATED, ROLE_UPDATED, ROLE_DELETED}),
}


def change(field: str, before: Any, after: Any) -> dict[str, Any] | None:
    """One changed field, or ``None`` when nothing changed."""
    if before == after:
        return None
    return {"field": field, "from": before, "to": after}


def permission_change(
    before: set[tuple[str, str]], after: set[tuple[str, str]]
) -> dict[str, Any] | None:
    """A role's permission list, as what was added and what was removed."""
    added = sorted(f"{m}:{a}" for m, a in after - before)
    removed = sorted(f"{m}:{a}" for m, a in before - after)
    if not added and not removed:
        return None
    return {"field": "permissions", "added": added, "removed": removed}


async def record(
    db: AsyncSession,
    *,
    event_type: str,
    actor: User,
    subject_type: str,
    subject_id: uuid.UUID,
    subject_name: str | None,
    changes: list[dict[str, Any] | None],
) -> None:
    """Write one access event (flushes; the caller's commit makes it durable)."""
    await AuditService(db).record(
        event_type,
        actor_id=actor.id,
        actor_type=ActorType.COMPLIANCE_OFFICER,
        payload={
            "subject_type": subject_type,
            "subject_id": str(subject_id),
            "subject_name": subject_name,
            "actor_name": actor.full_name or actor.email,
            "changes": [c for c in changes if c is not None],
        },
    )


class AccessChangeResponse(BaseModel):
    field: str
    #: The value before and after, for a field that has one.
    from_value: Any = None
    to_value: Any = None
    #: For a role's permissions: what was added and what was removed.
    added: list[str] = []
    removed: list[str] = []


class AccessHistoryEntryResponse(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    #: ``access.user_created``, ``access.user_updated``, ``access.user_password_reset``,
    #: ``access.role_created``, ``access.role_updated`` or ``access.role_deleted``.
    event_type: str
    actor_id: uuid.UUID | None
    actor_name: str | None
    changes: list[AccessChangeResponse]


class AccessHistoryResponse(BaseModel):
    entries: list[AccessHistoryEntryResponse]
    total: int


async def history(
    db: AsyncSession, subject_type: str, subject_id: uuid.UUID, *, limit: int, offset: int
) -> AccessHistoryResponse:
    page = await AuditService(db).list_for_subject(
        subject_type,
        subject_id,
        event_types=EVENT_TYPES[subject_type],
        limit=limit,
        offset=offset,
    )
    entries = []
    for event in page.events:
        payload = event.payload or {}
        entries.append(
            AccessHistoryEntryResponse(
                id=event.event_id,
                occurred_at=event.created_at,
                event_type=event.event_type,
                actor_id=event.actor_id,
                actor_name=payload.get("actor_name"),
                changes=[
                    AccessChangeResponse(
                        field=c.get("field", ""),
                        from_value=c.get("from"),
                        to_value=c.get("to"),
                        added=c.get("added", []),
                        removed=c.get("removed", []),
                    )
                    for c in payload.get("changes", [])
                ],
            )
        )
    return AccessHistoryResponse(entries=entries, total=page.total)


__all__ = [
    "ROLE",
    "ROLE_CREATED",
    "ROLE_DELETED",
    "ROLE_UPDATED",
    "USER",
    "USER_CREATED",
    "USER_PASSWORD_RESET",
    "USER_UPDATED",
    "AccessHistoryResponse",
    "change",
    "history",
    "permission_change",
    "record",
]
