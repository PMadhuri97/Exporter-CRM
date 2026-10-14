# CRM database audit — 2. Findings and table-by-table audit

**Part 2 of 4.** [1 Inventory](inventory.md) · [2 Audit](audit.md) ·
[3 Options](options.md) · [4 Migration plan](migration-plan.md)

This file contains:

- the **executive summary**;
- **Deliverable C**: the table necessity matrix, covering all 49 tables;
- **Deliverable D**: redundancy, normalisation and over-fragmentation, the table-count
  analysis, and the optimisation opportunity register.

Basis: code at `a36d10c` and the development database at `onboarding_0053`, read only.
Row counts are **development data**. They show only that a path has been exercised, and
a count of zero in development proves nothing about production.

**Revision note (12 October, second pass).** Every consolidation candidate was
re-examined against the code. Four verdicts changed:

1. Directors and UBOs extend `exporter_contact` instead of getting a new table.
2. `deal_buyer_company_map` folds into `deal_buyer`.
3. `qualification_reason_code` becomes code.
4. The sanctions overlap is understood: one record is a summary of the other. The real
   redundancy is that a sanctions result can be entered two ways.

---

## 1. Executive summary

**The `onboarding` schema has 49 tables. The CRM needs 32 of them.** The other 17 fall
into two groups:

- **14 tables are a second, dormant system.** This is the legacy onboarding-request,
  case, identity-provider and KYB path. It shares the schema but has no foreign key into
  the CRM and no rows in development. It is written only by routes and a Temporal worker
  that the CRM does not use.
- **3 CRM tables duplicate something or are unused:**
  - `deal_buyer_company_map` is one-to-one with `deal_buyer` and should be columns on it.
  - `qualification_reason_code` is a lookup that only migrations ever change.
  - `bank_activity_finding` is a placeholder that nothing writes.

**One entity is missing, and the fix adds no table.** The CRM has nowhere to record
directors and beneficial owners (UBOs). Sanctions screening and group suggestions read
them from the legacy `ubo_record` table, which no mounted route writes. So UBO
screening always sees an empty list, and the CRM's tests insert UBOs into legacy tables
with raw SQL.

`exporter_contact` already has everything a people table needs: a lifecycle (active,
inactive, left the company), no delete path, and field-level masking
(`api/schemas/masking.py`). The plan makes it the company's **people** table, with
director and UBO roles. A director who is also the main contact is then one row, not
two.

**The 32 remaining tables are each justified.** Four were re-examined as merge
candidates and kept, for the reasons below (detail in §4.2):

| Table | Why it stays separate |
|---|---|
| `follow_up_completion` | The design forbids adding completion columns to an append-only activity. Architecture §9.3 names that as the first mistake to avoid |
| `background_check_proposal_resolution` | A composite FK pins the approver to the decision |
| `sanctions_run` | Its outcome changes as its hits are decided, and one company-level `SANCTIONS` result summarises many runs |
| `trade_relationship` | It is an API resource. It cannot drift from deals, because a deal's buyer is set once |

**Other problems, beyond the table count:**

- **Superseded columns kept next to their replacements:**
  - the relationship manager's free text (100 of 128 development companies have only
    the text);
  - the GST branch's free-text address;
  - three legacy columns on `verification_result`.
- **Two ways to record a sanctions result:** a structured run, or a `SANCTIONS` result
  typed in by hand. In development, 59 of the 61 `SANCTIONS` results were entered
  directly (by hand or by sample data); only 2 were written by the screening service,
  from its 1 run.
- **Integrity gaps:**
  - an evidence reference has no FK;
  - two cycle FKs are single-column, where every sibling FK is composite;
  - a hit is not tied to the lists its run screened;
  - old configuration versions can still be edited.
- **Drift between the ORM, the documents and the database:**
  - one primary key and 12 CHECK constraints differ, and `alembic check` compares
    neither;
  - `database.md` and the migration register stop at 0043.

**Recommendation ([options.md](options.md)): the optimised design.**

- It takes the schema from **49 to 32 tables**.
- It keeps every append-only and maker-checker guarantee.
- It adds or strengthens 7 FKs (4 new, 3 made composite) and adds 2 CHECKs on derived
  columns.
- It turns the link from a sanctions run to a person, which today exists only in code,
  into a real FK.

A later, optional step retires `deal_buyer` (**31 tables**) once every environment has
run the buyer migration.

**Nothing has been changed.** These four documents are the only files written.

---

## 2. How each table was judged

For every table, the matrix answers the brief's seven questions:

| Question | Matrix column |
|---|---|
| 1 | Business requirement |
| 2 | Written / read by |
| 3 | API / workflow |
| 4 | Own lifecycle, integrity, access or audit? |
| 5 | Same information elsewhere? |
| 6 | If removed |
| 7 | Recommendation |

Code paths were found by searching non-test, non-migration code for the model class and
table name. Raw SQL, data commands, sample data, the frontend and the tests were also
searched. "Router" means a file in `app/modules/onboarding/api/`; "service" means a file
in `app/modules/onboarding/application/`.

The classes, from the brief:

| Class | Meaning |
|---|---|
| **A** | Essential |
| **B** | Essential but redesignable |
| **C** | Consolidation candidate |
| **D** | Potentially redundant |
| **E** | Legacy or obsolete |
| **F** | Uncertain |

---

## 3. Deliverable C — table necessity matrix

### 3.1 The company record and its satellites

| Table | Business requirement | Written / read by | API / workflow | Own lifecycle, integrity, access or audit? | Same information elsewhere? | If removed | Class | Recommendation |
|---|---|---|---|---|---|---|---|---|
| `exporter_profile` | One record per company for its whole life: lead → prospect → customer; PAN, IEC, CIN, registration number; owner, reviewer, collector; group parent | `exporter_profile_service`, `qualification_service`, the conversation and background-check services (gauges), `company_group_service`, `collections_owner_service`, `company_intake` (RXIL), CSV import; read by 53 non-test files | `exporter_router`, `company_directory_router`, `company_intake_router`, `company_group_router`, `staff_router` | Yes: root of 22 FKs; unique PAN and normalised registration number; journey, marker and pipeline CHECKs; `source` frozen; group-cycle trigger | The gauge columns cache the chain heads, intentionally (§4.3). `identity_type` is derived. The `relationship_manager` text is superseded | The CRM | **B** | Keep. Retire the RM text (O4). CHECK `identity_type` (O8). Keep the `id`/`customer_id` dual key (O16 not recommended) |
| `exporter_gstin` | Several GSTINs per company, each a branch with state, status, flag and activity | `gst_registration_service`, `exporter_profile_service`, `company_address_service`, `branch_flags`, `company_directory`, `deal_service` | `gst_registration_router`; deal branch picker | Yes: unique per company; never deleted; composite key referenced by `deal`; format CHECK | `address` (text) is superseded by `address_id` (in development, 6 text addresses and 0 linked). `state_code` = `left(gstin, 2)` | Multi-GSTIN breaks; deals lose their branch | **B** | Keep. Convert the text address, then drop it (O5). CHECK `state_code` (O8) |
| `company_address` | Typed addresses, one default per type | `company_address_service`; read by `background_check_service` | `company_address_router` | Yes: one default per type; never deleted | The GSTIN text address, until O5 | Addresses fall back to text | **A** | Keep |
| `exporter_contact` | People at the company. Today contacts only (status, primary); **should also hold directors and UBOs** | `exporter_contact_activity_service`, `exporter_profile_service`, `deal_service`, `company_directory` | `engagement_router` | Yes: one primary per company; the primary must be active; contact details masked; no delete route | Nothing in the CRM holds directors or UBOs. Legacy `ubo_record` does, but the CRM cannot write it | Contacts lost | **B** | **Extend into the company's people table** (O2): role flags `is_contact`, `is_director`, `is_ubo`, plus person fields, all masked; refuse DELETE |
| `company_bank_account` | Encrypted accounts: propose → approve → verify; a primary per currency; replacement | `company_bank_account_service` | `company_bank_account_router` | Yes: encryption boundary; approval workflow; audited reveal | No | Accounts lost | **A** | Keep. Keeping the workflow on the row, with history rows, is simpler than a separate approval table |
| `payment_term` | Payment terms, versioned so a deal keeps the term it was agreed on | `payment_term_service`, `deal_service` | `/settings/payment-terms` | Versioned configuration with an admin screen | No | Deal terms break | **B** | Keep. Freeze old versions (O9) |

### 3.2 History, activity and engagement

| Table | Business requirement | Written / read by | API / workflow | Own lifecycle, integrity, access or audit? | Same information elsewhere? | If removed | Class | Recommendation |
|---|---|---|---|---|---|---|---|---|
| `exporter_lifecycle_history` | The one append-only log of every change to a company | `history_service`, called by every CRM write service | `history_router`; Activity tab; worklists | Append-only; 17 dimensions in development | Bank and sanctions writes also go to `audit.audit_events`, which serves another purpose (access and security audit) | Audit trail lost | **A** | Keep. FK on `deal_id` (O7) |
| `exporter_activity` | Calls, meetings, emails, notes, tasks, follow-ups with due dates | `exporter_contact_activity_service`, `follow_up_service` | `engagement_router`, `follow_up_router` | Append-only: a correction is a new activity | No | Relationship history lost | **A** | Keep |
| `follow_up_completion` | The outcome of a follow-up, recorded once. A reschedule creates a new activity | `follow_up_service` | `follow_up_router` | Append-only; one per activity; its own actor and time | `customer_id` repeats the activity's | Completed follow-ups become indistinguishable from open ones | **A** | Keep. `follow_up_service.py` and architecture §9.3 rule out a `completed_at` column on the activity, because the activity must stay unchangeable. Composite FK to the activity (O7) |

### 3.3 Qualification

| Table | Business requirement | Written / read by | API / workflow | Own lifecycle, integrity, access or audit? | Same information elsewhere? | If removed | Class | Recommendation |
|---|---|---|---|---|---|---|---|---|
| `qualification_criterion` | Configurable, versioned criteria, optionally answered automatically | `qualification_service` | `/qualification/criteria` (create, version) | Append-only versions; shape CHECK | No | Checklist breaks | **A** | Keep |
| `qualification_reason_code` | NOT_QUALIFIED reason codes, each with a label and a requires-note flag | Read by `qualification_service.list_reason_codes`. **Written only by migrations**: 0017 seeded the codes and 0031 retired three | `GET /qualification/reason-codes` only | None. Nothing in the application changes it, and no FK points at it (`qualification_outcome.reason_codes` is a jsonb snapshot) | The rows are static reference data | Nothing, provided the same 9 codes come from code | **D** | **Move to a code catalogue** (O20). Keep the retired codes, marked inactive, so old outcomes still show a label |
| `qualification_result` | One answer per criterion per company, with evidence | `qualification_service`, `qualification_auto_service` | `qualification_router` | Append-only; evidence and confidence CHECKs | No | Outcomes lose their basis | **A** | Keep |
| `qualification_outcome` | The qualification decision, as a superseding chain | `qualification_service` | `qualification_router` | Append-only; a line, not a tree | The head is cached on the profile (0 mismatches) | Decision history lost | **A** | Keep |

### 3.4 Background check, verification and screening

| Table | Business requirement | Written / read by | API / workflow | Own lifecycle, integrity, access or audit? | Same information elsewhere? | If removed | Class | Recommendation |
|---|---|---|---|---|---|---|---|---|
| `check_cycle` | Numbered review cycles that scope results, answers, decisions and runs | `background_check_service`, `rekyc_due`, the verification, screening and sanctions services | `background_check_router`, `screening_router` | Append-only; target of 5 FKs | No | Re-KYC breaks | **A** | Keep. Make 2 FKs composite (O7) |
| `background_check_decision` | The log of the background-check gauge: moves checked in SQL, a line not a tree, maker-checker, expiry | `background_check_service` | `background_check_router` | 9 CHECKs, 4 composite FKs, self-approval refused | The head is cached on the profile (0 mismatches) | Decision trail lost | **A** | Keep unchanged |
| `background_check_evidence` | What each decision relied on (a tagged union) | `background_check_service`, `decision_evidence` | Decision detail | Append-only | No | Decisions lose their evidence | **A** | Keep. Add the missing FK on `verification_review_id` (O7) |
| `background_check_proposal` | The maker's proposed move | `background_check_service`, `compliance_worklists` | `background_check_router` | Append-only; composite keys | No | Maker-checker breaks | **A** | Keep |
| `background_check_proposal_resolution` | The checker's approve, reject or withdraw, once per proposal | `background_check_service`, `compliance_worklists` | `background_check_router` | Append-only; rules on who may withdraw; a composite FK pins the approver = `decision.approved_by` | No | Approvals stop being immutable | **A** | Keep. Merging would make the proposal mutable and create a proposal ↔ decision FK cycle (§4.2) |
| `verification_result` | Check results: KYB, AML, sanctions, PEP, GST, IEC, bank account, buyer and others | `verification_service`, `company_bank_account_service`, `qualification_auto_service`, `sanctions_screening_service`, RXIL adapter | `/verifications*` | No delete; inputs and the reviewed outcome frozen. **The one interface that the Clear rule, the handover guard and decision evidence read** | Three superseded columns (`reviewed_by`, `review_status`, `evidence_reference`). Sanctions summaries (R18) | Every check lost | **B** | Keep. Drop the three columns (O3). Composite cycle FK (O7) |
| `verification_review` | Reviewer decisions, as a superseding chain | `verification_service` | `POST /verifications/{id}/review` | Append-only; a line, not a tree | The legacy columns above | Review history lost | **A** | Keep |
| `screening_review_item` | The compliance checklist's answer log | `screening_review_service` | `screening_router` | Append-only; composite cycle FK | No | Checklist lost | **A** | Keep |
| `bank_activity_finding` | Bank-monitoring findings from a provider feed | **Nothing writes it.** Read by `screening_review_service.list_bank_findings` | `GET /exporters/{id}/bank-activity`; `BankActivityPanel` shows "no feed connected" | No FK; 0 rows | No | The panel loses a source that is always empty | **E** | **Drop** the table and the route. The panel keeps its "no feed connected" text (O10). A real feed will need its own design anyway: provider ids, deduplication, review |

### 3.5 Sanctions

| Table | Business requirement | Written / read by | API / workflow | Own lifecycle, integrity, access or audit? | Same information elsewhere? | If removed | Class | Recommendation |
|---|---|---|---|---|---|---|---|---|
| `sanctions_list` | Lists screened against, versioned by publication date | `sanctions_list_service` | `sanctions_router` (settings) | Versioned configuration | No | Re-screening on a list change breaks | **B** | Keep. Freeze old versions (O9) |
| `sanctions_run` | One screening of one subject (the company, a director or a UBO), with its lists and its hits | `sanctions_screening_service` | `sanctions_router` | Append-only. Its *outcome* is derived from its hits' current dispositions, so it changes over time | A **summary** goes to `verification_result`: the company's worst outcome across all subjects, written only when it changes, and citable as evidence (R18). It is not a copy of the run | Structured screening lost | **A** | Keep. Composite cycle FK (O7). `subject_reference` gets a real FK to people (O2). One entry path for sanctions (O19) |
| `sanctions_run_list` | Which list versions a run covered | `sanctions_screening_service` | Coverage; re-screen worklist | Append-only many-to-many | `code` and `list_version_date` snapshot the list | Coverage lost | **A** | Keep |
| `sanctions_hit` | Possible matches a run found | `sanctions_screening_service` | `sanctions_router` | Append-only | No | Hits lost | **A** | Keep. FK `(run_id, list_code)` to the run's lists (O7) |
| `sanctions_disposition` | Decisions on each hit, including true-match approval, as a chain | `sanctions_screening_service` | `sanctions_router` | Append-only; one head per hit | No | True-match approvals lost | **A** | Keep |

### 3.6 Deals, documents and trade history

| Table | Business requirement | Written / read by | API / workflow | Own lifecycle, integrity, access or audit? | Same information elsewhere? | If removed | Class | Recommendation |
|---|---|---|---|---|---|---|---|---|
| `deal` | A seller's deal with a buyer company, through a branch; value and term; handover with a frozen snapshot | `deal_service` and others | `deal_router`, the all-deals page | Terminal freeze; buyer set once; composite branch FK | No | Pipeline lost | **A** | Keep. Whether references must be unique is a business rule (O18) |
| `deal_buyer` | **Legacy:** the typed-in buyer, from before buyers were companies | `deal_service:707` (**still written**), `sample_data_deals.py`; read by `deal_repository`, `compliance_inputs`, `decision_evidence`, `migrate_deal_buyers.py` | The deal API's `buyer` field | One per deal | Superseded by `deal.buyer_company_id` | Legacy BUYER results (`entity_reference` = `deal_buyer.id`) lose their target, and the seller-timeline union in `decision_evidence` breaks | **D** | Keep, frozen, with its migration outcome as columns (O21). Refuse new writes (O6). Dropping it later is optional (O15) |
| `deal_buyer_company_map` | Which legacy buyer became which company, by which rule, in which run | `migrate_deal_buyers.py` only | None | Append-only. **The primary key is `deal_buyer_id`, so there is exactly one row per `deal_buyer`** | The relationship is one-to-one with `deal_buyer` | Nothing that set-once columns cannot keep | **C** | **Fold into `deal_buyer`** as set-once columns (O21). The buyer migration has not run on any live database, so the map should be empty everywhere it matters; step 0 checks this |
| `deal_required_document` | Document categories a deal needs before handover, versioned | `deal_required_documents_service`, `deal_service` | `/settings/deal-required-documents` | Append-only versions with an admin screen | No | The handover guard loses its rule | **A** | Keep |
| `crm_document` | Metadata of every document: one owner, scan and preview status | `document_service` and others | `document_router` | Never deleted; identity frozen; views audited | No | Documents lost | **A** | Keep |
| `trade_relationship` | A seller has traded with a buyer (an ordered pair) | `trade_history_service`, `backfill_trade_relationships.py`, `qualification_auto_service`, `exporter_profile_repository` (trade role) | `/exporters/{id}/trade-relationships`, `/trade-relationships/{id}`, `…/invoices` | Unique pair; seller ≠ buyer; provenance | In development all 35 rows equal the distinct deal pairs (`source = deal_buyer_recorded`). Past trade can also create one | The API resource and the anchor for invoices | **A** | Keep. The pair is derived at creation but **cannot drift**, because `deal.buyer_company_id` is set once. Folding it into invoices would re-key 4 routes and the frontend to save 1 table (§4.2) |
| `trade_invoice` | Invoices for past or current trade | `trade_history_service` | `trade_history_router` | Identity frozen | No | Trade history lost | **A** | Keep |
| `trade_invoice_outcome` | Paid, partial or disputed; claimed or proven; as a chain | `trade_history_service` | `trade_history_router` | Append-only | No | Payment record lost | **A** | Keep |

### 3.7 Legacy tables in the `onboarding` schema

What is true of all 14:

- They hold 0 rows in development.
- `database.md` §7 says "do not build on these".
- Their services, the workflow and 23 test files are excluded from `pytest --crm`.
- `migration-register.md` §3 says the legacy case machine and `onboarding_event` "must
  not be removed" (assumption A6). That earlier decision has to be revisited, not
  overridden (Q1).

| Table | Business requirement | Written / read by | API / workflow | Own lifecycle, integrity, access or audit? | Same information elsewhere? | If removed | Class | Recommendation |
|---|---|---|---|---|---|---|---|---|
| `onboarding_request` | The superseded 18-state onboarding journey | Legacy services and the Temporal workflow (the worker is not started); **read by the CRM** to find UBOs | None mounted | A partial unique index on the active request | Company identity now lives on `exporter_profile` (0014) | The CRM's UBO lookups break, unless O2 lands first | **E** | Retire after O2 |
| `ubo_record` | Beneficial owners of a request | `onboarding_request_service:500`; **read by the CRM** | None mounted | — | It is the missing CRM entity | As above | **E** | Copy into people with the same ids (O2), then retire |
| `onboarding_event` | State log for requests | Legacy services | None | Append-only | `exporter_lifecycle_history` | Nothing | **E** | Retire |
| `onboarding_document` | Documents for requests | Legacy services | None | — | `crm_document` | Nothing | **E** | Retire |
| `kyb_vendor_result` | KYB vendor responses | Legacy services | None | — | `verification_result` | Nothing | **E** | Retire |
| `kyb_vendor_registration` | KYB vendor registry | A startup seed that loads nothing | Startup | — | — | Remove the seed call | **E** | Retire |
| `onboarding_case` | The 12-state KYC case machine | `case_service` | `/onboarding/cases…` **mounted** | Idempotency keys | The `cases` module; `check_cycle` | The mounted routes break | **E / F** | Confirm no caller, then retire |
| `case_state_transition` | Case state log | `case_service` | Mounted | Append-only | — | As above | **E / F** | Retire with the case |
| `kyc_case` | One-to-one case extension | `case_service` | Mounted | — | — | As above | **E / F** | Retire with the case |
| `person_profile` | One-to-one case subject | `case_service` | Mounted | — | — | As above | **E / F** | Retire with the case |
| `onboarding_customers` | Identity-provider applicant (Sumsub) | `onboarding_service` | `/onboarding/register` **mounted** | Unique email | A third "customer" concept | The mounted route breaks | **E / F** | Confirm no caller or webhook, then retire |
| `onboarding_applicant_mappings` | Provider applicant ids | `onboarding_service`, `webhook_service` | `/register`, `/{id}/sdk-token` **mounted** | — | — | As above | **E / F** | Retire with the above |
| `onboarding_verifications` | Provider verification log | `webhook_service` | `/webhooks/sumsub` **mounted** | Append-only | `verification_result` | As above | **E / F** | Retire with the above |
| `onboarding_webhook_events` | Webhook deduplication and payload | `webhook_service` | `/webhooks/sumsub` **mounted** | Unique dedup key | — | As above | **E / F** | Retire with the above |

### 3.8 Matrix totals

| Class | Count | Tables | Outcome |
|---|---|---|---|
| A | 25 | `company_address`, `company_bank_account`, `exporter_lifecycle_history`, `exporter_activity`, `follow_up_completion`, `qualification_criterion`, `qualification_result`, `qualification_outcome`, `check_cycle`, `background_check_decision`, `background_check_evidence`, `background_check_proposal`, `background_check_proposal_resolution`, `verification_review`, `screening_review_item`, `sanctions_run`, `sanctions_run_list`, `sanctions_hit`, `sanctions_disposition`, `deal`, `deal_required_document`, `crm_document`, `trade_relationship`, `trade_invoice`, `trade_invoice_outcome` | kept |
| B | 6 | `exporter_profile`, `exporter_gstin`, `exporter_contact`, `payment_term`, `verification_result`, `sanctions_list` | kept, redesigned |
| C | 1 | `deal_buyer_company_map` | merged into `deal_buyer` |
| D | 2 | `deal_buyer` (kept frozen), `qualification_reason_code` (moved to code) | 1 kept |
| E | 15 | `bank_activity_finding` and the 14 legacy tables | removed |

The counts add up to 25 + 6 + 1 + 2 + 15 = **49**, so every table is classified. Kept:
25 + 6 + 1 (`deal_buyer`) = **32**.

---

## 4. Deliverable D — redundancy, normalisation and complexity

### 4.1 Duplicate and overlapping data

| # | Finding | Evidence | Distinct purpose? | Verdict |
|---|---|---|---|---|
| R1 | The relationship manager is held twice: `exporter_profile.relationship_manager` (text) and `relationship_manager_user_id` | In development, 100 companies have only the text, 2 only the id, 0 both. The contract made the text read-only on 7 Oct. `backfill_relationship_managers.py` has not run | No | Redundant after the backfill (O4) |
| R2 | The GST branch address is held twice: `exporter_gstin.address` and `address_id` → `company_address` | 6 text addresses, 0 linked | No | Redundant after conversion (O5) |
| R3 | The verification review is held twice: the legacy columns and the `verification_review` chain | 0 legacy values; "nothing writes them after 0021" | No | Redundant (O3) |
| R4 | `verification_result.evidence_reference` was retired in favour of `evidence_refs` | 0 values, but still in the API response | No | Redundant (O3) |
| R5 | The deal buyer is held twice: `deal_buyer` and `deal.buyer_company_id` | 4 legacy buyers; `deal_service:707` still writes them | Partly: legacy BUYER evidence points at `deal_buyer.id` | Freeze it, and carry its migration outcome on it (O6, O21) |
| R6 | `deal_buyer_company_map` is one-to-one with `deal_buyer` | Primary key = `deal_buyer_id`; 0 rows | No | Fold into `deal_buyer` (O21) |
| R7 | Reason codes exist as a table and as a jsonb snapshot on each outcome | The table changes only by migration; no FK | No | Move the catalogue into code (O20) |
| R8 | Directors and UBOs exist only in legacy `ubo_record`; elsewhere, directors are free text on sanctions runs | `sanctions_screening_service.py:565,780,786`; the tests seed legacy rows | A missing entity | People go in `exporter_contact` (O2) |
| R9 | Three "customer" entities: `exporter_profile`, `onboarding_customers`, `customers.customers` | `database.md` §3 | Legacy / another module | Retire `onboarding_customers` (O1) |
| R10 | Two case systems and two verification logs | — | Legacy | Retire (O1) |
| R11 | Cached gauges on `exporter_profile` | 0 mismatches against the chain heads | **Yes**: lists filter on them, and each has one writer, in the same transaction (architecture §3.8) | Keep |
| R12 | `identity_type` is derived from `pan` and `registration_number` | Migration 0043 had to repair drift | Derived, but filtered on | Keep, plus a CHECK (O8) |
| R13 | `exporter_gstin.state_code` = `left(gstin, 2)` | 0 drift | Derived | Keep, plus a CHECK (O8) |
| R14 | `source` and `created_via` on the profile | Different value sets: business origin versus entry channel | **Yes** | Keep both |
| R15 | `sanctions_run_list.code` and `list_version_date` copy the list | 0 drift | A snapshot | Keep |
| R16 | `follow_up_completion.customer_id` repeats the activity's | 0 mismatches | Index locality | Keep, plus a composite FK (O7) |
| R17 | `exporter_lifecycle_history` and `audit.audit_events` | Bank and sanctions writes record both | **Yes**: business history versus access audit | Keep both |
| R18 | **The sanctions outcome is held in two places:** the run tables, and a `SANCTIONS` `verification_result` that `_sync_company_result` (`sanctions_screening_service.py:830`) writes whenever the company's standing changes | In development, 61 SANCTIONS results: 2 carry the screening service's `sanctions-screening:` reference; 59 were entered directly (by hand or by sample data) | See the note below the table | Keep both tables. Make runs the only source of company and director sanctions results (O19) |
| R19 | `trade_relationship` pairs equal the distinct deal pairs | 35 = 35 in development | Derived at creation and then fixed (the buyer is set once); also anchors past trade | Keep |
| R20 | `auth.users.role` (enum) and `role_id` (FK) | `role_id` is NULL for all 10 users | Transitional, and owned by the platform | Out of the CRM's scope |

**R18 in detail.** The summary result is legitimate. It holds the company-level worst
outcome across all subjects, it is immutable once reviewed, and it is the single
interface that the Clear rule (`background_check_views.py:341,409`), the handover guard
and evidence links read for every check type. The redundancy is the second entry path:
`/verifications` accepts a hand-typed SANCTIONS result that no run supports.

### 4.2 Over-fragmentation: each candidate against a simpler alternative

| Current | Simpler alternative | What the alternative loses | Verdict |
|---|---|---|---|
| `deal_buyer_company_map`, one-to-one with `deal_buyer` | Columns `mapped_company_id`, `match_rule`, `matched_by`, `matched_at`, `mapping_run_id` on `deal_buyer`, each set once | Nothing. Set-once columns give the same "a re-run does nothing" guarantee the primary key gave, and the map is empty, so no data moves | **Merge** (O21) |
| The `qualification_reason_code` table | A catalogue in `domain/` (code, label, requires_note, active) | Editing codes without a deploy, which nothing does today: changes already ship as migrations | **Move into code** (O20) |
| A new `company_person` table (the first-pass proposal) | Role flags and person fields on `exporter_contact` | A separate permission boundary, which field-level masking (`masking.py`) already provides. With one table, a person who is both contact and director stays one row | **Extend contacts** (O2) |
| `follow_up_completion` | Completion columns on `exporter_activity` | Append-only activities. The service's docstring and architecture §9.3 forbid exactly this | Keep separate |
| A completion as another `exporter_activity` row, with `completes_activity_id` | — | It keeps append-only, but adds three sparse columns to every activity and mixes notes with outcomes. No simpler than a one-to-one table | Keep separate |
| `background_check_proposal_resolution` | Resolution columns on the proposal | Proposal immutability; it also adds a deferrable proposal ↔ decision FK cycle | Keep separate |
| `sanctions_run` stored as a `verification_result` row | Run columns map onto result columns | A run's outcome changes as hits are decided, but a result is frozen once reviewed. One company result summarises many runs. UBO would need adding to the entity enum, and every run would carry the result triggers | Keep separate |
| `trade_relationship` folded into `trade_invoice` (seller and buyer columns; pairs computed) | — | It re-keys `/trade-relationships/{id}`, its invoice routes and the frontend. It loses past-trade pairs without invoices, and the natural home for relationship-level attributes | Keep |
| Four versioned configuration tables as one generic table | — | Type-specific CHECKs and typed FKs | Keep; standardise versioning (O9) |
| Five decision chains as one generic table | — | Composite self-FKs, move CHECKs, maker-checker FKs | Keep |
| The evidence shapes as one table | — | Different subjects, actors and immutability rules | Keep |
| `company_address` merged into the GSTIN | — | Addresses that are not branches | Keep |

### 4.3 Normalisation and integrity

- **Functional dependencies.** The only non-key dependencies are the derived columns in
  R11–R13 and R15. All are intentional, and each gets a guard rather than a redesign.
  Mutable entities hold only their own attributes. Facts that change over time live in
  append-only children.
- **Identity.** `exporter_profile` has two uuid keys. `id` is the surrogate primary key,
  and nothing references it. `customer_id` is unique and is the target of 22 FKs.
  Promoting `customer_id` to primary key (O16) would remove a known trap
  (`database.md` §3), but it needs a base class other than `AnerModel` and is not worth
  doing on its own.
- **People get real integrity.** Today, `sanctions_run.subject_reference` points at
  legacy `ubo_record`, but only in code. After O2 it is a composite FK,
  `(subject_reference, company_id)` → `exporter_contact (id, customer_id)`, so a run
  cannot name another company's person.
- **Uniqueness that is enforced:**
  - PAN, globally;
  - registration number, per country and normalised;
  - GSTIN, per company (deliberately not globally);
  - one primary contact;
  - one default address per type;
  - one primary bank account per currency;
  - one current version per configuration code.
- **Uniqueness that is not enforced:** `deal.reference` (O18).
- **Deletion.** Every CRM FK is `RESTRICT`, except `deal_buyer.deal_id` (`CASCADE`;
  deals are never deleted). Append-only tables refuse `DELETE`, and so do four mutable
  ones. After O2, `exporter_contact` does too, because runs and results reference
  people. Right-to-erasure would need an anonymisation design, which is out of scope.
- **Database enforcement still missing:** [inventory.md §7.1](inventory.md) S1–S5 and
  S9 (O7, O9).
- **Identity mixed with workflow state.** `company_bank_account` keeps its approval
  workflow on the row. That is acceptable: the history records each step, CHECKs keep
  the states coherent, and a replacement is a new row. The profile's gauge caches are
  by design (R11).

### 4.4 Table-count analysis

| | Count | Tables |
|---|---|---|
| Current canonical (`onboarding`) | **49** | 35 CRM + 14 legacy |
| Kept, must remain separate | **32** | §3.1–§3.6, except the 3 below (`deal_buyer` is kept, frozen) |
| Merged into another table | 1 | `deal_buyer_company_map` → `deal_buyer` (O21) |
| Moved into code | 1 | `qualification_reason_code` (O20) |
| Dropped as unused | 1 | `bank_activity_finding` (O10) |
| Retired as legacy | 14 | §3.7 (O1, after O2) |
| New | **0** | People go in `exporter_contact` (O2) |
| Optional, later | −1 | `deal_buyer` (O15), once no environment needs it |

| Scenario | Final count | Assumptions |
|---|---|---|
| Today | 49 | — |
| **Recommended** | **32** | 49 − 14 − 1 − 1 − 1 |
| Recommended, with the legacy system kept (if Q1 says keep) | 46 | Only the three reductions inside the CRM |
| Recommended, plus the optional `deal_buyer` retirement | **31** | O15, after the buyer migration has run everywhere and one release has passed |

### 4.5 Optimisation opportunity register

Ranked by correctness first, then by how much it meaningfully reduces, then by
migration risk.

| Id | Opportunity | Existing tables | Proposed design | Expected benefit | Risks | Confidence | Dependencies |
|---|---|---|---|---|---|---|---|
| **O7** | Close the integrity gaps | `background_check_evidence`, `exporter_lifecycle_history`, `sanctions_run`, `verification_result`, `sanctions_hit`, `follow_up_completion` | FK on `verification_review_id`; FK on `history.deal_id`; composite cycle FKs on runs and results; FK `(run_id, list_code)` → run lists; composite FK from completion to activity (needs `UNIQUE (id, customer_id)` on activity) | The database refuses what today only the services refuse | Rows that violate a rule in an environment not yet seen. Add the constraint `NOT VALID`, report, then `VALIDATE` (the 0042 precedent) | High | — |
| **O8** | Guard derived columns | `exporter_profile`, `exporter_gstin` | CHECK that `identity_type` follows its rule; CHECK `state_code = left(gstin, 2)` | The drift that 0043 repaired cannot recur | Violating rows; check first | High | — |
| **O9** | One versioning pattern | `payment_term`, `sanctions_list` | A set-once trigger on every column except `is_current`, `active` and `updated_at` | A deal or run always shows the version it used | The services already write new versions | High | — |
| **O11** | Make the ORM describe the schema | Entity files | Declare the 12 CHECKs and the defaults (the map primary-key fix becomes moot after O21); extend the contract test to cover PKs and CHECKs | Future drift is caught | None | High | — |
| **O2** | People: directors and UBOs in `exporter_contact` | `exporter_contact`; legacy `ubo_record` (read) | See the note below the table | UBO and director screening works; group suggestions work; a real FK replaces linkage that exists only in code; no new table | Every reader of contacts must filter on `is_contact`; the new fields must be masked; the field list depends on Q2 | High (need); medium (fields) | Q2 |
| **O19** | One entry path for sanctions results | `verification_result`, `sanctions_run` | `/verifications` refuses a hand-typed `SANCTIONS` result for EXPORTER and DIRECTOR. The screening service becomes the only writer (through `_sync_company_result`). Provider adapters, when they arrive, record runs. Existing results stay | One way to say "sanctions passed", backed by lists and hits | Sample data, and probably UAT, use hand-typed results; needs a decision and a sample-data change | Medium | Q9; O2 |
| **O3** | Drop the superseded result columns | `verification_result` | Drop `reviewed_by`, `review_status`, `evidence_reference` and `trg_verification_result_field_immutability`; remove the legacy 409 path and the API field | One source of truth for reviews | An environment with a legacy verdict that is not in the chain; check first | High | The step 0 check |
| **O21** | Fold the buyer map into `deal_buyer` | `deal_buyer_company_map`, `deal_buyer` | Set-once columns on `deal_buyer`; `migrate_deal_buyers.py` writes them; drop the map | −1 table, same guarantees | The command and its 32 safety tests change. This must land **before** the buyer migration runs anywhere; otherwise copy the map rows across one-to-one first | High | Step 0 shows the map empty, or the rows are copied |
| **O20** | Reason codes into code | `qualification_reason_code` | `domain/qualification_reason_codes.py`, holding the same 9 codes with their active flags; the route serves it; drop the table | −1 table, no behaviour change | A code missing from the catalogue would show no label, so test that every code in any `reason_codes` array is in the catalogue | High | — |
| **O10** | Drop the bank placeholder | `bank_activity_finding` | Drop the table, the service method and the route; the panel shows its "no feed connected" text from the client | −1 table, −1 route | If a feed is imminent, it would come back | High | Q3 |
| **O6** | Freeze `deal_buyer` | `deal_buyer` | A trigger that refuses INSERT, and refuses UPDATE except a NULL → value change on the O21 columns; sample data moves to buyer companies (the existing R-25 plan) | The legacy buyer stops growing | Must follow the buyer migration in every environment | High | The buyer migration |
| **O1** | Retire the legacy system | 14 tables, 21 enums, 9 routes, the workflow, 23 test files, the KYB seed | Unmount → wait one release → archive → drop | −14 tables, −21 enums; three duplicate concepts gone | An unknown external caller; reverses A6 | High (technical) | O2; Q1 |
| **O4** | Retire the RM text | `exporter_profile` | Run the backfill in every environment; archive unmatched text to history; drop the column | One owner field | Unmatched names need a decision | High | Q4 |
| **O5** | Retire the GST text address | `exporter_gstin` | Convert each to a `company_address` row; link it; drop the column | One address model | Free text needs a mapping | Medium | Q5 |
| **O18** | A rule for deal references | `deal` | `UNIQUE (company_id, reference)`, or globally unique | Duplicates refused | Existing duplicates (0 in development) | — | Q6 |
| **O15** | Retire `deal_buyer` (optional, later) | `deal_buyer` | Archive it. `decision_evidence` and `compliance_inputs` stop reading it: results reach companies through `subject_company_id`, and the timeline union reads the creation history row instead | −1 table | Legacy BUYER `entity_reference` values would then point at the archive | Medium | O6, O21, the buyer migration in every environment, and one release |
| O12 | Align model base classes with triggers | 5 tables | `AppendOnlyModel`; drop `updated_at` | Cosmetic | A migration with no behaviour change | Low value | Only when those tables are touched anyway |
| O13 / O14 | Merge the follow-up and proposal one-to-one pairs | 2 | Set-once columns | −1 each | §4.2 | **Rejected** | — |
| O16 | `customer_id` as the profile's primary key | 1 | Drop `id` | Removes the dual-key trap | Needs a custom base class | Low value now | — |
| O22 | Store `sanctions_run` as a `verification_result` | 2 | — | −1 | §4.2 | **Rejected** | — |
| O23 | Fold `trade_relationship` into invoices | 2 | — | −1 | §4.2 | **Rejected** | — |
| **O24** | Squash the CRM's migrations into one baseline file | The CRM's revision files (56 today), interleaved with other modules' revisions in one shared chain | **Deferred to the separation.** One revision, `baseline_0001`, for the schemas the CRM keeps: guard, any roles, the schema DDL, privileges, seed rows. Existing environments are stamped onto it ([migration-plan.md](migration-plan.md) step 17) | One file is the schema's definition, and fresh installs run one revision | Done now, it would need either a whole-chain rewrite or re-parenting 12 non-CRM revisions, most of it thrown away at the separation. No downgrade below the baseline. The start-up `upgrade head` means the stamp must come first | High | The separation; every refinement step applied everywhere |

**O2 in detail.** Add to `exporter_contact`:

- role flags: `is_contact` (default true), `is_director`, `is_ubo`;
- person fields: `date_of_birth`, `nationality`, `residence_country`, `din`,
  `ownership_pct`, `control_type`, `identification_encrypted`, `identification_last4`;
- CHECKs: at least one role is set; a primary contact must have `is_contact`;
  `ownership_pct` only for a UBO;
- `UNIQUE (id, customer_id)`, and refuse DELETE.

Copy the `ubo_record` rows across **keeping their ids**, then add a composite FK from
`sanctions_run (subject_reference, company_id)`.

---

## 5. The 32 tables that stay, and why

| Group | Tables | Why |
|---|---|---|
| Company identity and satellites | `exporter_profile`, `exporter_gstin`, `company_address`, `exporter_contact` (people), `company_bank_account`, `payment_term` | Independent lifecycles, each with its own uniqueness rules. Bank accounts are an encryption and permission boundary |
| History and engagement | `exporter_lifecycle_history`, `exporter_activity`, `follow_up_completion` | Append-only logs. A completion is a separate fact with its own actor |
| Decision chains | `qualification_outcome`, `background_check_decision`, `verification_review`, `trade_invoice_outcome`, `sanctions_disposition` | Each is a line, not a tree, enforced in SQL with typed parents |
| Maker-checker | `background_check_proposal`, `background_check_proposal_resolution` | Composite FKs pin the approver's identity |
| Evidence and results | `qualification_result`, `verification_result`, `screening_review_item`, `sanctions_run`, `sanctions_run_list`, `sanctions_hit`, `background_check_evidence`, `check_cycle` | Different subjects, actors and immutability rules |
| Versioned configuration | `qualification_criterion`, `deal_required_document`, `sanctions_list` | Admin screens, typed CHECKs and typed FKs |
| Commerce | `deal`, `deal_buyer` (frozen legacy), `crm_document`, `trade_relationship`, `trade_invoice` | Distinct entities with freezes the database enforces |

The groups hold 6 + 3 + 5 + 2 + 8 + 3 + 5 = **32** tables.

---

## 6. Business clarifications required

| # | Question | Blocks |
|---|---|---|
| Q1 | Is the legacy onboarding-request, case, identity-provider and KYB system retired? A yes reverses `migration-register.md` §3 and assumption A6. Does anything call `/onboarding/register`, `/onboarding/cases…`, `/onboarding/{id}/sdk-token`, `/onboarding/{id}/status` or `/onboarding/webhooks/sumsub`? | O1 |
| Q2 | People: which fields are required for directors and UBOs (date of birth, nationality, DIN, ownership %, control type, identification)? Who sees them unmasked: the existing `view_full_tax_id` holders, or a new permission? | O2 |
| Q3 | Is a bank-monitoring feed planned? If not, the placeholder goes | O10 |
| Q4 | The RM free text: after the backfill, what happens to names that match no one? Archive them to history, assign them by hand, or discard them? | O4 |
| Q5 | The GST free-text address: convert it automatically (the whole text as line 1), or have a person do it? Which address type? | O5 |
| Q6 | Must a deal reference be unique, per seller or globally? | O18 |
| Q7 | Which environments hold real data (D-17)? Has the buyer migration or the RM backfill run on any of them? | O3–O6, O21 |
| Q8 | Do you want Option 2-style merges? The audit recommends against them (§4.2) | O13, O14, O22, O23 |
| Q9 | May a person still record a company's or a director's sanctions result by hand, with no structured run behind it? | O19 |
| Q10 | ~~Squash scope~~ **Answered 13 Oct:** no squash now; refine through ordinary migrations; squash the CRM's migrations once, at the separation | O24 |

**Answers (14 October 2026).** Scope: only CRM files change. The old system and every
non-CRM file stay untouched, even though the CRM does not need them.

| # | Answer |
|---|---|
| Q1 | Out of scope: the old system is not retired by this programme; the CRM only stops reading `ubo_record` |
| Q2 | Name and role required; every other person field optional. `view_full_tax_id` reveals them; no new permission |
| Q3 | No bank feed is planned: drop the placeholder |
| Q4 | Discard the RM names that match no user |
| Q5 | Convert automatically, address type `CORRESPONDENCE` |
| Q6 | Unique per seller |
| Q7 | `aner_settlement` only; neither the buyer migration nor the RM backfill has run |
| Q8 | Not asked again: no merges are proposed |
| Q9 | Keep both paths: hand-entered sanctions results stay allowed |
| Q10 | As above: squash at the separation |

---

## 7. Not verified

- **Production, and every database not on this server.** Row counts, legacy usage,
  O7/O8 violations, and whether the data commands have run are all unknown there.
  [migration-plan.md §2](migration-plan.md) gives read-only queries that check them.
- **External callers of the legacy routes.** Access logs would show them.
- **Performance.** No query plans or timings were taken.
- **The downgrade paths** of 0044–0053.
- **Fresh install versus upgrade equivalence,** beyond three identical schema dumps.
- **`e9-postgres`** (port 5556).
