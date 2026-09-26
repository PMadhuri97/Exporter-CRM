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

from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterLifecycleStatus,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.platform.database import services as db_services


async def make_company(
    customer_id: uuid.UUID | None = None,
    *,
    lifecycle_status: ExporterLifecycleStatus = ExporterLifecycleStatus.LEAD,
) -> uuid.UUID:
    """Insert a bare company through the ORM and return its id."""
    customer_id = customer_id or uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        db.add(
            ExporterProfile(
                customer_id=customer_id,
                source=ExporterSource.SALES,
                lifecycle_status=lifecycle_status,
            )
        )
        await db.commit()
    return customer_id


def insert_company(cursor, customer_id: uuid.UUID | None = None) -> uuid.UUID:
    """Insert a bare company with raw SQL, for tests that bypass the ORM."""
    customer_id = customer_id or uuid.uuid4()
    cursor.execute(
        "INSERT INTO onboarding.exporter_profile (id, customer_id, source, lifecycle_status) "
        "VALUES (%s, %s, 'SALES', 'LEAD')",
        (str(uuid.uuid4()), str(customer_id)),
    )
    return customer_id


__all__ = ["insert_company", "make_company"]
