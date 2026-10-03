"""The CRM's main path, end to end, through the API as the people in it would walk it
(architecture §4.1), and the §4.2 path that only a customer can take.

Nothing is substituted: real routes and roles, the real 4A ↔ 4B reader, the shipped
``CLEAR_POLICY``, the pass-through scanner behind the real upload route, and the
in-memory event bus captured so both announcements can be seen. This is milestone
M5's automated test (architecture §7.3): a Prospect whose check is recorded ``CLEAR``
becomes a ``CUSTOMER``, "became customer" is announced, and its deal is handed over.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.modules.onboarding.application.screening_review_service import SCREENING_CATALOGUE
from app.modules.onboarding.events import publisher as publisher_module
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.compliance import make_compliance_user
from app.platform.authentication.models import UserRole
from app.platform.messaging.ports import InMemoryEventBus
from app.platform.messaging.schemas import EventType

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"
PDF = b"%PDF-1.4 bill of lading"


@pytest.fixture(autouse=True)
def _isolated_storage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Uploads go through the route's own storage, which reads this variable."""
    monkeypatch.setenv("STORAGE_LOCAL_ROOT", str(tmp_path / "storage"))


@pytest.fixture
def bus(monkeypatch: pytest.MonkeyPatch) -> InMemoryEventBus:
    injected = InMemoryEventBus()
    monkeypatch.setattr(publisher_module, "get_event_bus", lambda: injected)
    return injected


def _pan() -> str:
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    return f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"


def _events(bus: InMemoryEventBus, event_type: EventType) -> list:
    return [e for e in bus.published if e.event_type is event_type]


class _Crm:
    """The API calls the path is made of, each asserting it succeeded."""

    def __init__(self, client: AsyncClient, ops: str, compliance: str, checker: str) -> None:
        self.client, self.ops, self.compliance = client, ops, compliance
        # Maker-checker (Developer 1, plan P3-1d): a second compliance officer approves
        # what `compliance` proposes.
        self.checker = checker

    async def ok(self, method: str, path: str, token: str, **kwargs) -> dict:
        resp = await self.client.request(method, f"{BASE}{path}", headers=auth_header(token),
                                         **kwargs)
        assert resp.status_code in (200, 201), f"{method} {path}: {resp.text}"
        return resp.json()

    async def company(self, company_id: str) -> dict:
        return await self.ok("GET", f"/exporters/{company_id}", self.compliance)

    async def deal(self, deal_id: str) -> dict:
        return await self.ok("GET", f"/deals/{deal_id}", self.ops)

    async def decide(self, company_id: str, to_value: str, token: str, **body) -> dict:
        """Record a move; a CLEAR, FLAGGED or ON_HOLD is proposed (202) and approved by
        the second officer (maker-checker). Returns the decision."""
        path = f"/exporters/{company_id}/background-check"
        resp = await self.client.post(f"{BASE}{path}/decisions", headers=auth_header(token),
                                      json={"to_value": to_value, **body})
        if resp.status_code != 202:
            assert resp.status_code == 201, f"{to_value}: {resp.text}"
            return resp.json()
        approved = await self.ok("POST", f"{path}/proposals/{resp.json()['id']}/approve",
                                 self.checker)
        return approved["decision"]

    async def answer_screening(self, company_id: str) -> None:
        for key in SCREENING_CATALOGUE:
            await self.ok("PUT", f"/exporters/{company_id}/screening-review/{key}",
                          self.compliance, json={"status": "PASSED"})
        # Rule B (plan P3-2): KYB, AML and sanctions passed in the current cycle.
        for check in ("KYB", "AML", "SANCTIONS"):
            await self.ok("POST", "/verifications", self.compliance,
                          json={"verification_type": check, "entity_type": "EXPORTER",
                                "entity_reference": company_id,
                                "payload": {"status": "PASSED"},
                                "evidence_note": f"{check} checked manually."})

    async def screen_the_buyer(self, deal_id: str) -> None:
        """PASSED sanctions and AML on the deal's buyer (plan BQ-4).

        Live since task 2.5 wired Developer 1's `ComplianceFactsReader`: the handover
        requires the **buyer's** sanctions and AML to be `PASSED`, and a buyer nobody
        has screened reads `MISSING` — "we have not checked" is not "clean".

        Keyed to the `deal_buyer` row, which is where `for_legacy_buyer` reads them.
        Once task 2.4 records buyer *companies*, this moves to the company.
        """
        deal = await self.deal(deal_id)
        buyer_id = deal["buyer"]["id"]
        for check in ("SANCTIONS", "AML"):
            await self.ok("POST", "/verifications", self.compliance,
                          json={"verification_type": check, "entity_type": "BUYER",
                                "entity_reference": buyer_id,
                                "payload": {"status": "PASSED"},
                                "evidence_note": f"Buyer {check} checked manually."})

    async def new_prospect_with_a_deal_ready_to_hand_over(self) -> tuple[str, str]:
        """Steps 1–7 of §4.1: a qualified company, a deal, its buyer and paperwork."""
        created = await self._create(_pan())
        company_id = created["customer_id"]
        await self.ok("POST", f"/exporters/{company_id}/qualification/outcome", self.ops,
                      json={"outcome": "QUALIFIED", "note": "Meets our requirements."})
        deal = await self.ok("POST", f"/exporters/{company_id}/deals", self.ops,
                             json={"reference": "Rotterdam shipment"})
        await self.ok("PUT", f"/deals/{deal['id']}/buyer", self.ops,
                      json={"name": "Rotterdam Trading BV", "country": "NL"})
        await self.ok("POST", f"/deals/{deal['id']}/transitions", self.ops,
                      json={"to_stage": "GATHERING_PAPERWORK"})
        # PRE_SHIPMENT, not SHIPPING: migration 0030 requires a pre-shipment
        # document before a handover (P2-5b, IQ-10), so this is the upload that
        # makes the guard passable rather than just paperwork on the deal.
        await self.ok("POST", f"/deals/{deal['id']}/documents", self.ops,
                      data={"category": "PRE_SHIPMENT",
                            "document_type": "proforma_invoice",
                            "source": "EXPORTER_UPLOAD"},
                      files={"file": ("proforma_invoice.pdf", PDF, "application/pdf")})
        await self.record_the_invoicing_branch(company_id, deal["id"])
        await self.screen_the_buyer(deal["id"])
        return company_id, deal["id"]

    async def record_the_invoicing_branch(self, company_id: str, deal_id: str) -> None:
        """Say which of the seller's GST branches this deal is invoiced from.

        Part of the real path since task 2.8. The handover guard asks for it whenever
        the seller has an active registration (plan P6-7), and this company is created
        with one — so without this the handover is refused with "the invoicing branch
        is not recorded", which is the rule working rather than a problem.
        """
        branches = await self.ok(
            "GET", f"/exporters/{company_id}/gst-registrations", self.ops
        )
        active = [row for row in branches["registrations"] if row["active"]]
        assert active, "this company was created with a GSTIN, so it has a branch"
        await self.ok(
            "PUT",
            f"/deals/{deal_id}/invoicing-branch",
            self.ops,
            json={"gst_registration_id": active[0]["id"]},
        )

    async def _create(self, pan: str) -> dict:
        resp = await self.client.post(
            f"{BASE}/exporters",
            json={"source": "SALES", "name": f"E2E Exports {pan}", "country": "IN",
                  "pan": pan, "gstins": [f"27{pan}1Z5"]},
            headers={**auth_header(self.ops), "Idempotency-Key": str(uuid.uuid4())},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()


async def _crm(client: AsyncClient) -> _Crm:
    return _Crm(
        client,
        await token_with_role(client, UserRole.OPERATIONS),
        await token_with_role(client, UserRole.COMPLIANCE),
        (await make_compliance_user(client, label="e2e-checker")).token,
    )


async def test_the_main_path_from_a_new_lead_to_a_handed_over_deal(
    client: AsyncClient, bus: InMemoryEventBus
):
    crm = await _crm(client)

    # 1–2. Staff add a lead. It cannot have a deal yet.
    pan = _pan()
    company = await crm._create(pan)
    company_id = company["customer_id"]
    assert company["journey"] == "LEAD"
    refused = await client.post(
        f"{BASE}/exporters/{company_id}/deals", json={"reference": "too early"},
        headers=auth_header(crm.ops),
    )
    assert refused.status_code == 409 and refused.json()["error_code"] == "DEAL_COMPANY_NOT_READY"

    # 3–4. Qualification: QUALIFIED moves the company to PROSPECT.
    await crm.ok("POST", f"/exporters/{company_id}/qualification/outcome", crm.ops,
                 json={"outcome": "QUALIFIED", "note": "Meets our requirements."})
    assert (await crm.company(company_id))["journey"] == "PROSPECT"

    # 5. The conversation.
    await crm.ok("POST", f"/exporters/{company_id}/conversation", crm.ops,
                 json={"conversation": "INTERESTED"})

    # 6. A deal — which the server now offers — sets the conversation to READY_NOW.
    listing = await crm.ok("GET", f"/exporters/{company_id}/deals", crm.ops)
    assert listing["can_open_deal"] is True
    deal = await crm.ok("POST", f"/exporters/{company_id}/deals", crm.ops,
                        json={"reference": "Rotterdam shipment"})
    deal_id = deal["id"]
    conversation = await crm.ok("GET", f"/exporters/{company_id}/conversation", crm.ops)
    assert conversation["conversation"] == "READY_NOW"
    await crm.ok("PUT", f"/deals/{deal_id}/buyer", crm.ops,
                 json={"name": "Rotterdam Trading BV", "country": "NL"})
    await crm.record_the_invoicing_branch(company_id, deal_id)
    await crm.ok("POST", f"/deals/{deal_id}/transitions", crm.ops,
                 json={"to_stage": "GATHERING_PAPERWORK"})

    # 7. Paperwork, scanned before it can be opened.
    #
    # The handover needs a PRE_SHIPMENT document (migration 0030, P2-5b), and the
    # guard says so while it is missing — checked here, before the upload, because
    # "the rule is configured" and "the rule is enforced" are different claims.
    missing_paperwork = await crm.deal(deal_id)
    assert "missing required documents: PRE_SHIPMENT" in (
        missing_paperwork["handover_blocked_reason"] or ""
    )

    required = await crm.ok(
        "POST", f"/deals/{deal_id}/documents", crm.ops,
        data={"category": "PRE_SHIPMENT", "document_type": "proforma_invoice",
              "source": "EXPORTER_UPLOAD"},
        files={"file": ("proforma_invoice.pdf", PDF, "application/pdf")},
    )
    assert required["scan_status"] == "AVAILABLE"

    document = await crm.ok(
        "POST", f"/deals/{deal_id}/documents", crm.ops,
        data={"category": "SHIPPING", "document_type": "bill_of_lading",
              "source": "EXPORTER_UPLOAD"},
        files={"file": ("bill_of_lading.pdf", PDF, "application/pdf")},
    )
    assert document["scan_status"] == "AVAILABLE"
    # The paperwork condition is met now, so what still blocks the handover is the
    # company's standing — which the next steps fix.
    assert "missing required documents" not in (
        (await crm.deal(deal_id))["handover_blocked_reason"] or ""
    )

    # 7b. The buyer is screened too (BQ-4, live since task 2.5). Checked before and
    # after, because this is the condition most easily satisfied by accident.
    assert "the buyer's sanctions check is MISSING" in (
        (await crm.deal(deal_id))["handover_blocked_reason"] or ""
    )
    await crm.screen_the_buyer(deal_id)
    assert "buyer's" not in ((await crm.deal(deal_id))["handover_blocked_reason"] or "")

    # 8. The background check: started by staff, its inputs recorded by compliance.
    await crm.decide(company_id, "IN_REVIEW", crm.ops)
    await crm.answer_screening(company_id)
    blocked = await crm.deal(deal_id)
    assert "HANDED_OVER" not in {m["to_stage"] for m in blocked["allowed_stage_moves"]}
    assert "not CUSTOMER" in blocked["handover_blocked_reason"]

    # 9–10. One compliance user proposes CLEAR and a second approves it; the company
    # becomes a CUSTOMER and "became customer" is announced, once.
    clearing = await crm.decide(company_id, "CLEAR", crm.compliance,
                                reason="Screening complete; nothing adverse.",
                                risk_rating="LOW")
    assert (await crm.company(company_id))["journey"] == "CUSTOMER"
    [became_customer] = _events(bus, EventType.COMPANY_BECAME_CUSTOMER)
    assert became_customer.payload["company_id"] == company_id
    assert became_customer.payload["clearing_decision_id"] == clearing["id"]
    assert became_customer.payload["risk_rating"] == "LOW"
    assert clearing["approved_by"] != clearing["decided_by"]

    # 11–12. The deal is handed over, and the lending team is told.
    ready = await crm.deal(deal_id)
    assert "HANDED_OVER" in {m["to_stage"] for m in ready["allowed_stage_moves"]}
    handed = await crm.ok("POST", f"/deals/{deal_id}/transitions", crm.ops,
                          json={"to_stage": "HANDED_OVER"})
    assert handed["stage"] == "HANDED_OVER"
    [handed_over] = _events(bus, EventType.DEAL_HANDED_OVER)
    assert set(handed_over.payload["document_ids"]) == {required["id"], document["id"]}
    # And the handover is a record now, not only an announcement (P2-7).
    snapshot = handed["handover_snapshot"]
    assert snapshot["snapshot_source"] == "taken_at_handover"
    assert snapshot["buyer"]["name"] == "Rotterdam Trading BV"
    assert set(snapshot["document_ids"]) == {required["id"], document["id"]}

    # The whole story is in the one history log.
    history = await crm.ok("GET", f"/exporters/{company_id}/history", crm.compliance,
                           params={"limit": 200})
    dimensions = {entry["dimension"] for entry in history["entries"]}
    assert {"journey", "qualification", "conversation", "deal", "background_check",
            "screening"} <= dimensions
    journey = {(e["from_value"], e["to_value"]) for e in history["entries"]
               if e["dimension"] == "journey"}
    assert {("LEAD", "PROSPECT"), ("PROSPECT", "CUSTOMER")} <= journey


async def test_new_information_about_a_customer_flags_it_and_blocks_its_handovers(
    client: AsyncClient, bus: InMemoryEventBus
):
    """§4.2: a cleared customer is reopened, then flagged. It stays a CUSTOMER (A5 —
    a flag is not a demotion), its deals cannot be handed over meanwhile, and
    reassessing and clearing it again does not announce a second "became customer"."""
    crm = await _crm(client)
    company_id, deal_id = await crm.new_prospect_with_a_deal_ready_to_hand_over()
    await crm.decide(company_id, "IN_REVIEW", crm.ops)
    await crm.answer_screening(company_id)
    await crm.decide(company_id, "CLEAR", crm.compliance, reason="All clear.", risk_rating="LOW")
    assert (await crm.company(company_id))["journey"] == "CUSTOMER"

    await crm.decide(company_id, "IN_REVIEW", crm.compliance, reason="New adverse media.")
    await crm.decide(company_id, "FLAGGED", crm.compliance, reason="Adverse media confirmed.")

    assert (await crm.company(company_id))["journey"] == "CUSTOMER"
    flagged = await crm.deal(deal_id)
    assert "HANDED_OVER" not in {m["to_stage"] for m in flagged["allowed_stage_moves"]}
    assert "FLAGGED" in flagged["handover_blocked_reason"]

    await crm.decide(company_id, "IN_REVIEW", crm.compliance, reason="Explained and resolved.")
    await crm.decide(company_id, "CLEAR", crm.compliance, reason="Resolved.",
                     risk_rating="MEDIUM")
    assert len(_events(bus, EventType.COMPANY_BECAME_CUSTOMER)) == 1
    assert "HANDED_OVER" in {m["to_stage"] for m in (await crm.deal(deal_id))["allowed_stage_moves"]}
