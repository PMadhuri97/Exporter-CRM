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
never imports 3A's enum to compare against it (``company-record.md`` §2.4).

**What it does not decide.** Which roles may open a deal or move a stage is the
route's, via ``require_role`` in ``deal_router.py``, matching the §3.7 matrix. This
service holds the *rules* — which moves exist, which need a reason, which need a
buyer — and ``allowed_stage_moves`` is those rules as data, so the screen asks the
server instead of keeping a copy (§7.5). That split is
``ConversationService.allowed_moves``' and is deliberately the same shape.

**The handover is built, and currently refuses every deal.**
``GATHERING_PAPERWORK → HANDED_OVER`` needs the company to be a ``CUSTOMER`` with a
``CLEAR`` background check (assumption A5). The second half cannot be evaluated:
``exporter_profile.background_check`` is Developer 4's column in migration 0015,
which has not landed, so ``read_background_check`` returns ``None``, the move is not
offered, ``handover_blocked_reason`` says why, and attempting it is refused.
Nothing here creates or writes that column (``company-record.md`` §2.4).

Everything downstream of that guard is real and tested: the document snapshot, the
history row, and the best-effort ``deal.handed_over`` announcement, in that order
(architecture §3.6 — the history row is the source of truth, the announcement is an
announcement). Tests reach it by substituting ``read_background_check``, which is a
separate function for exactly that reason.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.conversation_service import ConversationService
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.deal_views import (
    DealBuyerView,
    DealListItemView,
    DealStageMove,
    DealView,
)
from app.modules.onboarding.domain.entities.deal import Deal
from app.modules.onboarding.domain.entities.deal_buyer import DealBuyer
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.events.publisher import OnboardingEventPublisher
from app.modules.onboarding.exceptions import (
    DealBuyerRequiredError,
    DealCompanyNotFoundError,
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
#: may be handed over (assumption A5's first half). Compared by *name* rather than
#: by importing Developer 2's enum member, so this file states the rule without
#: taking a dependency on the shape of their enum.
_HANDOVER_JOURNEY = "CUSTOMER"


def read_background_check(company: ExporterProfile) -> str | None:
    """The company's background check, as a plain string, or ``None`` if there is
    none recorded.

    **This is a stand-in for Developer 4's read helper** (L4-01), and it is a
    separate function for two reasons.

    First, honesty: ``exporter_profile.background_check`` is Developer 4's column in
    migration 0015, which has not landed, so today this always returns ``None`` and
    every handover is refused. ``company-record.md`` §2.4 forbids creating or
    writing another developer's gauge field, so the column is not added here, and
    "not recorded" is never treated as "clear" — that would hand a deal to the
    lending team on the strength of a column that does not exist.

    Second, testability: the handover path downstream of the guard — the document
    snapshot, the history row, the announcement — is real code that must be exercised
    now rather than written blind and discovered broken when 0015 lands. Tests
    substitute this one function to reach it, and say in their docstrings that they
    are doing so.

    When Developer 4 publishes their helper, this body becomes a call to it and
    nothing else changes.
    """
    value = getattr(company, "background_check", None)
    if value is None:
        return None
    return str(getattr(value, "value", value))


@dataclass(frozen=True)
class _Handover:
    """What one handover rests on, captured inside the transaction that made it.

    Frozen, and built once: the whole point is that this cannot change between the
    commit and the announcement, nor afterwards.
    """

    buyer: dict
    document_ids: list[str]


class DealService:
    """Open deals, move their stages, record their buyers, and hand them over."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._deals = DealRepository(db)
        self._buyers = DealBuyerRepository(db)
        self._history = HistoryService(db)
        self._conversation = ConversationService(db)
        # Best effort by construction: `deal_handed_over` logs and swallows its
        # own failures, so a dead bus never undoes a committed handover.
        self._events = OnboardingEventPublisher()

    # ── Read ─────────────────────────────────────────────────────────────────

    async def get_deal(self, deal_id: uuid.UUID) -> DealView:
        deal = await self._require_deal(deal_id)
        return await self._to_view(deal)

    async def list_for_company(
        self,
        company_id: uuid.UUID,
        *,
        stages: tuple[DealStage, ...] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[DealListItemView], int]:
        deals, total = await self._deals.list_for_company(
            company_id, stages=stages, limit=limit, offset=offset
        )
        return [
            DealListItemView(
                id=deal.id,
                company_id=deal.company_id,
                reference=deal.reference,
                stage=deal.stage,
                buyer_name=deal.buyer.name if deal.buyer is not None else None,
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
        locks the row itself before moving the gauge.
        """
        cleaned_reference = (reference or "").strip()
        if not cleaned_reference:
            raise ValidationError("a deal needs a reference")

        if not await self._company_exists(company_id):
            raise DealCompanyNotFoundError(company_id)

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

        Step 5's guard is Phase 4's, and it currently refuses every handover
        because Developer 4's ``background_check`` column does not exist yet.
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
            if deal.buyer is None:
                raise DealBuyerRequiredError(deal_id)
            blocked = await self._handover_blocked_reason(deal)
            if blocked is not None:
                raise DealHandoverBlockedError(deal_id, blocked)

        deal.stage = to_stage
        deal.withdrawal_reason = cleaned_reason
        handover: _Handover | None = None
        if to_stage is DealStage.HANDED_OVER:
            deal.handed_over_at = datetime.now(tz=UTC)
            # The snapshot is taken **now**, inside the transaction, so it is the
            # list the handover actually rested on: a document uploaded a minute
            # later cannot change what the lending team was given (architecture
            # §3.6). Collected before the commit, announced after it.
            handover = await self._handover_snapshot(deal)

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

        Writes a ``deal`` history row with ``event_type="deal_buyer_changed"`` and
        the changed field names in ``details``: a buyer's details are part of a
        deal's story, and a separate ``buyer`` dimension would need a change to
        ``history-row.md`` §2, which is Developer 1's.
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
            details={"buyer_name": cleaned_name, "changed": changed},
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
        return _Handover(
            buyer=(
                {
                    "name": buyer.name,
                    "country": buyer.country,
                    "registration_number": buyer.registration_number,
                    "tax_id": buyer.tax_id,
                    "contact_email": buyer.contact_email,
                    "contact_phone": buyer.contact_phone,
                }
                # `_NEEDS_BUYER` already refused a handover without one, so this
                # branch is unreachable from `transition_stage`; it is here so the
                # method is safe to call from anywhere.
                if buyer is not None
                else {}
            ),
            document_ids=[str(document.id) for document in documents],
        )

    # ── The A5 handover guard ────────────────────────────────────────────────

    async def _handover_blocked_reason(self, deal: Deal) -> str | None:
        """Why this deal may not be handed over, or ``None`` if it may.

        Assumption A5: the company's journey is ``CUSTOMER`` **and** its background
        check is ``CLEAR``.

        The second half cannot be evaluated yet. ``exporter_profile`` has no
        ``background_check`` column — it is Developer 4's, in migration 0015, which
        has not landed — and ``company-record.md`` §2.4 forbids creating or writing
        another developer's gauge field. So this reports the missing check
        honestly rather than treating "not recorded" as "clear", which would hand a
        deal to the lending team on the strength of a column that does not exist.

        Phase 4 replaces the ``getattr`` below with Developer 4's published read
        helper (L4-01) once it exists.
        """
        # By `customer_id`, not `db.get`: `customer_id` is the company's business
        # key and the target of `fk_deal_company_id`, while the table's primary key
        # is the inherited `id`. `db.get` would look up the wrong column and find
        # nothing for every company.
        company = await self._db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == deal.company_id)
        )
        if company is None:  # pragma: no cover - the FK makes this unreachable
            raise DealCompanyNotFoundError(deal.company_id)

        if company.journey.value != _HANDOVER_JOURNEY:
            return f"the company is {company.journey.value}, not {_HANDOVER_JOURNEY}"

        background_check = read_background_check(company)
        if background_check is None:
            return (
                "the background check is not recorded yet — Developer 4's "
                "migration 0015 has not landed, so no company has one"
            )
        if background_check != "CLEAR":
            return f"the background check is {background_check}, not CLEAR"
        return None

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
            allowed_stage_moves=tuple(moves),
            handover_blocked_reason=blocked,
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

    async def _company_exists(self, company_id: uuid.UUID) -> bool:
        return (
            await self._db.scalar(
                select(ExporterProfile.customer_id).where(
                    ExporterProfile.customer_id == company_id
                )
            )
        ) is not None


#: The buyer fields ``set_buyer(keep=...)`` may leave as stored.
_BUYER_OPTIONAL_FIELDS = frozenset(
    {"registration_number", "tax_id", "contact_email", "contact_phone"}
)


def _clean(value: str | None) -> str | None:
    """Empty and whitespace-only become ``NULL``, so "not given" is one value in
    the database rather than three."""
    return (value or "").strip() or None
