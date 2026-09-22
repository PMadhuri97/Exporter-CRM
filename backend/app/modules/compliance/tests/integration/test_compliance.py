"""
Compliance module integration tests.

Fixture strategy:
- compliance_users: two COMPLIANCE-role users (maker + checker).
- api_user_token: an API_USER token (used to verify role denial).
- Customers and transactions created via API or psycopg2 sync helpers.
- Each test that creates a transaction uses a fresh UUID idempotency key.
- The `screened_tx_id` fixture creates a clean transaction and runs screening
  so it is in UNDER_REVIEW — reused by all approval tests.
"""

import uuid

import pytest
from httpx import AsyncClient

# ── sync helpers ──────────────────────────────────────────────────────────────


def _pg_connect():
    import psycopg2

    from app.platform.configuration.config import get_settings

    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


def _create_customer_sync(
    *,
    entity_name: str,
    entity_type: str = "BUYER",
    kyb_status: str = "VERIFIED",
    risk_rating: str = "LOW",
    sector_classification: str | None = None,
) -> str:
    cid = str(uuid.uuid4())
    conn = _pg_connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO customers.customers
            (customer_id, entity_name, entity_type, kyb_status, risk_rating,
             sector_classification, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
        """,
        (cid, entity_name, entity_type, kyb_status, risk_rating, sector_classification),
    )
    conn.commit()
    cur.close()
    conn.close()
    return cid


# ── auth helpers ──────────────────────────────────────────────────────────────


async def _register_login(client: AsyncClient, role: str = "COMPLIANCE") -> tuple[str, str]:
    """Return (user_id, access_token)."""
    email = f"compliance-{uuid.uuid4().hex[:8]}@aner-test.com"
    reg = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Password1",
            "role": role,
        },
    )
    assert reg.status_code == 201
    user_id = reg.json()["id"]
    tok = await client.post("/api/v1/auth/login", json={"email": email, "password": "Password1"})
    assert tok.status_code == 200
    return user_id, tok.json()["access_token"]


def _payment_payload(sender_id: str, beneficiary_id: str) -> dict:
    return {
        "sender_id": sender_id,
        "beneficiary_id": beneficiary_id,
        "amount": "10000.00",
        "source_currency": "USD",
        "destination_currency": "INR",
        "purpose": "Trade Payment",
        "destination_bank": {
            "ifsc_code": "SBIN0001234",
            "account_number": "12345678901",
            "bank_name": "State Bank of India",
        },
        "preferred_route": "DIGITAL_ASSET_BRIDGE",
    }


async def _create_transaction(
    client: AsyncClient, token: str, sender_id: str, beneficiary_id: str
) -> str:
    """Create a payment transaction and return the transaction_id."""
    resp = await client.post(
        "/api/v1/payments",
        json=_payment_payload(sender_id, beneficiary_id),
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 202, f"Payment creation failed: {resp.text}"
    return resp.json()["transaction_id"]


# ── module-scoped fixtures ────────────────────────────────────────────────────


@pytest.fixture(scope="module")
async def compliance_users(client: AsyncClient) -> dict:
    """Two COMPLIANCE officers and one API_USER."""
    maker_id, maker_token = await _register_login(client, "COMPLIANCE")
    checker_id, checker_token = await _register_login(client, "COMPLIANCE")
    _, api_token = await _register_login(client, "API_USER")
    return {
        "maker_id": maker_id,
        "maker_token": maker_token,
        "checker_id": checker_id,
        "checker_token": checker_token,
        "api_token": api_token,
    }


@pytest.fixture(scope="module")
def clean_customers() -> dict:
    """Sender + beneficiary, both KYB VERIFIED, no sanctions risk."""
    sender_id = _create_customer_sync(entity_name="Clean Sender Corp", entity_type="BUYER")
    bene_id = _create_customer_sync(entity_name="Clean Beneficiary Corp", entity_type="SUPPLIER")
    return {"sender_id": sender_id, "beneficiary_id": bene_id}


@pytest.fixture(scope="module")
def pending_kyb_customer() -> str:
    return _create_customer_sync(
        entity_name="Pending KYB Corp", entity_type="BUYER", kyb_status="PENDING"
    )


@pytest.fixture(scope="module")
def sanctioned_customer() -> str:
    # Name matches SANCTIONED_NAMES_OFAC in screening.py
    return _create_customer_sync(entity_name="Terror Finance LLC", entity_type="SUPPLIER")


@pytest.fixture(scope="module")
def dnfbp_customer() -> str:
    return _create_customer_sync(
        entity_name="Diamond Trade House",
        entity_type="BUYER",
        sector_classification="PRECIOUS_STONES_TRADE",
    )


@pytest.fixture(scope="module")
def high_risk_customer() -> str:
    return _create_customer_sync(
        entity_name="High Risk Entity Ltd",
        entity_type="BUYER",
        risk_rating="HIGH",
    )


@pytest.fixture(scope="module")
async def screened_tx_id(client: AsyncClient, compliance_users: dict, clean_customers: dict) -> str:
    """
    A transaction that has already passed screening (status = UNDER_REVIEW).
    Reused by all maker-checker approval tests.
    """
    tx_id = await _create_transaction(
        client,
        compliance_users["maker_token"],
        clean_customers["sender_id"],
        clean_customers["beneficiary_id"],
    )
    resp = await client.post(
        f"/api/v1/compliance/screen/{tx_id}",
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["transaction_status"] == "UNDER_REVIEW"
    return tx_id


# ── POST /compliance/screen/{transaction_id} ──────────────────────────────────


@pytest.mark.asyncio
async def test_screen_missing_auth(client: AsyncClient):
    resp = await client.post(f"/api/v1/compliance/screen/{uuid.uuid4()}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_screen_wrong_role_denied(client: AsyncClient, compliance_users: dict):
    resp = await client.post(
        f"/api/v1/compliance/screen/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {compliance_users['api_token']}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_screen_transaction_not_found(client: AsyncClient, compliance_users: dict):
    resp = await client.post(
        f"/api/v1/compliance/screen/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_screen_kyb_fails_sender(
    client: AsyncClient, compliance_users: dict, pending_kyb_customer: str, clean_customers: dict
):
    tx_id = await _create_transaction(
        client,
        compliance_users["maker_token"],
        pending_kyb_customer,
        clean_customers["beneficiary_id"],
    )
    resp = await client.post(
        f"/api/v1/compliance/screen/{tx_id}",
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["transaction_status"] == "VALIDATION_FAILED"
    assert body["screenings"] == []
    assert body["edd_required"] is False


@pytest.mark.asyncio
async def test_screen_kyb_fails_beneficiary(
    client: AsyncClient, compliance_users: dict, clean_customers: dict, pending_kyb_customer: str
):
    tx_id = await _create_transaction(
        client,
        compliance_users["maker_token"],
        clean_customers["sender_id"],
        pending_kyb_customer,
    )
    resp = await client.post(
        f"/api/v1/compliance/screen/{tx_id}",
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["transaction_status"] == "VALIDATION_FAILED"


@pytest.mark.asyncio
async def test_screen_sanctions_hit_blocks_transaction(
    client: AsyncClient, compliance_users: dict, clean_customers: dict, sanctioned_customer: str
):
    tx_id = await _create_transaction(
        client,
        compliance_users["maker_token"],
        clean_customers["sender_id"],
        sanctioned_customer,
    )
    resp = await client.post(
        f"/api/v1/compliance/screen/{tx_id}",
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["transaction_status"] == "BLOCKED"
    failed = [s for s in body["screenings"] if s["status"] == "FAIL"]
    assert len(failed) >= 1
    assert any(s["screening_type"] == "SANCTIONS_OFAC" for s in failed)


@pytest.mark.asyncio
async def test_screen_dnfbp_triggers_edd(
    client: AsyncClient, compliance_users: dict, dnfbp_customer: str, clean_customers: dict
):
    tx_id = await _create_transaction(
        client,
        compliance_users["maker_token"],
        dnfbp_customer,
        clean_customers["beneficiary_id"],
    )
    resp = await client.post(
        f"/api/v1/compliance/screen/{tx_id}",
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["transaction_status"] == "UNDER_REVIEW"
    assert body["edd_required"] is True
    dnfbp_screens = [s for s in body["screenings"] if s["screening_type"] == "DNFBP"]
    assert len(dnfbp_screens) >= 1
    assert dnfbp_screens[0]["status"] == "MANUAL_REVIEW"


@pytest.mark.asyncio
async def test_screen_high_risk_triggers_aml_manual_review(
    client: AsyncClient, compliance_users: dict, high_risk_customer: str, clean_customers: dict
):
    tx_id = await _create_transaction(
        client,
        compliance_users["maker_token"],
        high_risk_customer,
        clean_customers["beneficiary_id"],
    )
    resp = await client.post(
        f"/api/v1/compliance/screen/{tx_id}",
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["transaction_status"] == "UNDER_REVIEW"
    aml = [s for s in body["screenings"] if s["screening_type"] == "AML_RISK"]
    assert len(aml) == 1
    assert aml[0]["status"] == "MANUAL_REVIEW"


@pytest.mark.asyncio
async def test_screen_clean_transaction_moves_to_under_review(
    client: AsyncClient, compliance_users: dict, clean_customers: dict
):
    tx_id = await _create_transaction(
        client,
        compliance_users["maker_token"],
        clean_customers["sender_id"],
        clean_customers["beneficiary_id"],
    )
    resp = await client.post(
        f"/api/v1/compliance/screen/{tx_id}",
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["transaction_status"] == "UNDER_REVIEW"
    assert body["edd_required"] is False
    # Should have 8 sanctions screenings (4 types × 2 entities) + 1 AML
    assert len(body["screenings"]) == 9
    assert all(
        s["status"] == "PASS" for s in body["screenings"] if s["screening_type"] != "AML_RISK"
    )


@pytest.mark.asyncio
async def test_screen_already_screened_returns_409(
    client: AsyncClient, compliance_users: dict, screened_tx_id: str
):
    # screened_tx_id is already UNDER_REVIEW
    resp = await client.post(
        f"/api/v1/compliance/screen/{screened_tx_id}",
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "ALREADY_SCREENED"


# ── GET /compliance/screenings/{transaction_id} ───────────────────────────────


@pytest.mark.asyncio
async def test_get_screenings_not_found(client: AsyncClient, compliance_users: dict):
    resp = await client.get(
        f"/api/v1/compliance/screenings/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_screenings_success(
    client: AsyncClient, compliance_users: dict, screened_tx_id: str
):
    resp = await client.get(
        f"/api/v1/compliance/screenings/{screened_tx_id}",
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["transaction_status"] == "UNDER_REVIEW"
    assert len(body["screenings"]) > 0
    for s in body["screenings"]:
        assert "screening_id" in s
        assert "screening_type" in s
        assert "status" in s
        assert "created_at" in s


# ── POST /compliance/approvals ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approval_missing_auth(client: AsyncClient, screened_tx_id: str):
    resp = await client.post(
        "/api/v1/compliance/approvals",
        json={"transaction_id": screened_tx_id, "decision": "APPROVED"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_approval_wrong_role_denied(
    client: AsyncClient, compliance_users: dict, screened_tx_id: str
):
    resp = await client.post(
        "/api/v1/compliance/approvals",
        json={"transaction_id": screened_tx_id, "decision": "APPROVED"},
        headers={"Authorization": f"Bearer {compliance_users['api_token']}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_approval_transaction_not_found(client: AsyncClient, compliance_users: dict):
    resp = await client.post(
        "/api/v1/compliance/approvals",
        json={"transaction_id": str(uuid.uuid4()), "decision": "APPROVED"},
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_approval_transaction_not_under_review(
    client: AsyncClient, compliance_users: dict, clean_customers: dict
):
    # A fresh INITIATED transaction — not yet screened
    tx_id = await _create_transaction(
        client,
        compliance_users["maker_token"],
        clean_customers["sender_id"],
        clean_customers["beneficiary_id"],
    )
    resp = await client.post(
        "/api/v1/compliance/approvals",
        json={"transaction_id": tx_id, "decision": "APPROVED"},
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "INVALID_STATUS"


@pytest.mark.asyncio
async def test_full_maker_checker_approval_flow(
    client: AsyncClient, compliance_users: dict, clean_customers: dict
):
    """End-to-end: screen → maker approves → checker approves → APPROVED."""
    tx_id = await _create_transaction(
        client,
        compliance_users["maker_token"],
        clean_customers["sender_id"],
        clean_customers["beneficiary_id"],
    )
    screen = await client.post(
        f"/api/v1/compliance/screen/{tx_id}",
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert screen.json()["transaction_status"] == "UNDER_REVIEW"

    # MAKER approval
    maker_resp = await client.post(
        "/api/v1/compliance/approvals",
        json={"transaction_id": tx_id, "decision": "APPROVED", "notes": "Profile reviewed."},
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert maker_resp.status_code == 200
    body = maker_resp.json()
    assert body["approver_role"] == "MAKER"
    assert body["decision"] == "APPROVED"

    # Transaction should still be UNDER_REVIEW (waiting for checker)
    state = await client.get(
        f"/api/v1/compliance/approvals/{tx_id}",
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert state.json()["transaction_status"] == "UNDER_REVIEW"

    # CHECKER approval (different user)
    checker_resp = await client.post(
        "/api/v1/compliance/approvals",
        json={"transaction_id": tx_id, "decision": "APPROVED", "notes": "Second review done."},
        headers={"Authorization": f"Bearer {compliance_users['checker_token']}"},
    )
    assert checker_resp.status_code == 200
    body = checker_resp.json()
    assert body["approver_role"] == "CHECKER"
    assert body["decision"] == "APPROVED"

    # Transaction should now be APPROVED
    final = await client.get(
        f"/api/v1/compliance/approvals/{tx_id}",
        headers={"Authorization": f"Bearer {compliance_users['checker_token']}"},
    )
    assert final.json()["transaction_status"] == "APPROVED"
    assert len(final.json()["approvals"]) == 2


@pytest.mark.asyncio
async def test_same_user_both_roles_rejected(
    client: AsyncClient, compliance_users: dict, clean_customers: dict
):
    """Same compliance officer cannot be both MAKER and CHECKER."""
    tx_id = await _create_transaction(
        client,
        compliance_users["maker_token"],
        clean_customers["sender_id"],
        clean_customers["beneficiary_id"],
    )
    await client.post(
        f"/api/v1/compliance/screen/{tx_id}",
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    # MAKER
    await client.post(
        "/api/v1/compliance/approvals",
        json={"transaction_id": tx_id, "decision": "APPROVED"},
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    # Same user tries to be CHECKER
    resp = await client.post(
        "/api/v1/compliance/approvals",
        json={"transaction_id": tx_id, "decision": "APPROVED"},
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "DUPLICATE_APPROVER"


@pytest.mark.asyncio
async def test_maker_rejection_declines_transaction(
    client: AsyncClient, compliance_users: dict, clean_customers: dict
):
    tx_id = await _create_transaction(
        client,
        compliance_users["maker_token"],
        clean_customers["sender_id"],
        clean_customers["beneficiary_id"],
    )
    await client.post(
        f"/api/v1/compliance/screen/{tx_id}",
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    resp = await client.post(
        "/api/v1/compliance/approvals",
        json={"transaction_id": tx_id, "decision": "REJECTED", "notes": "AML concerns."},
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["decision"] == "REJECTED"

    state = await client.get(
        f"/api/v1/compliance/approvals/{tx_id}",
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert state.json()["transaction_status"] == "DECLINED"


@pytest.mark.asyncio
async def test_checker_rejection_declines_transaction(
    client: AsyncClient, compliance_users: dict, clean_customers: dict
):
    tx_id = await _create_transaction(
        client,
        compliance_users["maker_token"],
        clean_customers["sender_id"],
        clean_customers["beneficiary_id"],
    )
    await client.post(
        f"/api/v1/compliance/screen/{tx_id}",
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    await client.post(
        "/api/v1/compliance/approvals",
        json={"transaction_id": tx_id, "decision": "APPROVED"},
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    resp = await client.post(
        "/api/v1/compliance/approvals",
        json={"transaction_id": tx_id, "decision": "REJECTED", "notes": "Escalation required."},
        headers={"Authorization": f"Bearer {compliance_users['checker_token']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["decision"] == "REJECTED"
    assert resp.json()["approver_role"] == "CHECKER"

    state = await client.get(
        f"/api/v1/compliance/approvals/{tx_id}",
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert state.json()["transaction_status"] == "DECLINED"


@pytest.mark.asyncio
async def test_approval_after_complete_returns_409(
    client: AsyncClient, compliance_users: dict, clean_customers: dict
):
    """After both approvals exist, a third submission is rejected."""
    tx_id = await _create_transaction(
        client,
        compliance_users["maker_token"],
        clean_customers["sender_id"],
        clean_customers["beneficiary_id"],
    )
    await client.post(
        f"/api/v1/compliance/screen/{tx_id}",
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    await client.post(
        "/api/v1/compliance/approvals",
        json={"transaction_id": tx_id, "decision": "APPROVED"},
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    await client.post(
        "/api/v1/compliance/approvals",
        json={"transaction_id": tx_id, "decision": "APPROVED"},
        headers={"Authorization": f"Bearer {compliance_users['checker_token']}"},
    )
    # Third submission — transaction is now APPROVED, not UNDER_REVIEW
    resp = await client.post(
        "/api/v1/compliance/approvals",
        json={"transaction_id": tx_id, "decision": "APPROVED"},
        headers={"Authorization": f"Bearer {compliance_users['checker_token']}"},
    )
    # Transaction is APPROVED now, so INVALID_STATUS (422) fires before APPROVAL_ALREADY_COMPLETE
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "INVALID_STATUS"


# ── GET /compliance/approvals/{transaction_id} ────────────────────────────────


@pytest.mark.asyncio
async def test_get_approvals_not_found(client: AsyncClient, compliance_users: dict):
    resp = await client.get(
        f"/api/v1/compliance/approvals/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {compliance_users['maker_token']}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_approvals_missing_auth(client: AsyncClient, screened_tx_id: str):
    resp = await client.get(f"/api/v1/compliance/approvals/{screened_tx_id}")
    assert resp.status_code == 401
