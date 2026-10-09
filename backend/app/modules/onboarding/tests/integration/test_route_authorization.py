"""Role gates on the onboarding / exporter-CRM routes, reviewer attribution on
verification reviews, the provider allow-list, and server-side masking of
PAN/GSTIN/IEC and contact email/phone.

Every gated route gets a negative test per refused role asserting 403 — the
gate runs as a dependency, so a 403 also proves the handler never ran.

Reveal rule: holders of `exporters:view_full_tax_id` (COMPLIANCE by default) see raw
PAN/GSTIN/IEC and raw contact email/phone; every other role sees them masked — the
administrator, and the assigned relationship manager too (architecture decision 12
defers ownership-scoped reveal until after the prototype). Only they may use an exact
identifier search filter, because an exact match is an existence oracle whatever the
response body says.

Gates are permissions (`require_permission`); the sets below are the built-in roles
seeded with each. The administrator reads the business and changes none of it.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from httpx import AsyncClient

from app.modules.onboarding.tests.fixtures.auth import (
    auth_header,
    token_with_role,
    user_with_role,
)
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"

# Who works the business: relationship managers and compliance.
STAFF = {UserRole.OPERATIONS, UserRole.COMPLIANCE}
# Compliance's own decisions.
COMPLIANCE_ONLY = {UserRole.COMPLIANCE}
# System configuration: the administrator only.
ADMIN_ONLY = {UserRole.ADMIN}
# Reads of the compliance surface: staff, and the administrator read-only. Never
# DEVELOPER.
STAFF_READERS = STAFF | {UserRole.ADMIN}
# Masked exporter-CRM reads: DEVELOPER may read, never unmasked.
READERS = STAFF_READERS | {UserRole.DEVELOPER}
# Senior work no built-in role holds: the seeded lead roles do.
LEADS_ONLY: set[UserRole] = set()
# Saving a copy of a document: compliance only.
DOWNLOADERS = {UserRole.COMPLIANCE}


def _case_body() -> dict:
    return {
        "tenant_id": str(uuid.uuid4()),
        "country_code": "IN",
        "case_type": "KYC",
        "subject_type": "INDIVIDUAL",
        "required_checks": ["IDENTITY"],
        "profile": {"first_name": "Meera", "last_name": "Iyer"},
    }


def _trigger_body(entity_reference: str | None = None) -> dict:
    return {
        # KYB, not KYC: KYC is a check on a person, and the service rejects a
        # KYC/EXPORTER pair (422) before the route gate under test matters.
        "verification_type": "KYB",
        "entity_type": "EXPORTER",
        # The subject must be a real company (a random id is a
        # 404) — the gate tests never reach the handler, so any id does there.
        "entity_reference": entity_reference or str(uuid.uuid4()),
        "provider": "manual",
        "payload": {"status": "PASSED"},
        # A manual PASSED needs evidence (a note suffices).
        "evidence_note": "Registry extract checked.",
    }


_ID = "00000000-0000-4000-8000-000000000000"

# (method, path, json body, allowed roles)
GATED_ROUTES = [
    # cases
    ("POST", f"{BASE}/cases", _case_body(), STAFF),
    ("PATCH", f"{BASE}/cases/{_ID}", {"cell_id": "cell-in-2"}, STAFF),
    (
        "POST",
        f"{BASE}/cases/{_ID}/transitions",
        {"next_state": "SUBMITTED", "source": "USER_ACTION"},
        COMPLIANCE_ONLY,
    ),
    # onboarding foundation
    ("POST", f"{BASE}/register", {"email": "x@example.com", "full_name": "X"}, STAFF),
    # verifications
    ("POST", f"{BASE}/verifications", _trigger_body(), COMPLIANCE_ONLY),
    (
        "POST",
        f"{BASE}/verifications/{_ID}/review",
        {"review_status": "ACCEPTED"},
        COMPLIANCE_ONLY,
    ),
    # exporter CRM
    ("POST", f"{BASE}/exporters", {"source": "SALES"}, STAFF),
    ("PATCH", f"{BASE}/exporters/{_ID}", {"industry": "Textiles"}, STAFF),
    (
        "POST",
        f"{BASE}/exporters/{_ID}/marker",
        {"marker": "PAUSED", "reason": "Seasonal"},
        STAFF,
    ),
    ("POST", f"{BASE}/exporters/{_ID}/contacts", {"name": "Jane"}, STAFF),
    ("POST", f"{BASE}/exporters/{_ID}/contacts/{_ID}/status", {"status": "INACTIVE", "reason": "Left"}, STAFF),
    ("POST", f"{BASE}/exporters/{_ID}/contacts/{_ID}/verification", None, STAFF),
    # Trade history. Writes are STAFF; the reads are in
    # the contract table — DEVELOPER may make them, which `GATED_ROUTES` here cannot
    # express because every row of it is a write.
    (
        "POST",
        f"{BASE}/trade-relationships/{_ID}/invoices",
        {
            "invoice_number": "INV-1",
            "invoice_date": "2026-03-01",
            "amount": "100.00",
            "currency": "USD",
        },
        STAFF,
    ),
    (
        "POST",
        f"{BASE}/trade-invoices/{_ID}/outcomes",
        {"payment_status": "UNKNOWN"},
        STAFF,
    ),
    (
        "POST",
        f"{BASE}/deals/{_ID}/payment-outcome",
        {"payment_status": "UNKNOWN"},
        STAFF,
    ),
    # GST registrations. Recording and deactivating a branch is a
    # relationship manager's record; flagging one stops trade through it, so it is
    # COMPLIANCE's — and that difference is what `_GST_FLAG_ROLES` below asserts.
    (
        "POST",
        f"{BASE}/exporters/{_ID}/gst-registrations",
        {"gstin": "27AAAPL1234C1ZV"},
        STAFF,
    ),
    ("POST", f"{BASE}/gst-registrations/{_ID}/deactivate", {}, STAFF),
    ("GET", f"{BASE}/exporters/{_ID}/addresses", None, READERS),
    (
        "POST",
        f"{BASE}/exporters/{_ID}/addresses",
        {"address_type": "BILLING", "line1": "x", "city": "y", "country": "IN"},
        STAFF,
    ),
    ("PATCH", f"{BASE}/addresses/{_ID}", {"city": "Pune"}, STAFF),
    ("POST", f"{BASE}/addresses/{_ID}/default", None, STAFF),
    ("POST", f"{BASE}/addresses/{_ID}/deactivate", {}, STAFF),
    ("GET", f"{BASE}/exporters/{_ID}/bank-accounts", None, READERS),
    ("GET", f"{BASE}/bank-accounts/pending", None, STAFF),
    ("POST", f"{BASE}/bank-accounts/{_ID}/approve", None, STAFF),
    ("POST", f"{BASE}/bank-accounts/{_ID}/reject", {"reason": "x"}, COMPLIANCE_ONLY),
    (
        "POST",
        f"{BASE}/bank-accounts/{_ID}/verify",
        {"method": "BANK_LETTER", "evidence_document_id": _ID},
        COMPLIANCE_ONLY,
    ),
    ("POST", f"{BASE}/bank-accounts/{_ID}/primary", None, COMPLIANCE_ONLY),
    ("POST", f"{BASE}/bank-accounts/{_ID}/deactivate", {"reason": "x"}, COMPLIANCE_ONLY),
    ("POST", f"{BASE}/bank-accounts/{_ID}/reveal", None, COMPLIANCE_ONLY),
    (
        "POST",
        f"{BASE}/gst-registrations/{_ID}/flag",
        {"reason": "Returns unfiled"},
        COMPLIANCE_ONLY,
    ),
    (
        "POST",
        f"{BASE}/gst-registrations/{_ID}/unflag",
        {"reason": "Now filed"},
        COMPLIANCE_ONLY,
    ),
    # A deal's invoicing branch — a routine CRM write, like its buyer.
    ("PUT", f"{BASE}/deals/{_ID}/invoicing-branch", {"gst_registration_id": None}, STAFF),
    # Bringing a buyer-only company into the sales pipeline. A
    # commercial decision, so the roles that make commercial decisions; DEVELOPER is
    # read-only throughout the CRM.
    ("POST", f"{BASE}/exporters/{_ID}/pipeline", {}, STAFF),
    # "Which company is this?". STAFF, including OPERATIONS: recording a
    # deal's buyer is a relationship manager's job, and the disclosure rule was decided for
    # exactly that case — a full identifier may name a company even for a role that
    # sees identifiers masked. DEVELOPER is excluded: it may never reveal an
    # identifier (`can_reveal_identifiers`) and has no buyer to resolve.
    (
        "POST",
        f"{BASE}/companies/match",
        {"name": "Rotterdam Trading BV", "country": "NL"},
        STAFF,
    ),
    # qualification
    (
        "POST",
        f"{BASE}/qualification/criteria",
        {"key": "x", "label": "X", "kind": "YES_NO", "required": False},
        ADMIN_ONLY,
    ),
    (
        "POST",
        f"{BASE}/qualification/criteria/revenue/versions",
        {"label": "X", "kind": "YES_NO", "required": False},
        ADMIN_ONLY,
    ),
    (
        "POST",
        f"{BASE}/exporters/{_ID}/qualification/results",
        {"results": [{"criterion_key": "revenue", "result": "UNKNOWN"}]},
        STAFF,
    ),
    (
        "POST",
        f"{BASE}/exporters/{_ID}/qualification/outcome",
        {"outcome": "QUALIFIED"},
        STAFF,
    ),
    # company intake and bulk import
    ("POST", f"{BASE}/rxil/company-intake", {"exporter": {}}, COMPLIANCE_ONLY),
    ("POST", f"{BASE}/imports/companies", None, STAFF),
    ("POST", f"{BASE}/imports/companies/preview", None, STAFF),
    (
        "POST",
        f"{BASE}/exporters/{_ID}/activities",
        {"activity_type": "CALL", "subject": "x"},
        STAFF,
    ),
    # screening review
    (
        "PUT",
        f"{BASE}/exporters/{_ID}/screening-review/suspicious-bank-indicators",
        {"status": "PASSED"},
        COMPLIANCE_ONLY,
    ),
    # ── reads ──
    ("GET", f"{BASE}/cases/{_ID}", None, STAFF),
    ("GET", f"{BASE}/cases/{_ID}/transitions", None, STAFF),
    ("GET", f"{BASE}/{_ID}/sdk-token", None, STAFF),
    ("GET", f"{BASE}/{_ID}/status", None, STAFF),
    ("GET", f"{BASE}/verifications/{_ID}", None, STAFF_READERS),
    ("GET", f"{BASE}/verifications?entity_type=EXPORTER&entity_reference={_ID}", None, STAFF_READERS),
    ("GET", f"{BASE}/exporters", None, READERS),
    ("GET", f"{BASE}/companies/identity-completion", None, READERS),
    ("GET", f"{BASE}/exporters/{_ID}", None, READERS),
    ("GET", f"{BASE}/exporters/{_ID}/contacts", None, READERS),
    ("GET", f"{BASE}/exporters/{_ID}/activities", None, READERS),
    ("GET", f"{BASE}/exporters/activities/pending", None, READERS),
    ("GET", f"{BASE}/exporters/{_ID}/screening-review", None, STAFF_READERS),
    ("GET", f"{BASE}/exporters/{_ID}/bank-activity", None, STAFF_READERS),
    ("GET", f"{BASE}/qualification/criteria", None, READERS),
    ("GET", f"{BASE}/qualification/criteria/revenue/versions", None, READERS),
    ("GET", f"{BASE}/qualification/reason-codes", None, READERS),
    ("GET", f"{BASE}/exporters/{_ID}/qualification", None, READERS),
    ("GET", f"{BASE}/imports/companies/template", None, STAFF),
    # ══ Area blocks ═══════════════════════════════════════════════════════════
    #
    # §7.7: at least one refusal test per gated route. `REFUSALS` below derives
    # one per refused role from every row here, so a route needs a row and
    # nothing else. Several areas add them, so the tail is cut into one block per
    # area rather than leaving one shared append point, which would conflict
    # every time.
    #
    # ── Conversation and follow-ups ──
    #
    # ── Conversation gauge ──
    # `REFUSALS` turns each row into one 403 test per role the row excludes. The
    # bodies below are well formed on purpose: a gate that runs as a dependency
    # refuses before the handler, so a 403 here also proves the handler never ran.
    (
        "POST",
        f"{BASE}/exporters/{_ID}/conversation",
        {"conversation": "REACHING_OUT"},
        STAFF,
    ),
    ("GET", f"{BASE}/exporters/{_ID}/conversation", None, READERS),
    ("GET", f"{BASE}/exporters/{_ID}/conversation/moves", None, READERS),
    #
    # ── Follow-ups ──
    # One 403 test per refused role, derived by `REFUSALS` below. The body is
    # well formed on purpose: the gate runs as a dependency, so a 403 also proves
    # the handler never reached the service.
    (
        "POST",
        f"{BASE}/follow-ups/{_ID}/completion",
        {"outcome": "DONE"},
        STAFF,
    ),
    ("GET", f"{BASE}/follow-ups", None, READERS),
    #
    # ── Deals, buyers, storage and documents ──
    # One 403 test per refused role, derived by `REFUSALS` below. Each body is well
    # formed on purpose: the gate runs as a dependency, so a 403 also proves the
    # handler never reached the service.
    ("POST", f"{BASE}/exporters/{_ID}/deals", {"reference": "Rotterdam order"}, STAFF),
    ("GET", f"{BASE}/exporters/{_ID}/deals", None, READERS),
    ("GET", f"{BASE}/deals", None, READERS),
    ("GET", f"{BASE}/deals/{_ID}", None, READERS),
    (
        "POST",
        f"{BASE}/deals/{_ID}/transitions",
        {"to_stage": "GATHERING_PAPERWORK"},
        STAFF,
    ),
    (
        "PUT",
        f"{BASE}/deals/{_ID}/buyer",
        {"name": "Rotterdam Trading BV", "country": "NL"},
        STAFF,
    ),
    # Required document categories. A settings
    # rule about every deal, so the read is `READERS` like `/qualification/criteria`
    # and the write is ADMIN only.
    ("GET", f"{BASE}/settings/deal-required-documents", None, READERS),
    ("GET", f"{BASE}/settings/payment-terms", None, READERS),
    (
        "POST",
        f"{BASE}/settings/payment-terms",
        {"code": "X", "label": "x", "kind": "ADVANCE"},
        ADMIN_ONLY,
    ),
    ("PATCH", f"{BASE}/settings/payment-terms/X", {"label": "y"}, ADMIN_ONLY),
    ("PATCH", f"{BASE}/deals/{_ID}/terms", {"currency": "INR"}, STAFF),
    ("PUT", f"{BASE}/exporters/{_ID}/default-payment-term", {"payment_term_id": None}, STAFF),
    (
        "POST",
        f"{BASE}/settings/deal-required-documents",
        {"category": "BUYER"},
        ADMIN_ONLY,
    ),
    # Documents. The two uploads are multipart, so they are covered by their
    # own refusal tests in `test_documents.py` rather than here — this table
    # sends a JSON body, and a multipart route refuses a JSON one at parsing with a
    # 422 before the gate is reached, which would prove nothing about the gate.
    ("GET", f"{BASE}/documents/categories", None, READERS),
    ("GET", f"{BASE}/documents/{_ID}", None, READERS),
    ("GET", f"{BASE}/documents/{_ID}/preview", None, READERS),
    ("GET", f"{BASE}/exporters/{_ID}/documents", None, READERS),
    ("GET", f"{BASE}/deals/{_ID}/documents", None, READERS),
    ("POST", f"{BASE}/documents/{_ID}/download-link", None, DOWNLOADERS),
    (
        "GET",
        f"{BASE}/documents/content?key=test%2Fcompany%2Fx%2Finternal%2Fx.pdf"
        "&expires=1&signature=nope",
        None,
        READERS,
    ),
    # ══ Compliance blocks ══
    #
    # The same cut as the area blocks above: each area adds rows only inside its
    # own block, and `REFUSALS` derives the 403 tests.
    #
    # ── Background check ──
    #
    # DEVELOPER is refused even on the reads, and the administrator reads but never
    # moves. These rows are what proves it, rather than the intention living only in a
    # comment.
    ("GET", f"{BASE}/exporters/{_ID}/background-check", None, STAFF_READERS),
    (
        "POST",
        f"{BASE}/exporters/{_ID}/background-check/decisions",
        {"to_value": "IN_REVIEW"},
        STAFF,
    ),
    ("GET", f"{BASE}/exporters/{_ID}/background-check/decisions", None, STAFF_READERS),
    #
    # ── Verification and screening ──
    (
        "GET",
        f"{BASE}/exporters/{_ID}/screening-review/website-reviewed/history",
        None,
        STAFF_READERS,
    ),
    #
    # ── Compliance engine ──
    # DEVELOPER refused throughout. The start is COMPLIANCE's.
    (
        "GET",
        f"{BASE}/exporters/{_ID}/background-check/decisions/{_ID}/evidence",
        None,
        STAFF_READERS,
    ),
    ("GET", f"{BASE}/exporters/{_ID}/background-check/cycles", None, STAFF_READERS),
    (
        "POST",
        f"{BASE}/exporters/{_ID}/background-check/cycles",
        {"kind": "RE_KYC", "reason": "Annual re-check"},
        COMPLIANCE_ONLY,
    ),
    # Maker-checker: compliance and admin resolve proposals and read the
    # queue; the RM never approves. The due list is read by all staff.
    ("GET", f"{BASE}/exporters/{_ID}/background-check/proposals", None, STAFF_READERS),
    (
        "POST",
        f"{BASE}/exporters/{_ID}/background-check/proposals/{_ID}/approve",
        None,
        COMPLIANCE_ONLY,
    ),
    (
        "POST",
        f"{BASE}/exporters/{_ID}/background-check/proposals/{_ID}/reject",
        {"reason": "not convinced"},
        COMPLIANCE_ONLY,
    ),
    (
        "POST",
        f"{BASE}/exporters/{_ID}/background-check/proposals/{_ID}/withdraw",
        {},
        COMPLIANCE_ONLY,
    ),
    ("GET", f"{BASE}/background-check/proposals?status=open", None, COMPLIANCE_ONLY),
    ("GET", f"{BASE}/background-check/due", None, STAFF_READERS),
    # Who is working on it. The RM route admits staff; the service then applies "an RM
    # claims for themselves; anything else needs exporters:assign_rm". Bulk
    # reassignment needs exporters:assign_rm itself, which only the Sales lead role
    # holds. Reviews are claimed, assigned and released by compliance; the worklists
    # of reviews are theirs, the information requests, badge counts and recent
    # decisions every staff user's (and the administrator's, read-only).
    (
        "POST",
        f"{BASE}/exporters/{_ID}/relationship-manager",
        {"user_id": None, "seen_user_id": None},
        STAFF,
    ),
    ("GET", f"{BASE}/staff?role=OPERATIONS", None, STAFF),
    (
        "POST",
        f"{BASE}/relationship-managers/reassign",
        {"from_user_id": _ID, "to_user_id": _ID, "reason": "left", "dry_run": True},
        LEADS_ONLY,
    ),
    # Who chases the payments: compliance, and any role that may assign RMs.
    (
        "POST",
        f"{BASE}/exporters/{_ID}/collections-owner",
        {"user_id": None, "seen_user_id": None},
        COMPLIANCE_ONLY,
    ),
    (
        "POST",
        f"{BASE}/collections-owners/reassign",
        {"from_user_id": _ID, "to_user_id": _ID, "reason": "left", "dry_run": True},
        COMPLIANCE_ONLY,
    ),
    # Groups: read by every reader, linked by staff; the suggestions name people.
    ("GET", f"{BASE}/exporters/{_ID}/group", None, READERS),
    ("PUT", f"{BASE}/exporters/{_ID}/parent", {"parent_company_id": None}, STAFF),
    ("GET", f"{BASE}/exporters/{_ID}/group/suggestions", None, STAFF_READERS),
    # Sanctions screening: read by staff, recorded and decided by compliance.
    ("GET", f"{BASE}/settings/sanctions-lists", None, STAFF_READERS),
    (
        "POST",
        f"{BASE}/settings/sanctions-lists",
        {"code": "X", "name": "x", "list_version_date": "2026-10-09"},
        ADMIN_ONLY,
    ),
    ("PATCH", f"{BASE}/settings/sanctions-lists/X", {"name": "y"}, ADMIN_ONLY),
    ("GET", f"{BASE}/exporters/{_ID}/sanctions", None, STAFF_READERS),
    ("GET", f"{BASE}/exporters/{_ID}/sanctions/runs", None, STAFF_READERS),
    ("POST", f"{BASE}/exporters/{_ID}/sanctions/runs", {"list_codes": ["UN_SC"]}, COMPLIANCE_ONLY),
    ("GET", f"{BASE}/sanctions/runs/{_ID}", None, STAFF_READERS),
    (
        "POST",
        f"{BASE}/sanctions/hits/{_ID}/decision",
        {"disposition": "OPEN"},
        COMPLIANCE_ONLY,
    ),
    ("POST", f"{BASE}/sanctions/hits/{_ID}/confirm", None, COMPLIANCE_ONLY),
    ("POST", f"{BASE}/sanctions/hits/{_ID}/reject", {"reason": "x"}, COMPLIANCE_ONLY),
    ("GET", f"{BASE}/sanctions/true-matches", None, COMPLIANCE_ONLY),
    ("GET", f"{BASE}/sanctions/rescreen-due", None, STAFF_READERS),
    ("POST", f"{BASE}/exporters/{_ID}/background-check/reviewer/claim", None, COMPLIANCE_ONLY),
    (
        "PUT",
        f"{BASE}/exporters/{_ID}/background-check/reviewer",
        {"user_id": _ID, "reason": "balance"},
        COMPLIANCE_ONLY,
    ),
    (
        "POST",
        f"{BASE}/exporters/{_ID}/background-check/reviewer/release",
        {},
        COMPLIANCE_ONLY,
    ),
    ("GET", f"{BASE}/background-check/reviews?view=awaiting", None, COMPLIANCE_ONLY),
    ("GET", f"{BASE}/background-check/info-requests", None, STAFF_READERS),
    ("GET", f"{BASE}/worklist/counts", None, STAFF_READERS),
    ("GET", f"{BASE}/background-check/recent-decisions", None, STAFF_READERS),
]

REFUSALS = [
    pytest.param(
        method, path, body, role, id=f"{method} {path.removeprefix(BASE)} as {role.value}"
    )
    for method, path, body, allowed in GATED_ROUTES
    for role in UserRole
    if role not in allowed
]


@pytest.fixture(scope="module")
async def tokens(client: AsyncClient) -> dict[UserRole, str]:
    return {role: await token_with_role(client, role) for role in UserRole}


@pytest.mark.parametrize(("method", "path", "body", "role"), REFUSALS)
async def test_gated_route_refuses_role(
    client: AsyncClient,
    tokens: dict[UserRole, str],
    method: str,
    path: str,
    body: dict | None,
    role: UserRole,
):
    resp = await client.request(
        method,
        path,
        json=body,
        headers={**auth_header(tokens[role]), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error_code"] == "FORBIDDEN"


# ── PUT /screening-review/{item_key}: the proven exploit ────────────────────


async def _create_exporter(client: AsyncClient, token: str, **fields) -> str:
    resp = await client.post(
        f"{BASE}/exporters", json={"source": "SALES", **fields}, headers=auth_header(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["customer_id"]


async def test_api_user_cannot_pass_sanctions_check(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    customer_id = await _create_exporter(client, tokens[UserRole.COMPLIANCE])
    url = f"{BASE}/exporters/{customer_id}/screening-review/suspicious-bank-indicators"

    for role in (UserRole.API_USER, UserRole.DEVELOPER, UserRole.OPERATIONS):
        resp = await client.put(url, json={"status": "PASSED"}, headers=auth_header(tokens[role]))
        assert resp.status_code == 403, (role, resp.text)

    listing = await client.get(
        f"{BASE}/exporters/{customer_id}/screening-review",
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert listing.status_code == 200
    assert listing.json()["items"] == []


async def test_compliance_can_record_screening_decision_attributed_to_itself(
    client: AsyncClient,
):
    user_id, token = await user_with_role(client, UserRole.COMPLIANCE)
    customer_id = await _create_exporter(client, token)

    resp = await client.put(
        f"{BASE}/exporters/{customer_id}/screening-review/suspicious-bank-indicators",
        json={"status": "PASSED"},
        headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "PASSED"
    assert resp.json()["reviewed_by"] == user_id


async def test_operations_can_perform_routine_crm_writes(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    """Positive control: the STAFF gate admits OPERATIONS (Relationship Managers)."""
    token = tokens[UserRole.OPERATIONS]
    customer_id = await _create_exporter(client, token)

    contact = await client.post(
        f"{BASE}/exporters/{customer_id}/contacts", json={"name": "Jane"}, headers=auth_header(token)
    )
    assert contact.status_code == 201, contact.text
    activity = await client.post(
        f"{BASE}/exporters/{customer_id}/activities",
        json={"activity_type": "CALL", "subject": "Intro"},
        headers=auth_header(token),
    )
    assert activity.status_code == 201, activity.text


# ── Verification review attribution (FIX 3) ─────────────────────────────────


async def _trigger(client: AsyncClient, token: str) -> str:
    # A real company: a ghost subject is refused (404).
    customer_id = await _create_exporter(client, token)
    resp = await client.post(
        f"{BASE}/verifications", json=_trigger_body(customer_id), headers=auth_header(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_review_rejects_client_supplied_reviewed_by(client: AsyncClient):
    _, token = await user_with_role(client, UserRole.COMPLIANCE)
    result_id = await _trigger(client, token)

    resp = await client.post(
        f"{BASE}/verifications/{result_id}/review",
        json={"reviewed_by": "someone-else", "review_status": "ACCEPTED"},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text


async def test_review_is_attributed_to_authenticated_user(client: AsyncClient):
    user_id, token = await user_with_role(client, UserRole.COMPLIANCE)
    result_id = await _trigger(client, token)

    resp = await client.post(
        f"{BASE}/verifications/{result_id}/review",
        json={"review_status": "ACCEPTED"},
        headers=auth_header(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["reviewed_by"] == user_id
    assert resp.json()["review_status"] == "ACCEPTED"


# ── Provider allow-list (FIX 4) ──────────────────────────────────────────────


@pytest.mark.parametrize("provider", ["os", "app.shared.exceptions", "MANUAL", "", "rxil.evil"])
async def test_trigger_rejects_unknown_provider_at_schema(
    client: AsyncClient, tokens: dict[UserRole, str], provider: str
):
    resp = await client.post(
        f"{BASE}/verifications",
        json={**_trigger_body(), "provider": provider},
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert resp.status_code == 422, resp.text
    assert "provider" in resp.text


def test_schema_accepts_exactly_the_real_providers():
    from pydantic import ValidationError

    from app.modules.onboarding.api.schemas.verification import TriggerVerificationRequest

    base = {k: v for k, v in _trigger_body().items() if k != "provider"}
    assert TriggerVerificationRequest(**base).provider == "manual"
    assert TriggerVerificationRequest(**base, provider="manual").provider == "manual"
    # Decided 28 Sep 2026: the manual route is manual only; "rxil" is reserved
    # for the future RXIL intake path.
    for provider in ("rxil", "kyb"):
        with pytest.raises(ValidationError):
            TriggerVerificationRequest(**base, provider=provider)


# ── Server-side PAN/GSTIN/IEC masking (FIX 5) ────────────────────────────────

def _new_identifiers() -> tuple[str, str, str]:
    """A valid PAN, a GSTIN that carries it, and an IEC — fresh on every call.

    Since migration 0014 a PAN is format-checked and belongs to one company
    only, and a GSTIN must carry its company's PAN, so each company these
    tests create needs its own well-formed set."""
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    pan = f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"
    return pan, f"27{pan}1Z5", uuid.uuid4().hex[:10].upper()


# Unique per run so the search below never has to page past earlier runs' rows.
PAN, GSTIN, IEC = _new_identifiers()


def _set_relationship_manager_sync(customer_id: str, user_id: str) -> None:
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE onboarding.exporter_profile SET relationship_manager_user_id = %s "
                "WHERE customer_id = %s",
                (user_id, customer_id),
            )
            assert cur.rowcount == 1
        conn.commit()
    finally:
        conn.close()


def _masked(value: str) -> str:
    return "•" * (len(value) - 4) + value[-4:]


async def _identifiers_as(client: AsyncClient, token: str, customer_id: str) -> list[dict]:
    """The identifiers as seen on the detail route and in a search listing.

    The search leg deliberately does **not** filter by PAN. An exact identifier
    filter is for holders of the reveal permission only, so using one here would make this
    helper 403 for exactly the roles whose masking it exists to check. It pages
    through an unfiltered listing instead, which every reader may call.
    """
    detail = await client.get(f"{BASE}/exporters/{customer_id}", headers=auth_header(token))
    assert detail.status_code == 200, detail.text

    rows: list[dict] = []
    offset = 0
    while not rows:
        search = await client.get(
            f"{BASE}/exporters",
            params={"limit": 200, "offset": offset},
            headers=auth_header(token),
        )
        assert search.status_code == 200, search.text
        page = search.json()["profiles"]
        if not page:
            break
        rows = [p for p in page if p["customer_id"] == customer_id]
        offset += len(page)
    assert len(rows) == 1, f"{customer_id} not found in the listing"

    return [
        {k: body[k] for k in ("pan", "gstins", "iec")} for body in (detail.json(), rows[0])
    ]


@pytest.fixture(scope="module")
async def exporter_with_identifiers(
    client: AsyncClient, tokens: dict[UserRole, str]
) -> str:
    return await _create_exporter(
        client, tokens[UserRole.COMPLIANCE], pan=PAN, gstins=[GSTIN], iec=IEC
    )


@pytest.mark.parametrize("role", [UserRole.COMPLIANCE])
async def test_identifiers_unmasked_for_compliance(
    client: AsyncClient, tokens: dict[UserRole, str], exporter_with_identifiers: str, role: UserRole
):
    for seen in await _identifiers_as(client, tokens[role], exporter_with_identifiers):
        assert seen == {"pan": PAN, "gstins": [GSTIN], "iec": IEC}


@pytest.mark.parametrize("role", [UserRole.OPERATIONS, UserRole.DEVELOPER, UserRole.ADMIN])
async def test_identifiers_masked_for_operations_developer_and_admin(
    client: AsyncClient,
    tokens: dict[UserRole, str],
    exporter_with_identifiers: str,
    role: UserRole,
):
    """Neither role ever sees a raw identifier.

    OPERATIONS used to see its own exporters unmasked; architecture decision 12
    removed that ownership exception for the prototype, so sales staff and
    DEVELOPER are now treated the same here. (API_USER cannot read exporters at
    all — see the 403 cases above.)"""
    for seen in await _identifiers_as(client, tokens[role], exporter_with_identifiers):
        assert seen == {"pan": _masked(PAN), "gstins": [_masked(GSTIN)], "iec": _masked(IEC)}


async def test_identifiers_masked_even_for_the_owning_relationship_manager(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    """Previously `test_identifiers_unmasked_for_owning_relationship_manager`.

    Architecture decision 12 settles the prototype as COMPLIANCE only,
    with relationship-manager ownership deferred until afterwards. The test is
    inverted rather than deleted because the setup is the thing worth keeping:
    it is the only place that actually populates
    `exporter_profile.relationship_manager_user_id`, so it proves the reveal
    stays off even when that column is set — which is the case the old
    behaviour would have re-enabled silently.
    """
    rm_id, rm_token = await user_with_role(client, UserRole.OPERATIONS)
    pan, gstin, iec = _new_identifiers()
    customer_id = await _create_exporter(
        client, tokens[UserRole.COMPLIANCE], pan=pan, gstins=[gstin], iec=iec
    )

    _set_relationship_manager_sync(customer_id, rm_id)
    for seen in await _identifiers_as(client, rm_token, customer_id):
        assert seen == {"pan": _masked(pan), "gstins": [_masked(gstin)], "iec": _masked(iec)}

    # And an OPERATIONS user who is not the RM sees exactly the same thing.
    for seen in await _identifiers_as(client, tokens[UserRole.OPERATIONS], customer_id):
        assert seen["pan"] == _masked(pan)


# ── Identifier search is an existence oracle ─────────────────────────


@pytest.mark.parametrize("param", ["pan", "gstin", "iec"])
@pytest.mark.parametrize("role", [UserRole.OPERATIONS, UserRole.DEVELOPER, UserRole.ADMIN])
async def test_identifier_search_refused_for_roles_that_cannot_reveal(
    client: AsyncClient, tokens: dict[UserRole, str], role: UserRole, param: str
):
    """403, not an empty list.

    Masking the response body is not enough by itself: an exact match answers
    "which company holds this PAN" through whether a row comes back at all. An
    empty result would still answer it — with "none" — so the refusal is
    explicit and names the parameter.
    """
    value = {"pan": PAN, "gstin": GSTIN, "iec": IEC}[param]
    resp = await client.get(
        f"{BASE}/exporters", params={param: value}, headers=auth_header(tokens[role])
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error_code"] == "FORBIDDEN"
    assert param in resp.json()["detail"]


@pytest.mark.parametrize("role", [UserRole.COMPLIANCE])
async def test_identifier_search_allowed_for_compliance(
    client: AsyncClient,
    tokens: dict[UserRole, str],
    exporter_with_identifiers: str,
    role: UserRole,
):
    """The roles that may see a raw identifier may also search by one —
    otherwise the refusal above would have broken the feature for everyone."""
    resp = await client.get(
        f"{BASE}/exporters", params={"pan": PAN}, headers=auth_header(tokens[role])
    )
    assert resp.status_code == 200, resp.text
    found = [p for p in resp.json()["profiles"] if p["customer_id"] == exporter_with_identifiers]
    assert len(found) == 1
    assert found[0]["pan"] == PAN


@pytest.mark.parametrize("role", [UserRole.OPERATIONS, UserRole.DEVELOPER])
async def test_non_identifier_search_still_works_for_every_reader(
    client: AsyncClient, tokens: dict[UserRole, str], role: UserRole
):
    """The refusal is scoped to the three identifier filters. A reader that
    never touches them keeps full access to the listing."""
    resp = await client.get(
        f"{BASE}/exporters",
        params={"source": "SALES", "limit": 1},
        headers=auth_header(tokens[role]),
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("role", [UserRole.OPERATIONS, UserRole.DEVELOPER])
async def test_every_identifier_filter_is_named_when_several_are_used(
    client: AsyncClient, tokens: dict[UserRole, str], role: UserRole
):
    """A caller that sends two filters is told about both, so fixing the call
    does not take two round trips."""
    resp = await client.get(
        f"{BASE}/exporters",
        params={"pan": PAN, "iec": IEC},
        headers=auth_header(tokens[role]),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error_context"]["parameters"] == ["iec", "pan"]


async def test_write_responses_are_masked_too(client: AsyncClient, tokens: dict[UserRole, str]):
    """An OPERATIONS non-owner writing a PAN doesn't get it echoed back raw."""
    token = tokens[UserRole.OPERATIONS]
    pan, gstin, _iec = _new_identifiers()
    resp = await client.post(
        f"{BASE}/exporters", json={"source": "SALES", "pan": pan}, headers=auth_header(token)
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["pan"] == _masked(pan)

    # The same rule on the GST registrations route, which is where a GSTIN is written
    # now — a PATCH no longer accepts `gstins`.
    added = await client.post(
        f"{BASE}/exporters/{resp.json()['customer_id']}/gst-registrations",
        json={"gstin": gstin},
        headers=auth_header(token),
    )
    assert added.status_code == 201, added.text
    assert added.json()["gstin"] == _masked(gstin)
    # And the portal link is withheld, because it would carry the full value (3.17).
    assert added.json()["verify_url"] is None

    # The company response masks it too, wherever it appears.
    listed = await client.get(
        f"{BASE}/exporters/{resp.json()['customer_id']}", headers=auth_header(token)
    )
    assert listed.json()["gstins"] == [_masked(gstin)]


# ── Contact email/phone masking ──────────────────────────────────────────────

EMAIL = "jane.doe@acme-exports.example"
PHONE = "+919812345678"
MASKED_EMAIL = "j•••@acme-exports.example"


async def _contacts_as(client: AsyncClient, token: str, customer_id: str) -> list[dict]:
    """The contact as seen on the contacts route and inside the detail route."""
    listing = await client.get(
        f"{BASE}/exporters/{customer_id}/contacts", headers=auth_header(token)
    )
    assert listing.status_code == 200, listing.text
    detail = await client.get(f"{BASE}/exporters/{customer_id}", headers=auth_header(token))
    assert detail.status_code == 200, detail.text
    seen = listing.json()["contacts"] + detail.json()["contacts"]
    assert len(seen) == 2
    return [{"email": c["email"], "phone": c["phone"]} for c in seen]


async def _add_contact(client: AsyncClient, token: str, customer_id: str) -> dict:
    resp = await client.post(
        f"{BASE}/exporters/{customer_id}/contacts",
        json={"name": "Jane Doe", "email": EMAIL, "phone": PHONE},
        headers=auth_header(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture(scope="module")
async def exporter_with_contact(client: AsyncClient, tokens: dict[UserRole, str]) -> str:
    token = tokens[UserRole.COMPLIANCE]
    customer_id = await _create_exporter(client, token)
    await _add_contact(client, token, customer_id)
    return customer_id


@pytest.mark.parametrize("role", [UserRole.COMPLIANCE])
async def test_contacts_unmasked_for_compliance(
    client: AsyncClient, tokens: dict[UserRole, str], exporter_with_contact: str, role: UserRole
):
    for seen in await _contacts_as(client, tokens[role], exporter_with_contact):
        assert seen == {"email": EMAIL, "phone": PHONE}


@pytest.mark.parametrize("role", [UserRole.OPERATIONS, UserRole.ADMIN])
async def test_contacts_masked_for_non_owning_operations_and_admin(
    client: AsyncClient, tokens: dict[UserRole, str], exporter_with_contact: str, role: UserRole
):
    for seen in await _contacts_as(client, tokens[role], exporter_with_contact):
        assert seen == {"email": MASKED_EMAIL, "phone": _masked(PHONE)}


async def test_contacts_masked_even_for_the_owning_relationship_manager(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    """Previously `test_contacts_unmasked_for_owning_relationship_manager`.

    Contact email and phone follow the same reveal rule as the exporter's tax
    identifiers, so removing the ownership exception (decision 12) removes it
    here too. Kept with its RM setup for the same reason as the identifier
    twin above: it proves the reveal stays off with the column populated.
    """
    rm_id, rm_token = await user_with_role(client, UserRole.OPERATIONS)
    customer_id = await _create_exporter(client, tokens[UserRole.COMPLIANCE])
    _set_relationship_manager_sync(customer_id, rm_id)

    # The add-contact response follows the same rule as the reads.
    added = await _add_contact(client, rm_token, customer_id)
    assert (added["email"], added["phone"]) == (MASKED_EMAIL, _masked(PHONE))

    for seen in await _contacts_as(client, rm_token, customer_id):
        assert seen == {"email": MASKED_EMAIL, "phone": _masked(PHONE)}


async def test_add_contact_response_masked_for_non_owner(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    token = tokens[UserRole.OPERATIONS]
    customer_id = await _create_exporter(client, token)
    added = await _add_contact(client, token, customer_id)
    assert (added["email"], added["phone"]) == (MASKED_EMAIL, _masked(PHONE))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("a@b.co", "a•••@b.co"),
        ("jane@acme.com", "j•••@acme.com"),
        ("not-an-email", "••••••••mail"),
        ("@acme.com", "•••••.com"),
    ],
)
def test_mask_email_shapes(value: str | None, expected: str | None):
    from app.modules.onboarding.api.schemas.masking import mask_email

    assert mask_email(value) == expected


# ── The journey is never moved by hand ───────────────────────────────
#
# The ten-status lifecycle and its per-edge compliance gate are gone. The
# journey moves only through a qualification outcome (and, later, the
# background check), so no role can set it — not at creation, not by edit, and
# there is no route for it.


async def test_there_is_no_route_to_move_the_journey(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    customer_id = await _create_exporter(client, tokens[UserRole.COMPLIANCE])
    resp = await client.post(
        f"{BASE}/exporters/{customer_id}/transition",
        json={"to_status": "CUSTOMER"},
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert resp.status_code in (404, 405), resp.text


@pytest.mark.parametrize(
    "field, value", [("journey", "CUSTOMER"), ("lifecycle_status", "ONBOARDED")]
)
async def test_no_role_can_create_a_company_past_lead(
    client: AsyncClient, tokens: dict[UserRole, str], field: str, value: str
):
    resp = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", field: value},
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert resp.status_code == 422, resp.text


async def test_a_new_company_is_a_lead_not_yet_reviewed(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    resp = await client.post(
        f"{BASE}/exporters", json={"source": "SALES"},
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    body = resp.json()
    assert (body["journey"], body["qualification"], body["marker"]) == (
        "LEAD", "NOT_YET_REVIEWED", "NONE",
    )
    assert "lifecycle_status" not in body


# ── Allowed moves are served per viewer, not kept by the frontend ────────────


@pytest.mark.parametrize("role", [UserRole.OPERATIONS, UserRole.COMPLIANCE])
async def test_staff_are_served_the_marker_moves_they_may_make(
    client: AsyncClient, tokens: dict[UserRole, str], role: UserRole
):
    customer_id = await _create_exporter(client, tokens[UserRole.COMPLIANCE])
    detail = await client.get(
        f"{BASE}/exporters/{customer_id}", headers=auth_header(tokens[role])
    )
    assert detail.json()["allowed_marker_moves"] == [
        {"to": "PAUSED", "reason_required": True},
        {"to": "ENDED", "reason_required": True},
    ]


@pytest.mark.parametrize("role", [UserRole.DEVELOPER, UserRole.ADMIN])
async def test_a_reader_is_served_no_moves(
    client: AsyncClient, tokens: dict[UserRole, str], role: UserRole
):
    """DEVELOPER and the administrator read the company and may move none of it."""
    customer_id = await _create_exporter(client, tokens[UserRole.COMPLIANCE])
    token = tokens[role]
    detail = await client.get(f"{BASE}/exporters/{customer_id}", headers=auth_header(token))
    assert detail.json()["allowed_marker_moves"] == []
    qualification = await client.get(
        f"{BASE}/exporters/{customer_id}/qualification", headers=auth_header(token)
    )
    assert qualification.json()["allowed_outcomes"] == []
    assert qualification.json()["can_record_results"] is False


async def test_served_moves_follow_the_state(client: AsyncClient, tokens: dict[UserRole, str]):
    token = tokens[UserRole.OPERATIONS]
    customer_id = await _create_exporter(client, tokens[UserRole.COMPLIANCE])

    paused = await client.post(
        f"{BASE}/exporters/{customer_id}/marker",
        json={"marker": "PAUSED", "reason": "Seasonal"},
        headers=auth_header(token),
    )
    assert paused.json()["allowed_marker_moves"] == [
        {"to": "ENDED", "reason_required": True},
        {"to": "NONE", "reason_required": False},
    ]

    before = await client.get(
        f"{BASE}/exporters/{customer_id}/qualification", headers=auth_header(token)
    )
    assert set(before.json()["allowed_outcomes"]) == {"QUALIFIED", "NOT_QUALIFIED"}
    me = (await client.get("/api/v1/auth/me", headers=auth_header(token))).json()
    after = await client.post(
        f"{BASE}/exporters/{customer_id}/qualification/outcome",
        json={"outcome": "QUALIFIED", "relationship_manager_user_id": me["id"]},
        headers=auth_header(token),
    )
    assert after.json()["allowed_outcomes"] == []  # QUALIFIED is final
    assert after.json()["can_record_results"] is False


# ── Masked values cannot be written back ─────────────────────────────────────


async def test_masked_identifier_is_rejected_on_write(
    client: AsyncClient, tokens: dict[UserRole, str], exporter_with_identifiers: str
):
    """What a masked reader sees must not round-trip into the real column."""
    resp = await client.patch(
        f"{BASE}/exporters/{exporter_with_identifiers}",
        json={"pan": _masked(PAN)},
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert resp.status_code == 422, resp.text

    seen = await client.get(
        f"{BASE}/exporters/{exporter_with_identifiers}",
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert seen.json()["pan"] == PAN


async def test_masked_contact_email_is_rejected_on_write(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    token = tokens[UserRole.OPERATIONS]
    customer_id = await _create_exporter(client, token)
    resp = await client.post(
        f"{BASE}/exporters/{customer_id}/contacts",
        json={"name": "Jane", "email": MASKED_EMAIL},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text
