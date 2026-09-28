# Prompt — Developer 3B: deals, buyers, storage and documents

**Source of truth:** `docs/Exporter-CRM-Architecture-and-Plan.pdf` v1.0 (25 September 2026),
§9.3 "Developer 3: Conversations, deals and paperwork", plus the shared rules in
§7.5, §7.7 and §8.

Section 9.3 was written for one developer. It is being run by two, 3A and 3B, in
parallel. **You are 3B.** Your counterpart 3A has the mirror prompt in
`docs/dev3a-prompt-conversation-and-followups.md`. The split below was chosen so that
after one short seam commit neither of you ever edits a file the other is editing,
and neither of you can break the other's logic without a compile or test failure
saying so.

Read this whole file before writing code. The two sections marked **THE SHARED
AGREEMENT** say the same thing in both prompts, written from each side: same files,
same names, same merge order. If you change one, change 3A's copy too and tell them.

---

## 1. Your mission

Every deal a company has, from "there is a real need" to "handed to the lending team",
and the safe document storage that carries its paperwork. Nothing about contacts,
activities, the conversation gauge or follow-ups is yours.

From §9.3's task table you own **L3-01b and L3-05 through L3-10**, plus the deals and
documents half of **L3-11**.

| ID | Task | Size | Needs | Done when |
|---|---|---|---|---|
| L3-01b | Publish the **deal/buyer contract** and the **storage + document contract** | S | — | `docs/contracts/deal-and-buyer.md` and `docs/contracts/storage-and-documents.md` merged; 3A, Dev 2 and Dev 4 have each confirmed they read them |
| L3-07 | Storage interface and local-disk implementation; relative keys; download through the API or a short-lived link | L | L3-01b | Upload and download work; no cloud address is ever stored |
| L3-08 | Scan step: `PENDING_SCAN` until cleared; labelled pass-through scanner (A9); quarantine and alert paths | S | L3-07 | Unscanned files cannot be opened |
| L3-05 | Deal record (migration 0018): many per company; `OPEN`, `GATHERING_PAPERWORK`, `HANDED_OVER`, `WITHDRAWN` (A7); `READY_NOW` prompts a deal | M | L2-05, seam S1 | Stages and history work; opening a deal sets `READY_NOW` |
| L3-06 | Buyer details on the deal | S | L3-05 | Buyer saved, shown and linked for checks |
| L3-09 | Document records (migration 0019) owned by a company or a deal; categories checked by the server; types as settings; source | M | L3-07 | An invalid category is refused; category lists are contextual |
| L3-10 | Hand over a deal: guard (CUSTOMER **and** CLEAR, A5); announce `deal.handed_over` | S | L4-03, L1-12 | Guard tested; the event carries buyer and document IDs |
| L3-11b | Screens: Deals panel, deal list and detail, document upload and list | L | L3-05 … L3-10 | Usable end to end on sample data, with loading, empty and error states |

**Do them in the order of the table, not the order of the IDs.** L3-07 and L3-08 are
your largest chunk and depend on nobody, so starting there buys the time 3A needs to
land the conversation gauge that L3-05 calls (seam S1, §4). L3-10 goes last: it is
blocked on Dev 4 — see §6.6.

---

## 2. What you own exclusively

You may create and edit these freely. Nobody else touches them.

**Backend** (under `backend/app/modules/onboarding/`)

- `api/deal_router.py` — **new**, deals and buyers
- `api/document_router.py` — **new**, upload, list, download
- `api/schemas/deal.py`, `api/schemas/document.py` — **new**
- `application/deal_service.py`, `application/document_service.py` — **new**
- `application/storage_service.py` — **new**, or wherever your contract puts the port
- `domain/entities/deal.py`, `domain/entities/deal_buyer.py`, `domain/entities/crm_document.py` — **new**
- `domain/entities/deal_enums.py`, `domain/entities/document_enums.py` — **new**; do **not** add values to `exporter_enums.py` (Dev 2's) or `engagement_enums.py` (3A's)
- `domain/deal_views.py`, `domain/document_views.py` — **new**
- `domain/storage.py` — **new**, the `StoragePort` protocol
- `infrastructure/storage/` — **new** package: `local_disk.py`, `passthrough_scanner.py`, and later an S3 implementation of the same port. This replaces the empty `integrations/object_storage` scaffold (audit note E34) — see §6.2.
- `infrastructure/repositories/deal_repository.py`, `deal_buyer_repository.py`, `crm_document_repository.py` — **new**
- `migrations/onboarding_0018_deal_buyer.py`, `migrations/onboarding_0019_documents.py` — **new**, see §3
- `sample_data_deals.py` — **new**, called from the seam commit's hook
- tests: any new file whose name starts `test_l3b_`, under `tests/unit/` and `tests/integration/`

**Frontend** (under `frontend/src/modules/onboarding/`)

- `pages/panels/DealsPanel.tsx` — currently returns `null` on purpose; it is your seam
- `pages/DealsPage.tsx`, `pages/DealDetailPage.tsx`, `pages/DocumentsPage.tsx` (+ their `.test.tsx`) — **new**
- `api/deals.ts`, `api/documents.ts` — **new**
- `hooks/deals.ts`, `hooks/documents.ts` — **new**
- `components/DocumentUpload.tsx`, `components/ScanStatusBadge.tsx` — **new**

You do **not** edit `pages/ExporterDetailPage.tsx`. The shell already mounts
`DealsPanel` with `{ customerId, isStaff }` — read that panel's docstring: it was
written as a one-file change for exactly this work.

---

## 3. Your migrations: 0018 and 0019

**0018 — `onboarding_0018_deal_buyer`**

- `onboarding.deal`: real FK to `exporter_profile.customer_id`, a stage column on a
  new `onboarding.deal_stage_enum` (`OPEN`, `GATHERING_PAPERWORK`, `HANDED_OVER`,
  `WITHDRAWN`), a withdrawal reason (required when `WITHDRAWN`, assumption A7), and
  timestamps.
- Buyer details on the deal: name, country, identifiers (architecture §3.3). Whether
  that is columns on `deal` or its own `deal_buyer` table is your call — write the
  decision into your contract, because Dev 4 attaches buyer checks to it (§8.2:
  "buyer checks attach to the deal's buyer").
- `down_revision = "onboarding_0016_engagement"` — 3A's migration, which lands first.

**0019 — `onboarding_0019_documents`**

- `onboarding.crm_document`: owner (a company **or** a deal — architecture §3.4),
  category on a fixed server-checked enum, type (a settings value, not an enum),
  source (`RXIL`, `EXPORTER_UPLOAD`, `INTERNAL`, `SYSTEM`), file name, file type,
  size, uploader, timestamp, scan status, and the **relative storage key only**.
- `down_revision = "onboarding_0018_deal_buyer"`.

**Parent chain.** The current head is `onboarding_0020_retire_lifecycle` (0014, 0017
and 0020 have landed; Dev 4's 0015 has not). Numbers are labels, not order — the
register says so — and the agreed order is 0016 → 0018 → 0019. If you are somehow
ready to merge before 3A, **you re-parent, not them**: only the later-merging
developer edits a `down_revision`, and whoever does it tells Dev 1 to update
`docs/contracts/migration-register.md`.

Register rules that will actually bite you:

- **Revision id ≤ 32 characters.** `onboarding_0018_deal_buyer` is 26 and
  `onboarding_0019_documents` is 25. Fine. A longer one fails on the database
  partway through the DDL.
- **Never `ALTER TYPE … ADD VALUE` inside an autocommit block.** You create four
  enums; create them all in ordinary transactional migrations, as
  `onboarding_0012_risk_critical` does. This has broken the repository before.
- **One head**, before and after each migration.
- **Every new constraint gets a direct-SQL violation test** that bypasses the ORM with
  `psycopg2`, so it proves the *database* refuses it: the ghost-company FK, the
  ghost-deal FK, and the "document belongs to exactly one owner" check.
- Write the downgrades; if one is lossy, say so in the docstring.

Run this every time, before opening a PR:

```bash
cd backend
alembic heads          # exactly one
alembic upgrade head
alembic downgrade -1
alembic upgrade head   # the round trip must be clean
python -m pytest -q --no-cov -p no:cacheprovider
```

---

## 4. The two seams between you and 3A — THE SHARED AGREEMENT

There are exactly two places where your work and 3A's touch. Both are one-way function
calls across a named boundary. Neither of you reaches into the other's tables, enums or
services by any other route.

### Seam S1 — opening a deal sets the conversation to READY_NOW

Architecture §3.3: "READY_NOW … The screen offers to open a deal; opening a deal also
sets this." So **your** `open_deal` has to move 3A's gauge.

- **3A publishes**, in `application/conversation_service.py`:

  ```python
  class ConversationService:
      async def mark_ready_now_for_opened_deal(
          self,
          company_id: uuid.UUID,
          *,
          deal_id: uuid.UUID,
          actor_id: str,
      ) -> None:
          """Set conversation to READY_NOW because a deal was opened.

          Idempotent: already READY_NOW writes no history row. Flushes; does not
          commit — the caller owns the transaction, so the deal row, the deal
          history row and this gauge move land together or not at all.
          """
  ```

- **You call it** from `DealService.open_deal`, in the same session and transaction,
  passing `deal_id` so 3A's history row carries it (history contract §2: `deal_id` is
  set when another dimension's change is about a specific deal).
- **You never write `exporter_profile.conversation`** and never import 3A's enum to
  compare against it. `company-record.md` §2.4 forbids assigning to another
  developer's gauge field, "including just to keep it in step".
- **Merge order:** 3A's L3-03 merges before your L3-05. This costs you nothing — your
  order above starts with storage, which does not depend on 3A, so by the time you
  reach the deal record their service exists. If you get there first, land L3-05
  without the call and add it in a one-function follow-up commit; **do not stub their
  service** and do not write the column yourself.

### Seam S2 — the "open a deal" prompt on the Conversation panel

When conversation is `READY_NOW`, 3A's panel offers to open a deal.

- **You publish** the request function and hook for creating a deal in `api/deals.ts`
  / `hooks/deals.ts`, exported through the barrels the seam commit already wired.
- **3A imports it through the barrel**, never from your file directly, and defines no
  deal request function or deal type of their own.
- **Merge order:** your deal route merges before their prompt. Tell 3A the moment the
  route and hook are on the integration branch, with the exact names.

**That is the whole interface.** If you find you need a third seam, stop and agree it
with 3A in writing before writing code (§7.5: "Contracts change only with the
agreement of the owner and every user of that contract").

---

## 5. Step 0 — the seam commit — THE SHARED AGREEMENT

A handful of files are shared by every developer: the module's exception list, its
entity/repository/service indexes, the router index, the route-authorisation tables,
and the frontend barrels. If you and 3A both append to them on separate branches you
will conflict in the same hunk, every time.

So **3A lands one small commit first — nothing but seams, no behaviour — and you
review it.** Half a day at most. After it, neither of you edits a shared file again.
**Your first job is that review**, because three of the stubs are yours; do not start
L3-07 against a branch that does not have it.

**What it contains:**

1. **Empty routers**, mounted once and never re-mounted:
   - `api/follow_up_router.py` (3A's), `api/deal_router.py` and
     `api/document_router.py` (yours) — each just `router = APIRouter(...)` with a
     docstring naming its owner, and no routes.
   - `api/router.py` gains all three `include_router(...)` lines in this one commit,
     beside the existing engagement/screening/qualification includes and in the same
     comment style. **Neither of you touches `api/router.py` again.**
   - A router with no routes adds nothing to the OpenAPI document, so
     `frontend/openapi.json` does not move and
     `backend/tests/contract/test_openapi_artifact_is_current.py` stays green. Check
     that `python -m pytest backend/tests/contract -q` is green in the commit.
2. **Empty schema modules**: `api/schemas/follow_up.py`, `api/schemas/deal.py`,
   `api/schemas/document.py` — docstring and owner, nothing else.
3. **Two anchor blocks, separated by at least one line of real content**, in each of
   the shared files below, so your additions and 3A's land in different hunks:

   ```
   # ── Conversation and follow-ups — owner: Developer 3A (L3-02 … L3-04) ──
   # (3A appends here; 3B does not.)

   # ── Deals, buyers, storage and documents — owner: Developer 3B (L3-05 … L3-10) ──
   # (3B appends here; 3A does not.)
   ```

   | File | Owner per §8.1 |
   |---|---|
   | `onboarding/exceptions.py` | Dev 1 — additions only, owner reviews |
   | `domain/entities/__init__.py` | Dev 1 |
   | `infrastructure/repositories/__init__.py` | Dev 1 |
   | `application/__init__.py` | Dev 1 |
   | `backend/tests/contract/test_route_authorization_coverage.py` (inside `GATED_ROUTES`) | Dev 1 |
   | `backend/app/modules/onboarding/tests/integration/test_route_authorization.py` | Dev 1 |
   | `frontend/src/modules/onboarding/types.ts` | Dev 1 |
   | `frontend/src/modules/onboarding/routes.tsx` | Dev 1 |
   | `frontend/src/layout/Sidebar.tsx` | Dev 1 |

   All nine are Dev 1's per §8.1, so **this commit is a PR Dev 1 reviews**, and it is
   the only time either of you asks for that review. Note the sidebar already has a
   `Follow-ups` row with `status: 'soon'` — 3A flips that one word; **you add the
   Deals and Documents rows under your anchor**, `status: 'soon'` until the screens
   exist. Different lines, no conflict.
4. **Frontend stubs and barrel lines**: `api/follow-ups.ts`, `api/deals.ts`,
   `api/documents.ts`, `hooks/follow-ups.ts`, `hooks/deals.ts`, `hooks/documents.ts`
   — each an empty module with its owner in the docstring — plus the matching
   `export * from './…'` lines added to `api/index.ts` and `hooks/index.ts` in this
   one commit. Neither of you edits those two barrels again.
5. **Sample-data hooks**: `sample_data_engagement.py` (3A's) and `sample_data_deals.py`
   (yours), each exposing one async no-op seeder, plus the two call sites added to
   `backend/app/modules/onboarding/sample_data.py`. That file is Dev 2's, so **Dev 2
   reviews this part**. Neither of you edits `sample_data.py` again.

**What it must not contain:** a single route, enum value, column or rendered pixel. The
suite must be at baseline and `frontend/openapi.json` byte-identical when it merges.

---

## 6. Rules you will otherwise get wrong

### 6.1 Storage keys, and what must never be in them

Architecture §3.4 fixes the key shape:

```
{env}/{owner_type}/{owner_id}/{source}/{document_id}{ext}
```

- **Only the relative key is stored, never a cloud address**, so the provider can
  change without touching a single record (decision D8).
- **Keep the original file name and type out of the key.** They are stored as details
  on the document row. §9.3's "Watch out for" lists this explicitly — a user-supplied
  file name inside a key is both a path-traversal surface and a rename hazard.
- Everything the local-disk implementation writes stays under one configured root, and
  a key that escapes it is refused before any I/O.

### 6.2 The port comes first, then two implementations

L3-07 is "storage interface **and** local-disk implementation". Define
`StoragePort` — `upload`, `get_download_link`, `delete`, and the scan status — in
`domain/storage.py`, and make the local disk one implementation behind it. S3 with
Object Lock and KMS is a second implementation of the same port, later (D8, gate
§7.6). Dev 4 uses this port for evidence (§8.2: "document and check-result IDs used
as evidence at decision time"), so the port is a published contract, not an internal
detail.

`backend/app/modules/onboarding/integrations/object_storage` is an empty scaffold
(audit note E34). Replace it; do not build beside it, and do not leave both.

### 6.3 The scanner is a placeholder and must say so

Assumption A9 and gate §7.6: the prototype ships a **clearly labelled pass-through**
scanner. That means:

- Every upload lands `PENDING_SCAN` and **cannot be opened** — prove that with a test
  that tries.
- A clean result makes it `AVAILABLE`; infected or failed makes it `QUARANTINED` or
  `SCAN_FAILED`, never served, and raises an alert.
- The label is in the data as well as on the screen — scanner `"pass-through"`,
  exactly as providers are stored `"manual"` (§7.5, D4: stored lowercase, displayed
  uppercase).
- The screen says the scanner is a placeholder. §9.3's "Watch out for" requires this,
  and gate §7.6 blocks real documents until a real scanner is behind it. A fake
  "passed" that looks real is the specific failure Dev 4's placeholder clean-up exists
  to prevent.

### 6.4 Categories are a fixed server-checked list; types are settings

Architecture §3.4. Ten categories, each belonging to a company, a deal, or both:
`ENTITY_KYC`, `COMPLIANCE_SCREENING`, `COMPANY_MARKET_REVIEW` (company);
`PRE_SHIPMENT`, `SHIPPING`, `CUSTOMS_AND_REGULATORY`, `BUYER` (deal); `BANKING`,
`INSURANCE`, `OTHER` (both). The server refuses a category that does not belong where
it was filed, and a screen shows only the categories valid for where the user is
(company page or deal page). Document **types** within a category are seeded settings,
so a new type needs no code change. `COMPANY_MARKET_REVIEW` with source `SYSTEM` is
for later (D16) — the category exists, nothing generates into it in the prototype.

### 6.5 Customer, deal and buyer stay separate

Architecture §3.5 and decision 9. A buyer failing a check is recorded on the **buyer**;
a deal falling through is `WITHDRAWN` with a reason on the **deal**; neither touches the
company's record. Do not add a "has a bad deal" or "buyer risk" field to
`exporter_profile`. Transactions and how they perform are the lending side's, outside
the CRM entirely — do not model them.

### 6.6 L3-10 is blocked on Dev 4, and that is expected

The handover guard (assumption A5) needs the company to be `CUSTOMER` **and** its
background check `CLEAR`. `exporter_profile.background_check` does not exist yet: it is
Dev 4's column in migration 0015, which has not landed
(`company-record.md` §2.4 and §411 both say so).

- **Do not add that column yourself.** `company-record.md` §2.4 forbids writing to
  another developer's gauge field, and creating it would make Dev 4's 0015 fail.
- Read it, once it exists, through whatever read helper Dev 4 publishes in the
  background-check contract (L4-01). Ask for it at the daily check-in; §8.2 names this
  hand-off (`Dev 3 ↔ Dev 4`, agreed in "A5; deal contract").
- Do everything else in the meantime. Land L3-10 last, and if 0015 is still not there
  at your end date, say so in your progress note rather than faking the guard.

`OnboardingEventPublisher.deal_handed_over(...)` already exists in
`backend/app/modules/onboarding/events/publisher.py` with the payload the plan
specifies — deal ID, company ID, buyer, and the list of document IDs. Use it; do not
write another publisher. Architecture §3.6: the history row is the source of truth and
the announcement is best effort, so **write the history row first, then announce**.
The `document_ids` list is a snapshot of what the handover rested on, so a later upload
cannot change what the lending team was given.

### 6.7 Every stage move writes history, in the same transaction

Use Dev 1's `HistoryService.record(...)` in `application/history_service.py`. For you:

- `dimension="deal"` — fixed by `docs/contracts/history-row.md` §2; do not invent a
  dimension string
- `deal_id` **must** be set on every `deal` row (contract §2: "set exactly when
  `dimension = "deal"`"), and `company_id` is still required — a deal's history is
  part of its company's story
- `event_type`: `deal_initial` when the deal is created at `OPEN`, `deal_transition`
  for a move
- `source="deal_service.<method>"` — dotted, the code path
- `actor_id` from the login session, **never** from the request body (§7.5)
- `reason` required for `WITHDRAWN` (A7)

`record()` flushes and does not commit. The deal row and its history row land in one
transaction (architecture §3.8).

### 6.8 The server serves the allowed moves

§7.5: the frontend fetches the allowed deal moves for the current user rather than
keeping a hand-copied table. Expose them from the API; do not hard-code a stage
machine in `DealDetailPage.tsx`. Opening a deal is OPERATIONS, COMPLIANCE or ADMIN
(§3.3, §3.7); DEVELOPER reads and API_USER reaches nothing.

### 6.9 Every new route needs a role declaration, a test row and a documented 403

§7.5 and §7.7. You are adding the most routes of anyone, so for each one:

- roles via `require_role(...)`, matching the §3.7 matrix
- a `403` entry in the route's `responses={...}` description
- one row in `GATED_ROUTES` in
  `backend/tests/contract/test_route_authorization_coverage.py`, under **your** anchor
  from §5 — an unclassified route fails that test by construction
- a refusal test (§7.7: "at least one test for each refusal")

The download route needs more than a role check: an unscanned, quarantined or
failed-scan document is refused to **everyone**, and a short-lived link must actually
expire. Test both.

### 6.10 Generated API artifacts: regenerate, never merge

`frontend/openapi.json` and `frontend/src/lib/api/schema.ts` are generated. You and 3A
will both change them, and a three-way merge of generated JSON is worthless. After
every rebase onto the integration branch:

```bash
git checkout <integration-branch> -- frontend/openapi.json frontend/src/lib/api/schema.ts
cd frontend && pnpm generate:api
```

Dev 1 does the authoritative regeneration at each milestone (L1-14): the contract test
tells you it is stale, but a person still runs the command.

### 6.11 The module rule

All connecting code lives in `onboarding`. You edit no file in `kyb`, `cases`,
`customers` or `compliance` (architecture §2.5). The one documented exception is
Dev 1's, not yours.

### 6.12 Do not touch the legacy path

`domain/entities/onboarding_document.py` hangs off `onboarding_request` — the legacy
table (audit note E34). It is **not** your document record and must not be extended,
reused or renamed. Build `crm_document` fresh against the company and the deal. The
same holds for `onboarding_request`, `onboarding_event`, the Temporal workflow and the
18-state machine (§2.4, decision D11): out of scope, never built on.

---

## 7. Definition of done (plan §7.7, unchanged)

- Behaviour matches architecture §3.3-§3.6 and your own two contracts; roles enforced
  on the **server**.
- History rows written for every change; locked tables stay locked.
- Unit tests for the rules, route tests for the roles, at least one test for each
  refusal, and a direct-SQL test for each new constraint.
- Screens updated with loading, empty and error states, and the scanner labelled as a
  placeholder.
- Backend suite at baseline — **only** the 27 known payments/FX and
  compliance-screening failures. Anything else blocks the merge.
- `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build` all clean; no new
  import-rule violations (`lint-imports`).
- `alembic heads` prints one revision.

---

## 8. Reporting

Keep a short running note at `docs/dev3b-progress.md`: task, state, anything that
contradicts the architecture document or a contract, and any decision you had to make.
When you finish, add:

- the final deal/buyer shape and the storage port's signatures, and who has
  acknowledged each contract
- whether 0018 or 0019 needed anything the register did not anticipate, and the
  `down_revision` each ended up with
- the state of seams S1 and S2 — whose commit landed first, and whether the READY_NOW
  call is in
- the state of L3-10: guard implemented, or still waiting on Dev 4's 0015
- the two things gate §7.6 still blocks: a real virus scanner, and S3 with Object Lock
  and KMS. Say plainly that the prototype has neither, so nobody mistakes the
  pass-through for a scanner.

You have the larger half. If you fall behind, §7.1 and §10 say hand screens over
**early rather than late**: offer the document list screen to 3A (read-only, its own
file) with you reviewing, or the deal list screen to Dev 1, who has spare capacity from
Week 3. Do not hand over a migration; the chain must stay in one pair of hands per
number.
