"""Deterministic CRM sample data — **owner: Developer 2** (L2-05).

Run from ``backend/``::

    python -m app.modules.onboarding.sample_data

Migration 0014 starts the CRM fresh (architecture decision 1); this puts back
a small, known set of companies to build and demonstrate against. It is safe
to run as often as you like:

* **Fixed ids.** Every company's id is ``uuid5`` of a fixed namespace and its
  slug, so the same company is the same row on every machine and every run.
* **Converges, never duplicates.** Each step checks the current state first —
  a company that exists is not re-created, a contact or activity already
  logged (matched by name or subject) is not logged again, a journey already
  walked is continued from where it stands, a marker already set is left
  alone. A run interrupted halfway is finished by the next one.
* **Through the services.** Companies, journey moves and markers go through
  ``ExporterProfileService`` and contacts and activities through
  ``ExporterContactActivityService``, so every history row, check and
  constraint applies exactly as it does for a person using the CRM. Nothing is
  written to the legacy onboarding tables.

History rows it writes carry ``actor_id = None`` — the platform acting on its
own, per the history contract. Activities need a named actor, so they carry
``SAMPLE_DATA_ACTOR``.

**What it covers, and what it cannot yet.** Architecture §3.9 describes three
companies by journey, qualification, conversation, background check and
deals. The company record, identifiers, markers, contacts, activities and the
current ten-status journey exist today; the three-stage journey (L2-04),
qualification (L2-09/10), conversation (Dev 3), background check (Dev 4) and
deals (Dev 3) do not. Companies A, B and C are therefore seeded with what
exists, each carrying its §3.9 target in ``SampleCompany.target`` so the
owners of those pieces extend this file as they land.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

# Load the API package first, as the app does. Importing the `application`
# package first is circular in this module (its case service imports the API
# package, whose router imports back from `application`); the app never hits
# it because `app.main` loads the routers first. So neither does this.
import app.modules.onboarding.api  # noqa: F401, I001
from app.modules.onboarding.application.exporter_contact_activity_service import (
    ExporterContactActivityService,
)
from app.modules.onboarding.application.exporter_profile_service import (
    ExporterProfileService,
)
from app.modules.onboarding.domain.entities.engagement_enums import ExporterActivityType
from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterLifecycleStatus,
    ExporterMarker,
    ExporterSource,
)
from app.platform.database import services as db_services

#: Namespace for the companies' ``uuid5`` ids. Never change it: every
#: environment's sample companies would get new ids.
SAMPLE_NAMESPACE = uuid.UUID("5f1d7c1e-3a54-4d8e-9c1b-0e6f2a7d4c90")

#: The actor recorded on sample activities (the column is NOT NULL).
SAMPLE_DATA_ACTOR = "sample-data"

#: The old ten-status walk, used to reach each company's current status
#: through real, recorded transitions. Replaced by the three-stage journey in
#: L2-04.
_WALK: tuple[ExporterLifecycleStatus, ...] = (
    ExporterLifecycleStatus.LEAD,
    ExporterLifecycleStatus.CONTACTED,
    ExporterLifecycleStatus.DATA_COLLECTION,
    ExporterLifecycleStatus.VERIFICATION_IN_PROGRESS,
    ExporterLifecycleStatus.COMPLIANCE_REVIEW,
    ExporterLifecycleStatus.ONBOARDED,
    ExporterLifecycleStatus.ACTIVE,
)


@dataclass(frozen=True)
class SampleContact:
    name: str
    role: str
    email: str
    phone: str
    is_primary: bool = False


@dataclass(frozen=True)
class SampleActivity:
    activity_type: ExporterActivityType
    subject: str
    occurred_at: datetime
    notes: str | None = None
    due_at: datetime | None = None


@dataclass(frozen=True)
class SampleCompany:
    slug: str
    name: str
    country: str
    source: ExporterSource
    status: ExporterLifecycleStatus
    industry: str
    pan: str | None = None
    gstins: tuple[str, ...] = ()
    iec: str | None = None
    cin: str | None = None
    marker: ExporterMarker = ExporterMarker.NONE
    marker_reason: str | None = None
    contacts: tuple[SampleContact, ...] = ()
    activities: tuple[SampleActivity, ...] = ()
    #: Architecture §3.9's target state for this company, for the pieces that
    #: do not exist yet. Documentation, not data: nothing reads it.
    target: dict[str, str] = field(default_factory=dict)

    @property
    def customer_id(self) -> uuid.UUID:
        return uuid.uuid5(SAMPLE_NAMESPACE, self.slug)


def _at(day: int, hour: int = 10) -> datetime:
    """A fixed moment in September/October 2026, so every run logs the same
    times."""
    month, day = (9, day) if day <= 30 else (10, day - 30)
    return datetime(2026, month, day, hour, 0, tzinfo=UTC)


COMPANIES: tuple[SampleCompany, ...] = (
    # §3.9 Company A: a prospect who said "not now".
    SampleCompany(
        slug="company-a",
        name="Aarav Textiles Pvt Ltd",
        country="IN",
        source=ExporterSource.SALES,
        status=ExporterLifecycleStatus.CONTACTED,
        industry="Textiles",
        pan="AAACA1111A",
        gstins=("27AAACA1111A1Z5",),
        iec="AAACA1111A",
        cin="U17110MH2012PTC111111",
        contacts=(
            SampleContact("Priya Nair", "Finance Director", "priya.nair@aarav.example",
                          "+91 22 5550 1111", is_primary=True),
        ),
        activities=(
            SampleActivity(ExporterActivityType.CALL, "Intro call — interested, no need yet",
                           _at(10)),
            SampleActivity(ExporterActivityType.FOLLOW_UP, "Check back on Q1 shipments",
                           _at(12), notes="Said 'not now'; revisit in the new year.",
                           due_at=_at(45)),
        ),
        target={"journey": "PROSPECT", "qualification": "QUALIFIED",
                "conversation": "NOT_NOW", "background_check": "NOT_STARTED",
                "deals": "none"},
    ),
    # §3.9 Company B: a customer with two GSTINs (one per state).
    SampleCompany(
        slug="company-b",
        name="Bharat Precision Metals Ltd",
        country="IN",
        source=ExporterSource.REFERRAL,
        status=ExporterLifecycleStatus.ACTIVE,
        industry="Engineering goods",
        pan="AABCB2222B",
        gstins=("27AABCB2222B1Z5", "29AABCB2222B1ZX"),
        iec="AABCB2222B",
        cin="L27100MH2001PLC222222",
        contacts=(
            SampleContact("Rohan Mehta", "CFO", "rohan.mehta@bharatmetals.example",
                          "+91 22 5550 2222", is_primary=True),
            SampleContact("Anita Rao", "Export Manager", "anita.rao@bharatmetals.example",
                          "+91 80 5550 2223"),
        ),
        activities=(
            SampleActivity(ExporterActivityType.MEETING, "Deal review — two shipments to Rotterdam",
                           _at(14)),
        ),
        target={"journey": "CUSTOMER", "qualification": "QUALIFIED",
                "conversation": "READY_NOW", "background_check": "CLEAR",
                "deals": "two, one handed over"},
    ),
    # §3.9 Company C: a prospect whose background check is flagged.
    SampleCompany(
        slug="company-c",
        name="Coastal Seafood Exports Pvt Ltd",
        country="IN",
        source=ExporterSource.PARTNER,
        status=ExporterLifecycleStatus.DATA_COLLECTION,
        industry="Seafood",
        pan="AAACC3333C",
        gstins=("32AAACC3333C1Z1",),
        iec="AAACC3333C",
        contacts=(
            SampleContact("Joseph Varghese", "Managing Director", "joseph@coastalseafood.example",
                          "+91 484 555 3333", is_primary=True),
        ),
        activities=(
            SampleActivity(ExporterActivityType.CALL, "Needs financing for a Dubai order now",
                           _at(16)),
        ),
        target={"journey": "PROSPECT", "qualification": "QUALIFIED",
                "conversation": "READY_NOW", "background_check": "FLAGGED",
                "deals": "one open, cannot be handed over"},
    ),
    # A relationship on hold for business reasons (marker PAUSED).
    SampleCompany(
        slug="company-d-paused",
        name="Deccan Leather Works",
        country="IN",
        source=ExporterSource.EVENT,
        status=ExporterLifecycleStatus.CONTACTED,
        industry="Leather goods",
        pan="AAAFD4444D",
        gstins=("36AAAFD4444D1Z9",),
        marker=ExporterMarker.PAUSED,
        marker_reason="Factory closed for renovation until January",
    ),
    # A relationship that is over (marker ENDED): off the default list,
    # still found by search.
    SampleCompany(
        slug="company-e-ended",
        name="Eastern Spice Traders",
        country="IN",
        source=ExporterSource.MANUAL,
        status=ExporterLifecycleStatus.LEAD,
        industry="Spices",
        pan="AAAFE5555E",
        marker=ExporterMarker.ENDED,
        marker_reason="Exporter sold the business",
    ),
    # A lead entered before its PAN is known.
    SampleCompany(
        slug="company-f-new-lead",
        name="Falcon Agro Exports",
        country="IN",
        source=ExporterSource.MANUAL,
        status=ExporterLifecycleStatus.LEAD,
        industry="Agriculture",
    ),
    # A second record with Company B's Maharashtra GSTIN and no PAN — the
    # possible duplicate that decision 4 warns about instead of refusing.
    SampleCompany(
        slug="company-g-possible-duplicate",
        name="Bharat Metals (Pune office)",
        country="IN",
        source=ExporterSource.MANUAL,
        status=ExporterLifecycleStatus.LEAD,
        industry="Engineering goods",
        gstins=("27AABCB2222B1Z5",),
    ),
)


async def _ensure_company(company: SampleCompany) -> bool:
    """Create the company if it is missing; returns whether it was created."""
    async with db_services.AsyncSessionLocal() as db:
        _profile, created = await ExporterProfileService(db).create_or_get_profile(
            company.customer_id,
            source=company.source,
            name=company.name,
            country=company.country,
            pan=company.pan,
            gstins=list(company.gstins),
            iec=company.iec,
            cin=company.cin,
            industry=company.industry,
            actor_id=None,
            history_source="sample_data",
        )
    return created


async def _ensure_status(company: SampleCompany) -> int:
    """Walk the journey from wherever it stands to the company's status,
    through recorded transitions. Returns the number of moves made."""
    target = _WALK.index(company.status)
    moves = 0
    while True:
        async with db_services.AsyncSessionLocal() as db:
            service = ExporterProfileService(db)
            current = (await service.get_profile_detail(company.customer_id)).lifecycle_status
            position = _WALK.index(current)
            if position >= target:
                return moves
            await service.transition_lifecycle_status(
                company.customer_id,
                _WALK[position + 1],
                actor_id=None,  # type: ignore[arg-type]  # the platform acting
                compliance_authorized=True,
            )
        moves += 1


async def _ensure_marker(company: SampleCompany) -> bool:
    async with db_services.AsyncSessionLocal() as db:
        service = ExporterProfileService(db)
        current = (await service.get_profile_detail(company.customer_id)).marker
        if current is company.marker:
            return False
        await service.set_marker(
            company.customer_id, company.marker, reason=company.marker_reason, actor_id=None
        )
    return True


async def _ensure_contacts(company: SampleCompany) -> int:
    added = 0
    for contact in company.contacts:
        async with db_services.AsyncSessionLocal() as db:
            service = ExporterContactActivityService(db)
            existing = {c.name for c in await service.list_contacts(company.customer_id)}
            if contact.name in existing:
                continue
            await service.add_contact(
                company.customer_id,
                name=contact.name,
                role=contact.role,
                email=contact.email,
                phone=contact.phone,
                is_primary=contact.is_primary,
            )
        added += 1
    return added


async def _ensure_activities(company: SampleCompany) -> int:
    added = 0
    for activity in company.activities:
        async with db_services.AsyncSessionLocal() as db:
            service = ExporterContactActivityService(db)
            existing = {
                a.subject
                for a in await service.list_activities(company.customer_id, limit=200)
            }
            if activity.subject in existing:
                continue
            await service.log_activity(
                company.customer_id,
                activity_type=activity.activity_type,
                subject=activity.subject,
                actor_id=SAMPLE_DATA_ACTOR,
                notes=activity.notes,
                due_at=activity.due_at,
                occurred_at=activity.occurred_at,
            )
        added += 1
    return added


async def load_sample_data() -> dict[str, dict[str, int | bool]]:
    """Bring every sample company to its intended state. Returns what each
    step changed, per company — all zeros and ``False`` on a repeat run."""
    report: dict[str, dict[str, int | bool]] = {}
    for company in COMPANIES:
        report[company.slug] = {
            "created": await _ensure_company(company),
            "moves": await _ensure_status(company),
            "marker_set": await _ensure_marker(company),
            "contacts_added": await _ensure_contacts(company),
            "activities_added": await _ensure_activities(company),
        }
    return report


def main() -> None:
    report = asyncio.run(load_sample_data())
    for slug, changes in report.items():
        company = next(c for c in COMPANIES if c.slug == slug)
        summary = ", ".join(f"{key}={value}" for key, value in changes.items())
        print(f"{company.customer_id}  {company.name:<34} {summary}")


if __name__ == "__main__":
    main()


__all__ = ["COMPANIES", "SAMPLE_DATA_ACTOR", "SAMPLE_NAMESPACE", "load_sample_data"]
