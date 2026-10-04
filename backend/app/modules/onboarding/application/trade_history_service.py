"""``TradeHistoryService`` — what two companies have traded, and how it went —
**owner: Developer 3** (allocation tasks 3.18 and 3.19, plan P5-1, P5-2).

Three operations and one invariant.

``get_or_create_relationship`` is **idempotent under concurrency**, which is the
whole difficulty of task 3.18: two deals recording the same new pair at the same
moment must produce one relationship. It is written as insert-then-handle-the-race
rather than check-then-insert, because the check-then-insert version is wrong on a
database with more than one writer and passes every single-threaded test.

``record_invoice`` writes a fact about the past, whose identity the database then
freezes. ``record_outcome`` appends to a superseding chain — never edits — and
refuses to supersede anything but the chain's current head, so two people cannot each
correct the same outcome without seeing the other's.

Currency is stored and never converted (decision IQ-4). There is no reporting
currency and no rate, here or anywhere.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain import history_dimensions
from app.modules.onboarding.domain.entities.deal import Deal
from app.modules.onboarding.domain.entities.deal_enums import DealStage
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.trade_enums import (
    TradePaymentStatus,
    TradeProofStatus,
)
from app.modules.onboarding.domain.entities.trade_invoice import (
    DealInvoiceDraft,
    TradeInvoice,
    TradeInvoiceOutcome,
)
from app.modules.onboarding.domain.entities.trade_relationship import TradeRelationship
from app.modules.onboarding.domain.verification_evidence import (
    EvidenceRef,
    VerificationEvidence,
    check_evidence_shape,
)
from app.modules.onboarding.exceptions import (
    DealBuyerIsNotACompanyError,
    DealNotFoundError,
    DealNotHandedOverError,
    ExporterProfileNotFoundError,
    TradeInvoiceAlreadyRecordedError,
    TradeInvoiceDealNotThisPairError,
    TradeInvoiceNotFoundError,
    TradeOutcomeStaleError,
    TradeRelationshipIsSelfError,
    TradeRelationshipNotFoundError,
)
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)

#: The history dimension trade writes record. Developer 1's one list.
HISTORY_DIMENSION_TRADE = history_dimensions.TRADE

#: How a relationship came to exist (BQ-7).
SOURCE_DEAL_BUYER_RECORDED = "deal_buyer_recorded"
SOURCE_BACKFILL = "backfill"
SOURCE_MANUAL = "manual"


class TradeHistoryService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._history = HistoryService(db)

    # ── Relationships (task 3.18) ────────────────────────────────────────────

    async def get_or_create_relationship(
        self,
        *,
        seller_company_id: uuid.UUID,
        buyer_company_id: uuid.UUID,
        actor_id: str | None = None,
        source: str = SOURCE_MANUAL,
        source_ref: str | None = None,
    ) -> tuple[TradeRelationship, bool]:
        """The relationship for this ordered pair, creating it if it is new.

        Returns ``(relationship, created)``.

        **Safe under concurrency**, which is task 3.18's acceptance criterion: two
        deals recording the same new pair at the same moment produce one relationship.
        Done with ``INSERT … ON CONFLICT DO NOTHING`` against
        ``uq_trade_relationship_pair`` and then a read, rather than "look, then
        insert": the latter has a window between the two statements, and a test with
        one writer never finds it.

        The insert is in a savepoint so a loser's conflict does not poison the
        caller's transaction — this is usually called inside a larger unit of work
        (recording a deal's buyer), and that work must survive losing the race.

        **It does not commit**, for the same reason: the caller owns the transaction.
        A caller that only wants a relationship has to commit it.

        Ordered, not symmetric: A selling to B is a different relationship from B
        selling to A.
        """
        if seller_company_id == buyer_company_id:
            # `ck_trade_relationship_not_self` refuses it; this names the problem.
            raise TradeRelationshipIsSelfError(seller_company_id)

        for company_id in (seller_company_id, buyer_company_id):
            if await self._db.scalar(
                select(ExporterProfile.customer_id).where(
                    ExporterProfile.customer_id == company_id
                )
            ) is None:
                raise ExporterProfileNotFoundError(company_id)

        async with self._db.begin_nested():
            inserted = await self._db.scalar(
                pg_insert(TradeRelationship)
                .values(
                    seller_company_id=seller_company_id,
                    buyer_company_id=buyer_company_id,
                    created_by=actor_id,
                    source=source,
                    source_ref=source_ref,
                )
                .on_conflict_do_nothing(constraint="uq_trade_relationship_pair")
                # `RETURNING` yields a row only when the insert actually wrote one, so
                # `created` is the database's answer rather than a guess. Comparing the
                # stored `created_by` to ours would be wrong whenever the same actor
                # asks twice.
                .returning(TradeRelationship.id)
            )
        created = inserted is not None

        relationship = await self._db.scalar(
            select(TradeRelationship).where(
                TradeRelationship.seller_company_id == seller_company_id,
                TradeRelationship.buyer_company_id == buyer_company_id,
            )
        )
        # Unreachable: the insert either wrote the row or found it already there.
        assert relationship is not None

        logger.info(
            "trade_relationship.get_or_create",
            relationship_id=str(relationship.id),
            created=created,
            source=source,
        )
        return relationship, created

    async def list_relationships(
        self, company_id: uuid.UUID, *, as_buyer: bool = False
    ) -> list[TradeRelationship]:
        """This company's relationships — the ones it sells on, or with ``as_buyer``
        the ones it buys on. Two questions, two lists, for the same reason the deal
        lists are separate (task 2.7)."""
        column = (
            TradeRelationship.buyer_company_id
            if as_buyer
            else TradeRelationship.seller_company_id
        )
        rows = await self._db.scalars(
            select(TradeRelationship)
            .where(column == company_id)
            .order_by(TradeRelationship.created_at.desc())
        )
        return list(rows)

    async def relationship_for_pair(
        self, *, seller_company_id: uuid.UUID, buyer_company_id: uuid.UUID
    ) -> TradeRelationship | None:
        """The pair's relationship, or ``None``. A read, so it creates nothing — the
        deal page asks this to decide whether there is any history to show."""
        return await self._db.scalar(
            select(TradeRelationship).where(
                TradeRelationship.seller_company_id == seller_company_id,
                TradeRelationship.buyer_company_id == buyer_company_id,
            )
        )

    # ── Invoices (task 3.19) ─────────────────────────────────────────────────

    async def record_invoice(
        self,
        relationship_id: uuid.UUID,
        *,
        invoice_number: str,
        invoice_date: date,
        amount: Decimal,
        currency: str,
        deal_id: uuid.UUID | None = None,
        actor_id: str | None,
        source: str = SOURCE_MANUAL,
        source_ref: str | None = None,
    ) -> TradeInvoice:
        """Record an invoice against a relationship.

        Its identity is frozen the moment it is written
        (``trg_trade_invoice_identity_immutability``): an invoice whose amount could
        be edited afterwards is not evidence of anything. A mistake is corrected by
        recording the right invoice, and the wrong one stays visible — which is the
        same trade-off every append-only table in this module makes.

        ``deal_id`` is optional, because past trade predates us (task 3.21).

        ``currency`` is stored as given, upper-cased, and **never converted**
        (IQ-4). ISO 4217's shape is checked here and by
        ``ck_trade_invoice_currency``, because a code nobody can look up is permanent
        nonsense in a column that is never recomputed.

        ``deal_id``, when given, must be a deal **between this relationship's two
        companies** — the seller's deal with this buyer company (R-17). The value is
        frozen once written and nothing else ties an invoice to a deal, so a wrong id
        would sit on the invoice for good.

        Raises:
            TradeRelationshipNotFoundError: no such relationship.
            DealNotFoundError: ``deal_id`` names no deal.
            TradeInvoiceDealNotThisPairError: the deal is not between these companies.
            ValidationError: a blank number, a non-positive amount, a malformed
                currency, or a number this relationship already has.
        """
        invoice = await self._write_invoice(
            relationship_id,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            amount=amount,
            currency=currency,
            deal_id=deal_id,
            actor_id=actor_id,
            source=source,
            source_ref=source_ref,
        )
        await self._db.commit()
        await self._db.refresh(invoice)
        logger.info(
            "trade_invoice.recorded",
            invoice_id=str(invoice.id),
            relationship_id=str(relationship_id),
            currency=invoice.currency,
        )
        return invoice

    async def _write_invoice(
        self,
        relationship_id: uuid.UUID,
        *,
        invoice_number: str,
        invoice_date: date,
        amount: Decimal,
        currency: str,
        deal_id: uuid.UUID | None,
        actor_id: str | None,
        source: str,
        source_ref: str | None,
    ) -> TradeInvoice:
        """``record_invoice`` without the commit: flushed, with its history row, inside
        the caller's transaction. ``record_outcome_for_deal`` needs the invoice and its
        outcome to land together or not at all (R-12)."""
        relationship = await self._db.scalar(
            select(TradeRelationship).where(TradeRelationship.id == relationship_id)
        )
        if relationship is None:
            raise TradeRelationshipNotFoundError(relationship_id)
        if deal_id is not None:
            deal = await self._db.scalar(select(Deal).where(Deal.id == deal_id))
            if deal is None:
                raise DealNotFoundError(deal_id)
            if (deal.company_id, deal.buyer_company_id) != (
                relationship.seller_company_id,
                relationship.buyer_company_id,
            ):
                raise TradeInvoiceDealNotThisPairError(deal_id, relationship_id)

        number = (invoice_number or "").strip()
        if not number:
            raise ValidationError("an invoice needs its number")
        code = (currency or "").strip().upper()
        if len(code) != 3 or not code.isalpha() or not code.isascii():
            raise ValidationError(
                "currency must be a three-letter ISO 4217 code, for example USD"
            )
        if amount is None or Decimal(amount) <= 0:
            raise ValidationError("an invoice is for a positive amount")

        invoice = TradeInvoice(
            relationship_id=relationship_id,
            deal_id=deal_id,
            invoice_number=number,
            invoice_date=invoice_date,
            amount=Decimal(amount),
            currency=code,
            created_by=actor_id,
            source=source,
            source_ref=source_ref,
        )
        self._db.add(invoice)
        try:
            async with self._db.begin_nested():
                await self._db.flush()
        except IntegrityError as exc:
            # `uq_trade_invoice_number`: this relationship already has this number.
            raise ValidationError(
                f"invoice {number} is already recorded for this trade relationship"
            ) from exc

        await self._record_trade_history(
            relationship,
            event_type="trade_invoice_recorded",
            to_value=code,
            actor_id=actor_id,
            deal_id=deal_id,
            details={
                "invoice_id": str(invoice.id),
                "invoice_number": number,
                "amount": str(invoice.amount),
                "currency": code,
            },
        )
        return invoice

    async def list_invoices(self, relationship_id: uuid.UUID) -> list[TradeInvoice]:
        rows = await self._db.scalars(
            select(TradeInvoice)
            .where(TradeInvoice.relationship_id == relationship_id)
            .order_by(TradeInvoice.invoice_date.desc(), TradeInvoice.id.desc())
        )
        return list(rows)

    # ── Outcomes: an append-only chain (task 3.19) ───────────────────────────

    async def record_outcome(
        self,
        invoice_id: uuid.UUID,
        *,
        payment_status: TradePaymentStatus,
        proof_status: TradeProofStatus = TradeProofStatus.CLAIMED,
        amount_paid: Decimal | None = None,
        evidence_note: str | None = None,
        evidence_refs: list[dict] | None = None,
        supersedes_outcome_id: uuid.UUID | None = None,
        actor_id: str | None,
        source: str = SOURCE_MANUAL,
        source_ref: str | None = None,
    ) -> TradeInvoiceOutcome:
        """Append what we now know about an invoice.

        Nothing is edited. A correction is a **new** row naming the one it replaces,
        so the record says what we believed and when we stopped believing it — the
        same shape as a verification review, and ``public.prevent_mutation()`` holds
        it at the database.

        ``supersedes_outcome_id`` must be the chain's **current head**, or this is a
        409: a reviewer must not overrule a belief they have not seen. The first
        outcome omits it; a later one requires both it and an ``evidence_note``
        (``ck_trade_invoice_outcome_supersede_note``), because "we changed our mind"
        with no reason is not a record anyone can act on.

        ``PARTIAL`` requires ``amount_paid``. Nothing else may claim an amount it did
        not receive, and a payment in another currency is a conversion, which IQ-4
        rules out — so there is one amount, in the invoice's own currency.

        **Safe under concurrency** (R-13). The invoice row is locked ``FOR UPDATE``
        before the head is read, so two outcomes for one invoice are decided one after
        the other: the second sees the first as the head and is refused as stale, with
        the 409 the route documents, rather than racing it into a unique index and a
        500.

        Raises:
            TradeInvoiceNotFoundError: no such invoice.
            TradeOutcomeStaleError: ``supersedes_outcome_id`` is not the head.
            ValidationError: a missing ``amount_paid`` for ``PARTIAL``, a correction
                with no note, or malformed evidence.
        """
        outcome = await self._write_outcome(
            invoice_id,
            payment_status=payment_status,
            proof_status=proof_status,
            amount_paid=amount_paid,
            evidence_note=evidence_note,
            evidence_refs=evidence_refs,
            supersedes_outcome_id=supersedes_outcome_id,
            actor_id=actor_id,
            source=source,
            source_ref=source_ref,
        )
        await self._db.commit()
        await self._db.refresh(outcome)
        logger.info(
            "trade_outcome.recorded",
            invoice_id=str(invoice_id),
            outcome_id=str(outcome.id),
            payment_status=payment_status.value,
            superseded=str(supersedes_outcome_id) if supersedes_outcome_id else None,
        )
        return outcome

    @staticmethod
    def _checked_outcome(
        *,
        payment_status: TradePaymentStatus,
        amount_paid: Decimal | None,
        evidence_note: str | None,
        evidence_refs: list[dict] | None,
    ) -> tuple[EvidenceRef, ...]:
        """Everything about an outcome that can be checked without reading the
        database — so ``record_outcome_for_deal`` can refuse a bad request before it
        writes anything (R-12). Returns the parsed evidence references.

        Raises:
            ValidationError: a missing ``amount_paid`` for ``PARTIAL``, a negative
                amount, or malformed evidence.
        """
        if payment_status is TradePaymentStatus.PARTIAL and amount_paid is None:
            raise ValidationError("a PARTIAL outcome must say how much was paid")
        if amount_paid is not None and Decimal(amount_paid) < 0:
            raise ValidationError("amount_paid cannot be negative")
        if not evidence_refs:
            return ()
        # The **shape** rule a verification result's evidence gets, reused rather than
        # reimplemented so trade evidence and compliance evidence cannot drift: every
        # reference names a known type and a non-blank ref, and a `url` is an http(s)
        # link. Whether a referenced document belongs to the right subject is
        # `VerificationService`'s own check and does not apply here — a trade invoice's
        # proof may be the buyer's bank advice, which is nobody's company document.
        try:
            refs = tuple(
                EvidenceRef(type=str(r.get("type", "")), ref=str(r.get("ref", "")))
                for r in evidence_refs
            )
        except AttributeError as exc:
            raise ValidationError(
                "each evidence reference must be an object with a type and a ref"
            ) from exc
        check_evidence_shape(VerificationEvidence(note=evidence_note, refs=refs))
        return refs

    async def _write_outcome(
        self,
        invoice_id: uuid.UUID,
        *,
        payment_status: TradePaymentStatus,
        proof_status: TradeProofStatus,
        amount_paid: Decimal | None,
        evidence_note: str | None,
        evidence_refs: list[dict] | None,
        supersedes_outcome_id: uuid.UUID | None,
        actor_id: str | None,
        source: str,
        source_ref: str | None,
    ) -> TradeInvoiceOutcome:
        """``record_outcome`` without the commit: the invoice locked, the outcome
        flushed with its history row, inside the caller's transaction."""
        invoice = await self._db.scalar(
            select(TradeInvoice).where(TradeInvoice.id == invoice_id).with_for_update()
        )
        if invoice is None:
            raise TradeInvoiceNotFoundError(invoice_id)

        refs = self._checked_outcome(
            payment_status=payment_status,
            amount_paid=amount_paid,
            evidence_note=evidence_note,
            evidence_refs=evidence_refs,
        )

        head = await self._head_outcome(invoice_id)
        if head is None:
            if supersedes_outcome_id is not None:
                raise TradeOutcomeStaleError(invoice_id, supersedes_outcome_id, None)
        else:
            if supersedes_outcome_id is None:
                raise TradeOutcomeStaleError(invoice_id, None, head.id)
            if supersedes_outcome_id != head.id:
                raise TradeOutcomeStaleError(invoice_id, supersedes_outcome_id, head.id)
            if not (evidence_note or "").strip():
                raise ValidationError(
                    "a correction needs a note saying what changed: "
                    "the outcome it replaces stays on the record"
                )

        outcome = TradeInvoiceOutcome(
            invoice_id=invoice_id,
            payment_status=payment_status,
            amount_paid=Decimal(amount_paid) if amount_paid is not None else None,
            proof_status=proof_status,
            evidence_note=(evidence_note or "").strip() or None,
            evidence_refs=[r.as_json() for r in refs] if refs else None,
            recorded_by=actor_id,
            supersedes_outcome_id=supersedes_outcome_id,
            source=source,
            source_ref=source_ref,
        )
        self._db.add(outcome)
        try:
            async with self._db.begin_nested():
                await self._db.flush()
        except IntegrityError as exc:
            # `uq_trade_invoice_outcome_first` / `_supersedes`. The lock above makes
            # this unreachable for writers that go through here; a writer that does not
            # still gets the documented answer rather than a 500.
            self._db.expunge(outcome)
            raise TradeOutcomeStaleError(
                invoice_id, supersedes_outcome_id, getattr(head, "id", None)
            ) from exc

        relationship = await self._db.scalar(
            select(TradeRelationship).where(
                TradeRelationship.id == invoice.relationship_id
            )
        )
        await self._record_trade_history(
            relationship,
            event_type="trade_outcome_recorded",
            to_value=payment_status.value,
            from_value=head.payment_status.value if head is not None else None,
            actor_id=actor_id,
            deal_id=invoice.deal_id,
            details={
                "invoice_id": str(invoice_id),
                "outcome_id": str(outcome.id),
                "payment_status": payment_status.value,
                "proof_status": proof_status.value,
                "amount_paid": str(outcome.amount_paid) if outcome.amount_paid else None,
                "currency": invoice.currency,
            },
            reason=outcome.evidence_note,
        )
        return outcome

    # ── A handed-over deal's payment outcome (task 3.21) ─────────────────────

    async def record_outcome_for_deal(
        self,
        deal_id: uuid.UUID,
        *,
        payment_status: TradePaymentStatus,
        proof_status: TradeProofStatus = TradeProofStatus.CLAIMED,
        amount_paid: Decimal | None = None,
        evidence_note: str | None = None,
        evidence_refs: list[dict] | None = None,
        supersedes_outcome_id: uuid.UUID | None = None,
        invoice: DealInvoiceDraft | None = None,
        actor_id: str | None,
    ) -> tuple[TradeInvoice, TradeInvoiceOutcome]:
        """How a handed-over deal was actually paid — **creating the invoice if there
        is none** (task 3.21, plan P5-4).

        This is the question the CRM exists to answer in the end: the deal went to the
        lending team, and then what happened. Recording it at the *deal* is what makes
        that a single step for the person who knows the answer — they have a deal in
        front of them, not a relationship id and an invoice id.

        **The deal must be handed over.** Before that there is nothing to have been
        paid, and recording a payment against a deal still gathering paperwork would
        put an outcome on a trade that had not happened.

        **The deal must name a buyer company.** A relationship is a pair of company
        records; a legacy ``deal_buyer`` row is a set of details with nothing to pair
        with, so such a deal is refused until the buyer migration (P4-6) links it.
        That is a real limit, and saying so beats inventing a company.

        The relationship is created if the pair has none — ``get_or_create``, so two
        callers racing produce one. The invoice likewise: if this deal has no invoice
        yet, ``invoice`` supplies its identity and one is written. If it already has
        one, ``invoice`` must be omitted, because an invoice's identity is frozen and
        quietly ignoring new details would tell the caller they had been recorded.

        **All or nothing** (R-12). The request is checked before anything is written,
        and the relationship, the invoice and the outcome are written in one
        transaction committed once at the end. A refused request leaves no invoice
        behind, so the corrected retry is not refused for an invoice it never meant to
        create.

        **One request per deal at a time** (R-14). The deal row is locked ``FOR
        UPDATE`` first, so two first outcomes on a deal with no invoice cannot both
        create one: the second sees the first's invoice and is told so. Nothing more is
        enforced — whether a deal may have more than one invoice is decision D-03, and
        the relationship route still records a second one deliberately
        (``TradeInvoiceAlreadyRecordedError``). When a deal has several, this route
        answers about the earliest.

        Returns ``(invoice, outcome)``.
        """
        try:
            target, outcome, created_invoice = await self._outcome_for_deal(
                deal_id,
                payment_status=payment_status,
                proof_status=proof_status,
                amount_paid=amount_paid,
                evidence_note=evidence_note,
                evidence_refs=evidence_refs,
                supersedes_outcome_id=supersedes_outcome_id,
                invoice=invoice,
                actor_id=actor_id,
            )
            await self._db.commit()
        except Exception:
            # Whatever the caller does next, nothing of this request survives it.
            await self._db.rollback()
            raise
        await self._db.refresh(target)
        await self._db.refresh(outcome)
        logger.info(
            "trade_outcome.recorded_for_deal",
            deal_id=str(deal_id),
            invoice_id=str(target.id),
            outcome_id=str(outcome.id),
            created_invoice=created_invoice,
        )
        return target, outcome

    async def _outcome_for_deal(
        self,
        deal_id: uuid.UUID,
        *,
        payment_status: TradePaymentStatus,
        proof_status: TradeProofStatus,
        amount_paid: Decimal | None,
        evidence_note: str | None,
        evidence_refs: list[dict] | None,
        supersedes_outcome_id: uuid.UUID | None,
        invoice: DealInvoiceDraft | None,
        actor_id: str | None,
    ) -> tuple[TradeInvoice, TradeInvoiceOutcome, bool]:
        """``record_outcome_for_deal``'s writes, uncommitted. Returns the invoice, the
        outcome and whether the invoice was created here."""
        deal = await self._db.scalar(select(Deal).where(Deal.id == deal_id).with_for_update())
        if deal is None:
            raise DealNotFoundError(deal_id)
        if deal.stage is not DealStage.HANDED_OVER:
            raise DealNotHandedOverError(deal_id, deal.stage.value)
        if deal.buyer_company_id is None:
            raise DealBuyerIsNotACompanyError(deal_id)
        # Before any write: a request that can be refused on its own terms is.
        self._checked_outcome(
            payment_status=payment_status,
            amount_paid=amount_paid,
            evidence_note=evidence_note,
            evidence_refs=evidence_refs,
        )

        relationship, _created = await self.get_or_create_relationship(
            seller_company_id=deal.company_id,
            buyer_company_id=deal.buyer_company_id,
            actor_id=actor_id,
            source=SOURCE_DEAL_BUYER_RECORDED,
            source_ref=str(deal_id),
        )

        existing = await self._db.scalar(
            select(TradeInvoice)
            .where(
                TradeInvoice.relationship_id == relationship.id,
                TradeInvoice.deal_id == deal_id,
            )
            .order_by(TradeInvoice.created_at, TradeInvoice.id)
            .limit(1)
        )
        if existing is not None:
            if invoice is not None:
                raise TradeInvoiceAlreadyRecordedError(deal_id, existing.id)
            target = existing
        else:
            if invoice is None:
                raise ValidationError(
                    "this deal has no invoice yet, so recording how it was paid needs "
                    "the invoice's number, date, amount and currency"
                )
            target = await self._write_invoice(
                relationship.id,
                invoice_number=invoice.invoice_number,
                invoice_date=invoice.invoice_date,
                amount=invoice.amount,
                currency=invoice.currency,
                deal_id=deal_id,
                actor_id=actor_id,
                source=SOURCE_DEAL_BUYER_RECORDED,
                source_ref=str(deal_id),
            )

        outcome = await self._write_outcome(
            target.id,
            payment_status=payment_status,
            proof_status=proof_status,
            amount_paid=amount_paid,
            evidence_note=evidence_note,
            evidence_refs=evidence_refs,
            supersedes_outcome_id=supersedes_outcome_id,
            actor_id=actor_id,
            source=SOURCE_DEAL_BUYER_RECORDED,
            source_ref=str(deal_id),
        )
        return target, outcome, existing is None

    async def _head_outcome(self, invoice_id: uuid.UUID) -> TradeInvoiceOutcome | None:
        """The chain's current head: the outcome nothing supersedes.

        Found by "no row supersedes me" rather than by timestamp, because two rows
        written in one transaction share a ``created_at`` and the newest-looking row
        is not necessarily the live one.
        """
        superseded = select(TradeInvoiceOutcome.supersedes_outcome_id).where(
            TradeInvoiceOutcome.invoice_id == invoice_id,
            TradeInvoiceOutcome.supersedes_outcome_id.isnot(None),
        )
        return await self._db.scalar(
            select(TradeInvoiceOutcome).where(
                TradeInvoiceOutcome.invoice_id == invoice_id,
                TradeInvoiceOutcome.id.not_in(superseded),
            )
        )

    async def current_outcome(self, invoice_id: uuid.UUID) -> TradeInvoiceOutcome | None:
        """What we believe about this invoice now — the chain's head."""
        return await self._head_outcome(invoice_id)

    async def list_outcomes(self, invoice_id: uuid.UUID) -> list[TradeInvoiceOutcome]:
        """The whole chain, oldest first: every belief and when it was replaced."""
        rows = await self._db.scalars(
            select(TradeInvoiceOutcome)
            .where(TradeInvoiceOutcome.invoice_id == invoice_id)
            .order_by(TradeInvoiceOutcome.created_at, TradeInvoiceOutcome.id)
        )
        return list(rows)

    # ── Internals ────────────────────────────────────────────────────────────

    async def _record_trade_history(
        self,
        relationship: TradeRelationship | None,
        *,
        event_type: str,
        to_value: str,
        actor_id: str | None,
        deal_id: uuid.UUID | None = None,
        from_value: str | None = None,
        reason: str | None = None,
        details: dict | None = None,
    ) -> None:
        """One ``trade`` history row, on the **seller's** timeline.

        The seller's, because that is where a deal's rows go and the two belong to one
        story. The buyer sees it through the read-side union task 2.7 added for deals
        (``include_deals_as_buyer``) when the row carries a ``deal_id``; a past-trade
        row has none, and surfacing it on the buyer's timeline is task 3.20's
        question, not this one's.
        """
        if relationship is None:  # pragma: no cover - the FK makes this unreachable
            return
        await self._history.record(
            relationship.seller_company_id,
            dimension=HISTORY_DIMENSION_TRADE,
            to_value=to_value,
            from_value=from_value,
            actor_id=actor_id,
            source="trade_history_service",
            deal_id=deal_id,
            event_type=event_type,
            reason=reason,
            details={"relationship_id": str(relationship.id), **(details or {})},
        )


__all__ = [
    "HISTORY_DIMENSION_TRADE",
    "SOURCE_BACKFILL",
    "SOURCE_DEAL_BUYER_RECORDED",
    "SOURCE_MANUAL",
    "TradeHistoryService",
]
