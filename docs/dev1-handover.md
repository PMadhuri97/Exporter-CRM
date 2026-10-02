# Developer 1 (Compliance engine) — handover

| | |
|---|---|
| Date | 1 October 2026 |
| Branch | `feature/compliance-foundation` |
| Commits | `411d7da` F1 + P2 · `3d8f0ec` P3 · `4193c96` P4 · this PR: the final pass (concurrency, lifecycle e2e, consumer fake, fixes) |
| Scope | [`developer-allocation.md`](developer-allocation.md) §3, tasks F1 and 1.1–1.20 |
| Contract | [`contracts/background-check.md`](contracts/background-check.md) (§12 seam, §12.3 cycles, §12.4 facts, §12.5 maker-checker, §12.6 rule B, §12.7 expiry) |

Every Dev 1 task is built and tested. What is left is either **another lane's work that
switches Dev 1's behaviour on** (§2), **Dev 1 work that waits for that** (§3), or **a
decision for the lead** (§4). Nothing below is a known defect.

---

## 1. What is done

| Task | Plan id | Where | Tests |
|---|---|---|---|
| F1 | P0-2, P0-5 | migration 0023; `domain/compliance_inputs.py` (seam v2); `domain/compliance_facts.py` + `application/compliance_facts.py`; `promote_to_customer_if_ready` needs a current Clear; history dimensions; `app/shared/clock.py`; `tests/fixtures/compliance.py` | `test_dev1_foundation.py`, `unit/test_dev1_clock_and_facts_rules.py` |
| 1.1 | P2-1a | `application/decision_evidence.py`, `GET …/decisions/{id}/evidence` | `test_dev1_decision_evidence.py` |
| 1.2 | P2-1b | 0024 `screening_review_item.evidence_refs` | `test_dev1_screening_evidence.py` |
| 1.3 | P2-1c | `EvidenceList` in `ScreeningChecklist`, `DecisionHistory` | `ScreeningChecklist.test.tsx`, `DecisionHistory.test.tsx` |
| 1.4 | P2-2 | filters in `VerificationSection` | `VerificationSection.test.tsx` |
| 1.5 | P2-4a | 7-item checklist, `rules_version` | evidence + screening tests |
| 1.6–1.9 | P2-3a–d | 0025 `check_cycle`; cycle-scoped seam; `POST …/cycles`; cycle UI | `test_dev1_check_cycles.py` |
| 1.10–1.13 | P3-1a–d | 0026 proposals/resolutions; propose / approve / reject / withdraw; queue + Home card; two-user suite and seed | `test_dev1_maker_checker.py`, `unit/test_dev1_maker_checker_rules.py`, `BackgroundCheckApproval.test.tsx` |
| 1.14 | P3-2 | `ClearPolicy.required_passed_types = (KYB, AML, SANCTIONS)`; `required_checks` served | unit rules + integration |
| 1.15–1.17 | P3-3a–c | 0027 expiry + backfill; expiry in standing and facts; `GET /background-check/due`; badge + Home card | `test_dev1_clear_expiry.py` |
| 1.18 | P4-5 | `verification_result.about_company` / `.subject_company`; verification service, seam, router, decision evidence | `test_dev1_company_keyed.py` |
| 1.19 | P4-11 | no special-casing; never promoted | `test_dev1_company_keyed.py` |
| 1.20 | — | `CompanyComplianceSummary.tsx` full version | `CompanyComplianceSummary.test.tsx` |
| Final integration | §6 | concurrency: handover vs move, approval vs input, cycle vs decision | `test_dev1_concurrency.py` |
| Lane e2e | §2.2 | the lifecycle through the API; 401/403 on every Dev 1 route | `test_e2e_compliance_lifecycle.py` |

---

## 2. Handover to other lanes

### 2.1 Developer 2 — deals, handover, buyer migration

| Your task | What Dev 1 gives you | What you need to do |
|---|---|---|
| **F2** `deal.buyer_company_id` | — | Nothing Dev 1-specific. Buyer companies are ordinary company ids: their checks are recorded on the company itself (`entity_type = EXPORTER`, `entity_reference = company id`), which now sets `subject_company_id` automatically. |
| **2.4** buyer on the deal page | `CompanyComplianceSummary` (`props: { companyId }`), the one compliance summary: gauge with "Awaiting approval" / "Re-KYC due" badges, expiry, sanctions/AML, link to the company's background-check panel | Mount it for the seller and, when the deal names one, the **buyer company**. Keep `BuyerChecks` mounted **only** for deals whose buyer is still a `deal_buyer` row. |
| **2.5** guard conditions | `ComplianceFactsReader` (§5) and a fake for your tests: `StaticComplianceFactsReader`, `party_facts(...)` in `app/modules/onboarding/tests/fixtures/compliance.py` | Seller: `is_clear_current` — when false and `is_clear` is true, "the background check expired on `clear_expires_at`" (P3-3b). Seller with `sanctions`/`aml == "FAILED"` blocks (BQ-3). Buyer: `sanctions` and `aml` must both be `"PASSED"` (BQ-4) — `for_company(buyer_company_id)` when the deal names one, else `for_legacy_buyer(deal_buyer_id)`. Share-lock both company rows sorted by `customer_id` (P4-7). **Dev 1 does not touch the guard.** |
| **2.6** P4-6 buyer migration | `verification_result.subject_company_id`: nullable FK, **set once** (`NULL` → company), then frozen by `trg_verification_result_input_immutability` | Fill it on legacy `BUYER` rows from your map. From then on every read treats the row as the buyer company's check: inputs, facts, rule B, the company's verification list; later reviews go on the buyer company's timeline with `deal_id`. `buyer_checks` / `for_legacy_buyer` keep reading it for old deals. Do not touch `entity_type` / `entity_reference` / `subject_snapshot`. |
| **2.10** P4-10 retire `deal_buyer` writes | — | Tell Dev 1: `BuyerChecks.tsx` is then deleted (§3). |
| **2.12** main e2e | `test_crm_end_to_end.py` already uses two compliance users and records KYB/AML/SANCTIONS (a minimal Dev 1 edit, P3-1d) | Keep the `checker` token and the rule-B checks when you rewrite it. |

**Note for Dev 2's tests:** any test that clears a company now needs `record_required_checks(company_id)`
(rule B) and two users — `approve_as(checker, company, maker=…)` (services) or
`propose_and_approve(client, company, maker_token=…, checker_token=…)` (HTTP).

### 2.2 Developer 3 — company record

| Your task | Effect on Dev 1 |
|---|---|
| **F3 / P4-1** `pipeline_status` and `NOT_IN_PIPELINE ⇒ LEAD / NOT_YET_REVIEWED / NOT_CONTACTED`; qualification refuses `NOT_IN_PIPELINE` | This rule is **why a buyer-only company is never promoted** (promotion needs a `PROSPECT`). Dev 1 added no promotion rule of its own. The P4-11 tests (`_buyer_only_company()` in `test_dev1_company_keyed.py`) set `pipeline_status = 'NOT_IN_PIPELINE'` automatically once the column exists — re-run them after F3 merges. |
| **P4-9** onboard a buyer into the pipeline | A company already `CLEAR` (current) is promoted by the existing path when later `QUALIFIED`. Nothing to change. |
| `exporter_profile.background_check_expires_at` | Dev 1's column (F1) on your entity: the current Clear's expiry, written only by `BackgroundCheckService`. Please leave it to Dev 1. |

---

## 3. Dev 1 work that waits for another lane

| Item | Waits for | What to do |
|---|---|---|
| Concurrency: **handover vs a flag on the buyer company** | Dev 2's F2 + P4-7 (guard share-locks both companies) | Copy the pattern in `test_dev1_concurrency.py` (`_Pause` holds a transaction at a named method): pause the handover after its guard, flag the **buyer** company (propose + approve), assert the approval waits. The seller form is already proved. |
| Delete `components/BuyerChecks.tsx` (and its test, its export, `BUYER_CHECK_TYPES` if then unused) | Dev 2's P4-6 run everywhere + P4-10 | It is the only place a legacy `deal_buyer`'s sanctions/AML can be recorded, which BQ-4 needs until every buyer is a company. |
| Show "Not in pipeline" on the Re-KYC due list / Home card | Dev 3's F3 | Optional: the list serves `journey`; add `pipeline_status` to `ReKycDueCompanyResponse` when the column exists. |

---

## 4. Decisions for the programme lead

Recorded in [`open-items.md`](open-items.md) §1.1 (built on a recommendation; confirm or change):

1. REVIEW + REJECTED sanctions/AML reads as **FAILED** (`check_state`).
2. A new check cycle is refused while the current one is empty (`CHECK_CYCLE_EMPTY`).
3. Maker-checker details: the proposer cannot reject (only withdraw); nothing else moves the check while a proposal is open; any input change — including a company document passing its scan — makes a proposal stale; the queue is COMPLIANCE/ADMIN only; the approved decision's `decided_by` (and so the journey row and `company.became_customer`) names the proposer.
4. The expiry backfill uses the **last** CLEAR decision (BQ-5 literally).
5. `BuyerChecks.tsx` kept for legacy deal buyers until P4-10.

---

## 5. Integration contract — `ComplianceFactsReader`

```python
# app/modules/onboarding/domain/compliance_facts.py   (pure; no I/O)
class ComplianceFactsReader(Protocol):
    async def for_company(self, company_id: uuid.UUID, now: datetime) -> PartyComplianceFacts: ...
    async def for_legacy_buyer(self, deal_buyer_id: uuid.UUID, now: datetime) -> PartyComplianceFacts: ...

@dataclass(frozen=True)
class PartyComplianceFacts:
    background_check: BackgroundCheckValue   # the gauge; "NOT_STARTED" for a legacy buyer
    is_clear: bool                           # gauge == CLEAR (expired or not)
    clear_expires_at: datetime | None        # stored expiry; legacy Clear: decided + 365 days
    is_clear_current: bool                   # is_clear and now < clear_expires_at
    sanctions: CheckState                    # PASSED | FAILED | PENDING | MISSING
    aml: CheckState
```

Implementation: `ComplianceFactsService(db)` in `application/compliance_facts.py`. Read-only, never locks
(the caller locks). `now` must be timezone-aware — take it from `app.shared.clock.now()`.

| State | `background_check` | `is_clear` | `is_clear_current` |
|---|---|---|---|
| Never checked | `NOT_STARTED` | false | false |
| A CLEAR awaiting approval (gauge does not move) | `IN_REVIEW` | false | false |
| The CLEAR proposal rejected | `IN_REVIEW` | false | false |
| Approved, within validity | `CLEAR` | true | **true** |
| Approved, past `clear_expires_at` (no automatic gauge move) | `CLEAR` | true | false |
| Re-KYC started (new cycle reopens the Clear) | `IN_REVIEW` | false | false |
| Flagged / on hold | `FLAGGED` / `ON_HOLD` | false | false |

`sanctions` / `aml`: the latest non-placeholder result of that type in the company's **current cycle**,
company-keyed (its own results and any legacy buyer result mapped to it): `PASSED`, or `REVIEW` with an
`ACCEPTED` review → `PASSED`; `FAILED`, or `REVIEW` with a `REJECTED` review → `FAILED`; unreviewed
`REVIEW` / `PENDING` → `PENDING`; none → `MISSING`. `for_legacy_buyer` reads the `deal_buyer`'s own
results, without cycles.

Testing a consumer:

```python
from app.modules.onboarding.tests.fixtures.compliance import StaticComplianceFactsReader, party_facts

reader = StaticComplianceFactsReader(
    companies={seller: party_facts(), buyer: party_facts("NOT_STARTED", sanctions="FAILED")},
    legacy_buyers={deal_buyer_id: party_facts("NOT_STARTED", aml="MISSING")},
)
expired = party_facts(clear_expires_at=at, is_clear_current=False)   # an expired Clear
```

---

## 6. Deploying

**Migrations, in order** (one head; next free number **0028**; details in
[`contracts/migration-register.md`](contracts/migration-register.md)):

| Revision | Data | Downgrade |
|---|---|---|
| `onboarding_0023_dev1_foundation` | none | lossy since P4-5/P3-3a (drops every result's subject company and every current expiry; both re-derivable) |
| `onboarding_0024_dev1_evidence` | none (DDL default) | lossy (screening evidence) |
| `onboarding_0025_dev1_check_cycle` | **inserts** one cycle 1 per company with inputs | lossy (cycles, `cycle_id`, `rules_version`) |
| `onboarding_0026_dev1_approval` | none | lossy (proposals, approvals) |
| `onboarding_0027_dev1_expiry` | **updates** `exporter_profile.background_check_expires_at` for CLEAR companies (only where NULL; idempotent) | lossy (stored expiries) |

Before 0027 on a live database:

```bash
pg_dump …                                                        # always first
cd backend
./.venv/Scripts/python.exe -m app.modules.onboarding.migrations.onboarding_0027_dev1_expiry --dry-run
./.venv/Scripts/alembic.exe upgrade head
./.venv/Scripts/python.exe -m app.modules.onboarding.migrations.onboarding_0027_dev1_expiry --validate   # must print 0
```

All five were downgraded to 0022 and upgraded again on a copy of the test database (1 Oct 2026):
`alembic check` clean, `--validate` 0.

**Merging the other lanes after this PR.** On 1 October 2026 two other branches also number
from 0023 on `onboarding_0022_integrity`: Developer 2's `feature/handover-snapshot`
(`onboarding_0025_deal_foundation`, `onboarding_0026_deal_snapshot`,
`onboarding_0027_deal_req_docs`) and Developer 3's `feature/trade_history`
(`onboarding_0023_domestic_first`). Merged as they are, the chain has three heads. Whichever
merges next renumbers from **0028**, points its first `down_revision` at the head at that moment
(`onboarding_0027_dev1_expiry` if it is the first after this PR), checks `alembic heads` prints
one, and regenerates `frontend/openapi.json` and `frontend/src/lib/api/schema.ts` rather than
hand-merging them (allocation §2.2). A trial merge also conflicts in
`contracts/migration-register.md` (both), `frontend/openapi.json` (Dev 2), and
`frontend/src/pages/HomePage.tsx`, `frontend/src/platform/auth/roles.ts` and `index.ts` (Dev 3).

**Settings** (`platform/configuration/config.py`; [`development.md`](development.md) §3):

| Setting | Default | Note |
|---|---|---|
| `CRM_BACKGROUND_CHECK_MAKER_CHECKER` | `true` | `false` only where `ENVIRONMENT` is `local` or `test` (IQ-17); **the server refuses to start** with it off anywhere else — `development` included, because it is the default and what `.env.example` / docker-compose set |
| `CRM_BACKGROUND_CHECK_CLEAR_VALIDITY_DAYS` | `365` | ≥ 1; applies to Clears recorded after a change |
| `CRM_REKYC_DUE_WINDOW_DAYS` | `30` | ≥ 0 |

**Demo / UAT:** clearing now takes **two** COMPLIANCE/ADMIN accounts (`bootstrap` makes an ADMIN and a
COMPLIANCE user — enough) and KYB, AML and sanctions results ([`demo.md`](demo.md) §4 steps 8–9).

---

## 7. Verification baseline (this PR)

| Command (from `backend/`, `frontend/`) | Result |
|---|---|
| `./.venv/Scripts/python.exe -m pytest -q --no-cov -p no:cacheprovider` | **4,855 passed, 7 skipped, 27 xfailed, 0 failed** (~38 min; the 27 are the unmounted payments/FX routes) |
| `… -m pytest tests/contract` | 360 passed (ORM drift, OpenAPI artifact, route coverage) |
| `./.venv/Scripts/ruff.exe check .` | 16 findings, all pre-existing (merge revisions, two `__init__.py`) |
| `./.venv/Scripts/lint-imports.exe --config importlinter.ini` | 19 kept, 0 broken |
| `./.venv/Scripts/alembic.exe heads` / `check` | one head `onboarding_0027_dev1_expiry` / clean |
| `npx tsc -b --noEmit` · `npx eslint .` · `npx vitest run` · `npx vite build` | clean · 0 errors, 2 warnings (`AuthContext.tsx`) · 36 files, 349 tests · OK (chunk-size warning) |

Dev 1's own tests: `backend/app/modules/onboarding/tests/integration/test_dev1_*.py`,
`test_e2e_compliance_lifecycle.py`, `unit/test_dev1_*.py`, plus the frontend files above.

---

## 8. For the PR reviewer — files outside Dev 1's own areas

Each is a minimal, deliberate edit:

| File | Owner | Why |
|---|---|---|
| `backend/app/platform/configuration/config.py` | platform | the three compliance settings |
| `backend/app/main.py` | platform | one call: refuse to start with maker-checker off outside local/test (IQ-17) |
| `backend/app/modules/onboarding/domain/entities/exporter_profile.py`, `application/exporter_profile_service.py` | Dev 3 | F1's one column and one promotion change (allowed once, allocation §2.2) |
| `backend/app/modules/onboarding/tests/integration/test_crm_end_to_end.py` | Dev 2 | two compliance users and rule-B checks (plan P3-1d names this file) |
| `backend/app/modules/onboarding/tests/integration/test_company_record_0014.py` | Dev 3 | one FK-count assertion (F1) |
| `frontend/src/pages/HomePage.tsx` | — | mounts the two compliance Home cards by role |
| `frontend/src/platform/auth/roles.ts`, `index.ts` | — | `isComplianceRole` |
| `frontend/openapi.json`, `frontend/src/lib/api/schema.ts` | shared | regenerated, never hand-edited |
