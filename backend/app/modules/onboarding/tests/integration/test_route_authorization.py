"""Role gates on the onboarding / exporter-CRM routes, reviewer attribution on
verification reviews, the provider allow-list, and server-side masking of
PAN/GSTIN/IEC and contact email/phone.

Every gated route gets a negative test per refused role asserting 403 — the
gate runs as a dependency, so a 403 also proves the handler never ran.
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

STAFF = {UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN}
COMPLIANCE_OR_ADMIN = {UserRole.COMPLIANCE, UserRole.ADMIN}
# Masked exporter-CRM reads: DEVELOPER may read, never unmasked.
READERS = STAFF | {UserRole.DEVELOPER}


def _case_body() -> dict:
    return {
        "tenant_id": str(uuid.uuid4()),
        "country_code": "IN",
        "case_type": "KYC",
        "subject_type": "INDIVIDUAL",
        "required_checks": ["IDENTITY"],
        "profile": {"first_name": "Meera", "last_name": "Iyer"},
    }


def _trigger_body() -> dict:
    return {
        # KYB, not KYC: KYC is a check on a person, and the service rejects a
        # KYC/EXPORTER pair (422) before the route gate under test matters.
        "verification_type": "KYB",
        "entity_type": "EXPORTER",
        "entity_reference": str(uuid.uuid4()),
        "provider": "manual",
        "payload": {"status": "PASSED"},
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
        COMPLIANCE_OR_ADMIN,
    ),
    # onboarding foundation
    ("POST", f"{BASE}/register", {"email": "x@example.com", "full_name": "X"}, STAFF),
    # verifications
    ("POST", f"{BASE}/verifications", _trigger_body(), COMPLIANCE_OR_ADMIN),
    (
        "POST",
        f"{BASE}/verifications/{_ID}/review",
        {"review_status": "ACCEPTED"},
        COMPLIANCE_OR_ADMIN,
    ),
    # exporter CRM
    ("POST", f"{BASE}/exporters", {"source": "SALES"}, STAFF),
    ("PATCH", f"{BASE}/exporters/{_ID}", {"industry": "Textiles"}, STAFF),
    (
        "POST",
        f"{BASE}/exporters/{_ID}/transition",
        {"to_status": "CONTACTED"},
        STAFF,
    ),
    ("POST", f"{BASE}/exporters/{_ID}/contacts", {"name": "Jane"}, STAFF),
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
        COMPLIANCE_OR_ADMIN,
    ),
    # ── reads ──
    ("GET", f"{BASE}/cases/{_ID}", None, STAFF),
    ("GET", f"{BASE}/cases/{_ID}/transitions", None, STAFF),
    ("GET", f"{BASE}/{_ID}/sdk-token", None, STAFF),
    ("GET", f"{BASE}/{_ID}/status", None, STAFF),
    ("GET", f"{BASE}/verifications/{_ID}", None, STAFF),
    ("GET", f"{BASE}/verifications?entity_type=EXPORTER&entity_reference={_ID}", None, STAFF),
    ("GET", f"{BASE}/exporters", None, READERS),
    ("GET", f"{BASE}/exporters/{_ID}", None, READERS),
    ("GET", f"{BASE}/exporters/{_ID}/contacts", None, READERS),
    ("GET", f"{BASE}/exporters/{_ID}/activities", None, READERS),
    ("GET", f"{BASE}/exporters/activities/pending", None, READERS),
    ("GET", f"{BASE}/exporters/{_ID}/screening-review", None, STAFF),
    ("GET", f"{BASE}/exporters/{_ID}/bank-activity", None, STAFF),
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
    resp = await client.post(f"{BASE}/verifications", json=_trigger_body(), headers=auth_header(token))
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
    for provider in ("manual", "rxil"):
        assert TriggerVerificationRequest(**base, provider=provider).provider == provider
    with pytest.raises(ValidationError):
        TriggerVerificationRequest(**base, provider="kyb")


# ── Server-side PAN/GSTIN/IEC masking (FIX 5) ────────────────────────────────

# Unique per run so the search below never has to page past earlier runs' rows.
_RUN = uuid.uuid4().hex.upper()
PAN = _RUN[:10]
GSTIN = _RUN[10:25]
IEC = _RUN[20:30]


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
    """The identifiers as seen on the detail route and the search route."""
    detail = await client.get(f"{BASE}/exporters/{customer_id}", headers=auth_header(token))
    assert detail.status_code == 200, detail.text
    search = await client.get(f"{BASE}/exporters", params={"pan": PAN}, headers=auth_header(token))
    assert search.status_code == 200, search.text
    rows = [p for p in search.json()["profiles"] if p["customer_id"] == customer_id]
    assert len(rows) == 1
    return [
        {k: body[k] for k in ("pan", "gstin", "iec")} for body in (detail.json(), rows[0])
    ]


@pytest.fixture(scope="module")
async def exporter_with_identifiers(
    client: AsyncClient, tokens: dict[UserRole, str]
) -> str:
    return await _create_exporter(
        client, tokens[UserRole.COMPLIANCE], pan=PAN, gstin=GSTIN, iec=IEC
    )


@pytest.mark.parametrize("role", [UserRole.COMPLIANCE, UserRole.ADMIN])
async def test_identifiers_unmasked_for_compliance_and_admin(
    client: AsyncClient, tokens: dict[UserRole, str], exporter_with_identifiers: str, role: UserRole
):
    for seen in await _identifiers_as(client, tokens[role], exporter_with_identifiers):
        assert seen == {"pan": PAN, "gstin": GSTIN, "iec": IEC}


@pytest.mark.parametrize("role", [UserRole.OPERATIONS, UserRole.DEVELOPER])
async def test_identifiers_masked_for_non_owning_operations_and_developer(
    client: AsyncClient,
    tokens: dict[UserRole, str],
    exporter_with_identifiers: str,
    role: UserRole,
):
    """OPERATIONS reads every exporter, but only its own unmasked; DEVELOPER
    reads every exporter and never unmasked. (API_USER can't read exporters at
    all — see the 403 cases above.)"""
    for seen in await _identifiers_as(client, tokens[role], exporter_with_identifiers):
        assert seen == {"pan": _masked(PAN), "gstin": _masked(GSTIN), "iec": _masked(IEC)}


async def test_identifiers_unmasked_for_owning_relationship_manager(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    rm_id, rm_token = await user_with_role(client, UserRole.OPERATIONS)
    customer_id = await _create_exporter(
        client, tokens[UserRole.COMPLIANCE], pan=PAN, gstin=GSTIN, iec=IEC
    )

    _set_relationship_manager_sync(customer_id, rm_id)
    for seen in await _identifiers_as(client, rm_token, customer_id):
        assert seen == {"pan": PAN, "gstin": GSTIN, "iec": IEC}

    # Another OPERATIONS user still sees this exporter masked.
    for seen in await _identifiers_as(client, tokens[UserRole.OPERATIONS], customer_id):
        assert seen["pan"] == _masked(PAN)


async def test_write_responses_are_masked_too(client: AsyncClient, tokens: dict[UserRole, str]):
    """An OPERATIONS non-owner writing a PAN doesn't get it echoed back raw."""
    token = tokens[UserRole.OPERATIONS]
    resp = await client.post(
        f"{BASE}/exporters", json={"source": "SALES", "pan": PAN}, headers=auth_header(token)
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["pan"] == _masked(PAN)

    patched = await client.patch(
        f"{BASE}/exporters/{resp.json()['customer_id']}",
        json={"gstin": GSTIN},
        headers=auth_header(token),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["gstin"] == _masked(GSTIN)


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


@pytest.mark.parametrize("role", [UserRole.COMPLIANCE, UserRole.ADMIN])
async def test_contacts_unmasked_for_compliance_and_admin(
    client: AsyncClient, tokens: dict[UserRole, str], exporter_with_contact: str, role: UserRole
):
    for seen in await _contacts_as(client, tokens[role], exporter_with_contact):
        assert seen == {"email": EMAIL, "phone": PHONE}


async def test_contacts_masked_for_non_owning_operations(
    client: AsyncClient, tokens: dict[UserRole, str], exporter_with_contact: str
):
    for seen in await _contacts_as(client, tokens[UserRole.OPERATIONS], exporter_with_contact):
        assert seen == {"email": MASKED_EMAIL, "phone": _masked(PHONE)}


async def test_contacts_unmasked_for_owning_relationship_manager(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    rm_id, rm_token = await user_with_role(client, UserRole.OPERATIONS)
    customer_id = await _create_exporter(client, tokens[UserRole.COMPLIANCE])
    _set_relationship_manager_sync(customer_id, rm_id)

    # The add-contact response follows the same rule as the reads.
    added = await _add_contact(client, rm_token, customer_id)
    assert (added["email"], added["phone"]) == (EMAIL, PHONE)

    for seen in await _contacts_as(client, rm_token, customer_id):
        assert seen == {"email": EMAIL, "phone": PHONE}


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
    from app.modules.onboarding.api.schemas.exporter import mask_email

    assert mask_email(value) == expected


# ── Lifecycle moves: gated per edge, not per route ───────────────────────────


async def _move(client: AsyncClient, token: str, customer_id: str, to_status: str):
    return await client.post(
        f"{BASE}/exporters/{customer_id}/transition",
        json={"to_status": to_status},
        headers=auth_header(token),
    )


async def _exporter_in_compliance_review(client: AsyncClient, token: str) -> str:
    """Walk a new exporter through the sales stages — all open to OPERATIONS."""
    customer_id = await _create_exporter(client, token)
    for to_status in (
        "CONTACTED",
        "DATA_COLLECTION",
        "VERIFICATION_IN_PROGRESS",
        "COMPLIANCE_REVIEW",
    ):
        resp = await _move(client, token, customer_id, to_status)
        assert resp.status_code == 200, (to_status, resp.text)
    return customer_id


async def test_operations_can_work_sales_stages_up_to_compliance_review(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    customer_id = await _exporter_in_compliance_review(client, tokens[UserRole.OPERATIONS])
    detail = await client.get(
        f"{BASE}/exporters/{customer_id}", headers=auth_header(tokens[UserRole.OPERATIONS])
    )
    assert detail.json()["lifecycle_status"] == "COMPLIANCE_REVIEW"


@pytest.mark.parametrize("to_status", ["ONBOARDED", "DATA_COLLECTION"])
async def test_operations_cannot_decide_out_of_compliance_review(
    client: AsyncClient, tokens: dict[UserRole, str], to_status: str
):
    """Approving (-> ONBOARDED) and sending back (-> DATA_COLLECTION) are both
    compliance decisions."""
    customer_id = await _exporter_in_compliance_review(client, tokens[UserRole.OPERATIONS])

    resp = await _move(client, tokens[UserRole.OPERATIONS], customer_id, to_status)
    assert resp.status_code == 403, resp.text
    assert resp.json()["error_code"] == "FORBIDDEN"

    resp = await _move(client, tokens[UserRole.COMPLIANCE], customer_id, to_status)
    assert resp.status_code == 200, resp.text
    assert resp.json()["lifecycle_status"] == to_status


async def test_operations_cannot_move_an_onboarded_exporter(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    customer_id = await _exporter_in_compliance_review(client, tokens[UserRole.OPERATIONS])
    onboarded = await _move(client, tokens[UserRole.COMPLIANCE], customer_id, "ONBOARDED")
    assert onboarded.status_code == 200, onboarded.text

    resp = await _move(client, tokens[UserRole.OPERATIONS], customer_id, "ACTIVE")
    assert resp.status_code == 403, resp.text


async def test_illegal_edge_is_409_even_from_a_gated_status(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    """The edge table is checked first, so an illegal move reads the same to
    every caller rather than leaking which edges are merely role-gated."""
    customer_id = await _exporter_in_compliance_review(client, tokens[UserRole.OPERATIONS])
    resp = await _move(client, tokens[UserRole.OPERATIONS], customer_id, "ACTIVE")
    assert resp.status_code == 409, resp.text


# ── Creation cannot skip the compliance decision ─────────────────────────────


@pytest.mark.parametrize("lifecycle_status", ["ONBOARDED", "ACTIVE", "OFFBOARDED"])
async def test_operations_cannot_create_an_exporter_past_compliance(
    client: AsyncClient, tokens: dict[UserRole, str], lifecycle_status: str
):
    resp = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "lifecycle_status": lifecycle_status},
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error_code"] == "FORBIDDEN"


async def test_operations_can_create_at_a_sales_stage(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    await _create_exporter(client, tokens[UserRole.OPERATIONS], lifecycle_status="DATA_COLLECTION")


async def test_compliance_can_create_an_onboarded_exporter(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    """Migrating an already-approved relationship in is a compliance call."""
    resp = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "lifecycle_status": "ONBOARDED"},
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["lifecycle_status"] == "ONBOARDED"


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
