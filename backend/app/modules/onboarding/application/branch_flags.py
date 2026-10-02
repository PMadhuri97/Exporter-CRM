"""``BranchFlagReader`` — is this GST registration flagged? — **owner: Developer 3**
(allocation F3; plan P6-5, P6-7).

The Protocol is **Developer 2's**, declared in ``domain/handover_conditions.py``
because their handover guard is its only consumer and F2 merged before F3. This module
provides the class that satisfies it; nothing here re-declares the Protocol, and
nothing here injects it — ``DealService`` choosing to use it is Developer 2's task 2.9.

**This is the F3 stub: it answers "not flagged" for everything.** The real reader is
task 3.14, and it needs the columns task 3.12 adds to ``exporter_gstin``
(``flag_status``, ``flag_reason``, ``state_name``) — none of which exist yet. A stub
that always says "no" is the honest answer while there is nowhere to record a flag:
no GST registration *can* be flagged today, so "not flagged" is true rather than
merely convenient.

It is deliberately **not** a null object that the guard treats as "no information".
``NoBranchFlags`` in ``handover_conditions.py`` plays that part. This one is a real
reader whose dataset happens to be empty, which is why it may be injected in
production once 2.9 does so.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class BranchFlagService:
    """Satisfies Developer 2's ``BranchFlagReader`` Protocol.

    Holds the caller's session so task 3.14 can start reading from it without the
    constructor changing, and so a consumer wires it the same way before and after.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def is_flagged(
        self, gst_registration_id: uuid.UUID
    ) -> tuple[bool, str | None]:
        """Whether this registration is flagged, and which state it is in.

        Returns ``(False, None)`` for every registration until task 3.14. The state
        name is part of the answer because the guard's message names it — "the
        invoicing branch Maharashtra is flagged" — and only this lane knows how to
        derive a state from a GSTIN.
        """
        return (False, None)


__all__ = ["BranchFlagService"]
