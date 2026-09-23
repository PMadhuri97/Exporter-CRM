# Epic 4 Reference — ANER Fintech Platform

**This is the ongoing personal working copy for the Exporter CRM & Financing Intake build**,
scoped to the Epic 4 (Client/Ops Interface) modules from the ANER fintech platform, plus
`compliance` (where screening logic actually lives in this codebase). Originally pulled from the
reconciled `feature/epic4-onboarding-orchestration` branch of the company's platform monorepo
(private `Aner-Group/fintech-platform`, never pushed back there and never containing that repo's
commit history — this repo started from a single fresh commit, deliberately excluding
company-proprietary modules unrelated to this work: `ledger`, `settlement`, `rails`, `fx`,
`reconciliation`, `payments`, `reporting`, `orchestration` have schema-only migrations here, no
business logic).

New work for the Exporter CRM PRD (see the implementation plan) is built and committed **directly
in this repo going forward** — it is no longer a disposable, re-copied snapshot.

## This runs — see RUNNING.md

`app/platform/`, `app/shared/`, `alembic.ini` / `migrations/`, `requirements.txt`, `conftest.py`,
`Dockerfile` and the rest of the platform infrastructure needed to actually boot are present:
`alembic upgrade head`, the FastAPI app, and most of the test suite run against a plain Postgres
instance. **See [`RUNNING.md`](RUNNING.md)** for how to start it, exactly which modules have
business logic vs. schema-only tables and why, and the caveats found during verification.

## The business context this code exists for

The platform's first real workflow is **RXIL** — an Indian invoice/receivables marketplace
where ANER participates as a financier. RXIL pushes invoice and counterparty data in (already
filtered — e.g. below a rupee threshold); a human (currently the CEO) reviews it; only after
that does anything proceed to a separate, not-yet-built **underwriting** module. Nothing here
assumes live settlement, payments, FX/corridor logic, or ledger accounts exist yet — that is
deliberate, not an oversight. Every module below was scoped to stop short of that boundary.

## What's in this snapshot

| Module | Epic | What it does | Status |
|---|---|---|---|
| `onboarding` | 4.1 | Verifies a business entity: schema, KYB registry, risk rating, the service API, plus AL-672's Temporal workflow (merged from the platform team, not built here) | Partial — see Gaps below |
| `kyb` | 4.1 (S2) | Vendor-agnostic KYB adapter interface + real Middesk/Trulioo adapters, empty Decentro placeholder | Built, **not wired to `onboarding`** |
| `cases` | 4.3 | Compliance/ops case management: intake → evidence → assignment/notes → resolution (maker-checker stand-in) → SLA monitoring → query interface | Built and review-clean for the RXIL flow |
| `customers` | 4.2 | Lifecycle/re-KYC schema | Schema only — built by a different team, in progress elsewhere |
| `notifications` | 4.6 | A minimal notification queue, currently wired only to `payments` | Prototype, not connected to `cases` or `onboarding` |
| `gateway` | 4.4 | External API gateway skeleton — correlation IDs, request logging, health check, version routing | **Deliberately paused.** No external customer exists yet to call an API; resume once underwriting produces a real customer-facing need |
| `compliance` | 3.1/3.2-adjacent | Screening, rule engine, sector risk — included because screening logic lives here, not in a dedicated Epic 3.2 module | Pre-existing, not modified as part of this work |

## Architecture patterns worth noting

- **Consumer-owned `Protocol` ports, not inherited ABCs.** `kyb`'s `KYBAdapter`, AL-672's
  `RiskRater`/`Screener`/`EntityVerifier` in `onboarding/domain/workflow_dependencies.py` — all
  structural typing. An adapter satisfies the contract without importing it, keeping the
  dependency arrow pointing one way.
- **Module facade isolation, enforced by import-linter, not just convention.** Every module's
  `__init__.py` is its only import surface; `importlinter.ini` has an
  `<module>-internals-are-private` contract per module, checked by a contract test that fails
  loudly (not silently) if a new module skips it — this happened once during this work (`cases`
  shipped without one) and was caught and fixed.
- **Append-only audit trails at the DB level, not just application discipline.** `case_timeline_event`,
  `onboarding_event` reject UPDATE/DELETE via Postgres triggers, verified by tests that attempt
  the violation directly via SQL — the standard this codebase holds itself to for anything
  audit-relevant (BUILD.md #12: every DB constraint gets a test that violates it via direct SQL).
- **Idempotency via a shared platform primitive** (`app.platform.idempotency`), not ad hoc unique
  columns — `register_key`/`complete_key` against a `(key_value, scope_id)` pair, used
  consistently across `kyb`'s vendor registry and `onboarding`'s request initiation.
- **Deliberately decoupled from unbuilt/unrelated epics.** Neither `onboarding` nor `cases`
  imports `ledger`, `settlement`, `rails`, `fx`, `reconciliation`, `payments`, or `orchestration`
  — verified by grep at every stage of this work, not assumed.

## Gaps — what's missing for this to be a complete onboarding pipeline

Ranked by what actually blocks an end-to-end flow, not by story number.

1. **No composition root wires real dependencies into the Temporal workflow.**
   `onboarding/infrastructure/adapters/unavailable_workflow_dependencies.py` is still the only
   factory for `OnboardingWorkflowDependencies` — meaning even though `ConfigDrivenRiskRater`
   (a real, tested risk-rating adapter) and the real Middesk/Trulioo KYB adapters exist, **nothing
   in the running application actually constructs and passes them to the workflow.** This is the
   single highest-value next step — everything else being "built" doesn't matter operationally
   until this wiring exists.

2. **No `Screener` implementation exists at all**, and this is by design, not an oversight:
   Epic 3.2 (the real screening service) doesn't exist, and RXIL provides its own AML/CFT
   screening result rather than ANER running screening itself. Building a fake `Screener` would
   mean inventing screening logic that doesn't belong in this codebase yet. The right fix is
   deciding how RXIL's screening result reaches the workflow — not writing a stub.

3. **`cases` and `onboarding` are siloed with no bridge.** A resolved case (the CEO's
   approve/reject decision) currently writes only to `compliance_case` — nothing signals the
   onboarding Temporal workflow's `ComplianceDecisionReceived` signal. This gap is structural:
   the two modules were deliberately kept import-free of each other all the way through. Closing
   it needs an explicit integration decision (an internal event bus — the one piece of Epic 4.6
   that might matter before the rest of it does — or a direct call, which would mean relaxing the
   module-isolation rule on purpose).

4. **S4 (UBO Mapping and Document Collection) isn't built.** AL-672's `activities.py` has
   Protocol-shaped placeholders (`UboMapper`, `DocumentChecklist`) waiting for it, but the actual
   iterative UBO resolution, KYC individual verification, and document-completeness logic don't
   exist.

5. **A confirmed bug in AL-672 itself** (found during reconciliation, not introduced by this
   work): the Temporal workflow has no transition path for a screening `REVIEW_REQUIRED`
   outcome — only `HARD_BLOCK` is branched on; anything else silently falls through to
   `SCREENING_COMPLETE` as if it were clear. Needs a decision from whoever owns Epic 4.1's S3,
   not a silent patch.

6. **No HTTP/API layer exists for `cases`.** Its nine `application/` modules — lifecycle,
   transitions, notes, queries, SLA monitoring, evidence aggregation — are real, tested Python,
   callable from other Python code and from tests, and reachable over a network from nowhere.
   `app/api/rest/router.py` includes no cases router because `app/modules/cases/` has no `api/`
   package to include. `gateway` (4.4) is not the answer here; that's the *external*,
   customer-facing surface, deliberately paused. What's needed is a much thinner *internal*
   router (assign a case, propose/decide a resolution) for whatever internal tool — a frontend,
   an ops script — needs to call it.

   **`onboarding` is no longer in this gap.** It has two mounted routers —
   `app/modules/onboarding/api/router.py` (417 lines) and `api/exporter_router.py` (527 lines) —
   both included under `/api/v1/onboarding` by `app/api/rest/router.py`. A frontend has shipped
   against them.

7. **S6 (ledger account creation) is deliberately skipped**, not missing by accident — a
   product decision to hold off on anything that creates a live financial account until
   underwriting exists downstream.

8. **Two real S1 schema bugs were found and have since been fixed** on the real branch (not yet
   reflected in this snapshot's Jira docs, which describe the original intended schema): a
   mislabeled `kyb_result` column (it held screening results, not KYB results — renamed to
   `screening_result`) and two missing columns (`edd_required`, `edd_reason`) that are now real,
   persisted fields rather than values embedded in a JSON blob. Fixed via
   `onboarding_0004_screening_fix`, verified upgrade → downgrade → upgrade against a live
   Postgres.

## Recommended next step

*(The previous version of this section said to build the internal API layer for `cases` and
`onboarding` "before frontend work starts". That has been overtaken: `onboarding`'s routers
exist and a frontend has shipped against them — nine of the ten EXP-F tickets are built. Kept
here only so the change of direction is visible.)*

Build the thin internal API layer for `cases` (item 6 above). It is now the only module in this
checkout with a full application layer and no way to reach it, and the asymmetry is the point:
`onboarding` got its router and immediately grew a real frontend consumer, while `cases`'
lifecycle, SLA and evidence services have no caller outside their own tests. Anything that wants
to act on a case — the compliance console the blueprint describes, an ops script, the
onboarding↔cases bridge in item 3 — is blocked on it.
