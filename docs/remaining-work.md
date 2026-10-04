# Remaining work — Exporter CRM

**The one authoritative list of what is done, what is left, what is blocked, what needs a
decision, and what is deliberately not being done.** Audited on **4 October 2026** at
`feature/company-foundation-and-compliance-guard` @ `6cd71db`.

It replaces `open-items.md` (merged in here and deleted on 4 October 2026) and the three
lane lists `dev1/dev2/dev3-remaining-work.md` (deleted earlier the same day). §11 says where
every retired note went. **Keep this file current as items close; do not start a second
list.**

How the requirements were established: [`plan.md`](plan.md) (the post-demo plan; its §19.0
answers of 1 October win over any other section), the contracts in
[`contracts/`](contracts/), [`frontend-plan.md`](frontend-plan.md), and
[`developer-allocation.md`](developer-allocation.md) (historical, but its task ids and four
design adjustments are cited by the code). Every status below was checked against the code,
the migrations, the tests or a database on 4 October 2026, not copied from an earlier list.

**Status words.** DONE — VERIFIED · PARTIALLY DONE · STILL OPEN · BLOCKED · DECISION
REQUIRED · DEFERRED · OBSOLETE. **Ids.** `R-nn` is work, `D-nn` a decision for the lead,
`OPS-n` a step on a live database. Hyphenated `D-nn` are this list's; Developer 4's
unhyphenated D1–D17 are in `contracts/background-check.md` §14 and
`contracts/verification-and-screening.md` §11.

---

## 1. Current status

| | |
|---|---|
| **Audited** | `feature/company-foundation-and-compliance-guard` @ `6cd71db` (4 commits since `dfcb2d2`: R-01–R-05, R-06–R-11, R-12–R-23, R-24–R-33 Phase 0), 4 October 2026 |
| **Implementation** | Every allocated task of the three lanes is built and tested except **P4-10** (R-25, blocked on purpose) and the optional **P6-4** (R-30); task 3.2's script is built but its reports are still owed (OPS-0). One plan requirement was never allocated and is only partly built (R-34). Details in §2 and §3 |
| **Quality gates** | All pass at the baseline (§9) |
| **Migration head** | One head, `onboarding_0043_identity_type`. Next free number **0044**. Upgrade from an empty database, `downgrade -3` and back, and `alembic check` are clean |
| **Merge readiness** | **No merge blocker** (§3.1) |
| **Release readiness** | **Not ready to release.** The buyer migration (P4-6) has run in no environment, and on the rehearsal copy it leaves 325 rows for a person and 13 handed-over deals without a snapshot (§8). Eleven decisions are open (D-07 is probably answered by BQ-2) and four built behaviours await written confirmation (§4). No real document or customer data may be stored yet (P7-7, §5) |

---

## 2. Completed work (verified 4 October 2026)

| Area | Plan tasks | Evidence |
|---|---|---|
| **Compliance engine** (Developer 1, merged in PR #16) | F1; P2-1a–c, P2-2, P2-3a–d, P2-4a, P3-1a–d, P3-2, P3-3a–c, P4-5, P4-11; `CompanyComplianceSummary` (1.20) | `ComplianceFactsReader` (`application/compliance_facts.py`), check cycles and their route, maker-checker with `CRM_BACKGROUND_CHECK_MAKER_CHECKER` refused off outside local/test, rule B (`ClearPolicy.required_passed_types`), Clear expiry and `GET /background-check/due`, company-keyed buyer checks (`subject_company_id`). Tests `test_dev1_*.py`, `test_l4a_*`/`test_l4b_*`; the decisions behind them are in `contracts/background-check.md` §12, §14 |
| **Deals and handover** (Developer 2) | F2; P2-7, P2-5a/b, P4-4, P3-3b/P3-4/P4-7 (guard), P4-8 (deals), P6-6, P6-7; 2.11, 2.12 | `domain/handover_conditions.py` (seven conditions: CUSTOMER, CLEAR, required documents, seller current and no failed sanctions/AML, buyer sanctions and AML PASSED, branch recorded, branch not flagged), both parties share-locked by `customer_id`; handover snapshot (0029); invoicing branch (0036). `test_l3b_*`, `test_crm_end_to_end.py` |
| **Buyer migration command** | P4-6 (code) | `migrate_deal_buyers.py`, map table (0038), 0039, `ALREADY_LINKED` (0041); 32 safety tests; rehearsed (§8). **Not run on any live database** |
| **Company record, settings, GST, trade** (Developer 3) | F3; P0-3 (script), P0-4, P1-1, P1-2, P1-4, P1-5, P2-4b, P2-6, P4-1–P4-3, P4-9, P6-1, P6-2, P6-5, P6-3's warn-only consequences, P5-1–P5-8 | `CompanyDirectory`, `/companies/match` (BQ-2, audited), `pipeline_status` and `NOT_IN_PIPELINE`, GST registrations as branches (0035) with flags, trade relationships, invoices and outcomes (0037), relationship backfill command, masking sweep (`test_dev3_masking_sweep.py`), `backend/scripts/crm_data_inventory.sql` |
| **PR audit fixes** | R-01 – R-24, R-27 – R-29 (not R-19) | §6 and the commits `436731d`, `ccc42cc`, `0713986`, `6cd71db` |
| **Fail-closed screens** | R-33 Phase 0 (G1–G7) | `src/platform/access`, module table `src/routes/modules.ts`, route gates, No workspace, lazy screens, ESLint rule against role literals; `src/routes/access.matrix.test.tsx` |

Settled questions that need no further work: the stale OPERATIONS description in
`catalog.py` (fixed by `auth_0005`); `pg_trgm` for name matching (not needed: matching is
equality after normalisation, `company_directory._by_name`); the D14 history texts
(`history-row.md` §4); a concurrent create of the same new buyer (the loser gets 409
`DUPLICATE_REGISTRATION_NUMBER`, `ExporterProfileService.create_or_get_profile`).

---

## 3. Remaining work

### 3.1 Merge blockers

**None.** Every gate passes (§9). No route lacks a role gate (`test_route_authorization_coverage.py`),
no CRM read serves an unmasked identifier to a masked role (`test_dev3_masking_sweep.py`),
the generated API artifacts are current (`test_openapi_artifact_is_current.py`; `schema.ts`
regenerated and compared, identical), and nothing found in this audit is unsafe to merge.
What is left is release work (§3.2, §8), decisions (§4) and planned later phases.

### 3.2 Required follow-up

In priority order. Operational steps on live databases are §8 (`OPS-0` – `OPS-6`); they
come before R-25 and R-26.

#### R-25 — Retire `deal_buyer` writes (P4-10, task 2.10)

| | |
|---|---|
| Status | **BLOCKED** — operational precondition not met |
| Priority | High (it ends the legacy buyer model) |
| Why it remains | Plan P4-10's precondition is "P4-6 on all environments". P4-6 has run in **none**: checked read-only on 4 October, `crm_release_audit` is at `onboarding_0022` and `aner_settlement` at `onboarding_0027` (neither has `deal_buyer_company_map`); `crm_uat_walk` and the demo database are not on this server. A revision adding the refusing trigger would run at the next `alembic upgrade head`, i.e. before P4-6, which §8 forbids |
| Source | `plan.md` P4-10, §17.2; allocation 2.10 |
| Affected code | `DealService.set_buyer` (the only `DealBuyer(...)` writer), the legacy form of `PUT /deals/{id}/buyer`, `DealView.buyer`, the deal page's "Record details instead" form |
| Required implementation | A migration whose trigger refuses `INSERT`/`UPDATE` on `onboarding.deal_buyer` (table kept: BUYER results and snapshots reference its ids); remove the legacy request form and the screen's legacy form; keep `buyer` read-only for one release, then drop it from the response; rewrite decision 9 in `architecture.md`, `deal-and-buyer.md`, `event-envelope.md` (`deal.handed_over`) and `history-row.md` |
| Validation | Raw-SQL refusal test; OpenAPI regenerated; frontend no longer sends the legacy shape; `--validate` 0 on every environment beforehand |
| Dependencies | OPS-5 passed in **every** environment; D-02 accepted |
| Decision required? | No (D-02 must be accepted before OPS-5) |
| Owner | The developer completing the project |

#### R-26 — Delete `BuyerChecks.tsx`

| | |
|---|---|
| Status | **BLOCKED** on R-25 |
| Priority | Medium |
| Why it remains | Until R-25, it is the only place a legacy `deal_buyer`'s sanctions and AML can be recorded, which the handover guard (BQ-4) needs. Confirmed as the intended order on 2 October (`background-check.md` §14.2) |
| Source | allocation 1.20; `background-check.md` §12.2, §16 |
| Affected code | `components/BuyerChecks.tsx` and its test, its export, the `DealDetailPage.tsx` mount, `BUYER_CHECK_TYPES` if nothing else uses it |
| Required implementation | Delete them; the deal page already shows `CompanyComplianceSummary` for both parties |
| Validation | vitest, tsc, build; deal page tests |
| Dependencies | R-25 |
| Decision required? | No |
| Owner | The developer completing the project |

#### R-34 — Buyer KYB and incomplete-check warnings on the deal (new, found 4 October)

| | |
|---|---|
| Status | **PARTIALLY DONE** |
| Priority | Medium |
| Why it remains | Plan P3-4: "Incomplete KYB and other buyer checks are warnings in the deal view." P4-7: "An expired or incomplete buyer background check is a warning, not a block." The blocking half is built. The warning half was **not carried into allocation task 2.5**, so no lane built it. Today the deal page's `CompanyComplianceSummary` shows the buyer's gauge, its Clear expiry and sanctions/AML, but **not its KYB state**, and `CompanyComplianceFactsResponse` does not serve KYB |
| Source | `plan.md` P3-4, P4-7 (BQ-4: "incomplete KYB or other checks = warning") |
| Affected code | `api/schemas/background_check.py` (`CompanyComplianceFactsResponse`), `application/compliance_facts.py`, `components/CompanyComplianceSummary.tsx` |
| Required implementation | Serve the buyer's KYB state (IQ-2's meaning of passed) with sanctions and AML, and show a warning on the deal when the buyer's KYB is not passed or its background check is not `CLEAR` or has expired. **Not** a guard condition |
| Validation | Facts reader tests; component test; masking sweep unaffected (no identifiers); DEVELOPER still refused (D8) |
| Dependencies | None |
| Decision required? | No |
| Owner | The developer completing the project |

#### R-33 (Phases 1–5) — Frontend redesign

| | |
|---|---|
| Status | **STILL OPEN** — Phase 0 done |
| Priority | Medium |
| Why it remains | Planned work: tokens and primitives, shell, signature components, screens, polish |
| Source | `frontend-plan.md` §14 |
| Affected code | `frontend/src` |
| Required implementation | As planned. The deal room and party card re-compose `InvoicingBranchPicker` (R-05) and the create-buyer step (R-24) rather than rebuilding them. The manifest's drift check against the server's role table waits on ask A7 |
| Validation | `frontend-plan.md` §15; the role-matrix test stays green |
| Dependencies | None (A7 for the drift check) |
| Decision required? | No |
| Owner | The developer completing the project |

#### Smaller items

| Id | Item | Status | Priority | Source | Required implementation and validation | Decision? |
|---|---|---|---|---|---|---|
| R-31 | `POST /exporters` still creates a company with no `name` or `country` | STILL OPEN | Low | `company-record.md` §10 | Remove the unnamed path (`CreateExporterProfileRequest.name/country` are optional), then expand → backfill → contract to `NOT NULL`. Route and ORM tests | No |
| R-35 | Retire `GET /exporters/activities/pending` | STILL OPEN | Low | `engagement.md` §5.6; plan §19.3 | Superseded by `GET /follow-ups`, still lists completed follow-ups, no screen calls it. Remove the route, its authorisation rows and OpenAPI entry; confirm no outside caller first | No |
| R-36 | The qualification-criteria screen shows a version's `created_by` as a user id | STILL OPEN | Low | architecture §8; plan §19.3 | Serve `created_by_name`, as every other history-like read does | No |
| R-37 | The company search returns no `total` | STILL OPEN | Low | plan §19.3 | Add `total` to `GET /exporters`; Home and Companies then show exact counts | No |
| R-38 | Two tests fail intermittently | STILL OPEN | Low | `development.md` §9 | `test_dev1_decision_evidence.py::test_new_decisions_record_the_current_rules_and_cycle` (order by `decided_at DESC, id DESC`, or assert the set); `test_expiry_sweep.py::test_sweep_can_use_the_partial_ck_index` (asserts a query plan) | No |
| R-39 | The OpenAPI artifact test compares `info.title`, which comes from `APP_NAME` | STILL OPEN | Low | `development.md` §8 | Pin the title in code, or leave it out of the comparison | No |
| R-40 | The suite cannot run inside the `aner-app` container | STILL OPEN | Low | — | `test_openapi_artifact_is_current.py` needs `./frontend`; mount it in compose | No |
| R-41 | Accounts created before 29 September with a special-use address (`admin@demo.local`) cannot sign in | STILL OPEN (data) | Low | — | Make a new account with a real-looking address and deactivate the old one (Settings cannot change an email) | No |

---

## 4. Decisions required

None of these is answered by an authoritative document. Where one is built a certain way,
that is the recommended default, not a decision.

| Id | Question | Why it matters | Affected code | Consequences | Blocks |
|---|---|---|---|---|---|
| **D-01** | May the invoicing branch be **changed** before handover? **The sources disagree:** allocation 2.8 says "set-once rule in the trigger"; plan P6-6 says it "may be set any time before handover" | Whether a mistaken branch is corrected by editing or by withdrawing the deal | 0036's trigger, `DealService.set_invoicing_branch`, `InvoicingBranchPicker` | Built: changeable until handover, frozen after. "Set once" needs a trigger change and a screen without Clear | Nothing today |
| **D-02** | Accept restoring the `pg_dump` as the **only** rollback of P4-6? §17.2's logical rollback is impossible because both columns it would reset are frozen | A wrong run cannot be undone in place | `migrate_deal_buyers --rollback` (reports, writes nothing) | If not accepted, a reversible design is needed before any live run | **OPS-5** |
| **D-03** | One invoice per deal? | Whether a second invoice on a deal is an error or normal | `trade_invoice`, `TradeHistoryService` | Built: not enforced. The deal route locks the deal, so two outcomes at once cannot both create an invoice, and it answers about the deal's earliest invoice; the relationship route may record a second one deliberately (R-14). "One" needs a partial unique index | Nothing today |
| **D-04** | Should a **deactivated** invoicing branch block the handover, or only warn? | A branch deactivated after it was recorded neither blocks nor warns today | `handover_conditions.py`, `GstRegistrationService.deactivate` | Blocks: a new guard condition. Warns: a deal-page notice. This is **R-19** | R-19 |
| **D-05** | Should DEVELOPER see GST branch **flag reasons**? They are compliance judgements (D8's reasoning) | DEVELOPER reads them today on `GET …/gst-registrations` and in `gst_registration` history | `gst_registration_router.py`, `HIDDEN_FROM_DEVELOPER` | Hiding them: add the dimension and blank the field for DEVELOPER, with masking tests | Nothing today |
| **D-07** | `also_held_by` (shared-GSTIN warnings) and CSV-import candidates name the other company to OPERATIONS | **Probably answered:** BQ-2 lets a masked role be told the holder of a full PAN/GSTIN "when matching a buyer or refusing a duplicate". Confirm that GSTIN warnings and import candidates fall under it, then close this and the old "identifier disclosure" item | `gst_registration_router.py`, `company_import_service.py` | If not: omit holder ids for masked roles | Nothing |
| **D-08** | Confirm in writing: the move to `CUSTOMER` commits in the same transaction as the `CLEAR` or `QUALIFIED` that completes it (U4/D11) | Built that way since 29 September | `promote_to_customer_if_ready` | A different boundary would need an outbox | Nothing |
| **D-09** | Confirm in writing: only a `PROSPECT` or `CUSTOMER` may have a deal opened (`DEAL_COMPANY_NOT_READY`) | Built | `DealService.open_deal` | Allowing leads changes seam S1 | Nothing |
| **D-10** | Confirm in writing: the D2 clarification — a `REVIEW` result with an `ACCEPTED` or `REJECTED` review no longer blocks `CLEAR` | Built (`CLEAR_POLICY`) | `domain/background_check_views.py` | The literal D2 makes such companies impossible to clear | Nothing |
| **D-11** | Confirm in writing: the D5 amendment — risk is refused on every move except `CLEAR` | Built, enforced by a database check | `ck_background_check_decision_risk_only_on_clear` | — | Nothing |
| **D-12** | O2: does `CUSTOMER` replace `ONBOARDED` for the ANER-4.2-S1T2 consumer, which watched journey rows marked `terminal`? | That consumer sees completions only if confirmed | `company-record.md` §10 | — | That consumer |
| **D-13** | The reload-burst refresh window: a reload landing after the server committed a token rotation, while its answer is in flight, must sign in again (21 of 30 bursts stayed signed in on the production build, 29 September) | A security trade-off | `lib/api/client.ts`, `POST /auth/refresh` | Close it with a short server-side grace window (weakens rotation) or by keeping the access token across reloads (changes where script can read it) | Nothing |
| **D-14** | Re-date a `NOT_NOW` check-back in one move? Today it takes two, because a move to the value already held is refused | Usability | `engagement.md` §1.1 | Needs `NOT_NOW → NOT_NOW` with a new date in the contract | Nothing |
| **D-15** | Q5: do reason codes need an ADMIN route and screen, or stay seeded settings changed by migration? | Who may change them | `criterion-result.md` §10 Q5 | A route, a screen, authorisation rows | Nothing |
| **D-16** | CI (U6): there is none; every gate is run by hand | Regressions are caught only when someone runs the gates | — | A pipeline running `development.md` §7 | Nothing |

**Closed by this audit:** D-06 (a buyer company's History shows trade rows — answered by
`trade-history.md` §6 and plan P5-3/P5-4, built as R-23). The old "identifier disclosure"
undecided row predates BQ-2 (1 October) and is folded into D-07. Confirmed on 2 October
and recorded in `contracts/background-check.md` §14.2: Developer 1's IQ-2 edge cases,
`CHECK_CYCLE_EMPTY`, the maker-checker details, the expiry backfill, keeping `BuyerChecks`
until P4-10, D4's verification side, no D2 amendment for placeholders, and no document
required to `CLEAR` (to be revisited with P7-7).

---

## 5. Deferred, and waiting on outside parties

Not current work. Each starts only when its trigger happens.

| Item | Status | Trigger | Source |
|---|---|---|---|
| P7-7 — a real scanner, S3 with Object Lock, KMS and retention, field-level encryption | DEFERRED; **precondition for any real document or customer data** | A decision to use real data | plan P7-7; architecture §7, §12. Each is one new implementation of an existing port (`ScannerPort`, `StoragePort`); `app/integrations/object_storage` is kept as the home of the S3 implementation |
| P7-4 field-level provenance, P7-5 consent | DEFERRED | The DPDP meeting (BQ-7). Basic provenance is on every new table | plan §19.0 |
| P7-1 – P7-3 provider adapters | DEFERRED | BQ-8: checks stay manual this quarter | plan §19.0 |
| P7-6 RXIL results intake; RXIL's machine identity | DEFERRED | RXIL's package and results contract (Developer 4's D12). Intake stays ADMIN-only meanwhile; a machine identity must never be `API_USER` | `verification-and-screening.md` §11 |
| P1-3 rupee display of thresholds | DEFERRED | BQ-1 kept USD | plan §19.0 |
| P6-3 global GSTIN uniqueness | OBSOLETE (dropped by IQ-9) | — | plan §19.0 |
| R-30 — PAN from GSTIN for PAN-less companies (P6-4, task 3.16) | DEFERRED, optional | Only if OPS-0's reports show it is worth doing; with an audit table for rollback | plan P6-4 |
| R-32 — name matching scans every company in a country, in Python, per lookup | DEFERRED | Past about 50,000 companies in one country: store `name_key` (maintained by `company_names.name_key`) | `company_directory._by_name` |
| R-42 — group-level `--confirm-name` for the buyer migration | DEFERRED | Only if a live dry run shows the rehearsal's shape (330 rows sharing `NL-8899`, about 110 confirmations per command line) | §8 |
| Cross-company Deals and Documents lists | DEFERRED (product) | A decision to add two paged routes and rail rows | plan §19.3 |
| Group companies (different PANs) link | DEFERRED | "Later" in the source | plan §19.3 |
| CSV import above 1,000 rows | DEFERRED | Only if the business needs it: a background job with a pollable report | — |
| A foreign key from `bank_activity_finding` to the company | DEFERRED | When a bank feed is connected | — |
| Documents in the sample data | DEFERRED | Once there is a scanner worth running | — |
| The "Verify GSTIN" link's portal format | Built as `services.gst.gov.in/services/searchtp?tin=`; the portal's deep-link format was never confirmed | If the portal ignores the parameter, it opens the search page | plan §19.3 |

---

## 6. Reconciliation of the earlier lists

### 6.1 R-01 – R-33

| Id | Title | Status | Evidence |
|---|---|---|---|
| R-01 | TypeScript build | DONE — VERIFIED | `tsc -b` 0 errors, `npm run build` passes (§9); `436731d` |
| R-02 | import-linter: the masking sweep imported `app.main` | DONE — VERIFIED | 19 kept / 0 broken; the sweep reads the served OpenAPI |
| R-03 | Ruff `I001` | DONE — VERIFIED | 16 findings, all pre-existing |
| R-04 | Stale closed-deal buyer test | DONE — VERIFIED | `test_a_closed_deals_buyer_company_is_filled_once_then_frozen_in_raw_sql` passes |
| R-05 | No invoicing-branch picker | DONE — VERIFIED | `InvoicingBranchPicker` (13 tests) and 7 deal-page tests |
| R-06 | Name-only buyers merged | DONE — VERIFIED | `test_l3b_buyer_migration_safety.py`; rehearsal §8 |
| R-07 | Already-linked buyers re-pointed | DONE — VERIFIED | `ALREADY_LINKED` (0041); validation checks 8–9 are 0 on the rehearsal copy |
| R-08 | Arbitrary PAN holder through a GSTIN | DONE — VERIFIED | `CONFLICT` with every holder; safety tests |
| R-09 | `--confirm-name` unchecked | DONE — VERIFIED | `check_confirmations` before any write; exit 2 on a bad line |
| R-10 | §17.2 gaps (contacts, history row, one-character numbers, query 5) | DONE — VERIFIED | Safety tests; validation query 5 is 0 |
| R-11 | Data commands crash on a Windows console | DONE — VERIFIED | `command_console.prepare_console`; cp1252 subprocess tests |
| R-12 | Payment outcome not atomic | DONE — VERIFIED | `test_dev3_trade_integrity.py` |
| R-13 | Concurrent outcomes give a 500 | DONE — VERIFIED | Invoice locked; 409 `TRADE_OUTCOME_STALE`; concurrency tests |
| R-14 | Two invoices for one deal under a race | DONE — VERIFIED (the lock); one invoice per deal is D-03 | Deal locked `FOR UPDATE`; concurrency test |
| R-15 | `registration_number` unmasked in history | DONE — VERIFIED | Masked on write and on read; the sweep edits it first |
| R-16 | `identity_type` stale on edit | DONE — VERIFIED | Recomputed on edit; IQ-7 on edit; 0043 |
| R-17 | Invoice accepts any `deal_id` | DONE — VERIFIED | Service checks; FKs in 0042 (`NOT VALID` where old rows violate) |
| R-18 | Handover and a branch flag interleave | DONE — VERIFIED | `flag`/`unflag`/`deactivate` lock the company; concurrency test |
| R-19 | A deactivated invoicing branch does not block handover | DECISION REQUIRED (D-04) | Behaviour unchanged and stated in `deal-and-buyer.md` §6.1 |
| R-20 | Registration key disagrees with the index | DONE — VERIFIED | ASCII key; the collision test gets a 409 |
| R-21 | `POST /exporters` accepts `DEAL_BUYER` | DONE — VERIFIED | Refused by the route and by the CSV import |
| R-22 | Match audit actor type | DONE — VERIFIED | `actor_type_for_role` |
| R-23 | Buyer's history lacks trade rows | DONE — VERIFIED | Read-side union; `trade-history.md` §6 |
| R-24 | Create a buyer company from the deal | DONE — VERIFIED | `test_l3b_deal_buyer_company_create.py` (17 cases: pipeline count unchanged, refusals, roles, masking); picker and deal-page tests |
| R-25 | Retire `deal_buyer` writes (P4-10) | BLOCKED | §3.2 |
| R-26 | Delete `BuyerChecks` | BLOCKED | §3.2 |
| R-27 | Past-invoice form | DONE — VERIFIED | `RecordPastTradeForm` (7 tests) and 4 panel tests |
| R-28 | IQ-7 completion list | DONE — VERIFIED | `test_dev3_identity_completion.py` (9), `IdentityCompletionPage.test.tsx` (6) |
| R-29 | `pipeline_status` on the Re-KYC due list | DONE — VERIFIED | Due-list test in `test_dev1_clear_expiry.py`; `HomeCards.test.tsx` |
| R-30 | PAN from GSTIN (P6-4) | DEFERRED | §5 |
| R-31 | `name`/`country` `NOT NULL` | STILL OPEN | §3.2 |
| R-32 | Name matching at scale | DEFERRED | §5 |
| R-33 | Frontend plan | PARTIALLY DONE (Phase 0 done) | §3.2; `access.matrix.test.tsx` |

### 6.2 Rows carried from `open-items.md` (deleted 4 October 2026)

| Old row | Now |
|---|---|
| §1.1 U4/D11; deals only for PROSPECT/CUSTOMER; D2 clarification; D5 amendment | D-08 – D-11 |
| §1.2 D12, RXIL's service identity | §5 (P7-6) |
| §1.2 O2 | D-12 |
| §1.2 identifier disclosure to masked roles | Folded into D-07 (BQ-2 answers most of it) |
| §1.2 reload-burst refresh window | D-13 |
| §1.2 re-dating a `NOT_NOW` check-back | D-14 |
| §1.2 retire `GET /exporters/activities/pending` | R-35 |
| §1.2 cross-company Deals and Documents lists | §5 |
| §1.2 gate §7.6 (scanner, S3), the `object_storage` package | §5 (P7-7) |
| §1.2 CI (U6) | D-16 |
| §2 unnamed `POST /exporters` | R-31 |
| §2 CSV limit; `bank_activity_finding` FK; documents in sample data | §5 |
| §2 OpenAPI `info.title`; container suite; flaky tests; special-use addresses | R-39, R-40, R-38, R-41 |
| §2 search `total`; user ids shown | R-37, R-36 (the pending route's ids go with R-35) |
| §2 no reason-codes screen | D-15 |
| §2 legacy routes commit after the response; legacy case actor type | §7 (out of scope) |
| §2 shared test database accumulates rows | Not work: demo on a separate database (`demo.md` §1) |
| §2 contract acknowledgement tables read "pending" | OBSOLETE: a step of the multi-developer process; nothing to do |

---

## 7. Out of scope

| Item | Why |
|---|---|
| The legacy `onboarding_request` path and its Temporal workflow (`backend/app/modules/onboarding/README.md`), the KYC `Case` state machine | Not part of the CRM; `TEMPORAL_ENABLED=true` is unsupported (architecture §12); their tests run only in the whole suite |
| The case engine connected to background-check decisions | Assumption A6 |
| Routes outside the CRM that commit after the response (legacy onboarding `/cases`, `/register`, the Sumsub webhook; the `compliance` routes) | The module rule keeps those modules closed; the CRM's own routes and the auth/role routes commit before returning |
| `CaseService._actor_type_for` records a user's transition as `API_CLIENT` | Legacy case path |
| Ledger, settlement, rails, FX, reconciliation, payments | Present as schema only so the migration chain applies (`RUNNING.md`) |
| `Jira/` (Epic 4.1–4.4, 4.6) | Specifications of the platform modules, not CRM requirements (`README.md`) |
| The platform modules' one-line READMEs citing an `ARCHITECTURE.md` | That file belongs to the platform monorepo this checkout was pruned from |

---

## 8. On live databases — in this order, do not reorder

Environments: `crm_uat_walk`, `crm_release_audit`, demo, shared test. The procedure for the
two commands (scratch rehearsal first, quiet settings, Windows console) is
[`development.md`](development.md) §10.1.

| Id | Step | Status |
|---|---|---|
| OPS-0 | Run `backend/scripts/crm_data_inventory.sql` (read-only) on every live database and keep the output with the migration ticket. It sizes OPS-5 and decides R-30. Never attach numbers from a development database | STILL OPEN |
| OPS-1 | Before deploying: the IEC pre-check for 0040 must return 0 — `SELECT count(*) FROM onboarding.exporter_profile WHERE iec IS NOT NULL AND iec !~ '^[A-Z0-9]{10}$'`. **Send the 0031 release note** (owed): after 0031, `export_history` and `export_licence` stop counting towards the suggestion, so an undecided lead may now suggest `QUALIFIED` | STILL OPEN |
| OPS-2 | `pg_dump` | STILL OPEN |
| OPS-3 | `alembic upgrade head` (to 0043). Read the counts 0033, 0035, 0042 and 0043 print; 0042 leaves a foreign key `NOT VALID` where old rows violate it and prints the query that lists them | STILL OPEN |
| OPS-4 | Deploy. Users can now name **or create** a buyer company on a deal (R-24), which R-07's `ALREADY_LINKED` handles in OPS-5 | STILL OPEN |
| OPS-5 | **Buyer migration P4-6.** First: P2-7's precondition must be 0 — `SELECT count(*) FROM onboarding.deal WHERE stage = 'HANDED_OVER' AND handover_snapshot IS NULL`; and D-02 accepted. Then `--dry-run`; Compliance reviews the look-alikes (IQ-8) and the rows that need a person; `--apply --run-id <id>` with `--confirm-name` lines; `--validate` (every count 0); re-run `--apply` (creates nothing). Also check `SELECT count(*) FROM onboarding.verification_result WHERE entity_type = 'BUYER' AND subject_company_id IS NOT NULL` | STILL OPEN in every environment |
| OPS-6 | **Relationship backfill P5-5**: `--dry-run`, `--apply --run-id <id>`, `--validate`. Undo is one `DELETE` (`--report-run`), as long as no invoice points at the run's relationships | STILL OPEN |
| — | Then R-25, then R-26 | — |

**What the rehearsal shows** (`p46_scratch`, a copy of the 15.9k-company scratch database
with 783 legacy buyers; read-only `--validate` re-run on 4 October 2026 at `6cd71db`):

- 453 rows migrated by rule (387 `NEW`, 21 `REGISTRATION_NUMBER`, 45 `ALREADY_LINKED`),
  391 companies created; a second `--apply` created nothing.
- **325 deals / 330 rows still need a person.** They share registration `NL-8899`, and the
  five deals among them that already name a buyer company name five *different* companies.
  Until someone decides who `NL-8899` is, none can be mapped by rule (R-42 if this shape
  appears on a live database).
- **13 handed-over deals have no handover snapshot**, so `--validate` fails that check.
  They predate the migration; P2-7 should have prevented them, so find out why before
  OPS-5.
- The relationship backfill has not been run on this copy (458 deals with a buyer company
  and no relationship).
- These checks are 0, as they must be: BUYER results without a subject, buyers that are
  their own seller, creation history rows, masked identifiers, and both `ALREADY_LINKED`
  consistency checks.

---

## 9. Validation baseline (4 October 2026, `6cd71db`)

Run as in [`development.md`](development.md) §7, against a scratch database at head
(`pr_f3_audit`, a copy of the 15.9k-company scratch data). Never the shared
`aner_settlement`, which is at 0027.

| Gate | Command | Result |
|---|---|---|
| Migration head | `alembic heads` | One: `onboarding_0043_identity_type` |
| Migration round trip | fresh empty database: `alembic upgrade head`; `downgrade -3`; `upgrade head`; `alembic check` | All clean; "No new upgrade operations detected" |
| Whole backend suite | `pytest -q --no-cov -p no:cacheprovider` | **5,350 passed, 7 skipped, 27 xfailed, 0 failed** (36 min). The 27 are the strict expected failures for payment routes this checkout does not mount (`development.md` §9); both intermittent tests (R-38) passed this run |
| CRM suite | `pytest --crm -q --no-cov -p no:cacheprovider` | **2,711 passed, 1 skipped, 0 failed** (53 min). The skip is the symlink test, which Windows refuses without developer mode |
| Ruff | `ruff check .` | 16 findings, all pre-existing (two generated Alembic merge revisions, two package index files) |
| import-linter | `lint-imports --config importlinter.ini` | 19 kept, 0 broken |
| TypeScript | `npx tsc -b --noEmit` | 0 errors |
| ESLint | `npx eslint .` | 0 errors, 2 warnings (`AuthContext.tsx`, pre-existing) |
| Frontend tests | `npx vitest run` | 51 files, 636 tests passed |
| Production build | `npm run build` (`tsc -b && vite build`) | Passes, no chunk-size warning (main bundle 435 kB) |
| Generated artifacts | `test_openapi_artifact_is_current.py`; `openapi-typescript` re-run and compared | Current |
| Buyer migration (read-only) | `migrate_deal_buyers --validate` on `p46_scratch` | 6 of 9 checks 0; 325 / 325 / 13 outstanding (§8) |
| Relationship backfill (read-only) | `backfill_trade_relationships --validate` on `p46_scratch` | 5 of 6 checks 0; 458 deals not yet backfilled (§8) |

---

## 10. Recommended order

1. **Merge** this branch: no blockers (§3.1).
2. **The lead answers D-02** (it gates OPS-5), then D-01, D-03, D-04 (with R-19), D-05,
   D-07, and confirms D-08 – D-11 in writing.
3. **Per environment, one at a time: OPS-0 → OPS-6** (§8). Resolve the 13 deals without a
   snapshot and the contested rows before OPS-5 anywhere; build R-42 only if a live dry run
   shows the rehearsal's shape.
4. **R-25, then R-26**, once OPS-5 has passed in every environment.
5. **R-34** at any point; it depends on nothing.
6. **R-33 Phases 1–5**, re-composing the R-05 and R-24 components.
7. The low-priority engineering items: R-31, R-35 – R-41.
8. §5 items only when their trigger happens; P7-7 before any real data.

---

## 11. Where the retired notes went

Decisions are recorded where their rule lives: the twelve prototype decisions and
assumptions A1–A14 in architecture §11 (the design PDF they came from was retired on 4
October 2026: `git show 451ef97:docs/Exporter-CRM-Architecture-and-Plan.pdf`); Developer 4's
D1–D17 and the confirmations of 2 October in `contracts/background-check.md` §14 and
`contracts/verification-and-screening.md` §11; each contract's own decisions in that
contract; the one module-rule exception in
[`module-rule-exceptions.md`](module-rule-exceptions.md).

| Removed | Its still-open content is now |
|---|---|
| `open-items.md` (4 October 2026) | §3 – §5 and §7 here; the mapping is §6.2 |
| `dev1-remaining-work.md`, `dev2-remaining-work.md`, `dev3-remaining-work.md` (4 October 2026) | This file |
| `Exporter-CRM-Architecture-and-Plan.pdf` (4 October 2026, outdated) | `architecture.md` and `plan.md` |
| `dev1-handover.md`, `dev2-handover.md`, `dev4/4a-task.md`, `dev4/4b-task.md` (2 October 2026) | The contracts (`background-check.md` §12, `verification-and-screening.md`) |
| `dev1-pr1-readiness.md`, `dev3a-*`, `dev3b-*`, `dev4/4b-remaining-work.md`, `frontend-refresh.md`, `exporter-crm-tickets.md`, `exporter-crm-frontend-tickets.md`, `../E9-NOTES.md`, `../TEST-BASELINE.md` (before 2 October) | The contracts, `development.md` §9, and this file |

Any of them can be read with `git show <commit>:docs/<name>` (`451ef97` for the 4 October
removals; `6cd71db` for `open-items.md`).
