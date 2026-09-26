# Dev2 — what is left, and what others own next

**As of 26 September 2026**, after the PR audit of `refactor/crm-ownership-split`
(L2-01 to L2-14 except L2-11). This file is only what remains once that PR
merges. It is grouped by **who acts next**, because most of it is not Dev2's to
close: it is in another developer's files, or it is a decision.

Verification at the end of the audit (with every fix below applied): see §6.

---

## 1. Fixed during the audit (for the record, nothing to do)

So a reader does not re-raise them:

| Finding | Fix |
|---|---|
| A company that arrived with GSTINs only (no PAN) was never found again: a repeated RXIL delivery or CSV re-import was refused as a possible duplicate, and an interrupted RXIL intake could not be finished | `CompanyMatcher` matches it to the one PAN-less company holding every incoming GSTIN (`company-record.md` §4 table) |
| RXIL intake let any staff user record a decision *as RXIL's* (`source=RXIL`, `AUTOMATED`, confidence) — fields the manual qualification routes refuse | Route is **ADMIN only**, backend and frontend |
| Migration 0014 empties five CRM tables wherever it runs | Refuses when they hold rows unless `E9_ALLOW_CRM_RESET=1` |
| CSV import allowed 5,000 rows (~4 minutes in one request) | `MAX_ROWS = 1000` (~1 minute) |
| Two ADMINs versioning one criterion at once → 500 | 409 `QUALIFICATION_CRITERION_CHANGED` / `QUALIFICATION_CRITERION_EXISTS` |
| Concurrent marker moves or profile edits could record a stale `from` | Both lock the company row first, as qualification does |
| Company search paged unstably on equal `created_at`; `%`/`_` in a name search were wildcards; `?name=` (blank) brought ENDED companies back | Tiebreak on `customer_id`; LIKE escaped; blank name is no search |
| Manual create/edit accepted GSTINs carrying two different PANs when no PAN was given (import and RXIL refuse them) | Refused everywhere |
| Edit form: CIN (masked by the server) was prefilled with bullets for OPERATIONS; a non-numeric year silently cleared the year | CIN treated like PAN/GSTIN/IEC; a bad year goes to the server as typed and is refused |
| Stale 403 text ("creating at ONBOARDED…") and a leftover `assert` in the create route | Removed |

---

## 2. Programme lead — decisions

### 2.1 Masked roles can learn who holds a tax identifier — **needs a decision**

Search deliberately refuses `?pan=` / `?gstin=` / `?iec=` to OPERATIONS and
DEVELOPER, because an exact match says which company holds the identifier
(`exporter_router.py`, `_reject_identifier_search`). OPERATIONS can still get
the same answer three other ways, each repeatable at no cost because a refused
create writes nothing:

- `POST /exporters` with a PAN → 409 `DUPLICATE_PAN` carrying `existing_customer_id`;
- create or edit with a GSTIN → `gstin_warnings[].other_customer_ids`;
- CSV import → `candidates` on a conflicting / possible-duplicate row.

Refusing a duplicate PAN always reveals *that* it exists; the question is only
whether a masked role also learns *which* company. Options: keep as is (the
data-entry benefit of decision 4 wins), or omit the ids for roles that
`can_reveal_identifiers` says no to. Owner of the fix once decided: Dev1
(L1-10 masking) with Dev2 (the responses). Not in `company-record.md`'s open
items yet — add it as O8.

### 2.2 Still open from before

- **U4 / O3** — do Dev4's `CLEAR` and Dev2's move to `CUSTOMER` commit in one
  transaction? **Blocks L2-11.**
- **O2** — the ANER-4.2-S1T2 consumer watched for `ONBOARDED`. Journey rows
  keep `lifecycle_initial`/`lifecycle_transition` and the `terminal` flag, but
  **no row sets `terminal=true` until L2-11 lands**, so that consumer sees no
  completions in the meantime. Confirm `CUSTOMER` is the replacement.
- **RXIL service identity.** Intake is ADMIN-only because a person pastes the
  package. When RXIL delivers through its own integration it needs a machine
  identity — **not `API_USER`**, which public sign-up grants and which must
  reach nothing in the CRM (`test_api_user_reaches_nothing_in_the_crm`).
- **O1, O4, O6/U1** unchanged (see `company-record.md` §7).

---

## 3. Developer 1

1. **Migration register** (`docs/contracts/migration-register.md`): add the row
   for `onboarding_0020_retire_lifecycle` (L2-04 has no number of its own), and
   note on 0014 that it now needs `E9_ALLOW_CRM_RESET=1` on a database whose
   CRM tables hold rows.
2. **Stale docstrings in Dev1 files**, made stale by Dev2's migrations — text
   only, no behaviour:
   - `domain/entities/exporter_lifecycle_history.py` module docstring still says
     one row per move of `lifecycle_status`, "`customer_id` is a bare, indexed
     UUID with no formal FK" (0014 added `fk_exporter_lifecycle_history_customer_id`),
     and describes `transition_lifecycle_status` and `create_lead` creating an
     onboarding request — all gone. The index comment still says the hook
     watches `COMPLIANCE_REVIEW -> ONBOARDED`.
   - `application/history_service.py`, the `source` argument's example names
     `exporter_profile_service.transition_lifecycle_status`.
3. **ORM foreign key** on `ExporterLifecycleHistory.customer_id` to match 0014
   (see §4.1 for why it matters).
4. **Reviews still owed** from before: the additive `lib/api/client.ts` change
   (FormData bodies, text responses) and Dev2's edits to the history tests;
   acknowledge Q3, O5 and O7.

---

## 4. Developer 3

### 4.1 Declare the company links 0014 added — `exporter_contact.py`, `exporter_activity.py`

Migration 0014 gave `exporter_contact` and `exporter_activity` a real foreign
key to `exporter_profile.customer_id` (`ON DELETE RESTRICT`), but the ORM
models still declare `customer_id` as a bare column. Two consequences:

- `alembic revision --autogenerate` would propose **dropping** the constraints;
  there is no drift test to catch that.
- SQLAlchemy only orders inserts by foreign keys it knows about. Adding a new
  company and its first contact in one flush can insert the contact first and
  fail the constraint.

Fix: `mapped_column(UUID(as_uuid=True), ForeignKey("onboarding.exporter_profile.customer_id", ondelete="RESTRICT"), nullable=False)`,
as `ExporterGstin` and the qualification tables already do. No migration.

### 4.2 Review Dev2's edit to `ExporterActivityRepository.list_pending`

L2-03 moved its display-name join from the legacy `onboarding_request` table to
`exporter_profile.name`. Dev3's file; the change needs its owner's review.

### 4.3 Migrations

`0016` must set `down_revision` to the head at the time it merges (today
`onboarding_0020_retire_lifecycle`), keeping one head (register §2).

### 4.4 Tests and sample data

- Any test writing a contact or activity must now create the company first:
  `tests/fixtures/companies.py` (`make_company`, `insert_company`).
- `sample_data.py` carries each company's architecture §3.9 target in
  `SampleCompany.target`; conversation and deals are Dev3's to add as they land.
- `engagement_router.py` / `schemas/engagement.py` / `engagement_views.py` were
  split out for Dev3 in L2-01, moved without change; they are Dev3's now.

---

## 5. Developer 4

- **ORM foreign key** on `ScreeningReviewItem.customer_id`
  (`domain/entities/screening_review.py`) — same reason and fix as §4.1.
  `bank_activity_finding` has no company link in the database at all; decide
  whether it should.
- **`0015`** re-parents onto the head when it merges, as in §4.3.
- **L2-11 hand-off**: a `CLEAR` background check moves a `PROSPECT` to
  `CUSTOMER` and writes the journey row with `terminal=true`. Blocked on U4.
- RXIL's own check results (KYC, AML/CFT, …) are L4-10's; company intake
  deliberately does not read them.
- `screening_router.py` / `schemas/screening.py` were split out for Dev4 in
  L2-01, moved without change.

---

## 6. Developer 2 — still open

| Item | Status |
|---|---|
| **L2-11** — the move to `CUSTOMER` | Blocked: U4 (§2.2) and Dev4's `CLEAR` |
| **IEC format in the database** | The service checks IEC (10 letters or digits) but, unlike PAN/GSTIN/CIN, there is no `CHECK` constraint. Needs a migration number from the register |
| **Imports above 1,000 rows** | Only if the business needs them: a background job with a pollable report, not a longer request |
| **Unnamed create path** | `POST /exporters` without `name`/`country` still creates a company with no identity, which is why `name`/`country` stay nullable. Remove once nothing calls it, then make both `NOT NULL` |
| Identifier disclosure (§2.1) | Implement once decided |

**Verification with every fix applied** (26 Sep 2026): backend suite identical
to the baseline failure set (22 failed / 5 errors, all pre-existing
payments/compliance/audit tests on routes this checkout does not mount), one
Alembic head (`onboarding_0020_retire_lifecycle`), ruff 16 (baseline, none in
changed files), import-linter 19 kept / 0 broken, `openapi.json` and
`schema.ts` current. Frontend: `tsc` clean, 0 lint errors, 42 tests, build
passes.
