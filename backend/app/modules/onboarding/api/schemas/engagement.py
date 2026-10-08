"""Request/response schemas for contacts and the activity log (architecture §8.1, §9.3).

Split out of `exporter.py` so the company shapes and the engagement
shapes stop sharing one file. The contact and activity classes are unchanged from
that split; the class names are what the OpenAPI document and the frontend's
generated types key on, so they stay exactly as they were.

The conversation shapes are added at the end, under their own heading.
Follow-ups add **no** class here: their completion shapes live in
`api/schemas/follow_up.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    computed_field,
    field_validator,
)

from app.modules.onboarding.api.schemas.masking import (
    NotMasked,
    can_reveal_identifiers,
    mask_email,
    mask_phone,
)
from app.modules.onboarding.domain.engagement_views import ConversationView
from app.modules.onboarding.domain.entities.engagement_enums import (
    ContactStatus,
    ExporterActivityType,
    ExporterConversation,
)
from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney
from app.platform.authentication.models import User
from app.platform.configuration.config import settings

#: A contact's name, trimmed before it is measured: "   " is not a name, and without the
#: trim it would pass ``min_length=1`` and save a contact nobody can find or act on.
ContactName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]


class AddExporterContactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ContactName
    role: str | None = Field(default=None, max_length=255)
    email: Annotated[str | None, NotMasked] = Field(default=None, max_length=255)
    phone: Annotated[str | None, NotMasked] = Field(default=None, max_length=50)
    department: str | None = Field(default=None, max_length=255)
    is_primary: bool = False


class UpdateExporterContactRequest(BaseModel):
    """A partial edit: only the fields actually sent are changed.

    Every field defaults to ``None`` **and** is nullable, which on its own would make
    "leave the phone alone" and "clear the phone" the same request. ``changes()`` below
    tells them apart with ``model_fields_set``, so the router passes on the keys that
    were really in the body — a field left out is untouched, a field sent as ``null`` is
    cleared.

    ``name`` is the exception: it may be changed but not removed, because a contact with
    no name is a row nobody can act on. ``ContactName`` refuses "" and a name of spaces;
    ``_not_null`` refuses an explicit ``null``, which the type alone would
    let through as "leave it alone" and so drop silently.
    """

    model_config = ConfigDict(extra="forbid")

    name: ContactName | None = None
    role: str | None = Field(default=None, max_length=255)
    email: Annotated[str | None, NotMasked] = Field(default=None, max_length=255)
    phone: Annotated[str | None, NotMasked] = Field(default=None, max_length=50)
    department: str | None = Field(default=None, max_length=255)
    is_primary: bool | None = None

    @field_validator("name", "is_primary", mode="before")
    @classmethod
    def _not_null(cls, value: object, info: ValidationInfo) -> object:
        # Runs only for a key that was sent, so a body without `name` is untouched.
        # `is_primary` is a yes/no: null is neither, and reading it as "leave it" would
        # hide a client bug the same way.
        if value is None:
            raise ValueError(
                f"{info.field_name} cannot be null; leave it out to keep it unchanged"
            )
        return value

    def changes(self) -> dict[str, object]:
        """The fields this request actually carried, under their column names.

        An empty body yields ``{}`` — a request that changes nothing, which the route
        refuses rather than answering 200 for a write that did not happen.
        """
        return {name: getattr(self, name) for name in self.model_fields_set}


class SetContactStatusRequest(BaseModel):
    """Move a contact to a status. Leaving ACTIVE needs a reason, which is kept."""

    model_config = ConfigDict(extra="forbid")

    status: ContactStatus
    reason: str | None = Field(default=None, max_length=2000)


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
    #: ACTIVE, INACTIVE or LEFT_COMPANY, with when and why it last changed.
    status: ContactStatus = ContactStatus.ACTIVE
    status_changed_at: datetime | None = None
    status_reason: str | None = None
    #: When someone last confirmed these details, and who (a user id).
    last_verified_at: datetime | None = None
    last_verified_by: str | None = None
    created_at: datetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def verification_due(self) -> bool:
        """An active contact whose details were last verified — or, never verified, were
        added — more than ``CRM_CONTACT_REVERIFY_MONTHS`` ago. Computed on read."""
        if self.status is not ContactStatus.ACTIVE:
            return False
        since = self.last_verified_at or self.created_at
        if since is None:
            return False
        months = settings.CRM_CONTACT_REVERIFY_MONTHS
        return datetime.now(UTC) - since > timedelta(days=round(months * 30.44))

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
    #: `AwareDatetime`, not `datetime`, as for a reschedule's `next_due_at`: the service
    #: compares it with an aware "now", and a value with no offset would raise there and
    #: surface as a 500. Refused here instead, as the 422 every other bad body gets.
    due_at: AwareDatetime | None = Field(
        default=None,
        description=(
            "When the follow-up is due, with a timezone offset (e.g. `Z` or `+05:30`). "
            "May not be in the past (ACTIVITY_DUE_IN_PAST)."
        ),
    )


class ExporterActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    activity_type: ExporterActivityType
    subject: str
    notes: str | None
    actor_id: str
    actor_name: str | None = Field(
        default=None,
        description=(
            "Who logged it, by name: the account's full name, or its email when it has "
            "none (DEVELOPER is given the full name only). Null when no account with a "
            "name matches `actor_id`. Resolved when read, not stored."
        ),
    )
    occurred_at: datetime
    due_at: datetime | None
    created_at: datetime

    def named(self, names: Mapping[str, str]) -> ExporterActivityResponse:
        """This activity with `actor_name` filled from `names` (`api/actor_names.py`)."""
        return self.model_copy(update={"actor_name": names.get(self.actor_id)})


class ExporterActivityListResponse(BaseModel):
    customer_id: uuid.UUID
    activities: list[ExporterActivityResponse]


class PendingActivityResponse(BaseModel):
    """One row of the cross-exporter pending/follow-up list. Unlike
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


# ── Conversation gauge ────────────────────────────────────────────────────


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
    "UpdateExporterContactRequest",
]
