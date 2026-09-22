"""Route/method gating for ``IdempotencyMiddleware``.

These cover the gate and nothing else, asserting two things and no more: which
requests the middleware decides are in scope, and that every request — gated or
not — still reaches its handler and comes back untouched.

Header extraction and key-format validation are covered in
``test_idempotency_validation.py``. They matter here only in that a *gated*
request must now carry a valid key to reach its handler at all, so the one test
that exercises the enabled route sends one; every other test here is about
requests the gate declines to touch.

Registration, replay and completion are later slices and are absent throughout.

**Why a purpose-built app rather than ``app.main:app``.** Two reasons, and the
second is binding. The gate reasons about (method, route template) pairs, so a
stub app carrying the real templates exercises exactly the logic under test with
no database, no authentication and no module behaviour in the way. And
``app.platform`` may not import ``app.main``: it reaches ``app.api`` and
``app.modules`` from there, which the ``foundation-is-independent`` contract in
``importlinter.ini`` forbids — including indirectly.

The assertions that *do* need the composed application — that these templates
are real, and that the middleware is wired in the right position — therefore
live in ``tests/contract/test_idempotency_middleware_wiring.py``, which sits
outside ``app`` and may import the composition root. ``STUB_ROUTES`` below is
the single source of truth both files share.
"""

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.platform.middleware import services as middleware_services
from app.platform.middleware.config import IDEMPOTENT_METHODS, IDEMPOTENT_ROUTES
from app.platform.middleware.services import IdempotencyMiddleware

#: The gated route these tests drive. The allowlist holds more than this one;
#: the gate's behaviour is identical for each, so the suite exercises one and
#: ``test_allowlist_contains_only_the_audited_routes`` pins the full set.
ENABLED = ("POST", "/api/v1/settlement/execute")

#: Templates copied verbatim from the live route table. Every one except the two
#: marked synthetic is asserted to still exist by the wiring suite in
#: ``tests/contract/``; the synthetic pair exists only to pin a branch of the
#: gate that no real route reaches.
SYNTHETIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/v1/settlement/execute"),
        ("POST", "/metrics"),
    }
)

STUB_ROUTES: tuple[tuple[str, str], ...] = (
    ENABLED,
    # Synthetic: the real app serves no GET here. Present so the method check can
    # be tested against the enabled path itself, not merely a different path.
    ("GET", "/api/v1/settlement/execute"),
    ("GET", "/api/v1/settlement/{transaction_id}"),
    # Legacy Idempotency-Key header implementations — must stay untouched.
    ("POST", "/api/v1/payments"),
    ("GET", "/api/v1/payments/{transaction_id}"),
    ("POST", "/api/v1/onboarding/cases"),
    ("PATCH", "/api/v1/onboarding/cases/{case_id}"),
    ("POST", "/api/v1/onboarding/cases/{case_id}/transitions"),
    # Legacy body-key + DB-unique-constraint implementation — must stay untouched.
    ("POST", "/api/v1/ledger/transactions"),
    ("POST", "/api/v1/ledger/transactions/{transaction_id}/compensation"),
    ("PATCH", "/api/v1/ledger/accounts/{account_id}/status"),
    # A mutating route that is simply not on the allowlist.
    ("POST", "/api/v1/compliance/approvals"),
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/docs"),
    ("GET", "/metrics"),
    # Synthetic: no mutating /metrics route exists. Present so a mutating request
    # to a path outside the versioned API is still shown to pass through.
    ("POST", "/metrics"),
)

UUID = "00000000-0000-4000-8000-000000000000"


def fresh_key() -> str:
    return str(uuid4())


@pytest.fixture
def handled() -> list[str]:
    """Records every handler that actually ran, as ``"METHOD /concrete/path"``."""
    return []


@pytest.fixture
def stub_app(handled: list[str]) -> FastAPI:
    app = FastAPI()

    async def endpoint(request: Request) -> dict[str, str]:
        handled.append(f"{request.method} {request.url.path}")
        return {"handler": "reached"}

    for method, template in STUB_ROUTES:
        app.add_api_route(template, endpoint, methods=[method])

    app.add_middleware(IdempotencyMiddleware)
    return app


@pytest.fixture
def gate_decisions(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """Records the gate's verdict for each request, in order.

    Wraps the real resolver rather than replacing it, so the recorded values are
    the genuine decisions the middleware acted on. A spy is used in preference to
    capturing log output because ``configure_logging`` sets
    ``cache_logger_on_first_use=True``, which makes log capture depend on whether
    some earlier test already bound the logger.
    """
    decisions: list[str | None] = []
    real = middleware_services.resolve_idempotent_route

    def spy(request: Request) -> str | None:
        decision = real(request)
        decisions.append(decision)
        return decision

    monkeypatch.setattr(middleware_services, "resolve_idempotent_route", spy)
    return decisions


@pytest.fixture
async def client(stub_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=stub_app), base_url="http://test"
    ) as ac:
        yield ac


# ── The enabled route ────────────────────────────────────────────────────────


async def test_enabled_route_is_gated(
    client: AsyncClient, gate_decisions: list[str | None], handled: list[str]
) -> None:
    """POST /api/v1/settlement/execute is recognised as gated.

    Sends a valid key because a gated request without one is rejected outright; the
    assertion under test is the gate's verdict, not the key handling.
    """
    response = await client.post(
        "/api/v1/settlement/execute",
        headers={"X-Idempotency-Key": fresh_key()},
    )

    assert gate_decisions == ["/api/v1/settlement/execute"]
    # Being gated does not by itself intercept: with a valid key the handler
    # still runs and the response is its own. Registration is a later slice.
    assert response.status_code == 200
    assert response.json() == {"handler": "reached"}
    assert handled == ["POST /api/v1/settlement/execute"]


async def test_get_on_the_enabled_path_passes_through(
    client: AsyncClient, gate_decisions: list[str | None], handled: list[str]
) -> None:
    """The gate keys on method as well as path, not on path alone."""
    response = await client.get("/api/v1/settlement/execute")

    assert gate_decisions == [None]
    assert response.status_code == 200
    assert handled == ["GET /api/v1/settlement/execute"]


# ── Everything else passes through ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path"),
    [
        pytest.param("GET", f"/api/v1/settlement/{UUID}", id="get-settlement"),
        pytest.param("GET", f"/api/v1/payments/{UUID}", id="get-payment"),
        pytest.param("GET", "/api/v1/health", id="health"),
        pytest.param("GET", "/api/v1/docs", id="docs"),
        pytest.param("GET", "/metrics", id="metrics"),
    ],
)
async def test_non_mutating_methods_pass_through(
    client: AsyncClient,
    gate_decisions: list[str | None],
    handled: list[str],
    method: str,
    path: str,
) -> None:
    response = await client.request(method, path)

    assert gate_decisions == [None]
    assert response.status_code == 200
    assert handled == [f"{method} {path}"]


@pytest.mark.parametrize(
    ("method", "path", "reason"),
    [
        pytest.param("POST", "/api/v1/payments", "legacy Idempotency-Key header", id="payments"),
        pytest.param("POST", "/api/v1/onboarding/cases", "legacy Idempotency-Key header", id="onboarding-cases"),
        pytest.param("PATCH", f"/api/v1/onboarding/cases/{UUID}", "onboarding, not enabled", id="onboarding-patch"),
        pytest.param(
            "POST",
            f"/api/v1/onboarding/cases/{UUID}/transitions",
            "onboarding, not enabled",
            id="onboarding-transitions",
        ),
        pytest.param("POST", "/api/v1/ledger/transactions", "legacy body idempotency_key", id="ledger-transactions"),
        pytest.param(
            "POST",
            f"/api/v1/ledger/transactions/{UUID}/compensation",
            "legacy body idempotency_key",
            id="ledger-compensation",
        ),
        pytest.param(
            "PATCH", f"/api/v1/ledger/accounts/{UUID}/status", "ledger, not enabled", id="ledger-account-status"
        ),
        pytest.param("POST", "/api/v1/compliance/approvals", "mutating but not enabled", id="compliance-approvals"),
        pytest.param("POST", "/metrics", "outside the versioned API", id="metrics-post"),
    ],
)
async def test_routes_not_enabled_pass_through_unchanged(
    client: AsyncClient,
    gate_decisions: list[str | None],
    handled: list[str],
    method: str,
    path: str,
    reason: str,
) -> None:
    """A mutating request outside the allowlist is left completely alone."""
    response = await client.request(method, path)

    assert gate_decisions == [None], f"{method} {path} was gated despite: {reason}"
    assert response.status_code == 200
    assert response.json() == {"handler": "reached"}
    assert handled == [f"{method} {path}"]


async def test_unmatched_path_with_enabled_method_is_not_gated(
    client: AsyncClient, gate_decisions: list[str | None]
) -> None:
    """A 404 must not be gated — the allowlist pattern is anchored at both ends."""
    response = await client.post("/api/v1/settlement/execute/extra")

    assert gate_decisions == [None]
    assert response.status_code == 404


async def test_path_prefix_alone_does_not_gate(
    client: AsyncClient, gate_decisions: list[str | None]
) -> None:
    """Guards against an unanchored pattern matching a longer sibling path."""
    response = await client.post("/api/v1/settlement/executed")

    assert gate_decisions == [None]
    # 405, not 404: the stub's GET /settlement/{transaction_id} claims this path
    # with transaction_id="executed". Which of the two the app returns is beside
    # the point — what matters is that the gate did not fire.
    assert response.status_code in {404, 405}


# ── Configuration ────────────────────────────────────────────────────────────


def test_allowlist_contains_only_the_audited_routes() -> None:
    """Widening the allowlist is a deliberate act, not an accident.

    ``POST /api/v1/settlement`` carries more weight than its own replay
    protection: the key it accepts is stored on the settlement and becomes the
    root every downstream key is derived from. Dropping it here would strand
    that chain without a root, not merely stop replaying one endpoint.
    """
    assert IDEMPOTENT_ROUTES == frozenset(
        {
            ("POST", "/api/v1/settlement"),
            ("POST", "/api/v1/settlement/execute"),
        }
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/payments"),
        ("POST", "/api/v1/onboarding/cases"),
        ("POST", "/api/v1/ledger/transactions"),
        ("POST", "/api/v1/ledger/transactions/{transaction_id}/compensation"),
    ],
)
def test_routes_with_legacy_idempotency_are_excluded(method: str, path: str) -> None:
    """Enabling the middleware on these would register one request under two
    mechanisms."""
    assert (method, path) not in IDEMPOTENT_ROUTES


def test_safe_methods_are_not_idempotency_bearing() -> None:
    assert IDEMPOTENT_METHODS == frozenset({"POST", "PUT", "PATCH", "DELETE"})
    assert "GET" not in IDEMPOTENT_METHODS
    assert "HEAD" not in IDEMPOTENT_METHODS
    assert "OPTIONS" not in IDEMPOTENT_METHODS


def test_compiled_allowlist_matches_the_configured_routes() -> None:
    """The compiled form is built once at import; keep it honest against config."""
    compiled = {
        (method, template) for method, _pattern, template in middleware_services._COMPILED_ROUTES
    }

    assert compiled == set(IDEMPOTENT_ROUTES)


def test_synthetic_routes_are_a_subset_of_the_stub() -> None:
    """The wiring suite exempts these from its real-route check; keep them honest."""
    assert SYNTHETIC_ROUTES <= set(STUB_ROUTES)
