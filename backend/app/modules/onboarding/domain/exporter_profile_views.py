"""Read-model view types for the company record (EXP-1) — **owner:
Developer 2** (architecture §8.1, §9.2).

Pure data structures — no I/O, no session — mirroring
``onboarding_request_views.py``'s pattern: ``ExporterProfileService``
assembles these from ORM rows; nothing here reaches for a database.

The contact, activity and pending-activity views moved to
``engagement_views.py`` (Developer 3) in L2-01. The detail view below still
embeds the first two, because the company page shows them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.modules.onboarding.domain.engagement_views import (
    ExporterActivityView,
    ExporterContactView,
)
from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterLifecycleStatus,
    ExporterSource,
)
from app.modules.onboarding.domain.onboarding_request_views import OnboardingHistoryEntry


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
    "ExporterProfileDetail",
    "ExporterProfileListItem",
]
