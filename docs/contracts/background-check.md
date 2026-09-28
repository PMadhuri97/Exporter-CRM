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
| 2 | `IN_REVIEW` | `CLEAR` | one COMPLIANCE or ADMIN user | **reason** | risk rating; no checks still pending; all eight screening items answered; evidence recorded (A3; exact rules D1–D4) |
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
| `decided_at` | `timestamptz` | no | **When.** `server_default now()`; server time, never supplied by a caller. |
| `reason` | `text` | yes | **Why.** Required where §4 says so. |
| `risk_rating` | `background_check_risk_enum` | yes | Required on `CLEAR` (§7). |
| `supersedes_decision_id` | `uuid` | yes | The previous decision for the same company. `NULL` only on the company's first decision. |
| `details` | `jsonb` | no | `DEFAULT '{}'`. Anything a reader needs without a second query. IDs only, never evidence content or PII. |

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
  `AVAILABLE` ones) and what counts as "evidence recorded" for `CLEAR` — is **D4**. The shape
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
| **On the company record** | **None.** There is no company-level risk column. Whether one is added for list filters is **D5 — open, non-blocking**. The current risk is read from the decisions through the read helper (§10). |
| **On other outcomes** | The column is nullable and unconstrained on non-`CLEAR` decisions. Whether risk is required, allowed or refused on `FLAGGED` / `ON_HOLD` / others is **D5**. The service does not invent a rule. |
| **After a reopen** | What the company shows while `IN_REVIEW` after a `CLEAR` is **D6**. |
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
  the `reason` on these rows — is **D8**. Until decided: no widening of any background-check route
  to DEVELOPER.
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
customer move. **It is specified here and implemented in phase 4A-6; it does not exist yet.**

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
- `risk_rating`'s meaning after a reopen follows **D6**; until then it is the risk of the latest
  decision that set one, and a consumer must read `value` to know whether the company is clear.

---

## 11. Relationships

### 11.1 Journey

The background check never moves the journey. A `CUSTOMER` whose check is reopened, flagged or put
on hold **stays** `CUSTOMER` (`company-record.md` §3.1, A5). Dev4A writes no journey value.

### 11.2 Deal handover (Developer 3)

A deal is handed over only when the company is `CUSTOMER` **and** its check is `CLEAR` (A5). The
guard and the handover are Developer 3's. Dev4A's part is the read helper (§10):

- `deal_service.read_background_check(company)` is Developer 3's stand-in. Once the column exists
  (4A-2) it returns the real value — `"NOT_STARTED"` for every company until a move is recorded —
  so every handover is refused with "the background check is NOT_STARTED, not CLEAR".
- In phase 4A-6 its body becomes `return current_background_check(company)`, with Developer 3's
  review. Its name and signature do not change, and nothing else in `deal_service.py` does.
- The `clear_background_check` fixture in `test_l3b_handover.py` stays until a real `CUSTOMER` can
  be produced (L2-11).
- Whether Developer 3's guard must lock or share-lock the company row, so a concurrent `FLAGGED`
  cannot slip past a handover, is **D10**. Dev4A's own moves always take the row lock, so a guard
  that also locks is fully serialised against them.

### 11.3 Customer transition (Developer 2) — **BLOCKED: U4 / O3**

`PROSPECT → CUSTOMER` happens when the company is `PROSPECT` and its check is `CLEAR`, whichever
becomes true second (A1). Developer 2 makes the move (L2-11) and it announces
`company.became_customer`, whose payload carries `risk_rating` and `clearing_decision_id`
(`event-envelope.md` §3) — both readable from `BackgroundCheckReader.standing`.

**Whether Dev4A's `CLEAR` and Developer 2's move commit together, and who publishes the event after
the commit, is undecided (U4, D11).** Until it is, Dev4A builds no customer move, calls no
Developer 2 code and publishes no `company.became_customer`. Dev4A acknowledges `event-envelope.md`
§3 as the payload it owes.

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

Planned for the service and routes (phases 4A-3 to 4A-7). Named here so the routes and the screen
can be built against them; the exact class names are fixed when the code lands.

| Case | HTTP | `error_code` |
|---|---|---|
| Unknown company | 404 | `EXPORTER_PROFILE_NOT_FOUND` (existing) |
| Move not in the §3 table, including a move to the current value and `CLEAR → FLAGGED` | 409 | `BACKGROUND_CHECK_MOVE_NOT_ALLOWED` |
| Caller's role may not make this move | 403 | `BACKGROUND_CHECK_ROLE_NOT_ALLOWED` |
| Text missing or blank where §4 requires it | 422 | `BACKGROUND_CHECK_REASON_REQUIRED` |
| `CLEAR` without a risk rating | 422 | `BACKGROUND_CHECK_RISK_REQUIRED` |
| `CLEAR` prerequisites unmet (rules per D1–D4) | 409 | `BACKGROUND_CHECK_PREREQUISITES_UNMET`, naming each unmet prerequisite |
| A write that bypasses the service and breaks §5.3 or §6 | — | refused by the database (`CheckViolation`, `ForeignKeyViolation`, `UniqueViolation`, `RaiseException`) |

Blocked items are never stubbed: there is no automatic start and no customer move to fail.

---

## 14. Open decisions

Every answer is recorded here, with its date and who decided. Nothing below is guessed in code.

| # | Decision | Status | Owner | Blocks |
|---|---|---|---|---|
| D1 | **CLEAR prerequisite semantics** beyond A3's wording (risk; no checks pending; eight items answered; evidence) | **Open** | programme lead with compliance | CLEAR's rule function (4A-4) |
| D2 | **Meaning of "pending"** — `PENDING` only? `REVIEW` without an accepted review? placeholders? unlinked subjects? | **Open** | programme lead with compliance | CLEAR's rule function |
| D3 | **FAILED / EXEMPT screening vs CLEAR** — does "answered" include them? | **Open** | programme lead with compliance | CLEAR's rule function; UI copy |
| D4 | **Evidence snapshot scope** — which documents; what counts as "evidence recorded" | **Open** | programme lead | document pinning and CLEAR's evidence rule |
| D5 | **Risk on the company record; risk on non-CLEAR outcomes** | **Open, non-blocking.** No company risk column; risk lives on the decision | Dev4 (A+B) with the lead | a company column (a later migration if added); Developer 2's list filter; UI |
| D6 | **Risk shown after a reopen** | **Open** | Dev4A with the lead | `standing.risk_rating` semantics; UI |
| D8 | **DEVELOPER visibility** of the gauge, reasons and evidence ids | **Open.** Default: no widening | lead with Developer 1 | route roles; UI; history `reason` policy |
| D10 | **Company row lock during handover** | **Open** | Developer 3 with the lead | Developer 3's guard |
| D11 / U4 / O3 | **Transaction boundary and announcement for the customer move** | **Blocked** | lead, Developer 2, Dev4A | all of §11.3 |
| D12 | **RXIL package / results contract**, including the actor of the automatic start | **Blocked** | RXIL, lead, Developer 2 | the automatic `NOT_STARTED → IN_REVIEW` only |
| D13 | **Risk database type** | **Settled 28 Sep 2026 (Dev4 lead):** a Dev4A-owned `background_check_risk_enum` | — | nothing |
| D14 | **`history-row.md` §4 omits two required texts** (`MORE_INFO → IN_REVIEW`, `CLEAR`) | **Open** — Dev4A enforces the architecture meanwhile | Developer 1 | the contract's text, before final merge |

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
| `BackgroundCheckService`, moves, `CLEAR`, reopen, allowed moves (4A-3 … 4A-5) | **not started** |
| `BackgroundCheckReader` and the Developer 3 swap (4A-6) | **not started** |
| API routes (4A-7), panel (4A-8) | **not started** |
| Customer transition (4A-9) | **blocked** (U4) |
| Automatic start on RXIL results | **blocked** (D12) |
