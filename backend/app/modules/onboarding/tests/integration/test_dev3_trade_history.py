"""Trade relationships, invoices and outcome chains — tasks 3.18 and 3.19
(**owner: Developer 3**, plan P5-1, P5-2, decision IQ-4).

The claims worth testing:

* **``get_or_create_relationship`` is safe under concurrency.** Task 3.18's own
  acceptance criterion: two deals recording the same new pair at the same moment must
  produce one relationship. A check-then-insert implementation passes every
  single-threaded test and is wrong, so this runs two real sessions at once.
* **An invoice's identity is frozen**, by trigger. Direct SQL, because the service
  simply never tries — which is exactly why the database has to.
* **Outcomes are append-only and the chain is a line.** ``UPDATE``/``DELETE`` refused
  in raw SQL; superseding anything but the head refused by the service; and the
  partial unique index refused in raw SQL, because that is what stops two people each
  correcting the same outcome.
* **Currency is stored and never converted** (IQ-4): what goes in comes out, and
  nothing in the model can hold a rate.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from decimal import Decimal

import psycopg2
import psycopg2.errors
import pytest
from sqlalchemy import func, select

from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.application.trade_history_service import (
    HISTORY_DIMENSION_TRADE,
    SOURCE_DEAL_BUYER_RECORDED,
    TradeHistoryService,
)
from app.modules.onboarding.domain.entities.exporter_enums import ExporterSource
from app.modules.onboarding.domain.entities.trade_enums import (
    TradePaymentStatus,
    TradeProofStatus,
)
from app.modules.onboarding.domain.entities.trade_invoice import (
    TradeInvoice,
    TradeInvoiceOutcome,
)
from app.modules.onboarding.domain.entities.trade_relationship import TradeRelationship
from app.modules.onboarding.exceptions import (
    ExporterProfileNotFoundError,
    TradeInvoiceNotFoundError,
    TradeOutcomeStaleError,
    TradeRelationshipIsSelfError,
    TradeRelationshipNotFoundError,
)
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio


def _connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


async def _company(label: str) -> uuid.UUID:
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id,
            source=ExporterSource.SALES,
            name=f"{label} {uuid.uuid4().hex[:8]}",
            country="IN",
        )
    return customer_id


async def _pair() -> tuple[uuid.UUID, uuid.UUID]:
    return await _company("Seller"), await _company("Buyer")


async def _relationship() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    seller, buyer = await _pair()
    async with db_services.AsyncSessionLocal() as db:
        relationship, _created = await TradeHistoryService(db).get_or_create_relationship(
            seller_company_id=seller, buyer_company_id=buyer, actor_id="rm-1"
        )
        relationship_id = relationship.id
        # The service leaves the transaction to its caller (it is normally part of
        # recording a deal's buyer), so the test commits it.
        await db.commit()
    return relationship_id, seller, buyer


async def _invoice(relationship_id: uuid.UUID, **overrides) -> uuid.UUID:
    fields = {
        "invoice_number": f"INV-{uuid.uuid4().hex[:8].upper()}",
        "invoice_date": date(2026, 3, 1),
        "amount": Decimal("1250.00"),
        "currency": "USD",
        **overrides,
    }
    async with db_services.AsyncSessionLocal() as db:
        invoice = await TradeHistoryService(db).record_invoice(
            relationship_id, actor_id="rm-1", **fields
        )
        return invoice.id


# ── Relationships (task 3.18) ─────────────────────────────────────────────────


async def test_a_relationship_is_created_once_and_found_again():
    seller, buyer = await _pair()
    async with db_services.AsyncSessionLocal() as db:
        first, created_first = await TradeHistoryService(db).get_or_create_relationship(
            seller_company_id=seller,
            buyer_company_id=buyer,
            actor_id="rm-1",
            source=SOURCE_DEAL_BUYER_RECORDED,
        )
        first_id = first.id
        await db.commit()
    assert created_first is True

    async with db_services.AsyncSessionLocal() as db:
        again, created_again = await TradeHistoryService(db).get_or_create_relationship(
            seller_company_id=seller, buyer_company_id=buyer, actor_id="rm-2"
        )
    assert again.id == first_id
    assert created_again is False
    # The original provenance survives: it is not overwritten by the second caller.
    assert again.source == SOURCE_DEAL_BUYER_RECORDED
    assert again.created_by == "rm-1"


async def test_the_pair_is_ordered_so_both_directions_can_exist():
    """A selling to B is a different relationship from B selling to A — different
    invoices, different risk — and a company really can be on both sides with the same
    counterparty."""
    first, second = await _pair()
    async with db_services.AsyncSessionLocal() as db:
        service = TradeHistoryService(db)
        forward, _c = await service.get_or_create_relationship(
            seller_company_id=first, buyer_company_id=second, actor_id="rm-1"
        )
        backward, _c = await service.get_or_create_relationship(
            seller_company_id=second, buyer_company_id=first, actor_id="rm-1"
        )
        forward_id, backward_id = forward.id, backward.id
        await db.commit()
    assert forward_id != backward_id


async def test_two_concurrent_callers_create_one_relationship():
    """Task 3.18's acceptance criterion, and the reason the implementation inserts and
    handles the conflict rather than checking first: a check-then-insert passes every
    single-threaded test and still produces two rows here."""
    seller, buyer = await _pair()

    async def create() -> uuid.UUID:
        async with db_services.AsyncSessionLocal() as db:
            relationship, _created = await TradeHistoryService(db).get_or_create_relationship(
                seller_company_id=seller, buyer_company_id=buyer, actor_id="rm-1"
            )
            await db.commit()
            return relationship.id

    ids = await asyncio.gather(*(create() for _ in range(4)))
    assert len(set(ids)) == 1

    async with db_services.AsyncSessionLocal() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(TradeRelationship)
            .where(
                TradeRelationship.seller_company_id == seller,
                TradeRelationship.buyer_company_id == buyer,
            )
        )
    assert count == 1


async def test_losing_the_race_does_not_poison_the_callers_transaction():
    """This is usually called inside a larger unit of work — recording a deal's buyer —
    and that work must survive losing the race. The insert is in a savepoint for
    exactly this."""
    seller, buyer = await _pair()
    async with db_services.AsyncSessionLocal() as db:
        await TradeHistoryService(db).get_or_create_relationship(
            seller_company_id=seller, buyer_company_id=buyer, actor_id="rm-1"
        )
        await db.commit()

    async with db_services.AsyncSessionLocal() as db:
        service = TradeHistoryService(db)
        relationship, created = await service.get_or_create_relationship(
            seller_company_id=seller, buyer_company_id=buyer, actor_id="rm-2"
        )
        assert created is False
        # The session is still usable, which is the point.
        invoice = await service.record_invoice(
            relationship.id,
            invoice_number=f"INV-{uuid.uuid4().hex[:8].upper()}",
            invoice_date=date(2026, 4, 1),
            amount=Decimal("10.00"),
            currency="EUR",
            actor_id="rm-2",
        )
    assert invoice.id is not None


async def test_a_company_cannot_trade_with_itself():
    company = await _company("Solo")
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(TradeRelationshipIsSelfError):
            await TradeHistoryService(db).get_or_create_relationship(
                seller_company_id=company, buyer_company_id=company, actor_id="rm-1"
            )


async def test_the_database_refuses_a_self_relationship_in_raw_sql():
    """``ck_trade_relationship_not_self``. The backfill (task 3.23) writes these rows
    without going through a deal, so the rule belongs in the database too."""
    company = await _company("Solo SQL")
    connection = _connect()
    try:
        with connection, connection.cursor() as cursor:
            with pytest.raises(psycopg2.errors.CheckViolation):
                cursor.execute(
                    "INSERT INTO onboarding.trade_relationship "
                    "(seller_company_id, buyer_company_id) VALUES (%s, %s)",
                    (str(company), str(company)),
                )
    finally:
        connection.close()


async def test_an_unknown_company_is_refused():
    seller, _buyer = await _pair()
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ExporterProfileNotFoundError):
            await TradeHistoryService(db).get_or_create_relationship(
                seller_company_id=seller, buyer_company_id=uuid.uuid4(), actor_id="rm-1"
            )


async def test_the_two_read_directions_are_separate_lists():
    seller, buyer = await _pair()
    async with db_services.AsyncSessionLocal() as db:
        relationship, _c = await TradeHistoryService(db).get_or_create_relationship(
            seller_company_id=seller, buyer_company_id=buyer, actor_id="rm-1"
        )
        relationship_id = relationship.id
        await db.commit()

    async with db_services.AsyncSessionLocal() as db:
        service = TradeHistoryService(db)
        sells = await service.list_relationships(seller)
        buys = await service.list_relationships(seller, as_buyer=True)
    assert [r.id for r in sells] == [relationship_id]
    assert buys == []


# ── Invoices (task 3.19) ──────────────────────────────────────────────────────


async def test_recording_an_invoice_stores_it_and_writes_trade_history():
    relationship_id, seller, _buyer = await _relationship()
    async with db_services.AsyncSessionLocal() as db:
        invoice = await TradeHistoryService(db).record_invoice(
            relationship_id,
            invoice_number="INV-2026-001",
            invoice_date=date(2026, 3, 15),
            amount=Decimal("45250.75"),
            currency="aed",  # upper-cased on the way in
            actor_id="rm-1",
        )
    assert invoice.currency == "AED"
    assert invoice.amount == Decimal("45250.75")
    assert invoice.deal_id is None  # past trade

    async with db_services.AsyncSessionLocal() as db:
        rows, _total = await HistoryService(db).list_for_company(
            seller, dimension=HISTORY_DIMENSION_TRADE, limit=10
        )
    [row] = list(rows)
    assert row.event_type == "trade_invoice_recorded"
    assert row.event_metadata["currency"] == "AED"
    assert row.event_metadata["amount"] == "45250.75"


async def test_an_invoice_keeps_its_currency_and_nothing_converts_it():
    """Decision IQ-4: the amount and code that go in are what come out. There is no
    rate column and no reporting currency anywhere in this model, which is the
    structural half of the decision."""
    relationship_id, _seller, _buyer = await _relationship()
    async with db_services.AsyncSessionLocal() as db:
        invoice = await TradeHistoryService(db).record_invoice(
            relationship_id,
            invoice_number=f"INV-{uuid.uuid4().hex[:8].upper()}",
            invoice_date=date(2026, 2, 1),
            amount=Decimal("1000.00"),
            currency="INR",
            actor_id="rm-1",
        )
        invoice_id = invoice.id

    async with db_services.AsyncSessionLocal() as db:
        stored = await db.scalar(select(TradeInvoice).where(TradeInvoice.id == invoice_id))
    assert (stored.amount, stored.currency) == (Decimal("1000.00"), "INR")
    # Nothing in the model can hold a converted figure.
    assert not any(
        "converted" in c.name or c.name in {"rate", "fx_rate", "reporting_currency"}
        for c in TradeInvoice.__table__.columns
    )


@pytest.mark.parametrize("currency", ["US", "USDD", "12A", "usd£"])
async def test_a_malformed_currency_is_refused(currency: str):
    relationship_id, _seller, _buyer = await _relationship()
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError, match="ISO 4217"):
            await TradeHistoryService(db).record_invoice(
                relationship_id,
                invoice_number=f"INV-{uuid.uuid4().hex[:8].upper()}",
                invoice_date=date(2026, 2, 1),
                amount=Decimal("1.00"),
                currency=currency,
                actor_id="rm-1",
            )


async def test_a_non_positive_amount_is_refused():
    relationship_id, _seller, _buyer = await _relationship()
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError, match="positive"):
            await TradeHistoryService(db).record_invoice(
                relationship_id,
                invoice_number=f"INV-{uuid.uuid4().hex[:8].upper()}",
                invoice_date=date(2026, 2, 1),
                amount=Decimal("0.00"),
                currency="USD",
                actor_id="rm-1",
            )


async def test_one_invoice_number_per_relationship():
    relationship_id, _seller, _buyer = await _relationship()
    await _invoice(relationship_id, invoice_number="INV-DUP")
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError, match="already recorded"):
            await TradeHistoryService(db).record_invoice(
                relationship_id,
                invoice_number="INV-DUP",
                invoice_date=date(2026, 5, 1),
                amount=Decimal("2.00"),
                currency="USD",
                actor_id="rm-1",
            )


async def test_the_same_number_on_another_relationship_is_a_different_invoice():
    """Not globally unique: two exporters may both number an invoice "001"."""
    first_relationship, _s, _b = await _relationship()
    second_relationship, _s, _b = await _relationship()
    await _invoice(first_relationship, invoice_number="001")
    await _invoice(second_relationship, invoice_number="001")


async def test_an_unknown_relationship_is_a_404():
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(TradeRelationshipNotFoundError):
            await TradeHistoryService(db).record_invoice(
                uuid.uuid4(),
                invoice_number="INV-X",
                invoice_date=date(2026, 1, 1),
                amount=Decimal("1.00"),
                currency="USD",
                actor_id="rm-1",
            )


async def test_an_invoices_identity_is_frozen_in_raw_sql():
    """``trg_trade_invoice_identity_immutability``. The service never tries to edit
    one — which is exactly why the database has to refuse it: a backfill, a script or
    a future careless UPDATE would otherwise rewrite evidence."""
    relationship_id, _seller, _buyer = await _relationship()
    invoice_id = await _invoice(relationship_id, amount=Decimal("100.00"))

    connection = _connect()
    try:
        for column, value in (
            ("amount", "999.00"),
            ("currency", "EUR"),
            ("invoice_number", "INV-REWRITTEN"),
            ("invoice_date", "2020-01-01"),
        ):
            with connection, connection.cursor() as cursor:
                with pytest.raises(psycopg2.errors.RaiseException) as caught:
                    cursor.execute(
                        f"UPDATE onboarding.trade_invoice SET {column} = %s WHERE id = %s",
                        (value, str(invoice_id)),
                    )
                assert "immutable once set" in str(caught.value)
    finally:
        connection.close()

    async with db_services.AsyncSessionLocal() as db:
        stored = await db.scalar(select(TradeInvoice).where(TradeInvoice.id == invoice_id))
    assert stored.amount == Decimal("100.00")


async def test_a_past_trade_invoice_can_be_tied_to_a_deal_once():
    """``prevent_field_mutation_when_set`` allows ``NULL`` → a value once, which is
    what lets an invoice recorded as past trade later be tied to the deal that
    produced it — and never re-tied."""
    relationship_id, _seller, _buyer = await _relationship()
    invoice_id = await _invoice(relationship_id)
    deal_id, other_deal = uuid.uuid4(), uuid.uuid4()

    connection = _connect()
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE onboarding.trade_invoice SET deal_id = %s WHERE id = %s",
                (str(deal_id), str(invoice_id)),
            )
        with connection, connection.cursor() as cursor:
            with pytest.raises(psycopg2.errors.RaiseException):
                cursor.execute(
                    "UPDATE onboarding.trade_invoice SET deal_id = %s WHERE id = %s",
                    (str(other_deal), str(invoice_id)),
                )
    finally:
        connection.close()


# ── Outcomes: the append-only chain (task 3.19) ───────────────────────────────


async def test_the_first_outcome_needs_no_note_and_later_ones_do():
    relationship_id, _seller, _buyer = await _relationship()
    invoice_id = await _invoice(relationship_id)

    async with db_services.AsyncSessionLocal() as db:
        first = await TradeHistoryService(db).record_outcome(
            invoice_id, payment_status=TradePaymentStatus.UNKNOWN, actor_id="rm-1"
        )
        first_id = first.id
    assert first.proof_status is TradeProofStatus.CLAIMED
    assert first.supersedes_outcome_id is None

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError, match="note"):
            await TradeHistoryService(db).record_outcome(
                invoice_id,
                payment_status=TradePaymentStatus.PAID,
                supersedes_outcome_id=first_id,
                actor_id="rm-1",
            )

    async with db_services.AsyncSessionLocal() as db:
        second = await TradeHistoryService(db).record_outcome(
            invoice_id,
            payment_status=TradePaymentStatus.PAID,
            proof_status=TradeProofStatus.PROVEN,
            evidence_note="Bank advice received",
            supersedes_outcome_id=first_id,
            actor_id="rm-1",
        )
    assert second.supersedes_outcome_id == first_id

    # The chain is the record: both beliefs survive, and the head is the current one.
    async with db_services.AsyncSessionLocal() as db:
        service = TradeHistoryService(db)
        chain = await service.list_outcomes(invoice_id)
        head = await service.current_outcome(invoice_id)
    assert [o.payment_status for o in chain] == [
        TradePaymentStatus.UNKNOWN,
        TradePaymentStatus.PAID,
    ]
    assert head.id == second.id


async def test_superseding_anything_but_the_head_is_refused():
    """What stops two people each correcting the same outcome without seeing the
    other's — the chain stays a line rather than becoming a tree."""
    relationship_id, _seller, _buyer = await _relationship()
    invoice_id = await _invoice(relationship_id)

    async with db_services.AsyncSessionLocal() as db:
        service = TradeHistoryService(db)
        first = await service.record_outcome(
            invoice_id, payment_status=TradePaymentStatus.UNPAID, actor_id="rm-1"
        )
        first_id = first.id
    async with db_services.AsyncSessionLocal() as db:
        await TradeHistoryService(db).record_outcome(
            invoice_id,
            payment_status=TradePaymentStatus.PARTIAL,
            amount_paid=Decimal("500.00"),
            evidence_note="Half received",
            supersedes_outcome_id=first_id,
            actor_id="rm-1",
        )

    # Somebody who only read the first outcome tries to correct it.
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(TradeOutcomeStaleError) as caught:
            await TradeHistoryService(db).record_outcome(
                invoice_id,
                payment_status=TradePaymentStatus.PAID,
                evidence_note="Paid in full",
                supersedes_outcome_id=first_id,
                actor_id="rm-2",
            )
    assert caught.value.status_code == 409


async def test_the_first_outcome_may_not_claim_to_supersede_and_a_later_one_must():
    relationship_id, _seller, _buyer = await _relationship()
    invoice_id = await _invoice(relationship_id)

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(TradeOutcomeStaleError):
            await TradeHistoryService(db).record_outcome(
                invoice_id,
                payment_status=TradePaymentStatus.PAID,
                supersedes_outcome_id=uuid.uuid4(),
                actor_id="rm-1",
            )

    async with db_services.AsyncSessionLocal() as db:
        await TradeHistoryService(db).record_outcome(
            invoice_id, payment_status=TradePaymentStatus.UNKNOWN, actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(TradeOutcomeStaleError):
            await TradeHistoryService(db).record_outcome(
                invoice_id, payment_status=TradePaymentStatus.PAID, actor_id="rm-1"
            )


async def test_a_partial_outcome_must_say_how_much_was_paid():
    relationship_id, _seller, _buyer = await _relationship()
    invoice_id = await _invoice(relationship_id)
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError, match="how much"):
            await TradeHistoryService(db).record_outcome(
                invoice_id, payment_status=TradePaymentStatus.PARTIAL, actor_id="rm-1"
            )


async def test_the_database_refuses_a_partial_outcome_with_no_amount_in_raw_sql():
    """``ck_trade_invoice_outcome_partial_amount``."""
    relationship_id, _seller, _buyer = await _relationship()
    invoice_id = await _invoice(relationship_id)
    connection = _connect()
    try:
        with connection, connection.cursor() as cursor:
            with pytest.raises(psycopg2.errors.CheckViolation):
                cursor.execute(
                    "INSERT INTO onboarding.trade_invoice_outcome "
                    "(invoice_id, payment_status) VALUES (%s, 'PARTIAL')",
                    (str(invoice_id),),
                )
    finally:
        connection.close()


async def test_outcomes_are_append_only_in_raw_sql():
    """``public.prevent_mutation()``, the function every append-only table in this
    schema uses. A correction is a new row; nothing is edited and nothing is
    deleted."""
    relationship_id, _seller, _buyer = await _relationship()
    invoice_id = await _invoice(relationship_id)
    async with db_services.AsyncSessionLocal() as db:
        outcome = await TradeHistoryService(db).record_outcome(
            invoice_id, payment_status=TradePaymentStatus.UNPAID, actor_id="rm-1"
        )
        outcome_id = outcome.id

    connection = _connect()
    try:
        with connection, connection.cursor() as cursor:
            with pytest.raises(psycopg2.errors.RaiseException):
                cursor.execute(
                    "UPDATE onboarding.trade_invoice_outcome SET payment_status = 'PAID' "
                    "WHERE id = %s",
                    (str(outcome_id),),
                )
        with connection, connection.cursor() as cursor:
            with pytest.raises(psycopg2.errors.RaiseException):
                cursor.execute(
                    "DELETE FROM onboarding.trade_invoice_outcome WHERE id = %s",
                    (str(outcome_id),),
                )
    finally:
        connection.close()


async def test_two_heads_are_impossible_in_raw_sql():
    """``uq_trade_invoice_outcome_first``, partial on ``supersedes_outcome_id IS
    NULL``. Without it two callers could each write a first outcome and the invoice
    would have two current beliefs."""
    relationship_id, _seller, _buyer = await _relationship()
    invoice_id = await _invoice(relationship_id)
    async with db_services.AsyncSessionLocal() as db:
        await TradeHistoryService(db).record_outcome(
            invoice_id, payment_status=TradePaymentStatus.UNPAID, actor_id="rm-1"
        )

    connection = _connect()
    try:
        with connection, connection.cursor() as cursor:
            with pytest.raises(psycopg2.errors.UniqueViolation):
                cursor.execute(
                    "INSERT INTO onboarding.trade_invoice_outcome "
                    "(invoice_id, payment_status) VALUES (%s, 'PAID')",
                    (str(invoice_id),),
                )
    finally:
        connection.close()


async def test_one_row_may_supersede_each_outcome_in_raw_sql():
    """``uq_trade_invoice_outcome_supersedes``: the chain is a line. Two rows claiming
    to supersede the same outcome would be a fork with no way to say which won."""
    relationship_id, _seller, _buyer = await _relationship()
    invoice_id = await _invoice(relationship_id)
    async with db_services.AsyncSessionLocal() as db:
        first = await TradeHistoryService(db).record_outcome(
            invoice_id, payment_status=TradePaymentStatus.UNPAID, actor_id="rm-1"
        )
        first_id = first.id
    async with db_services.AsyncSessionLocal() as db:
        await TradeHistoryService(db).record_outcome(
            invoice_id,
            payment_status=TradePaymentStatus.PAID,
            evidence_note="Paid",
            supersedes_outcome_id=first_id,
            actor_id="rm-1",
        )

    connection = _connect()
    try:
        with connection, connection.cursor() as cursor:
            with pytest.raises(psycopg2.errors.UniqueViolation):
                cursor.execute(
                    "INSERT INTO onboarding.trade_invoice_outcome "
                    "(invoice_id, payment_status, evidence_note, supersedes_outcome_id) "
                    "VALUES (%s, 'DISPUTED', 'also correcting', %s)",
                    (str(invoice_id), str(first_id)),
                )
    finally:
        connection.close()


async def test_evidence_references_are_checked_like_verification_evidence():
    relationship_id, _seller, _buyer = await _relationship()
    invoice_id = await _invoice(relationship_id)

    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError, match="http"):
            await TradeHistoryService(db).record_outcome(
                invoice_id,
                payment_status=TradePaymentStatus.PAID,
                proof_status=TradeProofStatus.PROVEN,
                evidence_refs=[{"type": "url", "ref": "javascript:alert(1)"}],
                actor_id="rm-1",
            )

    async with db_services.AsyncSessionLocal() as db:
        outcome = await TradeHistoryService(db).record_outcome(
            invoice_id,
            payment_status=TradePaymentStatus.PAID,
            proof_status=TradeProofStatus.PROVEN,
            evidence_refs=[{"type": "url", "ref": "https://bank.example/advice/1"}],
            actor_id="rm-1",
        )
    assert outcome.evidence_refs == [
        {"type": "url", "ref": "https://bank.example/advice/1"}
    ]


async def test_an_unknown_invoice_is_a_404():
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(TradeInvoiceNotFoundError):
            await TradeHistoryService(db).record_outcome(
                uuid.uuid4(), payment_status=TradePaymentStatus.PAID, actor_id="rm-1"
            )


async def test_an_outcome_writes_trade_history_on_the_sellers_timeline():
    relationship_id, seller, _buyer = await _relationship()
    invoice_id = await _invoice(relationship_id)
    async with db_services.AsyncSessionLocal() as db:
        await TradeHistoryService(db).record_outcome(
            invoice_id,
            payment_status=TradePaymentStatus.PAID,
            proof_status=TradeProofStatus.PROVEN,
            evidence_note="Bank advice on file",
            actor_id="rm-1",
        )
    async with db_services.AsyncSessionLocal() as db:
        rows, _total = await HistoryService(db).list_for_company(
            seller, dimension=HISTORY_DIMENSION_TRADE, limit=10
        )
    [outcome_row] = [r for r in rows if r.event_type == "trade_outcome_recorded"]
    assert outcome_row.to_status == "PAID"
    assert outcome_row.event_metadata["proof_status"] == "PROVEN"
    assert outcome_row.reason == "Bank advice on file"


async def test_proof_and_payment_are_independent():
    """"They paid" and "we can prove they paid" are different claims. A trade history
    that could not tell them apart would be worthless as evidence."""
    relationship_id, _seller, _buyer = await _relationship()
    claimed_invoice = await _invoice(relationship_id)
    async with db_services.AsyncSessionLocal() as db:
        claimed = await TradeHistoryService(db).record_outcome(
            claimed_invoice,
            payment_status=TradePaymentStatus.PAID,
            proof_status=TradeProofStatus.CLAIMED,
            evidence_note="The exporter says so",
            actor_id="rm-1",
        )
    assert claimed.payment_status is TradePaymentStatus.PAID
    assert claimed.proof_status is TradeProofStatus.CLAIMED

    async with db_services.AsyncSessionLocal() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(TradeInvoiceOutcome)
            .where(TradeInvoiceOutcome.invoice_id == claimed_invoice)
        )
    assert count == 1


async def test_a_three_link_chain_still_has_one_head():
    """`_head_outcome` finds the row nothing supersedes, not the newest by timestamp.

    Worth a longer chain than the two-link tests above: two rows written in one
    transaction share a `created_at`, so "newest" is not reliably "live", and a
    head query that sorted by time would start returning the wrong belief exactly
    when corrections came in quick succession.
    """
    relationship_id, _seller, _buyer = await _relationship()
    invoice_id = await _invoice(relationship_id)

    async with db_services.AsyncSessionLocal() as db:
        first = await TradeHistoryService(db).record_outcome(
            invoice_id, payment_status=TradePaymentStatus.UNKNOWN, actor_id="rm-1"
        )
        first_id = first.id
    async with db_services.AsyncSessionLocal() as db:
        second = await TradeHistoryService(db).record_outcome(
            invoice_id,
            payment_status=TradePaymentStatus.PARTIAL,
            amount_paid=Decimal("600.00"),
            evidence_note="Part payment received",
            supersedes_outcome_id=first_id,
            actor_id="rm-1",
        )
        second_id = second.id
    async with db_services.AsyncSessionLocal() as db:
        third = await TradeHistoryService(db).record_outcome(
            invoice_id,
            payment_status=TradePaymentStatus.PAID,
            proof_status=TradeProofStatus.PROVEN,
            evidence_note="Balance received, bank advice on file",
            supersedes_outcome_id=second_id,
            actor_id="rm-2",
        )
        third_id = third.id

    async with db_services.AsyncSessionLocal() as db:
        service = TradeHistoryService(db)
        head = await service.current_outcome(invoice_id)
        chain = await service.list_outcomes(invoice_id)
    assert head.id == third_id
    assert [o.id for o in chain] == [first_id, second_id, third_id]
    # Every belief survives, in order, with the amount each recorded.
    assert [o.payment_status for o in chain] == [
        TradePaymentStatus.UNKNOWN,
        TradePaymentStatus.PARTIAL,
        TradePaymentStatus.PAID,
    ]
    assert chain[1].amount_paid == Decimal("600.00")

    # And only the head may now be superseded.
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(TradeOutcomeStaleError):
            await TradeHistoryService(db).record_outcome(
                invoice_id,
                payment_status=TradePaymentStatus.DISPUTED,
                evidence_note="The buyer disputes it",
                supersedes_outcome_id=second_id,
                actor_id="rm-3",
            )
