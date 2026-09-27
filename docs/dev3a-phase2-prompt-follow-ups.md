# Prompt — Developer 3A, **Phase 2**: follow-up completion and the Follow-ups screen

**Source of truth:** `docs/Exporter-CRM-Architecture-and-Plan.pdf` v1.0 (25 September 2026),
§9.3 "Developer 3: Conversations, deals and paperwork", plus the shared rules in
§7.5, §7.7 and §8.

**Parent prompt:** `docs/dev3a-prompt-conversation-and-followups.md`. That file is the
whole of 3A's work, written for one run. It is being run in two phases. **You are
Phase 2.** Phase 1 has the mirror prompt in
`docs/dev3a-phase1-prompt-conversation-gauge.md`; it lands the seam commit, migration
0016 and the conversation gauge. Your counterpart on the other half of §9.3 is 3B
(`docs/dev3b-prompt-deals-storage-and-documents.md`) — **nothing in the 3A/3B
agreement changes because of this phase split**, and you do not edit their prompt.

**Read before you write a line of code**, in this order:

1. `docs/contracts/engagement.md` — Phase 1 published it and it fixes your completion
   shape, your check-back column, your error codes and your roles. It outranks this
   prompt where the two disagree; if it is silent, §6.4 says what to do.
2. `docs/dev3a-phase1-progress.md` — Phase 1's closing block is your starting brief.
3. `migrations/onboarding_0016_engagement.py` — your table already exists. Read the
   DDL rather than assuming it.

Two sections here are agreements repeated, from the other side, in another prompt:

- **THE PHASE AGREEMENT** (§6) — mirrored in Phase 1's prompt §6. If you change one,
  change both.
- **THE SHARED AGREEMENT** (§5) — mirrored in 3B's prompt §5 and Phase 1's §5. Phase 1
  has already executed it; for you it is a list of files you must **not** touch.

---

## 1. Your mission

What we owe the exporter next, and whether we did it. A follow-up is an activity with
a due date; completing one is a **new, locked record**, never an edit. The whole team
sees the same list (decision D2).

The gauge, contacts, activities and migration 0016 are Phase 1's and are done. Deals,
buyers, files and storage are 3B's. Yours is L3-04's second half and the screen that
shows it.

| ID | Task | Size | Needs | Done when |
|---|---|---|---|---|
| L3-04b | Follow-up completion as a new locked record; due and overdue read model; the Follow-ups list for the whole team | M | Phase 1's 0016 and `engagement.md` | Due and overdue lists correct; completing a follow-up leaves a record and never updates the activity |
| L3-11a-ii | Screens: the Follow-ups page, and flipping its sidebar row from `soon` | M | L3-04b | Usable end to end on sample data, with loading, empty and error states |
| S2 | The "open a deal" button in `components/OpenDealPrompt.tsx`, **only if Phase 1 left it open and 3B's deal route has merged** | XS | 3B's L3-05 | Button present, calling 3B's hook through the barrel; otherwise explicitly recorded as still pending |

**Order:** L3-04b → L3-11a-ii → S2. Check the S2 file's state early (Phase 1's
progress note says), because if 3B is not there yet, S2 drops out of your scope
entirely and stays a one-file commit for whoever gets there first.

**You write no migration.** §6.2 explains why; the short version is that your table
is already in 0016 and 3B's chain is parented onto it.

---

## 2. What you own exclusively in Phase 2

You may create and edit these freely. Nobody else touches them — not 3B, not Phase 1.
Several exist already as Step 0 stubs: an empty module with an owner docstring. Fill
them; do not re-create them.

**Backend** (under `backend/app/modules/onboarding/`)

- `api/follow_up_router.py` — *stub from Step 0*; follow-ups and completions
- `api/schemas/follow_up.py` — *stub from Step 0*
- `application/follow_up_service.py` — **new**
- `domain/entities/follow_up_completion.py` — **new**, append-only; the ORM mapping of
  the table 0016 created. Map what is there; if the ORM and the DDL disagree, the DDL
  wins and the disagreement is a contract note, not a migration.
- `domain/follow_up_views.py` — **new**, your read models (the due/overdue row)
- `infrastructure/repositories/follow_up_completion_repository.py` — **new**. Your
  due/overdue query, which joins `exporter_activity` to `follow_up_completion`, lives
  **here** — see §6.3 on why it does not go in the activity repository.
- `sample_data_follow_ups.py` — *stub from Step 0*; seed completed and outstanding
  follow-ups against the companies Phase 1's seeder creates
- tests: any new file named `test_l3a_follow_up_*.py`, under `tests/unit/` and
  `tests/integration/`

**Frontend** (under `frontend/src/modules/onboarding/`)

- `pages/FollowUpsPage.tsx` + `FollowUpsPage.test.tsx` — **new**
- `api/follow-ups.ts`, `hooks/follow-ups.ts` — *stubs from Step 0*
- `components/OpenDealPrompt.tsx` — Phase 1's file, **handed to you** for the S2
  button and nothing else. If you are not doing S2, do not open it.

**Shared files you may touch, and only in these two ways** (§5 otherwise forbids it):

- append under the **`3A·2`** sub-anchor in the files listed in §5.3
- flip the existing `Follow-ups` row in `frontend/src/layout/Sidebar.tsx` from
  `status: 'soon'` — **one word on one line.** 3B's rows are elsewhere in the file and
  Phase 1 added none.

You do **not** edit `pages/ExporterDetailPage.tsx`, `pages/panels/ConversationPanel.tsx`,
`api/router.py`, `api/index.ts`, `hooks/index.ts` or `sample_data.py`. Every line you
would have needed in them was written in Step 0.

---

## 3. You write no migration

Your table exists:

```
onboarding.follow_up_completion   -- created by onboarding_0016_engagement (Phase 1)
```

append-only, with real FKs to `exporter_activity.id` and
`exporter_profile.customer_id`, protected by `public.prevent_mutation()`, and already
covered by Phase 1's direct-SQL lock test. Your job is the entity, the repository, the
service, the routes and the screen — **not the DDL**.

The head must not move. Before and after your work:

```bash
cd backend
alembic heads          # exactly one, the same revision Phase 1 left
alembic upgrade head
python -m pytest -q --no-cov -p no:cacheprovider
```

If you conclude the table is genuinely wrong — a missing column you cannot work
around, a constraint that refuses a legitimate write — **stop and go back to §6.4**.
That is a contract change and a Phase-1-owned migration amendment, agreed with 3B
because their `down_revision` points at it, and with Dev 2 because the check-back
column sits on their table. Do not add `onboarding_0021_*` to work around it; a new
3A migration after 3B's 0018 is exactly the chain damage the split was designed to
avoid.

The one thing you still owe the database: **every new constraint gets a direct-SQL
violation test**. You add no constraint, so what you owe instead is the *service-level*
proof that the lock holds — an attempt to update or delete a completion through your
repository raises, and the API turns it into a clean error rather than a 500.

---

## 4. Your two seams

### 4.1 With Phase 1 — read-only, four things

Listed in §6.4. In code they amount to: import `ExporterConversation` from
`domain/entities/engagement_enums.py` if you need it, read
`exporter_profile.<check-back column>` in your due/overdue query, and write neither.
A check-back date moves only through `ConversationService`, exactly as 3B's deal
service may not write `conversation`.

### 4.2 With 3B — seam S2, one file, only if it is still open

Unchanged from THE SHARED AGREEMENT. When the gauge reads `READY_NOW` the Conversation
panel offers to open a deal. Phase 1 already mounted `components/OpenDealPrompt.tsx`
from the panel; in Phase 1 it renders the note with no button.

If 3B's deal route has merged and Phase 1 did not already do it, put the button in
that file:

- **3B publishes** the request function and hook in `api/deals.ts` / `hooks/deals.ts`.
- **You import them through the barrel** (`../../api`, `../../hooks`), never from 3B's
  file directly, and you never define your own deal request function or deal type.
- **Merge order:** 3B's deal route merges before the button. Never ship a button
  calling a route that does not exist — this project's stated principle is never to
  show navigation to something that renders nothing (see `layout/Sidebar.tsx`'s
  docstring).
- `ConversationPanel.tsx` stays closed. The button changes one file.

**That is the whole interface.** If you find you need a third seam with 3B, stop and
agree it in writing before writing code (§7.5: "Contracts change only with the
agreement of the owner and every user of that contract").

---

## 5. Step 0 — the seam commit — THE SHARED AGREEMENT (already landed)

Phase 1 executed this before either of you started. It is reproduced here as the list
of files that are now **closed to you**, because the whole point of the commit was
that nobody edits them twice.

1. **Empty routers** mounted once in `api/router.py`: `follow_up_router.py` (yours to
   fill, already included), `deal_router.py`, `document_router.py`. **You never touch
   `api/router.py`** — your routes appear simply by being added to your own router.
2. **Empty schema modules**: `api/schemas/follow_up.py` (yours to fill), `deal.py`,
   `document.py`.
3. **Anchor blocks** in the nine Dev 1-owned shared files below. The 3A block is cut
   as two sub-anchors, separated by a line of real content, so Phase 1's additions and
   yours land in different hunks. **You append under `3A·2` only:**

   ```
   # ── 3A·1 Conversation gauge (L3-02, L3-03) — Phase 1 appends here ──

   # ── 3A·2 Follow-ups (L3-04) — Phase 2 appends here ──
   ```

   | File | Owner per §8.1 | What you add |
   |---|---|---|
   | `onboarding/exceptions.py` | Dev 1 | your follow-up exceptions |
   | `domain/entities/__init__.py` | Dev 1 | `FollowUpCompletion` |
   | `infrastructure/repositories/__init__.py` | Dev 1 | your repository |
   | `application/__init__.py` | Dev 1 | `FollowUpService` |
   | `backend/tests/contract/test_route_authorization_coverage.py` (`GATED_ROUTES`) | Dev 1 | one row per route |
   | `backend/app/modules/onboarding/tests/integration/test_route_authorization.py` | Dev 1 | your route cases |
   | `frontend/src/modules/onboarding/types.ts` | Dev 1 | follow-up types |
   | `frontend/src/modules/onboarding/routes.tsx` | Dev 1 | the `/follow-ups` route |
   | `frontend/src/layout/Sidebar.tsx` | Dev 1 | the one-word `status: 'soon'` flip, existing row |

   Dev 1 reviewed the anchors once, in Step 0; appending under your own anchor does
   not re-open that review, but follow whatever the repo's normal review rule is for
   additions to an owner's file.
4. **Frontend stubs and barrel lines**: `api/follow-ups.ts` and `hooks/follow-ups.ts`
   exist and are already exported from `api/index.ts` and `hooks/index.ts`. **Fill the
   stubs; do not touch the two barrels.**
5. **Sample-data hooks**: `sample_data_follow_ups.py` exists as an async no-op and is
   already called from `backend/app/modules/onboarding/sample_data.py`, which is Dev
   2's file. **Fill the seeder; do not touch `sample_data.py`.**

If any of the five is missing when you start, Step 0 did not land as agreed. Say so in
your progress note and get it fixed in Phase 1's branch rather than patching a shared
file yourself.

---

## 6. The boundary between Phase 1 and Phase 2 — THE PHASE AGREEMENT

*Mirrored, from the other side, in `docs/dev3a-phase1-prompt-conversation-gauge.md`
§6. Same files, same names, same merge order. If you change one, change both.*

### 6.1 The split

| | Phase 1 | Phase 2 (this prompt) |
|---|---|---|
| Tasks | Step 0, L3-01a, L3-02, L3-03, L3-04a, L3-11a-i | L3-04b, L3-11a-ii, and the S2 button if it is still open |
| Slice | The gauge: values, history, roles, allowed moves, the check-back date, the panel control | Follow-ups: the completion record, the due/overdue read model, the Follow-ups page |
| Migrations | 0016, all of it | none |
| Engagement contract | writes `docs/contracts/engagement.md` | appends to it only |

Each phase is shippable on its own. Phase 1 merged gives an operator a working gauge
and gives 3B seam S1; Phase 2 merged gives the team the Follow-ups screen.

### 6.2 Phase 2 writes no migration

0016 creates `follow_up_completion` and the check-back column, even though Phase 1
writes no code against the first. Reasons, in order of how much the alternative would
hurt:

- 3B's 0018 already declares `down_revision = "onboarding_0016_engagement"`. A second
  3A migration landing after 0018 would have to parent onto 0019, or force 3B to
  re-parent — and the 3A/3B agreement puts re-parenting on the later merger, which by
  then is 3B, re-parenting for a reason that is purely internal to 3A.
- §9.3's own closing rule: the migration chain "must stay in one pair of hands per
  number".
- The table's shape is fixed by L3-01a, which Phase 1 publishes anyway.

So your first act is `alembic upgrade head` against a database that already has your
table, and your DoD includes `alembic heads` printing the same single revision Phase 1
left.

### 6.3 Disjoint files

Every file either phase writes is named in exactly one of the two prompts' §2. There
is no file both phases edit — not one. In particular:

- `ConversationPanel.tsx` is Phase 1's and was finished when Phase 1 merged. Your only
  business on that screen is `components/OpenDealPrompt.tsx`, handed over whole.
- `engagement_router.py`, `schemas/engagement.py`, `engagement_views.py`,
  `exporter_activity_repository.py` and `exporter_contact_repository.py` are Phase
  1's. **You add no method to any of them.** Your due/overdue query joins activities
  to completions from inside your own `follow_up_completion_repository.py`, and your
  read models live in your own `domain/follow_up_views.py`. A read repository that
  selects across two tables is ordinary; reaching into another owner's repository for
  one method is what creates the conflict.
- `follow_up_router.py`, `schemas/follow_up.py`, `follow_up_service.py`,
  `follow_up_completion.py`, `follow_up_completion_repository.py`,
  `follow_up_views.py`, `sample_data_follow_ups.py`, `api/follow-ups.ts`,
  `hooks/follow-ups.ts`, `FollowUpsPage.tsx` are yours. Phase 1 created the empty ones
  in Step 0 and never opened them again.
- Shared files: Phase 1 appends under `3A·1`, you under `3A·2`, plus the one-word
  sidebar flip, which is yours alone.
- Tests: Phase 1's files are `test_l3a_conversation_*` and `test_l3a_contact_*`; yours
  are `test_l3a_follow_up_*`. All still match the `test_l3a_` prefix §9.3 reserves for
  3A, and no filename collides.
- Progress notes: `docs/dev3a-phase1-progress.md` and `docs/dev3a-phase2-progress.md`.

Because the sets are disjoint and the anchors are pre-cut, the two phases can even run
concurrently once Step 0 has merged. They are *ordered* only by §6.4.

### 6.4 Merge order, and what you are owed

You can start as soon as **Step 0 and 0016** are merged, and you need nothing else from
Phase 1 at compile time. What you read, and must find true:

1. `docs/contracts/engagement.md` — the completion shape, the check-back column name,
   the error-code list, and which roles may complete a follow-up.
2. The `follow_up_completion` table as 0016 built it, with its lock trigger and FKs
   proven by Phase 1's direct-SQL test.
3. `exporter_profile.<check-back column>` — read-only for you. **You never write it**,
   exactly as 3B never writes `conversation`. A check-back date moves only through
   `ConversationService`.
4. `ExporterConversation` in `engagement_enums.py`, if your list renders a check-back
   row.

If you need a fifth thing, that is a contract change: amend `engagement.md` (appending,
with the date and the reason), re-acknowledge with 3B, Dev 2 and Dev 4, and record it
in both progress notes. If the change reaches the schema, it is a Phase-1-owned
amendment to 0016 — not a new migration of yours (§3).

---

## 7. Rules you will otherwise get wrong

### 7.1 Activities are locked; never update one

This is the one §9.3 lists first, and it is aimed at your task specifically.
`exporter_activity` is append-only, enforced by a database trigger. Completing a
follow-up therefore **inserts a `follow_up_completion` row**; it does not set a
`completed_at` on the activity. A "due and overdue" list is a query joining activities
that have due dates against their completions, **not** a status column.

Concretely, for the read model:

- outstanding = activity has a `due_at` and has **no** completion row
- overdue = outstanding and `due_at` is in the past
- done = a completion row exists; show who completed it and when, from the completion,
  never from the activity
- a second completion for the same activity is a refusal, not an upsert — decide the
  error code (or take it from `engagement.md`) and test it

### 7.2 Follow-ups are the whole team's

Decision D2: follow-ups are visible to everyone, so the list route is a **reader
route**, not a per-owner one. Do not filter by `actor_id` by default and do not invent
an ownership rule the contract does not have. Filtering *by* a person is a query
parameter, not a permission.

### 7.3 Every new route needs a role declaration, a test row and a documented 403

§7.5 and §7.7. For each route you add:

- roles via `require_role(...)` in `api/follow_up_router.py`, matching the §3.7 matrix
  and `engagement.md`: reads for the staff roles, completion for whoever the contract
  names; DEVELOPER and API_USER write nothing
- a `403` entry in the route's `responses={...}` description
- one row in `GATED_ROUTES` in
  `backend/tests/contract/test_route_authorization_coverage.py`, under the **`3A·2`**
  sub-anchor — an unclassified route fails that test by construction
- a refusal test (§7.7: "at least one test for each refusal")

### 7.4 History, if your contract asks for it

A completion is its own record, so it does not automatically need a history row; the
gauge is what `dimension="conversation"` is for, and that is Phase 1's. **Do not invent
a `follow_up` dimension** — `docs/contracts/history-row.md` §2 fixes the list. If
`engagement.md` says a completion writes history, use the dimension it names, take
`actor_id` from the login session and never from the request body (§7.5), and write the
row in the **same transaction** as the completion (architecture §3.8). `record()`
flushes and does not commit.

### 7.5 Generated API artifacts: regenerate, never merge

`frontend/openapi.json` and `frontend/src/lib/api/schema.ts` are generated. You, Phase
1 and 3B all change them, and a three-way merge of generated JSON is worthless. After
every rebase onto the integration branch:

```bash
git checkout <integration-branch> -- frontend/openapi.json frontend/src/lib/api/schema.ts
cd frontend && pnpm generate:api
```

Dev 1 does the authoritative regeneration at each milestone (L1-14): the contract test
tells you it is stale, but a person still runs the command.

### 7.6 The screen shows three states, and the sidebar follows the screen

Loading, empty and error are part of done, not polish. Flip the sidebar's
`status: 'soon'` in the **same commit** that makes `/follow-ups` render something real
— not before (dead navigation) and not in a separate commit (a shipped page nobody can
reach).

### 7.7 The module rule

All connecting code lives in `onboarding`. You edit no file in `kyb`, `cases`,
`customers` or `compliance` (architecture §2.5). The one documented exception is
Dev 1's, not yours.

### 7.8 Do not touch the legacy path

`onboarding_request`, `onboarding_event`, the Temporal workflow and the 18-state
machine are out of scope and must never be built on (§2.4, decision D11). If a
follow-up seems to want `onboarding_event`, it wants `exporter_lifecycle_history`.

---

## 8. Definition of done (plan §7.7, unchanged)

- Behaviour matches architecture §3.3 and the engagement contract; roles enforced on
  the **server**.
- History rows written for every change the contract requires; locked tables stay
  locked — completing a follow-up inserts, and an attempted update or delete of a
  completion or an activity is refused and tested.
- Unit tests for the rules, route tests for the roles, at least one test for each
  refusal. You add no constraint, so in place of a new direct-SQL test you prove the
  existing lock refuses your service (§3).
- Screens updated with loading, empty and error states; `/follow-ups` reachable from
  the sidebar.
- Backend suite at baseline — **only** the 27 known payments/FX and
  compliance-screening failures. Anything else blocks the merge.
- `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build` all clean; no new
  import-rule violations (`lint-imports`).
- `alembic heads` prints **one** revision, and the **same** one Phase 1 left — you
  added no migration.
- No file outside §2 changed, and inside the shared files nothing outside the `3A·2`
  anchor and the one sidebar word.

---

## 9. Reporting

Keep a short running note at `docs/dev3a-phase2-progress.md`: task, state, anything
that contradicts the architecture document or a contract, and any decision you had to
make. When you finish, add:

- the completion record's final shape as built, and any place it differs from what
  `engagement.md` said — with the amendment, if you made one, and who re-acknowledged
- the due/overdue rules as implemented, including how check-back dates appear in the
  list
- the roles on each route, and the refusal tests that cover them
- the state of seam S2 — button shipped, or still pending on 3B's L3-05, named as such
- anything you left for 3B, Dev 2 or Dev 4, named by task ID

Together with `docs/dev3a-phase1-progress.md`, this note is 3A's full report against
the parent prompt's §8. If the team wants one file, concatenate the two at the end
rather than editing Phase 1's.

If you finish ahead of 3B, the plan's own rebalancing valve applies (§7.1 and §10:
hand screens over early rather than late). Offer to take the **document list screen**
from L3-11b — read-only, in its own file — with 3B reviewing. Do not take a backend
task from them; the migration chain is the one thing that must stay in one pair of
hands per number.
