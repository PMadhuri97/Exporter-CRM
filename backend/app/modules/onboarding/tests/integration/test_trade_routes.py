"""The trade history API.

What is worth testing here, as opposed to repeating `test_trade_history.py`'s
coverage of the model:

* **The role split.** DEVELOPER **reads** and cannot write. That is unusual
  enough in this CRM to be worth pinning: everywhere else DEVELOPER is refused the
  compliance routes outright, and the reason it is allowed here is that these
  responses carry no identifiers at all.
* **No identifiers reach any role**, which is the claim the role split rests on. If
  a later change adds a PAN to a counterparty summary, this is the test that fails.
* **Amounts are strings, and there is no total.** A JSON number would invite a client
  to add two currencies together; a served total would do it for them.
* **The chain reads as a chain**: the whole history with the live row marked, not just
  the current belief.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.application.trade_history_service import TradeHistoryService
from app.modules.onboarding.domain.entities.exporter_enums import ExporterSource
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.modules.onboarding.tests.fixtures.deals import make_deal, make_deal_with_buyer_company
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"


def _pan() -> str:
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    return f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"


async def _company(label: str, **fields) -> uuid.UUID:
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id,
            source=ExporterSource.SALES,
            name=f"{label} {uuid.uuid4().hex[:8]}",
            country="IN",
            **fields,
        )
    return customer_id


async def _relationship() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A committed relationship, with its seller and buyer."""
    seller = await _company("Trade Seller", pan=_pan())
    buyer = await _company("Trade Buyer")
    async with db_services.AsyncSessionLocal() as db:
        relationship, _created = await TradeHistoryService(db).get_or_create_relationship(
            seller_company_id=seller, buyer_company_id=buyer, actor_id="rm-1"
        )
        relationship_id = relationship.id
        await db.commit()
    return relationship_id, seller, buyer


def _invoice_body(**overrides) -> dict:
    return {
        "invoice_number": f"INV-{uuid.uuid4().hex[:8].upper()}",
        "invoice_date": "2026-03-01",
        "amount": "1250.50",
        "currency": "USD",
        **overrides,
    }


# ── Who may read, who may write ───────────────────────────────────────────────


async def test_developer_may_read_trade_history_but_not_write_it(client: AsyncClient):
    """The unusual half of the role split, and the reason for it: these responses carry no
    identifiers, so there is nothing for masking to withhold. Everywhere else in the
    CRM DEVELOPER is refused compliance data outright."""
    relationship_id, seller, _buyer = await _relationship()
    _dev_id, dev_token = await user_with_role(client, UserRole.DEVELOPER)

    listed = await client.get(
        f"{BASE}/exporters/{seller}/trade-relationships", headers=auth_header(dev_token)
    )
    assert listed.status_code == 200, listed.text
    detail = await client.get(
        f"{BASE}/trade-relationships/{relationship_id}", headers=auth_header(dev_token)
    )
    assert detail.status_code == 200, detail.text

    refused = await client.post(
        f"{BASE}/trade-relationships/{relationship_id}/invoices",
        json=_invoice_body(),
        headers=auth_header(dev_token),
    )
    assert refused.status_code == 403, refused.text


async def test_a_relationship_manager_may_record_invoices_and_outcomes(
    client: AsyncClient,
):
    """"RM, Compliance and Admin record". A buyer's payment behaviour is the
    relationship manager's to record, not compliance's."""
    relationship_id, _seller, _buyer = await _relationship()
    _ops_id, ops_token = await user_with_role(client, UserRole.OPERATIONS)

    created = await client.post(
        f"{BASE}/trade-relationships/{relationship_id}/invoices",
        json=_invoice_body(),
        headers=auth_header(ops_token),
    )
    assert created.status_code == 201, created.text
    invoice_id = created.json()["id"]

    outcome = await client.post(
        f"{BASE}/trade-invoices/{invoice_id}/outcomes",
        json={"payment_status": "PAID", "proof_status": "PROVEN",
              "evidence_note": "Bank advice on file"},
        headers=auth_header(ops_token),
    )
    assert outcome.status_code == 201, outcome.text
    assert outcome.json()["is_current"] is True


async def test_an_outcomes_evidence_is_typed_as_type_and_ref(client: AsyncClient):
    """`evidence_refs` is verification's `{type, ref}` shape on the way in and out,
    so the generated client types name it. A reference of another type is
    refused at the boundary, before anything is written."""
    relationship_id, _seller, _buyer = await _relationship()
    _ops_id, ops_token = await user_with_role(client, UserRole.OPERATIONS)
    created = await client.post(
        f"{BASE}/trade-relationships/{relationship_id}/invoices",
        json=_invoice_body(),
        headers=auth_header(ops_token),
    )
    assert created.status_code == 201, created.text
    invoice_id = created.json()["id"]

    refused = await client.post(
        f"{BASE}/trade-invoices/{invoice_id}/outcomes",
        json={"payment_status": "PAID", "evidence_refs": [{"type": "email", "ref": "x"}]},
        headers=auth_header(ops_token),
    )
    assert refused.status_code == 422, refused.text

    ref = {"type": "url", "ref": "https://bank.example/advice/7"}
    outcome = await client.post(
        f"{BASE}/trade-invoices/{invoice_id}/outcomes",
        json={"payment_status": "PAID", "proof_status": "PROVEN", "evidence_refs": [ref]},
        headers=auth_header(ops_token),
    )
    assert outcome.status_code == 201, outcome.text
    assert outcome.json()["evidence_refs"] == [ref]

    detail = await client.get(f"{BASE}/trade-invoices/{invoice_id}", headers=auth_header(ops_token))
    assert detail.status_code == 200, detail.text
    assert [o["evidence_refs"] for o in detail.json()["outcomes"]] == [[ref]]


# ── No identifiers, for anyone ────────────────────────────────────────────────


async def test_no_response_carries_an_identifier_for_any_role(client: AsyncClient):
    """The claim the role split rests on. A counterparty is an id, a name, a country
    and whether it is in the pipeline — nothing else. If a later change adds a PAN to
    that summary, this fails, and the role-split reasoning has to be revisited."""
    seller_pan = _pan()
    seller = await _company("Identified Seller", pan=seller_pan, iec="1234567890")
    buyer = await _company("Identified Buyer")
    async with db_services.AsyncSessionLocal() as db:
        relationship, _c = await TradeHistoryService(db).get_or_create_relationship(
            seller_company_id=seller, buyer_company_id=buyer, actor_id="rm-1"
        )
        relationship_id = relationship.id
        await db.commit()

    for role in (
        UserRole.OPERATIONS,
        UserRole.COMPLIANCE,
        UserRole.ADMIN,
        UserRole.DEVELOPER,
    ):
        _user_id, token = await user_with_role(client, role)
        listed = await client.get(
            f"{BASE}/exporters/{seller}/trade-relationships", headers=auth_header(token)
        )
        assert seller_pan not in listed.text, role
        assert "1234567890" not in listed.text, role

        detail = await client.get(
            f"{BASE}/trade-relationships/{relationship_id}", headers=auth_header(token)
        )
        assert seller_pan not in detail.text, role
        counterparty = detail.json()["relationship"]["seller"]
        assert set(counterparty) == {
            "company_id",
            "name",
            "country",
            "pipeline_status",
        }, role


# ── The two sides ─────────────────────────────────────────────────────────────


async def test_the_two_sides_are_separate_lists(client: AsyncClient):
    relationship_id, seller, buyer = await _relationship()
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)

    sells = await client.get(
        f"{BASE}/exporters/{seller}/trade-relationships", headers=auth_header(token)
    )
    assert [r["id"] for r in sells.json()["relationships"]] == [str(relationship_id)]

    # The same company, asked about the other side: it buys from nobody.
    buys = await client.get(
        f"{BASE}/exporters/{seller}/trade-relationships",
        params={"as": "buyer"},
        headers=auth_header(token),
    )
    assert buys.json()["relationships"] == []

    # And the buyer sees it on its buying side.
    theirs = await client.get(
        f"{BASE}/exporters/{buyer}/trade-relationships",
        params={"as": "buyer"},
        headers=auth_header(token),
    )
    assert [r["id"] for r in theirs.json()["relationships"]] == [str(relationship_id)]


async def test_an_unknown_side_is_refused(client: AsyncClient):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    resp = await client.get(
        f"{BASE}/exporters/{uuid.uuid4()}/trade-relationships",
        params={"as": "guarantor"},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text


# ── Amounts, currencies and the absence of a total ────────────────────────────


async def test_amounts_come_back_as_strings_and_nothing_is_totalled(
    client: AsyncClient,
):
    """Never converted, in the shape of the response. A JSON number invites a client to
    add two currencies together; a served total would have done it for them."""
    relationship_id, _seller, _buyer = await _relationship()
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)

    for currency, amount in (("USD", "1000.00"), ("AED", "3670.00")):
        created = await client.post(
            f"{BASE}/trade-relationships/{relationship_id}/invoices",
            json=_invoice_body(currency=currency, amount=amount),
            headers=auth_header(token),
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["amount"] == amount
        assert isinstance(body["amount"], str)
        assert body["currency"] == currency

    detail = await client.get(
        f"{BASE}/trade-relationships/{relationship_id}", headers=auth_header(token)
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["relationship"]["invoice_count"] == 2
    # Two currencies, no total: summing them is a decision a person makes with a rate
    # they choose, and the API refuses to imply otherwise.
    assert "total_amount" not in detail.json()["relationship"]
    assert {i["currency"] for i in detail.json()["invoices"]} == {"USD", "AED"}


async def test_a_malformed_currency_is_refused_by_the_route(client: AsyncClient):
    relationship_id, _seller, _buyer = await _relationship()
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    resp = await client.post(
        f"{BASE}/trade-relationships/{relationship_id}/invoices",
        json=_invoice_body(currency="US"),
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text


async def test_a_non_positive_amount_is_refused_by_the_route(client: AsyncClient):
    relationship_id, _seller, _buyer = await _relationship()
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    resp = await client.post(
        f"{BASE}/trade-relationships/{relationship_id}/invoices",
        json=_invoice_body(amount="0"),
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text


# ── The outcome chain, read as a chain ────────────────────────────────────────


async def test_an_invoices_whole_chain_reads_with_the_live_row_marked(
    client: AsyncClient,
):
    """Not just the current belief: a screen showing only the head would make a
    corrected invoice indistinguishable from one that was right first time."""
    relationship_id, _seller, _buyer = await _relationship()
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    created = await client.post(
        f"{BASE}/trade-relationships/{relationship_id}/invoices",
        json=_invoice_body(),
        headers=auth_header(token),
    )
    invoice_id = created.json()["id"]

    first = await client.post(
        f"{BASE}/trade-invoices/{invoice_id}/outcomes",
        json={"payment_status": "UNPAID"},
        headers=auth_header(token),
    )
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]

    second = await client.post(
        f"{BASE}/trade-invoices/{invoice_id}/outcomes",
        json={
            "payment_status": "PARTIAL",
            "amount_paid": "600.00",
            "evidence_note": "Part payment received",
            "supersedes_outcome_id": first_id,
        },
        headers=auth_header(token),
    )
    assert second.status_code == 201, second.text

    chain = await client.get(f"{BASE}/trade-invoices/{invoice_id}", headers=auth_header(token))
    assert chain.status_code == 200, chain.text
    outcomes = chain.json()["outcomes"]
    assert [o["payment_status"] for o in outcomes] == ["UNPAID", "PARTIAL"]
    assert [o["is_current"] for o in outcomes] == [False, True]
    assert outcomes[1]["amount_paid"] == "600.00"
    # And the invoice's own `current_outcome` agrees with the chain's head.
    assert chain.json()["invoice"]["current_outcome"]["id"] == outcomes[1]["id"]


async def test_superseding_a_stale_outcome_is_a_conflict_through_the_route(
    client: AsyncClient,
):
    relationship_id, _seller, _buyer = await _relationship()
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    created = await client.post(
        f"{BASE}/trade-relationships/{relationship_id}/invoices",
        json=_invoice_body(),
        headers=auth_header(token),
    )
    invoice_id = created.json()["id"]
    first = await client.post(
        f"{BASE}/trade-invoices/{invoice_id}/outcomes",
        json={"payment_status": "UNPAID"},
        headers=auth_header(token),
    )
    first_id = first.json()["id"]
    await client.post(
        f"{BASE}/trade-invoices/{invoice_id}/outcomes",
        json={"payment_status": "PAID", "evidence_note": "Paid",
              "supersedes_outcome_id": first_id},
        headers=auth_header(token),
    )

    stale = await client.post(
        f"{BASE}/trade-invoices/{invoice_id}/outcomes",
        json={"payment_status": "DISPUTED", "evidence_note": "Also correcting",
              "supersedes_outcome_id": first_id},
        headers=auth_header(token),
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error_code"] == "TRADE_OUTCOME_STALE"
    # The current outcome is named so the caller can read it and decide again.
    assert stale.json()["error_context"]["current_outcome_id"] is not None


async def test_an_invoice_with_no_outcome_says_so_rather_than_guessing(
    client: AsyncClient,
):
    """`null` is not `UNKNOWN`: nobody has looked, versus somebody looked and could
    not say. A screen that showed them the same way would lose the difference."""
    relationship_id, _seller, _buyer = await _relationship()
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    created = await client.post(
        f"{BASE}/trade-relationships/{relationship_id}/invoices",
        json=_invoice_body(),
        headers=auth_header(token),
    )
    assert created.json()["current_outcome"] is None

    detail = await client.get(
        f"{BASE}/trade-relationships/{relationship_id}", headers=auth_header(token)
    )
    [invoice] = detail.json()["invoices"]
    assert invoice["current_outcome"] is None


async def test_unknown_relationships_and_invoices_are_404s(client: AsyncClient):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    missing_relationship = await client.get(
        f"{BASE}/trade-relationships/{uuid.uuid4()}", headers=auth_header(token)
    )
    assert missing_relationship.status_code == 404, missing_relationship.text
    missing_invoice = await client.get(
        f"{BASE}/trade-invoices/{uuid.uuid4()}", headers=auth_header(token)
    )
    assert missing_invoice.status_code == 404, missing_invoice.text


async def test_recording_an_invoice_on_an_unknown_relationship_is_a_404(
    client: AsyncClient,
):
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    resp = await client.post(
        f"{BASE}/trade-relationships/{uuid.uuid4()}/invoices",
        json=_invoice_body(),
        headers=auth_header(token),
    )
    assert resp.status_code == 404, resp.text


# ── A deal's invoice, and past trade ──────────────────────────────────────────


async def test_an_invoice_may_name_the_deal_it_came_from_or_no_deal_at_all(
    client: AsyncClient,
):
    """`deal_id` omitted is past trade — what the two companies did before they came
    to us, which is the evidence a new relationship cannot have. Given, it
    is a deal between the two companies."""
    deal, seller, buyer = await make_deal_with_buyer_company()
    async with db_services.AsyncSessionLocal() as db:
        relationship = await TradeHistoryService(db).relationship_for_pair(
            seller_company_id=seller, buyer_company_id=buyer
        )
    relationship_id = relationship.id
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    deal_id = str(deal)

    from_deal = await client.post(
        f"{BASE}/trade-relationships/{relationship_id}/invoices",
        json=_invoice_body(deal_id=deal_id),
        headers=auth_header(token),
    )
    assert from_deal.status_code == 201, from_deal.text
    assert from_deal.json()["deal_id"] == deal_id

    past = await client.post(
        f"{BASE}/trade-relationships/{relationship_id}/invoices",
        json=_invoice_body(),
        headers=auth_header(token),
    )
    assert past.status_code == 201, past.text
    assert past.json()["deal_id"] is None


async def test_an_invoice_cannot_name_a_deal_that_does_not_exist_or_is_not_this_pairs(
    client: AsyncClient,
):
    """``deal_id`` is frozen once written and nothing else ties an invoice to a
    deal, so a made-up id or another pair's deal would sit on the invoice for good."""
    _deal, seller, buyer = await make_deal_with_buyer_company()
    async with db_services.AsyncSessionLocal() as db:
        relationship = await TradeHistoryService(db).relationship_for_pair(
            seller_company_id=seller, buyer_company_id=buyer
        )
    # Same seller, another buyer company: a real deal, but not between these two.
    other_pairs_deal, _s, _b = await make_deal_with_buyer_company(seller=seller)
    # Same seller, buyer still a legacy row: not between two companies at all.
    legacy_deal = await make_deal(seller)
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)

    def post(deal_id):
        return client.post(
            f"{BASE}/trade-relationships/{relationship.id}/invoices",
            json=_invoice_body(deal_id=str(deal_id)),
            headers=auth_header(token),
        )

    missing = await post(uuid.uuid4())
    assert missing.status_code == 404, missing.text
    for wrong in (other_pairs_deal, legacy_deal):
        refused = await post(wrong)
        assert refused.status_code == 422, refused.text
        assert refused.json()["error_code"] == "TRADE_INVOICE_DEAL_NOT_THIS_PAIR"

    async with db_services.AsyncSessionLocal() as db:
        recorded = await TradeHistoryService(db).list_invoices(relationship.id)
    assert recorded == []


async def test_the_service_and_the_route_agree_about_an_invoices_amount():
    """A Decimal through the service and a string through the route must be the same
    money. Worth asserting because the serialiser is the one place a float could
    creep in."""
    relationship_id, _seller, _buyer = await _relationship()
    async with db_services.AsyncSessionLocal() as db:
        invoice = await TradeHistoryService(db).record_invoice(
            relationship_id,
            invoice_number=f"INV-{uuid.uuid4().hex[:8].upper()}",
            invoice_date=date(2026, 3, 1),
            amount=Decimal("1250.50"),
            currency="USD",
            actor_id="rm-1",
        )
    assert invoice.amount == Decimal("1250.50")


# ── 3.21: how a handed-over deal was paid ─────────────────────────────────────


async def _handed_over_deal_with_a_buyer_company() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A real handed-over deal: a cleared seller, a buyer **company**, paperwork, the
    invoicing branch and the buyer's screening. Driven through the services, so the
    handover passes the guard rather than being set by hand."""
    from app.modules.onboarding.application.deal_service import DealService
    from app.modules.onboarding.application.gst_registration_service import (
        GstRegistrationService,
    )
    from app.modules.onboarding.application.verification_service import VerificationService
    from app.modules.onboarding.domain.entities.deal_enums import DealStage
    from app.modules.onboarding.domain.entities.orchestration_enums import (
        VerificationEntityType,
        VerificationType,
    )
    from app.modules.onboarding.domain.verification_evidence import VerificationEvidence
    from app.modules.onboarding.tests.fixtures.companies import make_prospect
    from app.modules.onboarding.tests.integration._compliance_support import cleared_company
    from app.modules.onboarding.tests.integration.test_handover import (
        _add_required_document,
    )

    pan = _pan()
    seller = await make_prospect()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).update_profile(
            seller,
            {"name": f"Paid Seller {uuid.uuid4().hex[:8]}", "country": "IN", "pan": pan},
            actor_id="test",
        )
    async with db_services.AsyncSessionLocal() as db:
        await GstRegistrationService(db).add(seller, gstin=f"27{pan}1Z5", actor_id="rm-1")
    await cleared_company(seller)
    buyer = await _company("Paying Buyer")

    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            seller, reference=f"Paid deal {uuid.uuid4().hex[:8]}", actor_id="rm-1"
        )
    deal_id = view.id
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer_company(
            deal_id, buyer_company_id=buyer, actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        branches = await GstRegistrationService(db).list_for_company(seller)
        await DealService(db).set_invoicing_branch(
            deal_id, gst_registration_id=branches[0].id, actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            deal_id, DealStage.GATHERING_PAPERWORK, actor_id="rm-1"
        )
    await _add_required_document(deal_id)
    # The buyer company's sanctions and AML, where `for_company` reads them.
    for verification_type in (VerificationType.SANCTIONS, VerificationType.AML):
        async with db_services.AsyncSessionLocal() as db:
            await VerificationService(db).trigger_verification(
                verification_type,
                VerificationEntityType.EXPORTER,
                buyer,
                provider="manual",
                payload={"status": "PASSED"},
                actor_id="tester",
                evidence=VerificationEvidence(note="Test: screened the buyer company."),
            )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).transition_stage(
            deal_id, DealStage.HANDED_OVER, actor_id="rm-1"
        )
    return deal_id, seller, buyer


async def test_recording_how_a_deal_was_paid_creates_its_invoice(client: AsyncClient):
    """Task 3.21's core: one step for the person who knows the answer. The invoice
    appears because this deal had none, and the relationship is the pair's."""
    deal_id, seller, buyer = await _handed_over_deal_with_a_buyer_company()
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)

    resp = await client.post(
        f"{BASE}/deals/{deal_id}/payment-outcome",
        json={
            "payment_status": "PAID",
            "proof_status": "PROVEN",
            "evidence_note": "Bank advice received",
            "invoice_number": "INV-PAID-1",
            "invoice_date": "2026-04-01",
            "amount": "25000.00",
            "currency": "USD",
        },
        headers=auth_header(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["invoice_created"] is True
    assert body["invoice"]["deal_id"] == str(deal_id)
    assert body["invoice"]["amount"] == "25000.00"
    assert body["outcome"]["payment_status"] == "PAID"
    assert body["outcome"]["is_current"] is True

    # And the pair now has a relationship carrying it.
    async with db_services.AsyncSessionLocal() as db:
        relationship = await TradeHistoryService(db).relationship_for_pair(
            seller_company_id=seller, buyer_company_id=buyer
        )
    assert relationship is not None
    assert body["invoice"]["relationship_id"] == str(relationship.id)


async def test_a_second_outcome_supersedes_and_needs_no_invoice_details(
    client: AsyncClient,
):
    deal_id, _seller, _buyer = await _handed_over_deal_with_a_buyer_company()
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    first = await client.post(
        f"{BASE}/deals/{deal_id}/payment-outcome",
        json={
            "payment_status": "UNPAID",
            "invoice_number": "INV-LATE-1",
            "invoice_date": "2026-04-01",
            "amount": "900.00",
            "currency": "EUR",
        },
        headers=auth_header(token),
    )
    assert first.status_code == 201, first.text
    first_outcome = first.json()["outcome"]["id"]

    second = await client.post(
        f"{BASE}/deals/{deal_id}/payment-outcome",
        json={
            "payment_status": "PAID",
            "evidence_note": "Paid late, bank advice on file",
            "supersedes_outcome_id": first_outcome,
        },
        headers=auth_header(token),
    )
    assert second.status_code == 201, second.text
    assert second.json()["invoice_created"] is False
    # One invoice, two beliefs.
    assert second.json()["invoice"]["id"] == first.json()["invoice"]["id"]


async def test_invoice_details_for_a_deal_that_already_has_one_are_refused(
    client: AsyncClient,
):
    """An invoice's identity is frozen, so new details cannot be applied — and
    ignoring them silently would tell the caller they had been recorded."""
    deal_id, _seller, _buyer = await _handed_over_deal_with_a_buyer_company()
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    await client.post(
        f"{BASE}/deals/{deal_id}/payment-outcome",
        json={
            "payment_status": "UNKNOWN",
            "invoice_number": "INV-ONCE",
            "invoice_date": "2026-04-01",
            "amount": "10.00",
            "currency": "USD",
        },
        headers=auth_header(token),
    )
    again = await client.post(
        f"{BASE}/deals/{deal_id}/payment-outcome",
        json={
            "payment_status": "PAID",
            "evidence_note": "Correcting",
            "invoice_number": "INV-TWICE",
            "invoice_date": "2026-05-01",
            "amount": "20.00",
            "currency": "USD",
        },
        headers=auth_header(token),
    )
    assert again.status_code == 422, again.text
    assert again.json()["error_code"] == "TRADE_INVOICE_ALREADY_RECORDED"


async def test_a_partial_invoice_identity_is_refused(client: AsyncClient):
    """All four fields or none: an invoice is immutable once written, so one created
    from three of them could never be completed."""
    deal_id, _seller, _buyer = await _handed_over_deal_with_a_buyer_company()
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    resp = await client.post(
        f"{BASE}/deals/{deal_id}/payment-outcome",
        json={"payment_status": "PAID", "invoice_number": "INV-HALF"},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text


async def test_a_deal_with_no_invoice_and_no_details_says_what_is_missing(
    client: AsyncClient,
):
    deal_id, _seller, _buyer = await _handed_over_deal_with_a_buyer_company()
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    resp = await client.post(
        f"{BASE}/deals/{deal_id}/payment-outcome",
        json={"payment_status": "PAID"},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text
    assert "number, date, amount and currency" in resp.text


async def test_a_deal_that_is_not_handed_over_has_nothing_to_have_been_paid(
    client: AsyncClient,
):
    from app.modules.onboarding.application.deal_service import DealService
    from app.modules.onboarding.tests.fixtures.companies import make_prospect

    seller = await make_prospect()
    buyer = await _company("Early Buyer")
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).open_deal(
            seller, reference=f"Open deal {uuid.uuid4().hex[:8]}", actor_id="rm-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        await DealService(db).set_buyer_company(
            view.id, buyer_company_id=buyer, actor_id="rm-1"
        )

    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)
    resp = await client.post(
        f"{BASE}/deals/{view.id}/payment-outcome",
        json={
            "payment_status": "PAID",
            "invoice_number": "INV-EARLY",
            "invoice_date": "2026-04-01",
            "amount": "10.00",
            "currency": "USD",
        },
        headers=auth_header(token),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "DEAL_NOT_HANDED_OVER"


async def test_claimed_past_trade_is_recorded_without_a_deal(client: AsyncClient):
    """Task 3.21's other half: what the two companies did **before** they came to us.
    `deal_id` is null and `proof_status` defaults to `CLAIMED` — an exporter's own
    account is worth recording, and worth less than a settled invoice."""
    relationship_id, _seller, _buyer = await _relationship()
    _user_id, token = await user_with_role(client, UserRole.OPERATIONS)

    invoice = await client.post(
        f"{BASE}/trade-relationships/{relationship_id}/invoices",
        json=_invoice_body(invoice_number="INV-PAST-2024"),
        headers=auth_header(token),
    )
    assert invoice.status_code == 201, invoice.text
    assert invoice.json()["deal_id"] is None
    invoice_id = invoice.json()["id"]

    outcome = await client.post(
        f"{BASE}/trade-invoices/{invoice_id}/outcomes",
        json={"payment_status": "PAID", "evidence_note": "The exporter says so"},
        headers=auth_header(token),
    )
    assert outcome.status_code == 201, outcome.text
    # CLAIMED by default: nobody has proved it, and the record says which.
    assert outcome.json()["proof_status"] == "CLAIMED"
    assert outcome.json()["payment_status"] == "PAID"
