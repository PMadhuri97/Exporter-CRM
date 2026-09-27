# Dev4A — Background Check / Compliance Core

> Companion document: **`docs/dev4/4b-task.md`** (Dev4B — Verification / Screening Integrity).
> The two documents describe one split of Developer 4's work (architecture §9.4) into two
> parallel pull requests. Sections 6 and 9 are identical in both files, and sections 10, 16 and
> 17 describe the same plan from each side. If they ever disagree, stop and reconcile before
> writing code.

---

## 1. Purpose

Dev4A builds the **company-level background-check gauge** and the **decision layer** behind it:

- the current value on the company (`NOT_STARTED`, `IN_REVIEW`, `CLEAR`, `MORE_INFO`, `FLAGGED`,
  `ON_HOLD`);
- every move between those values as a new, locked **decision record** that points at the one it
  supersedes;
- the **evidence snapshot** pinned to each decision;
- the CRM **risk rating** (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`) that compliance sets as part of a
  decision;
- the **read helper** Developer 3's deal-handover guard and Developer 2's customer move consume;
- the background-check API and the Background check panel that shows it.

Dev4A does **not** own the inputs to the decision. Verification results, their reviews, the
eight-item screening checklist, buyer checks and their UI belong to Dev4B (`docs/dev4/4b-task.md`).
Dev4A reads them only through the 4A ↔ 4B contract in §6.

A background-check decision is **not** a verification result and **not** a screening item.
Verification results and the eight screening items are **inputs** to the decision.

---

## 2. Source of Truth

In this order:

1. **`docs/Exporter-CRM-Architecture-and-Plan.pdf`** — authoritative. Relevant parts:
   §2.6 (principles), §3.2 (journey), §3.3 "Gauge 3: Background check" (the move table and its
   three bullets), §3.5, §3.6 (events), §3.7 (roles), §3.8 and Figure 3 ("Check decision
   (locked): company_id, outcome, who (from login), when, reason, supersedes"), §4.1 steps 8–11,
   §4.2, decisions 2, 5, 6, 10, assumptions A1, A3, A5, A6, A8, §7.4–7.7, §8.2, §9.4 (L4-01,
   L4-03 … L4-06, L4-08, L4-12, L4-13, L4-14).
2. **The Dev4 Phase 0 audit** (verdict `DEV4-AUDIT-READY-WITH-DEPENDENCIES`, run on `main` @
   `8d8606c`, 28 Sep 2026).
3. **Code on `main`.**
4. **Contracts and handovers already in the repository:**
   `docs/contracts/history-row.md`, `event-envelope.md`, `migration-register.md`,
   `company-record.md` (§2.4, §3.1, §3.2, §8, O3), `criterion-result.md` (§6),
   `deal-and-buyer.md` (§6), `storage-and-documents.md` (§5, §7), `engagement.md` (§1),
   `docs/dev1-remaining-work.md` (§2.2 U4), `docs/dev2-remaining-work.md` (§5),
   `docs/dev3b-remaining-work.md` (§6).

Where these disagree, the architecture wins; where the architecture is silent, the item is a
decision gate in §13 — **do not invent the answer**.

---

## 3. Current Repository Baseline

As measured by the Dev4 audit (28 Sep 2026):

| Item | Value |
|---|---|
| `main` | `8d8606c` (Dev1 PR #7 `8fb8729`, Dev2 PR #8 `c117fdf`, Dev3A PR #9 `447c6ba`, Dev3B PR #10 `f703c05`) |
| Alembic | One head, `onboarding_0019_documents`. Chain 0013 → 0014 → 0017 → 0020 → 0016 → 0018 → 0019. **0015 is unused.** |
| Backend suite | 30 failed / 3728 passed / 7 skipped / 22 errors. The **environment baseline is 29 failed + 22 errors** (compliance-module routes; `audit_ro`/`ledger_ro`/`settlement_ro` role passwords). The 30th was `test_l3a_conversation_gauge::test_a_check_back_date_in_the_past_is_refused`, which fails only between 00:00 and 05:30 IST (local vs UTC date) — a Dev3A test defect, not a regression. None of these are Dev4's; do not "fix" them. |
| Other gates | ruff 16 · import-linter 19 kept / 0 broken · `openapi.json` + `schema.ts` current · tsc clean · eslint 0 errors / 2 warnings · vitest 16 files / 131 tests · vite build ok |

What exists for Dev4A today — **nothing of the gauge**:

- no `background_check` column, enum, decision table, evidence table or risk field on the company;
- no `docs/contracts/background-check.md` (L4-01 was never written);
- `deal_service.read_background_check(company)` (`backend/app/modules/onboarding/application/deal_service.py:106`)
  is Dev3's stand-in: `getattr(company, "background_check", None)`. It returns `None` today, so
  every handover is refused with "the background check is not recorded yet";
- `EventType.COMPANY_BECAME_CUSTOMER` and `OnboardingEventPublisher.company_became_customer`
  already exist (Dev1, L1-12); nothing calls them;
- `QualificationService` never moves a company to `CUSTOMER`; L2-11 is unbuilt; **U4 is
  undecided** everywhere on `main`;
- the old ten-status compliance gate was already retired by Dev2 (migration 0020). There is
  nothing to "lift out of the profile service".

**Stale branches that must never be merged into or built on:**
`feature/provider-adapter-wiring`, `feature/vendor-adapter-wiring`,
`feature/case-bridge-event-wiring`.

---

## 4. Ownership Boundary

| Area | Dev4A owns | Dev4A consumes (read-only) | Dev4A must not modify |
|---|---|---|---|
| Background-check gauge | Column, values, moves, roles, allowed moves, locking | — | — |
| Decisions | Decision table, supersession, reasons, source, decided-by-kind | — | — |
| Evidence snapshot | Snapshot table and what it pins | Dev4B's inputs reader (§6); Dev3B's document list | Dev4B's tables; `crm_document` |
| Risk | CRM risk on the decision, in Dev4A's own database type (D13, settled); on the company only if D5 says so | — | `customers.*` risk enums, `onboarding_risk_rating_enum`, `verification_risk_level_enum` |
| History | `background_check` rows it writes | `HistoryService.record` (Dev1) | `history_service.py`, `exporter_lifecycle_history` |
| Deal handover | The read helper (§5.8) | — | Deal stages, the guard's logic, the snapshot, `deal.handed_over` |
| Customer transition | Nothing until U4 is settled (§13, D11) | `company-record.md` §3.2 | Journey, qualification, `company.became_customer` emission |
| Company record | One mapped column on `ExporterProfile` (Dev2's file, Dev2 review) | Company row lock pattern | Identity, journey, marker, company routes and schemas |
| Verification / screening / buyer checks | — | Dev4B's reader only | All of Dev4B's files (§7 of `4b-task.md`) |
| Frontend | Background check panel, gauge/decision UI, risk chip | Dev4B's `VerificationSection` (rendered, never edited) | `VerificationSection.tsx`, Dev2's shell and list, Dev3's pages |

---

## 5. Responsibilities

### 5.1 Background-check current gauge (L4-03)

- `exporter_profile.background_check`, `NOT NULL`, default `NOT_STARTED` (company-record §2.4:
  owner adds its own column in its own migration; only the owner writes it).
- The **only** legal moves are the architecture §3.3 table:

  | From | To | Who | Needs |
  |---|---|---|---|
  | `NOT_STARTED` | `IN_REVIEW` | OPERATIONS, COMPLIANCE, ADMIN; or automatic on RXIL results (**blocked**, §12) | — |
  | `IN_REVIEW` | `CLEAR` | one COMPLIANCE or ADMIN user | risk rating; no checks pending; eight screening items answered; evidence (see D1–D4) |
  | `IN_REVIEW` | `MORE_INFO` | COMPLIANCE, ADMIN | note of what is needed |
  | `MORE_INFO` | `IN_REVIEW` | OPERATIONS, COMPLIANCE, ADMIN | note of what arrived |
  | `IN_REVIEW` | `FLAGGED` | COMPLIANCE, ADMIN | reason |
  | `FLAGGED` | `ON_HOLD` | COMPLIANCE, ADMIN | reason |
  | `FLAGGED` or `ON_HOLD` | `IN_REVIEW` | COMPLIANCE, ADMIN (reassessment) | reason |
  | `CLEAR` | `IN_REVIEW` | one COMPLIANCE or ADMIN user (reopen, decision 5) | reason |

  Everything else is refused, including `CLEAR → FLAGGED` (architecture §4.2 routes "new
  information about a cleared company" through a reopen) and any move to the value already held.
- Server-side role enforcement per move, not only per route: OPERATIONS may start a check and
  answer `MORE_INFO`, nothing else.
- **Company row locked** (`SELECT … FOR UPDATE`, `populate_existing`) before any rule is
  evaluated, exactly as `QualificationService._lock_profile` does. Every rule is checked before
  anything is assigned, so a refused move leaves nothing behind.
- Current value, decision row, evidence rows and history row written with **one flush chain and
  one commit** (history contract §5).
- **Allowed moves served by the server** for the calling user, in the same shape as
  `ConversationService.allowed_moves` / `DealService.allowed_stage_moves`. No universal
  allowed-moves framework (U1 is unowned — do not take it).
- No `background_check_initial` history row: the column has a default, so every row is a
  transition — the precedent `ConversationService` set (engagement contract §8).

### 5.2 Background-check decision record (L4-04)

A new append-only table (`public.prevent_mutation()` trigger, `AppendOnlyRepository`), one row
per move. Required content (architecture §3.3 bullets, Figure 3, §2.6):

| Field | Rule |
|---|---|
| `id` | uuid4; the decision id every consumer refers to |
| `company_id` | FK → `exporter_profile.customer_id`, `ON DELETE RESTRICT` |
| `from_value`, `to_value` | the move |
| `decided_by` | `str(user.id)` from the login session; never from a request body; `NULL` only for a platform-originated move (none exists until RXIL intake — §12) |
| `decided_by_kind` | person or computer (`MANUAL` / `AUTOMATED`, the vocabulary criterion-result already uses). Always `MANUAL` in the prototype |
| `source` | where the decision came from (`MANUAL`; `RXIL` reserved for the blocked intake) |
| `decided_at` | server time |
| `reason` | required where §5.1 says so; enforced by the service **and** a DB `CHECK` |
| `risk_rating` | Dev4A's own risk type (D13); required on `CLEAR` (DB `CHECK`); elsewhere per D5 |
| `supersedes_decision_id` | self-FK to the previous decision for the same company; **unique**, so the chain cannot fork under a race; `NULL` only for the first decision |
| `details` | JSONB for anything a reader needs without a second query |

Decisions are never updated in place. A reopen or reassessment is a new decision that supersedes
the previous one. Direct-SQL tests prove `UPDATE` and `DELETE` are refused.

### 5.3 Evidence snapshot (L4-06)

Architecture §3.3: "At the moment of each decision, the IDs of the documents and check results
it relied on are stored with it." Dev4A owns the snapshot contract:

- A child append-only table (one row per pinned item), or an equivalent immutable structure,
  written in the decision's transaction.
- It pins **IDs only**, never content: `crm_document.id` (Dev3B's document system — **no second
  document store**), `verification_result.id`, the verification review id the result's standing
  rested on (Dev4B's, carried as a bare uuid — see §10), and `screening_review_item.id` (the
  exact checklist row, since screening rows keep changing after a decision).
- Foreign keys only to tables that already exist on `main` (`crm_document`, `verification_result`,
  `screening_review_item`), `ON DELETE RESTRICT`, so evidence cannot vanish under a decision.
- A snapshot is taken for **every** decision, not only `CLEAR` (the architecture says "each
  decision").
- Inputs come from Dev4B's reader (§6) and from Dev3B's document list; Dev4A never queries
  Dev4B's tables itself.
- **What** goes into the snapshot (which documents; whether non-`AVAILABLE` documents count) is
  decision **D4**.

### 5.4 Risk (L4-08)

- Values exactly `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` (decision 6). "Prohibited" is an outcome,
  recorded as `FLAGGED`, never a risk value.
- **Settled:** risk is set by compliance as part of the decision and is required on `CLEAR`
  (architecture §3.3, A3, §4.1 step 9). It lives on the decision record.
- **Settled:** `company.became_customer` carries `risk_rating` and `clearing_decision_id`
  (event-envelope §3), so the clearing decision's risk must be readable (§5.8).
- **Settled (D13, 28 Sep 2026):** the values are carried by a **new database enum type owned by
  Dev4A**, created in `onboarding_0015_bg_check`, with exactly `LOW`, `MEDIUM`, `HIGH`,
  `CRITICAL`. Dev4B's `verification_risk_level_enum` is **not** reused, so neither Dev4 migration
  depends on the other's schema. This is the CRM background-check risk vocabulary of decision 6;
  it changes no legacy, customer or onboarding risk type.
- **Not settled — decision gates:** whether risk is also carried on `exporter_profile` for list
  filters (Figure 3 draws `risk` on the company; company-record §2.4 leaves it to Dev4) — **D5**;
  whether risk is required or allowed on non-`CLEAR` outcomes — **D5**; what the company shows
  after a reopen — **D6**. D5 is open but does **not** block the migration: until it is decided,
  risk is stored on the decision record only, and no company risk column is added.
- Do not alter any existing risk enum to make it fit.
- `CRITICAL` must look different on screen (architecture §3.3, L4-08).

### 5.5 Background-check transition history

- Every gauge move writes one row through Dev1's `HistoryService.record(...)`:
  `dimension="background_check"`, `from_value`/`to_value` as strings, `actor_id` from the session,
  `reason`, `source="background_check_service.<method>"`, and `details` carrying at least
  `decision_id`, `supersedes_decision_id`, `risk_rating` (when set) and the evidence count.
  `event_type` is left to `HistoryService` (derives `background_check_transition`).
- `details` carry **IDs, never evidence content or PII**. The history route admits DEVELOPER
  (`history_router.py:44`); what free text DEVELOPER may read is **D8**.
- `history-row.md` §4 lists required reasons for `MORE_INFO`, `FLAGGED`, `ON_HOLD`, reopen and
  reassess, but **omits** the architecture's note on `MORE_INFO → IN_REVIEW` and the reason on
  `CLEAR` (§4.1 step 9). Dev4A enforces the architecture in its own service; the contract text is
  Dev1's to amend (**D14**, cross-developer). Do not edit `history_service.py` or the contract.

### 5.6 CLEAR decision orchestration (L4-03, A3)

Dev4A alone decides `CLEAR`. The operation:

1. locks the company row;
2. reads the inputs through Dev4B's `ComplianceInputsReader.company_inputs(company_id)` in the
   same session (§6) — **no** screening or verification logic is re-implemented in Dev4A;
3. evaluates the prerequisites: risk given; no checks pending; all eight screening items
   answered; evidence recorded;
4. writes decision + evidence + current value + history, commits once.

The prerequisite rules are **decision-gated** (D1, D2, D3, D4). Build the mechanism with the
rules isolated in one pure function of `(inputs, risk, evidence)` so a decision changes one place
and its tests. Do not merge a guessed rule.

### 5.7 Reopen and reassessment (L4-04, decision 5)

- `CLEAR → IN_REVIEW` (reopen), `FLAGGED → IN_REVIEW` and `ON_HOLD → IN_REVIEW` (reassess):
  COMPLIANCE or ADMIN, one user, reason required, new decision that supersedes the previous one.
  The original decision is unchanged in the database (test it).
- A `CUSTOMER` whose check is reopened, flagged or put on hold **stays** `CUSTOMER` (company-record
  §3.1; A5). Dev4A never touches the journey.
- `CLEAR → FLAGGED` directly is refused.

### 5.8 Dev3 integration — the read helper (L4-01, L4-05 first half)

Dev4A publishes the stable read seam. It is **not** blocked by U4 (Dev2 needs it whatever U4
decides). Contract to write into `docs/contracts/background-check.md`:

```python
# app/modules/onboarding/application/background_check_reader.py   (owner: Dev4A)

@dataclass(frozen=True)
class BackgroundCheckStanding:
    company_id: uuid.UUID
    value: str                            # one of the six gauge values
    risk_rating: str | None               # of the latest decision that set one (see D6)
    latest_decision_id: uuid.UUID | None  # None while NOT_STARTED with no decision
    clearing_decision_id: uuid.UUID | None  # the decision that made the current CLEAR; None unless value == "CLEAR"
    decided_at: datetime | None

def current_background_check(company: ExporterProfile) -> str:
    """Pure, no I/O: the loaded company's current gauge value as a string."""

class BackgroundCheckReader:
    def __init__(self, db: AsyncSession) -> None: ...
    async def standing(self, company_id: uuid.UUID) -> BackgroundCheckStanding: ...
```

- **Semantics:** a read of committed/flushed state in the caller's session. It never commits,
  never flushes and **never locks**; the caller owns locking.
- **Errors:** unknown company → `ExporterProfileNotFoundError` (existing, Dev2's).
- **Handover:** blocked unless `value == "CLEAR"` (A5; Dev3's guard also requires `journey ==
  "CUSTOMER"`). "Not `CLEAR`" is never treated as "clear".
- **Locking expectation:** whether Dev3's guard must lock the company row so a concurrent
  `FLAGGED` cannot slip past a handover is **D10**. Dev4A's own moves always take the row lock, so
  a guard that also locks (or `FOR SHARE`s) the row is fully serialised against them.
- **The Dev3 swap** (sanctioned in `docs/dev3b-remaining-work.md` §6 items 19–20, Dev3 review):
  `read_background_check(company)`'s body becomes `return current_background_check(company)`. The
  function keeps its name and signature. **Nothing else in `deal_service.py` changes.** The
  `clear_background_check` monkeypatch fixture in `test_l3b_handover.py` stays until a real
  `CUSTOMER` can be produced (L2-11) — see §17.
- **Unavoidable Dev3 test impact:** as soon as the column exists, Dev3's stand-in starts returning
  `"NOT_STARTED"`, so two assertions whose premise was "the column does not exist" become false:
  `test_l3b_deal_buyer.py::test_handover_is_blocked_because_no_background_check_exists_yet` and
  `test_l3b_handover.py::test_the_handover_is_refused_while_no_background_check_exists`. Dev4A
  updates only those two assertions (to the new, true blocked reason) in the same phase that adds
  the column, with Dev3 review. This is a direct consequence of Dev4A's change, not an unrelated
  test.

### 5.9 Customer-event integration (L4-05 second half, L4-12, A1)

**BLOCKED — U4 / O3 DECISION REQUIRED.** Dev4A does not build the move to `CUSTOMER`, does not
call Dev2, does not publish `company.became_customer`, and does not assemble its payload in a
code path. Whatever U4 decides, the data Dev4A owes is already covered by
`BackgroundCheckReader.standing` (`risk_rating`, `clearing_decision_id`). L4-12's documentation
is already in `event-envelope.md` §3 (Dev1); Dev4A reviews it and records its acknowledgement.

### 5.10 Background-check API / read model

New router file, Dev4A's own (absolute paths under the `/onboarding` mount):

| Method | Path (proposal) | Roles | Purpose |
|---|---|---|---|
| GET | `/exporters/{company_id}/background-check` | per D8 (at least OPERATIONS, COMPLIANCE, ADMIN) | current value, risk, latest decision, served `allowed_moves` for this user |
| POST | `/exporters/{company_id}/background-check/decisions` | OPERATIONS, COMPLIANCE, ADMIN at the route; per-move roles in the service | record a move (`to_value`, `reason`, `risk_rating`) |
| GET | `/exporters/{company_id}/background-check/decisions` | as the first GET | decisions newest first, each with its evidence snapshot, paged |

- Request bodies never carry an actor, a source, a decided-by-kind or an evidence list chosen by
  the caller (`extra="forbid"`). The snapshot is assembled by the server.
- 401/403/404/409/422 declared in `responses=` (§7.5); every route gets rows in both route-auth
  tables and a refusal test.
- Masking: a decision carries no tax identifier; if a response ever embeds one it goes through
  `api/schemas/masking.py` (Dev1's; read-only).

### 5.11 Background-check frontend (L4-13, gauge half)

`pages/panels/BackgroundCheckPanel.tsx` becomes: the gauge and its risk chip, the latest decision
and reason (where authorised), decision history with each evidence snapshot, a move dialog that
offers **only** the server's `allowed_moves` (reason field required where the server says),
`CRITICAL` visibly distinct, loading/empty/error states, and — unchanged, below it — Dev4B's
`<VerificationSection customerId={…} />`. Honest placeholders: say "not started", never imply a
check ran. The frontend holds no move table and no role checks of its own. Tests for every state.

---

## 6. 4A ↔ 4B Contract

This section is identical in `docs/dev4/4b-task.md`.

### 6.1 The one interface

| | |
|---|---|
| **Provider** | Dev4B |
| **Consumer** | Dev4A (CLEAR prerequisites and every evidence snapshot). Buyer reads may also be used later by Dev3's deal page — never by the company gauge |
| **Types module** | `backend/app/modules/onboarding/domain/compliance_inputs.py` — pure frozen dataclasses and a `Protocol`, no I/O. Owner: Dev4B |
| **Implementation** | `backend/app/modules/onboarding/application/compliance_inputs.py` — `ComplianceInputsService(db)` implementing the Protocol. Owner: Dev4B |
| **Lands** | In the **Dev4 seam PR** (Dev4B Phase 4B-0), on `main`, before either branch touches a shared file. The first implementation reads today's tables honestly; Dev4B evolves the internals later without changing the outputs |

```python
# domain/compliance_inputs.py  (Dev4B)

@dataclass(frozen=True)
class VerificationInput:
    verification_result_id: uuid.UUID
    verification_type: str          # VerificationType value
    entity_type: str                # "EXPORTER" in company_inputs; "BUYER" in buyer_checks
    provider: str                   # stored provider, verbatim
    status: str                     # PENDING | PASSED | FAILED | REVIEW
    risk_level: str | None
    performed_at: datetime
    is_placeholder: bool            # created without a provider (e.g. normalized_result.stub)
    latest_review_id: uuid.UUID | None
    latest_review_status: str | None     # ACCEPTED | REJECTED | ESCALATED
    latest_reviewed_at: datetime | None
    evidence_document_ids: tuple[uuid.UUID, ...]

@dataclass(frozen=True)
class ScreeningItemInput:
    item_key: str
    screening_review_item_id: uuid.UUID | None   # the latest row; None if never recorded
    status: str | None                           # NEEDS_REVIEW | PASSED | FAILED | EXEMPT | None
    reviewed_by: str | None
    reviewed_at: datetime | None

@dataclass(frozen=True)
class CompanyComplianceInputs:
    company_id: uuid.UUID
    screening_catalogue: tuple[str, ...]            # the eight keys, in display order
    screening_items: tuple[ScreeningItemInput, ...]  # exactly one per catalogue key, same order
    verifications: tuple[VerificationInput, ...]     # subject EXPORTER + this company, newest first

class ComplianceInputsReader(Protocol):
    async def company_inputs(self, company_id: uuid.UUID) -> CompanyComplianceInputs: ...
    async def buyer_checks(self, deal_buyer_id: uuid.UUID) -> tuple[VerificationInput, ...]: ...
```

### 6.2 Invariants

1. **Facts, not judgements.** The reader reports statuses. It exposes no `is_clear_ready`, no
   "pending" verdict and no "answered" verdict — those are Dev4A's rules and decision gates
   (D1–D3). Adding a judgement field is a contract change.
2. **Read-only in the caller's session.** Never commits, flushes, locks or writes history.
3. **Company scope** is `entity_type = EXPORTER` and `entity_reference = company_id`. Checks on
   subjects with no company link (DIRECTOR, INVOICE, VESSEL, SHIPMENT) are not returned; whether
   that is acceptable for "no checks pending" is **D2**.
4. **Buyer isolation.** `buyer_checks` is keyed by `deal_buyer.id` only. Nothing returned by
   `buyer_checks` is ever included in `company_inputs`, and Dev4A never reads it for the gauge
   (architecture §3.5, decision 9).
5. **Stable latest.** "Latest review" and "latest screening row" are deterministic
   (`created_at DESC, id DESC`), whatever storage Dev4B uses underneath.
6. **Serialisation.** Dev4A reads under its company `FOR UPDATE` lock. Dev4B's writers of
   company-scoped inputs (screening decisions; verification results and reviews whose subject is
   the company) take a `FOR SHARE` lock on the company row before writing, so a `CLEAR` and a
   new pending input cannot interleave. (Screening inserts already take `FOR KEY SHARE` via their
   foreign key; verification results have no foreign key and need the explicit lock.)
7. **Output shape is frozen** once the seam lands. Internals may change freely.

### 6.3 Error behaviour

| Case | Behaviour |
|---|---|
| Unknown company | `ExporterProfileNotFoundError` (existing) |
| Unknown `deal_buyer_id` | a new Dev4B exception, 404 |
| Company with no inputs | a valid empty value: eight `ScreeningItemInput` rows with `status=None`, `verifications=()` |
| Database error | propagates; the reader never swallows |

### 6.4 Ownership and forbidden edits

| | Dev4A | Dev4B |
|---|---|---|
| `domain/compliance_inputs.py`, `application/compliance_inputs.py` | **read / import only** | owns |
| `background_check_reader.py`, background-check service, entities, router | owns | **must not import** |
| Screening/verification tables, repositories, services | **must not read or import directly** | owns |
| Background-check tables | owns | **must not read** |

A change to §6.1's output shape needs both developers' written agreement in both task files
before code.

---

## 7. Files Owned

Paths relative to `backend/app/modules/onboarding/` unless shown otherwise.

**Modify:**

| File | Change | Owner review |
|---|---|---|
| `domain/entities/exporter_profile.py` | add the `background_check` mapped column (and risk only if D5 says so). Precedent: Dev3A added `conversation` here | Dev2 |
| `application/deal_service.py` | **only** the body of `read_background_check` (§5.8) | Dev3 |
| `tests/integration/test_l3b_deal_buyer.py`, `tests/integration/test_l3b_handover.py` | **only** the two "not recorded yet" assertions (§5.8) | Dev3 |
| `frontend/src/modules/onboarding/pages/panels/BackgroundCheckPanel.tsx` | rebuilt as the gauge panel (§5.11) | — |
| `frontend/src/modules/onboarding/api/index.ts`, `hooks/index.ts`, `components/index.ts` | one `export` line each for Dev4A's new files (Dev4B does not edit these barrels) | Dev1 |

**Add:**

- `domain/entities/background_check_enums.py` (gauge values; the Dev4A-owned risk values — D13)
- `domain/entities/background_check_decision.py` (decision and evidence entities)
- `domain/background_check_views.py`
- `infrastructure/repositories/background_check_decision_repository.py`
- `application/background_check_service.py`
- `application/background_check_reader.py`
- `api/background_check_router.py`, `api/schemas/background_check.py`
- `migrations/onboarding_0015_bg_check.py` (§10)
- `tests/integration/test_l4a_*.py`, `tests/unit/test_l4a_*.py`
- `frontend/src/modules/onboarding/api/background-check.ts`, `hooks/background-check.ts`
- `frontend/src/modules/onboarding/components/BackgroundCheckGauge.tsx`, `RiskChip.tsx`,
  `BackgroundCheckMoveDialog.tsx`, `DecisionHistory.tsx` (names indicative) and their tests
- `docs/contracts/background-check.md` (L4-01)

---

## 8. Files Read-Only

- **Dev4B's files** (all of §7 of `4b-task.md`), including `components/VerificationSection.tsx`,
  `api/verification.ts`, `hooks/verification.ts`, `application/verification_service.py`,
  `application/screening_review_service.py`, `api/screening_router.py`, the verification block
  of `api/router.py`, the adapters and `domain/workflow_dependencies.py`.
- `domain/compliance_inputs.py`, `application/compliance_inputs.py` (import only).
- Dev1: `application/history_service.py`, `api/history_router.py`,
  `domain/entities/exporter_lifecycle_history.py`, `api/schemas/masking.py`,
  `events/publisher.py`, `app/platform/messaging/*`, `app/platform/authorization/*`,
  `conftest.py`, `tests/fixtures/companies.py`, `frontend/src/lib/api/client.ts`,
  `components/HistoryTimeline.tsx` (already labels `background_check`).
- Dev2: `application/qualification_service.py`, `application/exporter_profile_service.py`,
  `api/exporter_router.py`, `api/schemas/exporter.py`, `sample_data.py`,
  `pages/ExporterDetailPage.tsx`, list/pipeline pages, `CompanyChips.tsx`.
- Dev3: everything else in `deal_service.py`, `document_service.py`,
  `infrastructure/repositories/crm_document_repository.py` (call `list_for_owner` /
  `list_for_deal_ids` only), `conversation_service.py`, Dev3 pages.

**Forbidden:** `app/modules/kyb`, `cases`, `customers`, `compliance` (the only exception, EX-001,
is Dev1's and closed); `onboarding_request` and everything on the legacy path
(`onboarding_request_service.py`, `onboarding_transition_service.py`, `workflows/`,
`screening_result_service.py`, `risk_rating_assignment_service.py`, `domain/policies/*`,
`case_service.py`); other developers' migrations; the three stale branches.

---

## 9. Controlled Shared Files

These are Developer 1's index and test-table files. Both Dev4A and Dev4B must add to them
(§7.5 requires every new route to have route-authorisation rows; new entities must be
registered). Zero sharing is not possible here, so the **Dev4 seam PR** (4B-0) cuts each file's
tail into two owned anchor blocks — the pattern Dev3A/Dev3B used, whose header comments already
explain why it keeps owners in separate diff hunks. After the seam, **each developer edits only
inside its own block, and nowhere else in the file.** Both files list the same table.

| File | Dev4A may | Dev4B may |
|---|---|---|
| `exceptions.py` | add classes under "Background check — owner: Developer 4A" | add classes under "Verification and screening — owner: Developer 4B"; **and** edit the existing `EXP-2: VerificationResult` classes (lines ~322–420) |
| `domain/entities/__init__.py` | import + `__all__ +=` in its block | same, its block |
| `infrastructure/repositories/__init__.py` | same | same |
| `application/__init__.py` | same | same |
| `backend/tests/contract/test_route_authorization_coverage.py` | rows in its block | rows in its block; **and** the existing "compliance workspace" and "verification results" sections |
| `tests/integration/test_route_authorization.py` | rows in its block | rows in its block; **and** the existing "verifications" / "screening review" rows, `_trigger_body()`, and the FIX 3 / FIX 4 tests |
| `api/router.py` | one import and one `router.include_router(background_check_router)` under its anchor | only the `EXP-2: generalized verification results` block and its imports |
| `frontend/src/modules/onboarding/types.ts` | aliases in its block | aliases in its block; **and** the existing `Verification*` / `Screening*` / `BankActivity*` aliases |

**Generated artifacts** — `frontend/openapi.json`, `frontend/src/lib/api/schema.ts`: never
hand-edited. Each branch regenerates them so `test_openapi_artifact_is_current` passes, with
`APP_NAME` pinned to the `Settings` default (see `dev3b-remaining-work.md` §2.4). On the second
PR's rebase, **conflicts in these two files are resolved by regenerating, never by merging
hunks**. Dev1 (L1-14) reviews both.

The seam PR creates every anchor above. It also adds the Dev1-reviewed header comment in each
file naming the two owners.

---

## 10. Migration Ownership

| | Dev4A | Dev4B |
|---|---|---|
| File | `migrations/onboarding_0015_bg_check.py` | `migrations/onboarding_0021_verif_review.py` |
| Revision id | `onboarding_0015_bg_check` (24 chars) | `onboarding_0021_verif_review` (28 chars) |
| Why that number | 0015 is the register's background-check slot | 0021 is the next free label after 0020; the two branches never share a filename |
| `down_revision` at branch time | the head when the branch starts (today `onboarding_0019_documents`) | same |

**Dev4A's migration contains only:** the gauge enum and the `exporter_profile.background_check`
column; the decision table, its `prevent_mutation()` trigger, the unique supersedes pointer and
the reason/risk `CHECK`s; the evidence table, its trigger and its FKs to `crm_document`,
`verification_result` and `screening_review_item`; the **Dev4A-owned risk enum type** (D13:
`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`, a new type, not `verification_risk_level_enum` or any other
existing risk type) and the decision's risk column that uses it; background-check indexes.
**No risk column on `exporter_profile`** while D5 is open. Nothing verification- or
screening-shaped.

**It references no Dev4B schema.** The verification-review id in the evidence snapshot is a bare
uuid on purpose, so the two migrations stay independent. An FK to Dev4B's review table, if wanted,
is a post-merge item (§17).

**Rules** (`migration-register.md` §2):

- One chain, one head. Both branches start from the same head, so **the PR that merges second
  re-parents its own `down_revision` to the first PR's revision id** (a one-line change),
  then proves `alembic heads` prints exactly one revision and a clean
  `upgrade head → downgrade -1 → upgrade head` round trip. Never add a merge revision; never
  renumber the file.
- If `main` gains another migration before either merges, re-parent onto it the same way.
- Enums are created in an ordinary transactional migration; never `ALTER TYPE … ADD VALUE` in an
  autocommit block. Revision ids ≤ 32 characters.
- The downgrade is written; if lossy, it says so.
- Every new constraint and trigger gets a direct-SQL violation test (psycopg2, bypassing the ORM).
- Dev4A does **not** edit `docs/contracts/migration-register.md`; it tells Dev1 the row to add
  (number, owner, content, parent) after merge.

---

## 11. API / Schema Ownership

| Artifact | Owner |
|---|---|
| `api/background_check_router.py`, `api/schemas/background_check.py` and every schema in it | Dev4A |
| The background-check paths in `openapi.json` / `schema.ts` | Dev4A generates on its branch; Dev1 reviews |
| `/verifications*`, `/exporters/{id}/screening-review*`, `/exporters/{id}/bank-activity` | Dev4B — Dev4A never changes them |
| Company responses (`schemas/exporter.py`) | Dev2 — exposing the gauge on company list rows/filters is post-merge (§17) |

---

## 12. Dependency Classification

| Item | Class | Why | Owner of the dependency | What clears it | Blocks |
|---|---|---|---|---|---|
| L4-01 background-check contract doc | PARALLEL | — | Dev4A | — | — |
| Migration + ORM column | CONTRACT-DEPENDENT; **seam CLEARED (4B-0 complete, 28 Sep 2026)** | needs the seam's anchor blocks in `entities/__init__.py` | Dev4B (seam PR) | seam PR merged | nothing once the seam is on `main` |
| Risk on company | DECISION-BLOCKED (partly) | D5 (D13, the risk type, settled 28 Sep 2026: Dev4A-owned) | Dev4 (A+B) with lead | written decision in `background-check.md` | the company column only; the decision's risk and its type are settled |
| Gauge moves except CLEAR | CONTRACT-DEPENDENT | every decision snapshots evidence through the reader | Dev4B | seam PR merged | implementation |
| CLEAR mechanism | CONTRACT-DEPENDENT | reads inputs through the reader | Dev4B | seam PR merged | implementation |
| CLEAR prerequisite rules | DECISION-BLOCKED | D1, D2, D3 | programme lead with compliance | answers recorded in `background-check.md` | final merge (mechanism can be built and tested with parameterised rules) |
| Evidence snapshot contents | DECISION-BLOCKED (partly) | D4 | programme lead | answer in contract | final merge of the document part; ids of checks/screening rows are settled |
| Reopen / reassess | PARALLEL (after gauge phase) | — | — | — | — |
| Read helper | PARALLEL | — | — | — | — |
| Dev3 stand-in swap + two test assertions | DEV3-DEPENDENT | edits Dev3's file under their sanction | Dev3 | Dev3 review on the PR | integration, not implementation |
| Handover guard row lock | DECISION-BLOCKED | D10; Dev3's code | Dev3 + lead | decision; Dev3 change if "yes" | final integration only |
| API + route-auth rows | CONTRACT-DEPENDENT | route-auth anchors | Dev4B (seam) | seam PR | implementation |
| Frontend panel | PARALLEL once the API exists on the branch | renders Dev4B's `VerificationSection` by its existing props | Dev4B keeps `VerificationSection({ customerId })` stable | §6 / §9 of `4b-task.md` | — |
| DEVELOPER visibility | DECISION-BLOCKED | D8 | lead + Dev1 | decision | route roles and UI for DEVELOPER; default until decided: no widening |
| L4-05 signal / CUSTOMER move / `became_customer` | DECISION-BLOCKED — **U4 / O3 DECISION REQUIRED** | cross-service transaction and who announces | lead, Dev2, Dev4A | written U4 decision | everything in §5.9 |
| Automatic start on RXIL results (A8) | DECISION-BLOCKED — **RXIL PACKAGE CONTRACT REQUIRED** | no results format; actor for an automatic move (D12) | RXIL, lead, Dev2 (parser) | published package contract | that move only |
| Company list chip / filter (L4-08 "filter") | DEV2-DEPENDENT, POST-MERGE | Dev2's list/schemas | Dev2 | Dev2 PR using `RiskChip` + the column | final demo, not Dev4A's PR |
| Sample data for §3.9 companies B and C | POST-MERGE, DEV2-DEPENDENT | Dev2's `sample_data.py` call site; B needs L2-11 | Dev2, Dev4A | hook call site; U4 | final demo |
| L4-14 end-to-end test / M5 | POST-MERGE + DECISION-BLOCKED | needs both PRs, L2-11, U4; "in CI" needs U6 (not Dev4's) | all | — | M5 |

---

## 13. Decisions Required Before Implementation

Numbering is shared with `4b-task.md`. Only the ones that affect Dev4A are listed.

| # | Decision | Status on `main` | Blocks for Dev4A |
|---|---|---|---|
| D1 | **CLEAR prerequisite semantics** — what exactly must be true (A3: risk; no checks pending; eight items answered; evidence). | Unsettled beyond A3's wording | final merge (rule function); not the mechanism |
| D2 | **Meaning of "pending"** — `status=PENDING` only? also `REVIEW` without an accepted review? placeholder rows? DIRECTOR/other subjects with no company link? | Unsettled | final merge (rule function) |
| D3 | **FAILED screening vs CLEAR** — does "answered" include `FAILED`? `EXEMPT`? can a company be CLEAR with a FAILED item? | Unsettled | final merge (rule function); UI copy |
| D4 | **Evidence snapshot scope** — which documents (company only? company + open deals? only `AVAILABLE`?); what counts as "evidence recorded" for CLEAR | Unsettled | final merge of document pinning and the CLEAR evidence rule |
| D5 | **Risk placement and requiredness** — on the company record too? required/allowed on `FLAGGED`/`ON_HOLD`/others? | **Open** (Figure 3 vs company-record §2.4). Non-blocking for 4A-2: the migration omits the company column and risk lives on the decision record | the company column only (a later migration if D5 adds it), integration (Dev2 list), UI |
| D6 | **Risk after reopening** — does the company keep showing the last CLEAR's risk while `IN_REVIEW`? cleared? | Unsettled | integration and UI; `standing.risk_rating` semantics |
| D8 | **DEVELOPER visibility** — may DEVELOPER read the gauge value, the decision reasons, the evidence ids? (history route already admits DEVELOPER) | Unsettled | route roles, UI, history `reason` policy; default: no widening |
| D10 | **Company row lock during handover** — must Dev3's guard lock/share-lock the company row? | Guard reads without a lock today | final integration (Dev3 change) |
| D11 | **U4 / O3 transaction boundary** — S1-style flush-only seam, shared session, or retry-safe separate commits; and who publishes `company.became_customer` after the commit | Undecided | all of §5.9 (BLOCKED) |
| D12 | **RXIL package / results contract**, including the actor of the automatic `NOT_STARTED → IN_REVIEW` move | Undecided | the automatic start only |
| D13 | **Risk database type** — reuse `onboarding.verification_risk_level_enum` (Dev4B's) or a Dev4A-owned type | **Settled 28 Sep 2026 (Dev4 lead):** a Dev4A-owned enum type with exactly `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`, created in `onboarding_0015_bg_check`. Dev4B's enum is not reused, keeping the two migrations independently owned with no schema dependency between them. It is the CRM background-check risk vocabulary (decision 6 fixes the values, not the type) and changes no legacy, customer or onboarding risk type | nothing (was: migration) |
| D14 | **History contract gap** — `history-row.md` §4 omits the `MORE_INFO → IN_REVIEW` note and the `CLEAR` reason the architecture requires | Dev1's contract | nothing in code (Dev4A enforces the architecture); contract text before final merge |

Record every answer in `docs/contracts/background-check.md` with its date and who decided.

---

## 14. Implementation Phases

> **Dev4A status (28 Sep 2026).**
>
> | Item | Status |
> |---|---|
> | **4B-0 dependency** (the §6 seam and the §9 anchor blocks) | **CLEARED.** Dev4B Phase 4B-0 is complete (`4b-task.md` §14, 4B-0 status). Dev4A consumes `domain/compliance_inputs.py` and `ComplianceInputsService` exactly as §6 documents, and edits only its own anchor blocks. |
> | **Dev4A implementation** | **NOT STARTED.** No contract doc, migration, entity, service, reader, API or panel yet. |
> | **D13** (risk database type) | **Settled:** a Dev4A-owned enum type (§13). |
> | **D5** (risk on the company record) | **Open, non-blocking:** no company risk column (§13). |
> | **U4 / D11** (customer transition) | **Blocked:** §5.9 and 4A-9 untouched. |
> | **D1–D4** (CLEAR prerequisites, evidence scope) | **Required before CLEAR implementation** (4A-4). |
>
> Two seam facts Dev4A builds on (from the 4B-0 status): company-scoped Dev4B writers already
> take `FOR SHARE` on the company row, so Dev4A's `FOR UPDATE` serialises against them; and
> until 4B-2, `VerificationInput.latest_review_id` and `latest_reviewed_at` are `None` even on
> a reviewed result, so `latest_review_status` is what says whether a review exists.

Each phase ends with the suite at baseline, ruff/import-linter unchanged, and (from 4A-6) the
OpenAPI artifact current. A phase that cannot meet its stop condition stops and reports.

### 4A-1 — Contract (L4-01)
- **Objective:** publish `docs/contracts/background-check.md`.
- **Scope:** values; the move table with roles and required text; decision record; evidence
  snapshot shape; risk (settled parts including D13's answer; D5/D6 marked open); read helper
  (§5.8); history usage; error codes; open decisions D1–D14 with owners; the 4A ↔ 4B contract by reference.
- **Files:** the new contract doc only.
- **Prerequisites:** none. **Other branch:** none.
- **Outputs:** the doc; acknowledgement requests to Dev1, Dev2, Dev3, Dev4B.
- **Tests:** none.
- **Stop when:** the doc is written and every open item is listed with an owner.

### 4A-2 — Schema, entities and ORM column
- **Objective:** migration `onboarding_0015_bg_check` and the entities.
- **Scope:** §10 contents; `ExporterProfile.background_check`; entity/repository registration in
  4A anchor blocks; the two Dev3 assertions (§5.8).
- **Files:** migration, `background_check_enums.py`, `background_check_decision.py`, repository,
  `exporter_profile.py` (Dev2 review), anchor blocks, the two Dev3 test assertions (Dev3 review).
- **Prerequisites:** the Dev4B seam (4B-0), **CLEARED 28 Sep 2026** (see the status block
  at the top of §14). D13 is settled (the Dev4A-owned risk type, §13), so it no longer
  blocks this phase. D5 stays open and is not a prerequisite: the company risk column is
  **omitted**.
- **Outputs:** one head; clean round trip.
- **Tests:** direct-SQL: `UPDATE`/`DELETE` refused on decision and evidence tables; reason and
  risk `CHECK`s; unique supersedes; FK RESTRICT on company and evidence targets; column default.
- **Stop when:** round trip clean, suite at baseline including the two updated Dev3 assertions.

### 4A-3 — Gauge service: forward moves
- **Objective:** `BackgroundCheckService` for every move except `CLEAR` and the moves out of
  `CLEAR`/`FLAGGED`/`ON_HOLD`.
- **Scope:** row lock, per-move roles, reasons, supersession, evidence snapshot via the reader,
  history row, one commit, `allowed_moves(value, user)`.
- **Prerequisites:** 4A-2; seam (reader). **Other branch:** none (tests use the seam reader or a
  fake `ComplianceInputsReader`).
- **Tests:** every legal move; every illegal one refused with nothing written; role refusals per
  move; rollback discards value + decision + history together; concurrent moves cannot fork the
  chain.
- **Stop when:** the §5.1 table is covered except CLEAR and the reassess/reopen rows.

### 4A-4 — CLEAR orchestration
- **Objective:** `IN_REVIEW → CLEAR`.
- **Scope:** single COMPLIANCE/ADMIN user; risk required; prerequisites as one pure rule function
  over `CompanyComplianceInputs`; `clearing` recorded; evidence snapshot.
- **Prerequisites:** 4A-3. D1–D4 **for the rule function's content**.
- **Tests:** rule-function unit tests per gate answer; service tests with a fake reader (each
  prerequisite failing on its own); OPERATIONS refused; risk missing refused.
- **Stop when:** mechanism complete. If D1–D4 are unanswered, stop with the rule function holding
  only what A3 states verbatim, flagged `DECISION PENDING` in code and contract — the PR cannot
  pass final review until they are answered.

### 4A-5 — Reopen and reassessment
- **Objective:** `CLEAR → IN_REVIEW`, `FLAGGED/ON_HOLD → IN_REVIEW`.
- **Scope:** reason required; supersedes; original unchanged; journey untouched; `CLEAR → FLAGGED`
  refused.
- **Prerequisites:** 4A-4.
- **Tests:** original decision row byte-identical after reopen (direct SQL); a `CUSTOMER` stays
  `CUSTOMER` (fixture company inserted at `CUSTOMER`, since L2-11 does not exist).
- **Stop when:** the whole §5.1 table is covered.

### 4A-6 — Read helper and the Dev3 seam
- **Objective:** `background_check_reader.py` (§5.8) and the stand-in swap.
- **Scope:** `current_background_check`, `BackgroundCheckReader.standing`; `read_background_check`
  body in `deal_service.py` (Dev3 review).
- **Prerequisites:** 4A-5.
- **Tests:** standing for each value; `clearing_decision_id` only when CLEAR; no lock taken; the
  existing `test_l3b_handover.py` suite passes unchanged apart from §5.8's assertion.
- **Stop when:** Dev3's guard reads the real column through the helper.

### 4A-7 — API and route authorisation
- **Objective:** the three routes (§5.10), schemas, allowed moves in the response.
- **Files:** router, schemas, 4A router anchor in `api/router.py`, route-auth rows in both tables,
  `openapi.json`/`schema.ts` regenerated.
- **Prerequisites:** 4A-6; D8 for DEVELOPER (default: not admitted).
- **Tests:** API tests per move; 401/403/404/409/422; request with `actor`/`source`/evidence
  refused (422); route-auth coverage and refusal rows; OpenAPI current.
- **Stop when:** OpenAPI current and the coverage test classifies every new route.

### 4A-8 — Background check panel
- **Objective:** §5.11.
- **Files:** `BackgroundCheckPanel.tsx`, Dev4A's new components, `api/background-check.ts`,
  `hooks/background-check.ts`, the 4A types block, three barrel lines.
- **Prerequisites:** 4A-7.
- **Tests:** vitest for gauge render per value, CRITICAL distinct, move dialog offers only served
  moves, reason required, error/empty/loading, `VerificationSection` still rendered.
- **Stop when:** tsc, eslint, vitest, build pass.

### 4A-9 — Customer transition hand-off — **BLOCKED — U4 / O3 DECISION REQUIRED**
- Not started until D11 is written down. Then: the agreed seam with Dev2 (L2-11), the announcement
  path, and invariant 2 of company-record §8 under test.

---

## 15. Testing Plan

**Independently on the 4A branch:**

- Unit: rule function (D1–D4), move table, allowed moves per role, `current_background_check`.
- Service (integration, real DB): every move, refusals leave nothing, rollback atomicity, row
  lock serialises two concurrent decisions, supersedes chain cannot fork.
- Repository / database: direct-SQL immutability of decision and evidence rows, CHECKs, unique
  supersedes, FK RESTRICT.
- Authorization: both route-auth tables (rows in the 4A block), refusal per role, OPERATIONS
  limited to start and `MORE_INFO → IN_REVIEW`.
- API: request/response shapes, forbidden fields, error codes.
- Reader contract: consume the seam's `ComplianceInputsService` against real rows; a fake
  `ComplianceInputsReader` for edge cases.
- Dev3 regression: `test_l3b_deal_buyer.py`, `test_l3b_handover.py`, `test_l3b_documents.py`.
- Frontend: vitest for the panel and components; `npx tsc -b --noEmit`; `npx eslint .`;
  `npx vite build`.
- Gates: `alembic heads` (one), round trip, `pytest -q --no-cov -p no:cacheprovider`,
  `ruff check .`, `lint-imports --config importlinter.ini`,
  `test_openapi_artifact_is_current`.

**Needs Dev4B's merged PR:** CLEAR against real superseding reviews (latest review from Dev4B's
table), evidence snapshot pinning a real verification review id, placeholder rows flagged by
Dev4B, company-scoped input writes taking `FOR SHARE`.

**Final integration (post-merge):** §17.

Compare the full suite with the §3 baseline failure set; any new failure outside it is a
regression. Do not edit unrelated failing tests.

---

## 16. Merge Strategy

1. **Dev4 seam PR (Phase 4B-0) merges first.** Anchor blocks in every §9 file; the §6 types
   module and its read-only implementation. No behaviour change; `openapi.json` byte-identical.
   Reviewed by Dev4A, Dev4B and Dev1. Both branches are cut from (or rebased once onto) `main`
   after it.
2. **Dev4A and Dev4B PRs are independent** and may merge in either order. Recommended: Dev4B
   first (its L4-02/L4-07 fixes are §7.6 gate items), but nothing forces it.
3. **The second PR rebases once** onto `main`: re-parent its migration (§10); regenerate
   `openapi.json`/`schema.ts` (never hand-merge); resolve anchor blocks (no overlap is expected);
   rerun the full suite and frontend gates.
4. **Contracts verified before each merge:** §6 output shape unchanged; `background-check.md`
   acknowledged by Dev1, Dev2, Dev3, Dev4B; D1–D4 answered for Dev4A's merge.
5. **Independent test runs** per §15; **integration tests** per §17.
6. **No cherry-picking** between the branches during development. Dev4A codes against the seam
   reader; it never pulls Dev4B commits.

---

## 17. Post-Merge Integration

One controlled step after both PRs are on `main` (owner: Dev4A, reviewed by Dev4B):

- Integration tests: CLEAR end to end with real verification results, a superseding review, all
  eight screening items and pinned documents; a later upload/review does not change a past
  decision's snapshot; a buyer check never moves the company gauge.
- Optional: a small Dev4A migration adding an FK from the evidence snapshot's review id to Dev4B's
  review table (only if both agree).
- Dev1: add the register rows for both migrations; regenerate types at the milestone;
  acknowledge D14.
- Dev2 (their PRs, Dev4A supplying `RiskChip` and the helper): company list/header chip and filter
  for the gauge and `CRITICAL`; `sample_data.py` call site for a Dev4A sample hook (company C
  `FLAGGED`; company B `CLEAR`, its `CUSTOMER` move waiting on L2-11/U4).
- Dev3: D10 lock change if decided; retire the `clear_background_check` fixture once L2-11 can
  produce a real `CUSTOMER`.
- **Final Dev4 audit verifies:** one Alembic head and clean round trip; suite at baseline; §5.1
  table fully enforced; decisions and evidence immutable in the database; reader used, no direct
  reads of Dev4B tables; `CLEAR → FLAGGED` refused; handover allowed only for `CUSTOMER` + `CLEAR`;
  OpenAPI current; route-auth coverage complete; UI offers only served moves; `CRITICAL`
  distinct; blocked items still blocked and labelled.

---

## 18. DO NOT BUILD

- **No third verification framework.** Decisions are the gauge's log, not another check system.
- **No new document system** — pin `crm_document` ids.
- No legacy `onboarding_request` workflow, no 18-state onboarding machine, nothing under
  `workflows/`.
- **No case engine** (A6). No Middesk, Trulioo or Sumsub.
- No changes to `kyb`, `cases`, `customers` or `compliance` modules; no new module-rule exception.
- **No deal lifecycle work** beyond the one sanctioned function body; no lending, transaction or
  performance tracking.
- No new customer or deal state machine; **no journey writes**.
- **No speculative U4 solution**: no CUSTOMER move, no call into Dev2, no `became_customer`
  publish.
- **No speculative RXIL package parsing**; no automatic start on RXIL results.
- No fake provider results, fake bank findings or placeholder decisions.
- **No universal allowed-moves framework**; serve this gauge's moves only.
- No edits to Dev4B's files, to `history_service.py`, to the history/event/migration contracts,
  or to existing risk enums.
- No frontend source of truth: no hand-copied move table or role list.
- Nothing from `feature/provider-adapter-wiring`, `feature/vendor-adapter-wiring`,
  `feature/case-bridge-event-wiring`.

---

## 19. Definition of Done

- `docs/contracts/background-check.md` merged and acknowledged by Dev1, Dev2, Dev3 and Dev4B;
  every decision it depends on either answered (D1–D6, D8, D13) or explicitly blocked (D10–D12).
- `onboarding_0015_bg_check` merged; one head; clean round trip; direct-SQL tests for every
  constraint and trigger.
- Every move in §5.1 works for the right roles with the right text; every other move and role is
  refused with nothing written; a reopen leaves the original decision unchanged.
- Each decision stores an evidence snapshot of ids; later changes do not alter it.
- Risk `LOW/MEDIUM/HIGH/CRITICAL` on decisions; required on CLEAR; `CRITICAL` distinct on screen.
- History row for every move, in the same transaction, with the decision id.
- `read_background_check` delegates to Dev4A's helper; handover still Dev3's.
- API routes declared with roles and 403s; route-auth rows; OpenAPI current.
- Panel usable end to end on sample data, with tests.
- Suite at the §3 baseline; ruff 16; import-linter 19/0; tsc/eslint/vitest/build pass.
- L4-05/U4 and RXIL items remain explicitly **BLOCKED** and are not stubbed.
