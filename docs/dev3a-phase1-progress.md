# Developer 3A, Phase 1 — progress

Running note for the conversation gauge. The closing block (§7 onward) is written
for a reader who has not seen this branch, because it is **Phase 2's starting
brief**.

---

## 1. State

| Task | State | Notes |
|---|---|---|
| **Step 0** — the seam commit | **done** | Nine shared files anchored, three routers mounted, six frontend stubs + barrel lines, three sample-data hooks. Suite at baseline, `frontend/openapi.json` byte-identical (proved by `pytest backend/tests/contract`, 212 passed). Needs Dev 1's review (nine files) and Dev 2's (`sample_data.py`). |
| **L3-01a** — engagement contract | **written**, acknowledgements **pending** | `docs/contracts/engagement.md`. §10 is the acknowledgement table; nobody has confirmed yet. |
| **L3-02** — contacts/activities point at a real company | **done** | Smaller than it reads — see §3. |
| **L3-03** — the gauge, with history; migration 0016 | **done** | |
| **L3-04a** — the `NOT_NOW` check-back rule | **done** | |
| **L3-11a-i** — the panel's gauge control, history, and `OpenDealPrompt` | **done** | |

**Not in this phase, deliberately:** `follow_up_completion` has its table, its
FKs and its lock, and no entity, repository, service or route. A test asserts
that those four files do not exist, so the boundary is checked rather than
promised.

---

## 2. What contradicts a document, and what I decided

### 2.1 The plan says L3-02 is open work; 0014 had already done the hard part

`onboarding_0014_company_record` created `fk_exporter_contact_customer_id` and
`fk_exporter_activity_customer_id` (its `_LINKED` tuple, step 4). Checked before
writing any DDL, as §7.1 says to. **0016 adds no foreign key**, and
`test_l3a_contact_activity_links.py` asserts there is exactly one FK on each
`customer_id` so a later migration cannot add a second.

What was actually wrong was the **documentation**: both entities' docstrings said
`customer_id` was "a bare, indexed UUID with no formal FK", which had been false
since 0014. Both rewritten, the `ForeignKey` declared on the `mapped_column`, and
a test now compares the mapper against `pg_constraint` so they cannot drift again.

### 2.2 A ghost company was a 500, not a 404

Writing a contact or an activity for a company that does not exist reached the
database and came back as an `IntegrityError` — a 500. `ExporterContactActivityService`
now checks the company first and raises `ExporterProfileNotFoundError` (404). The
foreign key remains the authority; the check is the error message.

The check runs **before** `add_contact` demotes an existing primary contact,
because otherwise a write refused for a mistyped company id would still have left
some *other* company with no primary. There is a test for that ordering.

### 2.3 `sample_data.py`'s docstring promised something the seam commit undoes

It said "the owners of those pieces extend this file as they land". After the seam
commit nobody extends it: each owner fills in their own hook. Corrected, in the
same commit that made it false.

### 2.4 The §9.3 seeders have no per-company row, so the report shape changed

`load_sample_data` returns one row per company. The three §9.3 seeders each span
every company, so their counts land under a reserved key, `SECTION_9_3_SLUG`
(`"section-9.3"`), and `main()` prints that row separately.
`test_sample_data_is_deterministic_and_safe_to_run_again` was updated to assert
the per-company rows and that key separately. **This is a change to Dev 2's file
and its test, and is part of what Dev 2 reviews.**

### 2.5 Anchor blocks: what "one line of real content" turned out to mean

§5 asks for two anchor blocks "separated by at least one line of real content".
In the three Python barrels that is `__all__ += []` inside each block — real,
valid Python, and it also gives each owner a private line to extend, instead of
everyone appending to the one `__all__` list, which was the actual conflict. The
imports sit below `__all__`; ruff exempts `__init__.py` from E402, so this is
clean rather than a suppressed warning.

Inside a Python `dict`/`list` literal (the two route-authorisation tables) a
statement is not possible, so there the separation is the anchor headers
themselves — four or more comment lines between owners, which is more than git's
three lines of context and therefore achieves what §5 states as the purpose
("different hunks"). Same in `routes.tsx` and `Sidebar.tsx`.

### 2.6 Two files I edited that are in neither prompt's §2

Named because a reviewer should not have to find them:

- `frontend/src/modules/onboarding/components/index.ts` — two export lines for my
  two new components. Not on §5's shared-file list, and 3B's components will land
  on different lines.
- `frontend/src/modules/onboarding/pages/ExporterDetailPage.test.tsx` — the page
  test mocks `../api` with a factory, which **replaces the whole module**, so a
  function the factory omits is `undefined` at the call site. My panel calls its
  own gauge query (§2 of the prompt explicitly allows this), so the factory had to
  gain three `vi.fn()`s and two default resolved values. I did **not** touch
  `ExporterDetailPage.tsx` itself.

### 2.7 The environment, not the code

The dev database was stamped at `onboarding_0013_risk_check`, a revision from an
abandoned branch that is not in the tree, so `alembic current` failed before I
changed anything. I left that database and `.env` alone and verified everything
against a fresh `aner_dev3a`, created and migrated from base. **Worth someone
fixing** — it is not caused by this branch and it will bite the next person.

---

## 3. Two routes for the allowed moves, on purpose

`GET .../conversation` carries `allowed_moves` **and** there is a
`GET .../conversation/moves`. That looks redundant and is deliberate: the task
table names an allowed-moves route, §7.5 asks for one, and the panel wants one
request rather than two. Both answer from the same service method and a test
asserts they agree, so they cannot drift.

---

## 4. Verification run

Against a fresh database migrated from base.

```
alembic heads            -> onboarding_0016_engagement (head)      # exactly one
alembic upgrade head     -> clean
alembic downgrade -1     -> clean
alembic upgrade head     -> clean                                   # round trip
lint-imports             -> 19 contracts kept, 0 broken
ruff (onboarding)        -> 9 errors, all pre-existing, unchanged
pnpm lint                -> 0 errors (2 pre-existing warnings in AuthContext.tsx)
pnpm typecheck           -> clean
pnpm test                -> 55 passed (8 files)
pnpm build               -> clean
```

Backend suite: see §8.

---

## 5. Seam S1 and seam S2 — for Developer 3B

**S1 is merged and is not yet called.**
`ConversationService.mark_ready_now_for_opened_deal(company_id, *, deal_id, actor_id)`
in `application/conversation_service.py`, exported from
`app.modules.onboarding.application`. Signature and docstring exactly as §4.1
specifies. It flushes and never commits; it is idempotent; it writes the history
row with `deal_id` set. Call it from `DealService.open_deal`, in the same session.

Three things about it you can rely on, and there are tests for each:

- **It does not check the journey**, so it works on a `LEAD`. Refusing after your
  deal row is written would fail your whole transaction over a gauge.
- **It does not check roles.** Your deal route's roles are yours; a second gate
  here would be a second copy of them.
- **It clears `conversation_check_back_on`**, which the database requires, and
  which is right: a company with an open deal is not waiting to be called back.

**S2 is a note with no button.** `components/OpenDealPrompt.tsx` renders the
`READY_NOW` note and no button, because your deal route does not exist yet and
this project does not show navigation to something that renders nothing. When
`api/deals.ts` / `hooks/deals.ts` are published, **that one file changes and
nothing else** — `ConversationPanel.tsx` is closed. Import through the barrel
(`../api`, `../hooks`), never from your file directly.

`sample_data_engagement.py` sets company B and C to `READY_NOW` **directly**,
because there is no deal to open yet. When your seeder lands, opening those deals
finds the gauge already `READY_NOW` and the S1 call is a no-op — which is the
idempotency, doing its job.

---

## 6. For Developer 2, and for Developer 4

**Dev 2 reviews two things** (architecture §8.1):

1. **Migration 0016 adds two columns to `exporter_profile`** — `conversation` and
   `conversation_check_back_on` — plus one `CHECK` and two indexes. Nothing else
   in your table is touched, and `ExporterProfile` gains those two mapped columns
   and nothing else. The `CHECK` mirrors your `ck_exporter_profile_marker_reason`
   in shape and reasoning.
2. **`sample_data.py`** — three imports, one reserved report key, one block of
   three `await`s, and `main()` tolerating that key. See §2.3 and §2.4.

**Dev 4:** nothing to do, one thing to know. The conversation gauge is not the
background check and neither reads the other. Both are columns on the same table
with one writing service each. Please acknowledge `engagement.md` §1 so that
stays deliberate.

---

## 7. The engagement contract — final values and rules

`docs/contracts/engagement.md`. **Not yet acknowledged by anyone** (§10 of that
file is the table).

**Six values** (architecture §3.3): `NOT_CONTACTED`, `REACHING_OUT`,
`SPOKE_TO_THEM`, `INTERESTED`, `NOT_NOW`, `READY_NOW`. Python
`ExporterConversation` in `domain/entities/engagement_enums.py`; Postgres
`onboarding.exporter_conversation_enum`.

**Rules, all of them:**

- **Any value may follow any other.** No transition table anywhere, frontend
  included. The one refused move is to the value already held.
- **Who:** `OPERATIONS`, `COMPLIANCE`, `ADMIN` may set it. `DEVELOPER` reads and
  writes nothing; `API_USER` reaches neither.
- **From `PROSPECT` onward** (A4). A `LEAD` has the column, reading
  `NOT_CONTACTED`, and the service refuses a move on it.
- **`NOT_NOW` needs a reason and a check-back date**, and that date must be today
  or later. No other move needs either, and a check-back date on any other move is
  **refused, not ignored**.
- **Moving away from `NOT_NOW` clears the date**, without being asked.
- The server serves the allowed moves, each with `reason_required` and
  `check_back_required`.

**No `conversation_initial` history row is ever written.** The column arrives with
a default; recording an `_initial` row for a value nobody chose would put a change
in the log that never happened. The `event_type` name is fixed in the contract
anyway, for a future create path that does choose one.

---

## 8. The check-back column

```
onboarding.exporter_profile.conversation_check_back_on    DATE    NULL
```

The name Phase 2's prompt assumes, so nothing to reconcile. A `date`, not a
timestamp: "check back in the new year" is a day.

**Phase 2 reads it and never writes it**, exactly as 3B never writes
`conversation`. A check-back date moves only through `ConversationService`.

It is guarded by `ck_exporter_profile_conversation_check_back`: a date exists
**exactly** when `conversation = 'NOT_NOW'`. So Phase 2's Follow-ups list can
treat a non-null date as "this company is parked and due back on this day" with no
second condition — and cannot encounter a stale date on a company that has moved
on. There is a partial index for that query:
`ix_exporter_profile_conversation_check_back WHERE conversation_check_back_on IS NOT NULL`.

---

## 9. `follow_up_completion` — the final column list

Created by 0016. **Phase 2 fills it; Phase 1 wrote no code against it.**

| Column | Type | Null |
|---|---|---|
| `id` | `uuid` | no |
| `created_at` | `timestamptz` | no (`now()`) |
| `activity_id` | `uuid` | no |
| `customer_id` | `uuid` | no |
| `outcome` | `onboarding.follow_up_outcome_enum` | no |
| `note` | `text` | yes |
| `next_due_at` | `timestamptz` | yes |
| `completed_by` | `varchar(255)` | yes |
| `completed_at` | `timestamptz` | no (`now()`) |

`follow_up_outcome_enum` = `DONE`, `NO_ANSWER`, `RESCHEDULED`, `CANCELLED`.

**Phase 1 created the Postgres type and no Python enum.** `FollowUpOutcome` is
yours, in your own `domain/entities/follow_up_completion.py` — not in
`engagement_enums.py`, which is Phase 1's, because §6.3 gives no file to both
phases.

Constraints, each with a direct-SQL test in
`tests/integration/test_l3a_conversation_gauge.py`:

- `fk_follow_up_completion_activity_id` → `exporter_activity.id`, `ON DELETE RESTRICT`
- `fk_follow_up_completion_customer_id` → `exporter_profile.customer_id`, `ON DELETE RESTRICT`
- `uq_follow_up_completion_activity_id` — **one completion per follow-up**
- `ck_follow_up_completion_next_due` — `next_due_at` set **iff** `outcome = 'RESCHEDULED'`
- `trg_follow_up_completion_append_only` — `public.prevent_mutation()`, raises
  `RaiseException` with "immutable" in the message, like every other locked table
- `ix_follow_up_completion_customer_recent` — `(customer_id, completed_at DESC, id DESC)`

No index on `activity_id`: the unique constraint already gives one.

`customer_id` is denormalised from the activity **on purpose**, so one company's
completions need no join; the FK keeps it honest.

---

## 10. Error codes, and which ones Phase 2 reuses

| Code | HTTP | When | Phase 2 |
|---|---|---|---|
| `EXPORTER_PROFILE_NOT_FOUND` | 404 | No such company. Dev 1's existing exception. | **reuse** |
| `CONVERSATION_NOT_AVAILABLE` | 409 | A move on a `LEAD`. | — |
| `INVALID_CONVERSATION_TRANSITION` | 409 | A move to the value already held. | — |
| `CONVERSATION_CHECK_BACK_REQUIRED` | 422 | `NOT_NOW` with no date. | **reuse** for a reschedule with no new date |
| `CONVERSATION_CHECK_BACK_NOT_ALLOWED` | 422 | A date on a move that is not to `NOT_NOW`. | — |
| `CONVERSATION_CHECK_BACK_IN_PAST` | 422 | A date before today. | **reuse** |
| `VALIDATION_ERROR` | 422 | `NOT_NOW` with no reason. The shared `ValidationError`, as `set_marker` uses. | — |

All five new classes are in `exceptions.py` under the **`3A·1`** sub-anchor. Yours
go under **`3A·2`**, which is empty and waiting.

---

## 11. Did 0016 need anything the register did not anticipate?

**No.** Every register rule applied as written:

- Revision id `onboarding_0016_engagement` is 26 characters (limit 32).
- Both enums are created in the ordinary transactional body. **No
  `ALTER TYPE … ADD VALUE` anywhere** — the thing the register calls out by name.
- `down_revision = "onboarding_0020_retire_lifecycle"`, as the prompt fixes,
  because 0020 is the head. One head before and after.
- Every new constraint has a direct-SQL violation test.
- The downgrade is written and **says it is lossy**: it drops every follow-up
  completion row.

One thing for **Dev 1**: the register's table still lists 0016 as "Follow-up
completion (locked)" with parent `0014`, and its state as "not started". It now
also carries the conversation column and the check-back column, and its parent is
`0020`. **Please update `docs/contracts/migration-register.md`** — the rule is
that whoever sets a `down_revision` tells you.

---

## 12. What I left for whom

| Who | What | Task ID |
|---|---|---|
| **Dev 1** | Review the nine shared files' anchors; review five new exception classes; update the register row for 0016 (§11); regenerate the API artifacts authoritatively at the milestone | L1-14 |
| **Dev 2** | Review 0016's two columns on `exporter_profile`, and the `sample_data.py` changes (§6) | — |
| **Dev 4** | Acknowledge `engagement.md` §1 | L4-01 |
| **Dev 3B** | Call `mark_ready_now_for_opened_deal` from `DealService.open_deal`; publish `api/deals.ts` / `hooks/deals.ts` so seam S2's button can land; re-parent 0018 only if 3B merges first | L3-05 |
| **Phase 2** | Everything in §7–§10; the sidebar's one-word flip; `sample_data_follow_ups.py` | L3-04b, L3-11a-ii |
| **Whoever is next on S2** | The button in `OpenDealPrompt.tsx` — one file | — |

**Offer on the table.** If Phase 1 lands ahead of 3B, the plan's rebalancing valve
(§7.1, §10) applies and I will take the **document list screen** from L3-11b —
read-only, in its own file, 3B reviewing. Not a backend task: the migration chain
stays in one pair of hands per number.
