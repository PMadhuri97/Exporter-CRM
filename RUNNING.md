# Running this checkout

This repo went from "read-only reference snapshot that cannot run" (see the
history of `README.md`'s old "⚠️ This does not run" banner) to an actually
bootable, testable FastAPI application. This document explains how to run it,
exactly what's included vs excluded and why, and what to expect when you do.

## Quick start

```bash
# 1. A Postgres instance. Any Postgres 16 works; this is what verification used:
docker run -d --name epic4-reference-postgres \
  -e POSTGRES_USER=aner -e POSTGRES_PASSWORD=aner -e POSTGRES_DB=aner_settlement \
  -p 5556:5432 postgres:16-alpine

# 2. Python deps (3.12; no venv is checked in, use your own)
cd backend
pip install -r requirements.txt -r requirements-dev.txt

# 3. backend/.env — copy .env.example and fill in at least:
#      DATABASE_URL / DATABASE_SYNC_URL  -> point at the Postgres above
#      LEDGER_RO_DB_PASSWORD, SETTLEMENT_RO_DB_PASSWORD, AUDIT_RO_DB_PASSWORD
#        -> `alembic upgrade head` REFUSES to run without these (see Caveats)
cp .env.example .env
# edit .env ...

# 4. Schema
python -m alembic upgrade head

# 5. Run it
python -m uvicorn app.main:app --reload
# GET http://localhost:8000/api/v1/health         -> internal platform health
# GET http://localhost:8000/health                -> gateway health probe
# GET http://localhost:8000/api/v1/docs           -> Swagger UI
```

`docker-compose.yml` at the repo root also works end to end (it brings up
Temporal, Kafka/Redpanda, OTel/Jaeger/Prometheus/Grafana too) but none of
that is required — with `TEMPORAL_ENABLED`, `KAFKA_ENABLED`,
`EVENT_CONSUMERS_ENABLED` and `OTEL_ENABLED` left at their defaults (all
`false`), the app runs against nothing but Postgres.

## What's in scope, and why

Business logic (application/, api/, domain policies, infrastructure) is kept
in full for: `onboarding`, `kyb`, `cases`, `customers`, `notifications`,
`gateway`, `compliance` (screening lives here), and `audit` (generic
infra that `onboarding`'s legacy code imports directly).

Everything else — `ledger`, `settlement`, `rails`, `fx`, `reconciliation`,
`reporting`, `orchestration`, `payments` — belongs to other epics and has
**no business logic** in this checkout. What each one has instead:

| Module | migrations/ | domain/entities/ | Why |
|---|---|---|---|
| `ledger`, `settlement`, `fx`, `reconciliation`, `payments` | yes | yes | `app/bootstrap.py`'s `Base.metadata` imports (and, for `payments`, `audit`'s own application code — see below) need these ORM classes registered so SQLAlchemy can resolve relationships from in-scope modules. Schema only: columns, types, relationships — verified by reading every entity file, they import nothing but `app.platform.database.models`. |
| `rails` | yes | yes | Not needed by `bootstrap.py`, but `migrations/env.py` imports `app.modules.rails.domain.entities.rail_models` directly (for autogenerate metadata) — that import has to succeed for `alembic` itself to load, regardless of which command you run. |
| `reporting` | yes (empty but for `__init__.py`) | — | Nothing references its entities anywhere; migrations exist only so the directory is registered like every other module's (`ARCHITECTURE.md` §4 / `test_migration_discovery.py`). |
| `orchestration` | — | — | **Genuinely has neither.** It owns no tables (it's pure Temporal workflow/activity glue) and nothing imports its entities. It gets an empty placeholder package (see below) purely so `importlinter.ini`'s contracts can resolve the dotted path. |

This checkout uses **one single, interlinked Alembic chain across every
module** (confirmed: `onboarding_0001_baseline`'s `down_revision` is
`audit_0001_baseline`; several merge revisions combine heads across module
boundaries). That chain cannot be cleanly split without either including
every module's migrations or doing surgery on migration history. This
checkout includes every module's migrations rather than rewrite history —
per module tables for `ledger`, `settlement`, `fx`, `reconciliation`,
`rails`, `payments`, `reporting` exist in the database with **zero
application code behind them**. That is intentional, not a bug: don't be
surprised to find a `ledger.ledger_account` table and no `ledger` service
anywhere.

### `payments` is a partial exception

Unlike the other excluded modules, `payments/__init__.py` (its real public
facade) was already schema-only in the source repo — it exports domain
entities and a plain `infrastructure/repository.py` (generic
`BaseRepository`/`AppendOnlyRepository` CRUD wrappers, no business rules),
never `application/` or `api/`. `audit/application/services.py` (kept in
full, since `audit` is in scope) imports `TransactionRepository` from
`app.modules.payments` directly, so `payments` keeps that one real facade
and its `infrastructure/` folder rather than a stub — everything else about
it (no `api/`, no `application/`) matches the exclusion policy.

### The `gateway` module and its migration head

`gateway` (Epic 4.4) was already present in this reference repo before this
pass, pulled in from a **sibling git worktree/branch**
(`feature/epic4.4-customer-api`) that has never been merged into
`feature/epic4-onboarding-orchestration` — the branch everything else here
comes from. Both branches added a migration directly on top of the same
revision (`0a772fd562e8`), so integrating `gateway`'s code left two real,
divergent Alembic heads. This was resolved with a plain no-op merge revision
(`app/modules/gateway/migrations/2807a84d72ba_...py`) — the exact pattern
already used dozens of times in this codebase's own history for exactly
this situation, not a rewrite of anything. `gateway` was also added to
`migrations/env.py`'s entity imports / `MODULE_SCHEMAS`, and to
`alembic.ini`'s `version_locations` — none of which knew about it, because
it doesn't exist on the branch those files came from.

One consequence: `importlinter.ini` (also from that branch) never got a
`gateway-internals-are-private` contract, and its per-module privacy
contracts don't list `app.modules.gateway` as a policed source either. The
architecture contracts import-linter actually *enforces* still pass (19/19,
`lint-imports --config importlinter.ini`) because nothing currently imports
into `gateway`'s internals — but a meta-test that checks the *config file's*
own completeness would (correctly) flag that gap. See "Contract tests"
below for how this was handled.

## `bootstrap.py`

Trimmed, not rewritten:

- **Entity imports** for the schema-only modules are kept exactly as they
  were (`ledger`, `settlement`, `fx`, `reconciliation`, `payments`,
  `compliance`, `customers`, `notifications`, `onboarding`, `audit`) — that's
  the whole point of copying their `domain/entities/`.
- **Event consumers removed**: `ReconciliationConsumer` and
  `SettlementLifecycleConsumer`/`RailWebhookConsumer` lived in
  `reconciliation/events/consumers.py` and `settlement/events/consumers.py`
  — application-tier code for out-of-scope modules. `ALL_CONSUMERS` now only
  has `AuditEventConsumer`, `NotificationConsumer`,
  `IdempotencyViolationStreamProcessor`. The rails routing-engine
  circuit-breaker consumer registration (`register_cb_consumer`) is dropped
  the same way.
- **`run_worker()` (the Temporal worker) removed entirely.** It registered
  one worker across workflows/activities from `onboarding` (in scope) and
  `orchestration`/`settlement`/`rails` (all out of scope) — the set can't be
  split, it's one task queue. `TEMPORAL_ENABLED` defaults to `false`, so this
  has no effect on normal boot, `alembic upgrade head`, or the test suite.
  **Setting `TEMPORAL_ENABLED=true` against this checkout is not supported.**
- **`load_dev_rail_registry_seed_data()` removed.** It imported
  `app.modules.rails.infrastructure.dev_rail_seed_loader` unconditionally
  (before its own environment gate), so leaving it in would break every
  boot, not just ones that reach the rail-seeding branch. Rails' migrations
  still create `rails.rail_registration`; nothing here ever populates it.
- **`load_stub_rail_registry_seed_data()` was left alone** — its rails
  import happens *after* both its environment and `STUB_RAIL_CONFIG_DIR`
  gates, both of which default to skipping it, so it never actually reaches
  the missing import in this checkout.
- Everything else (ledger precision check, GitOps seed loaders for purpose
  codes / sector registry / compliance rules / case SLA config / KYB vendor
  registry) is untouched — all in-scope.

## Router aggregation

Lives in `app/api/rest/router.py` (imported by `app/main.py` as
`api_router`) — confirmed by grep across `app/`, the earlier assumption that
`main.py` handled it directly was wrong. Removed: `fx`, `ledger`, `payments`,
`reconciliation`, `settlement` routers (including the settlement rail-webhook
router) — none of those modules' `api/` layers are present. Also removed:
`app.api.rest.idempotency_audit`'s router — it imports
`LedgerTransactionKeyResolver` (from `app.modules.ledger`) and
`SettlementCrossReference` (from `app.modules.settlement`) at module scope, a
genuinely cross-module feature spanning two out-of-scope modules'
infrastructure. The file is left in place, just not wired in.

`cases` and `kyb` have no `api/router.py` in the real platform either
(confirmed against the source repo) — nothing was ever registered for them.

`gateway` is **not** wired through `api_router` at all — its own
`health_router`/`v1_router`/`fallback_router` are mounted directly in
`app/main.py` at the application root (unprefixed, alongside
`GatewayRequestMiddleware`), matching exactly how the customer-api-4.4
worktree wires it — `app/main.py` on the source branch predates `gateway`
and never had this code, so it was ported over rather than found there.

`app/main.py`'s lifespan also directly imported (not just routed to) several
out-of-scope modules' application code for background jobs: the ledger
integrity check, the rail polling manager, the settlement leg-signal relay,
the rail performance aggregation job, and the rail health monitor. All
removed, each documented inline at its old call site in `main.py`. Their
`Settings` flags (`RAIL_POLLING_ENABLED`, etc.) still exist but are now
unread dead config.

## Verification results

- **`alembic upgrade head`** against a real Postgres 16 (`epic4-reference-postgres`,
  container on `localhost:5556`): **succeeds**, applies all 39 revisions
  cleanly, creates all 16 schemas (`audit`, `auth`, `cases`, `compliance`,
  `customers`, `fx`, `gateway`, `ledger`, `messaging`, `notifications`,
  `onboarding`, `payments`, `rails`, `reconciliation`, `settlement`, plus
  `public`). Single head at the merge point described above.
  **Caveat**: requires `LEDGER_RO_DB_PASSWORD`, `SETTLEMENT_RO_DB_PASSWORD`,
  `AUDIT_RO_DB_PASSWORD` to be set (`openssl rand -hex 24` each) — three
  migrations create Postgres login roles with these passwords and abort with
  an explicit `RuntimeError` if they're blank. This is by design in the real
  platform (no checked-in default for a credential that can read an entire
  module's schema), not something introduced here.
- **App import smoke test**: `python -c "from app.main import app"` —
  succeeds. This matches the pattern `conftest.py` itself uses
  (`from app.main import app`, with a handful of `os.environ.setdefault(...)`
  calls for GCP audit-sink config that would otherwise raise `KeyError` at
  import time — `.env` in this checkout sets the same variables).
- **`uvicorn app.main:app`**: boots cleanly end to end — startup lifespan
  completes (ledger precision check, all GitOps seed loaders, scheduler,
  audit dispatcher), `GET /api/v1/health` → 200, `GET /health` (gateway) →
  200 with a live DB dependency check, `GET /api/v1/openapi.json` → 200.
- **`pytest app/modules/{onboarding,cases,kyb,customers,notifications,gateway,compliance} -q --no-cov`**:
  **1743 passed, 2 skipped, 20 failed, 5 errors** (out of ~1770). Every
  failure/error is in `compliance`'s integration tests
  (`test_compliance.py`, `test_screening_uses_rule_registry.py`), and all of
  them fail for the same reason: they `POST /api/v1/payments` to create a
  transaction before screening it, and `payments`' API router is
  deliberately not present (see above). This is a structural consequence of
  the scope boundary, not a defect in what was copied — screening's own
  logic (rule engine, sector risk, sanctions) is fully exercised elsewhere
  in the same file via paths that don't need a real payment created.
- **`pytest tests/contract -q --no-cov`**: **27 passed** (after trimming —
  see below). **`lint-imports --config importlinter.ini`**: **19/19
  contracts kept.**

### Two bugs found and fixed during verification (not pre-existing, introduced by the pruning itself)

- `app/modules/__init__.py` was missing from the target repo before this
  pass (present in the source repo, empty file). Without it Python still
  imports `app.modules.*` fine as an implicit namespace package, but
  `import-linter` reports `Module 'app.modules' does not exist` and refuses
  to run. Restored.
- `app/modules/orchestration/` didn't exist at all (see the table above —
  it has nothing to bring over). `importlinter.ini`'s contracts name
  `app.modules.orchestration` as a source/forbidden module in several
  places, and import-linter errors on a dotted path that doesn't resolve to
  anything on disk at all (as opposed to an empty result). Added an empty
  placeholder package (docstring only, zero code) for this reason alone.

## Contract tests: what was brought over, what wasn't

`tests/contract/` isn't in the copy instructions explicitly, but the source
repo's suite is worth mining selectively. Copied, and passing (27/27):
`test_api_module_facades.py`, `test_consumer_uniqueness.py`,
`test_currency_column_width.py` (schema-only entity inspection — works
because the schema-only modules' entities are present), `test_kyb_interface.py`,
`test_migration_discovery.py` (validates exactly the migration-registration
invariants this document describes — genuinely useful here), and
`test_no_conflict_markers.py`.

**Not copied**, all for the same underlying reason — they assert facts about
the *complete* real platform, not a deliberately-pruned subset of it, and
would need to be rewritten rather than "adjusted":

- `test_advisory_lock_keys.py` — a ratchet test asserting a specific,
  hardcoded set of known advisory-lock key collisions found across the
  *entire* codebase; this checkout's smaller file set naturally finds fewer.
- `test_module_independence.py` — same ratchet pattern for known dependency
  cycles (`KNOWN_CYCLES`); several of the cataloged cycles involve
  out-of-scope modules' application code and no longer exist here.
- `test_event_flow.py` — exercises the reconciliation/settlement-lifecycle
  consumers removed from `bootstrap.py` above.
- `test_idempotency_middleware_wiring.py` — checks that specific
  `/api/v1/{ledger,settlement,payments}/...` routes exist and are documented;
  those routers aren't present.
- `test_import_contracts.py` — checks that `importlinter.ini` itself is
  complete (every module listed as a policed source in every other module's
  privacy contract, every module has its own contract section). It correctly
  flags the pre-existing `gateway` integration gap described above
  (`gateway` has no privacy contract, and isn't listed as a source in
  several others') — genuine, but not something to paper over by guessing
  the right contract for a module this checkout didn't write.

If you extend this checkout to fix the `gateway`/`importlinter.ini` gap
directly (add a `gateway-internals-are-private` contract, add
`app.modules.gateway` to every other module's `source_modules`), that test
can come back.

## What you'll need to add yourself

- **Redis / Kafka / Temporal**: not required for anything verified above.
  `docker-compose.yml` still defines all of them if you want the full stack.
- **`LEDGER_RO_DB_PASSWORD` / `SETTLEMENT_RO_DB_PASSWORD` / `AUDIT_RO_DB_PASSWORD`**:
  generate your own (`openssl rand -hex 24`), put them in `backend/.env`
  (never committed).
- **GCP audit sink credentials**: `GCP_PROJECT_ID`, `AUDIT_BUCKET_NAME`,
  `SERVICE_ACCOUNT_EMAIL`, `LOG_SINK_LOGGER_NAME` need *some* value (real or
  dummy) or `app.platform.audit_framework.config` raises `KeyError` at
  import time — see `.env.example`.
