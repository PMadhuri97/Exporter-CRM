"""Role gates on the routes outside the onboarding module (L1-06, L1-07, L1-08).

`app/modules/onboarding/tests/integration/test_route_authorization.py` covers
every route under `/api/v1/onboarding`. Nothing covered the rest, which is why
nine routes shipped checking only that the caller held a token — and two
checking nothing at all. This file is the equivalent table for them.

It lives under `platform/authorization` rather than in any one module's tests
because the routes it covers belong to four different places (`notifications`,
`audit`, `compliance`, and the delivery layer's `workflows.py`), and because
`require_role` — the thing actually under test — lives here.

Structure mirrors the onboarding file deliberately: a table of
`(method, path, body, allowed_roles)`, and a parametrised refusal per route per
disallowed role. A 403 from a dependency also proves the handler never ran.

Scope note: this is a per-route table, not a coverage guard. Deriving the
expected set from the mounted routes so that a *new* unguarded route fails the
build is a separate, later task (it needs an agreed public-route allowlist).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.platform.authentication.models import UserRole
from app.platform.authentication.testing import auth_header, token_with_role

pytestmark = pytest.mark.asyncio

STAFF = {UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN}
COMPLIANCE_OR_ADMIN = {UserRole.COMPLIANCE, UserRole.ADMIN}

_ID = "00000000-0000-4000-8000-000000000000"

# (method, path, json body, allowed roles)
GATED_ROUTES = [
    # notifications (L1-06) — these had no auth dependency at all.
    ("GET", "/api/v1/notifications/", None, STAFF),
    ("POST", "/api/v1/notifications/process-pending", None, STAFF),
    # audit (L1-07) — /events was already gated; these three were login-only.
    ("GET", f"/api/v1/audit/events/{_ID}", None, COMPLIANCE_OR_ADMIN),
    ("GET", f"/api/v1/audit/transactions/{_ID}", None, COMPLIANCE_OR_ADMIN),
    ("GET", f"/api/v1/audit/correlations/{_ID}", None, COMPLIANCE_OR_ADMIN),
    # workflows (L1-07) — login-only, including the one that starts a workflow.
    ("GET", f"/api/v1/workflows/{_ID}", None, STAFF),
    ("POST", f"/api/v1/workflows/{_ID}/start", None, STAFF),
    # compliance (L1-08) — the one documented module-rule exception.
    ("GET", f"/api/v1/compliance/approvals/{_ID}", None, COMPLIANCE_OR_ADMIN),
    ("GET", f"/api/v1/compliance/screenings/{_ID}", None, COMPLIANCE_OR_ADMIN),
]

REFUSALS = [
    pytest.param(method, path, body, role, id=f"{method} {path} as {role.value}")
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


@pytest.mark.parametrize(
    ("method", "path"),
    [pytest.param(m, p, id=f"{m} {p}") for m, p, _, _ in GATED_ROUTES],
)
async def test_gated_route_refuses_anonymous(client: AsyncClient, method: str, path: str):
    """No token at all is a 401, not a 403 — the caller is unknown, not refused.

    Worth asserting separately from the role table: the notification routes had
    no auth dependency whatsoever, so an anonymous request reached the handler
    and returned data. A 401 here is the proof that no longer happens.
    """
    resp = await client.request(method, path, headers={"Idempotency-Key": str(uuid.uuid4())})
    assert resp.status_code == 401, resp.text


async def test_staff_can_still_read_the_notification_queue(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    """The gate must not have broken the routes for the roles that may use them.

    A refusal-only test suite passes just as well against a route that refuses
    everyone, so the allowed path is asserted too. `list_pending` needs no
    fixture data — an empty queue is a valid 200.
    """
    for role in STAFF:
        resp = await client.get("/api/v1/notifications/", headers=auth_header(tokens[role]))
        assert resp.status_code == 200, (role, resp.text)
        assert isinstance(resp.json(), list)
