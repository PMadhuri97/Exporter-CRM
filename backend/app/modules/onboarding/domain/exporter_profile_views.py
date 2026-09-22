"""Read-model view types for the Exporter CRM application services (EXP-1).

Pure data structures — no I/O, no session — mirroring
``onboarding_request_views.py``'s pattern: the application services
(``ExporterProfileService``, ``ExporterContactActivityService``) assemble
these from ORM rows; nothing here reaches for a database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterActivityType,
    ExporterLifecycleStatus,
    ExporterSource,
)
from app.modules.onboarding.domain.onboarding_request_views import OnboardingHistoryEntry


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


@dataclass(frozen=True)
class ExporterProfileDetail:
    """Result of ``ExporterProfileService.get_profile_detail``: the profile
    plus its contacts, recent activities, and linked ``OnboardingRequest``
    history — all queried by ``customer_id`` alone, no join table, per the
    confirmed plan that ``OnboardingRequest.customer_id`` already supports
    multiple historical rows.
    """

    customer_id: uuid.UUID
    gstin: str | None
    pan: str | None
    iec: str | None
    source: ExporterSource
    relationship_manager: str | None
    relationship_manager_user_id: uuid.UUID | None
    lifecycle_status: ExporterLifecycleStatus
    industry: str | None
    export_markets: list | None
    products: list | None
    year_established: int | None
    website: str | None
    date_added: datetime
    created_at: datetime
    updated_at: datetime
    contacts: tuple[ExporterContactView, ...]
    recent_activities: tuple[ExporterActivityView, ...]
    onboarding_history: tuple[OnboardingHistoryEntry, ...]


@dataclass(frozen=True)
class ExporterProfileListItem:
    """One row of ``ExporterProfileService.search_profiles``.

    Everything ``ExporterProfileDetail`` has except the per-exporter
    sub-collections (contacts/activities/history — too expensive to carry
    for every row of a list), plus ``legal_name``: resolved via the exact
    same "most recent ``OnboardingRequest`` per ``customer_id``" window-
    function join ``ExporterActivityRepository.list_pending`` already uses
    for ``PendingActivityView.exporter_display_name`` — see
    ``ExporterProfileRepository.search``. ``None`` for a bare Lead with no
    ``OnboardingRequest`` yet, same "nothing to match" case documented
    throughout this module.
    """

    customer_id: uuid.UUID
    legal_name: str | None
    gstin: str | None
    pan: str | None
    iec: str | None
    source: ExporterSource
    relationship_manager: str | None
    relationship_manager_user_id: uuid.UUID | None
    lifecycle_status: ExporterLifecycleStatus
    industry: str | None
    year_established: int | None
    date_added: datetime
    created_at: datetime
    updated_at: datetime


__all__ = [
    "ExporterActivityView",
    "ExporterContactView",
    "ExporterProfileDetail",
    "ExporterProfileListItem",
    "PendingActivityView",
]
