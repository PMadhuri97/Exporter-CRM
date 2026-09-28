# Contract — the shared history row

**Owner:** Developer 1 · **Table:** `onboarding.exporter_lifecycle_history` · **Migration:** `onboarding_0013_shared_history`

Every change to a company's journey, to any of its three gauges, to its marker,
and to any of its deals is recorded as one row in this table. One table, one
shape, so "show me everything that ever happened to this company" is one query
instead of a union across five schemas.

This contract is what Developers 2, 3 and 4 write against. Changing it needs the
agreement of all four.

---

## 1. The row

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | `uuid` | no | Primary key, `uuid4`. |
| `customer_id` | `uuid` | no | **The company.** Indexed, no foreign key yet — see §6. |
| `deal_id` | `uuid` | yes | **The deal**, when the change is about one. `NULL` for everything company-level. |
| `dimension` | `varchar(32)` | no | **Which row of the model changed.** Values in §2. |
| `event_type` | `varchar(100)` | no | Why the row was written — see §3. |
| `from_status` | `varchar(64)` | yes | **From value.** `NULL` means "entered at creation". |
| `to_status` | `varchar(64)` | no | **To value.** |
| `actor_id` | `varchar(255)` | yes | **Who.** `str(user.id)` from the login session. `NULL` = the platform itself. |
| `reason` | `text` | yes | **Why**, in the actor's words. Required for the moves §4 marks required. |
| `event_metadata` | `jsonb` | yes | **Details.** Free-shaped; `source` lives here — see §3. |
| `created_at` | `timestamptz` | no | **When.** `server_default now()`. Server-authoritative. |

`from_status` / `to_status` keep their existing names. Renaming them to
`from_value` / `to_value` would read better now that the table carries more than
the journey, but it would touch every writer and reader in a migration whose job
is to add columns, so it is deliberately not done here.

### Values are strings, never enums

`from_status` and `to_status` are `varchar`, and must stay `varchar`.

A history table has to be able to record a value that was **just added** to an
enum without needing its own migration first, and to keep serving a value that
was later **removed**. Making these columns a Postgres enum would mean every new
gauge value is a two-migration change, and would make deleting a value destroy
the history of it. `dimension` is `varchar(32)` for the same reason.

The service validates the value before writing it, so what lands is an enum
member at the time it was stored.

---

## 2. `dimension`

Lower-case snake case. One value per row of the model in section 3 of the
architecture.

| Value | Covers | Owner |
|---|---|---|
| `journey` | `LEAD` → `PROSPECT` → `CUSTOMER` | Dev 2 |
| `qualification` | `NOT_YET_REVIEWED` / `QUALIFIED` / `NOT_QUALIFIED` | Dev 2 |
| `marker` | `PAUSED` / `ENDED` and clearing them | Dev 2 |
| `profile` | Edits to company fields that are not a gauge | Dev 2 |
| `conversation` | `NOT_CONTACTED` … `READY_NOW` | Dev 3 |
| `deal` | `OPEN` / `GATHERING_PAPERWORK` / `HANDED_OVER` / `WITHDRAWN` | Dev 3 |
| `background_check` | `NOT_STARTED` / `IN_REVIEW` / `MORE_INFO` / `CLEAR` / `FLAGGED` / `ON_HOLD` | Dev 4 |
| `verification` | A verification result's status or review changing | Dev 4 |

Adding a dimension needs no migration — add the string here and start writing
it. Adding one **without** adding it here is the thing this table exists to
prevent, because nothing else records what the value means.

`deal_id` is set exactly when `dimension = "deal"`, or when another dimension's
change is about a specific deal. It is `NULL` otherwise.

---

## 3. `event_type` and `source`

`event_type` says why the row exists; today two values are in use, both on the
journey dimension:

| `event_type` | Meaning |
|---|---|
| `lifecycle_initial` | The company was created at this value. `from_status` is `NULL`. |
| `lifecycle_transition` | A recorded move from one value to another. |

A new dimension follows the same pair: `<dimension>_initial` where a default is
recorded at creation, `<dimension>_transition` for a move.

`event_metadata.source` names the code path that wrote the row, as a dotted
string (`exporter_profile_service.transition_lifecycle_status`). It is a column
of `event_metadata` rather than its own column because it is for a human reading
the trail, not something anything queries.

`event_metadata` also carries whatever else the writer wants a reader to have
without a second query. The journey dimension writes `terminal: bool`.

---

## 4. When a reason is required

Section 3 of the architecture requires a reason on these moves. The **service**
enforces it; the column stays nullable because most moves do not need one and a
`NOT NULL` column would force writers to invent text.

| Dimension | Move | Reason |
|---|---|---|
| `marker` | setting `PAUSED` or `ENDED` | required |
| `deal` | → `WITHDRAWN` | required |
| `background_check` | → `MORE_INFO`, `FLAGGED`, `ON_HOLD` | required |
| `background_check` | `CLEAR` → `IN_REVIEW` (reopen) | required |
| `background_check` | `FLAGGED`/`ON_HOLD` → `IN_REVIEW` (reassess) | required |
| `qualification` | → `NOT_QUALIFIED` | reason **codes** required, note optional |

---

## 5. The flush-not-commit rule

> **The history writer flushes. It never commits. The caller owns the transaction.**

This is the rule that makes "the current value and its history change together"
true rather than aspirational. A writer that committed on its own would make two
transactions out of one change, and a crash between them leaves a company whose
gauge says one thing and whose history has no record of it ever moving.

`ExporterProfileService._record_lifecycle` already works this way and its
docstring says so. Every new writer follows it:

```python
profile.lifecycle_status = to_status          # 1. the current value
await self._record_lifecycle(...)             # 2. the history row — flush only
await self._db.commit()                       # 3. one commit, both writes
```

Two consequences worth stating, because both have bitten this repository:

- **An illegal move must leave nothing behind.** Validate before assigning, so a
  rejected move never reaches step 2. `test_a_rejected_transition_writes_no_event`
  covers this for the journey.
- **A cross-service hand-off is not yet one transaction.** Services in this
  repository call `self._db.commit()` themselves, so "Dev 4 records `CLEAR`" and
  "Dev 2 moves the company to `CUSTOMER`" are two commits today. Dev 1 is not
  introducing a unit-of-work primitive — it is not among tasks L1-01..L1-15 —
  so the two developers sharing a hand-off must either pass one session between
  the two service calls or accept that the second can fail after the first
  committed. **Raise this before building the hand-off, not after.**

---

## 6. No foreign key yet

`customer_id` is a bare indexed `uuid`. There is no foreign key to the company,
and migration 0013 does not add one.

Not an oversight: migration **0014 (Dev 2)** recreates the CRM's own tables and
already owns adding the real links for contacts, activities and screening items.
Adding the company link in 0013 would mean 0014 had to drop the constraint
before recreating `exporter_profile` and re-add it afterwards — a hand-off that
buys nothing, because both migrations land in the same week.

**0014 adds `exporter_lifecycle_history.customer_id → exporter_profile` along
with the others.** Until it does, this table has the referential integrity it
has today, which is none. There are currently 1,498 history rows and zero
orphans, so the constraint will apply cleanly when it is added.

---

## 7. Rows cannot be changed or deleted

`trg_exporter_lifecycle_history_append_only` runs
`public.prevent_mutation()` `BEFORE UPDATE OR DELETE`, which raises
unconditionally. `ExporterLifecycleHistoryRepository` extends
`AppendOnlyRepository`, which exposes no `update` and no `delete`.

Both layers are deliberate and both are tested against the database with direct
SQL, not through the ORM. A correction is a **new row**, never an edit.

---

## 8. Indexes

| Index | Serves |
|---|---|
| `ix_exporter_lifecycle_history_customer_id` | Bare `customer_id` lookups. |
| `ix_exporter_lifecycle_history_recent` | One company's whole history, newest first. |
| `ix_exporter_lifecycle_history_to_status` | The ANER-4.2-S1T2 completion hook polling `to_status`. |
| `ix_exporter_lifecycle_history_dimension_recent` | One company's history **filtered to one dimension** — what a gauge panel asks. |
| `ix_exporter_lifecycle_history_deal_recent` | One deal's history. Partial: `WHERE deal_id IS NOT NULL`. |

Ordering is `created_at DESC, id DESC`. `created_at` defaults to `now()`, which
is **transaction** time, so two rows written in one transaction share a
timestamp. The `id` tie-break makes that order deterministic, **not
chronological** — `id` is a random `uuid4`. A writer that records several rows in
one transaction must not rely on this order between them.

---

## 9. What is implemented today

Stated separately so nobody reads this contract as a description of the code.

| Item | State |
|---|---|
| The table, its columns and its indexes | **implemented** (0013) |
| Append-only trigger and repository | **implemented** (0011) |
| Journey `lifecycle_initial` / `lifecycle_transition` rows | **implemented** |
| Flush-not-commit, on the journey writer | **implemented** |
| A shared writer other services call | **not built** — L1-11 part 2 |
| A read route (`GET .../history`) | **not built** — L1-11 part 2 |
| Every dimension other than `journey` | **not built** — Dev 2/3/4 |
| The company foreign key | **not built** — 0014, Dev 2 |

Until the shared writer exists, `ExporterProfileService._record_lifecycle` is the
only writer, and it writes `dimension = "journey"` only.
