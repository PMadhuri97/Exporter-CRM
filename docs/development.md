# Developing the Exporter CRM

How to run the system locally, test it, change its schema and its API, and what
"green" means here. For what the system is, read [`architecture.md`](architecture.md);
for why this checkout contains more than the CRM, [`../RUNNING.md`](../RUNNING.md).

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
for anything you show people** (see [`demo.md`](demo.md)).

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
`backend/.local-storage`, git-ignored) and `SELF_SERVICE_SIGNUP_ENABLED=false` (turns
`POST /api/v1/auth/register` off; it only ever grants `API_USER`, which reaches nothing
in the CRM).

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
with no account. Roles: `ADMIN`, `COMPLIANCE`, `OPERATIONS`, `DEVELOPER` (read-only) and
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
baseline (§9) before a merge.** There is no CI (decision U6 is open), so run them by
hand.

```bash
cd backend
python -m alembic heads                                   # exactly one
python -m pytest -q --no-cov -p no:cacheprovider          # ~15 minutes
ruff check .
lint-imports --config importlinter.ini                    # the --config flag is required

cd ../frontend
pnpm exec tsc -b --noEmit
pnpm exec eslint .
pnpm exec vitest run
pnpm build
```

- `--no-cov` and `-p no:cacheprovider` keep a run from writing `htmlcov/`, `.coverage`
  and `.pytest_cache` into the tree; a baseline is about pass/fail.
- `lint-imports` without `--config importlinter.ini` finds no configuration and fails.
- **Do not run Prettier over existing files**: there is no Prettier configuration, and
  the code is hand-formatted (single quotes, ~100 columns).
- The contract tests in `backend/tests/contract/` guard the repository itself: every
  mounted route is classified by role (`test_route_authorization_coverage.py`), the
  committed OpenAPI document matches the served one (`test_openapi_artifact_is_current.py`),
  and the ORM matches the `onboarding` schema (`test_orm_matches_the_onboarding_schema.py`).
- `app/modules/onboarding/tests/integration/test_crm_end_to_end.py` walks the whole
  main path through the API, with nothing substituted.

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

Measured 29 September 2026:

| Gate | Baseline |
|---|---|
| Backend suite | **26 failed, 4,523 passed, 7 skipped, 5 errors** — every failure listed below |
| `ruff check .` | 16 findings, all pre-existing: two auto-generated Alembic merge revisions and two package index files |
| `lint-imports` | 19 contracts kept, 0 broken |
| `alembic heads` | one: `onboarding_0021_verif_review` |
| Frontend | `tsc` clean; eslint 0 errors, 2 warnings (`AuthContext.tsx`); vitest 27 files, 270 tests; build passes with a >500 kB chunk warning |

The known backend failures — anything else is new:

| Failing | Cause |
|---|---|
| 22 tests in `compliance/tests/integration/test_compliance.py`, `test_screening_uses_rule_registry.py` and `audit/tests/integration/test_audit.py`, and 5 errors in `test_compliance.py` | They create a payment or an FX quote first, and those routers are deliberately not mounted in this checkout ([`../RUNNING.md`](../RUNNING.md)), so the request gets 404 |
| `onboarding/.../test_l4a_background_check_schema.py::test_0015_parents_onto_0019_and_the_chain_has_one_head` and `::test_the_database_is_at_0015` | Stale: they pin migration 0015 as the head, which it stopped being when later migrations landed |
| `onboarding/.../test_l3a_conversation_gauge.py::test_a_check_back_date_in_the_past_is_refused` | Time-zone dependent: the test takes the local date, the service the UTC date, so it fails between local midnight and UTC midnight (00:00–05:30 in India) |
| `platform/authorization/tests/test_role_management.py::test_last_role_manager_cannot_be_demoted_by_a_non_admin_user_editor` | Environment: the test sets aside only the first 200 active ADMIN accounts, so on a database holding more (left by earlier runs) other role managers remain and the guard rightly allows the demotion |
| `platform/idempotency/tests/test_expiry_sweep.py::test_sweep_can_use_the_partial_ck_index` — **sometimes** | It asserts a query plan, which depends on the size and statistics of the database |

Two environment traps turn a clean run red: without `google-cloud-logging` and
`google-cloud-storage` (both in `requirements.txt`) collection stops with two
`ModuleNotFoundError`s; and if the read-only role passwords in `.env` no longer match
the database, about two dozen idempotency and audit tests fail with "password
authentication failed".

## 10. Migrations

Rules (details in [`../backend/migrations/README.md`](../backend/migrations/README.md) and
[`contracts/migration-register.md`](contracts/migration-register.md)):

- **One chain, one head.** A new migration's `down_revision` is the current head. If
  two land at once, the later one re-parents; never add a merge revision.
- **Revision ids are 32 characters or fewer** (`alembic_version.version_num`).
- **Never `ALTER TYPE … ADD VALUE` in an autocommit block.**
- **Register a new migrations directory in `alembic.ini`** (one line);
  `test_migration_discovery.py` checks it.
- **Every new constraint gets a direct-SQL test** that tries the violation.
- **Declare every index and constraint on the model too**; otherwise
  `alembic revision --autogenerate` proposes dropping it, and
  `test_orm_matches_the_onboarding_schema.py` fails.
- **Round-trip it** before merging: `alembic upgrade head`, `alembic downgrade -1`,
  `alembic upgrade head`. A lossy downgrade says so in its docstring.
- **Add the row to the migration register.** The next free onboarding number is there.

## 11. Where things are documented

| Document | What it is |
|---|---|
| [`architecture.md`](architecture.md) | The CRM: model, state machines, roles, ownership, decisions, limitations |
| [`demo.md`](demo.md) | How to demonstrate it |
| [`contracts/`](contracts/) | What each part promises the others |
| [`module-rule-exceptions.md`](module-rule-exceptions.md) | The one recorded exception to the module rule |
| [`Exporter-CRM-Architecture-and-Plan.pdf`](Exporter-CRM-Architecture-and-Plan.pdf) | The design the CRM was built from (v1.0) |
| [`dev4/`](dev4/) | Developer 4's task documents — the only record of some of 4B's decisions |
| [`../RUNNING.md`](../RUNNING.md) | Why this checkout contains more than the CRM, and what was pruned |
