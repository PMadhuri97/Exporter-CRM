"""A real company for a test to hang child rows on.

Since migration 0014, contacts, activities, screening items and history rows
must point at a company that exists (``fk_<table>_customer_id``). A test that
used to invent ``uuid.uuid4()`` as a company id and write straight to a child
table now creates the company first with one of these.

Both insert a **bare** company row — no journey history row, no GSTINs — so a
test that counts the history rows it writes still sees only its own. They are
test scaffolding, not a way to create companies: the service
(``ExporterProfileService.create_or_get_profile``) is.

**Each has a relationship manager by default** — one shared, active OPERATIONS
fixture user (:func:`fixture_relationship_manager`), set directly with no history
row. Starting a background check and recording QUALIFIED need an RM on an
in-pipeline company, and a test about something else should not have to supply one.
Pass ``relationship_manager=False`` for a company with none.
"""

from __future__ import annotations

import uuid

from app.modules.onboarding.domain.entities.exporter_enums import ExporterSource
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.platform.authentication.models import UserRole
from app.platform.authentication.testing import create_user_direct
from app.platform.database import services as db_services

_FIXTURE_RM: dict[str, uuid.UUID] = {}


def fixture_relationship_manager() -> uuid.UUID:
    """The shared fixture RM: an active OPERATIONS user, created once per test run."""
    if "id" not in _FIXTURE_RM:
        _FIXTURE_RM["id"] = uuid.UUID(
            create_user_direct(
                f"fixture-rm-{uuid.uuid4().hex[:10]}@aner-test.com",
                UserRole.OPERATIONS,
                full_name="Fixture RM",
            )
        )
    return _FIXTURE_RM["id"]


async def make_company(
    customer_id: uuid.UUID | None = None, *, relationship_manager: bool = True
) -> uuid.UUID:
    """Insert a bare company through the ORM and return its id."""
    customer_id = customer_id or uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        db.add(
            ExporterProfile(
                customer_id=customer_id,
                source=ExporterSource.SALES,
                relationship_manager_user_id=(
                    fixture_relationship_manager() if relationship_manager else None
                ),
            )
        )
        await db.commit()
    return customer_id


async def ensure_relationship_manager(customer_id: uuid.UUID) -> uuid.UUID:
    """Give a company with no RM the fixture RM, directly (scaffolding, no history row).
    Returns the company's RM."""
    from sqlalchemy import update

    rm = fixture_relationship_manager()
    async with db_services.AsyncSessionLocal() as db:
        await db.execute(
            update(ExporterProfile)
            .where(
                ExporterProfile.customer_id == customer_id,
                ExporterProfile.relationship_manager_user_id.is_(None),
            )
            .values(relationship_manager_user_id=rm)
        )
        await db.commit()
    return rm


async def make_prospect(customer_id: uuid.UUID | None = None) -> uuid.UUID:
    """A company qualified to ``PROSPECT`` through the real ``QualificationService``.

    For a test that needs what only a prospect may have — above all a deal, which
    ``DealService.open_deal`` refuses to a ``LEAD`` (``DEAL_COMPANY_NOT_READY``).
    Driven through the service rather than by setting ``journey``, so the company
    holds exactly what a qualified company holds: a ``QUALIFIED`` outcome, with a
    ``qualification`` and a ``journey`` history row. Unlike ``make_company``, it is
    therefore not history-free.
    """
    # Imported here: the fixture module is imported by tests of every layer, and
    # most of them never need the application layer.
    from app.modules.onboarding.application.qualification_service import QualificationService
    from app.modules.onboarding.domain.entities.qualification_enums import (
        QualificationOutcomeValue,
    )

    customer_id = await make_company(customer_id)
    async with db_services.AsyncSessionLocal() as db:
        await QualificationService(db).record_outcome(
            customer_id, QualificationOutcomeValue.QUALIFIED, actor_id="test-fixture"
        )
    return customer_id


async def ensure_primary_contact(customer_id: uuid.UUID) -> None:
    """Give a company an active primary contact if it has none (scaffolding, no history
    row). A deal is handed over only when its seller has one, and a test about something
    else should not have to add it."""
    from sqlalchemy import exists, select

    from app.modules.onboarding.domain.entities.exporter_contact import ExporterContact

    async with db_services.AsyncSessionLocal() as db:
        has_one = await db.scalar(
            select(
                exists().where(
                    ExporterContact.customer_id == customer_id,
                    ExporterContact.is_primary_contact.is_(True),
                )
            )
        )
        if not has_one:
            db.add(
                ExporterContact(
                    customer_id=customer_id, name="Fixture Contact", is_primary_contact=True
                )
            )
            await db.commit()


def insert_company(cursor, customer_id: uuid.UUID | None = None) -> uuid.UUID:
    """Insert a bare company with raw SQL, for tests that bypass the ORM."""
    customer_id = customer_id or uuid.uuid4()
    cursor.execute(
        "INSERT INTO onboarding.exporter_profile (id, customer_id, source) "
        "VALUES (%s, %s, 'SALES')",
        (str(uuid.uuid4()), str(customer_id)),
    )
    return customer_id


__all__ = [
    "ensure_relationship_manager",
    "fixture_relationship_manager",
    "insert_company",
    "make_company",
    "make_prospect",
]
