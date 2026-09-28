# Exporter CRM

An internal CRM for exporters combined with a verification and compliance record, built
for ANER as a financier. Staff find and qualify exporting companies, run the sales
conversation, record background checks, open deals, gather their paperwork, and hand
deals to the lending team. Companies arrive from staff research, CSV import, or RXIL —
an Indian receivables marketplace that sends exporters it has already filtered.

It is a **prototype**: real, tested end to end, and deliberately honest about what is
not real yet (a pass-through document scanner, local-disk storage, checks recorded by
hand). See [`docs/architecture.md`](docs/architecture.md) §12 before using it with real
data.

## Start here

| If you want to… | Read |
|---|---|
| Understand the CRM — its model, state machines, roles and ownership | [`docs/architecture.md`](docs/architecture.md) |
| Run it, test it, change its schema or API | [`docs/development.md`](docs/development.md) |
| Demonstrate it | [`docs/demo.md`](docs/demo.md) |
| Know what is still open, and who decides | [`docs/open-items.md`](docs/open-items.md) |
| Know exactly what one part promises the others | [`docs/contracts/`](docs/contracts/) |
| Know why this checkout contains more than the CRM | [`RUNNING.md`](RUNNING.md) |

## Quick start

```bash
docker compose up -d postgres                     # Postgres 16 on localhost:5433

cd backend                                        # Python 3.12, your own virtualenv
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env                              # then fill it in: docs/development.md §3
python -m alembic upgrade head
python -m app.platform.authentication.cli bootstrap
python -m app.modules.onboarding.sample_data
python -m uvicorn app.main:app --reload           # http://localhost:8000/api/v1/docs

cd ../frontend
pnpm install && pnpm dev                          # http://localhost:5173
```

## Layout

| Path | What it is |
|---|---|
| `backend/app/modules/onboarding` | The CRM: entities, migrations, services, routes and tests (plus a legacy onboarding path that is out of scope) |
| `backend/app/modules/{kyb,cases,customers,compliance,…}` | Other platform modules; the CRM uses some of them and edits none (the module rule) |
| `backend/app/platform` | Shared plumbing: authentication and roles, database, messaging, idempotency, observability |
| `backend/tests/contract` | Guards on the repository itself: route authorisation, the OpenAPI artifact, ORM ↔ schema, module facades |
| `frontend/src/modules/onboarding` | The CRM screens |
| `frontend/openapi.json`, `frontend/src/lib/api/schema.ts` | The generated API contract, committed and checked for drift |
| `deployments/gitops/reference-data` | Reference data loaded as settings (document types, compliance rules, …) |
| `docs/` | Architecture, development and demo guides, open items, the contracts, and the design PDF |
| `Jira/` | The Epic 4 specifications (4.1–4.4 and 4.6) the platform's onboarding, lifecycle, case, customer-API and notification modules were built from — not CRM requirements |

## Where it came from

This repository started from a pruned copy of ANER's platform monorepo (the Epic 4
client and operations modules, plus `compliance`), and the Exporter CRM has been built
in it directly since. Modules unrelated to the CRM — ledger, settlement, rails, FX,
reconciliation, payments — are present as schema only, so the one migration chain
still applies; [`RUNNING.md`](RUNNING.md) records what was kept, what was removed and
why. The CRM's design is
[`docs/Exporter-CRM-Architecture-and-Plan.pdf`](docs/Exporter-CRM-Architecture-and-Plan.pdf).
