# The database — source of truth

**Scope:** every database fact the Exporter CRM depends on. What the schemas are, what
owns each table, what the database itself refuses, how a connection is made, and where
the traps are.

Verified on 5 October 2026 against the running database (PostgreSQL 16.14,
`alembic_version = onboarding_0043_identity_type`) and against `Base.metadata` as the
models declare it. `alembic check` reports **no drift** between the two, so where this
file states a column, a constraint, an index or a trigger, the models, the migrations
and the live database all agree.

Companion documents, not duplicated here:

- [`contracts/migration-register.md`](contracts/migration-register.md) — the running
  order of every migration, what each one changed, and the rules for writing the next.
  **That file is the authority on migrations;** §10 below only summarises.
- [`architecture.md`](architecture.md) — why the model is shaped this way.
- [`contracts/`](contracts/) — the per-area contracts (company record, history row,
  deal and buyer, background check, verification and screening, trade history,
  storage and documents, engagement, criterion and result).

---

## 1. The physical database

| | |
|---|---|
| Engine | PostgreSQL 16 (16.14 locally) |
| Database name | `aner_settlement` — one database, the whole platform. There is no separate CRM database and no separate test database. |
| Local container | `aner-postgres`, published on **`localhost:5433`** (the container listens on 5432) |
| Owner / app role | `aner` |
| Extensions | `plpgsql`, `btree_gist`. Nothing else. `gen_random_uuid()` is PostgreSQL 13+ built-in, not `pgcrypto`. |
| Connection (async) | `postgresql+asyncpg://…` — `DATABASE_URL` |
| Connection (sync) | `postgresql+psycopg2://…` — `DATABASE_SYNC_URL`, used by Alembic and by the direct-SQL constraint tests |

Both URLs must point at the same database. The migration commands read
`DATABASE_SYNC_URL`; the application and the test suite read `DATABASE_URL`.

> **The default in `config.py` says port 5432, the container publishes 5433.** A fresh
> checkout with no `backend/.env` connects to nothing. `backend/.env` is untracked and
> is where the real port lives.

### Login roles

| Role | Login | Purpose | Schemas it has `USAGE` on |
|---|---|---|---|
| `aner` | yes | The application. Owns every schema and every object. | all |
| `ledger_ro` | yes | The ledger query service | `ledger`, `settlement` |
| `settlement_ro` | yes | The settlement query service | `settlement` |
| `audit_ro` | yes | The audit query interface | `audit` |

**No read-only role can reach the `onboarding` schema.** Every CRM read and write goes
through the `aner` role on the writable session. The three `*_ro` roles exist for other
modules' query services; one role per module, never one role spanning several, so a
query service reading three schemas holds three connections rather than one credential
with a three-module blast radius.

Their passwords are **not** defaulted in `config.py`. `LEDGER_RO_DB_PASSWORD`,
`SETTLEMENT_RO_DB_PASSWORD` and `AUDIT_RO_DB_PASSWORD` must be set in the environment or
in `backend/.env`, or building the URL raises at first use with the setting named —
`alembic upgrade head` refuses to run without them. A checked-in default would be a
shared credential every environment silently ends up running with.

---

## 2. Schema map

Sixteen schemas. `public` holds no application table — only `public.prevent_mutation()`
and `alembic_version`.

| Schema | Owner module | The CRM's relationship to it |
|---|---|---|
| `onboarding` | `app/modules/onboarding` | **The CRM lives here.** 41 tables: the CRM's own (§4–§6) plus the legacy onboarding path (§7). |
| `auth` | `app/platform/authentication` + `authorization` | Read. Actor ids stored in CRM tables are `auth.users.id` as text; names are resolved through the auth facade when a row is read. RBAC lives in `auth.role` / `auth.role_permission`. |
| `audit` | `app/modules/audit` | Write, through the `AuditService` facade only. |
| `customers` | `app/modules/customers` | **Not touched.** See the warning in §3. |
| `compliance` | `app/modules/compliance` | Not touched for data. Role checks on two compliance read routes are the single recorded module-rule exception (EX-001). |
| `cases`, `fx`, `gateway`, `ledger`, `messaging`, `notifications`, `payments`, `rails`, `reconciliation`, `settlement` | their own modules | Schema only in this checkout. The CRM reads and writes none of them. |

Module boundaries are enforced in CI by `backend/importlinter.ini` (one
private-internals contract per module) and by
`tests/contract/test_module_independence.py` (a Tarjan SCC analysis that import-linter
cannot express). `onboarding` may import another module's public facade; **nothing may
import `onboarding`.**

`migrations/env.py` restricts autogenerate to the schemas listed in `MODULE_SCHEMAS`,
so an object in an unlisted schema is never proposed for deletion. A model missing from
that file's import block is absent from `Base.metadata` while its table still exists —
and autogenerate then proposes dropping it. Adding a table means adding its model
module to that import list.

---

## 3. The key rule — read this before writing any query

`onboarding.exporter_profile` has **two** uuid columns that look like a primary key:

| Column | What it is |
|---|---|
| `id` | The table's actual primary key (`AnerModel`, `uuid4`). **Almost nothing references it.** |
| `customer_id` | The **company id** — the business key, `UNIQUE`, and the target of every child foreign key. |

Every child table in the CRM points at `exporter_profile.customer_id`, never at
`exporter_profile.id`:

```
fk_crm_document_company_id      FOREIGN KEY (company_id)  REFERENCES onboarding.exporter_profile (customer_id)
fk_deal_company_id              FOREIGN KEY (company_id)  REFERENCES onboarding.exporter_profile (customer_id)
fk_exporter_gstin_customer_id   FOREIGN KEY (customer_id) REFERENCES onboarding.exporter_profile (customer_id)
… and so on for every table in §4–§6
```

A join written against `exporter_profile.id` returns nothing and raises no error. The
company id in every API path, every history row, every document and every deal is
`customer_id`.

> **`customer_id` is not a foreign key to anything.** It is generated by the CRM
> (`uuid4`, or `uuid5` for the fixed sample companies) and is deliberately **not** a
> reference into `customers.customers` or into `onboarding.onboarding_request`. A
> company has one `exporter_profile` for its whole life, across any number of
> historical `onboarding_request` rows. Becoming a `CUSTOMER` publishes a
> `company.became_customer` event; it does not write a `customers` row. The event bus
> is in memory and has no receiver in this checkout.

Two other near-misses worth knowing:

- `onboarding.onboarding_customers` and `customers.customers` are **unrelated tables**
  in different schemas. The first belongs to the legacy identity-provider path (§7).
- `exporter_profile` has no `gstin` column. A company's GSTINs are rows in
  `exporter_gstin`; only `pan` and `iec` sit on the profile.

### A foreign-key cycle exists, by design

`deal` → `exporter_profile` (seller and buyer), `deal` → `exporter_gstin` (composite),
`exporter_profile.created_via_deal_id` → `deal`. SQLAlchemy cannot topologically sort
these three tables and emits `SAWarning: Cannot correctly sort tables` on every Alembic
run. **That warning is expected and harmless.** It means Alembic will not consider
those FKs when ordering DDL; the migrations create the columns and the constraints in
separate statements, which is why it works.

---

## 4. The company record and its gauges

### `exporter_profile` — one row per company

The enduring company record. A company may exist before any onboarding journey starts
(a Lead typed in by Sales) and keeps one profile forever.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | see §3 — not the company id |
| `customer_id` | `uuid` | **the company id.** `UNIQUE` |
| `name` | `varchar(255)` | nullable |
| `country` | `varchar(2)` | nullable, ISO-2 |
| `cin` | `varchar(21)` | nullable |
| `pan` | `varchar(10)` | `UNIQUE` across companies |
| `iec` | `varchar(10)` | `CHECK iec ~ '^[A-Z0-9]{10}$'` (0040) |
| `identity_type` | `company_identity_type_enum` | `IN_PAN` \| `FOREIGN_REG`, derived from `pan` / `registration_number` |
| `registration_number` | `varchar(100)` | unique **per country, normalised** — see the index below |
| `source` | `exporter_source_enum` | **immutable once set** (trigger) |
| `relationship_manager`, `relationship_manager_user_id` | `varchar(255)`, `uuid` | |
| `journey` | `exporter_journey_enum` | `LEAD` → `PROSPECT` → `CUSTOMER`, forward only |
| `marker` | `exporter_marker_enum` | `NONE` \| `PAUSED` \| `ENDED`; `marker_reason` required when set |
| `qualification` | `qualification_state_enum` | current value of the qualification gauge |
| `conversation` | `exporter_conversation_enum` | current value of the conversation gauge |
| `conversation_check_back_on` | `date` | required exactly when `conversation = 'NOT_NOW'`, forbidden otherwise (`CHECK`) |
| `background_check` | `background_check_enum` | current value of the background-check gauge |
| `background_check_expires_at` | `timestamptz` | when the current `CLEAR` lapses (0023/0027), partial index |
| `pipeline_status` | `company_pipeline_status_enum` | `NOT_IN_PIPELINE` requires `journey = LEAD AND qualification = NOT_YET_REVIEWED AND conversation = NOT_CONTACTED` (`CHECK`) |
| `created_via`, `created_via_deal_id` | `varchar(64)`, `uuid` → `deal.id` | how the company entered |
| `industry`, `export_markets`, `products`, `year_established`, `website`, `date_added` | | descriptive |

**Each gauge's current value is carried here on purpose** (architecture §3.8) so lists
and filters need no join. Each is written by exactly one service, which writes the
history row in the same transaction:

| Gauge column | The only service that writes it |
|---|---|
| `journey`, `qualification`, `marker` | `ExporterProfileService` / `QualificationService` |
| `conversation`, `conversation_check_back_on` | `ConversationService` |
| `background_check`, `background_check_expires_at` | `BackgroundCheckService` |

The authoritative log of *how* a gauge got where it is lives in the append-only tables
(`qualification_outcome`, `background_check_decision`) and in
`exporter_lifecycle_history`. The profile column is the cached current value.

The registration-number uniqueness is a **normalised partial unique index**, not a
constraint:

```sql
CREATE UNIQUE INDEX uq_exporter_profile_country_registration_number
    ON onboarding.exporter_profile
       (country, upper(regexp_replace(registration_number, '[^A-Za-z0-9]', '', 'g')))
 WHERE registration_number IS NOT NULL AND country IS NOT NULL;
```

Punctuation and case do not make a registration number distinct. A query looking for a
duplicate must normalise the same way or it will miss one.

### `exporter_gstin` — a company's branches

Several per company; `UNIQUE (customer_id, gstin)`. Since 0035 each row is a **branch
record**: `state_code`, `state_name`, `status`, `address`, `flag_status`, `flag_reason`,
`active`, `deactivated_at/by`.

- **`DELETE` is refused by a trigger** (`trg_exporter_gstin_no_delete`), with a message
  saying to deactivate instead. A branch a company traded through is not removable.
- `CHECK`: a `FLAGGED` branch must have a reason; an inactive branch must have
  `deactivated_at`.
- `uq_exporter_gstin_id_customer_id` exists only to be referenced — it is what lets a
  deal's composite FK tie its branch to its seller.
- A GSTIN held by another company is a **warning in the UI, not a database refusal**
  (`ix_exporter_gstin_gstin` is non-unique, deliberately).

### `exporter_contact`

`uq_exporter_contact_primary_per_customer` is a **partial unique index** on
`(customer_id) WHERE is_primary_contact = true` — at most one primary contact per
company, enforced by the database.

### `exporter_lifecycle_history` — the one shared history log

Append-only. Every change to a company's journey, any gauge, its marker, its profile or
any of its deals writes exactly one row here, in the same transaction as the change.
"Show me everything that ever happened to this company" is one query.

| Column | Type | Notes |
|---|---|---|
| `customer_id` | `uuid` | FK to `exporter_profile.customer_id` (added by 0014) |
| `deal_id` | `uuid` | the deal, when the change is about one; `NULL` for company-level |
| `dimension` | `varchar(32)` | `journey`, `qualification`, `marker`, `profile`, `conversation`, `deal`, `background_check`, `verification`, `screening` |
| `event_type` | `varchar(100)` | why the row was written |
| `from_status` / `to_status` | `varchar(64)` | **`varchar`, never enums** |
| `actor_id` | `varchar(255)` | `str(user.id)`; `NULL` = the platform |
| `reason` | `text` | required for the moves the contract marks required |
| `event_metadata` | `jsonb` | free-shaped details; `source` lives here |

`from_status` / `to_status` / `dimension` **must stay `varchar`**. A history table has
to record a value just added to an enum without its own migration first, and to keep
serving a value later removed. The service validates the value before writing, so what
lands was a valid enum member at the time.

> Rows written in one transaction **share a timestamp**, so their order among themselves
> is not chronological. Every "recent" index therefore tie-breaks on `id`:
> `(customer_id, created_at DESC, id DESC)`. Order by `created_at` alone and the result
> is non-deterministic.

> `contracts/history-row.md` §1 still says `customer_id` has "no foreign key yet". That
> is **stale** — `fk_exporter_lifecycle_history_customer_id` exists, added by 0014.

### `exporter_activity` and `follow_up_completion`

`exporter_activity` is append-only: an activity is never edited, so a correction is a
new activity. `follow_up_completion` is one row per activity
(`uq_follow_up_completion_activity_id`), also append-only, with `next_due_at` required
exactly when `outcome = 'RESCHEDULED'`.

`ix_exporter_activity_actor_due_at_pending` is partial — `WHERE due_at IS NOT NULL` —
and is what makes the "my follow-ups" query cheap.

### Qualification

Four tables. `qualification_criterion` (versioned, append-only,
`UNIQUE (key, version)`), `qualification_reason_code`, `qualification_result` (one per
criterion per company, append-only), `qualification_outcome` (the decision).

`qualification_outcome` is a **superseding chain**: `supersedes_outcome_id` is `UNIQUE`
(one superseder per row) and `uq_qualification_outcome_first_per_company` is a partial
unique index on `(customer_id) WHERE supersedes_outcome_id IS NULL` (one head per
company). Together those two make the chain a **line, not a tree** — the same shape is
used by `background_check_decision`, `trade_invoice_outcome` and `verification_review`.

---

## 5. Background check, verification and screening

### `check_cycle`

Append-only. A numbered cycle per company: `UNIQUE (company_id, number)`,
`CHECK (number = 1) = (kind = 'INITIAL')`, a reason required for every cycle after the
first. `uq_check_cycle_id_company` exists to be referenced by the composite FKs below.

### `background_check_decision`

The authoritative log of the background-check gauge. Append-only, and the most heavily
constrained table in the CRM. Worth reading in full before touching it.

- **The move is checked in SQL.** `ck_background_check_decision_move` enumerates the
  nine legal `(from_value, to_value)` pairs. The state machine is not only in Python.
- **The chain is a line.** `supersedes_decision_id` is `UNIQUE`, and
  `uq_background_check_decision_first_per_company` is partial-unique on
  `(company_id) WHERE supersedes_decision_id IS NULL`.
- **The chain cannot jump companies or skip a state.** `uq_…_chain_key UNIQUE
  (id, company_id, to_value)` is the target of a **composite self-FK** on
  `(supersedes_decision_id, company_id, from_value)` — so a decision's `from_value`
  must equal the superseded decision's `to_value`, for the same company. The database,
  not the service, refuses a forged chain.
- `CHECK ((from_value = 'NOT_STARTED') = (supersedes_decision_id IS NULL))` — the first
  decision, and only the first, has no parent.
- A reason is required for every move except the first. `risk_rating` is required
  exactly when `to_value = 'CLEAR'` and forbidden otherwise.
- `expires_at` is allowed only on a `CLEAR` and must be after `decided_at`.
- **Maker-checker** (0026): `(proposal_id IS NULL) = (approved_by IS NULL) =
  (approved_at IS NULL)`, plus `CHECK (approved_by <> decided_by)` — the database
  refuses self-approval.

### `background_check_proposal` / `…_resolution`

Both append-only. A proposal records the move someone wants, its `inputs_fingerprint`
(`CHECK ~ '^[0-9a-f]{64}$'` — a SHA-256 hex digest) and its `rules_version`. Exactly one
resolution per proposal (`uq_background_check_proposal_resolution_proposal`), with:

- `CHECK (outcome = 'WITHDRAWN') = (created_by = proposed_by)` — only the proposer
  withdraws, and a withdrawal is nobody else's act.
- `CHECK (outcome = 'APPROVED') = (decision_id IS NOT NULL)`.
- A composite FK pinning the approving decision to
  `(decision_id, proposal_id, created_by)` on the decision table — the approver on the
  resolution and the `approved_by` on the decision are the same person, enforced by the
  FK.

### `background_check_evidence`

Append-only, and a **tagged union**: `kind` is `DOCUMENT` \| `VERIFICATION_RESULT` \|
`SCREENING_ITEM`, and `ck_background_check_evidence_kind` requires exactly the one
matching reference column to be non-null and the others to be null. Each
`(decision_id, <ref>)` pair is unique, so the same evidence cannot be attached twice.

### `verification_result`

Four triggers, which between them make a reviewed result unfalsifiable:

| Trigger | What it refuses |
|---|---|
| `trg_verification_result_no_delete` | any `DELETE` |
| `trg_verification_result_field_immutability` | changing `reviewed_by` or `review_status` once set |
| `trg_verification_result_input_immutability` | changing `evidence_note`, `evidence_refs`, `subject_snapshot`, `subject_company_id`, `cycle_id` once set |
| `trg_verification_result_outcome_freeze` | changing the outcome of a result that has been reviewed |

`entity_reference` is a **bare uuid with no foreign key** — it is polymorphic over
`entity_type` (`EXPORTER`, `BUYER`, `DIRECTOR`, `INVOICE`, `VESSEL`, `SHIPMENT`).
`subject_company_id` is the real FK to the company, added by 0023 and set once.

`ix_verification_result_entity_recent` tie-breaks on three columns —
`(entity_type, entity_reference, performed_at DESC, created_at DESC, id DESC)` — because
results recorded in one transaction share `created_at`.

### `verification_review` and `screening_review_item`

`verification_review` is an append-only superseding chain, same line-not-tree shape as
above, with `CHECK (supersedes_review_id IS NULL OR note IS NOT NULL)` — superseding a
review requires saying why.

`screening_review_item` is the checklist's own append-only log, one row per answer per
item key. `status` is a `varchar` with a `CHECK` list (`NEEDS_REVIEW`, `PASSED`,
`FAILED`, `EXEMPT`), not an enum. `evidence_refs` is `jsonb` with
`CHECK jsonb_typeof(evidence_refs) = 'array'`. `cycle_id` carries a **composite FK**
`(cycle_id, customer_id)` → `check_cycle (id, company_id)`, so an answer cannot be filed
under another company's cycle.

### `bank_activity_finding`

Read by the screening router. **It has no foreign key to `exporter_profile`** —
`customer_id` is a bare uuid, unlike every other CRM child table. Nothing in this
checkout writes it.

---

## 6. Deals, documents and trade history

### `deal`

| Constraint / trigger | Rule |
|---|---|
| `ck_deal_withdrawal_reason` | a reason exactly when `stage = 'WITHDRAWN'` |
| `ck_deal_buyer_is_not_the_seller` | `buyer_company_id <> company_id` |
| `fk_deal_seller_gst_registration_id` | **composite** `(seller_gst_registration_id, company_id)` → `exporter_gstin (id, customer_id)` — the database refuses a deal invoiced through another company's branch |
| `trg_deal_buyer_company_set_once` | `buyer_company_id` is set once (`NULL` → a value is allowed once, so a backfill can still run) |
| `trg_deal_terminal_freeze` | see below |

`onboarding.prevent_terminal_deal_change()` is the most-rewritten function in the
schema — 0022, 0029, 0034, 0036 and 0039 each replaced it, and `CREATE OR REPLACE
FUNCTION` keeps nothing, so each version restates every earlier rule. The **current**
body (0039) refuses, once `stage IN ('HANDED_OVER', 'WITHDRAWN')`:

- any change to `stage`, `handed_over_at`, `withdrawal_reason`, `company_id`,
  `seller_gst_registration_id` or `reference`;
- any change to `buyer_company_id` **when the old value was not `NULL`** — a closed deal
  whose buyer was never linked can be filled in once, and never changed again;
- any change to `handover_snapshot` when one already exists — the snapshot is what the
  lending team was given.

> Editing this function means restating all of it. Reading only the newest migration
> tells you the whole rule; reading only an older one does not.

> **`deal.reference` has no unique constraint or index.** Uniqueness, if it is intended,
> is service-side only.

### `deal_buyer` and `deal_buyer_company_map`

`deal_buyer` is the typed-in buyer, one per deal (`uq_deal_buyer_deal_id`), and the one
CRM table with `ON DELETE CASCADE` — it is the deal's own detail, not an independent
record. `CHECK country ~ '^[A-Z]{2}$'`.

`deal_buyer_company_map` links a legacy `deal_buyer` to a real company. Append-only,
and its **primary key is `(deal_buyer_id, id)`** — `deal_buyer_id` leading is what makes
re-running the buyer migration a no-op. `match_rule` records *how* the link was decided
(`PAN`, `REGISTRATION_NUMBER`, `NEW`, `NAME_CONFIRMED` — a person decided —
`ALREADY_LINKED`).

### `crm_document`

| | |
|---|---|
| Owner | `CHECK num_nonnulls(company_id, deal_id) = 1` — a document belongs to a company **or** a deal, never both, never neither |
| `storage_key` | `UNIQUE`. Shape: `{env}/{owner_type}/{owner_id}/{source}/{document_id}{ext}` |
| `trg_crm_document_no_delete` | any `DELETE` is refused |
| `trg_crm_document_identity_immutability` | `company_id`, `deal_id`, `category`, `document_type`, `source`, `file_name`, `content_type`, `size_bytes`, `uploaded_by`, `uploaded_at`, `storage_key` are each fixed once set |

The bytes live outside the database. The only storage adapter in this checkout is
`infrastructure/storage/local_disk.py`; the scanner is a passthrough. `scan_status`
gates serving: only `AVAILABLE` is served, and `ix_crm_document_scan_status` exists for
the sweep.

`deal_required_document` is a versioned, append-only requirement list
(`UNIQUE (category, document_type, version)`). From 0030, a deal with no `AVAILABLE`
pre-shipment document **cannot be handed over** — a behaviour change, not just schema.

### Trade history

`trade_relationship` — one ordered pair per seller/buyer (`uq_trade_relationship_pair`,
`CHECK seller <> buyer`). There is deliberately **no column on `deal`** for this.

`trade_invoice` — `UNIQUE (relationship_id, invoice_number)`, `CHECK amount > 0`,
`CHECK currency ~ '^[A-Z]{3}$'`. Currency is stored and **never converted**. Identity
(`relationship_id`, `invoice_number`, `invoice_date`, `amount`, `currency`, `deal_id`)
is frozen once set — including `deal_id`, where `NULL` → a value is allowed once, so an
invoice recorded as past trade can later be tied to the deal that produced it and never
re-tied.

`trade_invoice_outcome` — append-only superseding chain, one head per invoice, one
superseder per row; superseding requires an `evidence_note`. `amount_paid` is required
when `payment_status = 'PARTIAL'`.

---

## 7. Legacy tables in the `onboarding` schema — do not build on these

The `onboarding` schema holds a second, older system: the `onboarding_request` path, an
18-state machine, a 12-state case machine, a Temporal workflow and an
identity-provider framework. **No CRM code reads or writes any of it.** It is kept, not
deleted (migration-register §3).

| Table | Belongs to |
|---|---|
| `onboarding_request`, `onboarding_event`, `onboarding_document`, `ubo_record` | the legacy request path |
| `onboarding_case`, `case_state_transition`, `kyc_case`, `person_profile` | the legacy 12-state case machine |
| `onboarding_customers`, `onboarding_applicant_mappings`, `onboarding_verifications`, `onboarding_webhook_events` | the legacy identity-provider framework |
| `kyb_vendor_registration`, `kyb_vendor_result` | the legacy KYB vendor registry |

`onboarding_event` cannot be reused for CRM history: its `onboarding_request_id` is
`NOT NULL` with a foreign key, which is exactly why `exporter_lifecycle_history` had to
be a separate table.

`pytest --crm` (defined in `backend/conftest.py`) collects the CRM's tests and
`tests/contract/` and skips these tables' tests by name. If you rename or delete one of
those test files, `--crm` raises a `UsageError` rather than silently collecting it
again.

---

## 8. Enum types

55 enum types live in the `onboarding` schema. They are real PostgreSQL types, created
by their migration and schema-qualified (`onboarding.deal_stage_enum`).

The ones a CRM query is most likely to need:

| Type | Values |
|---|---|
| `exporter_journey_enum` | `LEAD`, `PROSPECT`, `CUSTOMER` |
| `exporter_marker_enum` | `NONE`, `PAUSED`, `ENDED` |
| `qualification_state_enum` | `NOT_YET_REVIEWED`, `QUALIFIED`, `NOT_QUALIFIED` |
| `exporter_conversation_enum` | `NOT_CONTACTED`, `REACHING_OUT`, `SPOKE_TO_THEM`, `INTERESTED`, `NOT_NOW`, `READY_NOW` |
| `background_check_enum` | `NOT_STARTED`, `IN_REVIEW`, `CLEAR`, `MORE_INFO`, `FLAGGED`, `ON_HOLD` |
| `background_check_risk_enum` | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `deal_stage_enum` | `OPEN`, `GATHERING_PAPERWORK`, `HANDED_OVER`, `WITHDRAWN` |
| `company_identity_type_enum` | `IN_PAN`, `FOREIGN_REG` |
| `company_pipeline_status_enum` | `IN_PIPELINE`, `NOT_IN_PIPELINE` |
| `exporter_source_enum` | `MANUAL`, `SALES`, `REFERRAL`, `RXIL`, `PARTNER`, `API`, `BROKER`, `EVENT`, `EXISTING_CUSTOMER`, `DEAL_BUYER` |
| `exporter_activity_type_enum` | `CALL`, `MEETING`, `EMAIL`, `NOTE`, `TASK`, `FOLLOW_UP` |
| `follow_up_outcome_enum` | `DONE`, `NO_ANSWER`, `RESCHEDULED`, `CANCELLED` |
| `crm_document_category_enum` | `ENTITY_KYC`, `COMPLIANCE_SCREENING`, `COMPANY_MARKET_REVIEW`, `PRE_SHIPMENT`, `SHIPPING`, `CUSTOMS_AND_REGULATORY`, `BUYER`, `BANKING`, `INSURANCE`, `OTHER` |
| `crm_document_source_enum` | `RXIL`, `EXPORTER_UPLOAD`, `INTERNAL`, `SYSTEM` |
| `crm_document_scan_status_enum` | `PENDING_SCAN`, `AVAILABLE`, `QUARANTINED`, `SCAN_FAILED` |
| `gst_registration_status_enum` | `UNVERIFIED`, `ACTIVE`, `CANCELLED`, `SUSPENDED` |
| `gst_registration_flag_enum` | `NONE`, `FLAGGED` |
| `buyer_match_rule_enum` | `PAN`, `REGISTRATION_NUMBER`, `NEW`, `NAME_CONFIRMED`, `ALREADY_LINKED` |
| `verification_type_enum` | `KYC`, `KYB`, `AML`, `CFT`, `SANCTIONS`, `PEP`, `ADVERSE_MEDIA`, `COMPANY_REGISTRY`, `UBO`, `GST`, `IEC`, `BANK_ACCOUNT`, `BUYER`, `INVOICE`, `INVOICE_DUPLICATION`, `SHIPMENT`, `VESSEL`, `INSURANCE` |
| `verification_entity_type_enum` | `EXPORTER`, `BUYER`, `DIRECTOR`, `INVOICE`, `VESSEL`, `SHIPMENT` |
| `verification_result_status_enum` | `PENDING`, `PASSED`, `FAILED`, `REVIEW` |
| `verification_review_status_enum` | `ACCEPTED`, `REJECTED`, `ESCALATED` |
| `trade_payment_status_enum` | `PAID`, `UNPAID`, `PARTIAL`, `DISPUTED`, `UNKNOWN` |
| `trade_proof_status_enum` | `CLAIMED`, `PROVEN` |

Not enums, deliberately: `exporter_lifecycle_history.dimension` / `from_status` /
`to_status` (§4), `screening_review_item.status`, `check_cycle.kind` and
`background_check_proposal_resolution.outcome` — the last three are `varchar` with a
`CHECK` list.

> **Never run `ALTER TYPE … ADD VALUE` in an autocommit block.** It has broken this
> repository: the enum value commits, the rest of the migration does not, and
> `alembic_version` still names the old revision, so a re-run fails on a value that
> already exists. Add the value in an ordinary transactional migration.

> **PostgreSQL cannot drop an enum value.** Removing one means rebuilding the type
> (`onboarding_0041_map_rule_link`'s downgrade does this, and refuses while any row uses
> the value).

---

## 9. What the database refuses — functions and triggers

Append-only in this codebase means **the database refuses the write**, not that the
application avoids it. Every rule here has a test that attempts the violation in raw
SQL through `psycopg2`, bypassing the ORM, so the test proves the *database* refuses it.

### Five functions

| Function | Job |
|---|---|
| `public.prevent_mutation()` | Raises on any `UPDATE` or `DELETE`, naming the table via `TG_TABLE_NAME`. Shared across eight schemas, lives in `public` because it belongs to no module, and is always referenced schema-qualified so a `search_path` change cannot break it. **It blocks `DELETE` too** — a migration that must clear an append-only table has to use `TRUNCATE`, since row-level triggers do not fire on truncate. |
| `onboarding.prevent_field_mutation_when_set(cols…)` | Takes column names as trigger arguments. Refuses a change to any named column whose old value was not `NULL` — so `NULL` → a value is allowed **once**, which is what lets a backfill fill a column a trigger otherwise freezes. |
| `onboarding.prevent_terminal_deal_change()` | §6. |
| `onboarding.prevent_reviewed_verification_outcome_change()` | Refuses an outcome change on a verification result that has been reviewed. |
| `onboarding.prevent_gst_registration_delete()` | Refuses any `DELETE` on `exporter_gstin`, telling the caller to deactivate. |

### The 35 triggers on the `onboarding` schema

Fully append-only — `UPDATE` and `DELETE` both refused:

`background_check_decision`, `background_check_evidence`, `background_check_proposal`,
`background_check_proposal_resolution`, `check_cycle`, `deal_buyer_company_map`,
`deal_required_document`, `exporter_activity`, `exporter_lifecycle_history`,
`follow_up_completion`, `qualification_criterion`, `qualification_outcome`,
`qualification_result`, `screening_review_item`, `trade_invoice_outcome`,
`verification_review`, plus legacy `case_state_transition`, `onboarding_event` and
`onboarding_verifications`.

Column-level freezes — `prevent_field_mutation_when_set`, exact argument lists as the
live database has them:

```
crm_document        company_id, deal_id, category, document_type, source, file_name,
                    content_type, size_bytes, uploaded_by, uploaded_at, storage_key
deal                buyer_company_id                                    (set-once)
exporter_profile    source
trade_invoice       relationship_id, invoice_number, invoice_date, amount, currency, deal_id
verification_result reviewed_by, review_status                           (field immutability)
verification_result evidence_note, evidence_refs, subject_snapshot,
                    subject_company_id, cycle_id                        (input immutability)

kyb_vendor_registration  vendor_id                                      ┐
kyb_vendor_result        retrieved_at                                   │ legacy
onboarding_document      submitted_at                                   │ tables
onboarding_request       screening_result, ubo_mapping, risk_rating_factors
ubo_record               created_at                                     ┘
```

Delete-only refusals: `crm_document`, `verification_result` (both via
`prevent_mutation` on `BEFORE DELETE … FOR EACH STATEMENT`) and `exporter_gstin` (via
its own function, `FOR EACH ROW`).

**No table in the `onboarding` schema has a `NOT VALID` constraint, an exclusion
constraint or a sequence.** 153 indexes, all validated.

### Writing a new rule

- Every new constraint gets a direct-SQL violation test.
- `tests/contract/test_orm_matches_the_onboarding_schema.py` fails when a migration adds
  an index or constraint the model does not declare, or the reverse — so
  `alembic revision --autogenerate` never proposes dropping one.

---

## 10. Migrations

**[`contracts/migration-register.md`](contracts/migration-register.md) is the
authority.** It lists every revision, its parent, its owner, what it changed and how it
rolls back. The facts that belong here:

| | |
|---|---|
| Tool | Alembic, one chain for the whole platform |
| Revisions | 105 |
| Head | **one**: `onboarding_0043_identity_type` |
| CRM migration directory | `backend/app/modules/onboarding/migrations/`, revisions `onboarding_0001_baseline` … `onboarding_0043_identity_type` |
| Next free CRM number | **0044** |
| Naming | `onboarding_00NN_<lane>_<topic>` |
| Root revision | `a0b1c2d3e4f5_shared_immutability_function` — creates `public.prevent_mutation()`, which every other module's triggers need |

`version_locations` in `alembic.ini` is an explicit list of 18 directories and **must
stay on one line** — Alembic splits it on commas and spaces, so a multi-line value
silently resolves to zero locations. `tests/contract/test_migration_discovery.py`
derives the expected list from the filesystem, so an unlisted directory fails the build
rather than drifting silently.

Hard limits that have each broken this repository once:

- **Revision ids are 32 characters or fewer** (`alembic_version.version_num` is
  `varchar(32)`). A longer id fails *on the database, partway through the DDL*.
- **One chain, one head.** If `alembic heads` prints two, re-parent — do not add a
  merge revision. Three historical merge points exist; do not add a fourth.
- **Grow a column in three migrations** on a populated table: expand (nullable),
  backfill, contract.
- **`pg_dump` before any migration that changes data.** A data migration that inserts
  into an append-only table cannot be undone by a `DELETE` — the trigger refuses it.

Round-trip before merging:

```bash
cd backend
python -m alembic heads        # exactly one
python -m alembic upgrade head
python -m alembic downgrade -1
python -m alembic upgrade head
python -m alembic check        # no model/database drift
```

---

## 11. How the application connects

`app/platform/database/` holds all of it; no business rules live there.

### Models — `platform/database/models.py`

| Base | Gives you |
|---|---|
| `Base` | `DeclarativeBase` |
| `AnerModel` | `id` (`uuid4` PK) + `created_at` + `updated_at` (`onupdate=now()`). Every ordinary mutable record. |
| `AppendOnlyModel` | `id` + `created_at` only. **No `updated_at`**, because there is no update. |

A table using `AppendOnlyModel` must also get its trigger in a migration — the base
class alone enforces nothing. `AppendOnlyRepository` likewise exposes `get`, `list` and
`create` and no `update` or `delete`.

### Sessions — `platform/database/services.py`

Four engines, four session factories, four FastAPI dependencies:

| Dependency | Engine | Role |
|---|---|---|
| `get_db()` | `engine` | `aner` — writable. **Everything in the CRM uses this.** It commits on a clean exit and rolls back on any exception. |
| `get_ro_db()` | `ro_engine` | `ledger_ro` |
| `get_settlement_ro_db()` | `settlement_ro_engine` | `settlement_ro` |
| `get_audit_ro_db()` | `audit_ro_engine` | `audit_ro` |

Pool: `pool_size=10`, `max_overflow=20`, `pool_timeout=30`, `pool_recycle=1800`,
`pool_pre_ping=True`. Sessions are `expire_on_commit=False`, `autoflush=False`.

### Read-only enforcement is three independent layers

1. **The role** — credentials that cannot write. Fails at the database with SQLSTATE
   `42501`.
2. **The transaction** — `READ_ONLY_CONNECT_ARGS` sets
   `default_transaction_read_only=on` per *engine*, so raw SQL is refused too, with
   SQLSTATE `25006` and a message that names the reason.
3. **The ORM** — `forbid_writes(session)` attaches a `before_flush` listener that raises
   `ReadOnlySessionError` naming the pending objects, before any SQL is emitted. This is
   the layer a developer meets first and the only one whose message points at the
   Python.

None is redundant, and the tests assert on both SQLSTATEs because they prove different
layers.

### One transaction per operation

A CRM service validates everything before it assigns anything, writes its history row
through the shared writer (which flushes and **never** commits), and commits once.
Events are published **after** the commit, best effort — the history row is the source
of truth, so a dead bus never undoes a committed change.

---

## 12. The database in development and in tests

### Getting a usable database

```bash
cd backend
python -m alembic upgrade head                              # the schema
python -m app.platform.authentication.cli bootstrap         # first ADMIN + COMPLIANCE, from .env
python -m app.modules.onboarding.sample_data                # seven fixed companies
```

`sample_data` drives the **real services** — nothing is written directly. Company ids
are `uuid5`, so a repeat run changes nothing and reports zeros. Each owner seeds its own
part from its own `sample_data_*.py` hook.

Migration `0014` **refuses to empty the CRM's tables when they hold rows**. Set
`E9_ALLOW_CRM_RESET=1` only if you mean to start a database's CRM over.

### Tests share the development database

There is **no test database and no `create_all`**. The suite connects to `DATABASE_URL`
— the same database you develop against — against a schema that `alembic upgrade head`
has already built. Consequences:

- **A test run leaves rows behind.** There is no truncate-between-tests fixture.
- A session-scoped autouse fixture swaps the app's four pooled engines for `NullPool`
  twins, carrying `connect_args` across so the read-only transaction setting survives.
  This is a **Windows** workaround: asyncpg's overlapped-I/O futures are cancelled for
  idle pooled connections between tests, so a fresh TCP connection per request is the
  only reliable option.
- A second session-scoped fixture loads the three GitOps reference registries at the
  start and reloads them at the end, asserting they are non-empty — individual
  compliance tests delete registry rows, and a shared database would otherwise be left
  with sector screening silently disabled.

To rehearse a migration safely, copy the database first (`createdb -T <source>
<scratch>`, which needs nobody connected to the source, or `pg_dump | psql`), point
**both** `DATABASE_URL` and `DATABASE_SYNC_URL` at the copy, and check that
`alembic current` prints the head.

---

## 13. Traps, in one list

1. **Join on `exporter_profile.customer_id`, never `.id`.** The wrong one returns no
   rows and no error. (§3)
2. **The default port in `config.py` is wrong for the local container** — 5432 vs 5433.
   `backend/.env` holds the real one.
3. **`DATABASE_URL` and `DATABASE_SYNC_URL` must agree.** Alembic reads the second; the
   app and the tests read the first. Pointing them at different databases produces
   "the migration ran but nothing changed".
4. **`alembic upgrade head` refuses to run** without `LEDGER_RO_DB_PASSWORD`,
   `SETTLEMENT_RO_DB_PASSWORD` and `AUDIT_RO_DB_PASSWORD`.
5. **`SAWarning: Cannot correctly sort tables`** on every Alembic run is expected — the
   `deal` ↔ `exporter_profile` ↔ `exporter_gstin` FK cycle. (§3)
6. **Order by `(…, created_at DESC, id DESC)`, not `created_at` alone.** Rows written in
   one transaction share a timestamp. (§4)
7. **Normalise before looking for a duplicate registration number** — the unique index
   strips non-alphanumerics and upper-cases. (§4)
8. **`prevent_field_mutation_when_set` allows `NULL` → a value once.** That is a
   feature, used by backfills; it also means "frozen" does not mean "required".
9. **Editing `prevent_terminal_deal_change()` means restating all of it.**
   `CREATE OR REPLACE FUNCTION` keeps nothing. Read the newest migration that touches
   it (0039), not the oldest. (§6)
10. **`DELETE` on an append-only table is refused, so a migration that must clear one
    needs `TRUNCATE`** — row triggers do not fire on truncate. (§9)
11. **Tests run against your development database and leave rows behind.** (§12)
12. **`contracts/history-row.md` §1 is stale** on the history foreign key — it exists.
13. **Known gaps, if you are looking for one:** `deal.reference` has no unique
    constraint; `bank_activity_finding.customer_id` has no foreign key;
    `verification_result.entity_reference` is polymorphic and unconstrained by design.
