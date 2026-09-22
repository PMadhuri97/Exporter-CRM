"""Case notes (ANER-4.3-S3T3).

`add_case_note` is deliberately narrow, matching the ticket: it appends one
`case_timeline_event` (`NOTE_ADDED`) and bumps `compliance_case.
last_updated_at` — it never changes `case_status`, so it does not go through
`CaseLifecycleService._transition`. It is still barred on a terminal case:
the Jira doc's S3T3 section states "Officers can add notes to a case at any
point in its lifecycle (except terminal states)", enforced here via
`CaseIsTerminalError`.

`MAX_NOTE_LENGTH` (10,000 characters) is the doc's own stated cap ("Notes
support plain-text content with a maximum length of 10,000 characters. For
Walk phase, no rich text or markdown rendering is required") — not asked for
in the task brief's own text, but cheap to enforce here at the same layer as
the empty-note check, and left out entirely would silently accept content the
spec says the console does not support.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cases.application.actor_validation import require_active_user
from app.modules.cases.domain.entities.case_timeline_event import CaseTimelineEvent
from app.modules.cases.domain.entities.compliance_case import ComplianceCase
from app.modules.cases.domain.entities.enums import (
    TERMINAL_CASE_STATUSES,
    ActorType,
    TimelineEventType,
)
from app.modules.cases.exceptions import CaseIsTerminalError, CaseNotFoundError
from app.shared.exceptions import ValidationError

#: Jira doc, S3T3: "Notes support plain-text content with a maximum length
#: of 10,000 characters."
MAX_NOTE_LENGTH = 10_000


class CaseNoteService:
    """Appends investigation notes to a case's timeline. Does not touch
    `case_status` — see the module docstring."""

    __slots__ = ()

    async def add_case_note(
        self,
        session: AsyncSession,
        case_id: uuid.UUID,
        note: str,
        actor_id: str,
        actor_type: ActorType,
    ) -> CaseTimelineEvent:
        """Append a `NOTE_ADDED` `case_timeline_event` to `case_id` and bump
        `compliance_case.last_updated_at`. Does not change `case_status`.

        Raises:
            CaseNotFoundError: no `compliance_case` row exists for `case_id`.
            CaseIsTerminalError: the case is `RESOLVED` or
                `CLOSED_WITHOUT_ACTION`.
            ValidationError: `note` is empty/whitespace-only, or exceeds
                `MAX_NOTE_LENGTH` characters.
            UserNotFoundOrInactiveError: `actor_id` is not a real, active
                platform user.
        """
        case = await session.get(ComplianceCase, case_id)
        if case is None:
            raise CaseNotFoundError(case_id)
        if case.case_status in TERMINAL_CASE_STATUSES:
            raise CaseIsTerminalError(case_id, case.case_status)
        if note is None or not note.strip():
            raise ValidationError("note must not be empty or whitespace-only")
        if len(note) > MAX_NOTE_LENGTH:
            raise ValidationError(f"note must not exceed {MAX_NOTE_LENGTH} characters")

        await require_active_user(session, actor_id, role="actor")

        event = CaseTimelineEvent(
            case_id=case_id,
            event_type=TimelineEventType.NOTE_ADDED,
            from_status=case.case_status.value,
            to_status=case.case_status.value,
            actor_id=actor_id,
            actor_type=actor_type,
            note=note,
            payload={},
        )
        session.add(event)
        case.last_updated_at = datetime.now(UTC)

        await session.commit()
        await session.refresh(event)
        return event


__all__ = ["CaseNoteService", "MAX_NOTE_LENGTH"]
