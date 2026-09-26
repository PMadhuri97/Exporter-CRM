"""Request/response schemas for contacts and the activity log — **owner:
Developer 3** (architecture §8.1, §9.3).

Split out of `exporter.py` (L2-01) so the company shapes and the engagement
shapes stop sharing one file. Every class below is unchanged; the class names
are what the OpenAPI document and the frontend's generated types key on, so
they stay exactly as they were.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.modules.onboarding.api.schemas.masking import (
    NotMasked,
    can_reveal_identifiers,
    mask_email,
    mask_phone,
)
from app.modules.onboarding.domain.entities.engagement_enums import ExporterActivityType
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


__all__ = [
    "AddExporterContactRequest",
    "ExporterActivityListResponse",
    "ExporterActivityResponse",
    "ExporterContactListResponse",
    "ExporterContactResponse",
    "LogExporterActivityRequest",
    "PendingActivityListResponse",
    "PendingActivityResponse",
]
