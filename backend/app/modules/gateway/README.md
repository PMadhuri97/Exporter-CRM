# gateway

Business domain. Public facade is `__init__.py` — the only import surface for other modules (ARCHITECTURE.md §6).

Single external entry point for `/v1/...` customer-facing traffic (Epic 4.4). This
first slice (ANER-4.4-S1T1) builds the request-handling pipeline only:

- Correlation-ID validation and propagation (`X-Correlation-Id`), scoped to the
  paths this module owns.
- Append-only request audit trail (`gateway.api_request_logs`) — identifiers
  only, never a request/response body. See `domain/entities/gateway.py`.
- `GET /health` — overall status plus a per-dependency breakdown, structured so
  a new dependency is a new key, never a shape change.
- Version-prefix routing: `/v1/...` passes through (a 404 for an undefined path
  is expected — no real endpoints exist yet); any other version prefix
  (`/v2/...`) is rejected with a normalized 404.

Every error this module produces goes through the platform's existing
`AnerBaseException` → `aner_exception_handler` convention
(`app/platform/middleware/handlers.py`, wired in `app/main.py`) — the gateway
does not invent a second error shape.

Not in scope here: API key management, scope/authorization enforcement, rate
limiting, and the deprecation framework beyond basic prefix routing. Those are
ANER-4.4-S1T2 through S1T5.
