# Developing the Exporter CRM

How to run the system locally, test it, change its schema and its API, and what
"green" means here. For what the system is, read [`architecture.md`](architecture.md);
for why this checkout contains more than the CRM, §12.

---

## 1. Prerequisites

- **Python 3.12** for the backend (no virtualenv is checked in; make your own at
  `backend/.venv`).
- **Node 20+ and pnpm** for the frontend (`packageManager` is pnpm 10). Where `pnpm` is
  not on your `PATH`, `npx` runs the same tools.
- **PostgreSQL 16.** The simplest is the repository's compose service.

## 2. Database

```bash
docker compose up -d postgres        # repo root: postgres:16, database aner_settlement,
                                     # user aner, published on localhost:5433
```

Nothing else in `docker-compose.yml` (Temporal, Kafka/Redpanda, the observability stack)
is needed: with `TEMPORAL_ENABLED`, `KAFKA_ENABLED`, `EVENT_CONSUMERS_ENABLED` and
`OTEL_ENABLED` at their defaults (`false`) the app runs against Postgres alone.

**The test suite writes to the database your `.env` names.** A database you run the
suite against fills up with test companies, users and deals — some in states the
product cannot produce, because tests set them up directly. Use a **separate database
for anything you show people**, loaded with the sample data (§5).

## 3. Backend

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate      # Windows; .venv/bin/activate elsewhere
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
```

In `backend/.env`, set at least:

| Setting | Why |
|---|---|
| `DATABASE_URL`, `DATABASE_SYNC_URL` | Point at your Postgres. The example uses the compose host name `postgres:5432`; from your own machine it is `localhost:5433`. |
| `LEDGER_RO_DB_PASSWORD`, `SETTLEMENT_RO_DB_PASSWORD`, `AUDIT_RO_DB_PASSWORD` | Three migrations create read-only login roles with these and refuse to run without them (`openssl rand -hex 24` each). |
| `GCP_PROJECT_ID`, `AUDIT_BUCKET_NAME`, `SERVICE_ACCOUNT_EMAIL`, `LOG_SINK_LOGGER_NAME` | The audit framework reads them at import time; any value will do locally. |
| `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD`, `FIRST_COMPLIANCE_EMAIL` / `FIRST_COMPLIANCE_PASSWORD` | The first accounts (§4). |
| `APP_NAME` | Leave it at `Business Platform`: it becomes the OpenAPI title, and the committed `openapi.json` is compared whole (§8). |

Optional: `STORAGE_LOCAL_ROOT` (where uploaded documents go; default
`backend/.local-storage`, git-ignored) and `SELF_SERVICE_SIGNUP_ENABLED=true` (turns
`POST /api/v1/auth/register` on; off by default, and it only ever grants `API_USER`,
which reaches nothing in the CRM).

Security settings (see `.env.example`; `platform/security/startup_checks.py`):

- `JWT_SECRET_KEY` — signs access tokens. Outside `local`/`test` the server refuses to
  start with the built-in default or a key under 32 characters (`development` is not
  exempt).
- `API_DOCS_ENABLED` — the Swagger UI below and `/api/v1/openapi.json`. Unset, they are
  served only where `ENVIRONMENT` is `local` or `test`; set `true` to see them with
  `ENVIRONMENT=development`. `pnpm generate:api` calls `app.openapi()` directly and is
  unaffected.
- `METRICS_BEARER_TOKEN` — what Prometheus sends to scrape `/metrics`; without it
  `/metrics` is a 404 outside `local`/`test`.
- `CORS_ALLOWED_ORIGINS` — empty (no CORS) is right when the front end is served from
  the API's origin, as it is through the vite proxy and the load balancer.
- `LOGIN_MAX_FAILED_ATTEMPTS` / `LOGIN_LOCKOUT_MINUTES` (5 / 15) — after that many wrong
  passwords in a row an account answers 429 until the lockout ends or an administrator
  resets its password.
- `CRM_DOCUMENT_SCANNER` — `pass-through` (checks nothing; logged as an error at start-up
  outside `local`/`test`) or `clamav`, which streams each upload to clamd at
  `CLAMAV_HOST`:`CLAMAV_PORT` and leaves it `SCAN_FAILED` (never served) when clamd cannot
  answer. Every upload's bytes must also match its declared type, or it is refused (422).

Document previews: `CRM_DOCUMENT_CONVERTER` (default `soffice` — LibreOffice, run
headless, which turns a Word, Excel, PowerPoint or CSV document into the PDF people read
on screen; the backend image installs it) and `CRM_DOCUMENT_CONVERTER_TIMEOUT_SECONDS`
(default `60`). Without LibreOffice on your machine those files show "Preview
unavailable"; PDFs, images and text files are unaffected, and downloads work as before.
A document that links outside itself (a linked image, an INCLUDETEXT field, an external
workbook) is never converted, and the converter runs with an empty environment; outside
local development, run it where the server's secrets are not ([`remaining-work.md`](remaining-work.md) §2).

Bank accounts: `FIELD_ENCRYPTION_KEYS` (see `.env.example`) encrypts account numbers
and IBANs; without it, saving bank details answers 503 unless `ENVIRONMENT` is `local` or
`test`. `CRM_BANK_CHANGE_APPROVAL_MODE` (default `SECOND_PERSON`; also `PERMISSION_HOLDER`,
`BOTH`, and `OFF` in local/test only) decides who approves a proposed account.
Sanctions: `CRM_SANCTIONS_TRUE_MATCH_APPROVAL` (default `SECOND_OFFICER`; `HEAD` needs
`compliance:approve_true_match`, held by the Compliance lead; `SINGLE` in local/test only)
decides who confirms a true match.
Contacts: `CRM_CONTACT_REVERIFY_MONTHS` (default `12`) marks a contact "Verification due".

Compliance engine (`onboarding/application/compliance_settings.py`):
`CRM_BACKGROUND_CHECK_MAKER_CHECKER` (default `true`: CLEAR, FLAGGED and ON_HOLD need a
second COMPLIANCE user; `false` is accepted only where `ENVIRONMENT` is `local` or
`test`, and the server refuses to start with it off anywhere else — including
`development`, the default, so set `ENVIRONMENT=local` on your machine to turn it off),
`CRM_BACKGROUND_CHECK_CLEAR_VALIDITY_DAYS` (default 365: how long a new Clear stays
current; at least 1) and `CRM_REKYC_DUE_WINDOW_DAYS` (default 30: how far ahead "Re-KYC
due" looks).

```bash
python -m alembic upgrade head        # the schema
python -m alembic heads               # must print exactly one revision
python -m uvicorn app.main:app --reload
# http://localhost:8000/api/v1/docs  Swagger UI
# http://localhost:8000/api/v1/health
```

## 4. Accounts

```bash
python -m app.platform.authentication.cli bootstrap                    # first ADMIN + COMPLIANCE, from .env
python -m app.platform.authentication.cli promote someone@example.com OPERATIONS
```

`bootstrap` is idempotent and refuses a blank password; `promote` refuses an address
with no account. Both refuse, before writing anything, an address the sign-in form
would refuse (`EmailStr`): a special-use domain such as `.local`, `.test` or
`localhost` would make an account that can never sign in, so use a real-looking
domain (`admin@example.com`). Roles: `ADMIN`, `COMPLIANCE`, `OPERATIONS`, `DEVELOPER` (read-only) and
`API_USER`. Once an ADMIN exists, further users can be created from the Settings screen.

## 5. Sample data

```bash
python -m app.modules.onboarding.sample_data
```

Brings seven fixed companies to the states of architecture §3.9 through the real
services — nothing is written directly: A is a prospect who said "not now"; B is a
customer (its check is `CLEAR`) with two deals, one handed over; C is a prospect whose
check is `FLAGGED`, with an open deal; D is `NOT_QUALIFIED` and paused; E has ended; F
is a new lead; G shares B's GSTIN (a duplicate warning). Company ids are fixed
(`uuid5`), and a repeat run changes nothing and reports zeros. Each owner seeds its
own part from its own hook (`sample_data_*.py`).

Migration `0014` refuses to empty the CRM's tables when they hold rows; set
`E9_ALLOW_CRM_RESET=1` only if you mean to start a database's CRM over.

## 6. Frontend

```bash
cd frontend
pnpm install
pnpm dev            # http://localhost:5173 — /api is proxied to http://localhost:8000
```

## 7. Tests and gates

Run from `backend/` and `frontend/` respectively. **Every one of these must be at the
baseline (§9) before a merge.** There is no CI yet ([`remaining-work.md`](remaining-work.md) §2), so run them
by hand.

```bash
cd backend
python -m alembic heads                                   # exactly one
python -m alembic check                                   # no model/database drift
python -m pytest --crm -q --no-cov -p no:cacheprovider    # the CRM suite (below)
ruff check .
lint-imports --config importlinter.ini                    # the --config flag is required

cd ../frontend
pnpm exec tsc -b --noEmit
pnpm exec eslint .
pnpm exec vitest run
pnpm build
```

- **`--crm` runs the CRM suite**: the tests in `app/modules/onboarding/tests` and the
  repository guards in `tests/contract`, about half the tests in the checkout. It leaves
  out every other module's tests (the module rule means a CRM change edits none of those
  modules) and the legacy `onboarding_request` path in the same module, Temporal workflow
  included, which nothing in the CRM uses. The excluded legacy files are listed in
  `backend/conftest.py` (`_LEGACY_ONBOARDING_TESTS`).
- **Run the whole suite** — the same command without `--crm` — only when a change
  reaches outside the CRM: anything in `app/platform`, `app/shared`, `app/main.py`,
  `migrations/env.py`, another module, or one of the legacy files. While fixing, run just
  the test files for the code you changed, and the CRM suite once at the end.
- `--no-cov` and `-p no:cacheprovider` keep a run from writing `htmlcov/`, `.coverage`
  and `.pytest_cache` into the tree; a baseline is about pass/fail.
- `lint-imports` without `--config importlinter.ini` finds no configuration and fails.
- `alembic check` compares every model with the database it points at, so run it
  against a database at head. Tables a migration creates with no model behind them are
  listed in `migrations/env.py` (`UNMODELLED_TABLES`).
- Tests that cannot pass in this checkout are marked as **expected failures** in
  `backend/conftest.py` (`_NEEDS_UNMOUNTED_PAYMENT_ROUTES`) — never by editing the
  module they belong to. The marks are strict: one that starts passing fails the run
  until it is taken off the list.
- **Do not run Prettier over existing files**: there is no Prettier configuration, and
  the code is hand-formatted (single quotes, ~100 columns).
- The contract tests in `backend/tests/contract/` guard the repository itself: every
  mounted route is classified by role (`test_route_authorization_coverage.py`), the
  committed OpenAPI document matches the served one (`test_openapi_artifact_is_current.py`),
  and the ORM matches the `onboarding` schema (`test_orm_matches_the_onboarding_schema.py`).
- `app/modules/onboarding/tests/integration/test_crm_end_to_end.py` walks the whole
  main path through the API, with nothing substituted.
- **"Now" in new code comes from `app/shared/clock.py`** (`clock.now()`, timezone-aware
  UTC), never an inline `datetime.now(...)`. A test moves time with
  `with use_clock(FixedClock(at)):` — no sleeping, no patching `datetime`.
- **Two compliance users (maker-checker is on in tests).** `CLEAR`, `FLAGGED` and
  `ON_HOLD` are proposed by one COMPLIANCE/ADMIN user and approved by another. A test takes a company there with the helpers in
  `app/modules/onboarding/tests/fixtures/compliance.py`: `approve_as(checker, company,
  maker=…)` (services), `propose_and_approve(client, company, maker_token=…,
  checker_token=…)` (HTTP), and `record_required_checks(company)` for rule B's KYB, AML
  and sanctions. A test of code that *reads* compliance (the handover guard) can use
  `StaticComplianceFactsReader` / `party_facts(...)` from the same module, a fake of the
  published `ComplianceFactsReader`. `CRM_BACKGROUND_CHECK_MAKER_CHECKER=false` is
  accepted only where `ENVIRONMENT` is local or test — the server refuses to start with it
  off anywhere else, `development` included.

## 8. Changing the API

Every new or changed route:

1. declares its roles (`require_role(...)`) and documents its `403`;
2. gets a row in `backend/tests/contract/test_route_authorization_coverage.py` **and** in
   `app/modules/onboarding/tests/integration/test_route_authorization.py`;
3. is followed by regenerating the frontend's API types, with the backend virtualenv
   active (the first step runs `python`):

```bash
cd frontend
pnpm generate:api        # writes openapi.json and src/lib/api/schema.ts — commit both
```

`test_openapi_artifact_is_current.py` compares the whole document, including
`info.title`, which comes from `APP_NAME`: regenerate with `APP_NAME` at its default or
the test fails for everyone else.

A contract in `docs/contracts/` changes only with the agreement of its owner and its
users; change the contract in the same pull request as the code.

## 9. Baseline

Measured 14 October 2026 on `fix/migration-crm`, on fresh databases at head; the whole
suite was last measured on 4 October 2026:

| Gate | Baseline |
|---|---|
| CRM suite (`pytest --crm`) | **3,602 passed, 1 skipped, 0 failed** (about 30 minutes in three parallel chunks, each on its own database). The skip is the symlink test in `test_local_disk_storage.py`, which Windows refuses without developer mode |
| Whole suite (without `--crm`, 4 October 2026) | **5,350 passed, 7 skipped, 27 xfailed, 0 failed, 0 errors** (36 minutes) |
| Temporal workflow tests (`test_onboarding_workflow*.py`, whole suite only) | Pass within the whole suite. They download the Temporal test server, so they need internet access; the opt-in restart suite needs `RUN_RESILIENCE_TESTS=1` |
| `ruff check .` | clean on the CRM and the contract tests; elsewhere only pre-existing findings in two auto-generated Alembic merge revisions and two package index files |
| `lint-imports` | 19 contracts kept, 0 broken |
| `alembic heads` | one: `onboarding_0059_deal_reference` |
| `alembic check` | no new upgrade operations |
| Frontend | `tsc` and eslint clean; vitest 80 files, 1,052 tests; `pnpm build` passes |

The 27 expected failures (whole suite only) are the tests in `compliance/tests/integration/test_compliance.py`,
`test_screening_uses_rule_registry.py` and `audit/tests/integration/test_audit.py` that
create a payment or an FX quote first: those routers are deliberately not mounted in this
checkout (§12), so the request gets 404. They are strict
expected failures in `backend/conftest.py` (§7); one that starts passing fails the run.
Any failure is new.

Three tests can still fail intermittently ([`remaining-work.md`](remaining-work.md) §2 lists them):
`platform/idempotency/tests/test_expiry_sweep.py::test_sweep_can_use_the_partial_ck_index`
asserts a query plan, which depends on the size and statistics of the database; and
`test_decision_evidence.py::test_new_decisions_record_the_current_rules_and_cycle`
reads two decisions that can share a `decided_at`; and
`test_buyer_migration_safety.py::test_a_created_company_gets_one_creation_row_saying_where_it_came_from`
breaks a `created_at` tie by a random id.

Two environment traps turn a clean run red: without `google-cloud-logging` and
`google-cloud-storage` (both in `requirements.txt`) collection stops with two
`ModuleNotFoundError`s; and if the read-only role passwords in `.env` no longer match
the database, about two dozen idempotency and audit tests fail with "password
authentication failed".

## 10. Migrations

Rules (details in [`../backend/migrations/README.md`](../backend/migrations/README.md) and
[`contracts/migration-register.md`](contracts/migration-register.md)):

- **Name it `onboarding_00NN_<lane>_<topic>`** — module, next free number, area of
  work, what it does. Keep the tail short; see the next rule but one.
- **One chain, one head.** A new migration's `down_revision` is the current head. If
  two land at once, the later one re-parents; never add a merge revision. Re-point
  `down_revision` and re-run `alembic heads` **before merging** — a branch that waited
  was written against a head that has moved.
- **Revision ids are 32 characters or fewer** (`alembic_version.version_num`). It is
  easier to breach than it looks: `onboarding_0023_domestic_criteria` is 33 and failed
  on the database partway through the migration.
- **`pg_dump` before any migration that changes data**, and say in its docstring how
  it rolls back and what it changes about rows that already exist.
- **Never `ALTER TYPE … ADD VALUE` in an autocommit block.**
- **Register a new migrations directory in `alembic.ini`** (one line);
  `test_migration_discovery.py` checks it.
- **Every new constraint gets a direct-SQL test** that tries the violation.
- **Declare every index and constraint on the model too**; otherwise
  `alembic revision --autogenerate` proposes dropping it, and
  `test_orm_matches_the_onboarding_schema.py` fails.
- **Drop a column one release after the code stops naming it.** A deploy replaces the
  running instances one by one, so the old release keeps serving against the new schema
  for a while. First release: declare the column in `__table_args__` as a `Column` and
  list it in `__mapper_args__["exclude_properties"]` — the table still matches the
  database and the ORM never names it. `deferred=True` is **not** enough: the ORM still
  inserts an explicit `NULL` into every mapped nullable column with no default. The next
  release's migration drops it (0060 and 0061 retired five columns this way). A table
  nothing reads or writes can go at once.
- **Merging into `main` deploys.** `.github/workflows/deploy-backend.yml` builds and
  rolls out the backend on every merged pull request that touches `backend/`, and the
  container runs `alembic upgrade head` before it serves.
- **Round-trip it** before merging: `alembic upgrade head`, `alembic downgrade -1`,
  `alembic upgrade head`. A lossy downgrade says so in its docstring.
- **Add the row to the migration register.** The next free onboarding number is there.

### 10.1 The data commands — safe execution

The buyer migration (`migrate_deal_buyers`) and the trade relationship backfill
(`backfill_trade_relationships`) are commands, not revisions, because a person reads
a report between reading and writing. Their order on a live database, and what must hold
before each, is [`remaining-work.md`](remaining-work.md) §1. This section is how to run
them without hurting anything.

**Rehearse on a scratch database first, every time.** Never run on a live database,
`aner_settlement` included, before the rehearsal on a copy of *that* database has passed. A scratch database for a rehearsal must be:

1. **A copy of the environment you will run on**, not a development database. Take it with
   `createdb -T <source> <scratch>` (it needs nobody connected to the source) or
   `pg_dump <source> | psql <scratch>`. Numbers from another database prove nothing about
   this one.
2. **At head.** Point **both** `DATABASE_URL` and `DATABASE_SYNC_URL` at the scratch
   database (the commands read the first, `alembic` the second) and run
   `alembic upgrade head`; `alembic current` must print the head in
   `contracts/migration-register.md`. Read the counts 0033 and 0035 print.
3. **Clean of the handover-snapshot precondition**: `SELECT count(*) FROM onboarding.deal WHERE stage =
   'HANDED_OVER' AND handover_snapshot IS NULL` is 0. `--validate` counts it too, and the
   migration does not repair it.
4. **Yours alone** while it runs, and dropped afterwards (`dropdb <scratch>`). It holds a
   copy of real company data, so it is treated like the source.

**Quiet settings.** With the development `.env` (`DEBUG=true`, `LOG_LEVEL=DEBUG`) the
engine echoes every statement and the report is lost in it; both commands say so on
stderr if they see it. Set `LOG_LEVEL=WARNING` and `DEBUG=false` for the run.

**Windows consoles.** Both commands print ASCII and replace anything the console cannot
encode (a company name in another script) with an escape such as `\u0141` for `Ł`, so a cp1252
console shows the report rather than crashing on it. For a report that keeps every name
exactly, write it to a file as UTF-8: `$env:PYTHONIOENCODING = 'utf-8'` in PowerShell (or
`PYTHONIOENCODING=utf-8` in Git Bash) and redirect the output to a file.

**The order, on the rehearsal and then on the live database:**

```bash
cd backend
export LOG_LEVEL=WARNING DEBUG=false     # PowerShell: $env:LOG_LEVEL='WARNING'; $env:DEBUG='false'
export DATABASE_URL=... DATABASE_SYNC_URL=...   # both at the database you mean; check twice

pg_dump ... > before-buyers.sql          # 1. the only way back: neither command undoes in place

python -m app.modules.onboarding.migrate_deal_buyers --dry-run > buyers-dry-run.txt   # 2. writes nothing
#    3. Compliance reads the report: "Needs a person" rows are not migrated until
#       confirmed; "Kept separate - review" and "Migrates, but review" rows are.
python -m app.modules.onboarding.migrate_deal_buyers --apply --run-id <id> \
    [--confirm-name <deal_buyer_id>=<company_id> ...]   # 4. lines as the report printed them
python -m app.modules.onboarding.migrate_deal_buyers --validate            # 5. every count 0, else exit 1
python -m app.modules.onboarding.migrate_deal_buyers --apply --run-id <id2> # 6. must create nothing

python -m app.modules.onboarding.backfill_trade_relationships --dry-run    # 7. only after 5 passes
python -m app.modules.onboarding.backfill_trade_relationships --apply --run-id <id3>
python -m app.modules.onboarding.backfill_trade_relationships --validate
```

- **Do not reorder.** The backfill creates a relationship for every deal that names a
  buyer company, so before the buyer migration it would cover only the deals named on the
  new deal page and miss the rest.
- `--apply` checks every `--confirm-name` before writing anything; one bad line refuses
  the whole run (exit 2). It re-reads each deal under a lock and skips one that has named
  a company since the report.
- `--validate` failing means stop: do not go on to the backfill.
- **`migrate_deal_buyers --rollback` writes nothing**; it reports what a run did. The dump
  is the only way back (decided 4 October 2026). The backfill's undo is one `DELETE`, which
  `--report-run` prints, as long as no invoice points at the run's relationships.
- Keep the dry-run report, the `--validate` output and the run ids with the migration
  ticket.

## 11. Where things are documented

| Document | What it is |
|---|---|
| [`architecture.md`](architecture.md) | The CRM: model, state machines, roles, ownership, decisions, limitations |
| [`contracts/`](contracts/) | What each part promises the others |
| [`module-rule-exceptions.md`](module-rule-exceptions.md) | The one recorded exception to the module rule |
| [`database.md`](database.md) | The database as built: schemas, tables, constraints, triggers and traps |
| [`remaining-work.md`](remaining-work.md) | The one open list: the live-database steps, open work, decisions awaited and what is deferred |
| [`../backend/migrations/README.md`](../backend/migrations/README.md) | How the migration chain is laid out |

## 12. What this checkout contains besides the CRM

The repository began as a pruned copy of ANER's platform monorepo, and the CRM has been
built in it since. Everything below is outside the CRM; the module rule means a CRM
change edits none of it.

**Kept in full** (application, API, domain, infrastructure): `onboarding` (the CRM, plus
the legacy `onboarding_request` path), `kyb`, `cases`, `customers`, `notifications`,
`gateway`, `compliance` (screening) and `audit` (generic infrastructure the legacy
onboarding code imports).

**Schema only** — `ledger`, `settlement`, `rails`, `fx`, `reconciliation`, `reporting`,
`orchestration`, `payments` belong to other epics and have no business logic here:

| Module | Has | Why |
|---|---|---|
| `ledger`, `settlement`, `fx`, `reconciliation`, `payments` | migrations, entities | `app/bootstrap.py` registers their ORM classes so relationships from kept modules resolve |
| `rails` | migrations, entities | `migrations/env.py` imports `rails` entities for autogenerate, so `alembic` cannot load without them |
| `reporting` | an empty migrations package | registered like every module's (`test_migration_discovery.py`) |
| `orchestration` | an empty package | owns no tables; it exists so `importlinter.ini`'s contracts resolve |

There is **one Alembic chain across every module** (`onboarding_0001_baseline` descends
from `audit_0001_baseline`, and merge revisions join heads across modules), so every
module's migrations are kept rather than rewriting history: tables such as
`ledger.ledger_account` exist with no code behind them, on purpose. `payments` keeps its
facade and `infrastructure/` because `audit`'s services import `TransactionRepository`
from it. `gateway` came from a sibling branch; the no-op merge revision `2807a84d72ba`
joins its head, and `importlinter.ini` still has no privacy contract for it.

**Removed from the wiring**: the Temporal worker (`TEMPORAL_ENABLED=true` is not
supported), the event consumers of `reconciliation` and `settlement`, the rail seed
loader, the `fx`, `ledger`, `payments`, `reconciliation` and `settlement` routers and the
idempotency-audit router (it imports ledger and settlement internals), and the background
jobs `app/main.py` ran for those modules. `gateway`'s routers are mounted directly in
`app/main.py`, outside `api_router` (`app/api/rest/router.py`). Their settings flags
(`RAIL_POLLING_ENABLED` and the like) still exist and are read by nothing.

**Contract tests not brought over**, because they assert facts about the complete
platform: `test_advisory_lock_keys.py`, `test_module_independence.py`,
`test_event_flow.py`, `test_idempotency_middleware_wiring.py` and
`test_import_contracts.py` (the last would rightly flag the missing `gateway` contract).

The platform modules' own one-line READMEs cite an `ARCHITECTURE.md` that belongs to the
monorepo this checkout came from.
