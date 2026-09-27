# Developer 3A, Phase 2 — progress

Running note for follow-up completion and the Follow-ups screen. Together with
`docs/dev3a-phase1-progress.md` this is 3A's full report against the parent
prompt's §8; the two are meant to be read in order, not merged.

---

## 1. State

| Task | State | Notes |
|---|---|---|
| **L3-04b** — completion, the due/overdue read model, the team list | **done** | |
| **L3-11a-ii** — the Follow-ups page, and the sidebar row going live | **done** | One discrepancy in the prompt had to be resolved — §3. |
| **S2** — the "open a deal" button | **out of scope, still pending** | 3B has not merged: no deal routes, no 0018/0019, `api/deals.ts` and `hooks/deals.ts` are still empty stubs. Per §1 and §2 of the prompt, S2 therefore drops out and `components/OpenDealPrompt.tsx` was **not opened**. §6 below. |

**Step 0's five items were all present**, as §5 requires, so nothing had to go back
to Phase 1's branch: the empty `follow_up_router.py` and `api/schemas/follow_up.py`,
the router already included in `api/router.py`, the `3A·2` sub-anchors in all nine
shared files, `api/follow-ups.ts` and `hooks/follow-ups.ts` already exported from the
two barrels, and `sample_data_follow_ups.py` already called from `sample_data.py`.

**No migration.** `alembic heads` prints `onboarding_0016_engagement` before and
after, and `alembic upgrade head` applies nothing. The table was read from the DDL, not
assumed — `FollowUpCompletion` maps exactly the nine columns 0016 built, and a test
asserts the column set.

---

## 2. What contradicts a document, and what I decided

### 2.1 The routes are not under `/exporters` — the stub's prefix was wrong

Step 0's stub carried `prefix="/exporters"` as a placeholder. Dropped, for two
reasons, both in `follow_up_router.py`'s docstring:

- A follow-ups list spans every company, so it is not a company sub-resource — the
  same reasoning that gives `history_router.py`'s deal route absolute paths.
- With that prefix, `GET /exporters/follow-ups` would be matched by
  `GET /exporters/{customer_id}` first (`exporter_router` is included before this
  one), and FastAPI would try to parse the literal `follow-ups` as a UUID and return
  422. Phase 1's cross-company route dodged this with two segments
  (`/exporters/activities/pending`); this one is simply not under `/exporters`.

Final paths: `GET /onboarding/follow-ups` and
`POST /onboarding/follow-ups/{activity_id}/completion`. `api/router.py` was **not**
opened — the routes appear by being added to my own router, exactly as §5 says.

### 2.2 A completion writes no history row

`engagement.md` §5 was silent and prompt §7.4 says not to invent a `follow_up`
dimension. `history-row.md` §2's dimension list has nothing for a follow-up, and
adding one would mean recording in a second place what the completion table already
records permanently and append-only.

So: **no history row**, and I appended `engagement.md` §5.7 saying so explicitly,
because silence is the kind of thing the next reader has to re-derive. The one place
the two meet is the check-back date, which is the gauge's — and moving *that* does
write a `conversation` row, because it is a gauge change.

### 2.3 The two reserved check-back codes are mirrored, not reused

Phase 1 reserved `CONVERSATION_CHECK_BACK_REQUIRED` and
`CONVERSATION_CHECK_BACK_IN_PAST` for reuse on the reschedule path
(`engagement.md` §7). I did not reuse them. Those codes name the **conversation
gauge's** check-back date, which lives on the company record; a reschedule's
`next_due_at` is a moment on an activity. One code covering both would tell a caller
the wrong place to look.

So the reschedule path has `FOLLOW_UP_RESCHEDULE_NEEDS_DATE` and
`FOLLOW_UP_RESCHEDULE_IN_PAST`, with the same reasoning behind them. Recorded in
`engagement.md` §7.1 and in its §10 acknowledgement row. **This is the only place I
departed from Phase 1's stated intent**, and it needed no schema or contract change
beyond the append.

### 2.4 The seeder logs its own follow-ups

Developer 2's sample data gives exactly **one** activity a `due_at`, so a Follow-ups
screen built on it would demonstrate neither *overdue* nor *done*. Rather than edit
Dev 2's file, `sample_data_follow_ups.py` logs the follow-ups it needs against the
companies Dev 2 created — which is what prompt §2 asks of it. The result covers all
three states plus a reschedule chain, and converges (second run: 0).

Due dates are **relative to today**, never literals: a literal would rot, and the
moment the clock passed it a `RESCHEDULED` seed would start failing the future-date
check.

### 2.5 Two ruff/import-linter problems my own code introduced, and the fixes

Both worth recording because the fix is not obvious from the error:

- **E402 in the three barrels.** Ruff tolerates the *first* import after `__all__`
  but flags every one after that — so Phase 1's single late import per barrel was
  clean and Phase 2's second one was not. The anchored-block layout is deliberate (it
  is what gives each owner a private hunk), so each late import now carries an
  explicit `# noqa: E402` pointing at the anchor preamble, and the preamble says
  **3B: yours needs one too.** Phase 1's comment claiming ruff exempts `__init__.py`
  from E402 was wrong and has been corrected.
- **`importlinter` broke on my test.** `test_there_is_no_route_that_edits_or_deletes_a_completion`
  imported `app.main`, and `app.main` pulls in `app.api.rest.router`, which trips
  "modules never import the delivery layer". Rewritten to read the route list off
  Phase 2's own router — which is the truer scope anyway, since that is the only file
  such a route could be added to.

### 2.6 A Phase 1 typecheck error this phase surfaced

`pnpm build` is `tsc -b && vite build`. In Phase 1 I ran `vite build` directly, so a
type error in `ConversationPanel.test.tsx` went unreported and my Phase 1 note's
"typecheck clean" was based on a run that predated that file. It is fixed here:
`HistoryEntryResponse.details` is `dict | None` on the server, which generates as
`Record<string, never>` — a type accepting no properties — so the test's realistic
`details` object needs a cast. Developer 1 owns `schemas/history.py`; retyping it to
`dict[str, Any]` would generate `{[key: string]: unknown}` and remove the need for the
cast, which is **worth raising with Dev 1** but is not Developer 3's file to change.

### 2.7 The environment, again

The dev database is still stamped at `onboarding_0013_risk_check`, a revision from an
abandoned branch, so `alembic current` fails against it. Everything here was verified
against the fresh `aner_dev3a` Phase 1 created. Unchanged from Phase 1's note, and
still worth someone fixing.

---

## 3. The one place the prompt could not be satisfied as written

**`/follow-ups` is not reachable, so the screen is at `/exporters/follow-ups`.**

The prompt's §5 table assigns the route to
`frontend/src/modules/onboarding/routes.tsx` and describes the sidebar change as a
one-word `status` flip on the existing row, whose `path` is `/follow-ups`. Those two
cannot both hold: `OnboardingRoutes` is mounted by `routes/AppRouter.tsx` only at
`/exporters/*`, so a route added to `routes.tsx` can only ever be under `/exporters`.

The alternatives were:

| | Cost |
|---|---|
| **Chosen:** route in `routes.tsx`, sidebar row gets `path: '/exporters/follow-ups'` as well as `status: 'ready'` | Two words on a row Phase 2 already owns, instead of one |
| Top-level `/follow-ups` in `routes/AppRouter.tsx`, exported from `modules/onboarding/index.ts` | Three files outside §2, one of them the app router — against the explicit DoD "No file outside §2 changed" |

I took the first: it keeps the route in the file §5 names, keeps everything behind the
module facade the eslint `boundaries` rules exist to protect, and costs one extra word
on a line I am already allowed to edit. **Flagged for Developer 1**, who owns both
files, in case the team would rather have the top-level URL — it is a three-line change
if so. There is precedent for either: `PipelinePage` is a module page mounted at
top-level `/pipeline` in the app router.

### 3.1 Two shared-file lines that could not sit inside the `3A·2` anchor

Named so a reviewer does not have to find them:

- **`routes.tsx` needs `FollowUpsPage` imported**, and an ES module's imports must be
  at the top of the file, which is above every anchor. Rather than join the existing
  destructured `from './pages'` list — a line 3B would also have to edit — it is its
  own `import` statement, labelled `3A·2`. 3B's will be another separate line.
- **`pages/index.ts` needs the page exported** (one line). Not on §5's shared-file
  list and not in §2; the same situation as Phase 1's `components/index.ts`.

Also outside the anchor, in the three backend barrels: the anchor **preamble** comment
was corrected, because Phase 1 wrote there that ruff exempts `__init__.py` from E402
and that turned out to be false (§2.5). It is my own text from the same series of
commits, not another owner's.

---

## 4. The completion record as built

Exactly `engagement.md` §5.2, with **no amendment**. Nine columns, read off the DDL
0016 created rather than assumed:

| Column | Type | Null |
|---|---|---|
| `id` | `uuid` | no |
| `created_at` | `timestamptz` | no (`now()`) |
| `activity_id` | `uuid` | no → FK `exporter_activity.id`, RESTRICT |
| `customer_id` | `uuid` | no → FK `exporter_profile.customer_id`, RESTRICT |
| `outcome` | `follow_up_outcome_enum` | no |
| `note` | `text` | yes |
| `next_due_at` | `timestamptz` | yes |
| `completed_by` | `varchar(255)` | yes |
| `completed_at` | `timestamptz` | no (`now()`) |

`FollowUpOutcome` = `DONE`, `NO_ANSWER`, `RESCHEDULED`, `CANCELLED`, in
`domain/entities/follow_up_completion.py` — **not** in Phase 1's
`engagement_enums.py`, per §6.3.

`customer_id` is taken from the **activity**, never from the caller: a
caller-supplied company could disagree with it and put the completion on the wrong
company's list.

### Nothing updates an activity

The test that matters snapshots every column of the activity before completing it and
asserts the row is byte-identical afterwards — not merely that no exception was
raised. A reschedule logs a **new** activity and leaves the original with the date it
was promised for.

---

## 5. The due/overdue rules as implemented

Derived, never stored. There is no status column and nowhere to put one.

| State | Rule |
|---|---|
| `OUTSTANDING` | The activity has a `due_at` and **no** completion row. Expressed as `LEFT JOIN … WHERE completion.id IS NULL`. |
| `OVERDUE` | Outstanding **and** `due_at < now`. A *narrowing* of outstanding, not a value beside it — so the `OUTSTANDING` filter includes overdue rows, which is the distinction a reader is most likely to get wrong. |
| `DONE` | A completion row exists, whatever its outcome. `CANCELLED` and `NO_ANSWER` are dealt-with: somebody decided, and the decision is the record. |

- **A follow-up completed late is `DONE`, not overdue.** Otherwise the overdue count
  becomes a list of old work rather than of outstanding work.
- **`is_overdue` is computed once per response**, against the one `now` the query ran
  with, which is why the repository takes `now` as an argument instead of calling the
  clock itself. Two rows of one answer can never be judged against different clocks.
- An activity **without** a `due_at` is not on the list at all, and completing one is
  refused (`ACTIVITY_IS_NOT_A_FOLLOW_UP`).
- **The whole team's** (decision D2): no default owner filter. `actor_id` narrows and
  never gates — tested from both sides.
- Ordered soonest-due first, so overdue sorts to the front. `total` counts the filter,
  not the page, and comes from the same query builder as the page so the two can never
  describe different sets.

### How check-back dates appear

**As their own list, not as follow-ups.** `FollowUpListView` carries `follow_ups` and
`check_backs` separately, and the screen shows two sections.

A check-back is a company parked at `NOT_NOW` whose `conversation_check_back_on` says
when to try again. It has no activity and no completion, and it is **not completable
here**: it is dealt with by moving the conversation gauge on the company's page, which
clears the date in the same transaction. Merging the two lists would have produced a
row type that is half null on every row and would invite code that tries to complete a
check-back.

- **Phase 2 never writes the date.** Read-only, exactly as 3B never writes
  `conversation`. Tested: moving the gauge off `NOT_NOW` takes the row off this list.
- The query filters on the **date**, not on `conversation = 'NOT_NOW'`:
  `ck_exporter_profile_conversation_check_back` already guarantees those are the same
  set, and the partial index is on the date column.
- A check-back due **today** is due, not late.
- `include_check_backs=false` leaves them out; the screen uses it on the tabs where
  showing the same rows four times would be noise.

---

## 6. Seam S2 — still pending on 3B's L3-05

**Not shipped, and correctly so.** Checked before touching anything, as §1 instructs:

- `deal_router.py` declares no routes
- no `onboarding_0018_*` or `0019_*` migration exists
- `api/deals.ts` and `hooks/deals.ts` are still the `export {}` stubs

So per §1 and §2, S2 dropped out of Phase 2's scope and **`components/OpenDealPrompt.tsx`
was not opened**. It still renders the `READY_NOW` note with no button, which is the
right screen while the route it would call does not exist.

It remains a one-file commit for whoever gets there first. Everything that commit needs
is in that file's docstring: import 3B's request function and hook **through the
barrel** (`../api`, `../hooks`), define no deal request function or deal type, and
never set the conversation — opening the deal moves the gauge on the server via seam
S1.

---

## 7. Roles on each route, and the refusal tests

| Route | Roles | Why |
|---|---|---|
| `GET /onboarding/follow-ups` | OPERATIONS, COMPLIANCE, ADMIN, DEVELOPER | Follow-ups are the whole team's (D2). DEVELOPER reads the CRM. A follow-up carries no tax identifier, so there is nothing for the masking rules to apply to and every permitted role gets the same bytes. |
| `POST /onboarding/follow-ups/{activity_id}/completion` | OPERATIONS, COMPLIANCE, ADMIN | A routine CRM write — the same three that may set the conversation gauge (`engagement.md` §5.5). |

`API_USER` reaches neither.

Covered from both sides:

- **Rows under the `3A·2` anchor** in `backend/tests/contract/test_route_authorization_coverage.py`
  (an unclassified route fails that file by construction) and in
  `app/modules/onboarding/tests/integration/test_route_authorization.py`, which derives
  one 403 test per refused role.
- **A positive/negative pair** in `test_l3a_follow_up_completion.py`: DEVELOPER reads
  the list (200, one row) and is refused the completion (403, `FORBIDDEN`).
- **One test per refusal**, each asserting the contract's code rather than a bare
  status: `FOLLOW_UP_NOT_FOUND`, `ACTIVITY_IS_NOT_A_FOLLOW_UP`,
  `FOLLOW_UP_ALREADY_COMPLETED`, `FOLLOW_UP_RESCHEDULE_NEEDS_DATE`,
  `FOLLOW_UP_RESCHEDULE_IN_PAST`, `FOLLOW_UP_NEXT_DUE_NOT_ALLOWED`,
  `FOLLOW_UP_COMPLETION_IMMUTABLE`, and a 422 when `completed_by` is supplied in the
  body.

### The lock, in place of a direct-SQL constraint test

Phase 2 adds no constraint, so per prompt §3 what it owes instead is the proof that
the existing lock holds against this code. Three layers, three tests:

1. `FollowUpCompletionRepository` exposes no `update` and no `delete` — asserted, not
   trusted, because the failure mode is somebody adding one later.
2. `FollowUpService.refuse_completion_edit` raises `FOLLOW_UP_COMPLETION_IMMUTABLE`
   (409) — a named, tested behaviour rather than an absence somebody could fill in.
3. The database still refuses an UPDATE made through a session that was handed the
   mapped object — the one that would catch somebody bypassing the repository.

Plus an assertion that the router declares **only** the two routes above, so a PATCH
or DELETE cannot appear without a test failing.

---

## 8. Verification run

Against the fresh `aner_dev3a`, migrated from base.

```
alembic heads            -> onboarding_0016_engagement (head)   # unchanged, one
alembic upgrade head     -> nothing to apply                    # no new migration
lint-imports             -> 19 contracts kept, 0 broken
ruff (onboarding)        -> 9 errors, all pre-existing, unchanged
pnpm lint                -> 0 errors (2 pre-existing warnings in AuthContext.tsx)
pnpm typecheck           -> clean
pnpm test                -> 72 passed (9 files)
pnpm build               -> clean  (tsc -b && vite build)
Phase 2 backend tests    -> 42 integration + 11 unit passed
contract tests           -> 224 passed (openapi.json regenerated and current)
```

Backend suite: see §10.

---

## 9. What I left for whom

| Who | What | Task ID |
|---|---|---|
| **Dev 1** | Review the `3A·2` additions to the five shared backend/frontend files; decide the `/follow-ups` vs `/exporters/follow-ups` question in §3; consider retyping `HistoryEntryResponse.details` to `dict[str, Any]` so callers do not need a cast (§2.6); update `migration-register.md`'s 0016 row (still outstanding from Phase 1); authoritative API regeneration at the milestone | L1-14 |
| **Dev 2** | Nothing new. `sample_data.py` was not opened in this phase — only the hook it already calls. | — |
| **Dev 4** | Nothing. Still owes an acknowledgement of `engagement.md` §1, from Phase 1. | L4-01 |
| **Dev 3B** | Publish `api/deals.ts` / `hooks/deals.ts` and the deal route so seam S2's button can land; call `ConversationService.mark_ready_now_for_opened_deal` from `DealService.open_deal`; add `# noqa: E402` to their barrel imports (§2.5); re-parent 0018 only if they merge before Phase 1 | L3-05 |
| **Whoever is next on S2** | The button, in `components/OpenDealPrompt.tsx` — one file | — |

**Offer on the table.** 3B has not merged, so the plan's rebalancing valve (§7.1,
§10) applies: I can take the **document list screen** from L3-11b — read-only, in its
own file, 3B reviewing. Not a backend task; the migration chain stays in one pair of
hands per number.

---

## 10. Backend suite

**At baseline.** `23 failed, 3492 passed, 6 skipped, 5 errors in 937s`.

22 failures + 5 errors = the 27 documented items, the same list as Phase 1's run and
`TEST-BASELINE.md`: two audit `/payments`/`/fx` 404s, twelve compliance
`POST /payments` 404s, eight screening-rule-registry 404s, five compliance
fixture-setup errors. Zero onboarding failures. The +60 passes over Phase 1's 3432 are
this phase's tests.

### The 23rd failure was mine, and the fix is worth reading

`test_l3a_conversation_gauge.py::test_phase_1_writes_no_code_against_follow_up_completion`
— a Phase 1 guard asserting that Phase 2's entity, repository and service **did not
exist**. Phase 2 built them, so it failed.

That is correct behaviour for a guard against a state that was always meant to end,
but it is not a test worth keeping: it was load-bearing on a condition Phase 2 was
always going to remove. Phase 1 should have seen that when writing it.

Rewritten as `test_only_0016_ever_touches_follow_up_completion`, which guards the half
of §6.2 that stays true forever: exactly one migration in the repository may mention
`follow_up_completion`. That still protects something real — 3B's 0018 parents onto
0016, so a second 3A migration would force them to re-parent for a reason internal to
3A, which is the chain damage the phase split exists to prevent.

Re-verified after the fix: **357 passed, 0 failed** across the 224 contract tests (so
the regenerated `openapi.json` is current) and all 133 `test_l3a_*` tests.
