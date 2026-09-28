"""The company share lock for writers of compliance inputs — **owner: Developer 4B**.

``docs/dev4/4b-task.md`` §6.2 invariant 6: Developer 4A decides the background
check under a ``SELECT … FOR UPDATE`` on the company row and reads the inputs
through ``ComplianceInputsService`` while it holds that lock. Every Dev4B write of
a company-scoped input — a screening decision; a verification result, a status
update or a review whose subject is the company — takes ``FOR SHARE`` on the same
row first, in the writer's own transaction. ``FOR SHARE`` conflicts with
``FOR UPDATE``, so a ``CLEAR`` and a new pending input cannot interleave: whichever
commits second sees the first. Share locks do not conflict with each other, so
Dev4B's writers never wait on one another because of it.

A separate module rather than a function in ``compliance_inputs.py``: the reader
there imports the screening catalogue from ``screening_review_service.py``, and the
screening service needs this lock, so housing it with the reader would be an import
cycle. It is also not the reader's — the reader never locks (§6.2 invariant 2).

A company id that matches no row locks nothing and is not an error here: whether a
write for an unknown company is refused, and how, is the writer's own rule. The ids
that *were* found are returned, so a writer can refuse an unknown company (404) from
the same statement that locked the known ones.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile


async def share_lock_companies(
    db: AsyncSession, company_ids: Iterable[uuid.UUID]
) -> frozenset[uuid.UUID]:
    """``SELECT … FOR SHARE`` on each company row, held until the caller's commit.

    Takes the locks in one statement, ordered by id, so two writers locking the
    same set of companies take them in the same order. Selects the key column
    only: the caller's identity map is not touched.

    Returns the ids that matched a company (and are now locked).
    """
    ids = set(company_ids)
    if not ids:
        return frozenset()
    result = await db.execute(
        select(ExporterProfile.customer_id)
        .where(ExporterProfile.customer_id.in_(ids))
        .order_by(ExporterProfile.customer_id)
        .with_for_update(read=True)
    )
    return frozenset(result.scalars().all())


__all__ = ["share_lock_companies"]
