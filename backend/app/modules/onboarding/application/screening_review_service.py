"""E9 persistence service for screening review state and bank findings.

**The checklist is a log, not a set of toggles.** ``screening_review_item`` has
no unique constraint on ``(customer_id, item_key)`` and rejects ``UPDATE`` and
``DELETE`` at the database (onboarding_0011_review_log). Recording a decision
appends a row; the current state of an item is its most recent row. That keeps
"this item was FAILED by X on Tuesday, then PASSED by Y on Thursday" — which is
what an auditor asks for, and what overwriting in place destroyed.

The read path compensates so nothing above this service notices:
``list_review_items`` returns exactly one row per ``item_key``, the latest, and
``upsert_review_item`` returns the row it just wrote. ``list_item_history``
returns the whole log for one item (Dev4B 4B-1).

Every decision is also written to the company's shared history log under the
``screening`` dimension, in the same transaction (decision **D9**, lead, 28 Sep 2026).
The checklist table stays the item's own full history.

Screening is not qualification and not a gauge (architecture §5.5).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.company_input_lock import share_lock_companies
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.screening_review import (
    SCREENING_STATUSES,
    BankActivityFinding,
    ScreeningReviewItem,
)
from app.modules.onboarding.exceptions import ExporterProfileNotFoundError
from app.shared.exceptions import ValidationError


@dataclass(frozen=True)
class ScreeningCatalogueItem:
    """One checklist item as the workspace renders it."""

    key: str
    label: str
    section: str


#: **The one screening catalogue** — the eight checklist items, in display order,
#: with the label and section the workspace shows. Served to the frontend in the
#: list response (4b-task.md §5.5, Dev4B 4B-1), so `VerificationSection.tsx` needs
#: no copy of its own; everything else in the backend derives from this tuple.
#:
#: Checked here rather than in the router because the router takes `item_key` as a
#: bare path string: anything that is not one of these was a typo, and before this
#: check a typo persisted happily, rendered nowhere, and never counted toward the
#: "X/8 reviewed" progress the reviewer is working against.
#:
#: Adding a ninth item is one entry here.
SCREENING_CATALOGUE_ITEMS: tuple[ScreeningCatalogueItem, ...] = (
    ScreeningCatalogueItem(
        "website-reviewed",
        "Has the website been reviewed?",
        "Company checks",
    ),
    ScreeningCatalogueItem(
        "address-physical",
        "Is the registered address a physical business address?",
        "Company checks",
    ),
    ScreeningCatalogueItem(
        "business-consistency",
        "Does the declared business activity make sense for the exporter?",
        "Company checks",
    ),
    ScreeningCatalogueItem(
        "payment-purpose",
        "Does expected payment and trading activity fit the business?",
        "Volume and activity",
    ),
    ScreeningCatalogueItem(
        "bank-statements-reviewed",
        "Have bank statements / bank-linked activity been reviewed?",
        "EDD",
    ),
    ScreeningCatalogueItem(
        "suspicious-bank-indicators",
        "Were suspicious bank activity indicators investigated?",
        "EDD",
    ),
    ScreeningCatalogueItem(
        "exception-approval",
        "If an exception exists, has it been formally approved?",
        "Exception",
    ),
    ScreeningCatalogueItem(
        "exception-evidence",
        "Has supporting evidence for the exception been attached?",
        "Exception",
    ),
)

#: The catalogue's keys in display order — what the compliance-inputs contract
#: serves (4b-task.md §6.1). Derived, so there is still one backend copy.
SCREENING_CATALOGUE: tuple[str, ...] = tuple(item.key for item in SCREENING_CATALOGUE_ITEMS)
VALID_ITEM_KEYS: frozenset[str] = frozenset(SCREENING_CATALOGUE)

#: The shared-history dimension screening decisions are recorded under (D9). Needs
#: its row in `docs/contracts/history-row.md` §2 — Developer 1's contract.
HISTORY_DIMENSION = "screening"


def _check_item_key(item_key: str) -> None:
    if item_key not in VALID_ITEM_KEYS:
        raise ValidationError(
            f"Unknown screening-review item_key {item_key!r}. "
            f"Expected one of: {', '.join(SCREENING_CATALOGUE)}."
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
        returned here — that is `list_item_history`.

        Raises `ExporterProfileNotFoundError` (404) for an unknown company.
        """
        await self._require_company(customer_id)
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
        self,
        customer_id: uuid.UUID,
        item_key: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ScreeningReviewItem], int]:
        """Every decision ever recorded for one checklist item, newest first — one
        page of it, with the total behind the page.

        The append-only table *is* the full history the architecture asks for
        (4b-task.md §5.6); nothing is copied anywhere. Same order as the latest-row
        rule (`created_at DESC, id DESC`), so the first row of the first page is
        always the item's current state.

        Raises `ValidationError` (422) for an unknown `item_key` and
        `ExporterProfileNotFoundError` (404) for an unknown company.
        """
        _check_item_key(item_key)
        await self._require_company(customer_id)
        where = (
            ScreeningReviewItem.customer_id == customer_id,
            ScreeningReviewItem.item_key == item_key,
        )
        total = await self._db.scalar(
            select(func.count()).select_from(ScreeningReviewItem).where(*where)
        )
        result = await self._db.execute(
            select(ScreeningReviewItem)
            .where(*where)
            .order_by(
                ScreeningReviewItem.created_at.desc(),
                ScreeningReviewItem.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)

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

        Raises `ValidationError` (422) for an `item_key` outside the catalogue or a
        `status` outside `SCREENING_STATUSES` (the database refuses one too:
        `ck_screening_review_item_status`), and `ExporterProfileNotFoundError`
        (404) for an unknown company — not a foreign-key error.

        Takes `FOR SHARE` on the company row before the insert (4b-task.md §6.2
        invariant 6), so a decision cannot land in the middle of Developer 4A's
        background-check decision, which holds that row `FOR UPDATE`.

        Also writes one `screening` row to the company's shared history log, in
        the same transaction (**D9**): `from_value` the item's previous status (or
        `None` for its first decision), `to_value` the new one, `reason` the
        comment, and the item key and row id in `details`.
        """
        _check_item_key(item_key)
        if status not in SCREENING_STATUSES:
            raise ValidationError(
                f"Unknown screening-review status {status!r}. "
                f"Expected one of: {', '.join(SCREENING_STATUSES)}."
            )

        locked = await share_lock_companies(self._db, [customer_id])
        if customer_id not in locked:
            raise ExporterProfileNotFoundError(customer_id)
        previous_status = await self._db.scalar(
            select(ScreeningReviewItem.status)
            .where(
                ScreeningReviewItem.customer_id == customer_id,
                ScreeningReviewItem.item_key == item_key,
            )
            .order_by(ScreeningReviewItem.created_at.desc(), ScreeningReviewItem.id.desc())
            .limit(1)
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
        await self._db.flush()
        await HistoryService(self._db).record(
            customer_id,
            dimension=HISTORY_DIMENSION,
            to_value=status,
            from_value=previous_status,
            actor_id=actor_id,
            source="screening_review_service.upsert_review_item",
            reason=comment,
            details={"item_key": item_key, "screening_review_item_id": str(item.id)},
        )
        await self._db.commit()
        await self._db.refresh(item)
        return item

    async def list_bank_findings(self, customer_id: uuid.UUID) -> list[BankActivityFinding]:
        """Stored findings, newest first. Nothing writes this table today: no
        bank-monitoring provider feed is connected, and none is faked (§5.9)."""
        result = await self._db.execute(
            select(BankActivityFinding)
            .where(BankActivityFinding.customer_id == customer_id)
            .order_by(BankActivityFinding.detected_at.desc())
        )
        return list(result.scalars().all())

    async def _require_company(self, customer_id: uuid.UUID) -> None:
        exists = await self._db.scalar(
            select(ExporterProfile.customer_id).where(ExporterProfile.customer_id == customer_id)
        )
        if exists is None:
            raise ExporterProfileNotFoundError(customer_id)


__all__ = [
    "HISTORY_DIMENSION",
    "SCREENING_CATALOGUE",
    "SCREENING_CATALOGUE_ITEMS",
    "ScreeningCatalogueItem",
    "ScreeningReviewService",
    "VALID_ITEM_KEYS",
]
