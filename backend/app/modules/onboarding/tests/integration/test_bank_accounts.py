"""A company's bank accounts, over HTTP.

The walk-through: an RM proposes an EEFC account ("Pending approval"); a second person
approves it ("Pending verification"); compliance attaches a cancelled cheque and
verifies it ("Verified"). The RM never sees the full number, each step is in History
and the audit trail, and the number is stored encrypted.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import psycopg2
import psycopg2.extras
import pytest
from httpx import AsyncClient

from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"
PDF = b"%PDF-1.4 cancelled cheque"
NUMBER = "50200012345678"

EEFC = {
    "account_holder_name": "Acme Exports Pvt Ltd",
    "bank_name": "HDFC Bank",
    "branch": "Fort, Mumbai",
    "account_number": "5020 0012 3456 78",
    "ifsc": "hdfc0000060",
    "swift_bic": "HDFCINBB",
    "currency": "usd",
    "account_type": "EEFC",
    "ad_code": "0510002",
    "reason": "New USD receivables account",
}


@pytest.fixture(autouse=True)
def _isolated_storage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORAGE_LOCAL_ROOT", str(tmp_path / "storage"))


def _connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


async def _people(client: AsyncClient) -> dict[str, tuple[str, str]]:
    return {
        "rm": await user_with_role(client, UserRole.OPERATIONS),
        "rm2": await user_with_role(client, UserRole.OPERATIONS),
        "compliance": await user_with_role(client, UserRole.COMPLIANCE),
        "admin": await user_with_role(client, UserRole.ADMIN),
    }


async def _propose(client, token, customer_id, **overrides) -> dict:
    resp = await client.post(
        f"{BASE}/exporters/{customer_id}/bank-accounts",
        headers=auth_header(token),
        json={**EEFC, **overrides},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _post(client, token, path, json=None):
    return await client.post(f"{BASE}{path}", headers=auth_header(token), json=json)


async def _cheque(client, token, customer_id) -> str:
    uploaded = await client.post(
        f"{BASE}/exporters/{customer_id}/documents",
        data={"category": "OTHER", "document_type": "other"},
        files={"file": ("cheque.pdf", PDF, "application/pdf")},
        headers=auth_header(token),
    )
    assert uploaded.status_code == 201, uploaded.text
    return uploaded.json()["id"]


async def _verified(client, people, customer_id, **overrides) -> dict:
    _, rm = people["rm"]
    _, compliance = people["compliance"]
    account = await _propose(client, rm, customer_id, **overrides)
    assert (await _post(client, compliance, f"/bank-accounts/{account['id']}/approve")).status_code == 200
    resp = await _post(
        client, compliance, f"/bank-accounts/{account['id']}/verify",
        {"method": "CANCELLED_CHEQUE", "evidence_document_id": await _cheque(client, rm, customer_id)},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _events(account_id: str) -> list[str]:
    from app.modules.audit import AuditService

    async with db_services.AsyncSessionLocal() as db:
        page = await AuditService(db).list_for_subject("bank_account", uuid.UUID(account_id))
    return sorted(e.event_type for e in page.events)


async def test_the_walk_through_from_proposal_to_verified(client: AsyncClient):
    people = await _people(client)
    _, rm = people["rm"]
    _, compliance = people["compliance"]
    customer_id = await make_company()

    proposed = await _propose(client, rm, customer_id)
    assert proposed["status"] == "PENDING_APPROVAL"
    assert proposed["account_number_masked"] == "••••5678"
    assert proposed["ifsc"] == "HDFC0000060"
    assert proposed["currency"] == "USD"
    assert NUMBER not in str(proposed)

    approved = await _post(client, compliance, f"/bank-accounts/{proposed['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "PENDING_VERIFICATION"

    verified = await _post(
        client, compliance, f"/bank-accounts/{proposed['id']}/verify",
        {"method": "CANCELLED_CHEQUE", "evidence_document_id": await _cheque(client, rm, customer_id)},
    )
    assert verified.status_code == 200, verified.text
    body = verified.json()
    assert body["status"] == "VERIFIED"
    assert body["is_primary"] is True, "the first verified USD account is the USD primary"
    assert body["verification_method"] == "CANCELLED_CHEQUE"

    history = await client.get(
        f"{BASE}/exporters/{customer_id}/history",
        headers=auth_header(rm),
        params={"dimension": "bank_account"},
    )
    assert sorted(e["event_type"] for e in history.json()["entries"]) == [
        "bank_account_approved", "bank_account_proposed", "bank_account_verified",
    ]
    assert NUMBER not in history.text
    assert await _events(proposed["id"]) == [
        "crm.bank_account.approved", "crm.bank_account.proposed", "crm.bank_account.verified",
    ]


async def test_the_rm_never_sees_the_full_number_and_compliance_reveals_it_audited(
    client: AsyncClient,
):
    people = await _people(client)
    _, rm = people["rm"]
    _, compliance = people["compliance"]
    customer_id = await make_company()
    account = await _propose(client, rm, customer_id)

    listed = await client.get(f"{BASE}/exporters/{customer_id}/bank-accounts", headers=auth_header(rm))
    assert NUMBER not in listed.text
    assert listed.json()["capabilities"] == {
        "can_propose": True, "can_approve": False, "can_reveal": False,
    }
    refused = await _post(client, rm, f"/bank-accounts/{account['id']}/reveal")
    assert refused.status_code == 403, refused.text

    revealed = await _post(client, compliance, f"/bank-accounts/{account['id']}/reveal")
    assert revealed.status_code == 200, revealed.text
    assert revealed.json()["account_number"] == NUMBER
    assert "crm.bank_account.revealed" in await _events(account["id"])


async def test_the_number_is_stored_encrypted(client: AsyncClient):
    people = await _people(client)
    customer_id = await make_company()
    account = await _propose(client, people["rm"][1], customer_id)

    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT account_number_encrypted, account_number_last4 "
                "FROM onboarding.company_bank_account WHERE id = %s",
                (account["id"],),
            )
            stored, last4 = cursor.fetchone()
    finally:
        conn.close()
    assert NUMBER not in stored
    assert stored.startswith("v1.")
    assert last4 == "5678"


async def test_under_second_person_the_proposer_may_not_approve_but_another_rm_may(
    client: AsyncClient,
):
    people = await _people(client)
    _, rm = people["rm"]
    _, rm2 = people["rm2"]
    customer_id = await make_company()
    account = await _propose(client, rm, customer_id)

    own = await _post(client, rm, f"/bank-accounts/{account['id']}/approve")
    assert own.status_code == 403, own.text
    assert own.json()["error_code"] == "BANK_ACCOUNT_APPROVAL_REFUSED"

    queue = await client.get(f"{BASE}/bank-accounts/pending", headers=auth_header(rm2))
    row = next(a for a in queue.json()["accounts"] if a["id"] == account["id"])
    assert row["can_approve"] is True

    other = await _post(client, rm2, f"/bank-accounts/{account['id']}/approve")
    assert other.status_code == 200, other.text


async def test_an_rm_cannot_verify_and_an_unverified_account_cannot_be_primary(
    client: AsyncClient,
):
    people = await _people(client)
    _, rm = people["rm"]
    _, compliance = people["compliance"]
    customer_id = await make_company()
    account = await _propose(client, rm, customer_id)
    await _post(client, compliance, f"/bank-accounts/{account['id']}/approve")

    verify = await _post(
        client, rm, f"/bank-accounts/{account['id']}/verify",
        {"method": "CANCELLED_CHEQUE", "evidence_document_id": await _cheque(client, rm, customer_id)},
    )
    assert verify.status_code == 403, verify.text
    primary = await _post(client, compliance, f"/bank-accounts/{account['id']}/primary")
    assert primary.status_code == 409, primary.text
    assert primary.json()["error_code"] == "BANK_ACCOUNT_WRONG_STATUS"


async def test_the_admin_reads_the_accounts_but_may_not_propose_or_approve(client: AsyncClient):
    people = await _people(client)
    _, admin = people["admin"]
    customer_id = await make_company()
    account = await _propose(client, people["rm"][1], customer_id)

    listed = await client.get(f"{BASE}/exporters/{customer_id}/bank-accounts", headers=auth_header(admin))
    assert listed.status_code == 200
    assert (await _post(client, admin, f"/bank-accounts/{account['id']}/approve")).status_code == 403
    refused = await client.post(
        f"{BASE}/exporters/{customer_id}/bank-accounts", headers=auth_header(admin), json=EEFC
    )
    assert refused.status_code == 403


async def test_a_change_keeps_the_old_account_in_force_until_it_is_verified(client: AsyncClient):
    people = await _people(client)
    _, rm = people["rm"]
    _, compliance = people["compliance"]
    customer_id = await make_company()
    old = await _verified(client, people, customer_id)

    change = await _propose(
        client, rm, customer_id, account_number="50200099998888", replaces_id=old["id"],
        reason="Account moved to the new branch",
    )
    accounts = {
        a["id"]: a
        for a in (await client.get(
            f"{BASE}/exporters/{customer_id}/bank-accounts", headers=auth_header(rm)
        )).json()["accounts"]
    }
    assert (accounts[old["id"]]["status"], accounts[old["id"]]["is_primary"]) == ("VERIFIED", True)
    assert accounts[change["id"]]["replaces_id"] == old["id"]

    second = await client.post(
        f"{BASE}/exporters/{customer_id}/bank-accounts",
        headers=auth_header(rm),
        json={**EEFC, "replaces_id": old["id"]},
    )
    assert second.status_code == 422, "one waiting change per account"

    await _post(client, compliance, f"/bank-accounts/{change['id']}/approve")
    verified = await _post(
        client, compliance, f"/bank-accounts/{change['id']}/verify",
        {"method": "BANK_LETTER", "evidence_document_id": await _cheque(client, rm, customer_id)},
    )
    assert verified.json()["is_primary"] is True
    accounts = {
        a["id"]: a
        for a in (await client.get(
            f"{BASE}/exporters/{customer_id}/bank-accounts", headers=auth_header(rm)
        )).json()["accounts"]
    }
    assert (accounts[old["id"]]["status"], accounts[old["id"]]["is_primary"]) == ("INACTIVE", False)


async def test_a_rejection_needs_a_reason_and_ends_the_proposal(client: AsyncClient):
    people = await _people(client)
    _, compliance = people["compliance"]
    customer_id = await make_company()
    account = await _propose(client, people["rm"][1], customer_id)

    assert (await _post(client, compliance, f"/bank-accounts/{account['id']}/reject", {"reason": " "})).status_code == 422
    rejected = await _post(
        client, compliance, f"/bank-accounts/{account['id']}/reject",
        {"reason": "The name does not match the company"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "REJECTED"
    again = await _post(client, compliance, f"/bank-accounts/{account['id']}/approve")
    assert again.status_code == 409


async def test_a_passed_bank_account_verification_verifies_by_penny_drop(client: AsyncClient):
    people = await _people(client)
    _, compliance = people["compliance"]
    customer_id = await make_company()
    account = await _propose(client, people["rm"][1], customer_id)
    await _post(client, compliance, f"/bank-accounts/{account['id']}/approve")

    def insert(status: str) -> str:
        result_id = uuid.uuid4()
        conn = _connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO onboarding.verification_result "
                    "(id, verification_type, entity_type, entity_reference, provider, status, "
                    " performed_at, raw_result, normalized_result) "
                    "VALUES (%s, 'BANK_ACCOUNT', 'EXPORTER', %s, 'manual', %s, now(), %s, %s)",
                    (str(result_id), str(customer_id), status,
                     psycopg2.extras.Json({}), psycopg2.extras.Json({})),
                )
            conn.commit()
        finally:
            conn.close()
        return str(result_id)

    failed = await _post(
        client, compliance, f"/bank-accounts/{account['id']}/verify",
        {"method": "PENNY_DROP", "verification_result_id": insert("FAILED")},
    )
    assert failed.status_code == 422, failed.text
    passed = await _post(
        client, compliance, f"/bank-accounts/{account['id']}/verify",
        {"method": "PENNY_DROP", "verification_result_id": insert("PASSED")},
    )
    assert passed.status_code == 200, passed.text
    assert passed.json()["verification_method"] == "PENNY_DROP"


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"account_number": None}, id="no-number-or-iban"),
        pytest.param({"ifsc": "HDFC123"}, id="bad-ifsc"),
        pytest.param({"currency": "US1"}, id="bad-currency"),
        pytest.param({"ifsc": None, "swift_bic": None}, id="number-without-bank-code"),
    ],
)
async def test_a_proposal_with_bad_details_is_refused(client: AsyncClient, overrides: dict):
    people = await _people(client)
    customer_id = await make_company()
    resp = await client.post(
        f"{BASE}/exporters/{customer_id}/bank-accounts",
        headers=auth_header(people["rm"][1]),
        json={**EEFC, **overrides},
    )
    assert resp.status_code == 422, resp.text


async def test_a_foreign_account_may_be_an_iban_alone(client: AsyncClient):
    people = await _people(client)
    customer_id = await make_company()
    account = await _propose(
        client, people["rm"][1], customer_id,
        account_number=None, ifsc=None, swift_bic="ABNANL2A",
        iban="NL91 ABNA 0417 1643 00", currency="EUR", account_type="CURRENT",
    )
    assert account["iban_masked"] == "••••4300"
    assert account["account_number_masked"] is None


def test_the_database_refuses_a_primary_that_is_not_verified():
    customer_id = uuid.uuid4()
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            from app.modules.onboarding.tests.fixtures.companies import insert_company

            insert_company(cursor, customer_id)
            with pytest.raises(psycopg2.errors.CheckViolation):
                cursor.execute(
                    "INSERT INTO onboarding.company_bank_account "
                    "(id, customer_id, account_holder_name, bank_name, account_number_encrypted, "
                    " currency, account_type, is_primary, status) "
                    "VALUES (%s, %s, 'x', 'y', 'v1.k.z', 'INR', 'CURRENT', true, 'PENDING_APPROVAL')",
                    (str(uuid.uuid4()), str(customer_id)),
                )
    finally:
        conn.rollback()
        conn.close()
