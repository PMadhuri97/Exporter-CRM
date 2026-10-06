# Remaining work — Exporter CRM

**The one authoritative list of what is done, what is left, what is blocked, what needs a
decision, and what is deliberately not being done.** Audited on **4 October 2026** at
`feature/company-foundation-and-compliance-guard` @ `6cd71db`, re-audited after the merge on
`main` @ `05b43eb` the same evening. The lead answered every open decision then (§4), and
the work that follows from them is planned in §12. A UAT and demo-readiness audit on
`main` @ `46097bd` (the redesign merged) on **5 October 2026** built R-19 and R-47 early,
fixed four demo issues and rebuilt the demo database (§13). A walkthrough for the CEO demo
deck on `main` @ `9ed6cb6` the same day found four display issues, fixed as R-57 – R-60
(§14).

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
| **Audited** | `feature/company-foundation-and-compliance-guard` @ `6cd71db` (4 commits since `dfcb2d2`: R-01–R-05, R-06–R-11, R-12–R-23, R-24–R-33 Phase 0), 4 October 2026. **Merged** to `main` (`05b43eb`, fast-forward plus the audit's documentation commit; local `main` not yet pushed). Code since `6cd71db` changed in comments only, and every gate was re-run on `main` (§9) |
| **Implementation** | Every allocated task of the three lanes is built and tested except **P4-10** (R-25, blocked on purpose) and the optional **P6-4** (R-30); task 3.2's script is built but its reports are still owed (OPS-0). One plan requirement was never allocated and is only partly built (R-34). The post-merge audit found five more items (R-43–R-46 and the decided R-19, R-47–R-50). Details in §2, §3 and §12 |
| **Quality gates** | All pass at the baseline (§9, and §13.5 and §14.4 for 5 October) |
| **Migration head** | One head, `onboarding_0043_identity_type`. Next free number **0044**. Upgrade from an empty database, `downgrade -3` and back, and `alembic check` are clean (re-run on `main`) |
| **Merge readiness** | Merged. No blocker was found |
| **Demo readiness** | **Ready — re-verified 5 October 2026 on the redesigned UI (§13).** `crm_demo` was rebuilt clean that day (the rehearsal copy is kept as `crm_demo_rehearsal_1005`); the paragraph that follows is the 4 October state. **4 October:** ready. Sign-in accounts on `crm_demo`: one ADMIN, two COMPLIANCE (maker-checker needs the second), one RM (OPERATIONS) and one DEVELOPER, each with a full name; passwords kept outside the repository. Demo database `crm_demo` built fresh at head with the sample companies (demo.md §1); `demo.md` §3 and §5 rehearsed against a copy of it through the API and, for 91 screens across four roles, in a headless browser on the production build: no error, no failed request, role gating as §5 says. `demo.md` corrected where the sample data had moved on |
| **Release readiness** | **Not ready to release.** The buyer migration (P4-6) has run in no environment (§8). The rehearsal copy's "325 rows for a person" and "13 handed-over deals without a snapshot" turned out to be **test-suite debris**, not data problems (§8), so a real rehearsal on a copy of each environment is still owed. The decided work in §12 is not built. No real document or customer data may be stored yet (P7-7, §5) |

---

## 2. Completed work (verified 4 October 2026)

| Area | Plan tasks | Evidence |
|---|---|---|
| **Compliance engine** (Developer 1, merged in PR #16) | F1; P2-1a–c, P2-2, P2-3a–d, P2-4a, P3-1a–d, P3-2, P3-3a–c, P4-5, P4-11; `CompanyComplianceSummary` (1.20) | `ComplianceFactsReader` (`application/compliance_facts.py`), check cycles and their route, maker-checker with `CRM_BACKGROUND_CHECK_MAKER_CHECKER` refused off outside local/test, rule B (`ClearPolicy.required_passed_types`), Clear expiry and `GET /background-check/due`, company-keyed buyer checks (`subject_company_id`). Tests `test_dev1_*.py`, `test_l4a_*`/`test_l4b_*`; the decisions behind them are in `contracts/background-check.md` §12, §14 |
| **Deals and handover** (Developer 2) | F2; P2-7, P2-5a/b, P4-4, P3-3b/P3-4/P4-7 (guard), P4-8 (deals), P6-6, P6-7; 2.11, 2.12 | `domain/handover_conditions.py` (eight conditions: CUSTOMER, CLEAR, required documents, seller current and no failed sanctions/AML, buyer sanctions and AML PASSED, branch recorded, branch not flagged, branch not deactivated — the last added 5 October, R-19), both parties share-locked by `customer_id`; handover snapshot (0029); invoicing branch (0036). `test_l3b_*`, `test_crm_end_to_end.py` |
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
| Required implementation | A migration whose trigger refuses `INSERT`/`UPDATE` on `onboarding.deal_buyer` (table kept: BUYER results and snapshots reference its ids); remove the legacy request form and the screen's legacy form; keep `buyer` read-only for one release, then drop it from the response; **move `sample_data_deals.py` to buyer companies**, since it records its three buyers the legacy way and would be refused by the trigger (found 4 October; `demo.md` §3.1 changes with it); rewrite decision 9 in `architecture.md`, `deal-and-buyer.md`, `event-envelope.md` (`deal.handed_over`) and `history-row.md`. Plan: §12, PR-J |
| Validation | Raw-SQL refusal test; OpenAPI regenerated; frontend no longer sends the legacy shape; `--validate` 0 on every environment beforehand |
| Dependencies | OPS-5 passed in **every** environment in scope (D-17: `crm_uat_walk`, `crm_release_audit`, the demo database); D-02 accepted (it is) |
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
| Required implementation | Serve the buyer's KYB state (IQ-2's meaning of passed) with sanctions and AML, and show a warning on the deal when the buyer's KYB is not passed or its background check is not `CLEAR` or has expired. **Not** a guard condition. *Post-merge finding:* a company's KYB state is already served, in `required_checks` on `GET …/background-check` — the very response `CompanyComplianceSummary` reads — so the KYB chip needs no new field; what is missing is the warning, which is computed by the server beside the guard (§12, PR-B) so the rule lives in one place |
| Validation | Facts reader tests; component test; masking sweep unaffected (no identifiers); DEVELOPER still refused (D8) |
| Dependencies | None |
| Decision required? | No |
| Owner | The developer completing the project |

#### R-33 (Phases 1–5) — Frontend redesign

| | |
|---|---|
| Status | **DONE — VERIFIED** (5 October 2026). Phases 1–5 merged to `main` in PR #19 (`a77725d`, `46097bd`); walked in the UAT of §13 |
| Priority | Medium |
| Why it remains | — (kept for its record: tokens and primitives, shell, signature components, screens, polish) |
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
| R-31 | `POST /exporters` still creates a company with no `name` or `country` | STILL OPEN | Low | `company-record.md` §10 | Remove the unnamed path (`CreateExporterProfileRequest.name/country` are optional) now (§12, PR-E). The `NOT NULL` contract migration refuses to run while any nameless company exists and lands only after OPS-0 shows none in every environment in scope (D-18; §12, PR-L). The shared development database holds 6,029 nameless test companies; `crm_release_audit` none | Decided (D-18) |
| R-35 | Retire `GET /exporters/activities/pending` | STILL OPEN | Low | `engagement.md` §5.6; plan §19.3 | Superseded by `GET /follow-ups`, still lists completed follow-ups, no screen calls it. Remove the route, its authorisation rows and OpenAPI entry; confirm no outside caller first | No |
| R-36 | The qualification-criteria screen shows a version's `created_by` as a user id | STILL OPEN | Low | architecture §8; plan §19.3 | Serve `created_by_name`, as every other history-like read does | No |
| R-37 | The company search returns no `total` | STILL OPEN | Low | plan §19.3 | Add `total` to `GET /exporters`; Home and Companies then show exact counts | No |
| R-38 | Two tests fail intermittently (a third of the same kind found 5 October, §14.4: `test_l3b_buyer_migration_safety.py::test_a_created_company_gets_one_creation_row_saying_where_it_came_from`, because `migrate_deal_buyers.py` breaks a `created_at` tie by a random deal id) | STILL OPEN | Low | `development.md` §9 | `test_dev1_decision_evidence.py::test_new_decisions_record_the_current_rules_and_cycle`: the listing **already** orders by `decided_at DESC, id DESC`, and that cannot fix it — ids are random UUIDs, and on Windows two quick decisions can share a timestamp — so order ties by the decision chain (a decision follows the one it supersedes) and keep the assertion; `test_expiry_sweep.py::test_sweep_can_use_the_partial_ck_index` (asserts a query plan; whole suite only). §12, PR-E | No |
| R-39 | The OpenAPI artifact test compares `info.title`, which comes from `APP_NAME` | STILL OPEN | Low | `development.md` §8 | Pin the title in code, or leave it out of the comparison | No |
| R-40 | The suite cannot run inside the `aner-app` container | STILL OPEN | Low | — | `test_openapi_artifact_is_current.py` needs `./frontend`; mount it in compose | No |
| R-41 | Accounts created before 29 September with a special-use address (`admin@demo.local`) cannot sign in | STILL OPEN (data) | Low | — | Make a new account with a real-looking address and deactivate the old one (Settings cannot change an email). Neither `crm_release_audit` nor the shared development database has one (checked 4 October); it can only concern `crm_uat_walk` | No |

**Found or decided in the post-merge audit (4 October 2026).** Each is planned in §12.

| Id | Item | Status | Priority | Source | Plan | Decision |
|---|---|---|---|---|---|---|
| R-19 | A deactivated invoicing branch blocks the handover: guard condition 8, "the invoicing branch *state* is deactivated" | **DONE — VERIFIED** 5 October (§13) | Medium | D-04 (block) | PR-B (built early) | Decided |
| R-43 | **Every disclosure of a company to a masked role is audited** (BQ-2). Only `CompanyDirectory.match` writes the audit row today; the duplicate-PAN refusal (plan P4-3: "the same rule governs the duplicate-PAN refusal message"), the GSTIN warnings on create and edit, `also_held_by` on GST registrations and the CSV import's `candidates` name the holder without one | STILL OPEN | Medium | BQ-2; plan P4-3, P6-3; D-07 (yes) | PR-D | Decided |
| R-44 | OPS-0 and OPS-1 are incomplete. OPS-1's notice to users names only 0031, but an upgrade from 0022 also switches on the pre-shipment requirement (0030), maker-checker and rule B, Clear expiry (Clears older than a year stop being current at once), the buyer sanctions/AML requirement and the invoicing-branch rule. OPS-0's inventory counts none of what those, or R-31, will meet | STILL OPEN | High | `deal-and-buyer.md` §6.1.1; plan P3-3, P3-4, P6-7 | PR-A | No |
| R-45 | Documentation drift: architecture §8 lists 9 history dimensions (the code and `history-row.md` have 14); open items in `company-record.md` §9 and `criterion-result.md` §9 never reconciled; "to confirm" text the lead settled on 2 October (`background-check.md` §14.1's D4 note, `domain/compliance_facts.py`'s docstring) | STILL OPEN | Low | — | PR-A | No |
| R-46 | Frontend-plan asks **A1** (list rows carry every gauge), **A3** (structured handover conditions), **A4** (background-check filter on company search) and **A7** (the server's route-role table as a guarded artifact) | STILL OPEN | Medium | `frontend-plan.md` §13; D-19 | PR-B (A3), PR-F | Decided |
| R-47 | DEVELOPER no longer sees branch flags: flag status, reason, flagged count and the flag/unflag history details are withheld | **DONE — VERIFIED** 5 October (§13) | Medium | D8; D-05 (hide) | PR-C (built early) | Decided |
| R-48 | Re-date a `NOT_NOW` check-back in one step, as its own action with its own history event (not a gauge move) | STILL OPEN | Low | D-14 | PR-E | Decided |
| R-49 | Refresh-token reuse window: the token just rotated is accepted once more for about 30 seconds | STILL OPEN | Low | D-13 | PR-G | Decided |
| R-50 | CI: GitHub Actions running `development.md` §7 on every pull request, the whole suite nightly | STILL OPEN | Medium | D-16 | PR-H | Decided |

---

## 4. Decisions (answered 4 October 2026)

The lead answered every decision below on 4 October 2026, after the post-merge audit. Each
was put with its options and a recommendation drawn from the architecture; where the
architecture did not settle it, the recommendation said so. Where a "confirmation" is
recorded, the lead accepted the recommendation ("do what's best") rather than restating the
rule. Each answer is written into the contract that owns the rule in §12's PR-A (rules with
no code change) or in the pull request that builds it (development.md §8: the contract
changes with the code).

| Id | Question | Answer | Effect |
|---|---|---|---|
| **D-01** | May the invoicing branch be changed before handover? | **Yes — closed as already answered.** Plan P6-6 ("may be set any time before handover", IQ-20) outranks allocation 2.8 ("set-once"), whose own header says it reopens no decision | None: built that way (0036, `InvoicingBranchPicker`). Allocation 2.8 marked as superseded in PR-A |
| **D-02** | Is restoring the `pg_dump` the only rollback of P4-6? | **Yes.** Plan §17.1 allows restore-from-backup when the migration says so. Each environment's OPS-5 runs in a **write freeze** from the dump until `--validate` passes, so a restore loses nobody's work | OPS-5 unblocked on this count (§8) |
| **D-03** | One invoice per deal? | **No rule** (as built) | None. `trade-history.md` §2's "open" removed in PR-A |
| **D-04** | A deactivated invoicing branch: block or warn? | **Block** | R-19: guard condition 8 (PR-B) |
| **D-05** | Should DEVELOPER see GST branch flag reasons? | **No — hide flag status, reason, flagged count and the flag/unflag history details** (D8's reasoning) | R-47 (PR-C) |
| **D-07** | Does BQ-2 cover the shared-GSTIN warnings and CSV-import candidates? | **Yes, and every such disclosure is audited** | Holders stay named (plan P6-3); R-43 adds the missing audit rows (PR-D) |
| **D-08** | The move to `CUSTOMER` commits with the `CLEAR`/`QUALIFIED` that completes it (U4) | **Confirmed** | None; "awaiting confirmation" text removed in PR-A |
| **D-09** | Only a `PROSPECT` or `CUSTOMER` may have a deal opened | **Confirmed** | None; as D-08 |
| **D-10** | The D2 clarification (a reviewed `REVIEW` result no longer blocks `CLEAR`) | **Closed as already answered**: IQ-2 (1 October) counts `REVIEW` + `ACCEPTED` as passed, and the lead confirmed `REVIEW` + `REJECTED` reads as `FAILED` on 2 October (`background-check.md` §14.2) | None; as D-08 |
| **D-11** | The D5 amendment: risk refused on every move but `CLEAR` | **Confirmed** | None; as D-08 |
| **D-12** | Does `CUSTOMER` replace `ONBOARDED` for the ANER-4.2-S1T2 consumer? | **Confirmed.** The consumer is not in this checkout; under decision 10 it listens for `company.became_customer` | The lead tells that consumer's owner. `company-record.md` O2 closed in PR-A |
| **D-13** | The reload-burst refresh window | **A short server-side reuse window** (about 30 seconds) for the refresh token just rotated | R-49 (PR-G). Changes architecture §9's "a second exchange of the same token is refused" |
| **D-14** | Re-date a `NOT_NOW` check-back in one move? | **Yes, as a separate action** with its own history event; the gauge keeps its "never to itself" rule | R-48 (PR-E) |
| **D-15** | Reason codes: ADMIN route, or seeded settings changed by migration? | **Keep migrations** (plan P1-1/P1-2: identical in every environment) | None. `criterion-result.md` Q5 closed in PR-A |
| **D-16** | CI (U6) | **GitHub Actions**, owned by the lead | R-50 (PR-H) |
| **D-17** *(new)* | Which databases are "every environment" for OPS-0 – OPS-6 and R-25? | **Only those holding data someone needs:** `crm_uat_walk` (on another server; the lead runs the steps there), `crm_release_audit`, the demo database. Development and test databases are rebuilt from empty plus sample data, never migrated through P4-6 | §8; R-25's precondition |
| **D-18** *(new)* | R-31: what happens to companies that already have no name? | **Pre-check, then `NOT NULL`.** Code stops creating them now; the contract migration refuses while any exists and lands after OPS-0 shows none in scope. (A `NOT VALID` check was rejected: Postgres re-checks it on every update, and the gauges live on the company row.) | R-31 (PR-E, PR-L) |
| **D-19** *(new)* | Which frontend-plan backend asks are built? | **A1, A3, A4, A7.** A6 and A8 deferred; A5 stays deferred (§5) | R-46 |
| **D-20** *(new)* | Frontend plan §17 Q1–Q3 | **The designed defaults:** placeholder brand mark until a logo exists, a read-only Developer desk, Review in the Admin rail | R-33 Phases 1–4 as `frontend-plan.md` describes |
| — | Contract open items: `company-record.md` O1 (rename `customer_id`), O4 (mask CIN); `criterion-result.md` Q1 (range criteria), Q2 (`qualification_initial` row), Q3 (acknowledgement), Q4 (RXIL package) | **Closed:** O1 no rename; O4 CIN masked (architecture §9); Q1 not needed; **Q2 won't be built** (the column default stands for it); Q3 obsolete; Q4 is D12 (§5) | PR-A |
| — | The DPDP meeting | **Nothing in the plan depends on it.** P7-4, P7-5 and P7-7 stay deferred, and only sample data is used | §5 |

**Closed before this audit:** D-06 (a buyer company's History shows trade rows — answered by
`trade-history.md` §6 and plan P5-3/P5-4, built as R-23). Confirmed on 2 October and recorded
in `contracts/background-check.md` §14.2: Developer 1's IQ-2 edge cases, `CHECK_CYCLE_EMPTY`,
the maker-checker details, the expiry backfill, keeping `BuyerChecks` until P4-10, D4's
verification side, no D2 amendment for placeholders, and no document required to `CLEAR`
(to be revisited with P7-7).

**No decision is open.** A new one gets the next id, D-21.

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
| R-42 — group-level `--confirm-name` for the buyer migration | DEFERRED | Only if a live dry run shows many rows sharing one contested identifier. The rehearsal's 330 rows sharing `NL-8899` were test-suite debris (`NL-8899` is the tests' fixture value), so nothing suggests a real environment needs it | §8 |
| Frontend-plan asks A6 (`relationship_manager_user_id` and a "my companies" lens) and A8 (`dry_run` on CSV import) | DEFERRED (D-19) | A6: a product rule for how RMs are assigned. A8: a business need for a server-checked import preview | `frontend-plan.md` §13 |
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
| R-19 | A deactivated invoicing branch does not block handover | DONE — VERIFIED (5 October) | Guard condition 8; `test_l3b_invoicing_branch.py`, `test_l3b_handover_conditions.py`; `deal-and-buyer.md` §6.1 |
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
| R-31 | `name`/`country` `NOT NULL` | STILL OPEN (D-18) | §3.2; §12 PR-E, PR-L |
| R-32 | Name matching at scale | DEFERRED | §5 |
| R-33 | Frontend plan | DONE — VERIFIED (5 October; PR #19) | §3.2; `access.matrix.test.tsx`; §13 |

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

**Environments (D-17):** `crm_uat_walk` (on another server; the lead runs these steps
there), `crm_release_audit` (on the development server, at `onboarding_0022`: 11 companies,
5 legacy deal buyers, 2 open deals, IEC pre-check 0) and the demo database. Development and
test databases (`aner_settlement`, the scratch copies) are not migrated through P4-6: they
are rebuilt from empty plus sample data when they need to be current. The procedure for
the two commands (rehearsal on a copy of *that* environment first, quiet settings, Windows
console) is [`development.md`](development.md) §10.1.

**The demo database** built on 4 October 2026, `crm_demo`, is already at head (0043) with
the sample data, so for it OPS-1 – OPS-4 are done and OPS-5 has three legacy buyers to
migrate. Being a clean product of the real services, with no test debris, it is also the
best first rehearsal of OPS-5 and OPS-6 — on a copy, never on `crm_demo` itself before a
demo.

| Id | Step | Status |
|---|---|---|
| OPS-0 | Run `backend/scripts/crm_data_inventory.sql` (read-only) on every environment and keep the output with the migration ticket. It sizes OPS-5, decides R-30 and, once PR-A extends it (R-44), also counts what the upgrade will change for users and what R-31 will meet. Never attach numbers from a development database | STILL OPEN |
| OPS-1 | Before deploying: the IEC pre-check for 0040 must return 0 — `SELECT count(*) FROM onboarding.exporter_profile WHERE iec IS NOT NULL AND iec !~ '^[A-Z0-9]{10}$'` (0 on `crm_release_audit`, 4 October). **Tell the users what changes** (R-44): (1) 0031 — `export_history` and `export_licence` stop counting towards the suggestion, so an undecided lead may now suggest `QUALIFIED`; (2) 0030 — a deal cannot be handed over without a scanned-clean pre-shipment document, so open deals without one are blocked; (3) `CLEAR`, `FLAGGED` and `ON_HOLD` take two compliance officers, and a `CLEAR` needs KYB, AML and sanctions passed in the current cycle; (4) a Clear lasts one year, so one older than that stops being current at once — its company is listed as Re-KYC due and its deals cannot be handed over; (5) a deal's buyer needs sanctions **and** AML `PASSED`; (6) a seller with an active GST registration must have the deal's invoicing branch recorded | STILL OPEN |
| OPS-2 | `pg_dump` | STILL OPEN |
| OPS-3 | `alembic upgrade head` (to 0043). Read the counts 0033, 0035, 0042 and 0043 print; 0042 leaves a foreign key `NOT VALID` where old rows violate it and prints the query that lists them | STILL OPEN (done on `crm_demo`) |
| OPS-4 | Deploy. Users can now name **or create** a buyer company on a deal (R-24), which R-07's `ALREADY_LINKED` handles in OPS-5 | STILL OPEN |
| OPS-5 | **Buyer migration P4-6.** First: P2-7's precondition must be 0 — `SELECT count(*) FROM onboarding.deal WHERE stage = 'HANDED_OVER' AND handover_snapshot IS NULL`. **Freeze writes** from the dump until `--validate` passes (D-02: restoring the dump is the only way back, and the freeze is what makes a restore lose nothing). Then `--dry-run`; Compliance reviews the look-alikes (IQ-8) and the rows that need a person; `--apply --run-id <id>` with `--confirm-name` lines; `--validate` (every count 0); re-run `--apply` (creates nothing). Also check `SELECT count(*) FROM onboarding.verification_result WHERE entity_type = 'BUYER' AND subject_company_id IS NOT NULL` | STILL OPEN in every environment |
| OPS-6 | **Relationship backfill P5-5**: `--dry-run`, `--apply --run-id <id>`, `--validate`. Undo is one `DELETE` (`--report-run`), as long as no invoice points at the run's relationships | STILL OPEN |
| — | Then R-25 (PR-J), then R-26 (PR-K), then R-31's contract migration once OPS-0 shows no nameless company (PR-L) | — |

**What the rehearsal on `p46_scratch` does and does not show.** `p46_scratch` is a copy of a
*test* database (`dev3_audit_merged`) at `onboarding_0041`, two revisions behind head — not
a copy of an environment, so by `development.md` §10.1's own rule its numbers prove nothing
about any environment. Read-only `--validate` re-run on 4 October 2026:

- 453 rows migrated by rule (387 `NEW`, 21 `REGISTRATION_NUMBER`, 45 `ALREADY_LINKED`),
  391 companies created; a second `--apply` created nothing. **This is what it proves:** the
  command works and is idempotent on a large, messy copy.
- 325 deals / 330 rows "need a person" because they share registration `NL-8899`.
  **Test debris** (post-merge audit): `NL-8899` is the registration number the test fixtures
  use (`test_l3b_deal_buyer.py`, `test_l3b_handover.py`, `test_l3b_handover_snapshot.py`).
- 13 handed-over deals have no handover snapshot. **Test debris**, not a P2-7 failure: all 13
  were made on 2 October by raw SQL in `test_l4b_buyer_checks.py::_mark_handed_over` and
  `test_crm_integrity_guards_0022.py::_deal_at`, which set the stage directly; none has a
  handover history row and 10 have no buyer at all — states the product cannot produce.
- The relationship backfill has not been run on this copy (458 deals with a buyer company
  and no relationship).
- These checks are 0, as they must be: BUYER results without a subject, buyers that are
  their own seller, creation history rows, masked identifiers, and both `ALREADY_LINKED`
  consistency checks.

So the real rehearsal is still owed: on a copy of each environment, at head.

---

## 9. Validation baseline (4 October 2026, `6cd71db`)

Run as in [`development.md`](development.md) §7, against a scratch database at head
(`pr_f3_audit`, a copy of the 15.9k-company scratch data). Never the shared
`aner_settlement`, which is at 0027.

**Re-run after the merge, on `main` @ `05b43eb` (4 October 2026, evening):** every gate below
at the same result — CRM suite **2,711 passed, 1 skipped, 0 failed** (30 min), ruff 16,
import-linter 19/0, tsc 0, eslint 0 errors / 2 warnings, vitest 51 files / 636 tests, the
production build, and the fresh-database round trip with `alembic check` (on a throwaway
database, dropped afterwards). The whole suite was not re-run: nothing changed outside the
CRM, and the code changed only in comments since `6cd71db`. **Demo rehearsal** (a copy of
`crm_demo`): `demo.md` §3 and §5's claims checked against the API, and 91 screens walked as
RM, Compliance, Admin and Developer on the production build in headless Chrome — no
JavaScript error, no failed request, every forbidden screen the same "Page not found".

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

Superseded on 4 October 2026 by the implementation plan in §12, written once every decision
was answered (§4). In short: the demo first; then the code pull requests PR-A – PR-I in §12's
order, with the redesign (R-33) last; alongside them, the lead runs OPS-0 – OPS-6 in each
environment (§8); only after OPS-5 has passed everywhere, R-25 (PR-J), R-26 (PR-K) and R-31's
contract migration (PR-L). §5 items only when their trigger happens; P7-7 before any real data.

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

---

## 12. Implementation plan (4 October 2026, after the decisions)

Written once every decision in §4 was answered. Each pull request leaves `main` working and
passes `development.md` §7 at the §9 baseline before it merges (CRM suite; the **whole**
suite as well where a PR touches `app/platform`, `app/shared` or another module — PR-G).
Every PR that changes a route or a response shape adds its rows to
`tests/contract/test_route_authorization_coverage.py` **and**
`onboarding/tests/integration/test_route_authorization.py`, regenerates `frontend/openapi.json`
and `src/lib/api/schema.ts` (`pnpm generate:api`, `APP_NAME` at its default), keeps the
masking sweep green, and changes its contract in the same PR. Nothing here is committed by
the developer: changes are left for the lead to review, commit and merge. Next free migration
number: **0044**.

### Order

| # | PR | Items | Depends on | Migration |
|---|---|---|---|---|
| 0 | **Demo** (5 October) | Accounts on `crm_demo`. On 5 October the lead chose to build R-19 and R-47 before the demo, with four demo fixes (§13) | — | — |
| 1 | PR-A Documentation and operations prep | R-44, R-45; record §4 | — | — |
| 2 | PR-B Handover guard and deal view | R-19, R-34, R-46 (A3) | — | — |
| 3 | PR-C DEVELOPER and branch flags | R-47 | — | — |
| 4 | PR-D Identifier disclosure audit | R-43 | — | — |
| 5 | PR-E Engineering clean-up | R-31 (first half), R-35 – R-40, R-48 | — | — |
| 6 | PR-F Backend asks | R-46 (A1, A4, A7) | PR-B for A3 only | — |
| 7 | PR-G Refresh-token reuse window | R-49 | — | possibly `auth_0006` |
| 8 | PR-H CI | R-50 | the lead enables Actions | — |
| 9 | PR-I1 – I5 Redesign | R-33 Phases 1 – 5 | PR-F for the asks' fallbacks to switch off | — |
| ops | OPS-0 – OPS-6 per environment (§8) | run by the lead | PR-A (inventory, notice) | — |
| 10 | PR-J Retire `deal_buyer` writes | R-25 | OPS-5 passed in every environment in scope | **0044** |
| 11 | PR-K Delete `BuyerChecks` | R-26 | PR-J | — |
| 12 | PR-L Name and country required | R-31 (second half) | OPS-0 shows no nameless company in scope; PR-E | **0045** |

PR-B – PR-H are independent of one another and may be reordered; PR-B first because it
closes the only plan requirement not yet built (R-34). Two edits to the handover guard must
not run in parallel (plan §16.1): PR-B is the only one here.

### PR-A — Documentation and operations prep (R-44, R-45; recording §4)

- **Objective:** every decision in §4 written where its rule lives; OPS-0 and OPS-1 complete;
  the drift found by the audit gone. No behaviour change.
- **Files:** `backend/scripts/crm_data_inventory.sql` (new read-only sections: companies with
  no `name` or `country` (R-31); open deals without an `AVAILABLE` `PRE_SHIPMENT` document
  (0030); `CLEAR` companies whose last Clear is older than a year (0027); open deals whose
  legacy buyer has no `PASSED` sanctions or AML (P3-4); open deals of sellers with an active
  GST registration and no invoicing branch (P6-7)); `docs/architecture.md` (§8 dimensions
  list, §11 "awaiting confirmation" paragraph, §12 accepted list); `docs/contracts/deal-and-buyer.md`
  (§2 D-09 confirmed), `background-check.md` (§14 D2/D5/D11 confirmed, §14.1 D4 note),
  `company-record.md` (§9 O1–O4 closed, O2 per D-12), `criterion-result.md` (§9 Q1–Q5
  closed), `trade-history.md` (§2 D-03), `developer-allocation.md` (2.8 superseded by plan
  P6-6, D-01), `domain/compliance_facts.py` docstring (REVIEW + REJECTED confirmed 2 Oct).
- **Schema / API / frontend / authorisation / transactions:** none.
- **Tests:** none change; run the inventory on `crm_demo` to prove it parses (never attach
  those numbers).
- **Rollback:** revert the PR. **Done when:** no document calls a decided question open, and
  OPS-0's script answers every count §8's OPS-1 notice needs.

### PR-B — Handover guard and deal view (R-19, R-34, R-46 A3)

> **R-19 is built** (5 October, §13): condition 8 and `BranchFlagReader.is_active` as
> described below. PR-B's remaining scope is R-34 and A3.

- **Objective:** (1) a deal whose recorded invoicing branch is deactivated cannot be handed
  over (D-04); (2) the deal view warns — without blocking — when the buyer's KYB is not
  passed or its background check is not `CLEAR` or its Clear has expired (plan P3-4, P4-7);
  (3) the guard's conditions are served as a list, not only as one joined sentence (A3).
- **Files:** `domain/handover_conditions.py` (condition 8 after 7: "the invoicing branch
  *state* is deactivated", only when a branch is recorded; a second, separate tuple of
  **warning** conditions over the same `HandoverSubject`; both pure); `BranchFlagReader`
  gains `is_active(gst_registration_id)` — `application/branch_flags.py`, the null
  `NoBranchFlags` answers "active" so an un-injected reader adds no refusal;
  `domain/compliance_facts.py` + `application/compliance_facts.py` (`PartyComplianceFacts.kyb`
  by IQ-2's rule, `check_state(…, "KYB")`; legacy buyers read KYB from their `deal_buyer`
  checks); `api/schemas/deal.py` (`handover_conditions: [{key, met, message}]` and
  `handover_warnings: [{key, message}]` beside `handover_blocked_reason`, which stays);
  `application/deal_service.py` (`_to_view` fills both); `api/schemas/background_check.py`
  (`CompanyComplianceFactsResponse.kyb`); frontend `DealDetailPage.tsx` (pre-flight list
  from `handover_conditions`, warning callout from `handover_warnings`, in today's styling
  — the redesign restyles it in PR-I4), `CompanyComplianceSummary.tsx` (KYB chip from the
  served `required_checks`, nothing derived on the client).
- **Schema / migration:** none.
- **Authorisation:** both new fields are served only to roles served `handover_blocked_reason`
  (OPERATIONS, COMPLIANCE, ADMIN); DEVELOPER gets `[]` (D8) — masking-sweep and API tests.
- **Transactions:** condition 8 runs inside the existing share-locked guard (D10);
  `deactivate` already locks the company `FOR UPDATE` (R-18), so a deactivation and a
  handover serialise. Warnings run only on the unlocked read path.
- **Compatibility:** additive response fields; `handover_blocked_reason` unchanged in shape.
  **On deploy**, a deal invoiced from a branch deactivated earlier becomes blocked — add it
  to OPS-1's notice in the same PR.
- **Tests:** pure tests for condition 8 and each warning; guard tests with fake readers
  (deactivated branch blocks; reactivation is not possible, so re-choosing an active branch
  clears it); facts tests for KYB states incl. legacy buyers; API tests for both fields per
  role; concurrency test (deactivate during handover waits, then the guard refuses);
  `CompanyComplianceSummary` and `DealDetailPage` component tests; e2e still green.
- **Artifacts:** OpenAPI + `schema.ts`. **Docs:** `deal-and-buyer.md` §6.1 (condition 8; the
  "undecided (D-04)" paragraph replaced; warnings; the conditions list), `background-check.md`
  §12.4 (`kyb`), `frontend-plan.md` §13 (A3 landed). **Rollback:** revert; no data written.
- **Done when:** R-19, R-34 and A3 are DONE with tests, and the demo's deal pages show the
  checklist and warnings.

### PR-C — DEVELOPER and branch flags (R-47, D-05)

> **Built** (5 October, §13). The history half withholds the flag and unflag *rows*
> rather than only their reason (their from/to is the flag status), and the
> `flag_status` detail on the others; the list's totals agree with the page.

- **Files:** `api/schemas/gst_registration.py` (a DEVELOPER masking path: `flag_status` and
  `flag_reason` `null`, documented as "withheld"), `api/gst_registration_router.py`
  (`flagged_count` `null` for DEVELOPER), `api/history_router.py` (DEVELOPER keeps
  `gst_registration` rows for add/deactivate but loses the flag/unflag rows' reason and
  details — the same mechanism as `_DETAILS_HIDDEN_FROM_DEVELOPER`), frontend
  `GstRegistrationsSection.tsx` (no flag chip or reason when withheld; no new role check —
  it renders what is served).
- **Schema:** none. **Compatibility:** two response fields become nullable (a contract change
  in `company-record.md`/`history-row.md`). **Tests:** masking sweep extended; API tests per
  role; component test. **Artifacts:** OpenAPI. **Rollback:** revert.

### PR-D — Every disclosure of a company to a masked role is audited (R-43)

- **Objective:** BQ-2's "every lookup audited" holds on every path that names a holder.
- **Files:** move `CompanyDirectoryService._audit_identifier_lookup` into one application
  helper used by: `exporter_profile_service` (duplicate-PAN refusal and the GSTIN warnings on
  create and edit), `gst_registration_service` (`also_held_by` on add and flag),
  `company_import_service` (each row's `candidates`). The audit is written for masked roles
  (OPERATIONS) and, as today on `/companies/match`, for every caller.
- **Transactions:** the audit row is committed even when the request is refused (the R-24
  precedent: "the audit row is committed before the refusal"); on success it commits with the
  write.
- **Tests:** one test per path that a lookup writes exactly one audit row naming who, when
  and which company; refusal paths still audited; no identifier in the audit row beyond what
  `/companies/match` already records. **Docs:** `company-record.md`, `deal-and-buyer.md` §3.0,
  architecture §9. **Rollback:** revert (audit rows are append-only and harmless).

### PR-E — Engineering clean-up (R-31 first half, R-35 – R-40, R-48)

- **R-31:** `CreateExporterProfileRequest.name` and `country` required (422 without them);
  `ExporterProfileService.create_or_get_profile` requires both; every test and fixture that
  creates an unnamed company passes a name (about 22 test files use the service directly).
  No migration yet (PR-L).
- **R-35:** remove `GET /exporters/activities/pending`, its two authorisation rows and its
  OpenAPI entry; `engagement.md` §5.6. Confirm no outside caller first (none in the frontend).
- **R-36 (A9):** `created_by_name` on criterion versions through `api/actor_names.py`;
  `QualificationCriteriaPage.tsx` shows the name.
- **R-37 (A2):** `total` on `GET /exporters` (a `count(*)` over the same filter);
  Home and Companies show exact counts instead of "200+".
- **R-38:** the decision listing orders ties by the chain (a decision after the one it
  supersedes) — in Python after the query, the page being small — and the test keeps its
  order assertion; the query-plan test in `platform/idempotency` asserts the index exists and
  matches the predicate instead of a plan (that file is platform code: whole suite for this
  PR).
- **R-39:** leave `info.title` out of the artifact comparison (or pin it in code), so a local
  `APP_NAME` cannot fail the test; `development.md` §8.
- **R-40:** mount `./frontend` read-only into `aner-app` in `docker-compose.yml`.
- **R-48 (D-14):** `PUT /exporters/{id}/conversation/check-back {check_back_on}` — staff,
  only while `NOT_NOW`, date not in the past (the existing rule), refuses an unchanged date;
  one `conversation` history row, `event_type = conversation_check_back_changed`, from/to
  `NOT_NOW`, details `{from, to}` (the `deal_buyer_changed` precedent); the Follow-ups list
  re-reads it. Frontend: a "change date" control beside the check-back date.
- **Tests:** each item's own; route authorisation rows; OpenAPI. **Rollback:** revert.

### PR-F — Backend asks A1, A4, A7 (R-46)

- **A1:** company list rows carry `conversation`, `conversation_check_back_on`, and for staff
  only `background_check`, `awaiting_approval`, `rekyc_due` (omitted for DEVELOPER, D8) —
  read in one query, no N+1; masking sweep.
- **A4:** `background_check` filter on `GET /exporters`, refused (403) for DEVELOPER.
- **A7:** `frontend/route-roles.json` generated from `GATED_ROUTES`
  (`tests/contract/test_route_authorization_coverage.py`) and guarded like `openapi.json`; a
  vitest asserting every capability in `src/platform/access/capabilities.ts` maps to routes
  whose roles match it (the drift check `frontend-plan.md` §4.4 waits for).
- **Tests / artifacts:** API and masking tests; the new artifact test; OpenAPI.

### PR-G — Refresh-token reuse window (R-49, D-13)

- **Files:** `app/api/rest/auth/router.py` (`/auth/refresh`), `app/platform/authentication/services.py`
  and `models.py`. A token revoked **by rotation** less than `AUTH_REFRESH_REUSE_SECONDS`
  (default 30) ago is accepted once more and rotated normally; a token revoked by logout, or
  reused after the window, is refused as today. If the model cannot tell rotation from logout
  (`revoked`, `revoked_at` only), add `replaced_by_id` in migration `auth_0006` (nullable,
  set on rotation).
- **Transactions:** the existing `FOR UPDATE` read stays, so two exchanges still serialise.
- **Tests:** within the window succeeds once; after it fails; logout-revoked fails; the 499
  rollback test still passes; the reload-burst test in `lib/api/client.test.ts` unchanged.
- **Gates:** the **whole** suite (platform code). **Docs:** architecture §9 (the rotation
  sentence), `demo.md` §1 (the reload tip). **Rollback:** revert; `auth_0006` downgrade drops
  the column.

### PR-H — CI (R-50, D-16)

- **File:** `.github/workflows/ci.yml`. On pull requests: Postgres 16 service; Python 3.12
  with `requirements.txt` + `requirements-dev.txt`; test values for the read-only role
  passwords and the audit settings as job variables (none secret); `alembic heads` (one),
  `alembic upgrade head`, `alembic check`, `pytest --crm`, ruff, `lint-imports --config
  importlinter.ini`; Node 20 + pnpm: tsc, eslint, vitest, build. Nightly and on demand: the
  whole suite.
- **Ops prerequisite:** the lead enables Actions on `PMadhuri97/Exporter-CRM` and pushes.
  **Docs:** `development.md` §7 (CI exists), architecture §12 ("there is no CI" removed).

### PR-I1 – I5 — The redesign (R-33 Phases 1 – 5)

As `frontend-plan.md` §14 lays out, one PR per phase and one per screen in Phase 4, with
D-20's defaults. Phase 1 tokens, type and primitives (Ink & Paper; Instrument Serif/Sans and
JetBrains Mono; the raw-palette lint rule; the 21 files of §3.2 moved to tokens); Phase 2 the
shell (rail, context bar, ⌘K, shortcuts; Pipeline folded into Companies; lucide removed);
Phase 3 the signature components; Phase 4 the screens in §14's order, re-composing
`InvoicingBranchPicker` (R-05), the create-buyer step (R-24) and PR-B's checklist rather than
rebuilding them; Phase 5 polish, and each landed ask's fallback switched off. The role-matrix
test stays green throughout and gains PR-F's drift check. Gates per phase: `frontend-plan.md`
§15.

### PR-J — Retire `deal_buyer` writes (R-25), after OPS-5 everywhere in scope

- **Prerequisite check before starting:** `--validate` exits 0 on `crm_uat_walk`,
  `crm_release_audit` and the demo database (the lead's evidence from §8).
- **Migration `onboarding_0044_deal_buyer_ro`:** a trigger refusing `INSERT` and `UPDATE` on
  `onboarding.deal_buyer` (the table and its rows stay: BUYER results and snapshots reference
  them); downgrade drops the trigger; raw-SQL refusal test.
- **Code:** `PUT /deals/{id}/buyer` loses its legacy form (`DealService.set_buyer`'s
  `DealBuyer(...)` write removed); `DealView.buyer` stays read-only for one release (a later
  PR removes it); `sample_data_deals.py` records its three buyers as **companies**
  (`CompanyDirectory.create_buyer_company`), with their sanctions/AML on the company; the deal
  page loses "Record details instead".
- **Docs:** decision 9 rewritten in architecture §4/§11, `deal-and-buyer.md`,
  `event-envelope.md` (`deal.handed_over`), `history-row.md`; `demo.md` §3.1 (the sample deals
  now show trade history). **Rollback:** downgrade 0044 and revert.

### PR-K — Delete `BuyerChecks` (R-26)

`components/BuyerChecks.tsx`, its test, its export, the `DealDetailPage.tsx` mount and
`BUYER_CHECK_TYPES` (no other user, checked 4 October). Docs: `background-check.md` §12.2, §16.

### PR-L — Name and country required (R-31 second half, D-18)

- **Prerequisite:** OPS-0 shows no company without a name or country in any environment in
  scope; PR-E merged (nothing creates one any more).
- **Migration `onboarding_0045_company_name_nn`:** first counts companies with no `name` or
  `country` and **refuses** if any (the 0040 pre-check precedent), printing the query; then
  `SET NOT NULL` on both. Downgrade drops `NOT NULL`. Raw-SQL refusal test; ORM declares
  `nullable=False`.
- **Development databases** are rebuilt rather than migrated past it (D-17): the shared one
  holds 6,029 nameless test companies.
- **Docs:** `company-record.md` §10 ("name required by the database" built).

### Completion

The project is complete when every row of §3 is DONE — VERIFIED or DEFERRED with its trigger
unmet, OPS-0 – OPS-6 have passed in every environment in scope with their evidence kept,
PR-J – PR-L have merged, and §9 is re-run at the new baseline. Until then, "release-ready"
is not claimed.

---

## 13. UAT and demo-readiness audit (5 October 2026)

Run on `main` @ `46097bd` (the redesign, R-33 Phases 1–5, merged as PR #19). It was a
product UAT, not a test run: the business journeys were walked through the API and in
the redesigned UI as each role, on a copy of the demo database, never on `crm_demo`
itself. The lead answered four questions first: build R-19 and R-47 now; rebuild the demo
database clean; restore this file's answered decisions (they had been left in
`stash@{0}`); and rewrite `demo.md` for the redesign.

### 13.1 How it was verified

| Layer | What ran | Result |
|---|---|---|
| API journeys | A script over every core journey as every role (auth and `API_USER`; company create, duplicates, masking, edit; qualification; conversation; deal stages; buyer match / create / set-once; documents; seller checks, screening, maker-checker incl. self-approval refused and stale 409; buyer checks; branch record / flag / deactivate; handover; invoice, outcome, supersede, stale supersede; Re-KYC; marker; DEVELOPER surface) | Before: 142 / 146. After the fixes: **145 / 146**; the one failure is R-31 (deferred) |
| Every screen by URL | 4 roles × 44 screens in a headless browser on the production build, recording failed requests, console errors and crash text | **No failed request, no console error, no crash**; "Nothing here." exactly where the role table says |
| The main path in the UI | Add company → GST branch → qualify → conversation → open deal → no-match → create a foreign buyer → upload → start check (OPERATIONS) → screening, KYB/AML/Sanctions, propose Clear (COMPLIANCE) → approve from the Desk (second COMPLIANCE) → buyer's sanctions/AML → branch → hand over → outcome | **Works end to end**. Then, after the fixes: Enter in the picker, the new Ledger lines, the deactivated-branch refusal and DEVELOPER's view of a flagged branch, each in the UI |

### 13.2 Findings

| Id | Pri | Kind | Finding | Status |
|---|---|---|---|---|
| — | P0 | Setup | The demo preview (`:4173`) served a build from before the redesign, and `frontend/node_modules` lacked the redesign's packages, so `pnpm build` failed on `main` | **Fixed**: `pnpm install`, rebuilt, preview restarted (`demo.md` §1 says to restart it after every build) |
| R-19 | P1 | Bug (decided) | A deal handed over through a branch deactivated after it was recorded | **Done** — guard condition 8 |
| R-47 | P1 | Security (decided) | DEVELOPER read branch flag status, reason and count, and the flag rows in history | **Done** |
| R-51 | P1 | UX | The Ledger rendered a buyer-company row and an invoicing-branch row as "Gathering Paperwork" (their `to_value` is the deal's stage), an invoice as its currency and a branch row as a bare state name; `demo.md` promised "Buyer recorded: …" | **Done** — `HistoryTimeline.tsx` names each from the details the server writes |
| R-52 | P1 | UX | The buyer picker looked a name up only when the field lost focus; Enter did nothing and the hint said "Finish typing" | **Done** — Enter looks it up; the hint says so |
| — | P1 | Data | `crm_demo` held rehearsal records (ABC Exports, ABCD Exports, deals "Test" and "Test Deal") | **Fixed**: rebuilt from empty + sample data; the five accounts copied with their password hashes; the old one kept as `crm_demo_rehearsal_1005` |
| — | P1 | Docs | `demo.md` described the screens before the redesign; this file's decisions were only in a stash | **Fixed** |
| R-31 | P2 | Gap | `POST /exporters` still accepts a company with no name or country (the form requires both) | Open — PR-E / PR-L as planned |
| R-53 | P2 | UX | Two refusals put internal ids in `human_readable_message` ("Deal `<uuid>` cannot be handed over: …", `TRADE_INVOICE_ALREADY_RECORDED`). The screens show their own text for the first; the second is not reachable from the UI | Open |
| R-54 | P2 | UX | Raw codes in UI text: the handover refusal ("PRE_SHIPMENT", "MISSING, not PASSED", "PROSPECT, not CUSTOMER"), the risk options ("LOW"), check types title-cased from codes ("Kyb", "Aml") | Open — the check-type half is done (R-60, §14); the refusal half is A3 (PR-B) |
| R-55 | P3 | A11y | The branch flag form's reason field has no label | Open |
| R-56 | P3 | UX | Deactivating a branch is one click with no confirmation (reversible: adding the GSTIN again reactivates it) | Open |
| — | P3 | Data | The Desk greets by the first word of the full name, so the demo account "Relationship Manager" reads "Good morning, Relationship" | Not work: name the account |

**Operational notes.** `uvicorn --reload` on this machine stopped reloading at some point
on 5 October, and its spawned worker kept serving `:8000` after the reloader was stopped:
check the worker's PID, not only the reloader's, when restarting. `crm_demo`'s backend now
runs **without** `--reload`, so nothing changes under the demo. `vite preview` reads its
file list at start-up: restart it after every build. It listens on `localhost` (IPv6 on
this machine); a client that only tries `127.0.0.1` is refused.

### 13.3 What changed (unstaged)

| Area | Files |
|---|---|
| R-19 | `domain/handover_conditions.py` (condition 8, `BranchFlagReader.is_active`, `NoBranchFlags` answers "active"), `application/branch_flags.py`; tests `unit/test_l3b_handover_conditions.py`, `integration/test_l3b_invoicing_branch.py` |
| R-47 | `api/schemas/gst_registration.py` (`withholds_branch_flags`; `flag_status` nullable), `api/gst_registration_router.py` (`flagged_count` nullable), `api/history_router.py` (`_EVENTS_HIDDEN_FROM_DEVELOPER`, `flag_status` detail), `application/history_service.py` and the history repository (`exclude_event_types`, page and total); tests in `integration/test_dev3_gst_branch.py`, `GstRegistrationsSection.test.tsx`; `frontend/openapi.json`, `src/lib/api/schema.ts` regenerated |
| R-51, R-52 | `HistoryTimeline.tsx` (+ test), `CompanyPicker.tsx` (+ test) |
| Docs | `architecture.md` §5, §9; `contracts/deal-and-buyer.md` §6.1; `contracts/company-record.md` (DEVELOPER and flags); `contracts/history-row.md`; `demo.md` (rewritten); this file |

No migration. Next free number still **0044**.

### 13.4 Deliberately not done today

R-31, R-34, R-43, R-46, R-48 – R-50, R-53 – R-56; R-25 / R-26 (the sample deals keep their
legacy buyers until P4-6 and PR-J); R-35 – R-41; every OPS step. None blocks the demo
script in `demo.md`.

### 13.5 Gates (5 October 2026, `main` @ `46097bd` + the unstaged changes above)

| Gate | Result |
|---|---|
| Migration head | One: `onboarding_0043_identity_type` |
| CRM suite (`pytest --crm`) | **2,720 passed, 1 skipped, 0 failed** of 2,721 — the 4 October baseline (2,711 / 1 / 0) plus the 9 new tests; the skip is the Windows symlink test. Run as 11 chunks across three databases at head (`pr_f3_audit` and two clean copies), because one 50-minute background run is reaped under memory pressure on this machine |
| Ruff | 16 findings, all pre-existing (none in a changed file) |
| import-linter | 19 kept, 0 broken |
| TypeScript | 0 errors |
| ESLint | 0 errors, 2 warnings (`AuthContext.tsx`, pre-existing) |
| Frontend tests | 64 files, **884** passed (880 + 4 new) |
| Production build | Passes, no chunk warning (entry 448 kB, 146 kB gzip) |
| Generated artifacts | `openapi.json` and `schema.ts` regenerated; only R-47's fields and descriptions changed |

---

## 14. CEO-demo walkthrough fixes (5 October 2026)

While a CEO demo deck was being built, the CRM was driven end to end on `main` @ `9ed6cb6`
in a browser: the production build, an empty database, and a real user for each role. No
control was affected, but four screens showed wrong or unpolished information. Each fix
has its own id, continuing from R-56, and changes only `backend/app/modules/onboarding`
and `frontend/src/modules/onboarding`, plus the regenerated API artifacts, a one-line
addition to architecture §8 and this file. No migration was added; the next free number is
still **0044**.

### 14.1 Items

| Id | Pri | Kind | Finding | Fix | Covered by | Status |
|---|---|---|---|---|---|---|
| R-57 | P1 | Bug | A seller's **Deals & trade** tab read "No buyer recorded yet" for a deal whose buyer is a company record, while the deal page and "Trade — sold to" named it. `DealService.list_for_company` read `buyer_name` only from the legacy `deal_buyer` row and ignored `buyer_company_id`, which every new deal uses (P4-4) | On the seller side `buyer_name` is the buyer company's name, read in one query for every row as the buyer side already did for sellers. The legacy name is used only when no buyer company is set. A company name is not a masked identifier (architecture §9), so every reader, DEVELOPER included, gets it as stored. Neither the response shape nor the component changed | `test_l3b_deals_as_buyer.py`: `test_the_seller_side_names_the_buyer_company_then_the_legacy_buyer` (company, legacy and no buyer on one seller) and `test_the_seller_side_names_a_buyer_company_to_every_reader` (route, as OPERATIONS, COMPLIANCE and DEVELOPER). Both fail without the fix | **DONE — VERIFIED** |
| R-58 | P1 | Bug | The Agenda's **Done** tab read "Done by 853ef096-3113-… on …": a completion was served with `completed_by` (a user id) only | `completed_by_name` on the follow-up list's completion and on the completion route's response, resolved through `api/actor_names.py` in the same lookup as `actor_name` (OPERATIONS, COMPLIANCE and ADMIN get the full name or the email; DEVELOPER gets the full name only, architecture §8). `FollowUpsPage` renders it with `actorLabel`, the fallback every other screen uses. OpenAPI and `schema.ts` regenerated (two additive fields) | `test_actor_names.py::test_a_completed_follow_up_names_who_completed_it` (named and unnamed completer, staff and DEVELOPER); `FollowUpsPage.test.tsx` (the named row, and the shortened-id fallback) | **DONE — VERIFIED** |
| R-59 | P2 | UX | A document cited as verification evidence read "Document 1c068d09…" (for example the IEC certificate on a KYB result, Background check tab) | `EvidenceList` names it by `file_name`, read through a new `useDocument` query hook (`['document', id]`, five-minute cache, no retry, fetched only when a cited document is rendered). The shortened id shows while it loads and stays if the read is refused. It reads the same `GET /documents/{id}` the download already called, which the server serves to all four roles and which the Documents tab already names, so no role can see more. DEVELOPER is still refused the Background check tab (D8) | `EvidenceList.test.tsx` (named, cached across two citations, refused read, nothing cited) | **DONE — VERIFIED** |
| R-60 | P2 | UX | Check types read "Kyb", "Aml", "Iec", … wherever the raw code went through `humanize()` (part of R-54) | `verificationTypeLabel()` in `VerificationResultRow`, `BuyerChecks`, the `ManualResultForm` options and the screenings panel's "N check types have no result" chips. The Ledger (`HistoryTimeline`), `DecisionHistory` and `ComplianceCheckChip` already used it. Non-acronym types are now in sentence case like the others ("Bank account", "Company registry") | `VerificationResultRow.test.tsx` (KYB, AML, Sanctions, Company registry), `ManualResultForm.test.tsx`, `VerificationSection.test.tsx` (the chips; "Bank Account" became "Bank account"), `BuyerChecks.test.tsx` | **DONE — VERIFIED** |

### 14.2 Not done here: handover reasons in system words (rest of R-54; A3, PR-B)

The deal's "Not ready to hand over" box still shows the server's sentence, for example
"the company is PROSPECT, not CUSTOMER; …". It was left out of this pull request on
purpose, and the browser does not rewrite it:

- PR-B's remaining scope is R-34 (the buyer KYB and incomplete-check warnings, a new facts
  field including legacy buyers) **and** A3. Plan §16.1 allows only one edit to the
  handover guard at a time, and PR-B is planned as that edit.
- A3 as planned (`handover_conditions: [{key, met, message}]`) carries the guard's own
  `message`. Built alone, it would show the same system words as a list. Plain words mean
  changing the guard's messages, which `contracts/deal-and-buyer.md` §6.1 and
  `background-check.md` quote and 38 assertions in 8 test files depend on. That is a
  contract change for PR-B and the contract's owner, not a display fix.

So R-54's refusal half stays open under PR-B, as planned (§12).

### 14.3 How it was verified

Each repro was walked again in a headless browser. The setup:

- the production build of this branch, served by `vite preview` on `:4174`;
- this branch's API on `:8010`;
- a fresh database at head, `crm_ceo_walk`, with OPERATIONS, COMPLIANCE, ADMIN and DEVELOPER
  accounts that have full names, plus one OPERATIONS account with no name to exercise the
  fallback.

The preconditions (a qualified seller, a deal at Gathering paperwork, and a new DE buyer
"Nordsee Handels GmbH" with registration number "HRB 204518 Hamburg") were created through
the same routes the screens call. The steps each repro is about were done in the UI.

| Repro | OPERATIONS | COMPLIANCE | DEVELOPER |
|---|---|---|---|
| R-57 Deals & trade row | "Nordsee Handels GmbH · opened 05 Oct 2026" | the same | the same |
| R-58 Agenda → Done | Recorded "Done" through Record outcome; the row reads "Done by Riya Operations". The unnamed account's row reads its email | the same | "Done by Riya Operations"; the unnamed account's row reads "User 5137a620…", never the email |
| R-59 Evidence | KYB result reads "IEC-certificate-Coastal-Spice.pdf · Download" | Recorded the KYB result citing the certificate through "Record a result"; the row names the file | Background check tab not offered; no document read made |
| R-60 Check types | "KYB", "AML", "IEC", "Sanctions", "Company registry"; no "Kyb"-style label anywhere on the tab | the same, and the manual form offers "KYB, Company registry, GST, IEC, UBO, AML, CFT, Sanctions, PEP, Adverse media" | not applicable (D8) |

No console error and no 5xx response on any of these screens.

### 14.4 Gates (5 October 2026, `main` @ `9ed6cb6` + this branch)

| Gate | Result |
|---|---|
| Migration head | One: `onboarding_0043_identity_type`; `alembic check` reports no new upgrade operations |
| CRM suite (`pytest --crm`) | **2,723 passed, 1 skipped, 0 failed** of 2,724 (the 5 October baseline of 2,721 plus the 3 new tests); the skip is the Windows symlink test. Run in six chunks against a scratch database at head. On the first pass two tests failed on a timestamp tie and each then passed four runs in a row; neither file is touched here: `test_l4a_background_check_service.py::TestChain::test_two_concurrent_moves_serialise_and_only_one_wins` (two decisions share `decided_at`, so the order falls to a random id: R-38) and `test_l3b_buyer_migration_safety.py::test_a_created_company_gets_one_creation_row_saying_where_it_came_from` (`migrate_deal_buyers.py` picks the "earliest" deal by `(created_at, deal_id)`, so two deals created in the same tick tie the same way; a new instance of R-38). Passing chunk paths explicitly also collected 229 legacy `onboarding_request` tests that `--crm` leaves out; 5 of them failed and are not part of the gate |
| Ruff | 16 findings, all pre-existing (none in a changed file) |
| import-linter | 19 kept, 0 broken |
| TypeScript | 0 errors |
| ESLint | 0 errors, 2 warnings (`AuthContext.tsx`, pre-existing) |
| Frontend tests | 65 files, **896** passed (884 + 12 new; one existing expectation changed: "Bank account") |
| Production build | Passes, no chunk warning (entry 448 kB, 146 kB gzip) |
| Generated artifacts | `openapi.json` and `schema.ts` regenerated with `APP_NAME` at its default; only the two `completed_by_name` fields were added. `test_openapi_artifact_is_current.py` passes |
