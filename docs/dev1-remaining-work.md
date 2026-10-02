# Developer 1 — what is done, and what is left

**As of 2 October 2026.** Lane: the compliance engine — background check, verification,
screening, check cycles, maker-checker, Clear rules, expiry, company-keyed checks, and the
compliance facts the handover guard reads (`developer-allocation.md` §3). Contracts:
[`contracts/background-check.md`](contracts/background-check.md) and
[`contracts/verification-and-screening.md`](contracts/verification-and-screening.md).

| | |
|---|---|
| **Done (merged, PR #16)** | F1 and every lane task, 1.1–1.20, plus Dev 1's part of final integration |
| **Left** | 4 small follow-ups, each waiting on another lane (§2) |
| **Waiting on the lead** | 5 decisions built on a recommendation (§3) |
| **Known defects** | none |

---

## 1. Done

| Task | Plan id | Where | Tests |
|---|---|---|---|
| F1 | P0-2, P0-5 | migration 0023; seam v2 (`domain/compliance_inputs.py`); `ComplianceFactsReader` (`domain/` + `application/compliance_facts.py`); promotion needs a current Clear; history dimensions; `app/shared/clock.py`; `tests/fixtures/compliance.py` | `test_dev1_foundation.py`, `unit/test_dev1_clock_and_facts_rules.py` |
| 1.1 | P2-1a | `application/decision_evidence.py`, `GET …/decisions/{id}/evidence` | `test_dev1_decision_evidence.py` |
| 1.2 | P2-1b | 0024 `screening_review_item.evidence_refs` | `test_dev1_screening_evidence.py` |
| 1.3 | P2-1c | `EvidenceList` in `ScreeningChecklist`, `DecisionHistory` | `ScreeningChecklist.test.tsx`, `DecisionHistory.test.tsx` |
| 1.4 | P2-2 | filters in `VerificationSection` | `VerificationSection.test.tsx` |
| 1.5 | P2-4a | seven-item checklist (`website-reviewed` retired), `rules_version` | evidence + screening tests |
| 1.6–1.9 | P2-3a–d | 0025 `check_cycle`; cycle-scoped seam; `POST …/cycles`; cycle UI | `test_dev1_check_cycles.py` |
| 1.10–1.13 | P3-1a–d | 0026 proposals and resolutions; propose / approve / reject / withdraw; queue + Home card; two-user suite and seed | `test_dev1_maker_checker.py`, `unit/test_dev1_maker_checker_rules.py`, `BackgroundCheckApproval.test.tsx` |
| 1.14 | P3-2 | rule B: KYB, AML and sanctions passed (`ClearPolicy.required_passed_types`) | unit rules + integration |
| 1.15–1.17 | P3-3a–c | 0027 expiry + backfill; expiry in standing and facts; `GET /background-check/due`; badge + Home card | `test_dev1_clear_expiry.py` |
| 1.18 | P4-5 | company-keyed checks (`verification_result.subject_company_id`) | `test_dev1_company_keyed.py` |
| 1.19 | P4-11 | buyer-only companies run the full check and are never promoted | `test_dev1_company_keyed.py` |
| 1.20 | — | `CompanyComplianceSummary.tsx` full version | `CompanyComplianceSummary.test.tsx` |
| Final integration | §6 | concurrency: handover vs move, approval vs input, cycle vs decision | `test_dev1_concurrency.py` |
| Lane e2e | §2.2 | the lifecycle through the API; 401/403 on every Dev 1 route | `test_e2e_compliance_lifecycle.py` |

Migrations `onboarding_0023_dev1_foundation` … `onboarding_0027_dev1_expiry` — each row, its data
step and its downgrade are in `contracts/migration-register.md` §1 (0027 has a `--dry-run` and a
`--validate` that must print 0; `pg_dump` first). Settings `CRM_BACKGROUND_CHECK_MAKER_CHECKER`,
`CRM_BACKGROUND_CHECK_CLEAR_VALIDITY_DAYS`, `CRM_REKYC_DUE_WINDOW_DAYS`: `development.md` §3.
Clearing a company now takes **two** COMPLIANCE/ADMIN users and KYB, AML and sanctions results
(`demo.md` §4 steps 8–9).

---

## 2. Left — each waits for another lane

| # | Item | Waits for | What to do |
|---|---|---|---|
| 1 | **Concurrency: a handover vs a flag on the buyer company** | Developer 2's task 2.5 (the guard share-locks both companies, sorted by `customer_id`) | Copy the pattern in `test_dev1_concurrency.py` (`_Pause` holds a transaction at a named method): pause the handover after its guard, flag the **buyer** company (propose + approve), assert the approval waits. The seller form is already proved |
| 2 | **Delete `components/BuyerChecks.tsx`** — and its test, its export, and `BUYER_CHECK_TYPES` if then unused | Developer 2's buyer migration (2.6) applied in **every** environment, then 2.10 (no more `deal_buyer` writes) | It is the only place a legacy `deal_buyer`'s sanctions/AML can be recorded, which the handover rule (BQ-4) needs until every buyer is a company. Developer 2 tells you when 2.10 merges |
| 3 | **Re-run `test_dev1_company_keyed.py`** | Developer 3's F3 (`exporter_profile.pipeline_status`) | Its P4-11 tests (`_buyer_only_company()`) set `pipeline_status = 'NOT_IN_PIPELINE'` automatically once the column exists. A buyer-only company is never promoted because Developer 3's rule (`NOT_IN_PIPELINE ⇒ LEAD`) means it can never be qualified — Dev 1 added no promotion rule of its own |
| 4 | Optional: **"Not in pipeline" on the Re-KYC due list and Home card** | Developer 3's F3 | Add `pipeline_status` to `ReKycDueCompanyResponse` (the list serves `journey` today); regenerate the OpenAPI artifacts |

Nothing else is planned for this lane. Ask before taking on new work: the allocation's §7 items
(provider adapters, field-level provenance, consent, RXIL automatic intake) are deferred or wait
on outside parties.

---

## 3. Decisions waiting on the lead

Built on a recommendation; recorded in `open-items.md` §1. Confirm or change each.

1. REVIEW + REJECTED sanctions/AML reads as **FAILED** (`check_state`).
2. A new check cycle is refused while the current one is empty (`CHECK_CYCLE_EMPTY`).
3. Maker-checker details: the proposer cannot reject (only withdraw); nothing else moves the
   check while a proposal is open; any input change — including a company document passing its
   scan — makes a proposal stale; the queue is COMPLIANCE/ADMIN only; the approved decision's
   `decided_by` (and so the journey row and `company.became_customer`) names the proposer.
4. The expiry backfill uses the **last** CLEAR decision (BQ-5 read literally).
5. `BuyerChecks.tsx` kept for legacy deal buyers until P4-10 (§2 item 2).

Two verification-side items also wait on the lead (`contracts/verification-and-screening.md`
§11, `open-items.md` §1): D4's verification side (which documents may be evidence) and D12
(RXIL's results contract — blocked on RXIL).

---

## 4. What the other lanes take from you

Their remaining-work files carry the detail; nothing here needs action from you.

| Lane | Uses | Where it is described |
|---|---|---|
| Developer 2, 2.4 | `CompanyComplianceSummary` `{ companyId }` on the deal page, for the seller and the buyer company | `dev2-remaining-work.md` §3 |
| Developer 2, 2.5 | `ComplianceFactsReader` and its fake | `contracts/background-check.md` §12.4 |
| Developer 2, 2.6 | `verification_result.subject_company_id` (set once, then frozen) | `contracts/background-check.md` §12.2 |
| Developer 3, F3 / P4-1 | `exporter_profile.background_check_expires_at` is yours — written only by `BackgroundCheckService`; Developer 3 leaves it alone | `dev3-remaining-work.md` §2 |

**Rule both lanes follow:** Developer 1 does not touch the handover guard, and the guard never
reaches into Developer 1's tables — it reads `ComplianceFactsReader`.

---

## 5. Before any PR

- `alembic heads` prints one; take the next free number from `contracts/migration-register.md`
  §1 and parent on the head at merge time; id ≤ 32 characters.
- Request or response schema changed → regenerate `frontend/openapi.json` and
  `frontend/src/lib/api/schema.ts`.
- Any test that clears a company needs `record_required_checks(company_id)` (rule B) and two
  users — `approve_as(checker, company, maker=…)` (services) or
  `propose_and_approve(client, company, maker_token=…, checker_token=…)` (HTTP).
- Gates (`development.md` §7). Baseline on 2 October 2026: backend 4,932 passed, 7 skipped,
  27 xfailed; the one failure, `idempotency/test_expiry_sweep.py::test_sweep_can_use_the_partial_ck_index`,
  also fails on `main` (query-planner choice as the ledger table grows). Frontend 39 files /
  372 tests; ruff 16; import-linter 19 kept / 0 broken.
