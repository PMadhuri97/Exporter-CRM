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

Developer 1 (compliance engine) since 1 October 2026:

* **Seven items, not eight** (plan P2-4a, decision K). ``website-reviewed`` left the
  catalogue with the website field (R11). Its stored rows stay exactly as they were,
  and every decision that pinned one keeps it; the key is *retired*: readable in an
  item's history and in a decision's evidence, refused on a new write (422).
* **Evidence on an answer** (plan P2-1b, IQ-14: optional). An answer may carry
  ``{type, ref}`` references, checked by the same rule as a verification result's
  (``evidence_documents.check_evidence_documents``): the company's own ``AVAILABLE``
  documents, or http(s) links.
* **Cycles** (plan P2-3a/b). Every answer is stamped with the company's current check
  cycle; "the current state of an item" is its latest row **in that cycle**. A new
  cycle therefore starts with every item unanswered (IQ-3), and an earlier cycle's
  answers stay readable by naming the cycle.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.company_input_lock import share_lock_companies
from app.modules.onboarding.application.evidence_documents import check_evidence_documents
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.entities.check_cycle import CheckCycle
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.screening_review import (
    SCREENING_STATUSES,
    BankActivityFinding,
    ScreeningReviewItem,
)
from app.modules.onboarding.domain.verification_evidence import VerificationEvidence
from app.modules.onboarding.exceptions import (
    CheckCycleNotFoundError,
    ExporterProfileNotFoundError,
)
from app.modules.onboarding.infrastructure.repositories.check_cycle_repository import (
    CheckCycleRepository,
    in_cycle,
)
from app.shared import clock
from app.shared.exceptions import ValidationError


@dataclass(frozen=True)
class ScreeningCatalogueItem:
    """One checklist item as the workspace renders it."""

    key: str
    label: str
    section: str


#: **The one screening catalogue** — the seven checklist items, in display order,
#: with the label and section the workspace shows. Served to the frontend in the
#: list response (4b-task.md §5.5, Dev4B 4B-1), so `VerificationSection.tsx` needs
#: no copy of its own; everything else in the backend derives from this tuple.
#:
#: Checked here rather than in the router because the router takes `item_key` as a
#: bare path string: anything that is not one of these was a typo, and before this
#: check a typo persisted happily, rendered nowhere, and never counted toward the
#: "X/8 reviewed" progress the reviewer is working against.
#:
#: Adding an item is one entry here; retiring one moves it to
#: `RETIRED_SCREENING_ITEMS` (plan P2-4a) so its stored rows keep a label.
SCREENING_CATALOGUE_ITEMS: tuple[ScreeningCatalogueItem, ...] = (
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

#: Items that were once in the catalogue (plan P2-4a, decision K). Their stored rows
#: are kept and a decision that pinned one still resolves it, so they keep a label;
#: a new answer to one is refused.
RETIRED_SCREENING_ITEMS: tuple[ScreeningCatalogueItem, ...] = (
    # Retired 1 October 2026 with the website field (R11); part of `CLEAR_RULES_V1`.
    ScreeningCatalogueItem(
        "website-reviewed",
        "Has the website been reviewed?",
        "Company checks",
    ),
)

#: The catalogue's keys in display order — what the compliance-inputs contract
#: serves (4b-task.md §6.1). Derived, so there is still one backend copy.
SCREENING_CATALOGUE: tuple[str, ...] = tuple(item.key for item in SCREENING_CATALOGUE_ITEMS)
#: The keys a new answer may be recorded under.
VALID_ITEM_KEYS: frozenset[str] = frozenset(SCREENING_CATALOGUE)
RETIRED_ITEM_KEYS: frozenset[str] = frozenset(item.key for item in RETIRED_SCREENING_ITEMS)
#: Every key a stored row may carry and a reader may ask about, with its label.
ITEM_LABELS: dict[str, str] = {
    item.key: item.label for item in (*SCREENING_CATALOGUE_ITEMS, *RETIRED_SCREENING_ITEMS)
}

#: The shared-history dimension screening decisions are recorded under (D9). Needs
#: its row in `docs/contracts/history-row.md` §2 — Developer 1's contract.
HISTORY_DIMENSION = "screening"


def _check_item_key(item_key: str, *, for_write: bool) -> None:
    if for_write and item_key in RETIRED_ITEM_KEYS:
        raise ValidationError(
            f"Screening-review item {item_key!r} has been retired from the checklist; "
            "its earlier answers are kept, but no new one can be recorded."
        )
    if item_key not in VALID_ITEM_KEYS and item_key not in RETIRED_ITEM_KEYS:
        raise ValidationError(
            f"Unknown screening-review item_key {item_key!r}. "
            f"Expected one of: {', '.join(SCREENING_CATALOGUE)}."
        )


@dataclass(frozen=True)
class ScreeningCycleScope:
    """Which cycle a checklist read is about, and where that sits among the company's.

    ``selected`` is ``None`` only for a company with no cycle row yet — its implicit
    cycle 1, which is also its current one.
    """

    selected: CheckCycle | None
    current: CheckCycle | None
    initial: CheckCycle | None

    @property
    def is_current(self) -> bool:
        return self.selected is None or (
            self.current is not None and self.selected.id == self.current.id
        )


class ScreeningReviewService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._cycles = CheckCycleRepository(db)

    async def cycle_scope(
        self, customer_id: uuid.UUID, cycle_id: uuid.UUID | None = None
    ) -> ScreeningCycleScope:
        """The cycle a read is about: ``cycle_id`` if given, else the current one.

        Raises `ExporterProfileNotFoundError` (404) for an unknown company and
        `CheckCycleNotFoundError` (404) for a cycle that is not this company's.
        """
        await self._require_company(customer_id)
        cycles = await self._cycles.list_for_company(customer_id)
        current = cycles[-1] if cycles else None
        initial = cycles[0] if cycles else None
        if cycle_id is None:
            return ScreeningCycleScope(selected=current, current=current, initial=initial)
        selected = next((cycle for cycle in cycles if cycle.id == cycle_id), None)
        if selected is None:
            raise CheckCycleNotFoundError(customer_id, cycle_id)
        return ScreeningCycleScope(selected=selected, current=current, initial=initial)

    async def list_review_items(
        self, customer_id: uuid.UUID, *, scope: ScreeningCycleScope | None = None
    ) -> list[ScreeningReviewItem]:
        """The state of each checklist item in one cycle — one row per `item_key`.

        The cycle is ``scope.selected`` (default: the company's current cycle), with the
        legacy rule that a row with no cycle belongs to cycle 1. Only catalogue keys are
        listed: a retired item's rows stay stored and readable through its history, but
        they are not part of the checklist any more (plan P2-4a).

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
        scope = scope or await self.cycle_scope(customer_id)
        result = await self._db.execute(
            select(ScreeningReviewItem)
            .where(
                ScreeningReviewItem.customer_id == customer_id,
                ScreeningReviewItem.item_key.in_(SCREENING_CATALOGUE),
                in_cycle(ScreeningReviewItem.cycle_id, scope.selected),
            )
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
        page of it, with the total behind the page. Every cycle's, each row naming its
        own; a retired item's history stays readable.

        The append-only table *is* the full history the architecture asks for
        (4b-task.md §5.6); nothing is copied anywhere. Same order as the latest-row
        rule (`created_at DESC, id DESC`), so the first row of the first page is
        always the item's most recent answer.

        Raises `ValidationError` (422) for an unknown `item_key` and
        `ExporterProfileNotFoundError` (404) for an unknown company.
        """
        _check_item_key(item_key, for_write=False)
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
        evidence: VerificationEvidence | None = None,
    ) -> ScreeningReviewItem:
        """Record one checklist decision and return it.

        Named `upsert_` for its callers' sake — the router's `PUT` semantics are
        unchanged and so is the returned shape. What it does underneath is an
        insert, every time: the previous decision for this item stays exactly as
        it was written.

        Raises `ValidationError` (422) for an `item_key` outside the catalogue (or a
        retired one), a `status` outside `SCREENING_STATUSES` (the database refuses one
        too: `ck_screening_review_item_status`) or evidence the document rule refuses,
        and `ExporterProfileNotFoundError` (404) for an unknown company — not a
        foreign-key error.

        Takes `FOR SHARE` on the company row before the insert (4b-task.md §6.2
        invariant 6), so a decision cannot land in the middle of a background-check
        decision or the start of a new cycle, which hold that row `FOR UPDATE`. Under
        that lock the answer is stamped with the company's current cycle (created as
        cycle 1 if the company has none yet).

        Also writes one `screening` row to the company's shared history log, in
        the same transaction (**D9**): `from_value` the item's previous status in this
        cycle (or `None` for its first answer in it), `to_value` the new one, `reason`
        the comment, and the item key, row id and cycle in `details`.
        """
        _check_item_key(item_key, for_write=True)
        if status not in SCREENING_STATUSES:
            raise ValidationError(
                f"Unknown screening-review status {status!r}. "
                f"Expected one of: {', '.join(SCREENING_STATUSES)}."
            )

        locked = await share_lock_companies(self._db, [customer_id])
        if customer_id not in locked:
            raise ExporterProfileNotFoundError(customer_id)
        await check_evidence_documents(
            self._db, evidence, company_id=customer_id, subject_label="company"
        )
        now = clock.now()
        cycle = await self._cycles.current_or_initial(
            customer_id,
            actor_id=actor_id,
            source_ref="screening_review_service.upsert_review_item",
            at=now,
        )
        previous_status = await self._db.scalar(
            select(ScreeningReviewItem.status)
            .where(
                ScreeningReviewItem.customer_id == customer_id,
                ScreeningReviewItem.item_key == item_key,
                in_cycle(ScreeningReviewItem.cycle_id, cycle),
            )
            .order_by(ScreeningReviewItem.created_at.desc(), ScreeningReviewItem.id.desc())
            .limit(1)
        )
        refs = [ref.as_json() for ref in evidence.refs] if evidence is not None else []
        item = ScreeningReviewItem(
            customer_id=customer_id,
            item_key=item_key,
            status=status,
            comment=comment,
            reviewed_by=actor_id,
            reviewed_at=now,
            evidence_refs=refs,
            cycle_id=cycle.id,
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
            details={
                "item_key": item_key,
                "screening_review_item_id": str(item.id),
                "cycle_id": str(cycle.id),
                "evidence_count": len(refs),
            },
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
    "ITEM_LABELS",
    "RETIRED_ITEM_KEYS",
    "RETIRED_SCREENING_ITEMS",
    "SCREENING_CATALOGUE",
    "SCREENING_CATALOGUE_ITEMS",
    "ScreeningCatalogueItem",
    "ScreeningCycleScope",
    "ScreeningReviewService",
    "VALID_ITEM_KEYS",
]
