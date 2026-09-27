# Dev3b — what is left, and who owns it

**As of 27 September 2026**, after the four phases on
`feature/deals-storage-documents` (L3-01b, L3-05 … L3-10, L3-11b), commits
`c787a6e`, `c82d6fc`, `a59fc82`, `f46935c`.

**Nothing below is a code defect.** Every defect found during the work is fixed and
tested (§1). What remains is a **decision**, a **review the plan requires**, or
**another developer's task** — with one exception that matters more than the rest:
**no deal in this build can be handed over**, because Developer 4's migration 0015
does not exist (§6).

| When | Items |
|---|---|
| **Before merge** | §3 Dev1's review of the shared files · §4 Dev2's review of the two migrations and `config.py` |
| **After merge** | Everything else |

Verification as measured: §8.

---

## 1. Fixed during the work (for the record, nothing to do)

So a reader does not re-raise them:

| Finding | Fix |
|---|---|
| `db.get(ExporterProfile, company_id)` looked up the table's primary key (`id`), not the company's business key (`customer_id`), so the handover guard raised `DEAL_COMPANY_NOT_FOUND` for companies that plainly existed | Selects by `customer_id`; ten tests failed on it and now pass |
| `hooks/deals.ts` invalidated `['conversation', customerId]`, which is not a key anything uses — 3A's are `['exporterConversation', …]` and `['conversationHistory', …]`. A query key is a string, so it type-checked and would simply never have invalidated: the gauge would show a stale value after opening a deal | Both real keys invalidated, and every key this file touches was cross-checked against `hooks/engagement.ts` |
| `GET /documents/content` was declared **after** `/documents/{document_id}`; FastAPI matches in declaration order, so every download would have been read as a document id and refused as an invalid UUID | Content route declared first, with a comment saying why, and the API test fetches a real document through a minted link so the order is pinned |
| A test mutated the shared `compliance` built-in role and restored it in a `finally` whose first assertion sat outside the `try` — a failure left the role corrupted for the rest of the session | Not this branch's code (it was the earlier RBAC work), but the lesson is applied here: **no L3B test mutates a shared or built-in row**; every one mints its own company, deal and storage root |

---

## 2. Programme lead — decisions

### 2.1 No cross-company Deals or Documents screens — **decide, after merge**

The 3B prompt's §5 expects **Deals** and **Documents** rows in `layout/Sidebar.tsx`.
I added neither, deliberately: there is no cross-company deal or document endpoint,
so those rows would lead to a page that can only say "pick a company first" — the
fake navigation `Sidebar.tsx`'s own docstring forbids.

Deals are reached from the company's Deals panel; paperwork from a link beside it.
If the rows are wanted, they need backend routes first (`GET /onboarding/deals`,
`GET /onboarding/documents`, both cross-company, both paged and role-gated).
**Owner once decided: Dev3b** — two routes, two screens, two sidebar rows.

### 2.2 Gate §7.6 is unmet, and that is the real limit on this feature

Neither item is in §9.3's scope, and both block real use:

- **There is no virus scanner.** `PassThroughScanner` returns clean for everything.
  It is labelled `pass-through` on every row, in every API response, on every
  document badge and in the upload form's own warning — but it is not a scan.
  A real one (AWS GuardDuty Malware Protection for S3, or self-hosted ClamAV)
  replaces one implementation of `ScannerPort` and nothing else.
- **There is no S3, Object Lock, KMS or retention lock.** Local disk only, so the
  seven-year AML retention requirement is met by nothing here. S3 is a second
  implementation of the same `StoragePort` (decision D8).

**Until both land, real exporter documents must not be uploaded to this build.**
Who owns them, and when, is a programme decision — they are infrastructure, not
§9.3 tasks.

### 2.3 `app/integrations/object_storage` — keep or retire

The prompt's §6.2 says to replace an empty scaffold at
`onboarding/integrations/object_storage`. **That path does not exist.** The real
scaffold is `app/integrations/object_storage`, and I left it in place: its README
says "Vendor implementations only. The port is owned by the consuming module
(ARCHITECTURE.md §8)", which is exactly the design built here — the port lives in
`onboarding/domain/storage.py` — and it is the documented home for the future S3
*vendor* implementation. Deleting it would remove where S3 is meant to go and break
the uniformity of fourteen sibling scaffolds.

If audit note E34 meant something else, say so and I will retire it.

### 2.4 Environment, not code

- **The dev database holds roughly 7,900 test rows** (6,681 companies, 311 deals,
  97 documents, 934 users) left by the suite runs. A transactional cleanup script
  that keeps the seven §3.9 sample companies, their three deals and the three real
  logins is written but **was not run** — the bulk delete was refused by a
  permission guard. Path:
  `<scratchpad>/cleanup-test-debris.sql`, run with
  `docker exec -i aner-postgres psql -U aner -d aner_settlement < …`. Harmless to
  correctness; unpleasant when browsing 6,688 companies in the UI, and this kind of
  accumulation is what made a query-planner test fail earlier in the week.
- **The committed `frontend/openapi.json` embeds `info.title`, which comes from
  `APP_NAME`.** A developer whose `backend/.env` sets a different app name
  regenerates an artifact that fails `test_openapi_artifact_is_current` for
  everyone else. I generate with `APP_NAME` pinned to the `Settings` default
  ("Business Platform"), which is what the committed artifact holds. **Worth fixing
  properly** — either drop `info.title` from the comparison or fix it in code.
- **The suite cannot fully run inside the `aner-app` container** unless
  `./frontend` is mounted: `test_openapi_artifact_is_current.py` resolves the repo
  root from the backend package and looks for `/frontend/openapi.json`, while
  compose mounts only `./backend`. Three tests fail for that reason alone. A host
  run never sees it; I mount `./frontend:/frontend:ro` in a local override.
- **There is no supported way to create a staff account.** `/auth/register` only
  ever makes an `API_USER` (correctly), Dev1's first-admin command (L1-09) is not
  built, and the admin user-management screens live on an unmerged branch. Every
  staff login today needs a direct `UPDATE auth.users SET role = …`.

---

## 3. Developer 1 — review before merge, then register

**Before merge** (architecture §8.1 assigns these files to Dev1). Every addition
sits under the 3B anchor the seam commit created, and nothing else in these files
was touched:

1. `onboarding/exceptions.py` — **14 new classes** (6 deal, 8 document/storage).
2. `domain/entities/__init__.py`, `infrastructure/repositories/__init__.py`,
   `application/__init__.py` — late imports, each carrying `# noqa: E402` in the
   style 3A established there.
3. `backend/tests/contract/test_route_authorization_coverage.py` — 13 new rows.
4. `backend/app/modules/onboarding/tests/integration/test_route_authorization.py` —
   11 new rows. The two multipart uploads are **not** here: this table sends a JSON
   body, and a multipart route rejects JSON at parsing before the gate is reached,
   which would prove nothing about the gate. Their refusal tests live in
   `test_l3b_documents.py` instead.
5. `frontend/src/modules/onboarding/types.ts` and `routes.tsx` — under the 3B
   anchors. Also `pages/index.ts` and `components/index.ts`, which §8.1 does not
   list but 3A appended to the same way.

**After merge:**

6. **`docs/contracts/migration-register.md` is now wrong in three ways.** The 0018
   row says parent `0014`, "not started"; it is parent **`onboarding_0016_engagement`**
   and merged — 3A landed first, so per §3 I parented onto them and did **not**
   re-parent. The 0019 row says "not started"; it is merged, parent `0018`. And the
   "Head today" line still says `onboarding_0013_shared_history`; the head is
   **`onboarding_0019_documents`**.
7. **`HistoryService.list_for_deal`'s docstring is now stale.** It says "Empty until
   deals exist (migration 0018, Developer 3)". Deals exist, and it works: a sample
   deal returns three real rows (`deal_initial`, `deal_buyer_changed`,
   `deal_transition`), each with `deal_id` set. Verified through
   `GET /onboarding/deals/{id}/history`. Nothing to build — just a comment, and the
   same for `dev1-remaining-work.md` §4's "`DealsPanel` renders `null`", which it no
   longer does.
8. Authoritative API regeneration at the milestone (L1-14), and §2.4's `APP_NAME`
   trap, which lands on whoever regenerates.
9. Acknowledge `deal-and-buyer.md` §7 (the history fields: `dimension="deal"`,
   `deal_id` always set, `event_type` `deal_initial` / `deal_transition` /
   `deal_buyer_changed`) and its §8 error codes.

---

## 4. Developer 2 — review before merge

1. **Both migrations add foreign keys *referencing* `exporter_profile.customer_id`
   with `ON DELETE RESTRICT`** (`fk_deal_company_id`,
   `fk_crm_document_company_id`). Nothing in `exporter_profile` is altered, but the
   consequence is theirs to know: **a company with a deal or a document can no
   longer be deleted.** Deliberate — deleting a company would destroy the record of
   what was financed — but any future cleanup, and 0014's own truncate guard, must
   remove deals and documents first.
2. **`app/modules/onboarding/config.py`** gained `CRM_DOCUMENT_CONFIG_DIR` and
   `DEFAULT_DOCUMENT_TYPES_PATH`, pointing at
   `deployments/gitops/reference-data/crm/documents/document-types.yaml`. §8.1 does
   not assign that file an owner; it is flagged here because it is theirs by
   proximity.
3. **`DealsPanel` now renders content** on their detail page, and links to a new
   route `/exporters/:customerId/documents`. `ExporterDetailPage.tsx` is **not**
   touched — the shell already mounted the panel with `{ customerId, isStaff }`.
4. **`sample_data.py` is not touched.** `sample_data_deals.py`'s hook is filled and
   seeds three deals; a repeat run reports zero.

**After merge:** acknowledge `deal-and-buyer.md` §2 (a company has many deals) and
§3.1 (a buyer's problems never touch the company record — there is no "bad deal" or
"buyer risk" field on `exporter_profile`, and adding one would be a contract
change).

---

## 5. Developer 3A — after merge

1. **Seam S2's button is yours to land.** `openDeal` / `useOpenDeal` and every deal
   type are exported through the barrels and have been since `c82d6fc`.
   `components/OpenDealPrompt.tsx` is **your file** and I did not touch it: it still
   renders the note and no button, and its own docstring already names the exact
   imports (`../api`, `../hooks`, never 3B's files directly).
2. **Seam S1 is in and tested.** `DealService.open_deal` calls
   `mark_ready_now_for_opened_deal` in the same transaction. Tests assert the gauge
   moves, your history row carries the `deal_id`, and a second deal on an
   already-ready company writes no second row (your idempotence).
3. **`dev3a-remaining-work.md` §5 is now done** — all four items: S1 called, S2
   published, 0018 parented on 0016, `# noqa: E402` on the late imports. Retire it.
4. Acknowledge `deal-and-buyer.md` §5 and `storage-and-documents.md`.

---

## 6. Developer 4 — after merge, and this one blocks a shipped feature

**Migration 0015 does not exist.** Confirmed three ways: no migration file,
`origin/main` unchanged since `447c6ba`, and `background_check` absent from the live
database. So assumption A5's second half cannot be evaluated and **no deal in this
build can be handed over.** The guard refuses every attempt with
`DEAL_HANDOVER_BLOCKED`, `allowed_stage_moves` omits the move, and the screen says
"the background check is not recorded yet".

"Not recorded" is never treated as "clear". I did not create that column, write to
it, or default it — `company-record.md` §2.4 forbids the first two, and the third
would hand a deal to the lending team on the strength of a column that does not
exist.

**What to do when 0015 lands:**

1. **Publish the read helper** (L4-01). Then in
   `application/deal_service.py`, `read_background_check(company)` — a deliberate
   one-function seam — becomes a call to it. That is the whole change.
2. **Delete the `clear_background_check` fixture** in
   `tests/integration/test_l3b_handover.py`. Its success-path tests substitute
   exactly that one function today, and say so in their docstrings; with a real
   column they become ordinary end-to-end tests.
3. **Promote `_handover_blocked_error`** from an inline `AnerBaseException` in
   `deal_service.py` to a named class in `exceptions.py` (a comment there says why
   it was not added ahead of the route that raises it).
4. **Finish the §3.9 sample state** (§7.2 below) — one of company B's deals is meant
   to be handed over, and company C's blocked because its check is *flagged*.

**Also yours, and unblocked today:**

5. **Buyer checks attach to `deal_buyer.id`**, not to the deal and never to the
   company (`deal-and-buyer.md` §3, decision 9). That row exists now, one per deal,
   with its own id — which is why it is a table rather than columns.
6. **Evidence at decision time** (plan §8.2) comes from `DocumentService` and
   `StoragePort`: document ids are stable, `crm_document.storage_key` is unique, and
   content is refused for anything not `AVAILABLE`.
7. Your placeholder clean-up task and my pass-through scanner meet here: the
   scanner is labelled everywhere it appears (§2.2), so the "fake passed that looks
   real" failure is covered on the document side.
8. Acknowledge `deal-and-buyer.md` §6 and `storage-and-documents.md` §4, §7.

---

## 7. Developer 3B — after merge

1. **Collect the acknowledgements.** L3-01b's done-when is both contracts merged
   *and* 3A, Dev2 and Dev4 each confirming they read them. All still pending.
2. **Sample data is honest but incomplete.** Architecture §3.9 wants one of company
   B's two deals *handed over*, and company C's blocked *because its check is
   flagged*. Neither state is reachable without 0015, and writing the stage directly
   would put rows in the database that the service would never produce, with no
   history behind them. Both of B's deals stop at `GATHERING_PAPERWORK` with buyers
   recorded; C's is `OPEN`. **No documents are seeded at all** — worth adding once
   there is a scanner worth running.
3. **S3 implementation of `StoragePort`**, with Object Lock and KMS (§2.2).
4. **Cross-company deal and document lists**, if the lead wants the sidebar rows
   (§2.1).
5. **No delete or replace path for a document.** `StorageService.delete` exists and
   is tested but no route calls it: replacing a document means uploading a new one,
   and nothing in §9.3 asked for deletion. Decide whether an ops person needs it —
   note that seven-year retention argues against ever deleting.
6. **Optional, if the lead prefers it:** company documents as a section on the
   company page rather than their own route (§2.1's sibling decision).

---

## 8. Verification as measured

```
alembic heads            -> onboarding_0019_documents (head)       # exactly one
upgrade / downgrade -1 / upgrade, both 0018 and 0019               # clean
ruff  (app/modules/onboarding)
                         -> 9 findings, all pre-existing
                            (verified by running ruff against the same files
                             as they stand at 447c6ba, before this branch)
lint-imports             -> 19 kept, 0 broken
backend suite            -> 22 failed, 3738 passed, 6 skipped, 5 errors
                            = the 27 known payments/FX and compliance failures,
                            nothing else
L3B tests                -> 197 passed
                            81 storage · 47 deal/buyer · 58 document · 11 handover
                            a direct-SQL violation test for each of the 11 new
                            constraints
tsc                      -> clean
eslint                   -> 0 errors, 2 pre-existing warnings
vitest                   -> 91 passed (12 files)
vite build               -> ok
sample data              -> 3 deals created, 0 on a repeat run
```

**A note on the baseline:** `dev3a-remaining-work.md` §2.5 reports 29F/22E because
that machine's read-only role passwords no longer match its test settings. This
branch measures 22F/5E — the clean 27 — because `backend/.env` here has
`LEDGER_RO_DB_PASSWORD`, `SETTLEMENT_RO_DB_PASSWORD` and `AUDIT_RO_DB_PASSWORD`
set. The difference is environment, not code.
