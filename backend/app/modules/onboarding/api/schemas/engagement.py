"""Request/response schemas for contacts and the activity log — **owner:
Developer 3** (architecture §8.1, §9.3).

Split out of `exporter.py` (L2-01) so the company shapes and the engagement
shapes stop sharing one file. The contact and activity classes are unchanged from
that split; the class names are what the OpenAPI document and the frontend's
generated types key on, so they stay exactly as they were.

The conversation shapes (L3-03) are added at the end, under their own heading.
Phase 2 adds **no** class here: its completion shapes live in its own
`api/schemas/follow_up.py` (phase agreement §6.3).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.modules.onboarding.api.schemas.masking import (
    NotMasked,
    can_reveal_identifiers,
    mask_email,
    mask_phone,
)
from app.modules.onboarding.domain.engagement_views import ConversationView
from app.modules.onboarding.domain.entities.engagement_enums import (
    ExporterActivityType,
    ExporterConversation,
)
from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney
from app.platform.authentication.models import User


class AddExporterContactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    role: str | None = Field(default=None, max_length=255)
    email: Annotated[str | None, NotMasked] = Field(default=None, max_length=255)
    phone: Annotated[str | None, NotMasked] = Field(default=None, max_length=50)
    department: str | None = Field(default=None, max_length=255)
    is_primary: bool = False


class ExporterContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    name: str
    role: str | None
    email: str | None
    phone: str | None
    department: str | None
    is_primary_contact: bool

    def masked(self) -> ExporterContactResponse:
        return self.model_copy(
            update={"email": mask_email(self.email), "phone": mask_phone(self.phone)}
        )

    def masked_for(self, viewer: User) -> ExporterContactResponse:
        """Same reveal rule as the exporter's identifiers: COMPLIANCE and ADMIN
        see the contact's real email and phone, everyone else sees them
        masked."""
        if can_reveal_identifiers(viewer):
            return self
        return self.masked()


class ExporterContactListResponse(BaseModel):
    customer_id: uuid.UUID
    contacts: list[ExporterContactResponse]


class LogExporterActivityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_type: ExporterActivityType
    subject: str = Field(min_length=1, max_length=500)
    notes: str | None = None
    due_at: datetime | None = None


class ExporterActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    activity_type: ExporterActivityType
    subject: str
    notes: str | None
    actor_id: str
    occurred_at: datetime
    due_at: datetime | None
    created_at: datetime


class ExporterActivityListResponse(BaseModel):
    customer_id: uuid.UUID
    activities: list[ExporterActivityResponse]


class PendingActivityResponse(BaseModel):
    """One row of the cross-exporter pending/follow-up list (Piece 2). Unlike
    `ExporterActivityResponse`, this always carries `exporter_display_name`
    and `is_overdue` — there is no per-exporter context to fall back on, since
    this response spans every exporter."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    exporter_display_name: str | None
    activity_type: ExporterActivityType
    subject: str
    notes: str | None
    actor_id: str
    occurred_at: datetime
    due_at: datetime
    is_overdue: bool
    created_at: datetime


class PendingActivityListResponse(BaseModel):
    activities: list[PendingActivityResponse]
    limit: int
    offset: int


# ── Conversation gauge (L3-03, L3-04a) ────────────────────────────────────


class ConversationMoveResponse(BaseModel):
    """One move the signed-in user may make on this company's gauge.

    Served, never derived on the client (architecture §7.5). `reason_required`
    and `check_back_required` come from the same rule table the service enforces,
    so the screen and the server cannot drift apart.
    """

    model_config = ConfigDict(from_attributes=True)

    to: ExporterConversation
    reason_required: bool = Field(
        description="Whether this move is refused without a reason."
    )
    check_back_required: bool = Field(
        description="Whether this move is refused without a check-back date."
    )


class ConversationResponse(BaseModel):
    """The conversation gauge, its check-back date, and what may be done to it."""

    model_config = ConfigDict(from_attributes=True)

    company_id: uuid.UUID
    conversation: ExporterConversation
    #: Required but nullable, deliberately: the key is always present, and `null`
    #: means "no check-back date" rather than "the server did not say". An optional
    #: key would make a caller handle a third case that cannot happen.
    check_back_on: date | None = Field(
        description=(
            "The date a NOT_NOW conversation is to be picked up again. Null unless "
            "the conversation is NOT_NOW."
        ),
    )
    journey: ExporterJourney = Field(
        description=(
            "The company's journey. Present because the gauge applies from PROSPECT "
            "onward: on a LEAD there are no moves for that reason rather than "
            "because of the caller's role."
        )
    )
    #: Required, not defaulted: "which moves may I make" is part of the answer, and
    #: a default would make it absent from the schema as an optional key, leaving
    #: every caller to treat "no moves" and "not told" alike. An empty list is the
    #: real answer for a role that may not set the gauge and for a LEAD.
    allowed_moves: list[ConversationMoveResponse] = Field(
        description=(
            "The moves this caller may make now. Empty for a role that may not set "
            "the conversation, and empty on a LEAD."
        ),
    )

    @classmethod
    def from_view(
        cls, view: ConversationView, *, allowed_moves: list[ConversationMoveResponse]
    ) -> ConversationResponse:
        """Build the response from the service's view.

        `allowed_moves` is passed in rather than read off the view: the view holds
        what the *rules* allow and the route narrows it to what this *role* may
        do, which is the route's business (see `conversation_service.py`).
        """
        return cls(
            company_id=view.company_id,
            conversation=view.conversation,
            check_back_on=view.check_back_on,
            journey=view.journey,
            allowed_moves=allowed_moves,
        )


class ConversationMoveListResponse(BaseModel):
    """Just the allowed moves, for a caller that wants nothing else."""

    company_id: uuid.UUID
    conversation: ExporterConversation
    allowed_moves: list[ConversationMoveResponse]


class SetConversationRequest(BaseModel):
    """A conversation move.

    No `actor_id`: who did it comes from the login session, never from the body
    (architecture §7.5). No `from` value either — the server reads the current
    value under a row lock, so a client cannot assert what it is moving from.
    """

    model_config = ConfigDict(extra="forbid")

    conversation: ExporterConversation
    reason: str | None = Field(
        default=None,
        description=(
            "Why, in your words. Required for NOT_NOW; recorded in the company's "
            "history whenever given."
        ),
    )
    check_back_on: date | None = Field(
        default=None,
        description=(
            "When to pick this conversation back up. Required for NOT_NOW, today or "
            "later. Refused — not ignored — on any other move."
        ),
    )


__all__ = [
    "AddExporterContactRequest",
    "ConversationMoveListResponse",
    "ConversationMoveResponse",
    "ConversationResponse",
    "ExporterActivityListResponse",
    "ExporterActivityResponse",
    "ExporterContactListResponse",
    "ExporterContactResponse",
    "LogExporterActivityRequest",
    "PendingActivityListResponse",
    "PendingActivityResponse",
    "SetConversationRequest",
]
