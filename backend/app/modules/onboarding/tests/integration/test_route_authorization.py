"""Role gates on the onboarding / exporter-CRM routes, reviewer attribution on
verification reviews, the provider allow-list, and server-side masking of
PAN/GSTIN/IEC and contact email/phone.

Every gated route gets a negative test per refused role asserting 403 — the
gate runs as a dependency, so a 403 also proves the handler never ran.

Reveal rule as of L1-10: COMPLIANCE and ADMIN see raw PAN/GSTIN/IEC and raw
contact email/phone; every other role sees them masked, including the assigned
relationship manager (architecture decision 12 defers ownership-scoped reveal
until after the prototype). The same two roles are the only ones that may use
an exact identifier search filter, because an exact match is an existence
oracle whatever the response body says.
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
ADMIN_ONLY = {UserRole.ADMIN}
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
        f"{BASE}/exporters/{_ID}/marker",
        {"marker": "PAUSED", "reason": "Seasonal"},
        STAFF,
    ),
    ("POST", f"{BASE}/exporters/{_ID}/contacts", {"name": "Jane"}, STAFF),
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
    ("POST", f"{BASE}/rxil/company-intake", {"exporter": {}}, STAFF),
    ("POST", f"{BASE}/imports/companies", None, STAFF),
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
    ("GET", f"{BASE}/qualification/criteria", None, READERS),
    ("GET", f"{BASE}/qualification/criteria/revenue/versions", None, READERS),
    ("GET", f"{BASE}/qualification/reason-codes", None, READERS),
    ("GET", f"{BASE}/exporters/{_ID}/qualification", None, READERS),
    ("GET", f"{BASE}/imports/companies/template", None, STAFF),
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
    filter is COMPLIANCE/ADMIN-only (L1-10), so using one here would make this
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


@pytest.mark.parametrize("role", [UserRole.COMPLIANCE, UserRole.ADMIN])
async def test_identifiers_unmasked_for_compliance_and_admin(
    client: AsyncClient, tokens: dict[UserRole, str], exporter_with_identifiers: str, role: UserRole
):
    for seen in await _identifiers_as(client, tokens[role], exporter_with_identifiers):
        assert seen == {"pan": PAN, "gstins": [GSTIN], "iec": IEC}


@pytest.mark.parametrize("role", [UserRole.OPERATIONS, UserRole.DEVELOPER])
async def test_identifiers_masked_for_non_owning_operations_and_developer(
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

    Architecture decision 12 settles the prototype as COMPLIANCE/ADMIN only,
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


# ── Identifier search is an existence oracle (L1-10) ─────────────────────────


@pytest.mark.parametrize("param", ["pan", "gstin", "iec"])
@pytest.mark.parametrize("role", [UserRole.OPERATIONS, UserRole.DEVELOPER])
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


@pytest.mark.parametrize("role", [UserRole.COMPLIANCE, UserRole.ADMIN])
async def test_identifier_search_allowed_for_compliance_and_admin(
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

    patched = await client.patch(
        f"{BASE}/exporters/{resp.json()['customer_id']}",
        json={"gstins": [gstin]},
        headers=auth_header(token),
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["gstins"] == [_masked(gstin)]


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


# ── The journey is never moved by hand (L2-04) ───────────────────────────────
#
# The ten-status lifecycle and its per-edge compliance gate are gone. The
# journey moves only through a qualification outcome (and, later, the
# background check), so no role can set it — not at creation, not by edit, and
# there is no route for it.


async def test_there_is_no_route_to_move_the_journey(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    customer_id = await _create_exporter(client, tokens[UserRole.ADMIN])
    resp = await client.post(
        f"{BASE}/exporters/{customer_id}/transition",
        json={"to_status": "CUSTOMER"},
        headers=auth_header(tokens[UserRole.ADMIN]),
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
        headers=auth_header(tokens[UserRole.ADMIN]),
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


@pytest.mark.parametrize("role", [UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN])
async def test_staff_are_served_the_marker_moves_they_may_make(
    client: AsyncClient, tokens: dict[UserRole, str], role: UserRole
):
    customer_id = await _create_exporter(client, tokens[UserRole.ADMIN])
    detail = await client.get(
        f"{BASE}/exporters/{customer_id}", headers=auth_header(tokens[role])
    )
    assert detail.json()["allowed_marker_moves"] == [
        {"to": "PAUSED", "reason_required": True},
        {"to": "ENDED", "reason_required": True},
    ]


async def test_a_developer_is_served_no_moves(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    customer_id = await _create_exporter(client, tokens[UserRole.ADMIN])
    token = tokens[UserRole.DEVELOPER]
    detail = await client.get(f"{BASE}/exporters/{customer_id}", headers=auth_header(token))
    assert detail.json()["allowed_marker_moves"] == []
    qualification = await client.get(
        f"{BASE}/exporters/{customer_id}/qualification", headers=auth_header(token)
    )
    assert qualification.json()["allowed_outcomes"] == []
    assert qualification.json()["can_record_results"] is False


async def test_served_moves_follow_the_state(client: AsyncClient, tokens: dict[UserRole, str]):
    token = tokens[UserRole.OPERATIONS]
    customer_id = await _create_exporter(client, tokens[UserRole.ADMIN])

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
    after = await client.post(
        f"{BASE}/exporters/{customer_id}/qualification/outcome",
        json={"outcome": "QUALIFIED"},
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
