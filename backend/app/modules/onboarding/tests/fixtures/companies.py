"""A real company for a test to hang child rows on.

Since migration 0014, contacts, activities, screening items and history rows
must point at a company that exists (``fk_<table>_customer_id``). A test that
used to invent ``uuid.uuid4()`` as a company id and write straight to a child
table now creates the company first with one of these.

Both insert a **bare** company row — no journey history row, no GSTINs — so a
test that counts the history rows it writes still sees only its own. They are
test scaffolding, not a way to create companies: the service
(``ExporterProfileService.create_or_get_profile``) is.
"""

from __future__ import annotations

import uuid

from app.modules.onboarding.domain.entities.exporter_enums import ExporterSource
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.platform.database import services as db_services


async def make_company(customer_id: uuid.UUID | None = None) -> uuid.UUID:
    """Insert a bare company through the ORM and return its id."""
    customer_id = customer_id or uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        db.add(
            ExporterProfile(
                customer_id=customer_id,
                source=ExporterSource.SALES,
            )
        )
        await db.commit()
    return customer_id


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


def insert_company(cursor, customer_id: uuid.UUID | None = None) -> uuid.UUID:
    """Insert a bare company with raw SQL, for tests that bypass the ORM."""
    customer_id = customer_id or uuid.uuid4()
    cursor.execute(
        "INSERT INTO onboarding.exporter_profile (id, customer_id, source) "
        "VALUES (%s, %s, 'SALES')",
        (str(uuid.uuid4()), str(customer_id)),
    )
    return customer_id


__all__ = ["insert_company", "make_company", "make_prospect"]
