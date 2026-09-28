# Dev4B — Verification / Screening Integrity

> Companion document: **`docs/dev4/4a-task.md`** (Dev4A — Background Check / Compliance Core).
> The two documents describe one split of Developer 4's work (architecture §9.4) into two
> parallel pull requests. Sections 6 and 9 are identical in both files, and sections 10, 16 and
> 17 describe the same plan from each side. If they ever disagree, stop and reconcile before
> writing code.

---

## 1. Purpose

Dev4B owns the **inputs** to the background-check decision and makes them trustworthy:

- the existing **verification-result** system (`onboarding.verification_result`, the adapter
  registry, the manual and RXIL-stub adapters): superseding reviews instead of one frozen review,
  polling that can never overwrite a reviewed result, manual results that need evidence, honest
  provenance;
- the existing **eight-item screening checklist** (`onboarding.screening_review_item`): one
  server-side catalogue, validation, full history, served capabilities;
- **buyer checks**, recorded against `deal_buyer.id` and never the company;
- **honest placeholders**: no pending-forever rows, no misleading bank panel, no dev generator;
- the verification/screening UI, with tests;
- the **Dev4 seam PR** and the **4A ↔ 4B contract** (§6) that Dev4A reads the inputs through.

Dev4B does **not** decide the background check. The gauge, its decisions, the evidence snapshot,
risk and `CLEAR` belong to Dev4A (`docs/dev4/4a-task.md`).

A background-check decision is **not** a verification result and **not** a screening item.
Verification results and the eight screening items are **inputs** to the decision. Dev4B
**extends** the two existing systems; it does not create a third.

---

## 2. Source of Truth

In this order:

1. **`docs/Exporter-CRM-Architecture-and-Plan.pdf`** — authoritative. Relevant parts:
   §2.1 (RXIL results stored as given, never recomputed), §2.6 (principles; honest
   placeholders), §3.3 background-check bullets ("Inputs: verification results … plus the existing
   eight-item screening checklist … whose full history is shown"), §3.5 and decision 9 (buyer
   checks on the buyer), §3.6 (compliance team: "the CRM records their outcomes" via verification
   adapters), §3.7, §3.8 ("the existing verification-results table, the manual and RXIL adapters,
   the screening-checklist table and the shared 'cannot be changed' database protection are kept
   and reused"), §5.4, §5.5, §7.4 (0015's "superseding reviews on verification results"), §7.6
   (gate: "evidence required, honest pending checks, honest bank panel"), §9.4 (L4-02, L4-04's
   review half, L4-07, L4-09, L4-10, L4-11, L4-13's verification half), A13, Appendix E15, E17,
   E18, E19, E35, E42.
2. **The Dev4 Phase 0 audit** (verdict `DEV4-AUDIT-READY-WITH-DEPENDENCIES`, `main` @ `8d8606c`,
   28 Sep 2026).
3. **Code on `main`.**
4. **Contracts and handovers:** `docs/contracts/history-row.md` (§2 reserves the `verification`
   dimension for Dev 4), `migration-register.md`, `company-record.md`, `criterion-result.md`
   (§1: screening is not qualification; its evidence shape), `deal-and-buyer.md` (§3, §3.1),
   `storage-and-documents.md` (§4, §5), `docs/dev2-remaining-work.md` §5,
   `docs/dev3b-remaining-work.md` §6 items 23–25.

Where these disagree, the architecture wins; where it is silent, the item is a decision gate in
§13 — **do not invent the answer**.

---

## 3. Current Repository Baseline

As measured by the Dev4 audit (28 Sep 2026):

| Item | Value |
|---|---|
| `main` | `8d8606c` (Dev1 PR #7 `8fb8729`, Dev2 PR #8 `c117fdf`, Dev3A PR #9 `447c6ba`, Dev3B PR #10 `f703c05`) |
| Alembic | One head, `onboarding_0019_documents`. **0015 is unused.** |
| Backend suite | 30 failed / 3728 passed / 7 skipped / 22 errors. **Environment baseline: 29 failed + 22 errors** (compliance-module routes; read-only role passwords). The 30th, `test_l3a_conversation_gauge::test_a_check_back_date_in_the_past_is_refused`, fails only 00:00–05:30 IST (local vs UTC date) — a Dev3A test defect. None are Dev4's; do not "fix" them. |
| Other gates | ruff 16 · import-linter 19/0 · OpenAPI artifacts current · tsc clean · eslint 0 errors / 2 warnings · vitest 16 files / 131 · build ok |

What exists (all paths under `backend/app/modules/onboarding/`):

**Verification results (System 2)**

- `domain/entities/verification_result.py`: `entity_type` + `entity_reference` (bare uuid, no FK,
  by design), `provider`, `status` (PENDING/PASSED/FAILED/REVIEW), `risk_level`,
  `normalized_result`, `raw_result` (excluded from responses), `evidence_reference`
  (**never written by any code path**), `reviewed_by`/`review_status` (frozen once set by
  `trg_verification_result_field_immutability`, migration 0006). `status`, `risk_level`,
  `normalized_result` and `valid_until` remain mutable.
- `application/verification_service.py`: `trigger_verification`, `trigger_verification_batch`
  (no caller), `get_verification_status` (no route, no caller; **overwrites status/risk/
  normalized_result/valid_until even on reviewed rows**, lines 452–465), `list_verification_results`,
  `record_review` (one review only; second → 409). Every write commits itself.
- Adapters: `infrastructure/adapters/manual_entry_adapter.py` (`"manual"`, synchronous, accepts
  `PASSED` with no evidence), `stub_rxil_adapter.py` (registry key `"rxil"`, reports provider
  `"RXIL"` upper-case, batch-capable, stub). Registry and allow-list in
  `domain/workflow_dependencies.py`. Allowed providers: `VerificationProvider = Literal["manual",
  "rxil"]` (`api/schemas/verification.py`).
- Routes in `api/router.py` "EXP-2" block (lines ~368–488): `POST /verifications` (COMPLIANCE,
  ADMIN; **caller chooses `provider`, so COMPLIANCE can record a result as RXIL's**),
  `GET /verifications`, `GET /verifications/{id}` (OPERATIONS, COMPLIANCE, ADMIN; `normalized_result`
  unmasked), `POST /verifications/{id}/review` (COMPLIANCE, ADMIN; reviewer from the session).
- Nothing validates that `entity_reference` exists. No shared-history rows are written.

**Screening checklist (System 1)**

- `domain/entities/screening_review.py`, `application/screening_review_service.py`,
  `api/screening_router.py`, `api/schemas/screening.py`.
- Append-only (`trg_screening_review_item_append_only`, 0011); latest row per key wins; eight keys
  in `VALID_ITEM_KEYS` **and hand-copied** in `VerificationSection.tsx` `CHECKLIST_ITEMS`; status
  `NEEDS_REVIEW`/`PASSED`/`FAILED`/`EXEMPT` as an API `Literal` over a `varchar(32)` with no DB
  check; optional comment; no evidence; `list_item_history` exists but **no route**; DB FK to the
  company since 0014 but **the ORM model does not declare it** (`dev2-remaining-work.md` §5);
  no company-existence check in the service.
- `bank_activity_finding` + `GET /exporters/{id}/bank-activity`: read-only, hard-codes
  `connected_accounts=0`, no company FK.

**Frontend**

- `components/VerificationSection.tsx` (631 lines, **no tests**), `api/verification.ts`,
  `hooks/verification.ts`. Role checks hand-coded (`user.role === 'COMPLIANCE'`). A dev-only
  "Create placeholder records (dev)" generator inserts `PENDING` rows with
  `normalized_result.stub = true` that can never resolve. **There is no form to record a real
  manual result.**
- `pages/panels/BackgroundCheckPanel.tsx` wraps `VerificationSection` — that panel is Dev4A's.

**Stale branches that must never be merged into or built on:**
`feature/provider-adapter-wiring`, `feature/vendor-adapter-wiring`,
`feature/case-bridge-event-wiring`.

---

## 4. Ownership Boundary

| Area | Dev4B owns | Dev4B consumes (read-only) | Dev4B must not modify |
|---|---|---|---|
| Verification results | Service, adapters, registry, schemas, routes, enums, review model | — | kyb adapters; `ADAPTER_MODULE_ALLOWLIST` semantics |
| Screening checklist | Service, router, schemas, catalogue, history route | — | Qualification (never reuse screening as qualification) |
| Buyer checks | Validation, subject snapshot, reads | `deal_buyer` row via Dev3's repository | Deal, buyer, handover code |
| Evidence on inputs | Evidence fields on verification results / screening rows | `crm_document` ids via Dev3's repository | `crm_document`, storage, scanner |
| Contract | `domain/compliance_inputs.py`, `application/compliance_inputs.py` | — | — |
| History | `verification` rows it writes | `HistoryService.record` (Dev1) | `history_service.py`, the history contract |
| Background check | — | — | Every Dev4A file; the gauge column; decisions; risk |
| Bank activity | Honest read model | — | Inventing findings |
| Frontend | `VerificationSection.tsx` and its sub-components, `api/verification.ts`, `hooks/verification.ts` | — | `BackgroundCheckPanel.tsx`, the barrels, Dev2/Dev3 pages |

---

## 5. Responsibilities

### 5.1 Verification-result integrity — superseding reviews (L4-04 review half, 0015's "superseding reviews on verification results")

The existing one-review-only rule is replaced by immutable, superseding reviews. The database's
"reviews can never be changed" guarantee is kept by **adding** records, never editing them.

- **Review record:** a new append-only table (`prevent_mutation()` trigger,
  `AppendOnlyRepository`):

  | Field | Rule |
  |---|---|
  | `id` | uuid4 |
  | `verification_result_id` | FK → `verification_result.id`, `ON DELETE RESTRICT` |
  | `review_status` | existing `VerificationReviewStatus` (`ACCEPTED`, `REJECTED`, `ESCALATED`) |
  | `reviewed_by` | `str(user.id)` from the session; never a body field |
  | `reviewed_at` | server time |
  | `note` | the reviewer's reason; required on a superseding review |
  | `supersedes_review_id` | self-FK; **unique**, so reviews form one chain per result and a race cannot fork it; `NULL` only on the first review |

- **Latest-review semantics:** the chain head (the review nobody supersedes) is the result's
  current review. Deterministic; exposed through the §6 reader as `latest_review_*`.
- **Old reviews immutable:** direct-SQL tests prove `UPDATE`/`DELETE` refused. The existing
  frozen columns `verification_result.reviewed_by`/`review_status` and their trigger are **kept**
  (never drop protection). The migration copies any existing reviewed row into the new table as
  its first review, so there is one source of "latest"; new reviews are written only to the new
  table. Stop writing the old columns, and say so in the entity docstring.
- **API:** `POST /verifications/{id}/review` accepts `review_status`, `note` and
  `supersedes_review_id`. First review: `supersedes_review_id` absent. Later review: must name
  the current chain head, else 409 (stale, like a compare-and-set) — never a silent overwrite.
  `PENDING` results remain unreviewable (422, existing rule). Responses carry the review chain.
- **Authorisation:** COMPLIANCE, ADMIN (unchanged). The reviewer is always the caller.
- **History:** each review writes a `verification` history row (history contract §2) —
  `from_value` the previous review status (or `None`), `to_value` the new one, `reason` the note,
  `details` with `verification_result_id`, `review_id`, `supersedes_review_id`,
  `verification_type`. Company id: the subject company for `EXPORTER`; for `BUYER`, the deal's
  company with `deal_id` set (§5.7). Subjects with no company link: **D15**.
- `test_exp2_verification_service.py::test_record_review_rejects_a_second_review_with_conflicting_outcome`
  encodes the rule being replaced; rewrite it to the new rule (it is Dev4's own test).

### 5.2 Polling safety (L4-02)

Invariant: **a reviewed result is never silently mutated by a later provider update.**

- `get_verification_status` must not change `status`, `risk_level`, `normalized_result` or
  `valid_until` once the result has any review. It logs the ignored update (with the provider's
  new values) instead. (Recording the provider's later answer as a new row is allowed only if it
  does not reuse or edit the reviewed row.)
- Defence in depth: a DB trigger refusing `UPDATE` of those four columns on a result that has a
  review (reusing the existing `onboarding.prevent_field_mutation_when_set()` pattern where it
  fits, or a new trigger function if not).
- Tests: service test (L4-02's "done when": a reviewed result is unchanged by polling) and a
  direct-SQL test of the trigger. Polling has no production caller today; do not add a scheduler.

### 5.3 Manual verification evidence (L4-07)

- A manual result whose status is `PASSED` **requires evidence**. The shape mirrors the
  qualification evidence the CRM already uses (`criterion-result.md`): a note and/or references
  `{type, ref}` with `type` in `document` (a `crm_document.id`), `url`. Stored in new evidence
  field(s) on `verification_result` (Dev4B's migration); `evidence_reference` is either retired or
  filled consistently — say which in the docstring.
- `document` references are validated: the document exists and belongs to the same subject
  (the company for `EXPORTER`; the buyer's deal or its company for `BUYER`). Read through Dev3B's
  `CrmDocumentRepository` — **no parallel evidence store**.
- The **minimum** (note alone? at least one reference?) is **D16**; whether `FAILED` also needs
  evidence is part of D16. Build the check in one place so the answer is one edit.
- `entity_reference` for `EXPORTER` must be an existing company (404/422) — closes the audit's
  ghost-subject finding, and is required anyway to write a history row (FK).
- Callers affected: Dev1's `test_route_authorization.py::_trigger_body()` records `PASSED` with
  no evidence against a random uuid, and the FIX 3 / FIX 4 tests use it. Dev4B updates them
  inside the controlled region (§9), with Dev1 review. Update Dev4's own tests likewise
  (`test_exp2_*`, `test_manual_entry_adapter.py`, `test_exp3_stub_rxil_adapter.py`).

### 5.4 Provider provenance

- Provider fidelity stays: whatever the adapter reports is stored verbatim, never rewritten.
- Honest labels: `manual` is a person; `rxil` is a **stub** until the RXIL contract exists — the
  stored row and the UI must say so. The stub reports `"RXIL"` upper-case while decision D4 of the
  earlier plan says providers are stored lower-case and displayed upper-case; aligning it is
  Dev4B's, with a test that the stored value never changes after write.
- **Open — D7:** today `POST /verifications` lets any COMPLIANCE user choose `provider="rxil"`,
  i.e. record a result *as RXIL's*. Dev2 closed the same gap on RXIL company intake by making it
  ADMIN-only. Options: restrict `rxil` on the manual route (ADMIN only, or refused there
  entirely, reserving it for the future intake path), or keep it with a recorded justification.
  **Do not choose silently**; until decided, leave the behaviour unchanged and document it.
- Middesk, Trulioo and Sumsub stay unreachable (A13); do not widen `VerificationProvider`.

### 5.5 Screening checklist (L4-09)

- **One catalogue on the server:** `VALID_ITEM_KEYS` becomes an ordered catalogue (key, label,
  section) owned by the screening service and **served** to the frontend (e.g. in the list
  response). `VerificationSection.tsx` stops hand-copying it. No second backend copy.
- Server validation: unknown key 422 (exists); status restricted to the four values in the API
  **and** a DB `CHECK` (Dev4B's migration); company must exist (404, not a DB error).
- ORM: declare the existing FK on `ScreeningReviewItem.customer_id` (no migration — the DB
  already has it; `dev2-remaining-work.md` §5).
- Latest-row semantics unchanged (`DISTINCT ON`, `created_at DESC, id DESC`).
- Served capabilities: responses say whether the caller may record a decision, so the UI keeps no
  role list.
- Authorisation unchanged: read OPERATIONS/COMPLIANCE/ADMIN; write COMPLIANCE/ADMIN; DEVELOPER per
  D8 (default: no widening).
- Screening is **not** a gauge and **not** qualification.

### 5.6 Screening history

- `GET /exporters/{company_id}/screening-review/{item_key}/history` (or equivalent) routed to the
  existing `list_item_history`, newest first, paged. The append-only table **is** the full history
  the architecture requires; it needs no second store.
- Whether each screening decision *also* writes a row into Dev1's shared history log is **D9**:
  no dimension is reserved for screening in `history-row.md` §2, and adding one (or filing it
  under `verification`) is a change to Dev1's contract. **Do not write shared-history rows for
  screening until D9 is answered.**
- Writers take a `FOR SHARE` lock on the company row before inserting (§6.2 invariant 6).

### 5.7 Buyer verification (L4-11, decision 9)

- A check with `entity_type = BUYER` must name an existing `deal_buyer.id` (validated through
  Dev3B's `DealBuyerRepository`; 404/422 otherwise). Never the company id, never the deal id.
- **Subject snapshot:** at record time, copy the buyer's identity (name, country, registration
  number, tax id) onto the result (Dev4B's migration adds the field), because
  `DealService.set_buyer` can replace every buyer field **in place under the same id**. Later buyer
  edits cannot change what an old check was about. Tax id and registration number in the snapshot
  are masked for OPERATIONS/DEVELOPER through `api/schemas/masking.py`, matching the deal buyer's
  own masking (8d8606c).
- History: a `verification` row on the deal's company **with `deal_id` set**, so it appears in the
  deal's story. It never touches `background_check`.
- Reads: `ComplianceInputsReader.buyer_checks(deal_buyer_id)` and the existing
  `GET /verifications?entity_type=BUYER&entity_reference=…`.
- A test proves a failed buyer check leaves the company record and its background check unchanged.
- Recording checks on a buyer of a `HANDED_OVER`/`WITHDRAWN` deal: **D17**.
- A `BuyerChecks` component is Dev4B's; **mounting it on the deal page is Dev3's** (post-merge).

### 5.8 Verification routes and security

Audit and declare, with rows in both route-auth tables and a refusal per role:

| Route | Roles today | Dev4B action |
|---|---|---|
| `POST /verifications` | COMPLIANCE, ADMIN | keep; evidence rule; subject validation; D7 |
| `GET /verifications`, `GET /verifications/{id}` | OPERATIONS, COMPLIANCE, ADMIN | keep; masking of sensitive `normalized_result` per **D8** |
| `POST /verifications/{id}/review` | COMPLIANCE, ADMIN | superseding review (§5.1) |
| `GET /exporters/{id}/screening-review` (+ history) | OPERATIONS, COMPLIANCE, ADMIN | catalogue, capabilities, 404 |
| `PUT /exporters/{id}/screening-review/{key}` | COMPLIANCE, ADMIN | status CHECK, 404, company share-lock |
| `GET /exporters/{id}/bank-activity` | OPERATIONS, COMPLIANCE, ADMIN | honest "not connected" (§5.9) |

- `raw_result` stays out of every response.
- DEVELOPER is refused on all of these today; any change is **D8**, not an assumption.
- Actors always from the session; no caller-chosen actor, reviewer, source or decided-by field.

### 5.9 Honest placeholders (L4-07, E18, E19, §7.6 gate)

- **Retire** the dev-only "Create placeholder records (dev)" generator in `VerificationSection.tsx`.
- Existing placeholder rows (`normalized_result.stub = true`, no provider reference) are
  **flagged**, not deleted: the reader reports `is_placeholder = True`; the UI labels them. Whether
  they count as "pending" for `CLEAR` is Dev4A's D2.
- No route creates a `PENDING` result that nothing can ever resolve: a manual result is recorded
  with its real outcome; the only `PENDING` a manual entry may produce is one D16/D2 explicitly
  allows.
- Bank activity: the response states that no provider feed is connected (an explicit field or
  label), instead of a bare `connected_accounts: 0`. **No fake findings.**

### 5.10 Verification frontend (L4-13 verification half, E42)

`components/VerificationSection.tsx` (split into Dev4B's own sub-component files as needed):

- manual result form (type, subject, outcome, evidence note/references picked from the company's
  documents), refusing `PASSED` without evidence client-side and server-side;
- result list with provider/source labels (stub and placeholder visibly labelled), review chain,
  superseding-review dialog;
- screening checklist driven by the **server's catalogue**, with per-item history;
- honest bank panel;
- capabilities from the server, not `user.role` comparisons;
- the exported component and its props (`VerificationSection({ customerId })`) **stay stable** —
  Dev4A's panel renders it;
- **tests** (vitest) for each of the above, including loading, empty and error states.

---

## 6. 4A ↔ 4B Contract

This section is identical in `docs/dev4/4a-task.md`.

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

- `application/verification_service.py`, `application/screening_review_service.py`
- `domain/entities/verification_result.py`, `domain/entities/screening_review.py` (incl. the ORM FK)
- `domain/entities/orchestration_enums.py` — the `Verification*` enums only; the legacy
  `Onboarding*` enums in the same file are **not touched**
- `domain/workflow_dependencies.py` — the EXP-2 `VerificationAdapter` section only; the nine
  legacy workflow protocols are not touched
- `infrastructure/adapters/manual_entry_adapter.py`, `infrastructure/adapters/stub_rxil_adapter.py`,
  `infrastructure/adapters/__init__.py`
- `infrastructure/repositories/verification_repository.py`
- `api/screening_router.py`, `api/schemas/screening.py`, `api/schemas/verification.py`
- the EXP-2 verification block of `api/router.py` (§9)
- Dev4's own tests: `test_exp2_verification_service.py`, `test_exp2_verification_schema.py`,
  `test_exp3_stub_rxil_adapter.py`, `test_e9_screening_review_service.py`,
  `tests/unit/test_manual_entry_adapter.py`, `test_verification_type_pairs.py`,
  `test_verification_service_no_branching.py`, `test_verification_workflow_dependencies.py`
- `frontend/src/modules/onboarding/components/VerificationSection.tsx`,
  `frontend/src/modules/onboarding/api/verification.ts`,
  `frontend/src/modules/onboarding/hooks/verification.ts`

**Add:**

- `domain/compliance_inputs.py`, `application/compliance_inputs.py` (seam, §6)
- `application/company_input_lock.py` (the §6.2 invariant 6 writer lock; 4B-0)
- `domain/entities/verification_review.py`, `infrastructure/repositories/verification_review_repository.py`
- `migrations/onboarding_0021_verif_review.py` (§10)
- `tests/integration/test_l4b_*.py`, `tests/unit/test_l4b_*.py`
- Dev4B sub-components beside `VerificationSection.tsx`, imported by it directly (e.g.
  `ManualResultForm.tsx`, `ReviewDialog.tsx`, `ScreeningChecklist.tsx`, `BuyerChecks.tsx`) and
  their `*.test.tsx`. **Not** added to `components/index.ts` (Dev4A edits that barrel; Dev3's
  mount of `BuyerChecks` is post-merge).

---

## 8. Files Read-Only

- **Dev4A's files** (all of §7 of `4a-task.md`): `background_check_*`, `BackgroundCheckPanel.tsx`,
  the Dev4A components, `api/background-check.ts`, `hooks/background-check.ts`,
  `api/index.ts`, `hooks/index.ts`, `components/index.ts`, `exporter_profile.py`.
- Dev1: `history_service.py`, `history_router.py`, `exporter_lifecycle_history.py`,
  `api/schemas/masking.py`, `events/publisher.py`, `app/platform/*`, `conftest.py`,
  `tests/fixtures/companies.py`, `frontend/src/lib/api/client.ts`, `HistoryTimeline.tsx`
  (already labels `verification`).
- Dev2: qualification code, `exporter_profile_service.py`, `exporter_router.py`,
  `schemas/exporter.py`, `company_intake_service.py`, **`infrastructure/rxil/company_package.py`**
  (the shared RXIL parser — read only until D12).
- Dev3: `deal_service.py`, `deal_buyer.py`, `deal_buyer_repository.py`, `document_service.py`,
  `crm_document_repository.py` (read calls only), storage, Dev3 pages.

**Forbidden:** `app/modules/kyb` (including its adapters and its allow-list), `cases`, `customers`,
`compliance`; the legacy path (`onboarding_request*`, `onboarding_verifications`/`Verification`
entity, Sumsub webhook, `kyb_vendor_*`, `infrastructure/registry.py` `ProviderRegistry` and
`mock_provider.py`, `screening_result_service.py`, `risk_rating_*`, `domain/policies/*`,
`workflows/`, `case_service.py`); other developers' migrations; the three stale branches.

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

**Dev4B's migration contains only:** the verification-review table with its `prevent_mutation()`
trigger, unique supersedes pointer and FK to `verification_result`; the copy of existing
`reviewed_by`/`review_status` into it; the trigger that freezes a reviewed result's outcome fields
(§5.2); evidence and subject-snapshot fields on `verification_result` (§5.3, §5.7); the
`screening_review_item.status` `CHECK` (§5.5); verification-specific indexes. Nothing about the
background-check gauge, decisions or risk. The existing
`trg_verification_result_field_immutability` and `trg_screening_review_item_append_only` are
**kept**. One file, grown across Dev4B's phases before the PR (it is unmerged until then).

**Rules** (`migration-register.md` §2):

- One chain, one head. Both branches start from the same head, so **the PR that merges second
  re-parents its own `down_revision` to the first PR's revision id** (a one-line change),
  then proves `alembic heads` prints exactly one revision and a clean
  `upgrade head → downgrade -1 → upgrade head` round trip. Never add a merge revision; never
  renumber the file.
- If `main` gains another migration before either merges, re-parent onto it the same way.
- No `ALTER TYPE … ADD VALUE` in an autocommit block; revision ids ≤ 32 characters.
- The downgrade is written; if lossy (dropping reviews recorded after the upgrade), it says so.
- Every new constraint and trigger gets a direct-SQL violation test.
- Dev4B does **not** edit `docs/contracts/migration-register.md`; it tells Dev1 the row to add.

---

## 11. API / Schema Ownership

| Artifact | Owner |
|---|---|
| `/verifications*` routes, `api/schemas/verification.py` | Dev4B |
| `/exporters/{id}/screening-review*`, `/exporters/{id}/bank-activity`, `api/schemas/screening.py` | Dev4B |
| Their paths in `openapi.json` / `schema.ts` | Dev4B regenerates on its branch; Dev1 reviews |
| `/exporters/{id}/background-check*` | Dev4A — Dev4B never changes them |
| Deal routes and schemas (where buyer checks would be shown) | Dev3 |

Schema names that the frontend keys on (`VerificationResultResponse`, `ScreeningReviewItemResponse`,
…) are changed additively where possible; a rename is a coordinated frontend change in the same
PR.

---

## 12. Dependency Classification

| Item | Class | Why | Owner of the dependency | What clears it | Blocks |
|---|---|---|---|---|---|
| 4B-0 seam PR (anchors + §6 contract + read-only reader) | **COMPLETE (28 Sep 2026)**, see §14 4B-0 status | first thing on `main` | Dev4B (reviewed by 4A, Dev1) | — | nothing further; the merge to `main` is the remaining step |
| Superseding reviews | CONTRACT-DEPENDENT | route-auth anchors and exception block | Dev4B (seam) | seam merged | implementation |
| Verification history rows (EXPORTER, BUYER) | PARALLEL | `verification` dimension already reserved | — | — | — |
| Verification history for unlinked subjects | DECISION-BLOCKED | D15 | lead + Dev1 | decision | that case only |
| Polling safety | PARALLEL | — | — | — | — |
| Manual evidence mechanism | PARALLEL | reads Dev3B's documents | — | — | — |
| Manual evidence minimum | DECISION-BLOCKED | D16 | lead / compliance | written rule | final merge (rule text) |
| `_trigger_body` / FIX 3–4 updates | CONTRACT-DEPENDENT | Dev1's file | Dev1 review | seam + review | final merge |
| Provider provenance for `rxil` on the manual route | DECISION-BLOCKED | D7 | lead | decision | that change only; behaviour unchanged until then |
| Screening catalogue, CHECK, 404, ORM FK, history route | PARALLEL | — | — | — | — |
| Screening in the shared history log | DECISION-BLOCKED | D9; Dev1 contract | Dev1 + lead | contract amendment | those rows only |
| Buyer checks (validation, snapshot, reads) | PARALLEL | Dev3B's `deal_buyer` exists on `main` | — | — | — |
| Buyer checks on terminal deals | DECISION-BLOCKED | D17 | lead + Dev3 | decision | that rule only |
| Buyer checks shown on the deal page | DEV3-DEPENDENT, POST-MERGE | Dev3's page | Dev3 | Dev3 mounts `BuyerChecks` | final demo |
| Masking of `normalized_result`; DEVELOPER access | DECISION-BLOCKED | D8 | lead + Dev1 | decision | route roles/masking; default: no widening |
| Honest placeholders (backend + frontend) | PARALLEL | — | — | — | — |
| Verification frontend + tests | PARALLEL (after backend phases) | — | — | — | — |
| RXIL results intake (L4-10) | DECISION-BLOCKED — **RXIL PACKAGE CONTRACT REQUIRED** | no results section in the provisional package; parser is Dev2's | RXIL, lead, Dev2 | published package contract | full intake |
| Reader returning real review chains to Dev4A | POST-MERGE (behaviour); CONTRACT-DEPENDENT (shape) | shape fixed in seam | Dev4B | 4B PR merged | Dev4A integration tests only |

---

## 13. Decisions Required Before Implementation

Numbering is shared with `4a-task.md`. Only the ones that affect Dev4B are listed.

| # | Decision | Status on `main` | Blocks for Dev4B |
|---|---|---|---|
| D2 | **Meaning of "pending"** — decided for Dev4A's CLEAR rule, but Dev4B must expose enough facts (status, review, placeholder flag, subject type) | **Settled 28 Sep 2026** (programme lead; clarified in the Dev4A PR review): `PENDING`, `REVIEW` and placeholders block `CLEAR`, except that a `REVIEW` result whose `latest_review_status` is `ACCEPTED` or `REJECTED` no longer blocks (`background-check.md` §14.1) | nothing in 4B if the §6 facts are complete; a new fact is a contract change. **4B-2 must keep `latest_review_status` = the status of the latest (superseding) review**, since Dev4A's rule now reads it |
| D4 | **Evidence snapshot scope** — which documents may be evidence for a verification result (company only? the buyer's deal?) | Unsettled | integration (document validation rule) |
| D7 | **Manual-route provenance for RXIL** — may COMPLIANCE record `provider="rxil"` through `POST /verifications`? | Open (audit finding) | implementation of that restriction; final merge |
| D8 | **DEVELOPER visibility and masking of sensitive compliance data** — DEVELOPER on verification/screening reads? mask `normalized_result`/comments for OPERATIONS? | Unsettled | route roles, masking, UI; default: no widening |
| D9 | **Screening and the shared history log** — mirror screening decisions into `exporter_lifecycle_history`? under which dimension? | No dimension in `history-row.md` §2 | those history rows only; the history **route** is not blocked |
| D12 | **RXIL package / results contract** | Undecided (architecture §11) | full RXIL results intake |
| D15 | **Verification history for subjects with no company link** (DIRECTOR, INVOICE, VESSEL, SHIPMENT) — history rows need a company id | Unsettled | those rows only |
| D16 | **Minimum evidence** for a manual `PASSED` (note alone, or at least one reference?) and whether `FAILED` needs evidence | A3/L4-07 say "evidence required" only | final merge (rule text) |
| D17 | **Buyer checks after a deal is `HANDED_OVER`/`WITHDRAWN`** — allowed, refused? | Unsettled | that rule only |

### Dev4B decisions recorded (28 Sep 2026, decided by the lead)

| # | Answer | Where it is implemented |
|---|---|---|
| D7 | `POST /verifications` accepts `provider="manual"` only; `"rxil"` is refused there (422) and reserved for the future RXIL intake path | `api/schemas/verification.py` (`ManualRouteProvider`) |
| D8 | No change: DEVELOPER stays refused on verification/screening routes; `normalized_result` is not masked | unchanged roles |
| D9 | Screening decisions are also written to the shared history log under a new `screening` dimension (`screening_initial` / `screening_transition`) | `screening_review_service.upsert_review_item`. **Dev1 must add the `screening` row to `history-row.md` §2** |
| D15 | Checks on DIRECTOR / INVOICE / VESSEL / SHIPMENT write no history row (skipped and logged) | `verification_service._record_history` |
| D16 | A manual `PASSED` needs a non-blank note **or** at least one reference; `FAILED` / `REVIEW` need none | `domain/verification_evidence.check_manual_outcome` |
| D17 | A new buyer check on a `HANDED_OVER` or `WITHDRAWN` deal is refused — 409 `DEAL_CLOSED`; existing checks stay readable and reviewable | `verification_service._resolve_subject` |

Also confirmed: reviewing a `PENDING` result is 422 (`VERIFICATION_RESULT_NOT_REVIEWABLE`); the RXIL
stub stores provider `rxil_stub` and refuses `PENDING`.

Decisions D1, D3, D5, D6, D10, D11, D13 and D14 are Dev4A's (`4a-task.md` §13). D13 is settled
(28 Sep 2026): Dev4A creates its own risk enum type (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`) in
`onboarding_0015_bg_check` and does not reuse `verification_risk_level_enum`. Nothing in Dev4B's
migration or enum changes because of it, and neither migration depends on the other's schema. D5
stays open. Record every answer, with its date and who decided, in the verification/screening
section of the Dev4 contract docs.

---

## 14. Implementation Phases

Each phase ends with the suite at baseline, ruff/import-linter unchanged, and the OpenAPI
artifact current where routes changed. A phase that cannot meet its stop condition stops and
reports.

### 4B-0 — Dev4 seam PR (lands on `main` first)
- **Objective:** make parallel work conflict-free and publish the §6 contract.
- **Scope:** anchor blocks for 4A and 4B in every §9 file (comments only, plus empty
  `__all__ += []` where that is the pattern); `domain/compliance_inputs.py`;
  `application/compliance_inputs.py` implementing the Protocol over **today's** tables (latest
  screening row per key; EXPORTER results; the frozen review columns as the latest review;
  `is_placeholder` from `normalized_result.stub`; `evidence_document_ids` empty until 4B-4).
- **Prerequisites:** Dev4A agrees §6 in writing.
- **Outputs:** a small PR; no behaviour change; `openapi.json` byte-identical.
- **Tests:** reader integration tests (empty company; mixed statuses; buyer isolation; ordering;
  unknown company/buyer errors; reader writes nothing and takes no lock).
- **Stop when:** merged to `main` with Dev4A's and Dev1's review.

> **4B-0 STATUS: COMPLETE (28 Sep 2026).** Dev4B Phase 4B-0 is complete. The Dev4A seam
> dependency is cleared, subject to Dev4A consuming the frozen interface exactly as documented.
>
> - **Seam implemented:** `domain/compliance_inputs.py` (the four §6.1 types, field for field)
>   and `application/compliance_inputs.py` (`ComplianceInputsService`, exported from the 4B
>   block of `application/__init__.py`).
> - **Output contract frozen** (§6.2 invariant 7).
>   `tests/unit/test_l4b_compliance_inputs_contract.py` pins every field name, order and
>   annotation; changing one needs the §6.4 agreement first.
> - **Anchor blocks created** in all eight §9 files: `exceptions.py`,
>   `domain/entities/__init__.py`, `infrastructure/repositories/__init__.py`,
>   `application/__init__.py`, `api/router.py` (4A block only; 4B mounts nothing new),
>   `tests/contract/test_route_authorization_coverage.py`,
>   `tests/integration/test_route_authorization.py`, `frontend/src/modules/onboarding/types.ts`.
> - **Tests passing:** 13 contract unit tests and 25 reader and lock integration tests
>   (`test_l4b_compliance_inputs.py`); full suite at the §3 baseline; ruff 16; import-linter
>   19/0; one Alembic head (`onboarding_0019_documents`); no migration; `openapi.json`
>   untouched.
> - **Dev4A dependency: CLEARED.** Dev4A may build 4A-2 on this seam. The seam lives on branch
>   `feature/4b-decision-engine-and-integration` until it is merged; per §16 step 1, Dev4A cuts
>   or rebases its branch from `main` after that merge. Dev4A's and Dev1's review remain the
>   merge step.
>
> What 4B-0 delivered, and where it differs from the scope line above (recorded, not silent):
>
> 1. **`FOR SHARE` company lock on writers, brought forward** at the lead's instruction
>    (§6.2 invariant 6). `application/company_input_lock.py::share_lock_companies` (new,
>    Dev4B) is taken by `ScreeningReviewService.upsert_review_item` and, for `EXPORTER`
>    subjects only, by `VerificationService.trigger_verification`,
>    `trigger_verification_batch`, `get_verification_status` (when it changes a row) and
>    `record_review`, after any provider call and before the write. 4B-1's "`FOR SHARE`
>    company lock on writes" is therefore already done. This is a concurrency change only: no
>    route, status code, response or OpenAPI change.
> 2. **Ordered screening catalogue.** `screening_review_service.SCREENING_CATALOGUE` (the eight
>    keys in `VerificationSection.tsx`'s display order) is now the one backend list;
>    `VALID_ITEM_KEYS` is derived from it. Labels, sections and serving the catalogue remain
>    4B-1.
> 3. **Latest review, today.** `latest_review_status` is the frozen `review_status` column.
>    `latest_review_id` and `latest_reviewed_at` are `None` even on a reviewed result, because
>    today's storage records neither; 4B-2's review table fills both. Consumers must not read
>    `latest_review_id is None` as "never reviewed"; `latest_review_status` says that.
> 4. **Placeholders.** `is_placeholder` is `normalized_result.stub is True` **and** no
>    `provider_reference`, the same rule `VerificationSection.tsx` labels. Reported, not
>    filtered (D2 is Dev4A's).
> 5. **Unknown buyer** raises `ComplianceInputsBuyerNotFoundError` (404,
>    `DEAL_BUYER_NOT_FOUND`), in the 4B block of `exceptions.py`.
> 6. **Read-only, proved.** Queries run under `no_autoflush` and select columns rather than
>    entities, so the caller's pending work and identity map are untouched; tests prove no
>    flush, no commit and no row lock (another connection can `FOR UPDATE NOWAIT` every row
>    read).
> 7. **Not in 4B-0:** Dev4B phases 4B-1 onward (serving the catalogue, superseding reviews,
>    polling safety, evidence, buyer validation, frontend) are **not started**.

### 4B-1 — Screening integrity
- **Objective:** §5.5 and §5.6.
- **Scope:** served catalogue; status `CHECK` (migration); 404 for unknown company; ORM FK;
  history route; served capabilities. (The `FOR SHARE` company lock on writes landed in
  4B-0.)
- **Prerequisites:** 4B-0. **Other branch:** none.
- **Tests:** unknown key/status refused (API and direct SQL); history newest first; latest-row
  unchanged; 404; route-auth rows for the new route; OpenAPI current.
- **Stop when:** the frontend could render the checklist from the server alone.

### 4B-2 — Superseding verification reviews
- **Objective:** §5.1.
- **Scope:** review table + copy of existing reviews (migration); service; route; `verification`
  history rows (EXPORTER now; BUYER in 4B-5); reader switched to the chain head.
- **Prerequisites:** 4B-0.
- **Tests:** first review; superseding review; stale supersede → 409; concurrent reviews cannot
  fork (unique pointer); direct-SQL immutability; old frozen columns untouched; rewrite the
  one-review test; reader output unchanged in shape.
- **Stop when:** a reviewer can change a verdict only by adding a record.

### 4B-3 — Polling safety
- **Objective:** §5.2.
- **Scope:** service guard + DB trigger.
- **Tests:** L4-02's test; direct-SQL trigger test; an unreviewed row still updates.
- **Stop when:** no path can change a reviewed result's outcome fields.

### 4B-4 — Manual evidence and subject validation
- **Objective:** §5.3.
- **Scope:** evidence fields (migration); PASSED-needs-evidence in one function; document refs
  validated through Dev3B's repository; EXPORTER subject must exist; `FOR SHARE` company lock;
  reader fills `evidence_document_ids`; update Dev4's tests and, in the controlled region, Dev1's
  `_trigger_body` / FIX 3 / FIX 4 (Dev1 review).
- **Prerequisites:** 4B-0; D16 for the exact minimum (build with A3's wording until then, marked
  `DECISION PENDING`).
- **Tests:** PASSED without evidence 422; with a note / a valid document / a foreign document
  (refused); ghost subject refused; route-auth tables green.
- **Stop when:** no manual PASSED can be stored without evidence.

### 4B-5 — Buyer verification
- **Objective:** §5.7.
- **Scope:** BUYER subject validation; subject snapshot (migration field); masked reads; history
  row with `deal_id`; `buyer_checks` in the reader; `BuyerChecks` component (not mounted).
- **Prerequisites:** 4B-2 (history), 4B-4 (validation path).
- **Tests:** buyer check against a company id or deal id refused; snapshot survives a
  `set_buyer` rename; failed buyer check leaves `exporter_profile` untouched; masking per role.
- **Stop when:** buyer checks are recorded and read with no company effect.

### 4B-6 — Honest placeholders and provenance
- **Objective:** §5.9 and the non-gated part of §5.4.
- **Scope:** bank "not connected" in the response; placeholder rows flagged; RXIL stub label and
  casing; D7 applied **only if decided**.
- **Tests:** bank response says not connected with no findings; no route creates a
  pending-forever row; stored provider never rewritten.
- **Stop when:** §7.6's Dev4 gate items are true for the verification side.

### 4B-7 — Verification frontend and tests
- **Objective:** §5.10.
- **Files:** `VerificationSection.tsx` and Dev4B's sub-components, `api/verification.ts`,
  `hooks/verification.ts`, the 4B block of `types.ts`, regenerated `schema.ts`.
- **Prerequisites:** 4B-1 … 4B-6.
- **Tests:** vitest for manual form (evidence required), review chain + supersede dialog,
  checklist from the server catalogue + item history, placeholder/stub labels, bank panel, served
  capabilities, loading/empty/error; `VerificationSection({ customerId })` export unchanged.
- **Stop when:** tsc, eslint, vitest, build pass and no `user.role` comparison remains in Dev4B's
  files.

### 4B-8 — RXIL results intake — **BLOCKED — RXIL PACKAGE CONTRACT REQUIRED**
- Not started until D12 is published. Allowed now, only if it pretends nothing about the format:
  keep `StubRxilAdapter` and `trigger_verification_batch` as they are, labelled stub. The
  automatic `NOT_STARTED → IN_REVIEW` move on arrival is Dev4A's and also blocked.

---

## 15. Testing Plan

**Independently on the 4B branch:**

- Unit: adapters (manual evidence rule, stub casing), type-pair table, no-branching scan,
  evidence rule function, catalogue.
- Service (real DB): reviews and supersession, polling guard, subject validation, buyer snapshot,
  screening history, company `FOR SHARE` lock serialising with a `FOR UPDATE` holder.
- Repository / database: direct-SQL immutability of reviews; outcome-freeze trigger; screening
  status `CHECK`; unique supersedes; FKs.
- Authorization: both route-auth tables (existing verification/screening rows and the 4B block);
  refusal per role; DEVELOPER per D8.
- API: request/response shapes; 404/409/422; reviewer/actor/source never accepted from a body.
- Contract: the §6 reader against real rows (its tests live with it and must keep passing).
- Regression: `test_exp2_*`, `test_exp3_*`, `test_e9_*`, `test_route_authorization*`,
  `test_l3b_deal_buyer.py`, `test_l3b_documents.py`.
- Frontend: vitest for every §5.10 item; `npx tsc -b --noEmit`; `npx eslint .`;
  `npx vite build`.
- Gates: `alembic heads` (one), round trip, full `pytest -q --no-cov -p no:cacheprovider`,
  `ruff check .`, `lint-imports --config importlinter.ini`, `test_openapi_artifact_is_current`.

**Needs Dev4A's merged PR:** none for Dev4B's own behaviour. Dev4A's CLEAR consuming real review
chains and evidence ids is tested in §17.

**Final integration:** §17. Compare the full suite with the §3 baseline failure set; do not edit
unrelated failing tests.

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
4. **Contracts verified before each merge:** §6 output shape unchanged; the reader's own tests
   green; D7/D16 answered or their code paths left unchanged and labelled for Dev4B's merge.
5. **Independent test runs** per §15; **integration tests** per §17.
6. **No cherry-picking** between the branches during development. Dev4A codes against the seam
   reader; it never pulls Dev4B commits.

---

## 17. Post-Merge Integration

One controlled step after both PRs are on `main` (owner: Dev4A, reviewed by Dev4B):

- Integration tests: CLEAR end to end with real verification results, a superseding review, all
  eight screening items and pinned documents; a later upload/review does not change a past
  decision's snapshot; a buyer check never moves the company gauge.
- Optional: an FK from Dev4A's evidence snapshot to Dev4B's review table (Dev4A migration, only if
  both agree).
- Dev1: register rows for both migrations; types regenerated at the milestone; D9/D14/D15
  contract text.
- Dev3: mount `BuyerChecks` on the deal page (one import, one element).
- Dev2: sample data for the §3.9 companies (verification results and screening answers that let
  company B reach CLEAR and company C be FLAGGED) through a Dev4 sample hook called from
  `sample_data.py`.
- **Final Dev4 audit verifies:** one Alembic head and clean round trip; suite at baseline; no
  reviewed result can change (service and DB); every review is a record; manual PASSED needs
  evidence; screening keys exist in one backend place and the UI reads them from the server;
  screening history reachable; buyer checks attached to `deal_buyer.id` with a snapshot and no
  company effect; no placeholder generator, honest bank panel; provenance per D7; OpenAPI
  current; route-auth coverage complete; frontend tests present; RXIL intake still blocked and
  labelled.

---

## 18. DO NOT BUILD

- **No third verification framework.** Extend `verification_result`, its registry and adapters.
- **No new document system**; evidence references `crm_document` ids.
- No legacy `onboarding_request` workflow, no 18-state onboarding machine, no `workflows/`, no
  `onboarding_verifications`/Sumsub path, no `ProviderRegistry` work.
- **No case engine.** **No Middesk, Trulioo or Sumsub**; do not widen `VerificationProvider`; do
  not merge the stale adapter branches.
- No changes to `kyb`, `cases`, `customers` or `compliance` modules (including kyb's adapter
  allow-list); no new module-rule exception.
- **No deal lifecycle work**, no lending/transaction logic, no transaction performance tracking.
- No new customer or deal state machine; **screening is not a fourth gauge** and not qualification.
- No background-check decisions, gauge writes, risk ratings or `CLEAR` logic — Dev4A's.
- **No fake provider results, no fake bank findings**, no placeholder generator.
- **No speculative RXIL package parsing**; no edits to Dev2's RXIL parser.
- **No speculative U4 transaction solution.**
- **No universal allowed-moves framework**; serve capabilities for Dev4B's own actions only.
- No second backend copy of the screening keys; no role lists in the frontend.
- No edits to Dev4A's files, `history_service.py`, `masking.py`, or the history/event/migration
  contracts.

---

## 19. Definition of Done

- Seam PR merged; §6 contract stable; reader tests green.
- `onboarding_0021_verif_review` merged; one head; clean round trip; direct-SQL tests for every
  new constraint and trigger; existing immutability triggers intact.
- Reviews are superseding records; a stale supersede is refused; history rows written.
- Polling cannot alter a reviewed result (service test + DB trigger test).
- Manual `PASSED` requires evidence per D16; document evidence validated; ghost subjects refused.
- Provenance honest; D7 applied or explicitly left open with behaviour unchanged.
- Screening: one server catalogue, status `CHECK`, 404, ORM FK, history route, capabilities served.
- Buyer checks on `deal_buyer.id` with an identity snapshot, masked for OPERATIONS/DEVELOPER, and
  no effect on the company.
- Bank panel honest; placeholder generator gone; placeholder rows labelled.
- `VerificationSection` rebuilt with tests; no `user.role` checks in Dev4B files.
- Route-auth rows for every changed or new route; OpenAPI current.
- Suite at the §3 baseline; ruff 16; import-linter 19/0; tsc/eslint/vitest/build pass.
- RXIL results intake remains explicitly **BLOCKED** and is not stubbed beyond what exists.
