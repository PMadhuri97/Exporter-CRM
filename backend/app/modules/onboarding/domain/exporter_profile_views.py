"""Read-model view types for the company record (EXP-1) — **owner:
Developer 2** (architecture §8.1, §9.2).

Pure data structures — no I/O, no session — mirroring
``onboarding_request_views.py``'s pattern: ``ExporterProfileService``
assembles these from ORM rows; nothing here reaches for a database.

The contact, activity and pending-activity views moved to
``engagement_views.py`` (Developer 3) in L2-01. The detail view below still
embeds the first two, because the company page shows them.

``name`` and ``country`` are the company's identity
(``docs/contracts/company-record.md`` §2.1). They are ``None`` for a company
created without them, which the API still allows until migration 0014 makes
the name a required column on the company record.
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


@dataclass(frozen=True)
class CompanyIdentity:
    """What a company is called and where it is incorporated."""

    name: str
    country: str


@dataclass(frozen=True)
class ExporterProfileDetail:
    """Result of ``ExporterProfileService.get_profile_detail``: the company
    record, its identity, and the contacts and recent activities the company
    page shows.

    There is no onboarding-request history here any more. The company page
    used to derive the company's display name from it; the name is now part
    of the company's own identity (L2-03), and the legacy onboarding path's
    records stay where they are, served by that path's own routes.
    """

    customer_id: uuid.UUID
    name: str | None
    country: str | None
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


@dataclass(frozen=True)
class ExporterProfileListItem:
    """One row of ``ExporterProfileService.search_profiles``.

    Everything ``ExporterProfileDetail`` has except the per-company
    sub-collections (contacts and activities — too expensive to carry for
    every row of a list). The page's identities are fetched in one query for
    the whole page, never one per row.
    """

    customer_id: uuid.UUID
    name: str | None
    country: str | None
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
    "CompanyIdentity",
    "ExporterProfileDetail",
    "ExporterProfileListItem",
]
