# Contract — the background check

**Owner:** Developer 4A · **Task:** L4-01 (`docs/dev4/4a-task.md` §14, phase 4A-1) ·
**Migration:** `onboarding_0015_bg_check` · **Status:** published 28 Sep 2026; acknowledgement
requested from Developers 1, 2, 3 and 4B (§15)

The company-level background check: its six values, the only moves between them, who may make
each move and what it needs, the locked decision record behind every move, the evidence snapshot
pinned to each decision, the CRM risk rating, the history row, and the read helper other
developers consume.

**Source of truth.** `docs/Exporter-CRM-Architecture-and-Plan.pdf` §3.3 ("Gauge 3: Background
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
- A **buyer check is not a company check.** Checks about a deal's buyer are recorded against
  `deal_buyer.id` (decision 9) and never move this gauge.

---

## 2. Values

The current value lives on the company record, `exporter_profile.background_check`, Postgres type
`onboarding.background_check_enum`, `NOT NULL DEFAULT 'NOT_STARTED'` (`company-record.md` §2.4).

| Value | Meaning |
|---|---|
| `NOT_STARTED` | No check has been started. The default for every company. |
| `IN_REVIEW` | Compliance is reviewing checks, screening items and documents. |
| `CLEAR` | One compliance or admin user has cleared the company, with a risk rating, a reason and an evidence snapshot. |
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
| 2 | `IN_REVIEW` | `CLEAR` | one COMPLIANCE or ADMIN user | **reason** | risk rating; no checks still pending; all eight screening items answered; evidence recorded (A3; exact rules **settled 28 Sep 2026 — §14.1**) |
| 3 | `IN_REVIEW` | `MORE_INFO` | COMPLIANCE, ADMIN | **note of what is needed** | — |
| 4 | `MORE_INFO` | `IN_REVIEW` | OPERATIONS, COMPLIANCE, ADMIN | **note of what arrived** | — |
| 5 | `IN_REVIEW` | `FLAGGED` | COMPLIANCE, ADMIN | **reason** | — |
| 6 | `FLAGGED` | `ON_HOLD` | COMPLIANCE, ADMIN | **reason** | — |
| 7 | `FLAGGED` | `IN_REVIEW` | COMPLIANCE, ADMIN (reassessment) | **reason** | — |
| 8 | `ON_HOLD` | `IN_REVIEW` | COMPLIANCE, ADMIN (reassessment) | **reason** | — |
| 9 | `CLEAR` | `IN_REVIEW` | one COMPLIANCE or ADMIN user (reopen, decision 5) | **reason** | — |

Rules that go with the table:

- **Roles are enforced per move, on the server**, not only per route. OPERATIONS may make moves 1
  and 4 and nothing else. DEVELOPER and API_USER make no move. "One user" means a single person
  decides; there is no second approver in the prototype (decision 5).
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

### 6.1 Why the review id has no foreign key

Developer 4B's superseding-review table does not exist yet (4B-2, migration
`onboarding_0021_verif_review`). A foreign key to it would make Dev4A's migration depend on
Developer 4B's, and the two are deliberately independent (`4a-task.md` §10). Until 4B-2 lands,
the seam reports `latest_review_id = None` even for a reviewed result, so this column is `NULL`
for every snapshot taken before then. An FK can be added after both PRs merge, if both developers
agree (`4a-task.md` §17).

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

## 12. The 4A ↔ 4B seam (by reference)

The inputs to a decision — the eight screening items and the verification results whose subject
is the company — are read **only** through Developer 4B's `ComplianceInputsReader`
(`backend/app/modules/onboarding/domain/compliance_inputs.py`), implemented by
`ComplianceInputsService` (`application/compliance_inputs.py`). The interface, its invariants,
its errors and its ownership are `docs/dev4/4a-task.md` §6 / `4b-task.md` §6; they are **not**
restated here, and their output shape is frozen.

What Dev4A relies on from it:

- facts, not judgements — "pending", "answered" and "ready" are Dev4A's rules (D1–D3);
- company scope is `EXPORTER` + the company id; buyer checks never enter company inputs;
- the reader never locks; Developer 4B's writers of company-scoped inputs take `FOR SHARE` on the
  company row, so Dev4A's `FOR UPDATE` serialises a decision against them;
- until 4B-2, `latest_review_id` and `latest_reviewed_at` are `None` even on a reviewed result;
  `latest_review_status` says whether a review exists.

Dev4A imports the seam and nothing else of Developer 4B's.

---

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
list, and the service does not invent a fifth condition.

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
