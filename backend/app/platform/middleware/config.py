"""Configuration for the middleware platform capability.

Holds the route allowlist ``IdempotencyMiddleware`` gates on.

**Why the routes are literals and not imports.** ARCHITECTURE.md §2 — enforced
in CI by the ``foundation-is-independent`` contract in ``importlinter.ini`` —
forbids ``app.platform`` from importing ``app.api`` or ``app.modules``. The
middleware therefore cannot reach for a router object to learn which endpoints
opt in; the allowlist can only be data declared here and matched against the
request path at request time.

**Opt-in, never opt-out.** A request is subject to idempotency handling only
if its (method, route template) pair appears in ``IDEMPOTENT_ROUTES``. Every
other route on the application — including every route added in future —
passes through untouched. An opt-out list would silently capture new
endpoints the moment they were written.

This is also why there is no separate exclusion list. ``/metrics``, ``/static``,
the health probes and the docs endpoints are out of scope because they are not
listed here, not because something removes them afterwards — a second mechanism
that could veto an explicit entry would only make the policy harder to read.

**Templates, not URLs.** Entries carry the path *as declared on the route*
(``/api/v1/ledger/transactions/{transaction_id}``), not a concrete URL. A
parameterised route contributes one entry rather than one per resource, and the
template is what the middleware later uses as a bounded-cardinality scope.

**Routes deliberately absent, and which must stay absent.** Three endpoints
already own a working idempotency implementation, and enabling this middleware
on them would register the same request twice under two mechanisms with two
key formats:

* ``POST /api/v1/payments`` — legacy ``Idempotency-Key`` header, replayed via a
  separate 24-hour key table.
* ``POST /api/v1/onboarding/cases`` — legacy ``Idempotency-Key`` header, which
  also dedupes on ``external_case_id``, a dimension this middleware cannot
  observe.
* ``POST /api/v1/ledger/transactions`` and its ``/compensation`` sibling — the
  key travels in the request *body* and is enforced by a database unique
  constraint on the transaction row.

Consolidating those onto this middleware is a separate ticket. Until then they
are out of scope, not merely unconfigured.
"""

from app.platform.configuration.config import settings

#: Methods that may ever carry an idempotency key. A safe-method request never
#: registers a key, so the method check runs before any path matching.
IDEMPOTENT_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: (HTTP method, route template) pairs the middleware enforces a key on.
#:
#: Derived from ``API_V1_PREFIX`` rather than hardcoded so the allowlist cannot
#: drift into silently matching nothing if the prefix is ever changed.
#:
#: Both entries are mutating money endpoints with no competing idempotency
#: implementation, already role-gated to OPERATIONS/ADMIN.
#:
#: ``POST /api/v1/settlement`` matters beyond its own replay protection: the key
#: it accepts is written to ``settlement.idempotency_key`` and becomes the root
#: every downstream key for that settlement is derived from — the workflow's
#: per-step keys and the per-leg key handed to the external rail. Removing it
#: from this list does not merely stop replaying the endpoint; it strands that
#: whole chain without a root.
IDEMPOTENT_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", f"{settings.API_V1_PREFIX}/settlement"),
        ("POST", f"{settings.API_V1_PREFIX}/settlement/execute"),
    }
)
