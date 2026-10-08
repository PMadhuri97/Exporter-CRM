# Contract — the shared history row

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
| `background_check` | `NOT_STARTED` / `IN_REVIEW` / `MORE_INFO` / `CLEAR` / `FLAGGED` / `ON_HOLD` | Dev 4A |
| `verification` | A verification result's status or review changing. On the timeline of the company the result is **about** (plan P4-5): its own company, or — for a legacy deal-buyer result — the seller's with the deal as context, until the deal-buyer migration maps that buyer to a company; later rows then go to the buyer company, still with the deal | Dev 4B → Dev 1 |
| `screening` | A screening checklist item's decision (`screening_initial` / `screening_transition`; decision D9) | Dev 4B → Dev 1 |
| `check_cycle` | A new background-check cycle started — a Re-KYC or Re-KYB (plan P2-3c). `from_status` / `to_status` are the previous and new cycle **numbers** (`"1"` → `"2"`); `event_type = "check_cycle_started"` | Dev 1 |
| `background_check_approval` | A maker-checker proposal proposed, approved, rejected or withdrawn (plan P3-1b). `from_status` / `to_status` are the **proposal's** status: `null` → `OPEN` (`event_type = "background_check_proposed"`), then `OPEN` → `APPROVED` / `REJECTED` / `WITHDRAWN` (`background_check_approved` / `_rejected` / `_withdrawn`). `actor_id` is the proposer, then the resolver; `reason` the proposal's reason, then the rejection's or withdrawal's. An approval also writes the usual `background_check` row for the decision, whose actor is the decider (the proposer) | Dev 1 |
| `gst_registration` | A GST registration added, reactivated, deactivated, flagged or unflagged (plan P6-2, P6-5). **Written** by `GstRegistrationService` (tasks 3.13, 3.14). `to_value` is the branch's state name; `details` carries the registration id, the **masked** GSTIN, the state and the row's `active`/`flag_status`. A flag and an unflag both carry their `reason` | Dev 3 |
| `trade` | An invoice or a payment outcome recorded (plan P5-3, P5-4). **Written** by `TradeHistoryService` (task 3.19), on the **seller's** timeline, carrying `deal_id` when the invoice came from a deal. Read on the **buyer company's** timeline too, by the same read-side union as its deals (R-23); past trade with no deal stays the seller's. `to_value` is the invoice's currency for `trade_invoice_recorded` and the payment status for `trade_outcome_recorded`; an outcome's `reason` is its evidence note. A relationship's own creation writes no row — it is a consequence of recording a deal's buyer, which already has one | Dev 3 |
| `pipeline` | A company entering or leaving the sales pipeline — created as a buyer-only company, or brought in (plan P4-6, P4-9). **Written** by `CompanyDirectoryService.create_buyer_company` (`NULL` → `NOT_IN_PIPELINE`, with the deal it came from) and by `ExporterProfileService.bring_into_pipeline` (`NOT_IN_PIPELINE` → `IN_PIPELINE`, task 3.11). A buyer-only company's **first** row is on this dimension, not `journey`: it has no journey until it enters the pipeline | Dev 3 |
| `relationship_manager` | A company's relationship manager assigned, reassigned or cleared. **Written** only by `ExporterProfileService.set_relationship_manager` (the RM route, bulk reassignment, the RM set when a check is started or QUALIFIED is recorded, and the legacy-owner backfill). `from_status` / `to_status` are the user ids, or `UNASSIGNED`; `event_type` is `relationship_manager_assigned` / `_reassigned` / `_cleared`; `reason` is required on a change or clear | — |
| `background_check_assignment` | A background-check review claimed, assigned, reassigned, released or ended. **Written** only by `BackgroundCheckService._set_reviewer`. `from_status` / `to_status` are the reviewer ids, or `UNASSIGNED`; `event_type` is `review_claimed` / `review_assigned` / `review_reassigned` / `review_released` / `review_ended`; `reason` is required when a review is taken from someone, optional on a release | — |

The last five were added together in F1 (allocation §2.2, 1 October 2026) so that no
lane edits this list again. In code the list is
`app/modules/onboarding/domain/history_dimensions.py`; a writer imports its constant
from there rather than typing the string, and the frontend's `HistoryDimension` type
and timeline labels carry the same sixteen. `relationship_manager` and
`background_check_assignment` were added on 7 October 2026 (who is working on a company).

Adding a dimension needs no migration — add the string here and start writing
it. Adding one **without** adding it here is the thing this table exists to
prevent, because nothing else records what the value means.

**Who reads what.** The history routes serve every dimension to OPERATIONS,
COMPLIANCE and ADMIN. DEVELOPER does not receive `background_check`,
`verification`, `screening`, `check_cycle`, `background_check_approval` or
`background_check_assignment` rows —
from the page or the total — because decision D8 refuses DEVELOPER the same values,
reasons, review notes and screening comments on those gauges' own routes
(`api/history_router.py`, `history_dimensions.HIDDEN_FROM_DEVELOPER`).
`gst_registration`, `trade` and `pipeline` rows are served to DEVELOPER, so their
writers store identifiers already masked (as `profile` rows do) — except a branch's
`gst_registration_flagged` and `gst_registration_unflagged` rows, and the `flag_status`
detail on the others, which DEVELOPER does not receive (R-47, decision D-05;
`_EVENTS_HIDDEN_FROM_DEVELOPER` in `api/history_router.py`). `trade` rows carry
none at all — an invoice number, a currency and a payment status say nothing about a
company's identity, which is the same reason the trade routes serve no identifiers to
any role (`trade-history.md` §4, IQ-19).

`deal_id` is set exactly when `dimension = "deal"`, or when another dimension's
change is about a specific deal. It is `NULL` otherwise.

---

## 3. `event_type` and `source`

`event_type` says why the row exists. The journey dimension uses these two (the
names are kept from the lifecycle log the table began as); other dimensions follow
the pattern below:

| `event_type` | Meaning |
|---|---|
| `lifecycle_initial` | The company was created at this value. `from_status` is `NULL`. |
| `lifecycle_transition` | A recorded move from one value to another. |

A new dimension follows the same pair: `<dimension>_initial` where a default is
recorded at creation, `<dimension>_transition` for a move.

`event_metadata.source` names the code path that wrote the row, as a dotted
string (`qualification_service.record_outcome`). It is a key of `event_metadata`
rather than its own column because it is for a human reading the trail, not
something anything queries.

`event_metadata` also carries whatever else the writer wants a reader to have
without a second query. The journey dimension writes `terminal: bool` — `true` only
on the move to `CUSTOMER` — and, on that move, `cause`
(`background_check_clear` or `qualification_outcome`), `clearing_decision_id` and
`risk_rating`.

Where a row is about one thing of several, its details name it, and a reader may rely
on these keys (the history screen does, to say what changed rather than only the value
it reached):

| Rows | Keys | Defined in |
|---|---|---|
| `qualification`, `event_type = "qualification_result"` | `criterion_key` (with `result_id`, `criterion_version`) | `criterion-result.md` §6.1 |
| `deal`, `event_type = "deal_buyer_changed"` | `changed`, `buyer_name`, `created` | `deal-and-buyer.md` §7 |
| `screening` | `item_key`, `screening_review_item_id`; since 1 October 2026 also `cycle_id` and `evidence_count` | D9 (`verification-and-screening.md` §5, §11); P2-1b, P2-3a |
| `verification` | `verification_type`, `verification_result_id`; `entity_type` on a result's own rows; `review_id` on `verification_reviewed`; `cycle_id` on a company-subject result recorded since 1 October 2026 | `verification-and-screening.md` §1; P2-3a |
| `background_check` | `decision_id`, `supersedes_decision_id`, `risk_rating`, `evidence_count`; since 1 October 2026 also `cycle_id` and `rules_version`, and (tranche 2) `proposal_id`, `approved_by` (an approved move) and `expires_at` (a `CLEAR`) | `background-check.md` §8 |
| `check_cycle` | `cycle_id`, `kind`, `previous_cycle_id`, `reopen_decision_id` (set when the start reopened a `CLEAR` company) | `background-check.md` §12.3 |
| `background_check_approval` | `proposal_id`, `from_value`, `to_value` (the proposed move); on proposing also `risk_rating`, `based_on_decision_id`, `evidence_count`, `cycle_id`, `rules_version`; on resolving also `proposed_by` and `decision_id` (set on approval) | `background-check.md` §12.5 |
| `relationship_manager` | `from_user_id`, `to_user_id`, `from_user_name`, `to_user_name` (the names as they were), `bulk_run_id` (a bulk reassignment or backfill run; otherwise `null`) | `company-record.md` §2.5 |
| `background_check_assignment` | `from_user_id`, `to_user_id`, `from_user_name`, `to_user_name`, `background_check` (the gauge value at the time) | `background-check.md` §12.8 |

### 3.1 In the read response

The read routes serve a row with the contract's names (`from_value`, `to_value`,
`details` — `event_metadata` minus `source`, which is lifted out) and one field that is
not a column: **`actor_name`**, who acted, by name — the account's full name, or its
email when it has none; DEVELOPER is given the full name only. It is resolved when the
row is read, through the platform's auth facade (`api/actor_names.py`), and never
stored, so a renamed account shows its current name. It is `null` when `actor_id` is
`NULL` (the platform) or names no account with a name to show.

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
| `background_check` | `IN_REVIEW` → `CLEAR` | required (architecture §4.1 step 9; D14) |
| `background_check` | `MORE_INFO` → `IN_REVIEW` (what arrived) | required (architecture §3.3; D14) |
| `background_check` | `CLEAR` → `IN_REVIEW` (reopen) | required |
| `background_check` | `FLAGGED`/`ON_HOLD` → `IN_REVIEW` (reassess) | required |
| `qualification` | → `NOT_QUALIFIED` | reason **codes** required, note optional |
| `relationship_manager` | changing or clearing an RM already set (single or bulk) | required |
| `background_check_assignment` | taking a review from the person who holds it | required |

In short, every background-check move except the start (`NOT_STARTED` →
`IN_REVIEW`) carries text; the database refuses the decision row otherwise
(`ck_background_check_decision_reason`).

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

## 6. The company foreign key

`customer_id` references `exporter_profile.customer_id` (`ON DELETE RESTRICT`):
`fk_exporter_lifecycle_history_customer_id`, added by migration **0014 (Dev 2)**
together with the links from contacts, activities and screening items, and
declared on the model. Migration 0013 deliberately left it bare (decision U3):
adding it there would have forced 0014 to drop and re-add it around recreating
`exporter_profile`.

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
| The shared writer, `HistoryService.record` (flushes, never commits) | **implemented** (L1-11) |
| The read routes, `GET /exporters/{id}/history` and `GET /deals/{id}/history` | **implemented** (L1-11); DEVELOPER does not receive `background_check`, `verification`, `screening`, `check_cycle` or `background_check_approval` rows, nor a row's `risk_rating` or `clearing_decision_id` details — the `CUSTOMER` journey row carries both (D8) |
| The five F1 dimensions (§2) | **all written** (3 October 2026): `check_cycle` (P2-3c) and `background_check_approval` (P3-1b) by Developer 1; `pipeline` (F3, task 3.11), `gst_registration` (tasks 3.13, 3.14) and `trade` (task 3.19) by Developer 3 |
| `actor_name` on every row read (§3.1) | **implemented** (29 September 2026) |
| Every dimension in §2 | **implemented** by its owner's service |
| The move to `CUSTOMER`, with `terminal: true` | **implemented** (L2-11) |
| The company foreign key | **implemented** (0014), declared on the model |

Rows written in one transaction share `created_at` (§8), so the read routes do not
order them chronologically between themselves; each row's `from`/`to` says what it
was.
