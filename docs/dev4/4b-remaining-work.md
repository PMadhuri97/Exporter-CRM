# Dev4B — Remaining Work (`feature/4b-verification-screening-integrity`)

> **Audit:** 28 Sep 2026, against `docs/dev4/4b-task.md`, on branch
> `feature/4b-verification-screening-integrity` @ `38ab720` (commits `dabe28d` feat + `38ab720`
> merge of `main` @ `12d255c`). The local dev database was upgraded to this branch's head to run
> the tests.
>
> **Update, same day — Prompt 1 done:** B1, B3, B4, the `4b-task.md` updates and the
> `BuyerChecks` component are complete, and one extra fix (§3.5) was found and made on the way.
>
> **Update, same day — Prompt 2 done:** the 4B-7 frontend (F1–F11, §3.3) is complete. Prompts 1
> and 2 were committed as `206b817`.
>
> **Update, same day — PR audit of `206b817`:** one blocker (a stored `javascript:` evidence link)
> and four smaller findings, all fixed (§3.6). **No Dev4B code work remains.** What is left is
> coordination (§4) — the lead's D4 confirmation, Dev1's contract rows and review, Dev4A's two
> red tests — and the merge.
>
> Section 3 is the work; section 6 is the prompt scaffolding that produced it.

---

## 1. Verdict

**Backend 4B-1 … 4B-6: done. `BuyerChecks`: done. Frontend 4B-7: done. 4B-8: still blocked.**

Dev4B's own §19 items are met. The PR still waits on:

1. **Coordination items** that other owners need to handle (§4). This includes the lead confirming
   4B's side of D4.
2. **The suite is red on three tests that are already red on `main`** (§2). They are not caused
   by 4B, but they block a green PR.

---

## 2. Gates measured on this branch (after Prompt 1)

| Gate | Result |
|---|---|
| `alembic heads` | one: `onboarding_0021_verif_review` (parent `auth_0004_rbac`, re-parented correctly after the `main` merge) |
| Round trip `upgrade head → downgrade -1 → upgrade head` | clean (no migration changed in Prompt 1) |
| ruff | 16 (baseline; every file changed in Prompt 1 is clean) |
| import-linter | 19 kept / 0 broken |
| `test_openapi_artifact_is_current` (3 tests) | pass, after regeneration |
| 4B + Dev4 + route-auth + OpenAPI + l3b + qualification regression set, on the Prompt 1 code | **1118 passed / 3 failed** — the 3 below, nothing else |
| Full backend suite (run on the audit-state code, **before** Prompt 1; not re-run after) | 34 failed / 4367 passed / 7 skipped / 22 errors = the environment baseline 29 F + 22 E (compliance / audit / idempotency routes and read-only roles) + the 3 below + `test_expiry_sweep::test_sweep_can_use_the_partial_ck_index` (environment; fails on `main` too) + `app/platform/authorization/tests/test_role_management.py::test_last_role_manager_cannot_be_demoted_by_a_non_admin_user_editor` (PR #12's test, also fails alone; 4B touches nothing in `app/platform/authorization`; probably other role managers in the shared dev DB, **not verified on `main`**). No onboarding failure other than the two Dev4A tests below. |
| Frontend, after Prompt 1 | tsc clean · eslint 0 errors / 2 warnings (baseline) · vitest 20 files / 198 (was 19 / 178; +20 `BuyerChecks` tests) · build ok |
| Frontend, after Prompt 2 | tsc clean · eslint 0 errors / 2 warnings (baseline, `AuthContext.tsx`) · vitest **27 files / 258** · build ok (the >500 kB chunk warning is the existing one) |
| Backend after Prompt 2 (no backend change in Prompt 2) | OpenAPI artifact tests + every `test_l4b_*`: 199 passed |
| **PR audit, on `206b817` before the §3.6 fixes** | Full suite 34 failed / 4401 passed / 7 skipped / 5 errors — the known set only. Round trip, and the lossy downgrade keeping the chain head in the legacy columns, verified on a throwaway database. `schema.ts` identical to a fresh regeneration |
| **Final, after the §3.6 fixes** | `alembic heads` one (0021) · ruff 16 (changed files clean) · import-linter 19/0 · OpenAPI artifact + route-auth 155 passed · full suite **27 failed / 4426 passed / 7 skipped / 5 errors** — every failure also failed in the audit run: 22 environment (compliance, audit, screening-rule-registry) + the 3 below + `test_expiry_sweep` + `test_role_management` (above); +18 new tests · frontend tsc clean · eslint 0 errors / 2 warnings · vitest **27 files / 268** · build ok |

**The 3 failures in the targeted set are already failing on `main`. None is caused by 4B.**

| Test | Cause | Owner |
|---|---|---|
| `tests/contract/test_route_authorization_coverage.py::test_every_mounted_route_is_classified` | 16 `/api/v1/auth/*` routes from PR #12 (user management / RBAC) are mounted but not classified | PR #12 author / Dev1 |
| `test_l4a_background_check_schema.py::test_0015_parents_onto_0019_and_the_chain_has_one_head` | asserts `heads == ['onboarding_0015_bg_check']`; since PR #12, 0015 is no longer the head | Dev4A (make the test assert "one head, and 0015 is in the chain") |
| `test_l4a_background_check_schema.py::test_the_database_is_at_0015` | same: pins `alembic_version` to 0015 | Dev4A |

4B must **not** edit the two Dev4A tests (§8). Ask Dev4A to fix them, or get their written OK in
the PR.

---

## 3. Dev4B work

### 3.1 Backend fixes — **DONE (Prompt 1)**

| # | Item | Status |
|---|---|---|
| B1 | Document evidence ignored `scan_status` | **Done.** `verification_service._check_evidence_documents` now refuses (422) any `document` reference that is not `AVAILABLE`, after the existence and ownership checks, so a foreign document's scan state is never disclosed. `PENDING_SCAN` is refused as well, because the evidence is frozen once written. Tests cover service + API, `AVAILABLE` accepted, each of the other three refused, a mixed set refused, a foreign document refused as foreign, and a buyer's deal document still gated. The route and schema descriptions say so. |
| B2 | 4B's D4 (which documents may be evidence) is implemented but not confirmed | **Still open — lead.** It is recorded in `4b-task.md` §13 as "implemented, awaiting confirmation", with the rule and the scan gate. It is not presented as decided. |
| B3 | Stale "until_d16" / "pending_d15" test names | **Done** in `test_l4b_evidence_and_subjects.py`, `test_l4b_verification_integrity_rules.py` and `test_manual_entry_adapter.py`. Only the names and docstrings changed. Dev4A's `test_l4a_background_check_api.py::…test_developer_is_refused_pending_d8` has the same staleness and is Dev4A's (§4). |
| B4 | Legacy-column edge case | **Done: refused.** If a result has a legacy `review_status` but no `verification_review` row, `record_review` raises the new `VerificationLegacyReviewUnchainedError`, 409 `VERIFICATION_LEGACY_REVIEW_UNCHAINED`. It never records a "first" review that would overrule the legacy verdict with no link and no reason (§5.1). The remedy (copy the verdict into `verification_review`, as 0021 did) is in the message and is tested. |

### 3.2 `BuyerChecks` component — **DONE (Prompt 1)**

- `components/BuyerChecks.tsx` + `BuyerChecks.test.tsx` (20 tests). Signature:
  `BuyerChecks({ dealId, dealBuyerId })`. `dealId` is used only to offer the deal's `AVAILABLE`
  documents as evidence.
- Lists `GET /verifications?entity_type=BUYER&entity_reference=<deal_buyer.id>`, using the
  existing hooks (`useVerificationResults`, `useTriggerVerification`, `useReviewVerification`,
  `useDealDocuments`).
- Shows status, risk, current verdict, provenance (`MANUAL` / `STUB` / provider), the placeholder
  label, the subject snapshot exactly as the server masked it, evidence, and the review chain
  (Current / Superseded).
- Record and review actions depend only on `capabilities.can_record_result` / `can_review`; there
  is no role check. Recording refuses a `PASSED` with no evidence on the client (D16), and the
  server's refusal (e.g. 409 `DEAL_CLOSED`) is shown as worded. Reviewing sends
  `supersedes_review_id = latest_review_id` with a required reason. On 409
  `VERIFICATION_REVIEW_STALE` it refetches and explains. `PENDING` checks are not reviewable.
- **Not mounted, not in `components/index.ts`.** Dev3 mounts it after the merge.
- The tests were mutation-checked: never superseding, ignoring the record capability, and offering
  non-`AVAILABLE` documents each fail at least one test.

### 3.3 4B-7 — Verification frontend — **DONE (Prompt 2)**

**Result.** `VerificationSection({ customerId })` is unchanged in export and props and is now a
shell over new Dev4B components beside it. None of them is in `components/index.ts`:

| # | Done as |
|---|---|
| F1 | `ManualResultForm.tsx` — manual only, no provider choice, no `PENDING`, D16 checked client-side, `AVAILABLE` documents only (company's here, deal's in `BuyerChecks`), server 422/409 shown as worded. Opened by "Record a result" only when `capabilities.can_record_result`. |
| F2 | `ReviewDialog.tsx` — `ReviewChain` (every review: verdict, reviewer, time, note, Current/Superseded) and `ReviewDialog` (first review names nothing; later one sends `latest_review_id` + required note; 409 `VERIFICATION_REVIEW_STALE` → refetch + explanation; `PENDING`/placeholder not reviewable; gated by `can_review`). |
| F3 | `ScreeningChecklist.tsx` — items, labels, sections and order from `catalogue`; `CHECKLIST_ITEMS` / `ChecklistItem` deleted; unknown keys still listed read-only; progress counts against the catalogue. |
| F4 | `getScreeningItemHistory` (api), `useScreeningItemHistory` (hook; saving a decision invalidates it), `ScreeningItemHistory.tsx` (collapsed until opened; 5 per page, Newer/Older; loading, empty, error + retry). |
| F5 | Every action is gated by `VerificationResultList.capabilities` or `ScreeningReviewList.capabilities.can_record_decision`. There are no `user.role` or `useCurrentUser` calls in Dev4B frontend files, and the section renders with no auth context at all (tested). |
| F6 | `BankActivityPanel.tsx` — "Not connected" + `provider_feed_message`; the count tiles appear only if a feed is connected; "not a clean result" wording; stored findings listed as stored. |
| F7 | `VerificationResultRow.tsx` + `provenanceLabel`: `MANUAL` → "Manual (person)", `STUB` → "RXIL stub, not RXIL", `PROVIDER` → stored name; placeholder from `is_placeholder`; the client-side `normalized_result.stub` rule is deleted. |
| F8 | `EvidenceList.tsx` — `evidence_note` + `evidence_refs`; documents via `getDocument` → `createDownloadLink` (`useDownloadDocument`) → `fetchDocumentBlob` → save, as `DocumentList` does; `evidence_reference` no longer shown. |
| F9 | `useTriggerVerification` is used again (by `ManualResultForm`), and it is the only manual submission path — `BuyerChecks` uses the same form and `ReviewDialog`. |
| F10 | 4B block of `types.ts`: `VerificationReview`, `VerificationCapabilities`, `BuyerSnapshot`, `VerificationEvidenceRef` / `VerificationEvidenceRefStored` (schemas `VerificationEvidenceRefModel` / `…Out` — renamed from `EvidenceRef*` in §3.5), `ScreeningCatalogueItem`, `ScreeningCapabilities`, `ScreeningItemHistory`, plus the status/risk aliases. No generated artifact changed in Prompt 2. |
| F11 | vitest: `ManualResultForm`, `ReviewDialog`, `ScreeningChecklist`, `ScreeningItemHistory`, `BankActivityPanel`, `VerificationResultRow` (provenance, placeholder, evidence, download), `VerificationSection` (states, capabilities, bank tab) — 60 new tests. The seven key behaviours were mutation-checked, and each mutation fails at least one test. |

Shared helpers: `verification-labels.ts` (option lists, colours, provenance, reviewer),
`VerificationStatusChip.tsx`, and `verification-test-fixtures.ts` (test builders). `humanize` /
`formatDateTime` now come from `@/lib/format`.

The original work list is kept below for reference.

Files: `components/VerificationSection.tsx` (split into sub-components beside it),
`api/verification.ts`, `hooks/verification.ts`, the **4B block** of `types.ts`, and `schema.ts`
regenerated if anything changes. `VerificationSection({ customerId })` must keep its signature,
because Dev4A's `BackgroundCheckPanel` renders it.

**Already available from Prompt 1. Reuse these, don't duplicate them:**

- `components/verification-labels.ts`: `humanize`, `formatDateTime`, `chipClasses`,
  `provenanceLabel`, `formatReviewer`. `VerificationSection.tsx` still has its own copies of
  `humanize` / `formatDateTime` / `chipClasses`; switch it to this module and delete the copies.
- `types.ts` 4B block: `VerificationResultStatus`, `VerificationRiskLevel`, `VerificationReview`,
  `VerificationCapabilities`, `VerificationEvidenceRef`, `BuyerSnapshot`.
- `BuyerChecks.tsx`: working patterns for the review form (supersede, required reason, stale 409)
  and the manual record form (D16 check, `AVAILABLE`-only document picker). F1/F2 are the same
  flows for an `EXPORTER` subject with `useCompanyDocuments`. Extracting a shared `ReviewDialog`
  / `ManualResultForm` from it is fine, as long as `BuyerChecks` keeps its tests green.

The backend already serves everything below. What the UI still does today:

| # | Item | Today on this branch | Needed |
|---|---|---|---|
| F1 | **Manual result form** (`ManualResultForm.tsx`) | none; there is no way to record a real company result from the UI | Fields: type (company check types valid for EXPORTER), outcome `PASSED`/`FAILED`/`REVIEW` (no `PENDING`), optional risk, `evidence_note`, and `evidence_refs` picked from the company's documents (`useCompanyDocuments`; offer only `AVAILABLE` ones) plus URL refs. Refuse `PASSED` with no evidence on the client, and show the server's 422 message. `provider` is always `manual`. Show the form only when `capabilities.can_record_result`. |
| F2 | **Review chain + supersede dialog** (`ReviewDialog.tsx`) | `ReviewActions` sends only `{review_status}` and hides itself once any review exists, so a verdict cannot be changed from the UI | Show every review in `result.reviews`. The first review sends no `supersedes_review_id`. A later one sends `latest_review_id` plus a required note. On 409 `VERIFICATION_REVIEW_STALE`, refetch and explain. Show any other 409 (e.g. `VERIFICATION_LEGACY_REVIEW_UNCHAINED`) as worded. `PENDING` is not reviewable. Gate on `capabilities.can_review`. |
| F3 | **Checklist from the server catalogue** (`ScreeningChecklist.tsx`) | still uses the hand-copied `CHECKLIST_ITEMS` (line ~54) | Render `screeningReview.catalogue` (key, label, section, in order). Delete `CHECKLIST_ITEMS` and `ChecklistItem`. Keep the "unknown keys are not silently dropped" behaviour (line ~170) if it still applies. |
| F4 | **Per-item screening history** | no API function, hook or UI | Add `getScreeningItemHistory(customerId, itemKey, {limit, offset})` → `GET /onboarding/exporters/{id}/screening-review/{key}/history`, a hook, and an expandable history (newest first, paged) per item. |
| F5 | **Capabilities, not roles** | `user.role === 'COMPLIANCE' \|\| … 'ADMIN'` at lines ~162 and ~341, plus `useCurrentUser` at ~159, ~339 and ~390 | Use `VerificationResultList.capabilities` and `ScreeningReviewList.capabilities.can_record_decision`. **No `user.role` comparison may remain in Dev4B files** (§14 4B-7 stop condition). |
| F6 | **Honest bank panel** | still shows "Connected accounts 0" | Show `provider_feed_message` / `provider_feed_status = NOT_CONNECTED` prominently. Do not present `0` as a checked result. No fake findings. |
| F7 | **Provenance and placeholder labels** | `provider` shown raw (`rxil_stub`); the placeholder is detected client-side from `normalized_result.stub` | Use `provenanceLabel` and the served `is_placeholder`. Drop the client-side `isStubResult` rule. |
| F8 | **Evidence display** | shows the retired `evidence_reference` (always `—`) | Show `evidence_note` and `evidence_refs`. Document refs link through the existing download flow (`createDownloadLink`). |
| F9 | **Dead code** | `useTriggerVerification` has no caller in `VerificationSection` (it is used by `BuyerChecks`) | F1 uses it. |
| F10 | **types.ts 4B block** | 6 aliases added in Prompt 1 (above) | Add the rest as needed: `ScreeningCatalogueItemResponse`, `ScreeningCapabilities`, `ScreeningItemHistoryResponse`, `VerificationEvidenceRefOut`. Aliases only. |
| F11 | **vitest** | `VerificationSection` has **no** tests (only the `ExporterDetailPage` mocks were updated) | One test file per sub-component, covering: evidence required for PASSED, review chain + supersede + 409, checklist rendered from the catalogue, item history, placeholder/stub labels, bank "not connected", capabilities true/false, and loading, empty and error states. |

Stop condition (§14 4B-7): tsc, eslint, vitest and build pass, and `grep -n "user.role"` over
Dev4B's frontend files returns nothing.

### 3.4 Docs — **DONE (Prompt 1)**

`4b-task.md`:

- §3 now leads with the current state: `main` `12d255c`, Alembic head `auth_0004_rbac` on `main`
  and `onboarding_0021_verif_review` here, and the known red tests on `main`.
- The §12 dependency table now shows the status of each row.
- The §13 table points D7, D8, D9, D15, D16 and D17 to the recorded decisions. D4's 4B side is
  marked "implemented, awaiting confirmation". The B1 scan gate and the B4 refusal are recorded
  under the decisions table as follow-ups, not new decisions.
- §14 has a status note per phase: 4B-1…4B-6 COMPLETE, 4B-5 including `BuyerChecks`, 4B-7
  PENDING, 4B-8 BLOCKED.

### 3.5 Extra fix found during Prompt 1 — OpenAPI schema-name collision

- The branch's `api/schemas/verification.py` declared `EvidenceRefModel` / `EvidenceRefOut`, the
  same names as qualification's (`schemas/qualification.py`). OpenAPI schema names are global, so
  FastAPI renamed **both** pairs to
  `app__modules__onboarding__api__schemas__{qualification,verification}__EvidenceRef*`. That
  silently changed Dev2's generated schema names from `main` (§11: schema changes must be
  additive).
- Fixed by renaming 4B's classes to `VerificationEvidenceRefModel` / `VerificationEvidenceRefOut`
  (with a comment saying why). Qualification's names are back to exactly what `main` has.
  `openapi.json` and `schema.ts` were regenerated with the `pnpm generate:api` commands and
  `APP_NAME` pinned. The diff contains only these renames and the B1/B4 description text.

### 3.6 PR audit of `206b817` (28 Sep 2026) — **DONE**

Each finding was probed before the fix, and each new test was mutation-checked (it fails with
the fix reverted). Recorded in `4b-task.md` §13, *PR audit follow-ups*.

| # | Finding | Fix |
|---|---|---|
| A1 | **Blocker — stored XSS.** A `url` evidence reference accepted any non-blank text and `EvidenceList` rendered it as `<a href>`; React 18 does not block `javascript:`, and the refresh token is in `localStorage`. Probed: the API stored a `javascript:` link (201) and it rendered as a live `href`. | Server: `check_evidence_shape` refuses a `url` that is not an `http(s)://` link with a host (422). UI: `isWebLink` (`verification-labels.ts`); `ManualResultForm` refuses such a link; `EvidenceList` shows any non-web `url` as text. API descriptions say so; `openapi.json` / `schema.ts` regenerated (description text only). |
| A2 | 4B writes never refreshed Dev4A's `['backgroundCheck', id]` query (`staleTime` 30 s), so `CLEAR` stayed disabled after the checklist or a review was finished. | `invalidateWhatAWriteFeeds` in `hooks/verification.ts`: the background check and company history for an `EXPORTER`, the history lists for a `BUYER`. |
| A3 | `VerificationSection` dropped `EXPORTER` results outside the screening set, yet Dev4A's `CLEAR` counts them. Probed: a `BANK_ACCOUNT` result in `REVIEW` blocks `CLEAR` and was invisible. | Listed under "Other checks on this company", reviewable; the tab count covers every result. |
| A4 | `router.py` said `_VERIFICATION_DECISION_ROLES` gates the routes; the routes used a separate `_COMPLIANCE_OR_ADMIN`. | `_VERIFICATION_DECIDER = require_role(*_VERIFICATION_DECISION_ROLES)` on the two write routes (roles unchanged). |
| A5 | `get_verification_status` held the result row lock while the provider worked. | Provider first, then the row re-read `FOR UPDATE`; a test proves no lock is held and that a review landing meanwhile is honoured. |
| A6 | Docs: stale branch state; the D8 / history-route gap and the placeholder dead end were unrecorded. | `4b-task.md` §3, §13 and the 4B-3/4B-7 notes; §4 below. |

---

## 4. Items for other owners (not Dev4B code; raise them in the PR)

| Owner | Item |
|---|---|
| **Dev1** | Add the `screening` dimension row (`screening_initial` / `screening_transition`) to `docs/contracts/history-row.md` §2 (D9). The code already writes these rows. |
| **Dev1** | Add the `onboarding_0021_verif_review` row to `migration-register.md` (parent `auth_0004_rbac`). Dev4B must not edit the register. |
| **Dev1** | Review the controlled-region edits: `_trigger_body()` now takes a real company and an `evidence_note`, `_trigger()` creates an exporter, the provider test reflects D7, and one new `GATED_ROUTES` row (the history route) is in both route-auth tables. |
| **Dev1 / PR #12 author** | Classify the 16 `/api/v1/auth/*` routes in `test_route_authorization_coverage.py` (red on `main`). Also look at `test_role_management.py::test_last_role_manager_cannot_be_demoted_by_a_non_admin_user_editor`, which is red here in isolation (§2). |
| **Dev4A** | Fix the two `test_l4a_background_check_schema` tests that pin 0015 as head / DB version (red on `main`). Optionally rename `test_developer_is_refused_pending_d8`, since D8 is decided. |
| **Lead** | Confirm 4B's side of D4 (document scope + the `AVAILABLE` scan gate, B1/B2). |
| **Dev1 / lead** | D8 gap on the history route: `/history` admits DEVELOPER and now carries screening comments (D9) and review notes (§5.1) as `reason` — text D8 keeps from DEVELOPER on the verification and screening routes. Same gap Dev4A recorded for background-check reasons. The route's `reason` policy is Dev1's (`4b-task.md` §13, *Open*). |
| **Lead / Dev4A** | Placeholder rows can never stop blocking `CLEAR`: `PENDING` is unreviewable and D2 counts placeholders as pending. The generator was dev-only; the shared dev DB held 20 on 16 companies. A D2 amendment or a recorded data step is needed if any environment has them (`4b-task.md` §13, *Open*). |
| **Dev2** | `pages/panels/CompanyPanel.tsx` renders `profile.website` as `<a href>` with no scheme check — the same `javascript:` risk fixed in 4B's evidence (§3.6 A1), in Dev2's page and schema (`website` is any string ≤ 2048). Pre-existing on `main`; not touched here. |
| **Dev3 (post-merge)** | Mount `BuyerChecks` on the deal page: `<BuyerChecks dealId={deal.id} dealBuyerId={buyer.id} />` (one import, one element). |
| **Dev2 (post-merge)** | Sample-data hook for the §3.9 companies (B reaches CLEAR, C is FLAGGED) through a Dev4 hook. |
| **Dev4A (post-merge, §17)** | Integration tests: CLEAR end to end with real review chains and evidence ids, and a buyer check never moving the gauge. |

---

## 5. What is already done (for reference; do not redo)

| Phase | Status | Evidence |
|---|---|---|
| 4B-0 seam | Merged (PR #11) | `compliance_inputs.py` ×2, `company_input_lock.py`, anchors |
| 4B-1 screening integrity | **Done (backend)** | `SCREENING_CATALOGUE_ITEMS` served in the list response. `ck_screening_review_item_status` plus a service check. 404 on unknown company (read, write, history). ORM FK declared. `GET …/screening-review/{key}/history` paged. `capabilities.can_record_decision`. D9 `screening` history rows. Route-auth rows added. |
| 4B-2 superseding reviews | **Done** | `verification_review` table (append-only, unique supersedes, one-first-review partial index, same-result composite FK, note required on supersede). Legacy reviews copied. 409 on a stale supersede, and 409 on a legacy verdict with no review record (B4). Race tests. `verification` history rows. The reader reads the chain head. The legacy columns are no longer written. |
| 4B-3 polling safety | **Done** | Service guard + log. `FOR UPDATE` on poll and review. `trg_verification_result_outcome_freeze` with direct-SQL tests. |
| 4B-4 evidence + subjects | **Done** | `evidence_note` / `evidence_refs` (frozen). D16 in `check_manual_outcome` (one place). Document refs checked through `CrmDocumentRepository` for existence, ownership and `AVAILABLE` (B1). EXPORTER ghost → 404. Manual `PENDING` refused. The reader fills `evidence_document_ids`. |
| 4B-5 buyer checks | **Done** (backend + `BuyerChecks`, not mounted) | Validation against `deal_buyer.id` (a company or deal id is refused). `subject_snapshot` survives `set_buyer`. Masked for non-COMPLIANCE/ADMIN. History on the deal's company with `deal_id`. D17 409 `DEAL_CLOSED`. `buyer_checks` reader. No company effect (tested). |
| 4B-6 placeholders + provenance | **Done** (backend; UI labels in 4B-7) | Dev generator removed. `is_placeholder` / `provenance` served. The stub stores `rxil_stub` and refuses `PENDING`. D7: `POST /verifications` accepts `manual` only. Bank response `provider_feed_connected=false` / `NOT_CONNECTED`. |
| 4B-7 frontend | **Done** | See §3.3. |
| 4B-8 RXIL intake | **BLOCKED (D12)**, correctly untouched | Stub labelled. `trigger_verification_batch` has no caller. |

Decisions already applied in code: D7, D8 (no widening), D9, D15, D16, D17 (see `4b-task.md`
§13).

---

## 6. Prompt scaffolding

### Prompt A — backend fix-ups, docs, BuyerChecks — **DONE**

See §3.1, §3.2, §3.4 and §3.5.

### Prompt B — 4B-7 frontend (F1–F11) — **DONE**

See §3.3. The prompt text is kept for reference.

```
You are Dev4B on branch feature/4b-verification-screening-integrity (repo C:\e9-build).
Spec: docs/dev4/4b-task.md §5.10 and §14 4B-7. Work list: docs/dev4/4b-remaining-work.md §3.3
(F1–F11). The backend already serves catalogue, capabilities, review chains, provenance,
is_placeholder, evidence, subject_snapshot, item history and the bank NOT_CONNECTED fields.
Reuse what Prompt 1 added: components/verification-labels.ts, the 4B aliases in types.ts, and
the review/record flows in components/BuyerChecks.tsx (keep BuyerChecks' 20 tests green; it
stays unmounted and out of components/index.ts).
Build ManualResultForm, ReviewDialog (supersede with latest_review_id + required note, handle
409), ScreeningChecklist (from the served catalogue, with per-item history), an honest bank
panel, and provenance/placeholder labels.
Keep `VerificationSection({ customerId })` stable. Remove every user.role comparison and
CHECKLIST_ITEMS from Dev4B files. Add aliases only inside the 4B block of types.ts.
Write vitest for each component, including loading, empty and error states.
The repo is hand-formatted (single quotes, ~100 cols). Do NOT run prettier. Do not commit or stage.
Gates: npx tsc -b --noEmit; npx eslint . (0 errors); npx vitest run; npx vite build; and the
backend test_openapi_artifact_is_current if anything in the API changed.
```
