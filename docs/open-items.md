# Open items

Everything still open about the Exporter CRM, in one place, as of 29 September 2026
(revised after the UAT-readiness fixes the same day).
It replaced the pre-demo per-developer notes; §4 says where their still-useful content
went.

Everything still pending — the post-demo tasks, the PR audit's findings, the live-database
runbook and the decisions — is in one list: [`remaining-work.md`](remaining-work.md).

What is deliberately not built is in [`architecture.md`](architecture.md) §12. Each
contract also keeps its own open-items table (for example `company-record.md` §10);
this page lists what needs a decision or a change, and links there for detail.

---

## 1. Decisions for the programme lead

### 1.1 Implemented on a recommendation, awaiting written confirmation

| Decision | What was built | Where it is described |
|---|---|---|
| **U4 / D11** — the move to `CUSTOMER` commits in the same transaction as the `CLEAR` or `QUALIFIED` that completes it | `promote_to_customer_if_ready`, called by both; announced after the commit | architecture §5, `background-check.md` §11.3 |
| Only a `PROSPECT` or `CUSTOMER` may have a deal opened (`DEAL_COMPANY_NOT_READY`) | `DealService.open_deal`, `can_open_deal` | `deal-and-buyer.md` §2 |
| **D2** clarification — a `REVIEW` result with an `ACCEPTED` or `REJECTED` review no longer blocks `CLEAR` | `CLEAR_POLICY` | `background-check.md` §14.1 |
| **D5** amendment — risk is refused on every move except `CLEAR` | service and `ck_background_check_decision_risk_only_on_clear` | `contracts/background-check.md` §14 |
| **D4, Developer 4B's side** — which documents may be evidence for a verification (the company's own; for a buyer, its deal's or its company's), and only `AVAILABLE` ones | `verification_service._check_evidence_documents` | `contracts/verification-and-screening.md` §3, §11 |
| **IQ-2 edge cases** (Developer 1, 1 Oct 2026) — a `REVIEW` sanctions/AML result with a `REJECTED` review reads as `FAILED`; a `PASSED` or `FAILED` result reads as its status whatever its review says (IQ-2's wording) | `domain/compliance_facts.check_state` (feeds the handover guard, P3-4/P4-7) | `background-check.md` §12.4 |
| **No new cycle while the current one is empty** (Developer 1, P2-3c) — refused 409 `CHECK_CYCLE_EMPTY`; it is what makes two simultaneous starts produce one cycle, and it also means a wrongly chosen kind cannot be replaced until something is recorded | `BackgroundCheckService.start_cycle` | `background-check.md` §12.3 |
| **Maker-checker details** (Developer 1, P3-1b, 1 Oct 2026) — (a) the proposer may not reject their own proposal, only withdraw it (enforced by the database too); (b) while a proposal is open nothing else moves the check — no `MORE_INFO`, no second proposal, no new cycle (409 `BACKGROUND_CHECK_PROPOSAL_OPEN`); the checker rejects first; (c) **any** change to what the decision would rest on makes the proposal stale and unapprovable — a new or reviewed result, a screening answer, a new cycle, and also a company document passing its scan; (d) the switch may be off only where `ENVIRONMENT` is `local` or `test` — IQ-17 literally; `development` is refused because it is the default `ENVIRONMENT` and what `.env.example` and so the docker-compose stack set, which would leave the start-up guard inert on a UAT server (changed at the PR audit, 1 Oct 2026; a developer sets `ENVIRONMENT=local` to turn it off); (e) the approval queue is COMPLIANCE/ADMIN only, a company's proposals are readable by all staff; (f) the approved decision's `decided_by` — and so the journey row and `company.became_customer` — names the proposer, with the approver in `approved_by` | `BackgroundCheckService.propose/approve/reject/withdraw`, `compliance_settings` | `background-check.md` §12.5 |
| **Clear expiry backfill keyed on the last `CLEAR` decision** (Developer 1, P3-3a) — BQ-5's "1 year from the last Clear" taken literally, so a company whose gauge reads `CLEAR` while its chain head does not (only a raw-SQL write can do that; four such test rows existed on the shared test database) still gets an expiry; a new `CLEAR`'s `decided_at` and `expires_at` now come from one server timestamp read after the row lock, so `expires_at − decided_at` is exactly the validity | migration 0027, `_apply_move` | `background-check.md` §12.7, `migration-register.md` |
| **`BuyerChecks.tsx` kept for legacy deal buyers** (Developer 1, P4-5 / task 1.20) — `CompanyComplianceSummary` is the one compliance summary, and a buyer company's checks are recorded on its own panel. `BuyerChecks` stays (marked legacy) because it is the only place a `deal_buyer`'s sanctions and AML can be recorded on a deal that has no buyer company yet — which BQ-4's handover rule needs — and Developer 2's deal page mounts it. It goes when the deal-buyer migration (P4-6) and the retirement of `deal_buyer` writes (P4-10) have run; swapping the deal page's mount to `CompanyComplianceSummary` is Developer 2's task 2.4 | `components/BuyerChecks.tsx`, `pages/DealDetailPage.tsx` (Dev 2) | `background-check.md` §12.2, §16 |
| **P4-11 rests on Developer 3's `NOT_IN_PIPELINE ⇒ LEAD` rule** (P4-1, not yet merged) — a buyer-only company is never promoted because promotion needs a `PROSPECT` and such a company cannot be qualified. Dev 1 added no promotion rule of its own; the P4-11 tests run on a `LEAD` company today and set `pipeline_status = NOT_IN_PIPELINE` automatically once the column exists | `test_dev1_company_keyed.py` | allocation §3, task 1.19 |
| **The expiry condition in the handover guard is not built here** — "the background check expired on <date>" is Developer 2's task 2.5 (P3-3b's guard part), reading `ComplianceFactsReader.is_clear_current`. Until it lands, an expired Clear refuses promotion (IQ-18) but **does not yet block a handover** | Developer 2's `_handover_blocked_reason` | allocation §4, task 2.5 |

### 1.2 Undecided

| Item | Why it matters | Detail |
|---|---|---|
| **Placeholder results never stop blocking `CLEAR` within their cycle.** D2 counts a placeholder as pending, and a `PENDING` result cannot be reviewed, so a cycle holding one can never be cleared | Production should hold none (the generator was dev-only). Since check cycles (Developer 1, P2-3b) a company holding one is no longer stuck: the seam reads only the current cycle, so a COMPLIANCE/ADMIN user starts a Re-KYC/Re-KYB cycle and the placeholder stays behind in the old one. Still open: whether D2 should be amended so this needs no new cycle | `verification-and-screening.md` §8, `background-check.md` §12.3 |
| **The `CLEAR` evidence rule** (D4) is satisfied by the screening answers alone (seven since 1 October 2026), so a company can be cleared with **no document**. It can no longer be cleared with no verification result: rule B (P3-2) needs KYB, AML and sanctions each passed in the current cycle | Whether a Clear without any document is enough for a financier | architecture §12, `background-check.md` §14, §12.6 |
| **D12 — RXIL's package and results contract** | Blocks RXIL results intake (4B-8) and the automatic start of a check when RXIL results arrive. `StubRxilAdapter` stays a labelled stub until then | `contracts/verification-and-screening.md` §11 |
| **RXIL's service identity** | RXIL company intake is ADMIN-only because a person pastes the package. A direct integration needs a machine identity — never `API_USER`, which public sign-up grants | — |
| **O2 — `CUSTOMER` replaces `ONBOARDED`** for the ANER-4.2-S1T2 consumer, which watched journey rows marked `terminal` | That consumer sees completions only if `CUSTOMER` is confirmed as the replacement | `company-record.md` §10 |
| **Identifier disclosure to masked roles.** OPERATIONS cannot search by PAN, but learns which company holds one from the duplicate refusal (`existing_customer_id`), GSTIN warnings and import candidates | Keep (decision 4's data-entry benefit) or omit the ids for roles that may not reveal identifiers. The screens now show the holder as a link ("another company — open it") rather than printing its id, and reveal nothing the response does not | architecture §12 |
| **Should a failed buyer check block the handover?** A `FAILED` sanctions or AML result on a deal's buyer is recorded against the buyer and never touches the company (decision 9); the handover guard (A5) looks only at the company, so the deal can still be handed over | **Decided 1 October (BQ-4): yes** — the buyer's sanctions and AML must both be `PASSED`. **Built** (task 2.5): guard condition 5 reads Developer 1's `ComplianceFactsReader`, and both parties are share-locked. Nothing left to decide; the row stays until `remaining-work.md` §9's clean-up of this page | `deal-and-buyer.md` §3.1, §6.1; `demo.md` §4 step 8 |
| **A refresh whose answer never arrives.** The browser now shares one token refresh per tab and takes turns across tabs (Web Locks), treats only a 401 as the end of a session, and the server serialises two exchanges of one token (`SELECT … FOR UPDATE`) and rolls back a rotation whose caller has already gone. Measured in headless Chrome on 29 September: three company pages opened at once, 30 of 30 signed in; 72 of 72 reloads after the page settled, signed in; bursts of four reloads 250 ms apart, 30 of 30 signed in on the dev server but 21 of 30 on the production build. The remainder is a reload landing after the server committed the rotation, while its answer is in flight: the next load holds a revoked token and must sign in again | Closing it needs either a short server-side grace window for the just-replaced token (which weakens rotation, so it is a security decision) or keeping the access token across reloads (which changes where it may be read by script) | architecture §9 |
| **Re-dating a `NOT_NOW` check-back** takes two moves, because a move to the value already held is refused | One step would need `NOT_NOW → NOT_NOW` with a new date in the contract | `engagement.md` §1.1 |
| **Retire `GET /exporters/activities/pending`** | Superseded by `GET /follow-ups`, and it still lists completed follow-ups. The screens no longer call it | `engagement.md` §5.6 |
| **Cross-company Deals and Documents lists** | Deals and paperwork are reached from a company. Sidebar rows would need two new paged routes first | architecture §12 |
| **Gate §7.6 — a real scanner, and S3 with Object Lock, KMS and retention** | Until both exist, no real exporter document may be uploaded. Each is one new implementation of an existing port (`ScannerPort`, `StoragePort`) | architecture §7, §12; `storage-and-documents.md` |
| **`app/integrations/object_storage`** | Recommended: keep it as the home of the future S3 vendor implementation (the port lives in `onboarding/domain/storage.py`) | — |
| **CI (U6)** | There is none, so every gate is run by hand (`development.md` §7) | — |

## 2. Engineering items (no decision needed)

| Item | Detail |
|---|---|
| ~~IEC has no `CHECK` constraint~~ — **done** | Migration **0040** (`ck_exporter_profile_iec_format`): `iec IS NULL OR iec ~ '^[A-Z0-9]{10}$'`, the rule the service has always applied, now also in the database for writers that skip it. No backfill — no row violated it. Direct-SQL violation test, which asserts the pattern **equals** `IEC_RE.pattern` so the two cannot drift |
| A **past** invoice can be recorded only through the API | `POST /trade-relationships/{id}/invoices` and `POST /trade-invoices/{id}/outcomes` are live and tested, and claimed past trade (P5-8) is what they are for — an invoice with `deal_id` null and `proof_status = CLAIMED`. The deal page's form records the *deal's* invoice only, so adding history a company tells us about has no screen yet. One form on the company page's trade panel |
| `POST /exporters` without `name` or `country` still creates a company | Remove the unnamed create path once nothing calls it, then make both columns `NOT NULL` |
| CSV imports stop at 1,000 rows | Only if the business needs more: a background job with a pollable report, not a longer request |
| `bank_activity_finding` has no foreign key to the company | Decide whether it should when a bank feed is connected |
| The OpenAPI comparison includes `info.title`, which comes from `APP_NAME` | Regenerating with another app name fails the test for everyone. Pin the title in code or leave it out of the comparison |
| The suite inside the `aner-app` container | `test_openapi_artifact_is_current.py` needs `./frontend` mounted, which compose does not do |
| `test_dev1_decision_evidence.py::test_new_decisions_record_the_current_rules_and_cycle` sometimes fails | It asserts the decision list reads newest-first, and the two decisions it creates can share a `decided_at`, so the tie is broken arbitrarily (seen 3 October 2026 in a full-suite run; passes alone). Order by `decided_at DESC, id DESC`, or assert the set |
| `test_expiry_sweep.py::test_sweep_can_use_the_partial_ck_index` sometimes fails | It asserts a query plan, which depends on the size of the database |
| Accounts created before 29 September with a special-use address (`admin@demo.local`) cannot sign in | `bootstrap` and `promote` now refuse such an address, but an account already made with one stays unusable (Settings cannot change an email): make a new one with a real-looking address and deactivate the old |
| The shared test database accumulates thousands of test rows | Harmless to correctness; demo on a separate database (`demo.md` §1) |
| No documents in the sample data | Worth adding once there is a scanner worth running |
| The company search returns no `total` | Home and the Companies list cannot show exact counts |
| Two places still show a user id rather than a name | The Qualification criteria settings screen (a version's `created_by`, ADMIN only) and the retired `GET /exporters/activities/pending`. Everything else a person reads — history, background-check decisions, activities, follow-ups, screening decisions and verification reviews — carries the name (`actor_name`, `decided_by_name`, `reviewed_by_name`; architecture §8) |
| No screen or route for managing reason codes | `criterion-result.md`, open item Q5 |
| Routes outside the CRM still commit only in `get_db`'s teardown, which FastAPI runs after the response is sent | Fixed for the auth and role routes (they commit before returning, `app/api/rest/auth/tests/test_commit_before_response.py`); the CRM's services always did. Still open: the legacy onboarding routes (`/cases`, `/register`, the Sumsub webhook) and the `compliance` routes, which the module rule keeps closed. A client acting on their response at once can miss the write |
| Legacy case path: `CaseService._actor_type_for` records a user's transition as `API_CLIENT` | Out of scope (the legacy onboarding path); the actor id itself is recorded correctly |
| Contract acknowledgement tables still read "pending" (for example `engagement.md` §10) | A step from the multi-developer plan; nothing to do unless more developers join |

## 3. Decision records

Decisions are recorded where their rule lives, not here:

- The twelve prototype decisions and planning assumptions: the design PDF §6 (retired on 4 October 2026 as outdated; recover it with `git show 451ef97:docs/Exporter-CRM-Architecture-and-Plan.pdf`), summarised
  in architecture §11.
- Developer 4's D1–D17: `contracts/background-check.md` §14 and `contracts/verification-and-screening.md` §11.
- Each contract's own decisions, for example: follow-up completions write no history row
  (`engagement.md` §5.7); the reschedule path has its own error codes rather than reusing
  the conversation's (`engagement.md` §7.1); downloads fetch the bytes with the caller's
  token rather than trusting a signed URL alone (`storage-and-documents.md` §6.1).
- The one module-rule exception: [`module-rule-exceptions.md`](module-rule-exceptions.md).

## 4. Where the retired notes went

Removed on 29 September 2026, after the final release audit. Git history keeps them.

| Removed | Its still-open content is now |
|---|---|
| `dev1-remaining-work.md`, `dev1-pr1-readiness.md` | U4 and U6 above; the allowed-moves question (U1) was settled in practice (`company-record.md` §10, O6) |
| `dev2-remaining-work.md` | §1.2 and §2 above |
| `dev3a-remaining-work.md`, `dev3a-phase1-progress.md`, `dev3a-phase2-progress.md` | §1.2 above; the decisions are in `engagement.md` |
| `dev3b-remaining-work.md`, `dev3b-progress.md` | §1.2 and §2 above; the decisions are in `deal-and-buyer.md` and `storage-and-documents.md` |
| `dev4/4b-remaining-work.md` | §1 above |
| *Removed 2 October 2026:* `dev1-handover.md`, `dev2-handover.md` | The post-demo lanes' files above — `dev1-remaining-work.md`, `dev2-remaining-work.md` (new files under the pre-demo names), `dev3-remaining-work.md`; the facts contract and its test fake in `contracts/background-check.md` §12.4 |
| *Removed 2 October 2026:* `dev4/4a-task.md`, `dev4/4b-task.md` | Developer 4A's rules and D1–D14: `contracts/background-check.md` (the seam's full shape, invariants and errors in §12.1). Developer 4B's rules and D4, D7, D9, D15–D17: `contracts/verification-and-screening.md`. Their one open item, RXIL results intake (D12), is in §1.2 above |
| `exporter-crm-tickets.md`, `exporter-crm-frontend-tickets.md` | The original EXP-* build tickets, superseded by the design PDF |
| *Removed 4 October 2026:* `dev1-remaining-work.md`, `dev2-remaining-work.md`, `dev3-remaining-work.md` | [`remaining-work.md`](remaining-work.md) — one list now that one developer completes the project |
| *Removed 4 October 2026:* `Exporter-CRM-Architecture-and-Plan.pdf` (outdated) | [`architecture.md`](architecture.md) and [`plan.md`](plan.md); the PDF itself via `git show 451ef97:docs/Exporter-CRM-Architecture-and-Plan.pdf` |
| `frontend-refresh.md` | The 28 September frontend refresh; its remaining items are in §1.2 and §2 above |
| `../E9-NOTES.md`, `../TEST-BASELINE.md` | Superseded by the contracts and by `development.md` §9 |
