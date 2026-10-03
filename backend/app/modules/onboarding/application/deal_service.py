"""Deals and their buyers — **owner: Developer 3B** (L3-05, L3-06).

Contract: ``docs/contracts/deal-and-buyer.md``. Architecture §3.3, §3.5, §3.8.

**One transaction per operation.** Every write locks the deal row (or reads the
company for a create), validates, assigns, writes the history row through
Developer 1's shared ``HistoryService`` — which flushes and never commits — and
commits once at the end. Architecture §3.8: the current value and the record of
how it got there commit together or not at all. Every rule is checked *before*
anything is assigned, so a refused move leaves nothing behind.

**Seam S1 lives in ``open_deal``.** Opening a deal sets the company's conversation
to ``READY_NOW`` (architecture §3.3) by calling Developer 3A's
``ConversationService.mark_ready_now_for_opened_deal`` in this same session and
transaction. This service never assigns ``exporter_profile.conversation`` and
never imports 3A's enum to compare against it (``company-record.md`` §2.4). Because
S1 checks no journey, ``open_deal`` does: only a ``PROSPECT`` or ``CUSTOMER`` may
have a deal (``_OPENABLE_JOURNEYS``), so a lead is never given a conversation value.

**What it does not decide.** Which roles may open a deal or move a stage is the
route's, via ``require_role`` in ``deal_router.py``, matching the §3.7 matrix. This
service holds the *rules* — which moves exist, which need a reason, which need a
buyer — and ``allowed_stage_moves`` is those rules as data, so the screen asks the
server instead of keeping a copy (§7.5). That split is
``ConversationService.allowed_moves``' and is deliberately the same shape.

**The handover guard is real on both halves.**
``GATHERING_PAPERWORK → HANDED_OVER`` needs the company to be a ``CUSTOMER`` with a
``CLEAR`` background check (assumption A5). Developer 4A's migration 0015 has landed,
so ``read_background_check`` calls their published helper (``background-check.md``
§10) and returns a real value: a company that has never been checked reads
``NOT_STARTED``, and "not ``CLEAR``" is never treated as "clear". Nothing here
creates or writes that column (``company-record.md`` §2.4).

The guard **share-locks the company row** while a handover is in progress (decision
D10, settled 28 September 2026), so a concurrent flag cannot land between the guard
and the commit. The read that renders a deal takes no lock — see
``_handover_blocked_reason``.

A company reaches ``CUSTOMER`` through Developer 2's promotion (L2-11): the move that
makes it both a ``PROSPECT`` and ``CLEAR`` promotes it in the same transaction
(``ExporterProfileService.promote_to_customer_if_ready``). ``read_background_check``
stays a separate one-line function so the handover tests can isolate the code after
the guard; the whole path, unsubstituted, is ``test_crm_end_to_end.py``.

**The guard's rules now live in ``domain/handover_conditions.py``** (allocation F2):
an ordered list of condition functions over providers injected into this service.
A5's two conditions are the first two and decide today; four more — required
documents, the seller's and the buyer's compliance, the invoicing branch — are in
the list with their null provider injected, so they report nothing until the lane
that owns each provider ships it. This service keeps the part only a service can
do: read the company row once, under the right lock, and hand every condition the
same snapshot of it.

Everything downstream of the guard is real and tested: the **persisted** handover
snapshot (``deal.handover_snapshot``, plan P2-7, written in the same ``UPDATE`` as
the stage move so it lands before the terminal trigger freezes it), the history
row, and the best-effort ``deal.handed_over`` announcement, in that order
(architecture §3.6 — the record is the source of truth, the announcement is an
announcement).
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.background_check_reader import current_background_check
from app.modules.onboarding.application.compliance_facts import ComplianceFactsService
from app.modules.onboarding.application.conversation_service import ConversationService
from app.modules.onboarding.application.deal_required_documents_service import (
    DealRequiredDocumentsPolicy,
)
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.deal_views import (
    BuyerCompanyView,
    DealBuyerView,
    DealListItemView,
    DealStageMove,
    DealView,
)
from app.modules.onboarding.domain.entities.deal import Deal
from app.modules.onboarding.domain.entities.deal_buyer import DealBuyer
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.handover_conditions import (
    HANDOVER_JOURNEY,
    HandoverProviders,
    HandoverSubject,
    blocked_reason,
    state_name,
)
from app.modules.onboarding.events.publisher import OnboardingEventPublisher
from app.modules.onboarding.exceptions import (
    DealBuyerCompanyAlreadySetError,
    DealBuyerIsTheSellerError,
    DealBuyerRequiredError,
    DealCompanyNotFoundError,
    DealCompanyNotReadyError,
    DealHandoverBlockedError,
    DealNotFoundError,
    DealTerminalError,
    DealTransitionNotAllowedError,
    DealWithdrawalReasonRequiredError,
)
from app.modules.onboarding.infrastructure.repositories.crm_document_repository import (
    CrmDocumentRepository,
)
from app.modules.onboarding.infrastructure.repositories.deal_buyer_repository import (
    DealBuyerRepository,
)
from app.modules.onboarding.infrastructure.repositories.deal_repository import DealRepository
from app.shared import clock
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)

#: The move table, deal contract §1.1. A stage is a claim about what has happened,
#: not a judgement, so this is a fixed graph rather than "any value may follow any
#: other" — the deliberate difference from the conversation gauge.
PERMITTED_STAGE_MOVES: dict[DealStage, tuple[DealStage, ...]] = {
    DealStage.OPEN: (DealStage.GATHERING_PAPERWORK, DealStage.WITHDRAWN),
    DealStage.GATHERING_PAPERWORK: (DealStage.HANDED_OVER, DealStage.WITHDRAWN),
    DealStage.HANDED_OVER: (),
    DealStage.WITHDRAWN: (),
}

#: Assumption A7.
_NEEDS_REASON = frozenset({DealStage.WITHDRAWN})
#: A handover payload carries the buyer (architecture §3.6).
_NEEDS_BUYER = frozenset({DealStage.HANDED_OVER})

#: Architecture §3.3: the journey value a company must have reached before a deal
#: may be handed over (assumption A5's first half). It now lives with the condition
#: that reads it (``handover_conditions.HANDOVER_JOURNEY``) and is re-exported here
#: under its old name, because that is the name the rest of this module and its
#: tests call it by. Compared by *name* rather than by importing Developer 3's enum
#: member, so neither file takes a dependency on the shape of their enum.
_HANDOVER_JOURNEY = HANDOVER_JOURNEY

#: The journey values a company must hold before a deal may be opened on it. A deal
#: follows a sales conversation, which applies from ``PROSPECT`` onward (assumption
#: A4), and opening one sets the conversation to ``READY_NOW`` (seam S1) — so a
#: ``LEAD`` is refused before any row is written (``deal-and-buyer.md`` §2). Compared
#: by name, like ``_HANDOVER_JOURNEY``.
_OPENABLE_JOURNEYS = frozenset({"PROSPECT", "CUSTOMER"})


def read_background_check(company: ExporterProfile) -> str | None:
    """The company's background check, as a plain string.

    **This now calls Developer 4A's published read helper** (L4-01,
    ``background-check.md`` §10). It was a stand-in until migration 0015 landed; the
    body is a call to the helper and the name and signature are unchanged, which is
    exactly what the stand-in's docstring promised would happen.

    It stays a separate one-line function rather than being inlined at the call site,
    because that is what makes the seam visible: everything downstream of the guard
    reads the gauge through this one place, and Dev4A owns only this body
    (``background-check.md`` §10).

    The return type keeps ``| None`` for the callers that still handle it, but the
    column is ``NOT NULL DEFAULT 'NOT_STARTED'``, so in practice a value always comes
    back. A company that has never been checked reads ``NOT_STARTED`` — a fact, not an
    absence — and "not ``CLEAR``" is still never treated as "clear".
    """
    return current_background_check(company)


#: Marks a snapshot taken inside the handover's own transaction, as against one
#: reconstructed afterwards by migration 0029
#: (``"backfilled_from_deal_buyer"``). A reader can always tell the two apart.
SNAPSHOT_TAKEN_AT_HANDOVER = "taken_at_handover"


@dataclass(frozen=True)
class _Handover:
    """What one handover rests on, captured inside the transaction that made it.

    Frozen, and built once: the whole point is that this cannot change between the
    commit and the announcement, nor afterwards.

    Since P2-7 it is also **persisted**, as ``deal.handover_snapshot``: the
    announcement is best effort and the history row carries only the document ids,
    so neither was a record of the buyer the lending team was given. A company's
    details change after a handover; this does not (set-once, by
    ``trg_deal_terminal_freeze``).
    """

    buyer: dict
    document_ids: list[str]
    buyer_company_id: uuid.UUID | None
    at: datetime

    def as_snapshot(self) -> dict:
        """The JSONB value stored on the deal. The same keys migration 0029's
        backfill writes, so one reader handles both."""
        return {
            "buyer": self.buyer or None,
            "buyer_company_id": (
                str(self.buyer_company_id) if self.buyer_company_id is not None else None
            ),
            "document_ids": list(self.document_ids),
            "snapshot_source": SNAPSHOT_TAKEN_AT_HANDOVER,
            "snapshot_at": self.at.isoformat(),
        }


class DealService:
    """Open deals, move their stages, record their buyers, and hand them over."""

    def __init__(self, db: AsyncSession, *, providers: HandoverProviders | None = None) -> None:
        self._db = db
        self._deals = DealRepository(db)
        self._buyers = DealBuyerRepository(db)
        self._history = HistoryService(db)
        self._conversation = ConversationService(db)
        # Best effort by construction: `deal_handed_over` logs and swallows its
        # own failures, so a dead bus never undoes a committed handover.
        self._events = OnboardingEventPublisher()
        # The handover guard's providers (`domain/handover_conditions.py`).
        #
        # Five of the six conditions are live: assumption A5's two, the required
        # documents (P2-5b), and — since P4-7 — the seller's and the buyer's
        # compliance, through Developer 1's published reader. Only the invoicing
        # branch is still inert, waiting on Developer 3's real `BranchFlagReader`
        # (task 2.9 swaps `NoBranchFlags` for it and changes no condition's code).
        #
        # `ComplianceFactsService` reads in this same session and never writes, so the
        # facts a condition sees are the ones this transaction's locks cover.
        #
        # A caller may pass `providers` to substitute any of them; the handover tests
        # drive conditions from `StaticComplianceFactsReader`.
        self._providers = (
            providers
            if providers is not None
            else HandoverProviders(
                compliance=ComplianceFactsService(db),
                required_documents=DealRequiredDocumentsPolicy(db),
            )
        )

    # ── Read ─────────────────────────────────────────────────────────────────

    async def get_deal(self, deal_id: uuid.UUID) -> DealView:
        deal = await self._require_deal(deal_id)
        return await self._to_view(deal)

    async def can_open_deal(self, company_id: uuid.UUID) -> bool:
        """Whether ``open_deal`` would accept this company now — the rule as data, so
        the screen offers "Open a deal" only where the server would allow it
        (§7.5). The caller's role is the route's to add."""
        return await self._company_journey(company_id) in _OPENABLE_JOURNEYS

    async def list_for_company(
        self,
        company_id: uuid.UUID,
        *,
        stages: tuple[DealStage, ...] | None = None,
        as_buyer: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[DealListItemView], int]:
        """One company's deals — the ones it sells on, or with ``as_buyer`` the ones
        it buys on (task 2.7).

        On the buyer side, ``buyer_name`` is **the seller's** name rather than the
        buyer's: on a list of "deals where this company is the buyer", repeating the
        company whose page you are on in every row says nothing, and the other party
        is the only thing that distinguishes the rows. The field keeps its name
        because it is the same column of the same table — "the other party on this
        deal" — and renaming it would be a contract change for every caller.
        """
        deals, total = await self._deals.list_for_company(
            company_id, stages=stages, as_buyer=as_buyer, limit=limit, offset=offset
        )
        sellers: dict[uuid.UUID, str | None] = {}
        if as_buyer and deals:
            rows = await self._db.execute(
                select(ExporterProfile.customer_id, ExporterProfile.name).where(
                    ExporterProfile.customer_id.in_({deal.company_id for deal in deals})
                )
            )
            sellers = {row.customer_id: row.name for row in rows}
        return [
            DealListItemView(
                id=deal.id,
                company_id=deal.company_id,
                reference=deal.reference,
                stage=deal.stage,
                buyer_name=(
                    sellers.get(deal.company_id)
                    if as_buyer
                    else (deal.buyer.name if deal.buyer is not None else None)
                ),
                created_at=deal.created_at,
                updated_at=deal.updated_at,
            )
            for deal in deals
        ], total

    @staticmethod
    def allowed_stage_moves(current: DealStage) -> list[DealStageMove]:
        """Every move the rules allow from ``current``, with what each needs.

        A ``staticmethod`` because it is the rule table and touches no session —
        the same shape as ``ConversationService.allowed_moves`` and
        ``ExporterProfileService.allowed_marker_moves``, so a reader comparing the
        three finds one pattern.

        This does **not** take the handover guard into account: whether the guard
        is satisfied needs the company row, so ``_to_view`` filters
        ``HANDED_OVER`` out and explains why. Keeping the pure table pure is what
        lets it be unit-tested without a database.
        """
        return [
            DealStageMove(to=stage, reason_required=stage in _NEEDS_REASON)
            for stage in PERMITTED_STAGE_MOVES[current]
        ]

    # ── Write ────────────────────────────────────────────────────────────────

    async def open_deal(
        self,
        company_id: uuid.UUID,
        *,
        reference: str,
        actor_id: str | None,
    ) -> DealView:
        """Open a deal on a company, and set its conversation to ``READY_NOW``.

        In one transaction: the deal row, its ``deal_initial`` history row, and
        Developer 3A's gauge move (seam S1). If any of the three fails, none of
        them happened — which is why 3A's method flushes without committing.

        The company is read (not locked): nothing here changes it, and 3A's method
        locks the row itself before moving the gauge. Its journey must be
        ``PROSPECT`` or ``CUSTOMER`` — a ``LEAD`` is refused before anything is
        written, because seam S1 would otherwise give a lead a conversation value it
        may not hold (A4). Reading without a lock is enough: the journey only moves
        forward, so a company that passes this check cannot fall back behind it.
        """
        cleaned_reference = (reference or "").strip()
        if not cleaned_reference:
            raise ValidationError("a deal needs a reference")

        journey = await self._company_journey(company_id)
        if journey is None:
            raise DealCompanyNotFoundError(company_id)
        if journey not in _OPENABLE_JOURNEYS:
            raise DealCompanyNotReadyError(company_id, journey)

        deal = Deal(
            company_id=company_id,
            reference=cleaned_reference,
            stage=DealStage.OPEN,
        )
        self._db.add(deal)
        # Flushed so the deal has its id before the history row and 3A's call, both
        # of which carry `deal_id`.
        await self._db.flush()

        await self._history.record(
            company_id,
            dimension="deal",
            to_value=DealStage.OPEN.value,
            actor_id=actor_id,
            source="deal_service.open_deal",
            deal_id=deal.id,
            event_type="deal_initial",
            details={"reference": cleaned_reference},
        )
        # Seam S1 — engagement contract §6. Idempotent, checks no journey stage and
        # no role, and flushes without committing.
        await self._conversation.mark_ready_now_for_opened_deal(
            company_id, deal_id=deal.id, actor_id=actor_id or ""
        )

        await self._db.commit()
        await self._db.refresh(deal)
        logger.info(
            "deal.open.ok",
            company_id=str(company_id),
            deal_id=str(deal.id),
            actor_id=actor_id,
        )
        return await self._to_view(deal)

    async def transition_stage(
        self,
        deal_id: uuid.UUID,
        to_stage: DealStage,
        *,
        reason: str | None = None,
        actor_id: str | None,
    ) -> DealView:
        """Move a deal's stage, and record the move.

        The rules, in the order they are checked — each before anything is
        assigned:

        1. The deal exists (404).
        2. It is not already terminal (409) — a separate answer from "not that
           move", because the deal can never move again.
        3. The move is in the §1.1 table (422).
        4. ``WITHDRAWN`` carries a reason (422).
        5. ``HANDED_OVER`` has a buyer (422) and satisfies the A5 guard (409).

        Step 5's guard reads Developer 4A's ``background_check`` through
        ``read_background_check`` and share-locks the company row while it does (D10),
        so a concurrent reopen or flag waits until this handover commits.
        """
        deal = await self._lock_deal(deal_id)
        from_stage = deal.stage

        if from_stage.is_terminal:
            raise DealTerminalError(deal_id, from_stage.value)
        if to_stage not in PERMITTED_STAGE_MOVES[from_stage]:
            raise DealTransitionNotAllowedError(deal_id, from_stage.value, to_stage.value)

        cleaned_reason = (reason or "").strip() or None
        if to_stage in _NEEDS_REASON and cleaned_reason is None:
            raise DealWithdrawalReasonRequiredError(deal_id)
        if to_stage not in _NEEDS_REASON and cleaned_reason is not None:
            # Refused rather than dropped: silently discarding it would leave the
            # operator believing a reason was stored, and
            # `ck_deal_withdrawal_reason` refuses the row anyway.
            raise ValidationError(
                f"a reason belongs only to a withdrawal, not to {to_stage.value}"
            )

        if to_stage in _NEEDS_BUYER:
            # The company is the authority once it is set, and a `deal_buyer` row
            # satisfies this until the migration fills it (contract §3.0). Either one
            # is a buyer; neither is not.
            if deal.buyer_company_id is None and deal.buyer is None:
                raise DealBuyerRequiredError(deal_id)
            # `lock=True`: D10. The company row is share-locked for the rest of this
            # transaction, so the check cannot change between this guard and the
            # commit below.
            blocked = await self._handover_blocked_reason(deal, lock=True)
            if blocked is not None:
                raise DealHandoverBlockedError(deal_id, blocked)

        deal.stage = to_stage
        deal.withdrawal_reason = cleaned_reason
        handover: _Handover | None = None
        if to_stage is DealStage.HANDED_OVER:
            # The shared clock here too, so the time the handover is recorded at and
            # the `now` its guard just ran against are the same moment.
            deal.handed_over_at = clock.now()
            # The snapshot is taken **now**, inside the transaction, so it is the
            # list the handover actually rested on: a document uploaded a minute
            # later cannot change what the lending team was given (architecture
            # §3.6). Collected before the commit, announced after it.
            handover = await self._handover_snapshot(deal)
            # Persisted in the same UPDATE as the stage move (P2-7). The order is
            # what makes this legal: `trg_deal_terminal_freeze` fires on the OLD
            # row, whose stage is still `GATHERING_PAPERWORK`, so the column is
            # written before it is frozen — and set-once from then on.
            deal.handover_snapshot = handover.as_snapshot()

        await self._history.record(
            deal.company_id,
            dimension="deal",
            from_value=from_stage.value,
            to_value=to_stage.value,
            actor_id=actor_id,
            source="deal_service.transition_stage",
            reason=cleaned_reason,
            deal_id=deal.id,
            event_type="deal_transition",
            details={"document_ids": handover.document_ids} if handover else None,
        )
        await self._db.commit()
        await self._db.refresh(deal)

        if handover is not None:
            # After the commit, and best effort: the history row is the source of
            # truth and the announcement is an announcement (architecture §3.6).
            # Announcing first would risk telling the lending team about a handover
            # that then failed to commit — and `deal_handed_over` swallows its own
            # failures, so a dead bus cannot undo a committed handover either.
            await self._events.deal_handed_over(
                deal_id=deal.id,
                company_id=deal.company_id,
                buyer=handover.buyer,
                document_ids=handover.document_ids,
                actor_id=actor_id,
            )

        logger.info(
            "deal.transition.ok",
            deal_id=str(deal.id),
            company_id=str(deal.company_id),
            from_stage=from_stage.value,
            to_stage=to_stage.value,
            actor_id=actor_id,
        )
        return await self._to_view(deal)

    async def set_buyer(
        self,
        deal_id: uuid.UUID,
        *,
        name: str,
        country: str,
        registration_number: str | None = None,
        tax_id: str | None = None,
        contact_email: str | None = None,
        contact_phone: str | None = None,
        keep: Collection[str] = (),
        actor_id: str | None,
    ) -> DealView:
        """Record or replace the deal's buyer.

        ``keep`` names optional fields to leave exactly as stored, whatever was
        passed for them. The API uses it for the fields a masked role never sees
        in full (``registration_number``, ``tax_id``, ``contact_email``,
        ``contact_phone``): such a caller leaves them out of its request, and they
        must survive the replace rather than be cleared by it. On a new buyer
        there is nothing stored, so a kept field starts empty.

        One buyer per deal (contract §3), so setting it twice **updates the same
        row** rather than adding a second — which is what
        ``uq_deal_buyer_deal_id`` enforces and what keeps "the buyer" on the
        handover payload unambiguous.

        Writes a ``deal`` history row with ``event_type="deal_buyer_changed"`` and,
        in ``details``, the changed field names (``changed``), the buyer's name
        (``buyer_name``) and whether this recorded the deal's first buyer
        (``created``): a buyer's details are part of a deal's story, and a separate
        ``buyer`` dimension would need a change to ``history-row.md`` §2, which is
        Developer 1's.
        """
        deal = await self._lock_deal(deal_id)
        if deal.stage.is_terminal:
            # A handed-over deal's buyer is what the lending team was given, and a
            # withdrawn deal's is history. Editing either would rewrite a record.
            raise DealTerminalError(deal_id, deal.stage.value)

        cleaned_name = (name or "").strip()
        if not cleaned_name:
            raise ValidationError("a buyer needs a name")
        cleaned_country = (country or "").strip().upper()
        if len(cleaned_country) != 2 or not cleaned_country.isalpha():
            raise ValidationError(
                "a buyer's country must be a two-letter ISO-3166-1 alpha-2 code"
            )

        fields = {
            "name": cleaned_name,
            "country": cleaned_country,
            "registration_number": _clean(registration_number),
            "tax_id": _clean(tax_id),
            "contact_email": _clean(contact_email),
            "contact_phone": _clean(contact_phone),
        }

        unknown = set(keep) - _BUYER_OPTIONAL_FIELDS
        if unknown:
            raise ValueError(f"not an optional buyer field: {sorted(unknown)}")

        buyer = await self._buyers.get_for_deal(deal_id)
        created = buyer is None
        for key in keep:
            fields[key] = getattr(buyer, key) if buyer is not None else None
        if buyer is None:
            buyer = DealBuyer(deal_id=deal_id, **fields)
            self._db.add(buyer)
            changed = sorted(key for key, value in fields.items() if value is not None)
        else:
            changed = sorted(
                key for key, value in fields.items() if getattr(buyer, key) != value
            )
            for key, value in fields.items():
                setattr(buyer, key, value)

        await self._db.flush()
        await self._history.record(
            deal.company_id,
            dimension="deal",
            from_value=deal.stage.value,
            to_value=deal.stage.value,
            actor_id=actor_id,
            source="deal_service.set_buyer",
            deal_id=deal.id,
            event_type="deal_buyer_changed",
            details={"buyer_name": cleaned_name, "changed": changed, "created": created},
        )
        await self._db.commit()
        await self._db.refresh(deal)

        logger.info(
            "deal.buyer.set.ok",
            deal_id=str(deal.id),
            changed=changed,
            actor_id=actor_id,
        )
        return await self._to_view(deal)

    async def set_buyer_company(
        self, deal_id: uuid.UUID, *, buyer_company_id: uuid.UUID, actor_id: str | None
    ) -> DealView:
        """Name the company this deal's buyer **is** (plan P4-4, task 2.4).

        The successor to `set_buyer`, which records a `deal_buyer` row — a set of
        details with no record of its own. A buyer company is a full company record:
        it can be screened, its sanctions and AML live on its own timeline, and the
        same company can be the buyer on one deal and the seller on another. That is
        the point of the whole keystone (plan §1).

        **Set once.** Naming a different company later is refused, by this method and
        by `trg_deal_buyer_company_set_once` behind it — see
        `DealBuyerCompanyAlreadySetError` for why re-pointing it is worse than
        refusing it. Naming the *same* company again changes nothing and is allowed,
        so a retried request is not an error.

        The legacy `deal_buyer` row, if the deal has one, is deliberately left alone.
        It is what a handover before the migration was built from, and the deal
        response still serves it until P4-10 retires those writes; the company is the
        authority from here on (contract §3.0).

        Writes a `deal` history row with `event_type="deal_buyer_company_set"`.

        Raises:
            DealNotFoundError: no such deal.
            DealTerminalError: the deal is handed over or withdrawn.
            DealCompanyNotFoundError: no such company.
            DealBuyerIsTheSellerError: that company is the seller on this deal.
            DealBuyerCompanyAlreadySetError: the deal already names a different one.
        """
        deal = await self._lock_deal(deal_id)
        if deal.stage.is_terminal:
            # The same rule as `set_buyer`: a handed-over deal's buyer is what the
            # lending team was given, and a withdrawn deal's is history.
            raise DealTerminalError(deal_id, deal.stage.value)

        if deal.buyer_company_id is not None:
            if deal.buyer_company_id == buyer_company_id:
                # Already so. Not an error — a retried request must not fail — and
                # nothing to record, since nothing changed.
                return await self._to_view(deal)
            raise DealBuyerCompanyAlreadySetError(deal_id, deal.buyer_company_id)

        if buyer_company_id == deal.company_id:
            # `ck_deal_buyer_is_not_the_seller` would refuse the row; this names the
            # problem instead of surfacing a constraint violation.
            raise DealBuyerIsTheSellerError(deal_id, buyer_company_id)

        company = await self._db.scalar(
            select(ExporterProfile).where(
                ExporterProfile.customer_id == buyer_company_id
            )
        )
        if company is None:
            # `fk_deal_buyer_company_id` would refuse it; a 404 naming the company is
            # the useful answer.
            raise DealCompanyNotFoundError(buyer_company_id)

        deal.buyer_company_id = buyer_company_id
        await self._history.record(
            deal.company_id,
            dimension="deal",
            to_value=deal.stage.value,
            actor_id=actor_id,
            source="deal_service.set_buyer_company",
            deal_id=deal.id,
            event_type="deal_buyer_company_set",
            details={
                "buyer_company_id": str(buyer_company_id),
                "buyer_name": company.name,
                # Whether this deal also carries a legacy `deal_buyer` row, so the
                # P4-10 retirement can tell which deals still have both.
                "had_legacy_buyer": deal.buyer is not None,
            },
        )
        await self._db.commit()
        await self._db.refresh(deal)

        logger.info(
            "deal.buyer_company.set.ok",
            deal_id=str(deal.id),
            buyer_company_id=str(buyer_company_id),
            actor_id=actor_id,
        )
        return await self._to_view(deal)

    # ── The handover ─────────────────────────────────────────────────────────

    async def _handover_snapshot(self, deal: Deal) -> _Handover:
        """The buyer and the document ids this handover rests on.

        Both are what the lending team is given (architecture §3.6). The document
        list is a snapshot, not a live query the receiver could re-run later and get
        a different answer from.

        The buyer is already loaded on the deal; the documents are read here rather
        than kept on the deal, because "the paperwork for this deal" is a question
        about `crm_document`, not a column.
        """
        documents = await CrmDocumentRepository(self._db).list_for_deal_ids((deal.id,))
        buyer = deal.buyer
        # Built from the buyer **company** when the deal names one, and from the
        # legacy `deal_buyer` row otherwise (plan P4-4). The company is the
        # authority, so a deal carrying both snapshots the company: that is what the
        # lending team is being handed, and what every later read of this deal's
        # buyer resolves to.
        #
        # The keys are the same either way, because the snapshot is a record of what
        # was handed over and a reader must not have to know which era wrote it. A
        # company has no `tax_id` of its own — PAN is the Indian equivalent and
        # `registration_number` the foreign one — so `tax_id` is the PAN, and the
        # contact fields are empty: a company's contacts are people on its own
        # record, not one pair of fields, and inventing a primary contact here would
        # put a name in the handover that nobody chose.
        if deal.buyer_company_id is not None:
            company = await self._db.scalar(
                select(ExporterProfile).where(
                    ExporterProfile.customer_id == deal.buyer_company_id
                )
            )
        else:
            company = None

        if company is not None:
            buyer_details = {
                "name": company.name,
                "country": company.country,
                "registration_number": company.registration_number,
                "tax_id": company.pan,
                "contact_email": None,
                "contact_phone": None,
            }
        elif buyer is not None:
            buyer_details = {
                "name": buyer.name,
                "country": buyer.country,
                "registration_number": buyer.registration_number,
                "tax_id": buyer.tax_id,
                "contact_email": buyer.contact_email,
                "contact_phone": buyer.contact_phone,
            }
        else:
            # `_NEEDS_BUYER` already refused a handover without either, so this is
            # unreachable from `transition_stage`; it is here so the method is safe
            # to call from anywhere.
            buyer_details = {}

        return _Handover(
            buyer=buyer_details,
            document_ids=[str(document.id) for document in documents],
            # Recorded alongside the buyer's details, not instead of them: once
            # P4-4 points deals at company records, the snapshot has to say *which*
            # company was handed over as well as what it looked like at the time.
            buyer_company_id=deal.buyer_company_id,
            at=deal.handed_over_at or clock.now(),
        )

    # ── The A5 handover guard ────────────────────────────────────────────────

    async def _handover_blocked_reason(self, deal: Deal, *, lock: bool = False) -> str | None:
        """Why this deal may not be handed over — every unmet condition, joined with
        ``"; "`` — or ``None`` if it may.

        **The rules themselves are ``domain/handover_conditions.py``'s**, an ordered
        list of condition functions over the providers injected into this service
        (allocation F2). This method's job is the part only a service can do: read
        the seller's row **once**, under the right lock, and hand every condition
        the same snapshot of it.

        Assumption A5 — the company's journey is ``CUSTOMER`` **and** its background
        check is ``CLEAR`` — is the first two conditions. Both are real: Developer 4A's
        migration 0015 landed and ``read_background_check`` calls their published
        helper, so a company that has never been checked reads ``NOT_STARTED`` — a
        fact, not an absence — and "not ``CLEAR``" is never treated as "clear". The
        remaining four conditions are inert until their provider ships.

        ``lock`` takes ``FOR SHARE`` on the company row (**decision D10, settled 28
        September 2026**). It is passed only by ``transition_stage``, never by the
        read that renders a deal:

        * **On the move**, the lock closes a real race. Dev4A's own moves take
          ``FOR UPDATE``, so a share lock here makes a concurrent ``FLAGGED`` wait
          until this transaction ends. Without it a flag could commit between this
          guard seeing ``CLEAR`` and the handover committing, and the lending team
          would be given a deal on a company flagged moments earlier — with nothing
          in the record showing the overlap. A handover cannot be undone, which is
          what makes the narrow window worth closing.
        * **On the read** it would be actively harmful: ``_to_view`` runs on every
          deal page load, and locking there would have ordinary rendering block
          compliance's decisions.

        ``FOR SHARE`` rather than ``FOR UPDATE`` deliberately: it blocks Dev4A's
        writers, which is the point, while two handovers of different deals on the
        same company still proceed in parallel.
        """
        # **Both** parties, in one statement ordered by `customer_id` (P4-7). The
        # seller alone was enough while only its own standing was read; condition 5
        # now reads the buyer's, so a flag landing on the buyer between this guard and
        # the commit would be the same race D10 closed for the seller.
        #
        # `ORDER BY customer_id` is the deadlock rule, not a tidiness one: Postgres
        # takes row locks in the order the query returns them, so two handovers that
        # share a pair of companies — A selling to B while B sells to A — queue in one
        # order instead of each holding what the other wants. Sorted on the database
        # rather than in Python, so the lock order is the one the SQL actually used.
        #
        # By `customer_id`, not `db.get`: `customer_id` is the company's business
        # key and the target of `fk_deal_company_id`, while the table's primary key
        # is the inherited `id`. `db.get` would look up the wrong column and find
        # nothing for every company.
        wanted = {deal.company_id}
        if deal.buyer_company_id is not None:
            # `ck_deal_buyer_is_not_the_seller` rules out the two being equal, so this
            # is two rows whenever a buyer company is recorded.
            wanted.add(deal.buyer_company_id)
        statement = select(ExporterProfile).where(ExporterProfile.customer_id.in_(wanted))
        if lock:
            statement = statement.order_by(ExporterProfile.customer_id).with_for_update(
                read=True
            ).execution_options(populate_existing=True)
        rows = {row.customer_id: row for row in await self._db.scalars(statement)}

        company = rows.get(deal.company_id)
        if company is None:  # pragma: no cover - the FK makes this unreachable
            raise DealCompanyNotFoundError(deal.company_id)
        if deal.buyer_company_id is not None and deal.buyer_company_id not in rows:
            # pragma: no cover - `fk_deal_buyer_company_id` makes this unreachable
            raise DealCompanyNotFoundError(deal.buyer_company_id)

        # Every unmet condition, journey first, so the screen tells the whole story at
        # once — a PROSPECT whose check is FLAGGED needs both fixed, not one.
        subject = HandoverSubject(
            deal_id=deal.id,
            seller_company_id=deal.company_id,
            seller_journey=company.journey.value,
            # Through the read seam, so Developer 1 owns that one function's body
            # and the conditions never reach for the column themselves.
            seller_background_check=read_background_check(company),
            buyer_company_id=deal.buyer_company_id,
            legacy_buyer_id=deal.buyer.id if deal.buyer is not None else None,
            seller_gst_registration_id=deal.seller_gst_registration_id,
            # One "now" for the whole run, so two conditions cannot disagree about
            # whether a check had expired — and taken from the shared clock
            # (allocation §2.2), so a test can move past a Clear's expiry instead of
            # rewriting a decision the database refuses to change anyway.
            now=clock.now(),
        )
        return await blocked_reason(subject, self._providers)

    # ── Internals ────────────────────────────────────────────────────────────

    async def _to_view(self, deal: Deal) -> DealView:
        moves = self.allowed_stage_moves(deal.stage)
        blocked = (
            await self._handover_blocked_reason(deal)
            if any(move.to is DealStage.HANDED_OVER for move in moves)
            else None
        )
        if blocked is not None:
            # Not offered, and the reason says why — so the screen explains rather
            # than showing a button that 409s (contract §4.1).
            moves = [move for move in moves if move.to is not DealStage.HANDED_OVER]

        return DealView(
            id=deal.id,
            company_id=deal.company_id,
            reference=deal.reference,
            stage=deal.stage,
            withdrawal_reason=deal.withdrawal_reason,
            handed_over_at=deal.handed_over_at,
            created_at=deal.created_at,
            updated_at=deal.updated_at,
            buyer=(
                DealBuyerView(
                    id=deal.buyer.id,
                    deal_id=deal.buyer.deal_id,
                    name=deal.buyer.name,
                    country=deal.buyer.country,
                    registration_number=deal.buyer.registration_number,
                    tax_id=deal.buyer.tax_id,
                    contact_email=deal.buyer.contact_email,
                    contact_phone=deal.buyer.contact_phone,
                )
                if deal.buyer is not None
                else None
            ),
            buyer_company=await self._buyer_company(deal),
            handover_snapshot=deal.handover_snapshot,
            seller_gst_registration_id=deal.seller_gst_registration_id,
            allowed_stage_moves=tuple(moves),
            handover_blocked_reason=blocked,
        )

    async def _buyer_company(self, deal: Deal) -> BuyerCompanyView | None:
        """The buyer as a company record — ``None`` on every deal whose buyer is
        still a ``deal_buyer`` row (plan P4-4, filled by the migration in P4-6).

        A summary, not the company: a deal page wants enough to recognise the buyer
        and to click through, and the whole company record is one request away. The
        identifiers are the ones the company response already carries, so they are
        masked by the same rule in the same place (``schemas/deal.py``).
        """
        if deal.buyer_company_id is None:
            return None
        company = await self._db.scalar(
            select(ExporterProfile).where(
                ExporterProfile.customer_id == deal.buyer_company_id
            )
        )
        if company is None:  # pragma: no cover - `fk_deal_buyer_company_id` forbids it
            return None
        return BuyerCompanyView(
            company_id=company.customer_id,
            name=company.name,
            country=company.country,
            # Developer 3's F3 column, read by name through `state_name` so an enum
            # and a string look the same here. The `getattr` this used to need came
            # out when F3 merged, as its comment said it would.
            pipeline_status=state_name(company.pipeline_status),
            pan=company.pan,
            cin=company.cin,
        )

    async def _require_deal(self, deal_id: uuid.UUID) -> Deal:
        deal = await self._deals.get_by_id(deal_id)
        if deal is None:
            raise DealNotFoundError(deal_id)
        return deal

    async def _lock_deal(self, deal_id: uuid.UUID) -> Deal:
        deal = await self._deals.lock_by_id(deal_id)
        if deal is None:
            raise DealNotFoundError(deal_id)
        return deal

    async def _company_journey(self, company_id: uuid.UUID) -> str | None:
        """The company's journey as a plain value, or ``None`` if there is no such
        company."""
        journey = await self._db.scalar(
            select(ExporterProfile.journey).where(ExporterProfile.customer_id == company_id)
        )
        return None if journey is None else journey.value


#: The buyer fields ``set_buyer(keep=...)`` may leave as stored.
_BUYER_OPTIONAL_FIELDS = frozenset(
    {"registration_number", "tax_id", "contact_email", "contact_phone"}
)


def _clean(value: str | None) -> str | None:
    """Empty and whitespace-only become ``NULL``, so "not given" is one value in
    the database rather than three."""
    return (value or "").strip() or None
