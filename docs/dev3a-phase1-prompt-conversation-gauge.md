# Prompt — Developer 3A, **Phase 1**: the seams, migration 0016 and the conversation gauge

**Source of truth:** `docs/Exporter-CRM-Architecture-and-Plan.pdf` v1.0 (25 September 2026),
§9.3 "Developer 3: Conversations, deals and paperwork", plus the shared rules in
§7.5, §7.7 and §8.

**Parent prompt:** `docs/dev3a-prompt-conversation-and-followups.md`. That file is the
whole of 3A's work, written for one run. It is being run in two phases. **You are
Phase 1.** Phase 2 has the mirror prompt in `docs/dev3a-phase2-prompt-follow-ups.md`.
Your counterpart on the other half of §9.3 is 3B, whose prompt is
`docs/dev3b-prompt-deals-storage-and-documents.md` — **nothing in the 3A/3B agreement
changes because of this phase split.** 3B's copy of THE SHARED AGREEMENT is still
true word for word, and you do not edit their prompt.

Read this whole file before writing code. Two sections are marked as agreements and
are repeated, from the other side, in another prompt:

- **THE SHARED AGREEMENT** (§5) — mirrored in 3B's prompt §5. Do not change it.
- **THE PHASE AGREEMENT** (§6) — mirrored in Phase 2's prompt §6. If you change one,
  change both.

---

## 1. Your mission

Get the conversation gauge onto the company, truthfully and with history, and lay
every seam the rest of §9.3 hangs off. When you are done, 3B is unblocked (seam S1
exists), Phase 2 is unblocked (its table exists and its anchors are cut), and an
operator can move a company from `NOT_CONTACTED` to `READY_NOW` in the browser.

Contacts, activities and the gauge are yours. Follow-up completion, the Follow-ups
screen, and everything about deals, buyers, files and storage are not.

| ID | Task | Size | Needs | Done when |
|---|---|---|---|---|
| **Step 0** | The seam commit (§5) — empty routers, empty schema modules, anchor blocks, frontend stubs and barrel lines, sample-data hooks | S | — | Merged, reviewed by Dev 1 (nine shared files) and Dev 2 (`sample_data.py`); suite at baseline; `frontend/openapi.json` byte-identical |
| L3-01a | Publish the **engagement contract**: conversation values, who may set them, which moves need a reason, the NOT_NOW check-back rule, **and the follow-up/completion shape Phase 2 will build to** | S | — | `docs/contracts/engagement.md` merged; 3B, Dev 2 and Dev 4 have each confirmed they read it |
| L3-02 | Contacts and activities must point at a real company (§9.3, E16) | S | already done in the DB by 0014 — see §7.1 | Ghost-company writes refused, with a direct-SQL test |
| L3-03 | Conversation gauge on the company, with history (assumption A4); migration 0016 | M | L3-02, L1-11 | Values and rules per architecture §3.3; every change writes a `conversation` history row in the same transaction |
| L3-04a | The NOT_NOW check-back rule: moving to `NOT_NOW` requires a check-back date, stored on the company | S | L3-03 | Refused without a date, with a documented error code and a test |
| L3-11a-i | Screens: the Conversation panel's **gauge control and history**, and the `OpenDealPrompt` seam file | M | L3-03 | Usable end to end on sample data, with loading, empty and error states |

**Order:** Step 0 → L3-01a → L3-02 → L3-03 → L3-04a → L3-11a-i. Step 0 is first and
is half a day at most. Do not move L3-03 later: 3B's L3-05 waits on the service you
publish there (seam S1, §4.1), and Phase 2 waits on the whole of it.

Follow-up **completion** is not in this phase. You create the `follow_up_completion`
table in 0016 (§3) and then leave it alone: no entity, no repository, no service, no
route. That is Phase 2's, and §6.2 says why the table is still yours to create.

---

## 2. What you own exclusively in Phase 1

You may create and edit these freely. Nobody else touches them — not 3B, not Phase 2.

**Backend** (under `backend/app/modules/onboarding/`)

- `api/engagement_router.py` — contacts and activity routes (yours since L2-01), and **new**: the gauge routes and the allowed-moves route
- `api/schemas/engagement.py`
- `application/exporter_contact_activity_service.py`
- `application/conversation_service.py` — **new**, the conversation gauge and seam S1
- `domain/entities/engagement_enums.py` — add `ExporterConversation` here, **not** in `exporter_enums.py` (that file holds Dev 2's company values). The file already exists and holds `ExporterActivityType`.
- `domain/entities/exporter_contact.py`, `domain/entities/exporter_activity.py`
- `domain/entities/exporter_profile.py` — **only** the two columns 0016 adds (`conversation` and the check-back date). Dev 2 reviews; see §3.
- `domain/engagement_views.py`
- `infrastructure/repositories/exporter_contact_repository.py`, `exporter_activity_repository.py`
- `migrations/onboarding_0016_engagement.py` — **new**, see §3. The only migration either phase writes.
- `sample_data_engagement.py` — **new**, called from the seam commit's hook
- tests: any new file named `test_l3a_conversation_*.py` or `test_l3a_contact_*.py`, under `tests/unit/` and `tests/integration/`

**Frontend** (under `frontend/src/modules/onboarding/`)

- `pages/panels/ConversationPanel.tsx` — **written once, in this phase, and never edited again** (see §4.2)
- `components/ConversationGaugeControl.tsx` — **new**
- `components/OpenDealPrompt.tsx` — **new**, the seam-S2 file (§4.2)
- `api/engagement.ts`, `hooks/engagement.ts`

You do **not** edit `pages/ExporterDetailPage.tsx`. The shell already mounts
`ConversationPanel` and hands it `customerId`, contacts, activities and `isStaff`; if
you need a new query, call it inside your panel. Read that page's docstring and the
panel's own first — they explain why the existing three queries live in the shell and
why the panel is presentational, and the page test asserts the timing.

---

## 3. Your migration: 0016, and nothing else — in either phase

You own exactly one migration, `onboarding_0016_engagement`. **Phase 2 writes no
migration at all**, so 0016 creates Phase 2's table as well as your columns. This is
deliberate; §6.2 is the rule and the reasoning.

0016 does four things:

1. Creates the enum `onboarding.exporter_conversation_enum` with the six
   architecture §3.3 values: `NOT_CONTACTED`, `REACHING_OUT`, `SPOKE_TO_THEM`,
   `INTERESTED`, `NOT_NOW`, `READY_NOW`.
2. Adds `exporter_profile.conversation`, `NOT NULL DEFAULT 'NOT_CONTACTED'`. This is
   the field `docs/contracts/company-record.md` §2.4 reserves for you — the row that
   names Developer 3 as its owner. **It is a column on Dev 2's table, so this
   migration needs Dev 2's review** before merge (§8.1 shared-file rule). Nothing
   else in that table is yours.
3. Adds the NOT_NOW check-back date column, wherever your own contract puts it.
   Recommended, and the name Phase 2's prompt assumes:
   `exporter_profile.conversation_check_back_on`, `DATE NULL`. Whatever you choose,
   **name it in `engagement.md` before Phase 2 starts**, because Phase 2's Follow-ups
   list reads it.
4. Creates `onboarding.follow_up_completion` — append-only, with real FKs to
   `exporter_activity.id` and `exporter_profile.customer_id`, protected by the
   existing `public.prevent_mutation()` trigger the way every other locked table in
   this repo is. **Phase 2 fills this table with code; you only create it.** Its
   columns are the ones your contract's "follow-up/completion shape" (L3-01a) fixes —
   get that written before you write the DDL, because Phase 2 builds to it and
   changing it later costs a migration nobody has budgeted.

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
  L3-02, and how you prove `follow_up_completion` is really locked — **write that
  lock test here, in Phase 1, in raw SQL with no ORM entity.** It tests the
  migration, not Phase 2's code, and Phase 2 should inherit a table it already knows
  is safe.
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

Unchanged by the phase split. Both seams are Phase 1's to land; Phase 2 only replaces
the body of one file (§4.2).

### 4.1 Seam S1 — opening a deal sets the conversation to READY_NOW

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

### 4.2 Seam S2 — the "open a deal" prompt on the Conversation panel

When conversation is `READY_NOW` your panel offers to open a deal. 3B publishes the
request function and hook for creating a deal in `api/deals.ts` / `hooks/deals.ts`;
you import them **through the barrel** (`../../api`, `../../hooks`), never from 3B's
file directly, and you never define your own deal request function or deal type.

**The phase split adds one rule, invisible to 3B: the prompt lives in its own file.**
Create `components/OpenDealPrompt.tsx` in this phase and mount it from
`ConversationPanel.tsx` whenever the gauge reads `READY_NOW`. In Phase 1 it renders
the READY_NOW note **with no button** — a button calling a route that does not exist
is a broken screen, and this project's stated principle is never to show navigation
to something that renders nothing (see `layout/Sidebar.tsx`'s docstring). Whoever
lands the button later — you, once 3B's deal route merges, or Phase 2 — changes that
one file and nothing else. `ConversationPanel.tsx` is written once and closed.

**That is the whole interface with 3B.** If you find you need a third seam, stop and
agree it with 3B in writing before writing code (§7.5: "Contracts change only with the
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
   - `api/follow_up_router.py` (3A's, filled in Phase 2), `api/deal_router.py` and
     `api/document_router.py` (3B's) — each just `router = APIRouter(...)` with a
     docstring naming its owner, and no routes.
   - `api/router.py` gains all three `include_router(...)` lines in this one commit,
     beside the existing engagement/screening/qualification includes and in the same
     comment style. **Neither of you touches `api/router.py` again, and neither does
     Phase 2.**
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
   `Follow-ups` row with `status: 'soon'` — **Phase 2** flips that one word; 3B adds
   two new rows under their anchor. Different lines, no conflict.

   **Phase-split addition (§6.3), inside the 3A block only.** Cut the 3A block as
   *two* sub-anchors, again separated by a line of real content, so Phase 1 and
   Phase 2 also land in different hunks:

   ```
   # ── 3A·1 Conversation gauge (L3-02, L3-03) — Phase 1 appends here ──

   # ── 3A·2 Follow-ups (L3-04) — Phase 2 appends here ──
   ```

   3B's block is untouched, so their prompt stays true as written and
   `dev3b-prompt-deals-storage-and-documents.md` needs no edit.
4. **Frontend stubs and barrel lines**: `api/follow-ups.ts`, `api/deals.ts`,
   `api/documents.ts`, `hooks/follow-ups.ts`, `hooks/deals.ts`, `hooks/documents.ts`
   — each an empty module with its owner in the docstring — plus the matching
   `export * from './…'` lines added to `api/index.ts` and `hooks/index.ts` in this
   one commit. Neither of you edits those two barrels again, **and neither does
   Phase 2**: its `follow-ups` stubs and barrel lines are cut here.
5. **Sample-data hooks**: `sample_data_engagement.py` (Phase 1),
   `sample_data_follow_ups.py` (Phase 2) and `sample_data_deals.py` (3B's), each
   exposing one async no-op seeder, plus the three call sites added to
   `backend/app/modules/onboarding/sample_data.py`. That file is Dev 2's, so **Dev 2
   reviews this part**. Nobody edits `sample_data.py` again. (The parent prompt named
   two hooks; the third is the phase split's, and it is what keeps Phase 2 out of a
   Dev 2 file.)

**What it must not contain:** a single route, enum value, column or rendered pixel.
The suite must be at baseline and `frontend/openapi.json` byte-identical when it
merges.

---

## 6. The boundary between Phase 1 and Phase 2 — THE PHASE AGREEMENT

*Mirrored, from the other side, in `docs/dev3a-phase2-prompt-follow-ups.md` §6. Same
files, same names, same merge order. If you change one, change both.*

### 6.1 The split

| | Phase 1 (this prompt) | Phase 2 |
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
  re-parent — and the 3A/3B agreement puts re-parenting on the later merger, which
  after Phase 1 is 3B, re-parenting for a reason that is purely internal to 3A.
- §9.3's own closing rule: the migration chain "must stay in one pair of hands per
  number".
- The table's shape is fixed by L3-01a, which Phase 1 publishes anyway.

So Phase 2's first act is `alembic upgrade head` against a database that already has
its table, and its DoD includes `alembic heads` printing the same single revision
Phase 1 left.

### 6.3 Disjoint files

Every file either phase writes is named in exactly one of the two prompts' §2. There
is no file both phases edit — not one. In particular:

- `ConversationPanel.tsx` is Phase 1's and is finished when Phase 1 merges. Phase 2's
  only business on that screen is `components/OpenDealPrompt.tsx`, its own file.
- `engagement_router.py`, `schemas/engagement.py`, `engagement_views.py`,
  `exporter_activity_repository.py` and `exporter_contact_repository.py` are Phase
  1's. **Phase 2 adds no method to any of them.** Its due/overdue query joins
  activities to completions from inside its own
  `infrastructure/repositories/follow_up_completion_repository.py`, and its read
  models live in its own `domain/follow_up_views.py`.
- `follow_up_router.py`, `schemas/follow_up.py`, `follow_up_service.py`,
  `follow_up_completion.py`, `follow_up_completion_repository.py`,
  `follow_up_views.py`, `sample_data_follow_ups.py`, `api/follow-ups.ts`,
  `hooks/follow-ups.ts`, `FollowUpsPage.tsx` are Phase 2's. Phase 1 creates the empty
  ones in Step 0 and then does not open them.
- Shared files: Phase 1 appends under `3A·1`, Phase 2 under `3A·2`, plus the one-word
  sidebar flip, which is Phase 2's alone.
- Tests: Phase 1's files are `test_l3a_conversation_*` and `test_l3a_contact_*`;
  Phase 2's are `test_l3a_follow_up_*`. All still match the `test_l3a_` prefix §9.3
  reserves for 3A, and no filename collides.
- Progress notes: `docs/dev3a-phase1-progress.md` and `docs/dev3a-phase2-progress.md`.

Because the sets are disjoint and the anchors are pre-cut, the two phases can even run
concurrently once Step 0 has merged. They are *ordered* only by §6.4.

### 6.4 Merge order, and what Phase 2 is owed

Phase 2 can start as soon as **Step 0 and 0016** are merged, and needs nothing else
from you at compile time. What it reads, and must therefore find true:

1. `docs/contracts/engagement.md` — the completion shape, the check-back column name,
   the error-code list, and which roles may complete a follow-up.
2. The `follow_up_completion` table as 0016 built it, with its lock trigger and FKs
   proven by your direct-SQL test.
3. `exporter_profile.<check-back column>` — read-only for Phase 2. **Phase 2 never
   writes it**, exactly as 3B never writes `conversation`. A check-back date moves
   only through `ConversationService`.
4. `ExporterConversation` in `engagement_enums.py`, if the list needs to render a
   check-back row.

If Phase 2 finds it needs a fifth thing, that is a contract change: amend
`engagement.md`, re-acknowledge with 3B, Dev 2 and Dev 4, and record it in both
progress notes.

---

## 7. Rules you will otherwise get wrong

### 7.1 L3-02 is smaller than it reads

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

### 7.2 Activities are locked; never update one

`exporter_activity` is append-only, enforced by a database trigger. Nothing you do to
the gauge touches an activity row. The rule bites hardest in Phase 2, but it bites
here too: if a check-back date makes you want to "mark" an activity, it does not —
the check-back lives on the company, and completion is a new row in a table Phase 2
owns. §9.3's "Watch out for" says this first because it is the mistake this design
invites.

### 7.3 Every gauge move writes history, in the same transaction

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

### 7.4 The server serves the allowed moves

§7.5: "The frontend fetches the allowed journey, gauge and deal moves for the current
user instead of keeping hand-copied tables." Any value may follow any other on this
gauge — it is a judgement, per §3.3 — but the *roles* are a rule: OPERATIONS,
COMPLIANCE and ADMIN may set it; DEVELOPER and API_USER never. Expose the allowed
moves from the API; do not hard-code a list in `ConversationPanel.tsx` or
`ConversationGaugeControl.tsx`.

### 7.5 The conversation gauge starts at PROSPECT

Assumption A4: "The conversation gauge applies from PROSPECT onward." A LEAD has the
column (defaulting to `NOT_CONTACTED`) but the panel does not offer to move it and
the service refuses a move on a LEAD. Decide the error code, put it in your contract,
and test the refusal.

### 7.6 Every new route needs a role declaration, a test row and a documented 403

§7.5 and §7.7. For each route you add:

- roles via `require_role(...)` in `api/engagement_router.py`, matching the §3.7 matrix
- a `403` entry in the route's `responses={...}` description
- one row in `GATED_ROUTES` in
  `backend/tests/contract/test_route_authorization_coverage.py`, under the **`3A·1`**
  sub-anchor from §5 — an unclassified route fails that test by construction
- a refusal test (§7.7: "at least one test for each refusal")

### 7.7 Generated API artifacts: regenerate, never merge

`frontend/openapi.json` and `frontend/src/lib/api/schema.ts` are generated. You, 3B
and Phase 2 will all change them, and a three-way merge of generated JSON is
worthless. After every rebase onto the integration branch:

```bash
git checkout <integration-branch> -- frontend/openapi.json frontend/src/lib/api/schema.ts
cd frontend && pnpm generate:api
```

Dev 1 does the authoritative regeneration at each milestone (L1-14): the contract test
tells you it is stale, but a person still runs the command.

### 7.8 The module rule

All connecting code lives in `onboarding`. You edit no file in `kyb`, `cases`,
`customers` or `compliance` (architecture §2.5). The one documented exception is
Dev 1's, not yours.

### 7.9 Do not touch the legacy path

`onboarding_request`, `onboarding_event`, the Temporal workflow and the 18-state
machine are out of scope and must never be built on (§2.4, decision D11). If something
seems to want `onboarding_event`, it wants `exporter_lifecycle_history`.

---

## 8. Definition of done (plan §7.7, unchanged)

- Behaviour matches architecture §3.3 and your own engagement contract; roles
  enforced on the **server**.
- History rows written for every change; locked tables stay locked — including
  `follow_up_completion`, which you created and must prove locked even though you
  write no code against it.
- Unit tests for the rules, route tests for the roles, at least one test for each
  refusal, and a direct-SQL test for each new constraint.
- Screens updated with loading, empty and error states.
- Backend suite at baseline — **only** the 27 known payments/FX and
  compliance-screening failures. Anything else blocks the merge.
- `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build` all clean; no new
  import-rule violations (`lint-imports`).
- `alembic heads` prints one revision.
- **Phase-1 additions:** Step 0 merged with the suite at baseline and
  `frontend/openapi.json` byte-identical; the `3A·2` sub-anchors present and empty in
  every shared file; `docs/contracts/engagement.md` carries the completion shape
  Phase 2 needs and has been acknowledged.

---

## 9. Reporting

Keep a short running note at `docs/dev3a-phase1-progress.md`: task, state, anything
that contradicts the architecture document or a contract, and any decision you had to
make. When you finish, add — and write this block for a reader who has not seen your
branch, because it is Phase 2's starting brief:

- the engagement contract's final values and rules, and who has acknowledged it
- the exact name and type of the check-back column, and the final column list of
  `follow_up_completion`
- the error codes you defined, and which ones Phase 2 is expected to reuse
- whether 0016 needed anything the register did not anticipate
- the state of seams S1 and S2 — service merged; `OpenDealPrompt.tsx` still
  note-only, or already carrying 3B's button
- anything you left for Phase 2, 3B, Dev 2 or Dev 4, named by task ID

If you finish ahead of 3B, the plan's own rebalancing valve applies (§7.1 and §10:
hand screens over early rather than late). Offer to take the **document list screen**
from L3-11b — read-only, in its own file — with 3B reviewing. Do not take a backend
task from them; the migration chain is the one thing that must stay in one pair of
hands per number.
