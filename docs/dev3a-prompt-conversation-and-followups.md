# Prompt — Developer 3A: the conversation gauge and follow-ups

> **Run split into two phases.** This file is unchanged and remains the reference for
> the whole of 3A. The work is executed as two prompts, which together cover exactly
> what is below and nothing more:
>
> - Phase 1 — `docs/dev3a-phase1-prompt-conversation-gauge.md`: the §5 seam commit,
>   L3-01a, L3-02, L3-03, the NOT_NOW check-back rule, migration 0016 in full, and the
>   Conversation panel.
> - Phase 2 — `docs/dev3a-phase2-prompt-follow-ups.md`: follow-up completion, the
>   due/overdue read model, the Follow-ups page. No migration.
>
> The 3A/3B agreement in §4 and §5 is untouched, so
> `docs/dev3b-prompt-deals-storage-and-documents.md` needs no change. The phase
> prompts add one sub-anchor inside 3A's own anchor block and one extra sample-data
> stub, both invisible to 3B.

**Source of truth:** `docs/Exporter-CRM-Architecture-and-Plan.pdf` v1.0 (25 September 2026),
§9.3 "Developer 3: Conversations, deals and paperwork", plus the shared rules in
§7.5, §7.7 and §8.

Section 9.3 was written for one developer. It is being run by two, 3A and 3B, in
parallel. **You are 3A.** Your counterpart 3B has the mirror prompt in
`docs/dev3b-prompt-deals-storage-and-documents.md`. The split below was chosen so
that after one short seam commit neither of you ever edits a file the other is
editing, and neither of you can break the other's logic without a compile or test
failure saying so.

Read this whole file before writing code. The two sections marked **THE SHARED
AGREEMENT** say the same thing in both prompts, written from each side: same
files, same names, same merge order. If you change one, change 3B's copy too and
tell them.

---

## 1. Your mission

Track the sales relationship: who we talk to, what was said, how the conversation
is going, and what we owe the exporter next. Nothing about deals, buyers, files or
storage is yours.

From §9.3's task table you own **L3-01a, L3-02, L3-03, L3-04** and the conversation
half of **L3-11**.

| ID | Task | Size | Needs | Done when |
|---|---|---|---|---|
| L3-01a | Publish the **engagement contract**: conversation values, who may set them, which moves need a reason, the NOT_NOW check-back rule, the follow-up/completion shape | S | — | `docs/contracts/engagement.md` merged; 3B, Dev 2 and Dev 4 have each confirmed they read it |
| L3-02 | Contacts and activities must point at a real company (§9.3, E16) | S | already done in the DB by 0014 — see §6.1 | Ghost-company writes refused, with a direct-SQL test |
| L3-03 | Conversation gauge on the company, with history (assumption A4) | M | L3-02, L1-11 | Values and rules per architecture §3.3; every change writes a `conversation` history row in the same transaction |
| L3-04 | Follow-up completion as a new locked record (migration 0016); Follow-ups screen for the whole team; NOT_NOW requires a check-back date | M | L3-03 | Due and overdue lists correct; completing a follow-up leaves a record and never updates the activity |
| L3-11a | Screens: the Conversation panel (gauge control + history) and the Follow-ups page | M | L3-03, L3-04 | Usable end to end on sample data, with loading, empty and error states |

**Suggested order:** L3-01a → L3-02 → L3-03 → L3-04 → L3-11a. Do not move L3-03
later: 3B's L3-05 waits on the service you publish there (seam S1, §4).

---

## 2. What you own exclusively

You may create and edit these freely. Nobody else touches them.

**Backend** (under `backend/app/modules/onboarding/`)

- `api/engagement_router.py` — contacts and activity routes (yours since L2-01)
- `api/follow_up_router.py` — **new**, follow-ups and completions
- `api/schemas/engagement.py`
- `api/schemas/follow_up.py` — **new**
- `application/exporter_contact_activity_service.py`
- `application/conversation_service.py` — **new**, the conversation gauge
- `application/follow_up_service.py` — **new**
- `domain/entities/engagement_enums.py` — put `ExporterConversation` here, **not** in `exporter_enums.py` (that file holds Dev 2's company values)
- `domain/entities/exporter_contact.py`, `domain/entities/exporter_activity.py`
- `domain/entities/follow_up_completion.py` — **new**, append-only
- `domain/engagement_views.py`
- `infrastructure/repositories/exporter_contact_repository.py`, `exporter_activity_repository.py`
- `infrastructure/repositories/follow_up_completion_repository.py` — **new**
- `migrations/onboarding_0016_engagement.py` — **new**, see §3
- `sample_data_engagement.py` — **new**, called from the seam commit's hook
- tests: any new file whose name starts `test_l3a_`, under `tests/unit/` and `tests/integration/`

**Frontend** (under `frontend/src/modules/onboarding/`)

- `pages/panels/ConversationPanel.tsx`
- `pages/FollowUpsPage.tsx` + `FollowUpsPage.test.tsx` — **new**
- `api/engagement.ts`, `api/follow-ups.ts` (**new**)
- `hooks/engagement.ts`, `hooks/follow-ups.ts` (**new**)
- `components/ConversationGaugeControl.tsx` — **new**, if you want the control separate

You do **not** edit `pages/ExporterDetailPage.tsx`. The shell already mounts
`ConversationPanel`; if you need a new query, call it inside your panel. Read that
page's docstring first — it explains why the existing three queries live in the
shell, and its test asserts the timing.

---

## 3. Your migration: 0016, and nothing else

You own exactly one migration, `onboarding_0016_engagement`. It does four things:

1. Creates the enum `onboarding.exporter_conversation_enum` with the six
   architecture §3.3 values: `NOT_CONTACTED`, `REACHING_OUT`, `SPOKE_TO_THEM`,
   `INTERESTED`, `NOT_NOW`, `READY_NOW`.
2. Adds `exporter_profile.conversation`, `NOT NULL DEFAULT 'NOT_CONTACTED'`. This is
   the field `docs/contracts/company-record.md` §2.4 reserves for you — the row that
   names Developer 3 as its owner. **It is a column on Dev 2's table, so this
   migration needs Dev 2's review** before merge (§8.1 shared-file rule). Nothing
   else in that table is yours.
3. Adds the NOT_NOW check-back date column, wherever your own contract puts it.
4. Creates `onboarding.follow_up_completion` — append-only, with real FKs to
   `exporter_activity.id` and `exporter_profile.customer_id`, protected by the
   existing `public.prevent_mutation()` trigger the way every other locked table in
   this repo is.

**Parent revision.** The current head is `onboarding_0020_retire_lifecycle` (0014,
0017 and 0020 have landed; Dev 4's 0015 has not). Numbers are labels, not order —
the register says so explicitly — so set:

```python
down_revision = "onboarding_0020_retire_lifecycle"
```

3B's 0018 then parents onto your 0016, and 0019 onto 0018. If 3B is somehow ready to
merge first, **3B re-parents, not you**: the rule is that only the later-merging
developer edits a `down_revision`, and whoever does it tells Dev 1 to update
`docs/contracts/migration-register.md`.

Register rules that will actually bite you:

- **Revision id ≤ 32 characters.** `onboarding_0016_engagement` is 26. Fine.
- **Never `ALTER TYPE … ADD VALUE` inside an autocommit block.** Create the enum in
  the ordinary transactional migration, as `onboarding_0012_risk_critical` does.
  This has broken the repository before.
- **One head**, before and after.
- **Every new constraint gets a direct-SQL violation test** that bypasses the ORM
  with `psycopg2`, so it proves the *database* refuses it. That is how you close
  L3-02 and how you prove `follow_up_completion` is really locked.
- Write the downgrade; if it is lossy, say so in the docstring.

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

## 4. The two seams between you and 3B — THE SHARED AGREEMENT

There are exactly two places where your work and 3B's touch. Both are one-way
function calls across a named boundary. Neither of you reaches into the other's
tables, enums or services by any other route.

### Seam S1 — opening a deal sets the conversation to READY_NOW

Architecture §3.3: "READY_NOW … The screen offers to open a deal; opening a deal
also sets this." So 3B's `open_deal` has to move **your** gauge.

- **You publish**, in `application/conversation_service.py`:

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

- **3B calls it** from `DealService.open_deal`, in the same session and transaction,
  passing `deal_id` so your history row carries it (history contract §2: `deal_id`
  is set when another dimension's change is about a specific deal).
- **3B never writes `exporter_profile.conversation`** and never imports your enum to
  compare against it. `company-record.md` §2.4 forbids assigning to another
  developer's gauge field, "including just to keep it in step".
- **Merge order:** your L3-03 merges before 3B's L3-05. This costs 3B nothing —
  their prompt starts them on storage (L3-07/L3-08), which does not depend on you,
  so by the time they reach the deal record your service exists. If they arrive
  first they land L3-05 without the call and add it in a one-function follow-up
  commit; they do not stub your service.

### Seam S2 — the "open a deal" prompt on the Conversation panel

When conversation is `READY_NOW` your panel offers to open a deal.

- **3B publishes** the request function and hook for creating a deal in
  `api/deals.ts` / `hooks/deals.ts`.
- **You import it through the barrel** (`../../api`, `../../hooks`), never from 3B's
  file directly, and you never define your own deal request function or deal type.
- **Merge order:** 3B's deal route merges before your prompt. Ship L3-11a's panel
  without the button if 3B is not there yet, and add the button in a small commit.
  A button calling a route that does not exist is a broken screen, and this project's
  stated principle is never to show navigation to something that renders nothing
  (see `layout/Sidebar.tsx`'s docstring).

**That is the whole interface.** If you find you need a third seam, stop and agree
it with 3B in writing before writing code (§7.5: "Contracts change only with the
agreement of the owner and every user of that contract").

---

## 5. Step 0 — the seam commit — THE SHARED AGREEMENT

A handful of files are shared by every developer: the module's exception list, its
entity/repository/service indexes, the router index, the route-authorisation tables,
and the frontend barrels. If you and 3B both append to them on separate branches you
will conflict in the same hunk, every time.

So **you (3A) land one small commit first — nothing but seams, no behaviour — and 3B
reviews it.** Half a day at most. After it, neither of you edits a shared file again.

**What it contains:**

1. **Empty routers**, mounted once and never re-mounted:
   - `api/follow_up_router.py` (yours), `api/deal_router.py` and
     `api/document_router.py` (3B's) — each just `router = APIRouter(...)` with a
     docstring naming its owner, and no routes.
   - `api/router.py` gains all three `include_router(...)` lines in this one commit,
     beside the existing engagement/screening/qualification includes and in the same
     comment style. **Neither of you touches `api/router.py` again.**
   - A router with no routes adds nothing to the OpenAPI document, so
     `frontend/openapi.json` does not move and
     `backend/tests/contract/test_openapi_artifact_is_current.py` stays green. Run
     `python -m pytest backend/tests/contract -q` in this commit to prove it.
2. **Empty schema modules**: `api/schemas/follow_up.py`, `api/schemas/deal.py`,
   `api/schemas/document.py` — docstring and owner, nothing else.
3. **Two anchor blocks, separated by at least one line of real content**, in each of
   the shared files below, so your additions and 3B's land in different hunks:

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
   `Follow-ups` row with `status: 'soon'` — you later flip that one word; 3B adds two
   new rows under their anchor. Different lines, no conflict.
4. **Frontend stubs and barrel lines**: `api/follow-ups.ts`, `api/deals.ts`,
   `api/documents.ts`, `hooks/follow-ups.ts`, `hooks/deals.ts`, `hooks/documents.ts`
   — each an empty module with its owner in the docstring — plus the matching
   `export * from './…'` lines added to `api/index.ts` and `hooks/index.ts` in this
   one commit. Neither of you edits those two barrels again.
5. **Sample-data hooks**: `sample_data_engagement.py` (yours) and
   `sample_data_deals.py` (3B's), each exposing one async no-op seeder, plus the two
   call sites added to `backend/app/modules/onboarding/sample_data.py`. That file is
   Dev 2's, so **Dev 2 reviews this part**. Neither of you edits `sample_data.py`
   again.

**What it must not contain:** a single route, enum value, column or rendered pixel.
The suite must be at baseline and `frontend/openapi.json` byte-identical when it
merges.

---

## 6. Rules you will otherwise get wrong

### 6.1 L3-02 is smaller than it reads

The plan lists "contacts and activities must point at a real company" as open work,
but `onboarding_0014_company_record` already created
`fk_exporter_contact_customer_id` and `fk_exporter_activity_customer_id` (its
`_LINKED` tuple, step 4). What is actually left:

- The ORM entities still say the opposite. `domain/entities/exporter_contact.py`
  lines 3-4 and `exporter_activity.py` lines 9-10 both document `customer_id` as "a
  bare, indexed UUID with no formal FK". That is now false. Declare the `ForeignKey`
  on the `mapped_column` and rewrite those docstrings.
- Add the direct-SQL test that a `customer_id` pointing at no company is refused by
  the database, and a service-level test that the API returns a clean error rather
  than a 500.
- Do **not** re-add the constraint in 0016. Check first — read 0014, or
  `\d onboarding.exporter_contact` in psql.

### 6.2 Activities are locked; never update one

`exporter_activity` is append-only, enforced by a database trigger. Completing a
follow-up therefore **inserts a `follow_up_completion` row**; it does not set a
`completed_at` on the activity. A "due and overdue" list is a query joining
activities that have due dates against their completions, not a status column.
§9.3's "Watch out for" says this first because it is the mistake this design invites.

### 6.3 Every gauge move writes history, in the same transaction

Use Dev 1's `HistoryService.record(...)` in `application/history_service.py`. For
you:

- `dimension="conversation"` — fixed by `docs/contracts/history-row.md` §2; do not
  invent a dimension string
- `event_type` follows the `<dimension>_initial` / `<dimension>_transition` pair:
  `conversation_initial` when a default is recorded at creation,
  `conversation_transition` for a move
- `source="conversation_service.set_conversation"` — dotted, the code path
- `actor_id` from the login session, **never** from the request body (§7.5)
- `reason` where your own contract requires one
- `to_value` / `from_value` are strings; validate against your enum before writing

`record()` flushes and does not commit. Update `exporter_profile.conversation` and
write the row in **one** transaction — architecture §3.8: "Developers must update
both in the same transaction."

### 6.4 The server serves the allowed moves

§7.5: "The frontend fetches the allowed journey, gauge and deal moves for the current
user instead of keeping hand-copied tables." Any value may follow any other on this
gauge — it is a judgement, per §3.3 — but the *roles* are a rule: OPERATIONS,
COMPLIANCE and ADMIN may set it; DEVELOPER and API_USER never. Expose the allowed
moves from the API; do not hard-code a list in `ConversationPanel.tsx`.

### 6.5 The conversation gauge starts at PROSPECT

Assumption A4: "The conversation gauge applies from PROSPECT onward." A LEAD has the
column (defaulting to `NOT_CONTACTED`) but the panel does not offer to move it and
the service refuses a move on a LEAD. Decide the error code, put it in your contract,
and test the refusal.

### 6.6 Every new route needs a role declaration, a test row and a documented 403

§7.5 and §7.7. For each route you add:

- roles via `require_role(...)` in `api/follow_up_router.py`, matching the §3.7 matrix
- a `403` entry in the route's `responses={...}` description
- one row in `GATED_ROUTES` in
  `backend/tests/contract/test_route_authorization_coverage.py`, under **your** anchor
  from §5 — an unclassified route fails that test by construction
- a refusal test (§7.7: "at least one test for each refusal")

Follow-ups are visible to the whole team (decision D2), so the list route is a
reader route, not a per-owner one.

### 6.7 Generated API artifacts: regenerate, never merge

`frontend/openapi.json` and `frontend/src/lib/api/schema.ts` are generated. You and
3B will both change them, and a three-way merge of generated JSON is worthless. After
every rebase onto the integration branch:

```bash
git checkout <integration-branch> -- frontend/openapi.json frontend/src/lib/api/schema.ts
cd frontend && pnpm generate:api
```

Dev 1 does the authoritative regeneration at each milestone (L1-14): the contract test
tells you it is stale, but a person still runs the command.

### 6.8 The module rule

All connecting code lives in `onboarding`. You edit no file in `kyb`, `cases`,
`customers` or `compliance` (architecture §2.5). The one documented exception is
Dev 1's, not yours.

### 6.9 Do not touch the legacy path

`onboarding_request`, `onboarding_event`, the Temporal workflow and the 18-state
machine are out of scope and must never be built on (§2.4, decision D11). If a
follow-up seems to want `onboarding_event`, it wants `exporter_lifecycle_history`.

---

## 7. Definition of done (plan §7.7, unchanged)

- Behaviour matches architecture §3.3 and your own engagement contract; roles
  enforced on the **server**.
- History rows written for every change; locked tables stay locked.
- Unit tests for the rules, route tests for the roles, at least one test for each
  refusal, and a direct-SQL test for each new constraint.
- Screens updated with loading, empty and error states.
- Backend suite at baseline — **only** the 27 known payments/FX and
  compliance-screening failures. Anything else blocks the merge.
- `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build` all clean; no new
  import-rule violations (`lint-imports`).
- `alembic heads` prints one revision.

---

## 8. Reporting

Keep a short running note at `docs/dev3a-progress.md`: task, state, anything that
contradicts the architecture document or a contract, and any decision you had to
make. When you finish, add:

- the engagement contract's final values and rules, and who has acknowledged it
- whether 0016 needed anything the register did not anticipate
- the state of seams S1 and S2 — service merged, button shipped or still pending
- anything you left for 3B, Dev 2 or Dev 4, named by task ID

If you finish ahead of 3B, the plan's own rebalancing valve applies (§7.1 and §10:
hand screens over early rather than late). Offer to take the **document list screen**
from L3-11b — read-only, in its own file — with 3B reviewing. Do not take a backend
task from them; the migration chain is the one thing that must stay in one pair of
hands per number.
