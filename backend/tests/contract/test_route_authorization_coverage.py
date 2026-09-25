"""Every mounted route is classified, and every gated one refuses the roles it should.

Two module-level test files already assert role gates: the onboarding suite
covers `/api/v1/onboarding/*` in depth (masking, the screening-checklist
exploit, the identifier-search oracle), and both grew out of fixing specific
holes. Neither could catch the thing that actually went wrong — a route shipping
with *no* classification at all. `POST /api/v1/notifications/process-pending`
had no auth dependency of any kind and no test anywhere asserted that it should,
so nothing failed.

This file closes that gap with a coverage guard rather than more rows. It reads
the mounted routes out of the OpenAPI document and requires each one to appear
in exactly one of three tables below. A new route is unclassified by
construction, so adding one without deciding who may call it fails the build.

**It records what is, and is the place to change what should be.** The tables
were built by probing every route with every role, so they describe enforced
behaviour, not intent. Where the two differ the comment says so — see
`POST /api/v1/compliance/approvals`, which ADMIN cannot call. Changing a gate
means changing the route and this table together, which is the point.

Deliberate overlap: the onboarding suite keeps its own refusal rows. They test
the same gates from the module's side and are cheap; this file is the authority
on *which routes exist and how they are classified*.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.main import app
from app.platform.authentication.models import UserRole
from app.platform.authentication.testing import auth_header, token_with_role

pytestmark = pytest.mark.asyncio

ALL_ROLES = frozenset(UserRole)
STAFF = frozenset({UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN})
COMPLIANCE_OR_ADMIN = frozenset({UserRole.COMPLIANCE, UserRole.ADMIN})
#: Staff plus DEVELOPER, which may read the CRM but never unmasked.
READERS = STAFF | {UserRole.DEVELOPER}

_ID = "00000000-0000-4000-8000-000000000000"

V1 = "/api/v1"
CRM = f"{V1}/onboarding"


#: Routes that answer without any credential, by design.
#:
#: Each one is listed because it was confirmed public, not because it happens to
#: have no dependency today — that reasoning is what left the notification queue
#: open. `login` / `register` / `refresh` are the unauthenticated entry points
#: (register always grants API_USER, and returns 404 when
#: SELF_SERVICE_SIGNUP_ENABLED is false); the health and metrics probes are
#: scraped by infrastructure that holds no account.
PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/health"),
        ("GET", "/metrics"),
        ("GET", f"{V1}/health"),
        ("GET", f"{V1}/health/ready"),
        ("POST", f"{V1}/auth/login"),
        ("POST", f"{V1}/auth/register"),
        ("POST", f"{V1}/auth/refresh"),
    }
)

#: Authenticated by a request signature instead of a bearer token.
#:
#: The Sumsub webhook is called by Sumsub, which has no account here. It
#: verifies an HMAC over the body (`X-Payload-Digest`) and returns 401 when that
#: fails — so it is neither public nor role-gated, and a role cross-product
#: would assert nothing about it. It gets its own test below.
SIGNATURE_AUTHENTICATED_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", f"{CRM}/webhooks/sumsub"),
    }
)

#: (method, path) -> the roles permitted to call it. Every other role gets 403.
#:
#: A route mapped to ALL_ROLES is still gated: it requires a valid token and
#: refuses an anonymous caller, it just does not narrow by role.
GATED_ROUTES: dict[tuple[str, str], frozenset[UserRole]] = {
    # ── auth: authenticated, but every role acts only on itself ──────────────
    ("POST", f"{V1}/auth/logout"): ALL_ROLES,
    ("GET", f"{V1}/auth/me"): ALL_ROLES,
    # ── notifications (L1-06) ────────────────────────────────────────────────
    ("GET", f"{V1}/notifications/"): STAFF,
    ("POST", f"{V1}/notifications/process-pending"): STAFF,
    # ── audit (L1-07) — the platform-wide record of who did what ─────────────
    ("GET", f"{V1}/audit/events"): COMPLIANCE_OR_ADMIN,
    ("GET", f"{V1}/audit/events/{{event_id}}"): COMPLIANCE_OR_ADMIN,
    ("GET", f"{V1}/audit/transactions/{{transaction_id}}"): COMPLIANCE_OR_ADMIN,
    ("GET", f"{V1}/audit/correlations/{{correlation_id}}"): COMPLIANCE_OR_ADMIN,
    # ── workflows (L1-07) ────────────────────────────────────────────────────
    ("GET", f"{V1}/workflows/{{transaction_id}}"): STAFF,
    ("POST", f"{V1}/workflows/{{transaction_id}}/start"): STAFF,
    # ── compliance (L1-08, the one documented module-rule exception) ─────────
    #
    # The two POSTs are COMPLIANCE-only: `require_role(UserRole.COMPLIANCE)`,
    # with no ADMIN. That is pre-existing and is recorded here as enforced
    # rather than corrected, because widening a compliance gate is a decision
    # for whoever owns maker-checker, not a side effect of writing a test.
    ("POST", f"{V1}/compliance/screen/{{transaction_id}}"): frozenset({UserRole.COMPLIANCE}),
    ("POST", f"{V1}/compliance/approvals"): frozenset({UserRole.COMPLIANCE}),
    ("GET", f"{V1}/compliance/approvals/{{transaction_id}}"): COMPLIANCE_OR_ADMIN,
    ("GET", f"{V1}/compliance/screenings/{{transaction_id}}"): COMPLIANCE_OR_ADMIN,
    # ── onboarding: legacy case state machine ────────────────────────────────
    ("POST", f"{CRM}/cases"): STAFF,
    ("GET", f"{CRM}/cases/{{case_id}}"): STAFF,
    ("PATCH", f"{CRM}/cases/{{case_id}}"): STAFF,
    ("POST", f"{CRM}/cases/{{case_id}}/transitions"): COMPLIANCE_OR_ADMIN,
    ("GET", f"{CRM}/cases/{{case_id}}/transitions"): STAFF,
    # ── onboarding: legacy foundation ────────────────────────────────────────
    ("POST", f"{CRM}/register"): STAFF,
    ("GET", f"{CRM}/{{customer_id}}/sdk-token"): STAFF,
    ("GET", f"{CRM}/{{customer_id}}/status"): STAFF,
    # ── Exporter CRM: writes are staff, reads admit DEVELOPER (masked) ───────
    ("POST", f"{CRM}/exporters"): STAFF,
    ("GET", f"{CRM}/exporters"): READERS,
    ("GET", f"{CRM}/exporters/{{customer_id}}"): READERS,
    ("PATCH", f"{CRM}/exporters/{{customer_id}}"): STAFF,
    ("POST", f"{CRM}/exporters/{{customer_id}}/transition"): STAFF,
    ("POST", f"{CRM}/exporters/{{customer_id}}/contacts"): STAFF,
    ("GET", f"{CRM}/exporters/{{customer_id}}/contacts"): READERS,
    ("POST", f"{CRM}/exporters/{{customer_id}}/activities"): STAFF,
    ("GET", f"{CRM}/exporters/{{customer_id}}/activities"): READERS,
    ("GET", f"{CRM}/exporters/activities/pending"): READERS,
    # ── Shared CRM history log (L1-11) ───────────────────────────────────────
    # "See companies, contacts, deals, history" in the role matrix (§3.7):
    # staff yes, DEVELOPER read-only, API_USER no. Read-only routes; there is
    # no write surface for history and there should never be one.
    ("GET", f"{CRM}/exporters/{{customer_id}}/history"): READERS,
    ("GET", f"{CRM}/deals/{{deal_id}}/history"): READERS,
    # ── Exporter CRM: compliance workspace ───────────────────────────────────
    ("GET", f"{CRM}/exporters/{{customer_id}}/screening-review"): STAFF,
    (
        "PUT",
        f"{CRM}/exporters/{{customer_id}}/screening-review/{{item_key}}",
    ): COMPLIANCE_OR_ADMIN,
    ("GET", f"{CRM}/exporters/{{customer_id}}/bank-activity"): STAFF,
    # ── Exporter CRM: verification results ───────────────────────────────────
    ("POST", f"{CRM}/verifications"): COMPLIANCE_OR_ADMIN,
    ("GET", f"{CRM}/verifications"): STAFF,
    ("GET", f"{CRM}/verifications/{{verification_result_id}}"): STAFF,
    ("POST", f"{CRM}/verifications/{{verification_result_id}}/review"): COMPLIANCE_OR_ADMIN,
}


def _mounted_routes() -> set[tuple[str, str]]:
    """Every operation in the served OpenAPI document."""
    spec = app.openapi()
    return {
        (method.upper(), path)
        for path, operations in spec["paths"].items()
        for method in operations
        if method in ("get", "post", "put", "patch", "delete")
    }


def _concrete(path: str) -> str:
    """Substitute a well-formed dummy id for each path parameter.

    The id never matches a real row, which is the point: a gate runs as a
    dependency, so a refusal happens before the handler looks anything up. A
    test that needed real fixture data per route would be asserting the
    handler, not the gate.
    """
    out = path
    while "{" in out:
        head, _, rest = out.partition("{")
        _, _, tail = rest.partition("}")
        out = head + _ID + tail
    return out


CLASSIFIED = set(GATED_ROUTES) | PUBLIC_ROUTES | SIGNATURE_AUTHENTICATED_ROUTES


# ── The coverage guard ───────────────────────────────────────────────────────


def test_every_mounted_route_is_classified():
    """A new route must be added to one of the three tables above.

    This is the test that would have caught the unauthenticated notification
    routes: they were mounted, they were reachable, and no table mentioned
    them. Failing here forces the question "who may call this?" to be answered
    in the same change that adds the route.
    """
    unclassified = sorted(_mounted_routes() - CLASSIFIED)
    assert not unclassified, (
        "Routes are mounted but not classified. Add each to GATED_ROUTES with "
        "its permitted roles, or to PUBLIC_ROUTES / "
        "SIGNATURE_AUTHENTICATED_ROUTES with a reason:\n  "
        + "\n  ".join(f"{m} {p}" for m, p in unclassified)
    )


def test_no_table_row_names_a_route_that_is_not_mounted():
    """The other direction, so the tables cannot rot.

    A row left behind after a route is renamed or removed would otherwise sit
    there asserting nothing, and the next reader would trust it.
    """
    stale = sorted(CLASSIFIED - _mounted_routes())
    assert not stale, "Classified but not mounted:\n  " + "\n  ".join(
        f"{m} {p}" for m, p in stale
    )


def test_a_route_is_classified_exactly_once():
    overlap = sorted(
        (set(GATED_ROUTES) & PUBLIC_ROUTES)
        | (set(GATED_ROUTES) & SIGNATURE_AUTHENTICATED_ROUTES)
        | (PUBLIC_ROUTES & SIGNATURE_AUTHENTICATED_ROUTES)
    )
    assert not overlap, f"Classified in more than one table: {overlap}"


# ── Role refusals: the cross-product ─────────────────────────────────────────

REFUSALS = [
    pytest.param(method, path, role, id=f"{method} {path} as {role.value}")
    for (method, path), allowed in sorted(GATED_ROUTES.items())
    for role in UserRole
    if role not in allowed
]


@pytest.fixture(scope="module")
async def tokens(client: AsyncClient) -> dict[UserRole, str]:
    return {role: await token_with_role(client, role) for role in UserRole}


@pytest.mark.parametrize(("method", "path", "role"), REFUSALS)
async def test_gated_route_refuses_role(
    client: AsyncClient,
    tokens: dict[UserRole, str],
    method: str,
    path: str,
    role: UserRole,
):
    resp = await client.request(
        method,
        _concrete(path),
        headers={**auth_header(tokens[role]), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error_code"] == "FORBIDDEN"


@pytest.mark.parametrize(
    ("method", "path"),
    [pytest.param(m, p, id=f"{m} {p}") for m, p in sorted(GATED_ROUTES)],
)
async def test_gated_route_refuses_anonymous(client: AsyncClient, method: str, path: str):
    """No token is 401, not 403: the caller is unknown rather than refused.

    Asserted for every gated route, including the ones that admit all five
    roles — `GET /auth/me` narrows by nobody but must still not answer to a
    stranger.
    """
    resp = await client.request(
        method, _concrete(path), headers={"Idempotency-Key": str(uuid.uuid4())}
    )
    assert resp.status_code == 401, resp.text


# ── The two non-role categories ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path"),
    [pytest.param(m, p, id=f"{m} {p}") for m, p in sorted(PUBLIC_ROUTES)],
)
async def test_public_route_answers_without_a_token(
    client: AsyncClient, method: str, path: str
):
    """Public means "does not ask who you are", which is not the same as 200.

    `login`, `register` and `refresh` reject an empty body with 422 — that is
    the handler running, which is exactly what makes them public. The assertion
    is therefore "not 401 and not 403", not a specific success code.
    """
    resp = await client.request(method, _concrete(path))
    assert resp.status_code not in (401, 403), resp.text


async def test_the_signed_webhook_refuses_an_unsigned_request(client: AsyncClient):
    """It has no bearer auth and is still not open.

    Anonymous, with no `X-Payload-Digest`, it must refuse. A regression that
    dropped the signature check would show up here as a 2xx, which no other
    test in the repository would notice.
    """
    resp = await client.post(f"{CRM}/webhooks/sumsub", json={"type": "test"})
    assert resp.status_code == 401, resp.text


async def test_the_signed_webhook_ignores_bearer_role(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    """A valid token does not substitute for a valid signature.

    Documents why this route is not in GATED_ROUTES: no role gets further than
    any other, so a role cross-product would assert nothing.
    """
    for role in (UserRole.API_USER, UserRole.ADMIN):
        resp = await client.post(
            f"{CRM}/webhooks/sumsub",
            json={"type": "test"},
            headers=auth_header(tokens[role]),
        )
        assert resp.status_code == 401, (role, resp.text)


async def test_an_allowed_role_still_reaches_a_gated_route(
    client: AsyncClient, tokens: dict[UserRole, str]
):
    """A refusal-only suite passes just as well against a route that refuses
    everyone, so at least one gate is checked from the permitted side.

    The notification queue is the route that can show this without fixture
    data: `list_pending` on an empty queue is a valid 200. The rest of the
    gated table answers 404 for the dummy id, which proves the gate let the
    caller through but reads less clearly than this does.
    """
    for role in sorted(GATED_ROUTES[("GET", f"{V1}/notifications/")], key=lambda r: r.value):
        resp = await client.get(f"{V1}/notifications/", headers=auth_header(tokens[role]))
        assert resp.status_code == 200, (role, resp.text)
        assert isinstance(resp.json(), list)


def test_api_user_reaches_nothing_in_the_crm():
    """Planning assumption A10, asserted as an invariant rather than as a
    coincidence.

    Public sign-up stays open and grants `API_USER`, on the understanding that
    the role reaches nothing in the Exporter CRM. Every CRM route already
    excludes it, so the cross-product above generates 27 refusal tests — but
    those only check the routes as classified today. Nothing stopped someone
    adding a CRM route to `GATED_ROUTES` *with* `API_USER` in its allowed set
    and quietly reopening the hole.

    This is the rule itself: no route under the CRM prefix may admit
    `API_USER`, whatever the table says.

    The Sumsub webhook shares the prefix and is deliberately not covered — it
    holds no bearer role at all and refuses every caller without a valid
    signature, which `test_the_signed_webhook_ignores_bearer_role` asserts.
    """
    reachable = sorted(
        (method, path)
        for (method, path), allowed in GATED_ROUTES.items()
        if path.startswith(CRM) and UserRole.API_USER in allowed
    )
    assert not reachable, (
        "These CRM routes admit API_USER, which assumption A10 says must reach "
        "nothing in the CRM:\n  " + "\n  ".join(f"{m} {p}" for m, p in reachable)
    )
