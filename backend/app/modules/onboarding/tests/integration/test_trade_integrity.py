"""Trade history's transaction and concurrency rules (contract ``trade-history.md`` §5).

* **All or nothing** — recording a deal's payment outcome is all or nothing. It used to commit
  the invoice and only then validate the outcome, so a refused request left an invoice
  behind and the corrected retry was refused because of it.
* **One outcome at a time** — two outcomes for one invoice at once are decided one after the other. The
  loser gets the documented 409 ``TRADE_OUTCOME_STALE``, never an ``IntegrityError``.
* **One first outcome per deal** — two first outcomes on one deal cannot both create its invoice.
* **Real deals** — the database refuses an invoice naming a deal that does not exist.

The concurrency tests do what ``test_handover_compliance.py`` does for the
handover: pause the first writer at a known point, start the second, and show it
waits — so they fail deterministically without the lock rather than by luck.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from decimal import Decimal

import psycopg2
import psycopg2.errors
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.modules.onboarding.application.trade_history_service import TradeHistoryService
from app.modules.onboarding.domain.entities.exporter_lifecycle_history import (
    ExporterLifecycleHistory,
)
from app.modules.onboarding.domain.entities.trade_enums import TradePaymentStatus
from app.modules.onboarding.domain.entities.trade_invoice import DealInvoiceDraft, TradeInvoice
from app.modules.onboarding.exceptions import (
    TradeInvoiceAlreadyRecordedError,
    TradeOutcomeStaleError,
)
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.modules.onboarding.tests.fixtures.deals import make_deal_with_buyer_company
from app.modules.onboarding.tests.integration.test_trade_routes import (
    _handed_over_deal_with_a_buyer_company,
)
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"


def _draft() -> DealInvoiceDraft:
    return DealInvoiceDraft(
        invoice_number=f"INV-{uuid.uuid4().hex[:8].upper()}",
        invoice_date=date(2026, 4, 1),
        amount=Decimal("18400.00"),
        currency="USD",
    )


def _invoice_fields() -> dict:
    return {
        "invoice_number": f"INV-{uuid.uuid4().hex[:8].upper()}",
        "invoice_date": "2026-04-01",
        "amount": "18400.00",
        "currency": "USD",
    }


async def _invoices_of(deal_id: uuid.UUID) -> list[TradeInvoice]:
    async with db_services.AsyncSessionLocal() as db:
        return list(await db.scalars(select(TradeInvoice).where(TradeInvoice.deal_id == deal_id)))


async def _trade_rows_of(deal_id: uuid.UUID) -> int:
    async with db_services.AsyncSessionLocal() as db:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(ExporterLifecycleHistory)
                .where(
                    ExporterLifecycleHistory.deal_id == deal_id,
                    ExporterLifecycleHistory.dimension == "trade",
                )
            )
        )


async def _relationship_invoice() -> uuid.UUID:
    """An invoice with no outcome yet, on a real deal between a real pair."""
    deal_id, seller, buyer = await make_deal_with_buyer_company()
    async with db_services.AsyncSessionLocal() as db:
        service = TradeHistoryService(db)
        relationship = await service.relationship_for_pair(
            seller_company_id=seller, buyer_company_id=buyer
        )
        invoice = await service.record_invoice(
            relationship.id,
            invoice_number=f"INV-{uuid.uuid4().hex[:8].upper()}",
            invoice_date=date(2026, 4, 1),
            amount=Decimal("100.00"),
            currency="USD",
            deal_id=deal_id,
            actor_id="rm-1",
        )
    return invoice.id


# ── All or nothing ────────────────────────────────────────────────────────────


async def test_a_refused_outcome_leaves_no_invoice_and_the_corrected_retry_succeeds(
    client: AsyncClient,
):
    """The confirmed reproduction: PARTIAL with no amount used to answer 422 *after*
    writing the invoice, and the retry was then refused with
    TRADE_INVOICE_ALREADY_RECORDED."""
    deal_id, _seller, _buyer = await _handed_over_deal_with_a_buyer_company()
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    invoice = _invoice_fields()

    refused = await client.post(
        f"{BASE}/deals/{deal_id}/payment-outcome",
        json={"payment_status": "PARTIAL", **invoice},
        headers=auth_header(token),
    )
    assert refused.status_code == 422, refused.text
    assert await _invoices_of(deal_id) == []
    assert await _trade_rows_of(deal_id) == 0

    retried = await client.post(
        f"{BASE}/deals/{deal_id}/payment-outcome",
        json={"payment_status": "PARTIAL", "amount_paid": "9200.00", **invoice},
        headers=auth_header(token),
    )
    assert retried.status_code == 201, retried.text
    assert retried.json()["invoice_created"] is True
    assert len(await _invoices_of(deal_id)) == 1


async def test_a_failure_after_the_invoice_is_written_rolls_the_invoice_back():
    """A refusal that can only be known once the invoice exists — superseding an
    outcome on an invoice that has none — still leaves nothing: one transaction."""
    deal_id, _seller, _buyer = await _handed_over_deal_with_a_buyer_company()
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(TradeOutcomeStaleError):
            await TradeHistoryService(db).record_outcome_for_deal(
                deal_id,
                payment_status=TradePaymentStatus.PAID,
                supersedes_outcome_id=uuid.uuid4(),
                evidence_note="Correcting nothing",
                invoice=_draft(),
                actor_id="rm-1",
            )
    assert await _invoices_of(deal_id) == []
    assert await _trade_rows_of(deal_id) == 0


async def test_malformed_evidence_is_refused_before_anything_is_written():
    deal_id, _seller, _buyer = await _handed_over_deal_with_a_buyer_company()
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValidationError):
            await TradeHistoryService(db).record_outcome_for_deal(
                deal_id,
                payment_status=TradePaymentStatus.PAID,
                evidence_refs=[{"type": "url", "ref": "javascript:alert(1)"}],
                invoice=_draft(),
                actor_id="rm-1",
            )
    assert await _invoices_of(deal_id) == []


# ── One outcome at a time per invoice ─────────────────────────────────────────


async def _race_two_outcomes(monkeypatch, invoice_id, *, supersedes=None, note=None):
    """Run two ``record_outcome`` calls on ``invoice_id``: the first paused just after
    it has read the chain's head, the second started while it is paused. Returns the
    second's task, which must not finish while the first holds the invoice, and the
    first's result."""
    read_head = asyncio.Event()
    release = asyncio.Event()
    original = TradeHistoryService._head_outcome
    first_call = {"pending": True}

    async def paused(self, invoice_id):
        head = await original(self, invoice_id)
        if first_call.pop("pending", False):
            read_head.set()
            await release.wait()
        return head

    monkeypatch.setattr(TradeHistoryService, "_head_outcome", paused)

    async def record(status):
        async with db_services.AsyncSessionLocal() as db:
            return await TradeHistoryService(db).record_outcome(
                invoice_id,
                payment_status=status,
                supersedes_outcome_id=supersedes,
                evidence_note=note,
                actor_id="rm-1",
            )

    first = asyncio.create_task(record(TradePaymentStatus.PAID))
    await asyncio.wait_for(read_head.wait(), timeout=10)
    second = asyncio.create_task(record(TradePaymentStatus.UNPAID))
    done, _ = await asyncio.wait({second}, timeout=2)
    assert not done, "a second outcome ran while the first held the invoice"
    release.set()
    return await asyncio.wait_for(first, timeout=10), second


async def test_two_first_outcomes_at_once_give_one_outcome_and_one_stale(monkeypatch):
    invoice_id = await _relationship_invoice()
    winner, second = await _race_two_outcomes(monkeypatch, invoice_id)
    with pytest.raises(TradeOutcomeStaleError):
        await asyncio.wait_for(second, timeout=10)

    async with db_services.AsyncSessionLocal() as db:
        chain = await TradeHistoryService(db).list_outcomes(invoice_id)
    assert [o.id for o in chain] == [winner.id]


async def test_two_corrections_of_one_head_at_once_give_one_correction(monkeypatch):
    invoice_id = await _relationship_invoice()
    async with db_services.AsyncSessionLocal() as db:
        head = await TradeHistoryService(db).record_outcome(
            invoice_id, payment_status=TradePaymentStatus.UNKNOWN, actor_id="rm-1"
        )

    winner, second = await _race_two_outcomes(
        monkeypatch, invoice_id, supersedes=head.id, note="Bank advice arrived"
    )
    with pytest.raises(TradeOutcomeStaleError):
        await asyncio.wait_for(second, timeout=10)

    async with db_services.AsyncSessionLocal() as db:
        current = await TradeHistoryService(db).current_outcome(invoice_id)
    assert current.id == winner.id
    assert current.supersedes_outcome_id == head.id


async def test_simultaneous_requests_answer_201_and_409_never_500(client: AsyncClient):
    """Through the route, with no pausing: whichever wins, the other is told the
    documented TRADE_OUTCOME_STALE."""
    invoice_id = await _relationship_invoice()
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)

    async def post(status):
        return await client.post(
            f"{BASE}/trade-invoices/{invoice_id}/outcomes",
            json={"payment_status": status},
            headers=auth_header(token),
        )

    responses = await asyncio.gather(post("PAID"), post("UNPAID"), post("DISPUTED"))
    codes = sorted(r.status_code for r in responses)
    assert codes == [201, 409, 409], [r.text for r in responses]
    for response in responses:
        if response.status_code == 409:
            assert response.json()["error_code"] == "TRADE_OUTCOME_STALE"


# ── One first outcome per deal at a time ──────────────────────────────────────


async def test_two_first_outcomes_on_one_deal_create_one_invoice(monkeypatch):
    """Both name an invoice for a deal that has none. The first is paused while it
    holds the deal; the second waits, then finds the invoice and is told so."""
    deal_id, _seller, _buyer = await _handed_over_deal_with_a_buyer_company()

    started = asyncio.Event()
    release = asyncio.Event()
    original = TradeHistoryService._write_invoice
    first_call = {"pending": True}

    async def paused(self, *args, **kwargs):
        if first_call.pop("pending", False):
            started.set()
            await release.wait()
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(TradeHistoryService, "_write_invoice", paused)

    async def record():
        async with db_services.AsyncSessionLocal() as db:
            return await TradeHistoryService(db).record_outcome_for_deal(
                deal_id,
                payment_status=TradePaymentStatus.PAID,
                invoice=_draft(),
                actor_id="rm-1",
            )

    first = asyncio.create_task(record())
    await asyncio.wait_for(started.wait(), timeout=10)
    second = asyncio.create_task(record())
    done, _ = await asyncio.wait({second}, timeout=2)
    assert not done, "a second request on the deal ran while the first held it"
    release.set()

    invoice, _outcome = await asyncio.wait_for(first, timeout=10)
    with pytest.raises(TradeInvoiceAlreadyRecordedError):
        await asyncio.wait_for(second, timeout=10)
    assert [i.id for i in await _invoices_of(deal_id)] == [invoice.id]


async def test_the_deal_route_answers_about_the_deals_earliest_invoice():
    """No rule limits invoices per deal, so a deal may carry a second invoice recorded on purpose through
    the relationship route. The deal route then picks one deterministically — the
    earliest — rather than whichever row the database returns first."""
    deal_id, seller, buyer = await _handed_over_deal_with_a_buyer_company()
    async with db_services.AsyncSessionLocal() as db:
        first, first_outcome = await TradeHistoryService(db).record_outcome_for_deal(
            deal_id, payment_status=TradePaymentStatus.UNKNOWN, invoice=_draft(), actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        service = TradeHistoryService(db)
        relationship = await service.relationship_for_pair(
            seller_company_id=seller, buyer_company_id=buyer
        )
        await service.record_invoice(
            relationship.id,
            invoice_number=f"SECOND-{uuid.uuid4().hex[:6].upper()}",
            invoice_date=date(2026, 5, 1),
            amount=Decimal("50.00"),
            currency="USD",
            deal_id=deal_id,
            actor_id="rm-1",
        )
    async with db_services.AsyncSessionLocal() as db:
        target, _ = await TradeHistoryService(db).record_outcome_for_deal(
            deal_id,
            payment_status=TradePaymentStatus.PAID,
            supersedes_outcome_id=first_outcome.id,
            evidence_note="Paid in full",
            actor_id="rm-1",
        )
    assert target.id == first.id


# ── The database refuses an invented deal ─────────────────────────────────────


async def test_the_database_refuses_an_invoice_naming_no_deal():
    """Migration 0042's ``fk_trade_invoice_deal``: a writer that skips the service is
    refused too."""
    invoice_id = await _relationship_invoice()
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    connection = psycopg2.connect(url)
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT relationship_id FROM onboarding.trade_invoice WHERE id = %s",
                (str(invoice_id),),
            )
            [relationship_id] = cursor.fetchone()
        with connection, connection.cursor() as cursor:
            with pytest.raises(psycopg2.errors.ForeignKeyViolation):
                cursor.execute(
                    "INSERT INTO onboarding.trade_invoice (id, relationship_id, deal_id, "
                    "invoice_number, invoice_date, amount, currency, source) "
                    "VALUES (%s, %s, %s, %s, '2026-04-01', 10, 'USD', 'manual')",
                    (
                        str(uuid.uuid4()),
                        str(relationship_id),
                        str(uuid.uuid4()),
                        f"RAW-{uuid.uuid4().hex[:6]}",
                    ),
                )
    finally:
        connection.close()


async def test_the_database_refuses_a_company_created_from_no_deal():
    """Migration 0042's ``fk_exporter_profile_created_via_deal``."""
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    connection = psycopg2.connect(url)
    try:
        with connection, connection.cursor() as cursor:
            with pytest.raises(psycopg2.errors.ForeignKeyViolation):
                cursor.execute(
                    "INSERT INTO onboarding.exporter_profile "
                    "(id, customer_id, source, created_via_deal_id) "
                    "VALUES (%s, %s, 'SALES', %s)",
                    (str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())),
                )
    finally:
        connection.close()
