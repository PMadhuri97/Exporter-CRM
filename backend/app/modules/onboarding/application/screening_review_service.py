"""E9 persistence service for screening review state and bank findings.

**The checklist is a log, not a set of toggles.** ``screening_review_item`` has
no unique constraint on ``(customer_id, item_key)`` and rejects ``UPDATE`` and
``DELETE`` at the database (onboarding_0011_review_log). Recording a decision
appends a row; the current state of an item is its most recent row. That keeps
"this item was FAILED by X on Tuesday, then PASSED by Y on Thursday" — which is
what an auditor asks for, and what overwriting in place destroyed.

The read path compensates so nothing above this service notices:
``list_review_items`` returns exactly one row per ``item_key``, the latest, and
``upsert_review_item`` returns the row it just wrote. ``GET /screening-review``
and its response schema are unchanged.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.screening_review import (
    BankActivityFinding,
    ScreeningReviewItem,
)
from app.shared.exceptions import ValidationError

#: The eight checklist items the compliance workspace actually renders, in the
#: order `VerificationSection.tsx` declares them.
#:
#: This is the authoritative list, and it is checked here rather than in the
#: router because the router takes `item_key` as a bare path string: anything
#: that is not one of these was a typo, and before this check a typo persisted
#: happily, rendered nowhere, and never counted toward the "X/8 reviewed"
#: progress the reviewer is working against. The write looked like it worked.
#:
#: Adding a ninth item means adding it here *and* to `CHECKLIST_ITEMS` in
#: `frontend/src/modules/onboarding/components/VerificationSection.tsx`. The two
#: lists are the same list; keeping them in step is the price of validating at
#: all, and is cheaper than the silent no-op it replaces.
VALID_ITEM_KEYS: frozenset[str] = frozenset(
    {
        "website-reviewed",
        "address-physical",
        "business-consistency",
        "payment-purpose",
        "bank-statements-reviewed",
        "suspicious-bank-indicators",
        "exception-approval",
        "exception-evidence",
    }
)


class ScreeningReviewService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_review_items(self, customer_id: uuid.UUID) -> list[ScreeningReviewItem]:
        """The current state of each checklist item — one row per `item_key`.

        `DISTINCT ON (item_key)` with a matching `ORDER BY` takes the first row
        of each `item_key` group, and `created_at DESC` makes that the newest.
        `created_at` defaults to `now()` — transaction start time — so two
        decisions written in one transaction would share a timestamp. The `id`
        tie-break only makes that case deterministic, not chronological: `id`
        is a random `uuid4`. It does not arise today, because
        `upsert_review_item` commits each decision in its own transaction; a
        future caller that writes several decisions in one transaction must
        not rely on this order to pick the "latest" of them.

        `ix_screening_review_customer_item_recent` is built in this exact shape,
        so the sort is satisfied by the index rather than performed.

        Superseded decisions are still in the table and are deliberately not
        returned here. This method answers "what is the state of the checklist",
        which is what the response contract promises; the history is a separate
        question that nothing asks yet.
        """
        result = await self._db.execute(
            select(ScreeningReviewItem)
            .where(ScreeningReviewItem.customer_id == customer_id)
            .distinct(ScreeningReviewItem.item_key)
            .order_by(
                ScreeningReviewItem.item_key.asc(),
                ScreeningReviewItem.created_at.desc(),
                ScreeningReviewItem.id.desc(),
            )
        )
        return list(result.scalars().all())

    async def list_item_history(
        self, customer_id: uuid.UUID, item_key: str
    ) -> list[ScreeningReviewItem]:
        """Every decision ever recorded for one checklist item, newest first.

        Nothing in the API calls this yet — the route that would expose it is
        another developer's to write. It exists because the whole point of
        making the table append-only is that the history is reachable, and a
        history no code can read is a history nobody will trust is there.
        """
        result = await self._db.execute(
            select(ScreeningReviewItem)
            .where(
                ScreeningReviewItem.customer_id == customer_id,
                ScreeningReviewItem.item_key == item_key,
            )
            .order_by(
                ScreeningReviewItem.created_at.desc(),
                ScreeningReviewItem.id.desc(),
            )
        )
        return list(result.scalars().all())

    async def upsert_review_item(
        self,
        customer_id: uuid.UUID,
        *,
        item_key: str,
        status: str,
        comment: str | None,
        actor_id: str,
    ) -> ScreeningReviewItem:
        """Record one checklist decision and return it.

        Named `upsert_` for its callers' sake — the router's `PUT` semantics are
        unchanged and so is the returned shape. What it does underneath is an
        insert, every time: the previous decision for this item stays exactly as
        it was written.

        Raises `ValidationError` (422) for an `item_key` outside
        `VALID_ITEM_KEYS`.
        """
        if item_key not in VALID_ITEM_KEYS:
            raise ValidationError(
                f"Unknown screening-review item_key {item_key!r}. "
                f"Expected one of: {', '.join(sorted(VALID_ITEM_KEYS))}."
            )

        item = ScreeningReviewItem(
            customer_id=customer_id,
            item_key=item_key,
            status=status,
            comment=comment,
            reviewed_by=actor_id,
            reviewed_at=datetime.now(UTC),
        )
        self._db.add(item)
        await self._db.commit()
        await self._db.refresh(item)
        return item

    async def list_bank_findings(self, customer_id: uuid.UUID) -> list[BankActivityFinding]:
        result = await self._db.execute(
            select(BankActivityFinding)
            .where(BankActivityFinding.customer_id == customer_id)
            .order_by(BankActivityFinding.detected_at.desc())
        )
        return list(result.scalars().all())


__all__ = ["ScreeningReviewService", "VALID_ITEM_KEYS"]
