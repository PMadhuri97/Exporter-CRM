"""Read-model view types for contacts and the activity log — **owner:
Developer 3** (architecture §8.1, §9.3).

Pure data structures — no I/O, no session — the same pattern as
``exporter_profile_views.py``, from which these were split (L2-01) unchanged.
``ExporterContactActivityService`` assembles the pending view; the company
detail view (``ExporterProfileDetail``, Developer 2) embeds the contact and
activity views because the company page shows them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.modules.onboarding.domain.entities.engagement_enums import ExporterActivityType


@dataclass(frozen=True)
class ExporterContactView:
    id: uuid.UUID
    customer_id: uuid.UUID
    name: str
    role: str | None
    email: str | None
    phone: str | None
    department: str | None
    is_primary_contact: bool


@dataclass(frozen=True)
class ExporterActivityView:
    id: uuid.UUID
    customer_id: uuid.UUID
    activity_type: ExporterActivityType
    subject: str
    notes: str | None
    actor_id: str
    occurred_at: datetime
    due_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class PendingActivityView:
    """One row of `ExporterContactActivityService.list_pending_activities`'s
    cross-exporter pending/follow-up list (Piece 2).

    Carries the exporter's display name alongside the activity itself so a
    Follow-ups screen never needs a second, per-row query to answer "pending,
    for which exporter" — `exporter_display_name` is resolved via one join in
    `ExporterActivityRepository.list_pending` (the same
    `OnboardingRequest.legal_name` this module's `search_profiles` already
    joins to), not a Python-side loop calling back into the database.
    `None` for a bare Lead whose `OnboardingRequest` (if any) has no name yet
    — same "nothing to match" case `search_profiles`'s `legal_name_contains`
    already documents.

    `is_overdue` is computed once, at view-construction time, against the
    same `now` the query itself was run with — never recomputed from a stale
    `datetime.now()` deeper in a template or a second pass over the list.
    """

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


__all__ = [
    "ExporterActivityView",
    "ExporterContactView",
    "PendingActivityView",
]
