# Contract — engagement: the conversation gauge and follow-ups

> **Amendment, 9 October 2026 — permissions, and a read-only administrator.** Every CRM
> route now checks a permission (`require_permission`), not a role list; the grants each
> built-in role starts with are in `platform/authorization/catalog.py`
> (`BUILTIN_ROLE_PERMISSIONS`), seeded by `auth_0007_business_permissions`. The
> administrator (ADMIN) manages users, roles and settings and **reads** companies, deals,
> documents and compliance work, but creates, edits, decides, approves and assigns nothing,
> and sees tax identifiers masked. Wherever this document says "COMPLIANCE or ADMIN" (or
> lists ADMIN among those who write, decide, approve, assign, reveal or take in an RXIL
> package), read **COMPLIANCE** — or the holder of the named permission. The senior
> permissions (`exporters:assign_rm`, `compliance:assign`, `compliance:approve_high_risk`)
> are no longer "ADMIN, or the permission": they are held through the seeded **Sales lead**
> and **Compliance lead** roles. RXIL intake needs `exporters:partner_intake` (COMPLIANCE).

**Owner:** Developer 3A · **Column:** `onboarding.exporter_profile.conversation` · **Table:** `onboarding.follow_up_completion` · **Migration:** `onboarding_0016_engagement`

The conversation gauge answers *how is the sales conversation going?* — and
nothing else. It is not the journey (`LEAD` → `PROSPECT` → `CUSTOMER`, Developer
2), not whether the company met our requirements (qualification, Developer 2),
not whether it is safe to lend to (the background check, Developer 4), and not a
commercial pause (the marker, Developer 2). Folding those together into one line
is what the retired ten-status `lifecycle_status` did, and why it was retired.

Follow-ups are the other half of the same relationship: an activity with a
`due_at` is something someone said they would do, and a **completion** is the
record that they did.

This contract is what Developer 3B, Developer 2, Developer 4 and Developer 3A's
own Phase 2 write against. Changing it needs the agreement of the owner and
every user of it (architecture §7.5).

**Scope split.** Phase 1 publishes this whole file and builds §2–§4. §5 (the
completion record) is published here in Phase 1 and built by Phase 2, because its
table is created by migration 0016 and its shape has to be fixed before the DDL
is written. Phase 2 appends to this file; it does not rewrite it.

---

## 1. Values

Six, from architecture §3.3, upper case like every other gauge in this CRM.

| Value | Means |
|---|---|
| `NOT_CONTACTED` | Nobody has reached out yet. The default. |
| `REACHING_OUT` | We have tried — a call placed, an email sent — with no reply yet. |
| `SPOKE_TO_THEM` | A real conversation happened. Says nothing about how it went. |
| `INTERESTED` | They want to talk about financing, but not about a specific shipment yet. |
| `NOT_NOW` | They said not now. **Carries a check-back date** — §4. |
| `READY_NOW` | They have something they want financed. The screen offers to open a deal; opening a deal also sets this — §6. |

Python: `ExporterConversation` in
`backend/app/modules/onboarding/domain/entities/engagement_enums.py`. Deliberately
**not** in `exporter_enums.py`, which holds Developer 2's company values.

Postgres: `onboarding.exporter_conversation_enum`.

### 1.1 Any value may follow any other

A sales conversation is not a pipeline. Someone who said `NOT_NOW` in March can be
`READY_NOW` in April without passing back through `INTERESTED`, and a conversation
that looked promising can go quiet. Architecture §3.3 calls this a judgement, so
there is **no transition table** here and none in the frontend.

The one refusal is a move to the value the gauge already has: it records nothing
and would put a `from == to` row in the history log. See
`INVALID_CONVERSATION_TRANSITION` in §7.

What *is* a rule is who may move it (§3), what a move to `NOT_NOW` must carry
(§4), and that the gauge does not apply to a `LEAD` (§2.2).

---

## 2. The column, and when it applies

### 2.1 The columns

| Column | Type | Null | Default | Written by |
|---|---|---|---|---|
| `exporter_profile.conversation` | `onboarding.exporter_conversation_enum` | no | `'NOT_CONTACTED'` | `ConversationService` **only** |
| `exporter_profile.conversation_check_back_on` | `date` | yes | — | `ConversationService` **only** |

`conversation` is the field `docs/contracts/company-record.md` §2.4 reserves for
Developer 3. Per that contract, **only the owner writes it**, through its own
service, and writes the history row in the same transaction. No other service
assigns to it, "including just to keep it in step".

Two consequences, stated because each has a named counterparty:

- **Developer 3B never writes `exporter_profile.conversation`.** Opening a deal
  moves the gauge by calling the service — §6.
- **Phase 2 never writes `conversation_check_back_on`.** The Follow-ups list
  reads it. A check-back date moves only through `ConversationService`.

### 2.2 The gauge applies from `PROSPECT` onward

Assumption A4. A `LEAD` has the column — it is `NOT NULL`, so it has to — and it
reads `NOT_CONTACTED`, but the gauge is not *in use* yet: the service refuses a
move on a `LEAD` with `CONVERSATION_NOT_AVAILABLE` (409), and the screen offers no
moves.

The reasoning is the journey's: a `LEAD` becomes a `PROSPECT` when a qualification
outcome says `QUALIFIED` (company-record §3.1). Tracking how the sales
conversation is going before we have decided we would finance them at all records
an opinion about a company we may never call.

`CUSTOMER` is "onward", so the gauge stays live there: an existing customer's next
shipment is a fresh conversation.

### 2.3 The check-back date is `NULL` exactly when the value is not `NOT_NOW`

Enforced by the database, not only by the service:

```sql
CONSTRAINT ck_exporter_profile_conversation_check_back CHECK (
    (conversation = 'NOT_NOW' AND conversation_check_back_on IS NOT NULL)
    OR (conversation <> 'NOT_NOW' AND conversation_check_back_on IS NULL)
)
```

Same shape, and the same reasoning, as `ck_exporter_profile_marker_reason`: a
stale check-back date on a company that is now `READY_NOW` would put that company
on Phase 2's Follow-ups list for a conversation that has already moved on. So
moving **away** from `NOT_NOW` clears the date, in the same transaction and
without the caller asking.

The default row — `NOT_CONTACTED`, no date — satisfies it, which is why 0016 can
add both columns to a populated table.

---

## 3. Who may set it

Architecture §3.7's role matrix, and §7.5's rule that roles are enforced on the
server.

| Role | May set the conversation |
|---|---|
| `OPERATIONS` | **yes** — Relationship Managers are `OPERATIONS` |
| `COMPLIANCE` | **yes** |
| `ADMIN` | **yes** |
| `DEVELOPER` | **no** — reads the CRM, writes nothing |
| `API_USER` | **no** — reaches nothing in the CRM |

`DEVELOPER` may **read** the gauge, like every other CRM read. `API_USER` may not.

A refused role gets `403 FORBIDDEN` from the route's `require_role`, before the
handler runs. It is also served an empty `allowed_moves` list (§3.1), so a screen
never shows a button that would be refused.

### 3.1 The server serves the allowed moves

§7.5: "The frontend fetches the allowed journey, gauge and deal moves for the
current user instead of keeping hand-copied tables."

There is no transition table (§1.1), so "allowed moves" is the whole value list
minus the current value — but that is the *server's* sentence to say, and it also
carries whether each move needs a reason and whether it needs a check-back date.
`ConversationGaugeControl.tsx` renders exactly what it is given and holds no copy
of the values.

Each move is served as:

| Field | Meaning |
|---|---|
| `to` | The value this move sets. |
| `reason_required` | Whether the move is refused without a reason (§4). |
| `check_back_required` | Whether the move is refused without a check-back date (§4). |

Empty for a role that may not set the gauge, and empty on a `LEAD` (§2.2) — in
both cases because the move would be refused, and a screen that has to work out
*why* the list is empty is a screen keeping its own copy of the rules.

---

## 4. `NOT_NOW`: a reason and a check-back date

Moving to `NOT_NOW` requires **both**:

| | Why |
|---|---|
| a **reason** | `NOT_NOW` is the one value that records a setback. "Why not now" is the only thing that makes the row worth reading a quarter later, and unlike every other move it is not obvious from the value itself. Recorded as the history row's `reason`. |
| a **check-back date** | A conversation parked with no date is a conversation dropped. The date is what puts the company on Phase 2's Follow-ups list. Stored on the company as `conversation_check_back_on`. |

The check-back date must be **today or later**. A date in the past is a typo
(`2025` for `2026` is the common one), and a Follow-ups list seeded with dates
already overdue on the day they were entered is a list nobody trusts.

No other move requires either. Passing a check-back date on a move that is not to
`NOT_NOW` is refused rather than ignored — silently dropping it would leave the
operator believing a date was stored.

Every move, `NOT_NOW` or not, may carry a reason; it is recorded when given.

---

## 5. The completion record — Phase 2 builds this

Table `onboarding.follow_up_completion`. **Created by migration 0016 (Phase 1);
filled by Phase 2's code.** Phase 1 writes no entity, repository, service or route
for it, and proves it locked with a direct-SQL test.

### 5.1 What a completion is

An activity with a `due_at` is a promise. A completion is one append-only row
saying that promise was dealt with, and how.

**It is a new row, never an edit.** `exporter_activity` is append-only, enforced by
`trg_exporter_activity_append_only`. Nothing marks an activity as done —
architecture §9.3's "Watch out for" says this first because it is the mistake this
design invites. Rescheduling likewise logs a **new** activity with the new
`due_at`; the old one keeps the date it was promised for.

### 5.2 The row

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | `uuid` | no | Primary key, `uuid4`. |
| `created_at` | `timestamptz` | no | `server_default now()`. Server-authoritative. |
| `activity_id` | `uuid` | no | **The follow-up.** FK → `exporter_activity.id`, `ON DELETE RESTRICT`. |
| `customer_id` | `uuid` | no | **The company.** FK → `exporter_profile.customer_id`, `ON DELETE RESTRICT`. Denormalised from the activity so one company's completions need no join. |
| `outcome` | `onboarding.follow_up_outcome_enum` | no | §5.3. |
| `note` | `text` | yes | What happened, in the actor's words. |
| `next_due_at` | `timestamptz` | yes | Set **exactly** when `outcome = 'RESCHEDULED'`; the moment it was moved to. |
| `completed_by` | `varchar(255)` | yes | Who, from their login session — never from a request body. `NULL` = the platform itself, the same meaning `actor_id` carries everywhere in this CRM. |
| `completed_at` | `timestamptz` | no | When, `server_default now()`. |

### 5.3 `outcome`

| Value | Means |
|---|---|
| `DONE` | The follow-up happened. |
| `NO_ANSWER` | We tried and got nowhere. Closed without a reschedule. |
| `RESCHEDULED` | Moved. `next_due_at` says to when, and Phase 2 logs the replacement activity. |
| `CANCELLED` | No longer needed. |

Python: `FollowUpOutcome`, in Phase 2's own
`domain/entities/follow_up_completion.py`. Not in `engagement_enums.py` — that file
is Phase 1's, and the phase agreement (§6.3) gives no file to both phases. Phase 1
creates the Postgres type and nothing in Python.

### 5.4 Constraints, and what they mean

| Constraint | Rule |
|---|---|
| `pk_follow_up_completion` | `id`. |
| `fk_follow_up_completion_activity_id` | Real link to the activity, `ON DELETE RESTRICT`. |
| `fk_follow_up_completion_customer_id` | Real link to the company, `ON DELETE RESTRICT`. |
| `uq_follow_up_completion_activity_id` | **One completion per follow-up.** A second is a 409, not a second row: a reschedule is a new activity, so nothing legitimate completes the same activity twice. |
| `ck_follow_up_completion_next_due` | `next_due_at IS NOT NULL` **iff** `outcome = 'RESCHEDULED'`. |
| `trg_follow_up_completion_append_only` | `public.prevent_mutation()`, `BEFORE UPDATE OR DELETE`. A correction is a new activity plus its own completion, never an edit. |
| `ix_follow_up_completion_customer_recent` | `(customer_id, completed_at DESC, id DESC)` — one company's completions, newest first. |

There is no separate index on `activity_id`: the unique constraint already gives
one, and a second would be dead weight on an append-only table.

### 5.5 Who may complete a follow-up

`OPERATIONS`, `COMPLIANCE`, `ADMIN` — the same three that may set the conversation
(§3), and for the same reason: completing a follow-up is a routine CRM write.
`DEVELOPER` may read the list and complete nothing. `API_USER` reaches neither.

### 5.6 Due and overdue

A follow-up is **open** when its activity has a `due_at` and no completion row
points at it. It is **overdue** when it is open and `due_at < now()`.

Phase 2 computes this in its own
`infrastructure/repositories/follow_up_completion_repository.py`, joining
activities to completions there, and returns its own read models from
`domain/follow_up_views.py`. It adds no method to `exporter_activity_repository.py`
or `engagement_views.py`, which are Phase 1's (phase agreement §6.3).

`GET /onboarding/exporters/activities/pending` already exists (Phase 1's, from
L2-01) and lists activities with a `due_at` across every company. It knows nothing
about completions, so it lists completed follow-ups too. Phase 2's list is the one
that subtracts them; the pending route is **not** changed to do it, because its
callers today want "everything with a due date".

**Check-backs on an overdue view.** `GET /onboarding/follow-ups` takes
`check_backs_due_only=true` to list only the check-backs due on or before today
(UTC — the same date `is_overdue` is judged against), with `check_backs_total`
counting the same set. The Follow-ups screen's Overdue tab uses it, so a company
parked until next quarter is not listed beside work that is late; the All tab still
shows every parked company.

**Who logged it, by name.** An activity (`GET`/`POST …/activities`, and the company
detail's `recent_activities`) and a follow-up row (`GET /onboarding/follow-ups`) carry
`actor_name` beside `actor_id`: the account's full name, or its email when it has none —
DEVELOPER is given the full name only. Resolved when read through the platform's auth
facade (`api/actor_names.py`), never stored; `null` when no account with a name matches.
The pending route above is not changed.

### 5.7 A completion writes no history row

*Appended by Phase 2, 27 September 2026. A clarification, not a change: §5 was silent
and this records the answer so the next reader does not have to infer it.*

Completing a follow-up writes **one** row, in `follow_up_completion`, and nothing in
`exporter_lifecycle_history`.

`docs/contracts/history-row.md` §2 fixes the dimension list — `journey`,
`qualification`, `marker`, `profile`, `conversation`, `deal`, `background_check`,
`verification` — and none of them is a follow-up. Adding a `follow_up` dimension
without adding it to that contract is the thing the history table exists to prevent,
and adding it *to* the contract would need all four developers to agree to record
something the completion table already records permanently and append-only.

So the two are separate on purpose: the history log carries **what a company's gauges
did**, and a completion carries **what a person did about a promise**. The one place
they meet is the check-back date, which is the conversation gauge's — and moving it
does write a `conversation` history row, because that is a gauge change.

If a future ticket needs a follow-up in the company timeline, it is a change to
`history-row.md` §2 first and to this contract second, not a dimension string invented
at the call site.

---

## 6. Seam S1 — opening a deal sets `READY_NOW`

Architecture §3.3: "`READY_NOW` … The screen offers to open a deal; opening a deal
also sets this."

`ConversationService.mark_ready_now_for_opened_deal(company_id, *, deal_id, actor_id)`.

- **Developer 3B calls it** from `DealService.open_deal`, in the same session and
  the same transaction, passing `deal_id`.
- **It flushes and does not commit.** The caller owns the transaction, so the deal
  row, the deal's history row and this gauge move land together or not at all.
- **It is idempotent.** A company already `READY_NOW` writes no history row and is
  not an error: opening a second deal for a company that is already ready is
  normal.
- **It does not apply §2.2 or §3.** No `LEAD` check here — a deal is only opened for
  a company that got that far, and `DealService.open_deal` enforces exactly that
  before anything is written: a `LEAD` is refused with `DEAL_COMPANY_NOT_READY`
  (`deal-and-buyer.md` §2). So the gauge can never be moved on a `LEAD` through this
  seam. No role check either: the *deal* route's roles are Developer 3B's to
  enforce, and a second gate here would be a second copy of them.
- **Developer 3B never writes the column and never imports `ExporterConversation`
  to compare against it.**

Its history row carries `deal_id`, per `history-row.md` §2: "`deal_id` is set …
when another dimension's change is about a specific deal."

---

## 7. Error codes

Every refusal below has a test (plan §7.7). Phase 2 reuses the three marked
**reuse**.

| Code | HTTP | Raised when | For |
|---|---|---|---|
| `EXPORTER_PROFILE_NOT_FOUND` | 404 | No company with that id. Developer 1's existing exception, not a new one. | **reuse** |
| `CONVERSATION_NOT_AVAILABLE` | 409 | A move on a `LEAD` — the gauge applies from `PROSPECT` (§2.2). | |
| `INVALID_CONVERSATION_TRANSITION` | 409 | A move to the value the gauge already has (§1.1). | |
| `CONVERSATION_CHECK_BACK_REQUIRED` | 422 | A move to `NOT_NOW` with no check-back date (§4). | reserved for the reschedule path, then **not reused** there (§7.1) |
| `CONVERSATION_CHECK_BACK_NOT_ALLOWED` | 422 | A check-back date on a move that is not to `NOT_NOW` (§4). | |
| `CONVERSATION_CHECK_BACK_IN_PAST` | 422 | A check-back date before today (§4). | reserved for the reschedule path, then **not reused** there (§7.1) |
| `VALIDATION_ERROR` | 422 | A move to `NOT_NOW` with no reason (§4) — the shared `ValidationError`, as `set_marker` uses for the marker's reason. | |

Phase 2 defines its own codes for completion and appends them below. It redefines no
row above.

### 7.1 Follow-up completion

*Appended by Phase 2, 27 September 2026.*

| Code | HTTP | Raised when |
|---|---|---|
| `FOLLOW_UP_NOT_FOUND` | 404 | No `exporter_activity` row has that id. |
| `ACTIVITY_IS_NOT_A_FOLLOW_UP` | 409 | The activity exists but carries no `due_at`, so nobody promised it (§5.1). Kept distinct from the 404: "no such activity" and "that is not a follow-up" send a person looking in different places. |
| `FOLLOW_UP_ALREADY_COMPLETED` | 409 | A completion already points at that activity (`uq_follow_up_completion_activity_id`, §5.4). Carries `completion_id` and `outcome`, so a screen can say what is already recorded. Also what the **second of two simultaneous** completions gets: the service locks the activity row before checking, so the second waits for the first to commit and is refused here rather than tripping the unique constraint as a 500. |
| `FOLLOW_UP_RESCHEDULE_NEEDS_DATE` | 422 | `RESCHEDULED` with no `next_due_at`. |
| `FOLLOW_UP_NEXT_DUE_NOT_ALLOWED` | 422 | A `next_due_at` on any other outcome — refused, not ignored, for the same reason a check-back date on a non-`NOT_NOW` move is (§4). |
| `FOLLOW_UP_RESCHEDULE_IN_PAST` | 422 | `next_due_at` is not in the future. |
| *(request-body validation — FastAPI's `detail` list, no `error_code`)* | 422 | `next_due_at` has no timezone offset (e.g. `2030-01-01T10:00:00`). A moment without an offset names no moment; it is refused at the body rather than guessed. Send `Z` or an offset such as `+05:30`. |
| `FOLLOW_UP_COMPLETION_IMMUTABLE` | 409 | Something tried to change or remove a completion. There is no route that can reach this; the service raises it so the refusal is a named, tested behaviour rather than an absence. |

**`CONVERSATION_CHECK_BACK_REQUIRED` was reserved for reuse here (§7) and is not
reused.** That code names the *conversation gauge's* check-back date, which lives on
the company record; a reschedule's `next_due_at` is a moment on an activity. One code
covering both would tell a caller the wrong place to look, so
`FOLLOW_UP_RESCHEDULE_NEEDS_DATE` is its own. `CONVERSATION_CHECK_BACK_IN_PAST` is
likewise mirrored rather than reused, by `FOLLOW_UP_RESCHEDULE_IN_PAST`. The reasoning
behind both — a date in the past is a typo, and a list seeded with already-overdue
dates is a list nobody trusts — is unchanged.

---

## 8. History

Every change to the gauge writes one row in
`onboarding.exporter_lifecycle_history`, through Developer 1's
`HistoryService.record(...)`, **in the same transaction as the column**
(architecture §3.8; `history-row.md` §5).

| Field | Value |
|---|---|
| `dimension` | `conversation` — fixed by `history-row.md` §2. Never invented. |
| `event_type` | `conversation_initial` where a default is recorded at creation, `conversation_transition` for a move — the `<dimension>_initial` / `<dimension>_transition` pair. |
| `source` | `conversation_service.set_conversation`, or `conversation_service.mark_ready_now_for_opened_deal` for seam S1. |
| `from_value` / `to_value` | The enum members' `.value`, as strings. Validated against the enum before writing. |
| `actor_id` | `str(user.id)` from the login session. **Never** from the request body. |
| `reason` | Required for `NOT_NOW` (§4); recorded whenever given. |
| `deal_id` | Set only by seam S1 (§6). `NULL` otherwise. |
| `details.check_back_on` | The check-back date as `YYYY-MM-DD` when the move sets one, `null` when the move clears one. |

**No `conversation_initial` row is written today.** The column arrives with a
`NOT_CONTACTED` default on companies that already exist, and a company created
after 0016 gets that default from the database without a service call. Writing an
`_initial` row for a value nobody chose would put a change in the log that never
happened. The first `conversation` row a company has is its first real move. The
`event_type` is specified above so that a later create path which *does* choose a
starting value has the name already fixed.

---

## 9. What is implemented today

Stated separately so nobody reads this contract as a description of the code.

| Item | State |
|---|---|
| The two columns, the enum, the `CHECK` | **implemented** — 0016, Phase 1 |
| `ConversationService`: the gauge, the rules, history | **implemented** — L3-03, Phase 1 |
| The `NOT_NOW` check-back rule | **implemented** — L3-04a, Phase 1 |
| The gauge routes and the allowed-moves route | **implemented** — L3-03, Phase 1 |
| Seam S1 (`mark_ready_now_for_opened_deal`) | **implemented** — Phase 1; called by `DealService.open_deal` (L3-05), which refuses a `LEAD` first |
| The Conversation panel's gauge control and history | **implemented** — L3-11a-i, Phase 1 |
| Seam S2's "open a deal" **button** | **implemented** — `components/OpenDealPrompt.tsx` opens a deal from `READY_NOW` with the shared `OpenDealForm` (frontend refresh, 28 September 2026) |
| `follow_up_completion` — the table, its FKs, its lock | **implemented** — 0016, Phase 1 |
| `follow_up_completion` — the entity, repository, service and routes | **implemented** — L3-04b, Phase 2 |
| The due/overdue read model | **implemented** — L3-04b, Phase 2 |
| The Follow-ups screen, reachable from the sidebar | **implemented** — L3-11a-ii, Phase 2 |

---

## 10. Acknowledgements

Architecture §7.5 requires the users of a contract to have read it. L3-01a is done
when each of these has confirmed.

| Who | Reads it for | Confirmed |
|---|---|---|
| Developer 3B | Seam S1 (§6) — that they call the service and never write the column | **pending** |
| Developer 2 | §2.1 — a column on their table, and that nothing else in `exporter_profile` is Developer 3's | **pending** |
| Developer 4 | §1 — that the conversation gauge is not the background check, and that neither reads the other | **pending** |
| Developer 3A, Phase 2 | §4, §5, §7 — the completion shape, the check-back column name, the reusable error codes | **confirmed**, 27 September 2026. Built to §5.2 as written, with no amendment to the table. Two notes, both recorded above: a completion writes no history row (§5.7), and the two check-back codes are mirrored rather than reused (§7.1) |
| Developer 1 | The nine shared files' anchors, `exceptions.py`'s new codes (§7), and the register row for 0016 | **pending** |
