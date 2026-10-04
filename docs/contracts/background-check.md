# Contract — the background check

**Owner:** Developer 1 — the compliance engine (`docs/developer-allocation.md` §2.1, from
1 October 2026); built by Developer 4A (task L4-01; Developer 4A's task document was removed on
2 October 2026 — this contract and git history hold it) ·
**Migrations:** `onboarding_0015_bg_check`; `onboarding_0023_dev1_foundation`,
`onboarding_0024_dev1_evidence`, `onboarding_0025_dev1_check_cycle`,
`onboarding_0026_dev1_approval`, `onboarding_0027_dev1_expiry` · **Status:** published
28 Sep 2026; **seam v2** (§12) published 1 October 2026 with F1; **maker-checker, rule B
and Clear expiry** (§12.5–§12.7) 1 October 2026, Developer 1 tranche 2

The company-level background check: its six values, the only moves between them, who may make
each move and what it needs, the locked decision record behind every move, the evidence snapshot
pinned to each decision, the CRM risk rating, the history row, and the read helper other
developers consume.

**Source of truth.** The design PDF (retired on 4 October 2026 as outdated; recover it with `git show 451ef97:docs/Exporter-CRM-Architecture-and-Plan.pdf`) §3.3 ("Gauge 3: Background
check"), §3.5, §3.7, §3.8 and Figure 3, §4.1 steps 8–11, §4.2, decisions 5, 6, 9, 10, assumptions
A1, A3, A5, A8. Where this contract and the architecture disagree, the architecture wins. Where the
architecture is silent, the question is listed in §14 as an open decision and **this contract does
not answer it**.

---

## 1. What this is, and what it is not

Five different things in the CRM sound alike. They are kept apart on purpose:

| Thing | Question it answers | Owner | Where it lives | Moves |
|---|---|---|---|---|
| **Background-check decision** (this contract) | "Is it safe and lawful to work with this company?" | Developer 4A | `background_check_decision`, and the current value on `exporter_profile.background_check` | Only the §3 table; every move is a new locked decision |
| **Verification result** | "What did one check (KYC, KYB, sanctions, bank account …) on one subject find?" | Developer 4B | `verification_result` | Written by adapters; reviewed by compliance |
| **Screening item** | "Has compliance answered one of the eight checklist questions?" | Developer 4B | `screening_review_item` (append-only; latest row per key) | Recorded per item by compliance |
| **Qualification** | "Is this company worth pursuing commercially?" | Developer 2 | `exporter_profile.qualification`, criterion results and outcomes (`criterion-result.md`) | A reviewer's outcome |
| **Journey** | "Where is the company in the relationship: `LEAD`, `PROSPECT`, `CUSTOMER`?" | Developer 2 | `exporter_profile.journey` (`company-record.md` §3.1) | Forward only, never by hand |

- A **background-check decision is not a verification result and not a screening item.**
  Verification results and the eight screening items are **inputs** to a decision. Dev4A reads
  them only through the 4A ↔ 4B seam (§12); it never writes them and never reads their tables.
- A **background-check decision is not qualification.** Screening is never reused as
  qualification, and qualification is never an input to the gauge.
- A **background-check decision never moves the journey.** It is one of the two conditions for
  `PROSPECT → CUSTOMER` (A1), but Developer 2 makes that move (§11.3).
- **Checks are the company's, whatever its role** (decision D, plan P4-5, since 1 October 2026).
  A buyer company is an ordinary company: its checks are recorded on it and feed its own
  background check, never the seller's. A legacy check about a deal's buyer is recorded against
  `deal_buyer.id` (decision 9) and moves no gauge — until the deal-buyer migration (P4-6) maps
  that buyer to a company, when it becomes one of that company's checks (§12.2).

---

## 2. Values

The current value lives on the company record, `exporter_profile.background_check`, Postgres type
`onboarding.background_check_enum`, `NOT NULL DEFAULT 'NOT_STARTED'` (`company-record.md` §2.4).

| Value | Meaning |
|---|---|
| `NOT_STARTED` | No check has been started. The default for every company. |
| `IN_REVIEW` | Compliance is reviewing checks, screening items and documents. |
| `CLEAR` | Compliance has cleared the company, with a risk rating, a reason and an evidence snapshot — proposed by one COMPLIANCE or ADMIN user and approved by **another** (maker-checker, decision A, §12.5). Current for one year by default (§12.7). |
| `MORE_INFO` | Compliance has asked sales for something specific. |
| `FLAGGED` | A concern has been raised. Blocks deal handovers (A5). |
| `ON_HOLD` | A flagged company has been put on hold. Blocks deal handovers (A5). |

**Only Developer 4A writes this column**, through its own service, with the decision row, the
evidence rows and the history row in the same transaction (§9). No other service assigns to it,
including "just to keep it in sync" (`company-record.md` §2.4).

"Prohibited" is not a value. It is recorded as `FLAGGED` (decision 6).

---

## 3. Moves

These are the **only** legal moves (architecture §3.3). Every other move is refused, including a
move to the value already held, and including `CLEAR → FLAGGED`: new information about a cleared
company goes through a reopen (`CLEAR → IN_REVIEW`) and then `FLAGGED` (architecture §4.2).

| # | From | To | Who | Text required | Also needs |
|---|---|---|---|---|---|
| 1 | `NOT_STARTED` | `IN_REVIEW` | OPERATIONS, COMPLIANCE, ADMIN | — | — (the automatic start on RXIL results is **blocked**, §13) |
| 2 | `IN_REVIEW` | `CLEAR` | COMPLIANCE or ADMIN proposes; **a different** COMPLIANCE or ADMIN user approves (§12.5) | **reason** | risk rating; no checks still pending; all screening items answered; evidence recorded (A3; **§14.1**); KYB, AML and sanctions passed in the current cycle (rule B, §12.6) |
| 3 | `IN_REVIEW` | `MORE_INFO` | COMPLIANCE, ADMIN | **note of what is needed** | — |
| 4 | `MORE_INFO` | `IN_REVIEW` | OPERATIONS, COMPLIANCE, ADMIN | **note of what arrived** | — |
| 5 | `IN_REVIEW` | `FLAGGED` | COMPLIANCE, ADMIN — proposed and approved by two users (§12.5) | **reason** | — |
| 6 | `FLAGGED` | `ON_HOLD` | COMPLIANCE, ADMIN — proposed and approved by two users (§12.5) | **reason** | — |
| 7 | `FLAGGED` | `IN_REVIEW` | COMPLIANCE, ADMIN (reassessment) | **reason** | — |
| 8 | `ON_HOLD` | `IN_REVIEW` | COMPLIANCE, ADMIN (reassessment) | **reason** | — |
| 9 | `CLEAR` | `IN_REVIEW` | one COMPLIANCE or ADMIN user (reopen, decision 5) | **reason** | — |

Rules that go with the table:

- **Roles are enforced per move, on the server**, not only per route. OPERATIONS may make moves 1
  and 4 and nothing else. DEVELOPER and API_USER make no move. Moves 2, 5 and 6 take **two
  people** since 1 October 2026 (decision A, IQ-1; §12.5) — the prototype's "one user decides"
  (decision 5) holds only for the other six moves.
- **Text is required and non-blank** on every move except move 1. The service refuses a missing
  or blank text before anything is written, and the database refuses it too (§5.3).
- **The company row is locked** (`SELECT … FOR UPDATE`, `populate_existing`) before any rule is
  evaluated, exactly as `QualificationService._lock_profile` does. Every rule is checked before
  anything is assigned, so a refused move leaves nothing behind.
- **Allowed moves are served by the server** for the calling user, in the shape
  `ConversationService.allowed_moves` and `DealService.allowed_stage_moves` already use, with
  whether text and a risk rating are required. The frontend keeps no move table and no role list.
  This is this gauge's list only; it is not the universal allowed-moves endpoint (U1, unowned).
- **No `background_check_initial` history row.** The column has a default, so every recorded row
  is a transition — the precedent `ConversationService` set (engagement contract §8).

The move table and the text rule are enforced by `BackgroundCheckService` (phase 4A-3 onward) and
also by the database (§5.3), so a write that bypasses the service is still refused.

---

## 4. Reasons and notes

| Move | Text | Source |
|---|---|---|
| → `MORE_INFO` | note of what is needed | architecture §3.3; `history-row.md` §4 |
| `MORE_INFO` → `IN_REVIEW` | note of what arrived | architecture §3.3 — **not** in `history-row.md` §4 (D14) |
| → `FLAGGED`, → `ON_HOLD` | reason | architecture §3.3; `history-row.md` §4 |
| `FLAGGED` / `ON_HOLD` → `IN_REVIEW` | reason | architecture §3.3; `history-row.md` §4 |
| `CLEAR` → `IN_REVIEW` | reason | architecture §3.3; `history-row.md` §4 |
| `IN_REVIEW` → `CLEAR` | reason | architecture §4.1 step 9 — **not** in `history-row.md` §4 (D14) |
| `NOT_STARTED` → `IN_REVIEW` | none | — |

The text is stored once, on the decision's `reason` column, and copied to the history row's
`reason`. `history-row.md` §4 omits two rows the architecture requires; Dev4A enforces the
architecture. Amending that contract's text is Developer 1's (**D14**); nothing in code waits on
it.

---

## 5. The decision record

Architecture §3.3 and Figure 3: "Check decision (locked): company_id, outcome, who (from login),
when, reason, supersedes." Table `onboarding.background_check_decision`, one row per move.

### 5.1 Columns

| Column | Type | Null | Rule |
|---|---|---|---|
| `id` | `uuid` | no | Primary key, `uuid4`. **The decision id every consumer refers to.** |
| `created_at` | `timestamptz` | no | `server_default now()`. |
| `company_id` | `uuid` | no | FK → `exporter_profile.customer_id`, `ON DELETE RESTRICT`. |
| `from_value` | `background_check_enum` | no | The value before the move. |
| `to_value` | `background_check_enum` | no | The value after the move — the decision's **outcome**. |
| `decided_by` | `varchar(255)` | yes | **Who.** `str(user.id)` from the login session, never from a request body. `NULL` only for a platform-originated move, and none exists until RXIL intake (§13). |
| `decided_by_kind` | `background_check_decided_by_kind_enum` | no | `MANUAL` (a person) or `AUTOMATED` (the platform) — the vocabulary `criterion-result.md` uses. Always `MANUAL` in the prototype. |
| `source` | `background_check_decision_source_enum` | no | Where the decision came from: `MANUAL`; `RXIL` is reserved for the blocked intake. |
| `decided_at` | `timestamptz` | no | **When.** `server_default clock_timestamp()`; server time, never supplied by a caller. Wall clock at insert, not transaction start: a move inserts only after it holds the company lock, so `decided_at` follows the chain (a move that waited on the lock cannot sort before its predecessor). |
| `reason` | `text` | yes | **Why.** Required where §4 says so. |
| `risk_rating` | `background_check_risk_enum` | yes | Required on `CLEAR`, refused on every other move (§7). |
| `supersedes_decision_id` | `uuid` | yes | The previous decision for the same company. `NULL` only on the company's first decision. |
| `details` | `jsonb` | no | `DEFAULT '{}'`. Anything a reader needs without a second query. IDs only, never evidence content or PII. |
| `rules_version` | `varchar(64)` | yes | The Clear rules in force when the decision was taken (plan P2-4a, 0025). Every decision since 0025 records `clear-2026-10-01-7items` (`CLEAR_RULES_V2`). **`NULL` = `clear-2026-09-28-8items`** (`CLEAR_RULES_V1`, the eight-item checklist) by the documented read rule: the decisions before 0025 cannot be updated. |
| `cycle_id` | `uuid` | yes | The check cycle the decision was taken in (§12.3, 0025). Composite FK `(cycle_id, company_id)` → `check_cycle(id, company_id)`, so only a cycle of the same company. **`NULL` = the company's cycle 1** by read rule. |
| `proposal_id` | `uuid` | yes | The maker-checker proposal this decision approved (§12.5, 0026). Composite FK `(proposal_id, company_id, decided_by, from_value, to_value)` → the proposal's `(id, company_id, created_by, from_value, to_value)`: the same company, **the proposer as `decided_by`**, the same move. One decision per proposal. `NULL` on a move that needs no approval and on every decision before 0026. |
| `approved_by` | `varchar(255)` | yes | Who approved it, from the login session. Never `decided_by` (`ck_background_check_decision_maker_checker`). |
| `approved_at` | `timestamptz` | yes | When it was approved — the same server timestamp as `decided_at`. `proposal_id`, `approved_by` and `approved_at` are all set or all `NULL`. |
| `expires_at` | `timestamptz` | yes | When a `CLEAR` stops being current (§12.7, 0027): `decided_at` + `CRM_BACKGROUND_CHECK_CLEAR_VALIDITY_DAYS` (default 365), both from one server timestamp. `NULL` on every other move, and on a `CLEAR` before 0027 — **read as `decided_at` + one year** (BQ-5). |

The decision responses (the move and the decision list) also carry **`decided_by_name`**:
who decided, by name — the account's full name, or its email when it has none — resolved
when read through the platform's auth facade (`api/actor_names.py`), never stored. `null`
when no account with a name matches `decided_by`.

### 5.2 Locked

A decision is **never updated and never deleted**. `trg_background_check_decision_append_only`
runs the shared `public.prevent_mutation()` guard `BEFORE UPDATE OR DELETE … FOR EACH STATEMENT`,
the same guard every other append-only table in this repository uses; the repository class is an
`AppendOnlyRepository`, which exposes no update and no delete. A correction, reopen or
reassessment is a **new** decision that supersedes the previous one. The original row is unchanged
in the database.

### 5.3 What the database enforces

| Constraint | Invariant |
|---|---|
| `fk_background_check_decision_company_id` | A decision belongs to a real company; the company cannot be deleted while it has decisions (`RESTRICT`). |
| `ck_background_check_decision_move` | `(from_value, to_value)` is one of the nine §3 moves. |
| `ck_background_check_decision_reason` | Every move except `NOT_STARTED → IN_REVIEW` carries a non-blank `reason`. |
| `ck_background_check_decision_clear_risk` | `to_value = 'CLEAR'` carries a `risk_rating`. |
| `ck_background_check_decision_risk_only_on_clear` | Only `to_value = 'CLEAR'` carries a `risk_rating` (added in the PR review, 28 Sep 2026 — see §7). |
| `ck_background_check_decision_decided_by` | A `MANUAL` decision names a non-blank `decided_by`. |
| `ck_background_check_decision_first` | `supersedes_decision_id IS NULL` exactly when `from_value = 'NOT_STARTED'`: the first decision is the start, and every later decision names its predecessor. |
| `uq_background_check_decision_first_per_company` | Partial unique index on `company_id WHERE supersedes_decision_id IS NULL`: one chain per company. |
| `uq_background_check_decision_supersedes` | Unique `supersedes_decision_id`: a decision has at most one direct successor, so two concurrent moves cannot fork the chain. |
| `fk_background_check_decision_supersedes` | Composite FK `(supersedes_decision_id, company_id, from_value)` → `(id, company_id, to_value)`, `RESTRICT`: the predecessor is a decision **of the same company**, and this move starts from **the value that decision ended at**. |
| `trg_background_check_decision_append_only` | No `UPDATE`, no `DELETE`. |
| `ck_background_check_decision_approval` | `proposal_id`, `approved_by`, `approved_at`: all or none (0026). |
| `ck_background_check_decision_maker_checker` | `approved_by IS NULL OR approved_by <> decided_by` — the database refuses self-approval (0026). |
| `fk_background_check_decision_proposal`, `uq_background_check_decision_proposal` | An approved decision names a proposal of the same company, proposer and move; at most one decision per proposal (0026). |
| `ck_background_check_decision_expiry` | Only a `CLEAR` carries `expires_at`, and it is after `decided_at` (0027). |

Together these make the decisions of one company a single unbroken chain,
`NOT_STARTED → … → current`, that can only be extended at its head. Whether the head's `to_value`
equals the company's current `background_check` is kept by the service writing both in one
transaction (§9); it is not a database constraint.

### 5.4 Chain semantics

- **Latest decision** = the chain head: the company's decision that no other decision supersedes.
- **Superseded** = named by a later decision's `supersedes_decision_id`. It stays readable and
  unchanged forever.
- **Clearing decision** = the head, when the head's `to_value` is `CLEAR`. After a reopen there is
  no current clearing decision.

---

## 6. The evidence snapshot

Architecture §3.3: "At the moment of each decision, the IDs of the documents and check results it
relied on are stored with it." Table `onboarding.background_check_evidence`, one row per pinned
item, written in the decision's transaction.

| Column | Type | Null | Rule |
|---|---|---|---|
| `id` | `uuid` | no | Primary key. |
| `created_at` | `timestamptz` | no | `server_default now()`. |
| `decision_id` | `uuid` | no | FK → `background_check_decision.id`, `RESTRICT`. |
| `kind` | `background_check_evidence_kind_enum` | no | `DOCUMENT`, `VERIFICATION_RESULT` or `SCREENING_ITEM`. |
| `crm_document_id` | `uuid` | yes | FK → `crm_document.id`, `RESTRICT`. Set exactly when `kind = DOCUMENT`. |
| `verification_result_id` | `uuid` | yes | FK → `verification_result.id`, `RESTRICT`. Set exactly when `kind = VERIFICATION_RESULT`. |
| `verification_review_id` | `uuid` | yes | The review the result's standing rested on. **A bare uuid, no foreign key** (§6.1). Allowed only when `kind = VERIFICATION_RESULT`. |
| `screening_review_item_id` | `uuid` | yes | FK → `screening_review_item.id`, `RESTRICT` — the exact checklist row, since screening rows keep being added after a decision. Set exactly when `kind = SCREENING_ITEM`. |

Rules:

- **IDs only, never content.** No file bytes, no provider payloads, no checklist comments.
- **No second document system.** Documents are Developer 3B's `crm_document` rows
  (`storage-and-documents.md`). The snapshot stores their ids and nothing else.
- **Every decision** takes a snapshot, not only `CLEAR` (the architecture says "each decision").
  A snapshot may be empty (move 1, for a company with no inputs yet).
- **Locked.** `trg_background_check_evidence_append_only` refuses `UPDATE` and `DELETE`; the
  `RESTRICT` foreign keys mean a pinned document, result or screening row cannot be deleted from
  under a decision. A later upload, result or checklist answer never changes a past snapshot.
- **Constraints:** `ck_background_check_evidence_kind` (exactly the columns for the kind);
  `uq_background_check_evidence_document`, `uq_background_check_evidence_verification`,
  `uq_background_check_evidence_screening` (an item appears at most once per decision).
- **Inputs** come from Developer 4B's reader (§12) and from Developer 3B's document list
  (`CrmDocumentRepository.list_for_owner` / `list_for_deal_ids`). Dev4A never queries Developer
  4B's tables. The foreign keys above are referential integrity, not reads.
- **What** goes into the snapshot — which documents (company only, or also open deals; only
  `AVAILABLE` ones) and what counts as "evidence recorded" for `CLEAR` — was **D4**, settled 28
  September 2026: the company's own `AVAILABLE` documents, and at least one pinned id of any
  kind for `CLEAR` (§14.1). The shape
  above holds whatever D4 decides.
- Since seam v2 the snapshot pins the **current cycle's** inputs only (§12).

### 6.1 Why the review id has no foreign key

The superseding-review table (`verification_review`) arrived in `onboarding_0021_verif_review`,
written in parallel with this contract's `onboarding_0015_bg_check`; a foreign key would have made
one migration depend on the other, and they were kept independent on purpose. Snapshots taken
before 0021 merged hold `NULL` here even for a reviewed result, because the seam reported
`latest_review_id = None` until then. A foreign key could be added now; nobody has needed it.

### 6.2 Reading a decision's evidence (plan P2-1a)

`GET /exporters/{company_id}/background-check/decisions/{decision_id}/evidence` resolves each
pinned id into a readable item (`application/decision_evidence.py`), so a reviewer sees what a
decision rested on rather than a count:

| Kind | Served |
|---|---|
| `VERIFICATION_RESULT` | type, status, risk, provenance (`MANUAL`/`STUB`/`PROVIDER`), placeholder flag, `performed_at`, who recorded it (the actor of its first `verification` history row; `null` for a result older than the log), `evidence_note`, `evidence_refs`, the **pinned** review (status, who, when, note) and `review_superseded` (a later review exists), cycle |
| `SCREENING_ITEM` | the exact pinned row: key, label, `retired` (the item has since left the checklist — `website-reviewed` keeps its label so an eight-item decision still reads), status, comment, `evidence_refs`, who answered and when, cycle |
| `DOCUMENT` | file name, category, type, scan status, `is_downloadable`, uploader and time |

The response also names the decision's `rules_version` (legacy rule applied) and cycle. **No
identifier** is carried — a result's `subject_snapshot`, `raw_result` and `normalized_result` are
not resolved. Staff only; DEVELOPER is refused (D8); a decision of another company is the same 404
as one that does not exist (`BACKGROUND_CHECK_DECISION_NOT_FOUND`).

---

## 7. Risk

| | |
|---|---|
| **Values** | Exactly `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` (decision 6). |
| **Database type** | `onboarding.background_check_risk_enum` — **owned by Developer 4A** and created in `onboarding_0015_bg_check`. **D13, settled 28 Sep 2026:** Developer 4B's `verification_risk_level_enum` is **not** reused, so neither Dev4 migration depends on the other's schema. |
| **Where** | On the **decision** (`background_check_decision.risk_rating`). Set by compliance as part of the decision (architecture §3.3, A3, §4.1 step 9). |
| **Required** | On `CLEAR` — by the service and by `ck_background_check_decision_clear_risk`. |
| **On the company record** | **None** (**D5**, settled). There is no company-level risk column. The current risk is read from the decisions through the read helper (§10). |
| **On other outcomes** | **Refused** — `422 BACKGROUND_CHECK_RISK_NOT_ALLOWED` in the service and `ck_background_check_decision_risk_only_on_clear` in the database. Risk is compliance's rating at the moment of clearing. While it was merely "not refused", any move carried one — including an OPERATIONS start — and the reader (§10) reported it as the company's risk. Found and closed in the Dev4A PR review, 28 Sep 2026 (D5 row, §14). |
| **After a reopen** | The last clearance's risk, explicitly labelled (**D6**, settled). |
| **On screen** | `CRITICAL` must look different (architecture §3.3, L4-08). |

This is the CRM background-check risk vocabulary. It changes no existing risk type:
`customers.risk_rating_enum`, `review_risk_rating_enum`, `onboarding_risk_rating_enum` and
`verification_risk_level_enum` are untouched. "Prohibited" is an outcome (`FLAGGED`), never a risk
value.

---

## 8. History

Every move writes **one** row through Developer 1's `HistoryService.record(...)` (`history-row.md`),
in the same transaction as the current value, the decision and the evidence — the service flushes,
never commits separately, and commits once (`history-row.md` §5).

| History column | Value |
|---|---|
| `dimension` | `background_check` |
| `from_status` / `to_status` | the move, as strings |
| `actor_id` | the decision's `decided_by` |
| `reason` | the decision's `reason` |
| `event_type` | left to `HistoryService` (derives `background_check_transition`) |
| `event_metadata.source` | `background_check_service.<method>` |
| `event_metadata` | at least `decision_id`, `supersedes_decision_id`, `risk_rating` (when set) and the evidence count |

- `event_metadata` carries **ids, never evidence content or PII**.
- The history route admits DEVELOPER (`history_router.py`). What free text DEVELOPER may read —
  the `reason` on these rows — is **D8**, settled 28 Sep 2026: DEVELOPER is refused on every
  background-check route. The history route's own `reason` policy is Developer 1's (§14, D8).
- Dev4A does not edit `history_service.py` or the history contract.

---

## 9. One transaction per move

A move, when built (phase 4A-3), does exactly this, in order, in one session:

1. lock the company row `FOR UPDATE`;
2. check the move, the role, the text and (for `CLEAR`) the prerequisites — nothing is assigned
   yet;
3. read the inputs through the 4A ↔ 4B seam (§12) in the same session;
4. insert the decision, then its evidence rows;
5. assign `exporter_profile.background_check`;
6. write the history row (flush only);
7. commit once.

A refusal at step 2 or 3 leaves nothing behind. A failure after step 4 rolls everything back
together.

---

## 10. The read helper

Developer 4A publishes a stable read seam for Developer 3's handover guard and Developer 2's
customer move. **Built in phase 4A-6** (`application/background_check_reader.py`), and Developer
3's guard reads the real column through it.

```python
# app/modules/onboarding/application/background_check_reader.py   (owner: Dev4A)

@dataclass(frozen=True)
class BackgroundCheckStanding:
    company_id: uuid.UUID
    value: str                              # one of the six §2 values
    risk_rating: str | None                 # of the latest decision that set one (see D6)
    latest_decision_id: uuid.UUID | None    # None while NOT_STARTED with no decision
    clearing_decision_id: uuid.UUID | None  # the decision that made the current CLEAR; None unless value == "CLEAR"
    decided_at: datetime | None

def current_background_check(company: ExporterProfile) -> str:
    """Pure, no I/O: the loaded company's current gauge value as a string."""

class BackgroundCheckReader:
    def __init__(self, db: AsyncSession) -> None: ...
    async def standing(self, company_id: uuid.UUID) -> BackgroundCheckStanding: ...
```

- **Semantics:** a read of committed or flushed state in the caller's session. It never commits,
  never flushes and **never locks**; the caller owns locking.
- **Errors:** an unknown company raises `ExporterProfileNotFoundError` (existing, Developer 2's).
- **"Not `CLEAR`" is never treated as "clear".**
- `risk_rating` is the risk of the latest decision that set one — only `CLEAR` decisions can
  (§7) — so after a reopen it is the last clearance's rating, to be labelled as such (**D6**,
  settled). A consumer must read `value` to know whether the company is clear.

---

## 11. Relationships

### 11.1 Journey

The background check never moves the journey. A `CUSTOMER` whose check is reopened, flagged or put
on hold **stays** `CUSTOMER` (`company-record.md` §3.1, A5). Dev4A writes no journey value.

### 11.2 Deal handover (Developer 3)

**The guard share-locks the company row while a handover is in progress** (D10, settled 28
September 2026). Developer 3's `_handover_blocked_reason` takes `SELECT … FOR SHARE` on
`exporter_profile` when called from `transition_stage`, and **no lock** when called from the read
that renders a deal.

Why a lock at all: Dev4A's own moves take `FOR UPDATE`, so without one a `FLAGGED` could commit
between the guard seeing `CLEAR` and the handover committing, and the lending team would be given
a deal on a company flagged moments earlier — with nothing in the record showing the overlap. A
handover cannot be undone, which is what makes the narrow window worth closing.

Why `FOR SHARE` rather than `FOR UPDATE`: it blocks Dev4A's writers, which is the point, while
two handovers of *different deals on the same company* still proceed in parallel.

Why not on the read: `_to_view` runs on every deal page load. Locking there would have ordinary
rendering block compliance's decisions — the opposite of the intent.

A deal is handed over only when the company is `CUSTOMER` **and** its check is `CLEAR` (A5). The
guard and the handover are Developer 3's. Dev4A's part is the read helper (§10):

- `deal_service.read_background_check(company)` is Developer 3's stand-in. Once the column exists
  (4A-2) it returns the real value — `"NOT_STARTED"` for every company until a move is recorded —
  so every handover is refused with "the background check is NOT_STARTED, not CLEAR".
- In phase 4A-6 its body becomes `return current_background_check(company)`, with Developer 3's
  review. Its name and signature do not change. (Built in 4A-6; the D10 lock below and the
  docstrings the swap made false were also changed in `deal_service.py` — **Developer 3 review
  required**.)
- The `clear_background_check` fixture in `test_l3b_handover.py` stays until a real `CUSTOMER` can
  be produced (L2-11).
- **D10, settled 28 Sep 2026:** Developer 3's guard share-locks the company row (`FOR SHARE`) on
  the handover move, and takes no lock on the read that renders a deal. Dev4A's moves take
  `FOR UPDATE`, so a reopen issued while a handover is in flight waits for the handover to commit.
  Proved by a two-session test (`test_l4a_background_check_reader.py::TestTheHandoverLock`) that
  fails if the lock is removed.

### 11.3 Customer transition (Developer 2)

`PROSPECT → CUSTOMER` happens when the company is `PROSPECT` and its check is `CLEAR`, whichever
becomes true second (A1). Developer 2 makes the move (L2-11) and it announces
`company.became_customer`, whose payload carries `risk_rating` and `clearing_decision_id`
(`event-envelope.md` §3) — both read from `BackgroundCheckReader.standing`.

**One transaction (U4 / D11, implemented 29 September 2026 on the audit's recommendation; the
programme lead to confirm).** When a move reaches `CLEAR`, `_move` calls Developer 2's
`ExporterProfileService.promote_to_customer_if_ready` at step 7b — after the history row, before the
single commit, under the row lock already held — and publishes the announcement after the commit.
The other order (cleared first, qualified second) is Developer 2's `QualificationService`, calling
the same method. Dev4A still never writes `journey`; a reopen, flag or hold never demotes a
customer. See `company-record.md` §3.2.

---

## 12. The compliance-inputs seam — v2

The inputs to a decision — the screening items and the verification results whose subject
is the company — are read **only** through `ComplianceInputsReader`
(`backend/app/modules/onboarding/domain/compliance_inputs.py`), implemented by
`ComplianceInputsService` (`application/compliance_inputs.py`). v1 was agreed between
Developers 4A and 4B on 28 September 2026 and frozen. **v2 is the one deliberate revision**
(plan P0-2, allocation F1, 1 October 2026), designed once for cycles (decision E), company-level
checks (decision D) and the rules version, so the contract does not change three times. The
verification and screening rules behind the inputs are `verification-and-screening.md`.

### 12.1 Shape

The v1 fields, then three fields **appended** in v2, each with a `None` default so every v1
construction still builds (`unit/test_l4b_compliance_inputs_contract.py` pins the whole shape):

```python
@dataclass(frozen=True)
class VerificationInput:
    verification_result_id: uuid.UUID
    verification_type: str                # VerificationType value
    entity_type: str                      # "EXPORTER" in company_inputs; "BUYER" in buyer_checks
    provider: str                         # stored provider, verbatim
    status: str                           # PENDING | PASSED | FAILED | REVIEW
    risk_level: str | None
    performed_at: datetime
    is_placeholder: bool                  # created without a provider (normalized_result.stub)
    latest_review_id: uuid.UUID | None    # the head of the review chain
    latest_review_status: str | None      # ACCEPTED | REJECTED | ESCALATED
    latest_reviewed_at: datetime | None
    evidence_document_ids: tuple[uuid.UUID, ...]
    cycle_id: uuid.UUID | None = None     # v2: the result's cycle; a legacy row reports cycle 1's id

@dataclass(frozen=True)
class ScreeningItemInput:
    item_key: str
    screening_review_item_id: uuid.UUID | None   # the latest row; None if never recorded
    status: str | None                           # NEEDS_REVIEW | PASSED | FAILED | EXEMPT | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    cycle_id: uuid.UUID | None = None     # v2: the cycle of the latest row; None with no row this cycle

@dataclass(frozen=True)
class CompanyComplianceInputs:
    company_id: uuid.UUID                 # the SUBJECT company
    screening_catalogue: tuple[str, ...]  # seven keys since P2-4a
    screening_items: tuple[ScreeningItemInput, ...]
    verifications: tuple[VerificationInput, ...]
    current_cycle_id: uuid.UUID | None = None   # v2: the cycle the inputs are scoped to

class ComplianceInputsReader(Protocol):
    async def company_inputs(self, company_id: uuid.UUID) -> CompanyComplianceInputs: ...
    async def buyer_checks(self, deal_buyer_id: uuid.UUID) -> tuple[VerificationInput, ...]: ...  # legacy
```

Still facts, not judgements: no field says "ready", "pending", "answered" or "clear".

**Invariants** (unchanged since v1):

1. **Facts, not judgements.** "Pending", "answered" and "ready to clear" are this contract's
   rules (D1–D3, §14.1), applied by the background check; adding a judgement field to the seam is
   a contract change.
2. **Read-only** in the caller's session (§12.2).
3. **Buyer isolation.** Nothing `buyer_checks` returns is ever part of `company_inputs`, and the
   background check never reads it (architecture §3.5, decision 9).
4. **Stable latest.** "Latest review" and "latest screening row" are deterministic
   (`created_at DESC, id DESC`).
5. **Serialisation.** The background check reads under its company `FOR UPDATE`; every writer
   of a company-scoped input takes `FOR SHARE` on the company row first, so a `CLEAR` and a new
   pending input cannot interleave.
6. **One way in.** The background-check code reads inputs only through the reader — it never
   imports the verification or screening repositories or reads their tables directly.
7. **The shape only grows.** A change appends a field with a default (as v2 did); nothing is
   removed or retyped.

**Errors:** an unknown company raises `ExporterProfileNotFoundError` (404); an unknown
`deal_buyer_id`, `ComplianceInputsBuyerNotFoundError` (404); a company with no inputs is a valid
empty value (every catalogue item with `status = None`, no verifications); a database error
propagates.

### 12.2 What the reads mean

- **`company_inputs(company_id)` is scoped to the current cycle** (plan P2-3b): the results of that
  cycle and the latest answer per catalogue item **in that cycle**. A new cycle therefore starts
  with every item unanswered and no results, and a placeholder left in an earlier cycle no longer
  blocks `CLEAR`. A company with no cycle row yet is read whole, as before cycles existed.
- **Keyed by the subject company (plan P4-5).** `company_id` is the company the checks are
  *about*: `verification_result.subject_company_id = company_id`, or — for a row recorded before
  checks were company-keyed — `subject_company_id IS NULL AND entity_type = EXPORTER AND
  entity_reference = company_id` (`verification_result.about_company`, served by a `BitmapOr` of
  `ix_verification_result_subject_company_id` and the entity index). `subject_company_id`
  (migration 0023: nullable, FK, **set once then frozen** by
  `trg_verification_result_input_immutability`) is written on **every new company-subject
  result** — a seller, a buyer-only company, both — and on a legacy deal-buyer result when the
  deal-buyer migration (P4-6, Developer 2) maps its buyer to a company. Existing rows are never
  rewritten by this rule. The same rule keys every read: the seam, the facts, the company's
  `GET /verifications?entity_type=EXPORTER` list (which serves `subject_company_id`), the cycle a
  result is stamped in and read as, the company lock a writer takes, and the timeline a later
  review is recorded on (a mapped buyer result's goes to its company, with the deal as context).
  One set of checks per company, wherever it appears.
- **`buyer_checks(deal_buyer_id)` is legacy.** It serves deals whose buyer is still a `deal_buyer`
  row, and is replaced by `company_inputs(buyer_company_id)` once a deal names a buyer company
  (P4-4/P4-5). Legacy buyers have no background check and no cycles: `cycle_id` is `None`.
- Read-only in the caller's session; never commits, flushes or locks. Writers of company-scoped
  inputs take `FOR SHARE` on the company row, so a move under `FOR UPDATE` reads a stable set.
- `latest_review_id` / `latest_review_status` are the head of the result's review chain.

### 12.3 Check cycles (plan P2-3a–d, decision E, IQ-3)

`onboarding.check_cycle` (migration 0025, **append-only**): `id`, `company_id` (FK, `RESTRICT`),
`number` (1, 2, 3 … — unique per company; the **current** cycle is the highest), `kind`
(`INITIAL` = cycle 1 and only cycle 1; `RE_KYC`, `RE_KYB`; `FULL` reserved), `reason` (required
from cycle 2), `started_at`, `rules_version`, and BQ-7's `created_by`, `created_at`, `source`,
`source_ref`.

- **`cycle_id`** on `verification_result`, `screening_review_item` and `background_check_decision`
  (nullable). Every new company-subject result, answer and decision carries it, stamped under the
  company lock. **`NULL` = the company's cycle 1** by the documented read rule — existing rows are
  never updated. The migration inserted one cycle-1 row (`source = 'MIGRATION'`) per company that
  already had an input or decision, dated at the earliest; a company's first input or decision
  after that creates its cycle 1 (`source = 'FIRST_INPUT'`).
- **Starting a cycle** — `POST /exporters/{id}/background-check/cycles {kind, reason}`, COMPLIANCE
  and ADMIN only (`BackgroundCheckService.start_cycle`), one transaction under the company's
  `FOR UPDATE`:

  | Gauge | Effect |
  |---|---|
  | `NOT_STARTED`, `IN_REVIEW`, `MORE_INFO` | the new cycle starts; the gauge does not move |
  | `CLEAR` | the new cycle starts **and** the reopen `CLEAR → IN_REVIEW` is recorded in it, reason `"Re-KYC: …"` / `"Re-KYB: …"` (IQ-3), so handovers pause until it is cleared |
  | `FLAGGED`, `ON_HOLD` | refused, 409 `CHECK_CYCLE_NOT_ALLOWED` — reassess first |

  A cycle with nothing recorded in it (no result, no answer) cannot be followed by another: 409
  `CHECK_CYCLE_EMPTY`. That is also why two simultaneous starts make **one** cycle.
  History: one `check_cycle` row (`"1"` → `"2"`, `event_type = "check_cycle_started"`), plus the
  reopen's `background_check` row on a `CLEAR` company.
- **Reads** — `GET …/background-check/cycles` (staff); the standing serves `current_cycle` and
  `allowed_cycle_actions` (the Re-KYC / Re-KYB buttons, empty when a start would be refused);
  decisions, results and screening answers carry their (resolved) `cycle_id`; the checklist is
  listed per cycle (`?cycle_id=`), earlier cycles read-only.

### 12.4 `ComplianceFactsReader` — the facts other lanes read (F1)

Published in `domain/compliance_facts.py`, implemented by `application/compliance_facts.py`, for
Developer 2's handover guard and Developer 3's promotion:

```python
for_company(company_id, now) -> PartyComplianceFacts
for_legacy_buyer(deal_buyer_id, now) -> PartyComplianceFacts

PartyComplianceFacts:
    background_check: BackgroundCheckValue   # the gauge ("NOT_STARTED" for a legacy buyer)
    is_clear: bool                           # background_check == "CLEAR"
    clear_expires_at: datetime | None        # the clearing decision's expires_at (P3-3a); before 0027, + 1 year (BQ-5)
    is_clear_current: bool                   # is_clear and now < clear_expires_at
    sanctions: CheckState                    # PASSED | FAILED | MISSING | PENDING
    aml: CheckState
```

`now` is always the caller's (from `app.shared.clock`). Sanctions and AML are the latest real
result of that type **in the current cycle** (IQ-2): `PASSED`, or `REVIEW` with an `ACCEPTED`
review → `PASSED`; `FAILED`, or `REVIEW` with a `REJECTED` review → `FAILED` (*the latter is this
contract's reading, for the lead to confirm*); unreviewed/`ESCALATED` `REVIEW` or `PENDING` →
`PENDING`; none, or placeholders only → `MISSING`. The standing route serves the same facts as
`compliance` for the `CompanyComplianceSummary` component.

`ExporterProfileService.promote_to_customer_if_ready` requires `facts.is_clear_current` (IQ-18):
a `PROSPECT` whose Clear has expired is not promoted.

`clear_expires_at` is the clearing decision's stored `expires_at` since P3-3a (§12.7), the legacy
rule only for a Clear recorded before migration 0027. `exporter_profile.background_check_expires_at`
(nullable, indexed; 0023) is written on every `CLEAR`, cleared on every move away, and was
backfilled by 0027 for the companies already `CLEAR`; the Re-KYC due list reads it.

The reader is read-only and never locks (the caller locks); `now` must be timezone-aware.

| State | `background_check` | `is_clear` | `is_clear_current` |
|---|---|---|---|
| Never checked | `NOT_STARTED` | false | false |
| A CLEAR awaiting approval (the gauge does not move) | `IN_REVIEW` | false | false |
| The CLEAR proposal rejected | `IN_REVIEW` | false | false |
| Approved, within validity | `CLEAR` | true | **true** |
| Approved, past `clear_expires_at` (no automatic gauge move) | `CLEAR` | true | false |
| Re-KYC started (a new cycle reopens the Clear) | `IN_REVIEW` | false | false |
| Flagged / on hold | `FLAGGED` / `ON_HOLD` | false | false |

`for_legacy_buyer` reads the `deal_buyer`'s own results, without cycles. A consumer tests
against the fake, never against Developer 1's code:

```python
from app.modules.onboarding.tests.fixtures.compliance import StaticComplianceFactsReader, party_facts

reader = StaticComplianceFactsReader(
    companies={seller: party_facts(), buyer: party_facts("NOT_STARTED", sanctions="FAILED")},
    legacy_buyers={deal_buyer_id: party_facts("NOT_STARTED", aml="MISSING")},
)
expired = party_facts(clear_expires_at=at, is_clear_current=False)   # an expired Clear
```

### 12.5 Maker-checker (plan P3-1, decision A, IQ-1, IQ-17)

**Proposal records; the gauge does not move** (the plan's recommended design). A move to
`CLEAR`, `FLAGGED` or `ON_HOLD` — and no other (IQ-1) — is first a **proposal**:

1. `POST …/background-check/decisions` with one of those values answers **202** with the proposal
   instead of a decision. Every rule the move checks is applied now (premise, legality, role, text,
   risk), and for `CLEAR` its prerequisites too — a proposal that could never be approved is
   refused when it is made, naming what is missing. The proposal stores the chain head it rests
   on, the SHA-256 **fingerprint** of the evidence selection (each result's status and review
   head, each screening row, the pinned documents, the cycle), the cycle and the rules version.
   The gauge stays `IN_REVIEW` (or `FLAGGED` for a proposed `ON_HOLD`); the read serves
   `awaiting_approval` and `open_proposal`.
2. `POST …/proposals/{id}/approve` — COMPLIANCE or ADMIN, **never the proposer** (403
   `BACKGROUND_CHECK_SELF_APPROVAL`) — locks the company, refuses a resolved proposal (409) and a
   **stale** one (409 `BACKGROUND_CHECK_PROPOSAL_STALE`: the gauge, the chain head or the
   fingerprint moved), then writes the decision through the same path every move takes (§9):
   `decided_by` = proposer, `approved_by` = approver, the evidence pinned, `CLEAR`'s prerequisites
   evaluated again, the expiry set, a qualified `PROSPECT` promoted — one transaction, announced
   after the commit.
3. `…/reject` needs a reason and is anyone's but the proposer's; `…/withdraw` is the proposer's
   alone (403 `BACKGROUND_CHECK_PROPOSAL_NOT_YOURS`). Neither moves the gauge. A stale proposal can
   still be rejected or withdrawn — that is how it is cleared away.

Rules that go with it:

- **One open proposal per company**, under the company row lock. While one is open **nothing else
  moves the check** — no second proposal, no other move, no new cycle (409
  `BACKGROUND_CHECK_PROPOSAL_OPEN`); the read offers no move and no cycle action. Inputs may still
  be recorded: they make the proposal stale.
- **No path lets one user take a company to `CLEAR`, `FLAGGED` or `ON_HOLD`.** The one place a
  decision is written (`BackgroundCheckService._apply_move`) refuses those moves unless the call
  comes from an approval (409 `BACKGROUND_CHECK_APPROVAL_REQUIRED`), and the database refuses a
  decision approved by its decider.
- **Served actions, role- and user-aware.** The open proposal carries `allowed_actions` for the
  caller: the proposer `WITHDRAW`; another COMPLIANCE/ADMIN user `APPROVE`, `REJECT` (only
  `REJECT` when stale); OPERATIONS nothing. Each `allowed_moves` entry says `approval_required`.
- **The queue**: `GET /background-check/proposals?status=open` (COMPLIANCE, ADMIN; oldest first;
  `awaiting=me` leaves out the caller's own — the Home card "Proposals awaiting me"); `status` may
  also be `approved`, `rejected`, `withdrawn` (newest first). A company's own:
  `GET /exporters/{id}/background-check/proposals` (staff).
- **Tables** (0026, both append-only, BQ-7 provenance): `background_check_proposal` (`created_by` is
  the proposer, `created_at` when proposed) and `background_check_proposal_resolution` (at most one
  per proposal; `outcome` `APPROVED`/`REJECTED`/`WITHDRAWN`; `created_by` the resolver; a copy of
  `proposed_by` pinned by a composite FK, so `(outcome = 'WITHDRAWN') = (created_by =
  proposed_by)` holds inside one row; `decision_id` exactly on `APPROVED`).
- **History**: dimension `background_check_approval` (`history-row.md` §2); DEVELOPER does not
  receive it (D8).
- **The switch** `CRM_BACKGROUND_CHECK_MAKER_CHECKER` (IQ-17): on by default; off is accepted only
  where `ENVIRONMENT` is `local` or `test` (IQ-17 literally) — the application refuses to start
  with it off anywhere else, **including `development`**, which is `ENVIRONMENT`'s default and
  what `.env.example` (and so the docker-compose stack) sets
  (`compliance_settings.enforce_compliance_settings`). Off, the three moves are recorded
  directly, as before.

### 12.6 Rule B — KYB, AML and sanctions passed (plan P3-2, decision B, IQ-2)

`ClearPolicy.required_passed_types = ("KYB", "AML", "SANCTIONS")`. Each must have **passed in the
current cycle**, by IQ-2's meaning (the same `compliance_facts.check_state` the facts use): the
latest non-placeholder result of that type is `PASSED`, or `REVIEW` with an `ACCEPTED` review; the
latest result wins; placeholders never count. A refusal names each missing one —
`kyb_passed`, `aml_passed`, `sanctions_passed` — after A3's four. Only the company's own
(`EXPORTER`) results count: another company's or a deal buyer's do not. The read serves
`required_checks` (`[{verification_type, state}]`) so the screen keeps no list of its own. Every
decision, proposal and cycle since records `rules_version = clear-2026-10-01-7items-kyb-aml-sanctions`
(`CLEAR_RULES_V3`). Legacy deal buyers (`for_legacy_buyer`) are unaffected.

### 12.7 Clear expiry and Re-KYC due (plan P3-3, decision E, BQ-5, IQ-18)

- **Stored** (P3-3a): every new `CLEAR` decision carries `expires_at` (§5.1) and the company's
  `background_check_expires_at` takes the same value; any move away clears the company column.
  Migration 0027 **backfilled** that column for the companies already `CLEAR` — from the last CLEAR
  decision, `decided_at` + one year (BQ-5) — with a dry run and a validation query.
- **Read, never moved** (P3-3b): `BackgroundCheckStanding.expires_at` and
  `is_clear_and_current(now)`; `ComplianceFactsReader.clear_expires_at` / `is_clear_current`. An
  expired Clear **still reads `CLEAR`** — no automatic gauge move — but promotion is refused on it
  (IQ-18). The handover guard's "the background check expired on <date>" is Developer 2's (task
  2.5), through the same facts.
- **Re-KYC due** (P3-3c): `GET /background-check/due?before=…` (staff; DEVELOPER refused) lists the
  `CLEAR` companies whose Clear expires before `before` (default now +
  `CRM_REKYC_DUE_WINDOW_DAYS`, 30) — expired first, then the soonest — with name, journey,
  `pipeline_status` (R-29: a buyer-only company's renewal is for the trade it buys on, not a
  sale, and the Home card says "Buyer only"), expiry, `is_expired` and the current cycle's
  number; never an identifier. A company whose Re-KYC has
  started is not listed (the start reopened it). The read serves `rekyc_due`, shown as the gauge's
  "Re-KYC due" badge and the Home card.

## 13. Errors

Raised by `BackgroundCheckService` and served by the routes (phases 4A-3 to 4A-7, and the PR
review of 28 Sep 2026). Each `error_context` carries plain values (`IN_REVIEW`, not
`BackgroundCheckState.IN_REVIEW`).

| Case | HTTP | `error_code` |
|---|---|---|
| Unknown company | 404 | `EXPORTER_PROFILE_NOT_FOUND` (existing) |
| Move not in the §3 table, including a move to the current value and `CLEAR → FLAGGED` | 409 | `BACKGROUND_CHECK_MOVE_NOT_ALLOWED` |
| Caller's role may not make this move | 403 | `BACKGROUND_CHECK_ROLE_NOT_ALLOWED` |
| Text missing or blank where §4 requires it | 422 | `BACKGROUND_CHECK_REASON_REQUIRED` |
| `CLEAR` without a risk rating | 422 | `BACKGROUND_CHECK_RISK_REQUIRED` |
| A risk rating on any move other than `CLEAR` | 422 | `BACKGROUND_CHECK_RISK_NOT_ALLOWED` |
| The request's optional `from_value` is not the company's current value (the screen was stale) | 409 | `BACKGROUND_CHECK_STATE_CHANGED`, with `expected` and `current` |
| `CLEAR` prerequisites unmet (rules per §14.1) | 409 | `BACKGROUND_CHECK_PREREQUISITES_UNMET`, naming each unmet prerequisite |
| Evidence asked for a decision that is not this company's | 404 | `BACKGROUND_CHECK_DECISION_NOT_FOUND` |
| A cycle asked for that is not this company's | 404 | `CHECK_CYCLE_NOT_FOUND` |
| A new cycle on a `FLAGGED` or `ON_HOLD` company | 409 | `CHECK_CYCLE_NOT_ALLOWED` |
| A new cycle while the current one is empty | 409 | `CHECK_CYCLE_EMPTY` |
| A new cycle started by a role other than COMPLIANCE or ADMIN (service rule; the route refuses first) | 403 | `CHECK_CYCLE_ROLE_NOT_ALLOWED` |
| `CLEAR`, `FLAGGED` or `ON_HOLD` asked to take effect without an approval, while maker-checker is on (a direct service call; the route proposes instead) | 409 | `BACKGROUND_CHECK_APPROVAL_REQUIRED` |
| Any move, proposal or new cycle while a proposal awaits approval | 409 | `BACKGROUND_CHECK_PROPOSAL_OPEN` |
| A proposal asked for that is not this company's | 404 | `BACKGROUND_CHECK_PROPOSAL_NOT_FOUND` |
| Approve, reject or withdraw a proposal already resolved (also the loser of two at once) | 409 | `BACKGROUND_CHECK_PROPOSAL_RESOLVED` |
| Approve a proposal whose gauge, chain head or inputs moved since | 409 | `BACKGROUND_CHECK_PROPOSAL_STALE`, with `why` |
| The proposer approves or rejects their own proposal | 403 | `BACKGROUND_CHECK_SELF_APPROVAL` |
| Someone other than the proposer withdraws it | 403 | `BACKGROUND_CHECK_PROPOSAL_NOT_YOURS` |
| A role other than COMPLIANCE or ADMIN approves, rejects or withdraws (service rule; the route refuses first) | 403 | `BACKGROUND_CHECK_APPROVER_ROLE_NOT_ALLOWED` |
| A write that bypasses the service and breaks §5.3 or §6 | — | refused by the database (`CheckViolation`, `ForeignKeyViolation`, `UniqueViolation`, `RaiseException`) |

Blocked items are never stubbed: there is no automatic start and no customer move to fail.

---

## 14. Open decisions

Every answer is recorded here, with its date and who decided. Nothing below is guessed in code.

| # | Decision | Status | Owner | Blocks |
|---|---|---|---|---|
| D1 | **CLEAR prerequisite semantics** beyond A3's wording (risk; no checks pending; eight items answered; evidence) | **Settled 28 Sep 2026 (programme lead):** the prerequisites are exactly A3's four and no others. D2–D4 fix what its phrases mean; see §14.1 | programme lead with compliance | — |
| D2 | **Meaning of "pending"** — `PENDING` only? `REVIEW` without an accepted review? placeholders? unlinked subjects? | **Settled 28 Sep 2026 (programme lead):** a check is pending unless it reached a terminal answer with a real provider — `PENDING`, `REVIEW` and placeholder rows all block `CLEAR`. **Clarified the same day in the Dev4A PR review** (at the user's instruction; to be confirmed by the lead): a `REVIEW` result stops blocking once it has an `ACCEPTED` or `REJECTED` review, because a review never changes `status` and the literal reading would have made such a company impossible to clear. See §14.1 | programme lead with compliance | — |
| D3 | **FAILED / EXEMPT screening vs CLEAR** — does "answered" include them? | **Settled 28 Sep 2026 (programme lead):** "answered" means answered satisfactorily. `PASSED` and `EXEMPT` only; a `FAILED` item blocks `CLEAR` | programme lead with compliance | — |
| D4 | **Evidence snapshot scope** — which documents; what counts as "evidence recorded" | **Settled 28 Sep 2026 (programme lead):** the company's own documents with `scan_status = AVAILABLE`; and `CLEAR` requires at least one pinned id | programme lead | — |
| D5 | **Risk on the company record; risk on non-CLEAR outcomes** | **Settled 28 Sep 2026 (programme lead):** **no company risk column.** Risk stays on the decision record and is read through `BackgroundCheckReader.standing` — no second copy to drift, no migration, and Developer 2's list filters through the reader. **Risk on non-`CLEAR` outcomes: refused** (Dev4A PR review, 28 Sep 2026, at the user's instruction). The first answer left it "neither required nor refused", which let any move — an OPERATIONS start included — record a rating the reader then reported as the company's (§7) | Dev4 (A+B) with the lead | nothing |
| D6 | **Risk shown after a reopen** | **Settled 28 Sep 2026 (programme lead):** keep **the last recorded risk, explicitly labelled**. `standing.risk_rating` is the risk of the most recent decision that set one, and the panel prints "from the most recent decision that set one" beside it whenever the company is not `CLEAR`. It is the best information available; the label is what stops it reading as a current verdict. A consumer must still read `value`, which is what `standing.is_clear` is for | Dev4A with the lead | nothing |
| D8 | **DEVELOPER visibility** of the gauge, reasons and evidence ids | **Settled 28 Sep 2026 (programme lead):** **no.** DEVELOPER is refused on all three routes, reads included — a decision's reason is free text a compliance officer wrote about a real company. Enforced by `_STAFF` in the router, with rows in both authorisation tables and an API test. The history routes now apply it too: DEVELOPER does not receive `background_check` (or `verification`/`screening`) rows there (29 Sep 2026, `history_router.py`, `history-row.md` §2) | lead with Developer 1 | nothing |
| D10 | **Company row lock during handover** | **Settled 28 Sep 2026 (programme lead):** **yes — `FOR SHARE`**, taken on the move and not on the read. Built in Developer 3's guard; **needs Dev3 review**. See §11.2 | Developer 3 with the lead | nothing |
| D11 / U4 / O3 | **Transaction boundary and announcement for the customer move** | **Implemented 29 Sep 2026 as one transaction** (the audit's recommendation; **the programme lead to confirm in writing**): the completing move calls Developer 2's flush-only promotion before its commit and announces after it (§11.3) | lead, Developer 2, Dev4A | nothing |
| D12 | **RXIL package / results contract**, including the actor of the automatic start | **Blocked** | RXIL, lead, Developer 2 | the automatic `NOT_STARTED → IN_REVIEW` only |
| D13 | **Risk database type** | **Settled 28 Sep 2026 (Dev4 lead):** a Dev4A-owned `background_check_risk_enum` | — | nothing |
| D14 | **`history-row.md` §4 omits two required texts** (`MORE_INFO → IN_REVIEW`, `CLEAR`) | **Open** — Dev4A enforces the architecture meanwhile | Developer 1 | the contract's text, before final merge |

### 14.1 D1–D4, as decided on 28 September 2026

Recorded in full because they define what "cleared" means, and because the code carries
them in exactly one value — `CLEAR_POLICY` in `domain/background_check_views.py` — with
a test that fails if any of them is changed without meaning to.

**D1 — the prerequisites are A3's four, and no others.** Risk given; no checks still
pending; all eight screening items answered; evidence recorded. Nothing was added to the
list, and the service does not invent a fifth condition. *Amended by decision B (plan P3-2,
1 October 2026):* KYB, AML and sanctions passed in the current cycle are required too
(§12.6), as three more named prerequisites.

**D2 — "pending" means "has not reached a terminal answer with a real provider".**

| Input | Blocks `CLEAR`? | Why |
|---|---|---|
| `status = PENDING` | yes | the check has not come back |
| `status = REVIEW`, no review or an `ESCALATED` one | yes | a human has not finished with it |
| `status = REVIEW` with an `ACCEPTED` or `REJECTED` review | **no** | a human has finished with it. `VerificationService.review` records `review_status` and never changes `status`, so without this row a result compliance had already dealt with would block `CLEAR` for ever (clarified in the Dev4A PR review, 28 Sep 2026; `ClearPolicy.concluding_review_statuses`) |
| `is_placeholder = true` | yes | created without a provider, so nothing ever ran — a review does not change that |
| `status = PASSED` or `FAILED`, real provider | no | it reached an answer |

The strict reading was chosen on purpose: a check that has not truly concluded should
not be able to sit quietly underneath a cleared company. Note that a `FAILED`
*verification* does not block `CLEAR` by itself — it is an answer, and the compliance
officer weighs it and records the risk. That is deliberate and differs from D3's
treatment of *screening* items.

**D3 — "answered" means answered satisfactorily: `PASSED` or `EXEMPT` only.** A `FAILED`
screening item blocks `CLEAR`, and `NEEDS_REVIEW` or a never-recorded item blocks it too.
A company with a failed screening item is `FLAGGED` — that is what the state is for
(architecture §3.3) — rather than cleared with a caveat, because a clearing decision that
names a failed sanctions item as evidence would be very hard to defend later.

**D4 — the snapshot pins the company's own `AVAILABLE` documents, and `CLEAR` requires
at least one pinned id.**

- **Which:** `crm_document` rows whose `company_id` is this company. **Deal paperwork is
  not pinned**: it belongs to the deal, not to the company's standing, and a company
  decision should not change meaning depending on which deals happened to be open.
- **Scan gate:** only `scan_status = AVAILABLE`. A `PENDING_SCAN`, `QUARANTINED` or
  `SCAN_FAILED` document is never served (`storage-and-documents.md` §4), so pinning one
  would name evidence nobody can open.
- **"Evidence recorded":** at least one pinned id of any kind — document, verification
  result or screening row. **Note:** because `CLEAR` also requires all eight screening items
  answered, and each answered item is a pinned id, this prerequisite can never be the only
  one unmet — a company can be cleared on its eight screening answers alone, with no document
  and no verification result. Whether "evidence recorded" should demand a document or a
  verification result is open for the lead (audit, 29 Sep 2026).
- The rule is applied in `select_evidence`, not in the query, so it is one pure function
  with unit tests rather than a `WHERE` clause nobody re-reads.

D5, D6, D8 and D10 were settled later the same day (table above). D11/U4/O3 was implemented as
one transaction on 29 September (the lead to confirm), and D14's texts are now in
`history-row.md` §4. Still open: D12.

### 14.2 Confirmed by the programme lead on 2 October 2026

These were built on a recommendation and listed in `open-items.md` §1 as awaiting
confirmation or undecided. The lead confirmed each **as built** on 2 October 2026. The
write-up made then never reached `main`, so it was recorded again here on 4 October 2026
(`remaining-work.md` §8.2), and the rows left `open-items.md` §1. Nothing in the code
changed: each is the behaviour already described in the section named.

| Confirmed | As built | Where |
|---|---|---|
| **IQ-2 edge cases** | A `REVIEW` sanctions or AML result whose review is `REJECTED` reads as `FAILED`; a `PASSED` or `FAILED` result reads as its status whatever its review says | §12.4, `domain/compliance_facts.check_state` |
| **No new cycle while the current one is empty** | Refused 409 `CHECK_CYCLE_EMPTY`. It makes two simultaneous starts produce one cycle; a wrongly chosen kind is replaced only once something is recorded | §12.3, `BackgroundCheckService.start_cycle` |
| **Maker-checker details** | (a) the proposer may not reject their own proposal, only withdraw it (the database enforces it too); (b) while a proposal is open nothing else moves the check (409 `BACKGROUND_CHECK_PROPOSAL_OPEN`); (c) any change to what the decision would rest on makes the proposal stale; (d) the switch may be off only where `ENVIRONMENT` is `local` or `test`; (e) the approval queue is COMPLIANCE/ADMIN only, a company's proposals are readable by all staff; (f) `decided_by` names the proposer, `approved_by` the approver | §12.5 |
| **Clear expiry backfill keyed on the last `CLEAR` decision** | BQ-5's "1 year from the last Clear" taken literally (migration 0027); a new `CLEAR`'s `decided_at` and `expires_at` come from one server timestamp read after the row lock | §12.7, `migration-register.md` |
| **`BuyerChecks.tsx` kept for legacy deal buyers** | It stays, marked legacy, until the buyer migration (P4-6) has run everywhere and `deal_buyer` writes are retired (P4-10, `remaining-work.md` R-25); then it is deleted (R-26) | §12.2, §16 |
| **D4, verification side** | Which documents may be evidence for a verification: the company's own, and for a buyer its deal's or its company's; only `AVAILABLE` ones | `verification-and-screening.md` §3, §11 |
| **No D2 amendment for placeholders** | A placeholder result keeps blocking `CLEAR` in its own cycle. A company holding one is not stuck: COMPLIANCE or ADMIN starts a new cycle and the placeholder stays behind in the old one | §12.3, §14.1 (D2) |
| **No document required to `CLEAR`** | "Evidence recorded" is met by the screening answers; rule B (§12.6) still needs KYB, AML and sanctions passed in the current cycle. **To be revisited** when gate §7.6 (a real scanner, S3 with Object Lock) makes real documents possible | §14.1 (D4), architecture §7, §12 |

---

## 15. Acknowledgements

| Developer | Why | Status |
|---|---|---|
| Developer 1 | history usage (§8), D14, the migration register row for 0015 | requested |
| Developer 2 | the `background_check` column on `exporter_profile` (§2), the customer move (§11.3) | requested |
| Developer 3 | the handover read (§11.2), D10 | requested |
| Developer 4B | the seam as consumed (§12), the evidence FKs to its tables (§6) | requested |

---

## 16. What is implemented today

| Part | Status |
|---|---|
| This contract (4A-1) | published |
| `onboarding_0015_bg_check`: the five enum types, `exporter_profile.background_check`, `background_check_decision`, `background_check_evidence`, every §5.3 and §6 constraint, both triggers, the indexes (4A-2) | built |
| ORM entities `BackgroundCheckDecision`, `BackgroundCheckEvidence`, the enums in `background_check_enums.py`, `ExporterProfile.background_check`, `BackgroundCheckDecisionRepository` (4A-2) | built |
| `BackgroundCheckService`: moves 1, 3, 4, 5, 6, the row lock, per-move roles, the text rule, supersession, the evidence snapshot, the history row, one commit, `allowed_moves` (4A-3) | built |
| `IN_REVIEW → CLEAR` (4A-4) | built. Risk required; A3's four prerequisites evaluated by one pure function under the row lock; **D1–D4 settled 28 Sep 2026** (§14.1) and carried by `CLEAR_POLICY` |
| Evidence snapshot contents | verification results, screening rows, **and the company's `AVAILABLE` documents** (D4). Deal documents are not pinned |
| Reopen and reassessment: `CLEAR`/`FLAGGED`/`ON_HOLD` → `IN_REVIEW` (4A-5) | built. All nine §3 moves are now reachable; the superseded decision is untouched and the journey is never written |
| `BackgroundCheckReader`, `current_background_check` (§10) and the Developer 3 swap (4A-6) | built. `deal_service.read_background_check` calls the helper; its name and signature are unchanged |
| API routes (4A-7) | built: the three routes of §5.10, `extra="forbid"` on the request, per-move roles in the service, rows in both authorisation tables, artifacts regenerated |
| Background-check panel (4A-8) | built: gauge, risk chip, decision trail with evidence counts, a move dialog offering only the server's `allowed_moves`, loading/empty/error states, Developer 4B's `VerificationSection` unchanged below it |
| PR review fixes (28 Sep 2026) | built: risk refused off `CLEAR` (service + `ck_background_check_decision_risk_only_on_clear`); D2's reviewed-`REVIEW` clarification (`concluding_review_statuses`); optional `from_value` with `BACKGROUND_CHECK_STATE_CHANGED`; `decided_at` on `clock_timestamp()`; plain values in error context; the dialog never sends a hidden risk; readable prerequisites and server error text in the panel; a behavioural D10 test |
| Customer transition (4A-9) | built (29 Sep 2026): step 7b of `_move` calls Developer 2's promotion on `CLEAR`, in the same transaction, and announces after the commit (§11.3); both orders tested in `test_customer_promotion.py` and end to end in `test_crm_end_to_end.py` |
| Automatic start on RXIL results | **blocked** (D12) |
| Seam v2 (§12), `subject_company_id` (set once, frozen), `background_check_expires_at`, `ComplianceFactsReader`, promotion on a current Clear only (F1, 1 Oct 2026) | built (0023) |
| Evidence resolved per decision (§6.2, P2-1a); evidence on screening answers (P2-1b, 0024) | built |
| Screening 8 → 7 and `rules_version` on decisions (P2-4a) | built (0025): `website-reviewed` retired — kept, readable, refused on write |
| Check cycles, cycle-scoped inputs, Re-KYC / Re-KYB (§12.3, P2-3a–d) | built (0025) |
| Maker-checker: proposals, approve / reject / withdraw, the queue, the switch (§12.5, P3-1a–d) | built (0026); the suite and sample data run with it on |
| Rule B: KYB, AML and sanctions passed, served `required_checks` (§12.6, P3-2) | built (`CLEAR_RULES_V3`) |
| Clear expiry stored and backfilled; expiry in the standing and the facts; Re-KYC due list and badge (§12.7, P3-3a–c) | built (0027) |
| Company-keyed checks: `subject_company_id` on every new company-subject result; every read by the subject company; legacy rows by `entity_reference`; `buyer_checks` / `for_legacy_buyer` kept (§12.2, P4-5) | built (no migration; nothing rewritten). Buyer companies themselves (`deal.buyer_company_id`, the migration filling legacy buyer rows) are Developer 2's F2/P4-4/P4-6 |
| Buyer-only companies (`NOT_IN_PIPELINE`) run the same check — cycles, rule B, maker-checker, expiry — and are never promoted (P4-11) | built: no special-casing; promotion needs a `PROSPECT`, which Developer 3's P4-1 rule keeps such a company from being |
| `CompanyComplianceSummary` full version (task 1.20): gauge with badges, expiry, sanctions/AML, link to the company's panel | built; `BuyerChecks` stays only for legacy `deal_buyer` deals until P4-10 |
| Final-integration concurrency (allocation §6), in two sessions with the existing locks (moves `FOR UPDATE`, input writers and the handover `FOR SHARE`) | built: `test_dev1_concurrency.py` — a Re-KYC waits for an in-flight handover; a handover waits for an in-flight approval and reads it committed; a flag committed first refuses the handover; an input in flight makes an approval wait and then refuse (stale); an approval in flight makes an input wait and stay outside the decision; a move waits for a cycle start and lands in the new cycle; a cycle start waits for an approval and reopens it. The buyer-company form of the first needs Developer 2's F2 and P4-7 guard |
| `ComplianceFactsReader` for consumers | the Protocol (`domain/compliance_facts.py`) and a fake for consumers' tests, `tests/fixtures/compliance.StaticComplianceFactsReader` / `party_facts`, so Developer 2's guard (task 2.5) is built and tested without Dev 1 code |
