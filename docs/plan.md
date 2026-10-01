# ANER Exporter CRM — Implementation Plan

| | |
|---|---|
| Date | 1 October 2026 |
| Repository state audited | `main` @ `632a824` ("Fix and Hardening"), clean working tree, one Alembic head `onboarding_0022_integrity` |
| Business source of truth | `docs/plan.md` — *ANER Exporter CRM — Post-Demo Change Plan*, 30 September 2026 (decisions A–K; DPDP and RXIL open) |
| Target picture used alongside it | `crm-state-model-v2.png` ("One company, several gauges", decisions A–K recorded 30 September 2026) |
| What this file is | An audit of the code against that plan, and the engineering plan that follows from it. No code, migration or behaviour was changed |
| Decisions recorded | 1 October 2026: all blocking and design questions answered, see §19.0 (it overrides earlier text where they differ) |
| Where it lives | Repository root. `docs/plan.md` is the source document and is untracked, so it was not overwritten |

Status words used for claims: **VERIFIED** (read in code), **NOT VERIFIED** (the claim is contradicted by the code), **PARTIALLY IMPLEMENTED**, **NOT IMPLEMENTED**, **UNKNOWN / NEEDS VERIFICATION** (cannot be settled from the repository). File references are relative to the repository root.

---

## 1. Executive Summary

The prototype is a well-layered extension of one module (`backend/app/modules/onboarding`) with database-enforced append-only records, server-side masking, and "the rules as data" served to the screen. It can take the post-demo changes **incrementally**; none of them needs a rewrite. The two places the current model resists the target are the **deal buyer** (a separate per-deal row, `deal_buyer`, that the rest of the compliance code is keyed to) and the **append-only triggers**, which rule out "update the old rows" migrations. Every compliance and history change therefore has to be additive: new columns, mapping tables, and read rules for legacy rows.

What the audit found that the source plan does not already say:

1. **There is no maker-checker switch.** `background_check_service.py:338` says "there is no second approver in the prototype". No setting in `app/platform/configuration/config.py` or `backend/.env` controls it. The only maker-checker code in the checkout belongs to payment transactions (`compliance.ComplianceApproval`) and a legacy case-engine stand-in in `cases`, which the module rule keeps closed. Decision A is new work (Phase 3).
2. **The buyer is not snapshotted at handover.** The handover writes only `document_ids` into the history row (`deal_service.py:360-371`). The buyer exists only as the live `deal_buyer` row, protected by the service and not the database, plus an in-memory event with no receiver or outbox. Once buyers become shared company records, their details will change after handover, so a persisted snapshot has to exist **before** the buyer migration (task P2-7).
3. **GST registrations are hard-deleted on edit.** `ExporterProfile.gstin_rows` uses `cascade="all, delete-orphan"` (`exporter_profile.py:154-158`) and `update_profile` replaces the whole list. Branch flags and a deal→branch foreign key cannot exist until GSTIN edits become add/deactivate operations.
4. **Qualification "currency" is a free-text `unit` ("USD"), and the server never compares values against thresholds**; a person records PASS/FAIL. Rupee thresholds are therefore a data change. However, **any new criterion version stops the existing results for that criterion from counting** (`qualification_service.py:539-555`), so changing the revenue threshold resets that criterion for every lead not yet decided.
5. **Clear today does not require any verification at all.** The source says "passing any one check is enough"; in code, the eight screening answers plus one pinned evidence id satisfy `CLEAR_POLICY`, and a `FAILED` verification does not block. Decision B is a bigger behaviour change than the source implies.
6. **The RM cannot search by PAN or GSTIN.** Exact identifier search is refused to masked roles (`exporter_router.py:99-103`, decision 12). The target's "RM picks the buyer by PAN, GSTIN, …" collides with that rule and with the still-open duplicate-PAN disclosure item. It has to be decided before buyer search is built.
7. **Consequence 5.1.1 is not automatic.** A `CLEAR` gauge is never recomputed when a new `FAILED` sanctions result arrives. "A company failing sanctions as a buyer also has its seller deals blocked" only happens if the handover guard reads sanctions/AML results for **both** parties, or compliance reopens the company.
8. **Cycles, `rules_version` and expiry cannot be backfilled into existing rows.** Decisions, screening rows and history rows refuse `UPDATE` at the database. Legacy rows must be read through explicit rules (a `NULL` cycle means cycle 1; a `NULL` expiry means decided + 1 year).
9. **The 4A↔4B compliance-inputs seam is contractually "frozen"** (`domain/compliance_inputs.py`, with a contract test). Cycles (B), company-level buyer checks (D) and required check types all change it. It should be revised **once**, deliberately (P0-2), not three times.
10. **A separate "trade history module" is not possible under the current import-linter contracts**: other modules may import only `onboarding`'s public facade. Trade history has to live inside `onboarding`, or the module rule needs a written exception.
11. **Removing the website breaks CSV import for existing files**, because the importer requires the header to equal `TEMPLATE_COLUMNS` exactly (`company_import_service.py:262`).
12. **Sumsub is not a verification adapter.** `app/integrations/identity_providers/sumsub/client.py` (96 lines) serves the legacy applicant/SDK flow. The CRM route accepts `provider="manual"` only (D7), and the `VerificationAdapter` protocol is synchronous.
13. **Existing data is sample/UAT data only** (decision 1; "no real customer data" rule). Migration risk is about correctness and repeatability, not volume, which makes the buyer migration tractable with human review of duplicates.

**The plan keeps the source's "Do not do" list (§8):** the journey stays `LEAD → PROSPECT → CUSTOMER` (buyer-only status is a separate `pipeline_status`); the RM never approves compliance (P3-1b); flags belong to a company or a branch, with no "exporter/buyer/both" types; `OPERATIONS` is renamed only in the UI (P1-5); verification results are never overwritten (buyer checks are re-keyed with a new column, P4-5); buyers become Leads only when someone onboards them (P4-9); no real customer data before encryption and DPDP (P7-7).

**Keystone:** company unification (Phase 4). **Critical path:** P0 decisions → P2-7 (persist the handover snapshot) → P4 identity and `pipeline_status` → buyer link and company-level checks → buyer migration (checkpoint) → company-level handover guard → trade history. Phases 1–3 run alongside it; they do not gate P4's additive schema work.

---

## 2. Current Architecture

### 2.1 Shape

| Layer | What is there | Evidence |
|---|---|---|
| Backend | FastAPI, async SQLAlchemy, PostgreSQL, Alembic. 1,009 Python files under `backend/app`; the CRM is `app/modules/onboarding` (~38k lines excluding tests) | `docs/architecture.md` §2, file listing |
| CRM layering inside `onboarding` | `api/` (routers + Pydantic schemas incl. `masking.py`) → `application/` (one service per concern, one transaction per operation) → `domain/` (entities, enums, pure policies, view dataclasses, ports) → `infrastructure/` (repositories, adapters, storage, RXIL package parser) | directory tree |
| Legacy in the same module | `onboarding_request` 18-state machine, Temporal workflow, `KybVendorResult`, legacy Sumsub provider. Not built on; `TEMPORAL_ENABLED=false` | `architecture.md` §2, `config.py:154` |
| Frontend | Vite, React 18, TS, TanStack Query, Tailwind. CRM screens in `frontend/src/modules/onboarding`, Settings in `frontend/src/modules/settings` | tree |
| Generated contract | `frontend/openapi.json` and `frontend/src/lib/api/schema.ts`, guarded by `backend/tests/contract/test_openapi_artifact_is_current.py` | file present |
| Module rule | Only `onboarding` connects things; `kyb`, `cases`, `customers`, `compliance` are not edited (one exception, EX-001). import-linter: 19 contracts, including "onboarding internals are private" | `docs/module-rule-exceptions.md`, `backend/importlinter.ini:296-323` |
| ORM/schema drift guard | `backend/tests/contract/test_orm_matches_the_onboarding_schema.py` — every migration needs matching ORM declarations | file present |
| Route authorisation guard | `onboarding/tests/integration/test_route_authorization.py` — every route needs a row | file present |

### 2.2 CRM routes (prefix `/api/v1/onboarding`)

| Area | Routes | Roles (write / read) |
|---|---|---|
| Company | `POST/GET /exporters`, `GET/PATCH /exporters/{id}`, `POST /exporters/{id}/marker` | Staff / Staff+DEVELOPER (masked) |
| Intake | `POST /rxil/company-intake` (ADMIN), `GET /imports/companies/template`, `POST /imports/companies` | ADMIN / Staff |
| Qualification | `GET/POST /qualification/criteria`, `GET/POST /qualification/criteria/{key}/versions`, `GET /qualification/reason-codes`, `GET /exporters/{id}/qualification`, `POST …/qualification/results`, `POST …/qualification/outcome` | Criteria ADMIN; results/outcome Staff |
| Conversation, contacts, activities, follow-ups | `engagement_router.py`, `follow_up_router.py` | Staff |
| Deals | `POST/GET /exporters/{id}/deals`, `GET /deals/{id}`, `POST /deals/{id}/transitions`, `PUT /deals/{id}/buyer` | Staff |
| Documents | `/documents/categories`, `/exporters/{id}/documents`, `/deals/{id}/documents`, `/documents/{id}`, `/documents/{id}/download-link`, `/documents/content` | Staff |
| Background check | `GET /exporters/{id}/background-check`, `POST/GET …/background-check/decisions` | Moves per table below; DEVELOPER refused (D8) |
| Verification | `POST /verifications` (provider `manual` only, D7), reads and reviews in `api/router.py` | Record/review COMPLIANCE, ADMIN; read Staff |
| Screening | `GET /exporters/{id}/screening-review`, `PUT …/{item_key}`, `GET …/{item_key}/history`, `GET …/bank-activity` | Decide COMPLIANCE, ADMIN |
| History | `GET /exporters/{id}/history`, `GET /deals/{id}/history` | Staff+DEVELOPER (D8 rows excluded) |

### 2.3 Services, repositories, adapters

- **Services** (all flush-then-commit-once, history row in the same transaction): `ExporterProfileService` (identity, identifiers, marker, search, `promote_to_customer_if_ready`), `QualificationService`, `ConversationService` (seam S1), `DealService` (stages, buyer, handover guard), `DocumentService`/`StorageService`, `BackgroundCheckService` + `BackgroundCheckReader`, `VerificationService`, `ScreeningReviewService`, `ComplianceInputsService` (4A↔4B seam), `HistoryService`, `CompanyImportService`, `PartnerIntakeService`, `CompanyMatcher`.
- **Repositories**: one per aggregate in `infrastructure/repositories/`.
- **Adapters and ports**: `VerificationAdapter` / `BatchVerificationAdapter` (`domain/workflow_dependencies.py:548-627`, **synchronous** `def verify`), `register_adapter`/`get_adapter` registry. Implementations: `ManualEntryAdapter`, `StubRxilAdapter`. A separate `ProviderRegistry` (`infrastructure/registry.py`) holds only mock identity/screening adapters (`ONBOARDING_ENABLED_PROVIDERS`), plus the legacy Sumsub boolean-flag resolver. `StoragePort` (local disk) and `ScannerPort` (pass-through).
- **External integrations present in the tree**: `integrations/identity_providers/{sumsub (legacy, 96-line client), middesk}`, `integrations/kyb/trulioo`, `integrations/sanctions/shared` (no vendor). `SUMSUB_ENABLED`, `MIDDESK_ENABLED` and `TRULIOO_ENABLED` default to `False` (`config.py:232-248`). None is wired to the CRM verification route.

### 2.4 Authorisation

Route gates are `require_role(...)` over the five built-in `UserRole` values (`app/platform/authentication/models.py:14`). The permission catalogue marks the CRM permissions `enforced=False` (`app/platform/authorization/catalog.py:82-123`), so Settings → Roles changes no CRM access. The built-in role display names are data (`catalog.py`: `OPERATIONS → "Operations"`). The catalogue's OPERATIONS description ("masked unless you own the record") is stale; `masking.py` removed that exception.

### 2.5 Quality gates (baseline 29 Sep 2026, `docs/development.md` §9)

Backend 4,570 passed / 7 skipped / 27 xfailed / 0 failed; ruff 16 pre-existing; import-linter 19/0; one head; frontend tsc clean, eslint 0 errors / 2 warnings, **vitest 32 files / 294 tests (re-run in this audit: 294/294 pass)**. The backend suite was **not** re-run in this audit (18–30 minutes); there is no CI (U6).

---

## 3. Current Data Model

### 3.1 Company — `onboarding.exporter_profile` (`domain/entities/exporter_profile.py`)

| Aspect | Today |
|---|---|
| Identity | Business key `customer_id` (UUID, unique); table PK is the inherited `id`. Every child FK points at `customer_id` |
| Fields | `name` (nullable while the unnamed create path exists; blank refused), `country` (ISO-2), `cin` (India-only regex), `pan`, `iec`, `source` (immutable enum), `relationship_manager` (free text) + `relationship_manager_user_id` (never written), `industry`, `export_markets`, `products`, `year_established`, `website`, `date_added` |
| PAN | Nullable; `uq_exporter_profile_pan`; duplicate refused with 409 `DuplicatePanError` naming the holder |
| GSTIN | Child table `exporter_gstin(customer_id, gstin)`; unique per company only; the same GSTIN on two companies is allowed (decision 4 warning). Each GSTIN must embed the company PAN; with no PAN, all GSTINs must embed the same PAN, which is **not** written to `pan`. No state, status, address or flag. Rows are **deleted** when removed from the list |
| Journey | `journey` enum `LEAD/PROSPECT/CUSTOMER`, `NOT NULL DEFAULT 'LEAD'` |
| Marker | `marker` `NONE/PAUSED/ENDED` + `marker_reason` (check constraint) |
| Gauges | `qualification`, `conversation` (+ `conversation_check_back_on`), `background_check` — current values carried on the row |
| Source | `ExporterSource`: MANUAL, SALES, REFERRAL, RXIL, PARTNER, API, BROKER, EVENT, EXISTING_CUSTOMER — mixes *how found* with *channel*. Creation channel is recoverable only from the first history row's `event_metadata.source` (`exporter_profile_service.create_lead`, `company_import.csv`, `partner_intake.rxil`, `sample_data`) |
| Compliance relationship | Only via `background_check` and verification/screening rows keyed by `customer_id` |
| Masking | PAN, GSTIN, IEC, CIN show the last 4 characters to OPERATIONS and DEVELOPER; exact search by them is refused to those roles |
| Foreign companies | Only `country`; no foreign registration number (CIN is India-format); no identity type |

### 3.2 Deal — `onboarding.deal` and `onboarding.deal_buyer`

| Aspect | Today |
|---|---|
| Seller | `deal.company_id` → `exporter_profile.customer_id` (RESTRICT) |
| Buyer | Separate table `deal_buyer`, 1:1 (`uq_deal_buyer_deal_id`, FK CASCADE): `name`, `country` (ISO-2, required), `registration_number`, `tax_id`, `contact_email`, `contact_phone`. Documented as "foreign by definition": no PAN/GSTIN rules apply |
| Buyer checks | `verification_result` rows with `entity_type='BUYER'`, `entity_reference=deal_buyer.id`, `subject_snapshot` (buyer identity at record time). History rows go to the **seller's** timeline with `deal_id` |
| Documents | `crm_document` owned by a company or a deal; category enum (10 values incl. `SHIPPING`, `CUSTOMS_AND_REGULATORY`, `BUYER`); types from `deployments/gitops/reference-data/crm/documents/document-types.yaml` |
| Stages | `OPEN → GATHERING_PAPERWORK → HANDED_OVER`; `OPEN/GATHERING_PAPERWORK → WITHDRAWN` (reason). Terminal freeze: service + trigger `trg_deal_terminal_freeze` (0022) on `stage`, `handed_over_at`, `withdrawal_reason`, `company_id`, `reference` only — **not** on `deal_buyer` |
| Snapshots | History row `details.document_ids` only. **No persisted buyer snapshot** |
| Relationships | None to other deals or to a buyer entity |

### 3.3 Qualification (migration 0017)

| Aspect | Today |
|---|---|
| Criteria | `qualification_criterion`, append-only, one row per `(key, version)`: `kind` (`NUMBER_THRESHOLD`/`YES_NO`/`ALLOWED_VALUES`), `comparison`, `threshold Numeric(20,4)`, **`unit String(32)` free text**, `allowed_values`, `required`, `active`, `created_by` |
| Seed (v1) | revenue ≥ 100,000,000 "USD" (required); years_in_business ≥ 5 (required); export_history (required); export_licence/IEC (required); industry (8 values, optional); geography (IN-AE/US/GB/NL/DE/SG, optional); deal_size ≥ 50,000 "USD" (optional) — `onboarding_0017_qualification.py:92-104` |
| Evaluation | A person records PASS/FAIL/UNKNOWN per criterion with evidence. **The server never compares `observed_value` with `threshold`.** Suggestion = QUALIFIED iff every active required criterion's latest result is PASS **against the current version** |
| Reason codes | `qualification_reason_code` (mutable, `active` flag), 9 seeded, 3 export-specific (`no_export_history`, `no_export_licence`, `geography_not_supported`); inactive codes are refused on new outcomes; no admin route |
| Decisions | `qualification_result` and `qualification_outcome` append-only; outcome chain (`supersedes_outcome_id`), `suggested_outcome`, `result_ids`, `source`, `decided_by_kind`, `decided_by` |

### 3.4 Background check (migration 0015) and its inputs (0006, 0010, 0021)

| Aspect | Today |
|---|---|
| Gauge | `exporter_profile.background_check`: `NOT_STARTED, IN_REVIEW, CLEAR, MORE_INFO, FLAGGED, ON_HOLD` |
| Decisions | `background_check_decision` (append-only): `from_value`, `to_value`, `decided_by`, `decided_by_kind` (always MANUAL), `source` (MANUAL; RXIL reserved), `decided_at`, `reason`, `risk_rating` (CLEAR only), `supersedes_decision_id`, `details`. DB constraints: the nine moves (`ck_background_check_decision_move`), risk only on CLEAR, reason on every move but the start, first-decision rule, chain FK |
| Evidence snapshot | `background_check_evidence` (append-only): per decision, pinned ids of kind `DOCUMENT`, `VERIFICATION_RESULT` (+ review id), `SCREENING_ITEM` |
| Clear logic | `CLEAR_POLICY` (`domain/background_check_views.py:217-233`): risk given; no verification `PENDING`/`REVIEW` without an ACCEPTED/REJECTED review; no placeholder; all catalogue screening items PASSED/EXEMPT; ≥1 pinned evidence id. `FAILED` verification does not block |
| Reopening | `CLEAR → IN_REVIEW` with a reason (COMPLIANCE/ADMIN); no `CLEAR → FLAGGED` |
| Cycles | **None.** The seam returns every EXPORTER verification result ever recorded; screening = latest row per item key |
| `rules_version` | **None.** The policy is code |
| Expiry | **None** on the check. `verification_result.valid_until` exists (provider-supplied) and is unused by Clear |
| Verification results | `verification_result`: `verification_type` (18 values incl. KYB, AML, SANCTIONS, PEP, ADVERSE_MEDIA, GST, IEC, UBO), `entity_type` (EXPORTER, BUYER, DIRECTOR, INVOICE, VESSEL, SHIPMENT), bare `entity_reference`, `provider`, `status` (PENDING/PASSED/FAILED/REVIEW), `risk_level`, `performed_at`, `valid_until`, `raw_result`, `normalized_result`, `evidence_note`, `evidence_refs`, `subject_snapshot`. No delete (0022); outcome frozen once reviewed; evidence/snapshot frozen once set. **`entity_type`/`entity_reference` are not frozen** |
| Reviews | `verification_review` superseding chain (ACCEPTED/REJECTED/ESCALATED) |
| Screening | `screening_review_item` append-only (`trg_screening_review_item_append_only`): `customer_id`, `item_key`, `status` (NEEDS_REVIEW/PASSED/FAILED/EXEMPT), `comment`, `reviewed_by/at`. **No evidence field.** Catalogue of 8 in code (`screening_review_service.py:63-102`), item 1 `website-reviewed` |
| Provenance | `provenance_of(provider)` → `MANUAL`/`STUB`/`PROVIDER`; `is_placeholder` |

### 3.5 History — `onboarding.exporter_lifecycle_history`

Append-only by trigger (`trg_exporter_lifecycle_history_append_only`, `public.prevent_mutation()`). Columns: `customer_id` (**NOT NULL**, FK RESTRICT), `dimension` (journey, qualification, marker, profile, conversation, deal, background_check, verification, screening), `deal_id` (bare), `event_type`, `from_status`, `to_status`, `actor_id`, `reason`, `event_metadata` (`{source: <code path>, …details}`), `created_at`. Rows written in one transaction share a timestamp. Identifiers are stored already masked in profile rows. **No data-provenance fields** (source type/reference/captured-by in the DPDP sense); `event_metadata.source` is the code path.

### 3.6 Users and roles (actual behaviour)

| Role | Behaviour in code |
|---|---|
| ADMIN | All CRM actions, criteria, RXIL intake, users/roles; full identifiers |
| COMPLIANCE | All background-check moves, screening decisions, verification record/review; full identifiers |
| OPERATIONS | Companies, contacts, activities, marker, qualification, conversation, deals, buyers, documents, CSV import; background check **start** and **answer MORE_INFO** only; identifiers masked; exact identifier search refused |
| DEVELOPER | Read-only, masked; no background-check/verification/screening data (D8), including history rows and deal stage moves/blocked reason |
| API_USER | Reaches nothing in the CRM (`test_api_user_reaches_nothing_in_the_crm`) |

---

## 4. Current Workflow

### 4.1 Journey

| Transition | Cause in code |
|---|---|
| (create) → `LEAD` | Every create path (form, CSV, sample data); RXIL intake creates `LEAD` then records a partner `QUALIFIED` outcome |
| `LEAD → PROSPECT` | `QualificationService._write_outcome` when an outcome `QUALIFIED` is recorded (manual or RXIL partner) |
| `PROSPECT → CUSTOMER` | `ExporterProfileService.promote_to_customer_if_ready` (`exporter_profile_service.py:700`), called in the same transaction by `BackgroundCheckService` on `CLEAR` and by `QualificationService` when `QUALIFIED` lands on an already-`CLEAR` company. Company row locked `FOR UPDATE` by both callers; `company.became_customer` announced after commit |
| Backwards | Never. Pausing/ending uses the marker |

### 4.2 Qualification

Who: OPERATIONS, COMPLIANCE, ADMIN record results and outcomes; ADMIN manages criteria. Server rules: PASS/FAIL need evidence; `NOT_QUALIFIED` needs ≥1 active reason code (`other` needs a note); `QUALIFIED` is final (A2); the suggestion is stored beside the decision. Frontend: reasons offered only for `NOT_QUALIFIED` (UAT fix); criteria screen `frontend/src/modules/onboarding/pages/QualificationCriteriaPage.tsx` edits label, threshold, unit, allowed values, required, active as a new version.

### 4.3 Background check

Start: OPERATIONS/COMPLIANCE/ADMIN. Record CLEAR/MORE_INFO/FLAGGED/ON_HOLD/reassess/reopen: COMPLIANCE/ADMIN. **One user decides; no maker-checker.** Each move: lock company `FOR UPDATE` → validate premise (`expected_current`, 409 if stale), move, role, reason, risk → read inputs through the seam → evaluate `CLEAR_POLICY` → insert decision + evidence snapshot → history row → promotion (CLEAR) → commit → announce. Reopen = `CLEAR → IN_REVIEW`. Clear works as in §3.4.

### 4.4 Handover — the exact guard

Location: `DealService.transition_stage` (`backend/app/modules/onboarding/application/deal_service.py:296-397`) and `DealService._handover_blocked_reason` (`:535-588`). Conditions, in order:

| # | Condition | Response |
|---|---|---|
| 1 | Deal exists | 404 |
| 2 | Deal not terminal | 409 `DealTerminalError` |
| 3 | Move in table — only `GATHERING_PAPERWORK → HANDED_OVER` reaches handover | 422 |
| 4 | No reason supplied (reasons belong to withdrawal only) | 422 |
| 5 | A buyer row exists | 422 `DealBuyerRequiredError` |
| 6 | Company `journey == CUSTOMER` | 409 `DealHandoverBlockedError`, all unmet joined by "; " |
| 7 | Company `background_check == CLEAR` (from the company column) | same |
| — | Company row share-locked (`FOR SHARE`) for the transaction (D10) | — |

**Not checked:** documents (none required; scan status ignored in the snapshot), buyer checks of any kind, seller sanctions/AML results, check age/expiry, GST branch, trade history. `_to_view` runs the same guard without the lock to hide the move and serve `handover_blocked_reason`.

---

## 5. Audit Findings

### 5.1 "Verify in code before starting" (source §9)

| # | Item | Status | Evidence and consequence |
|---|---|---|---|
| 1 | Maker-checker config switch exists | **NOT IMPLEMENTED** (claim NOT VERIFIED) | `background_check_service.py:338` "there is no second approver in the prototype (decision 5)"; no key in `config.py`, `.env`, `.env.example`; the only maker-checker code is `compliance.ComplianceApproval` (transaction approvals) and the `cases` S4T2 stand-in (`case_lifecycle_service.py:97-105`), neither connected to the CRM (assumption A6) |
| 2 | Qualification criteria support a currency / rupee thresholds | **PARTIALLY IMPLEMENTED** | `unit` is free text (`qualification.py`, "USD" seeded); no currency type, validation, formatting or conversion. Because the server never evaluates thresholds, "INR" in `unit` plus a new `threshold` is enough for behaviour. Threshold precision `Numeric(20,4)` holds rupee values. A new version de-counts existing results for that criterion |
| 3 | Admin can change "required" from the UI | **VERIFIED** | `QualificationCriteriaPage.tsx:258-265` checkbox → `POST /qualification/criteria/{key}/versions` (ADMIN, `qualification_router.py:112-133`) |
| 4 | How verification results and screening items are stored | **VERIFIED** | §3.4. For cycles: results have no cycle; screening rows are append-only and cannot be backfilled; decisions cannot be updated. For `rules_version`: nothing stored; the catalogue and policy live in code |
| 5 | How buyer fields and buyer checks are stored | **VERIFIED** | `deal_buyer` 1:1 table; checks are `verification_result(entity_type=BUYER, entity_reference=deal_buyer.id, subject_snapshot)`; buyer documents are deal documents; buyer history rows sit on the seller timeline with `deal_id` |
| 6 | How GSTINs are stored | **VERIFIED** | `exporter_gstin(customer_id, gstin)`, unique per company, delete-orphan cascade, no state/status/flag |
| 7 | Where the handover guard lives | **VERIFIED** | `deal_service.py:535` `_handover_blocked_reason`, called with `lock=True` at `:345` and unlocked at `:595` |
| 8 | Where `EvidenceList` is used and what it expects | **VERIFIED** | `frontend/src/modules/onboarding/components/EvidenceList.tsx`; props `{ note: string \| null; refs: {type, ref}[] }`; handles `document` (download via `useDownloadDocument` + `fetchDocumentBlob`), `url` (http(s) only), unknown types shown raw. Used in `VerificationResultRow.tsx:75` and `BuyerChecks.tsx:129`. Background-check decisions show counts only (`DecisionHistory.tsx:30-53`); screening items have no evidence to show |
| 9a | UAT fix: background-check save 422 | **VERIFIED** | Body encoded once; `api/background-check.test.ts:33`, `lib/api/client.test.ts:70` (commit 632a824) |
| 9b | UAT fix: header updates to Customer | **VERIFIED** | Query invalidation, `hooks/journey-invalidation.test.tsx:43,59` |
| 9c | UAT fix: session drops | **PARTIALLY IMPLEMENTED** | Single-flight refresh, Web Locks, server `FOR UPDATE` + 499 (`client.test.ts:87-180`, `app/api/rest/auth/tests/test_refresh_concurrency.py`). Residual: bursts of reloads on the production build still sign out ~30% (`docs/open-items.md` §1.2) |
| 9d | UAT fix: history rows | **VERIFIED** | `HistoryTimeline.test.tsx:73,92,116` |
| 9e | UAT fix: names instead of ids | **VERIFIED** with two known residuals | `api/actor_names.py`, `test_actor_names.py`; the criteria settings screen (`created_by`) and the retired pending-activities route still show ids (`open-items.md` §2) |
| 9f | UAT fix: Qualified form reasons | **VERIFIED** | `QualificationPanel.tsx` offers reasons only for `NOT_QUALIFIED`; `ExporterDetailPage.test.tsx` ("asks only for a note when recording Qualified") |

Frontend tests re-run in this audit: 32 files / 294 tests pass. The backend suite was not re-run.

### 5.2 Significant discrepancies ("what we think exists" vs "what exists")

**F-01 — Maker-checker (R6, decision A)**
- CURRENT CODE: one COMPLIANCE/ADMIN user records every move; no switch, no second user, no pending state.
- TARGET: record → awaiting approval → a different COMPLIANCE/ADMIN approves; RM never approves.
- GAP: the entire mechanism.
- IMPACT: new table(s), service path, API, UI; every existing test that clears a company as one user.
- DEPENDENCY: P0-5 (two-user test fixtures); decision on which moves need approval (IQ-1).
- RECOMMENDED TASK: P3-1a–d.

**F-02 — Buyer snapshot at handover**
- CURRENT CODE: history row carries `document_ids` only; the buyer lives in `deal_buyer` (service refuses edits on terminal deals, DB does not) and in an in-memory event.
- TARGET: "Keep the frozen buyer snapshot at handover."
- GAP: no persisted snapshot to keep.
- IMPACT: once `buyer_company_id` points at a mutable company, what the lending team was given can no longer be reconstructed.
- DEPENDENCY: must land before P4-4/P4-6.
- RECOMMENDED TASK: P2-7.

**F-03 — GST branches (R3, decision H)**
- CURRENT CODE: `exporter_gstin` rows are hard-deleted when the list is edited; unique per company only; no state/status/flag; GSTIN-only companies with `pan IS NULL` are allowed; the same GSTIN on two companies is allowed.
- TARGET: `gst_registration` with global GSTIN uniqueness, state, status, address, flag; deals reference the invoicing branch; a flagged branch blocks its deals.
- GAP: deletion semantics, columns, uniqueness, deal FK, guard.
- IMPACT: global uniqueness cannot be added while duplicates exist; a deal FK would make GSTIN edits fail with RESTRICT.
- DEPENDENCY: duplicate-resolution policy (IQ-9); branch-blocking confirmation (BQ-6).
- RECOMMENDED TASK: P6-1–P6-7 (evolve `exporter_gstin` in place rather than a new table; see P6-1).

**F-04 — Currency and criteria versions (R5, decision F)**
- CURRENT CODE: `unit` free text; thresholds not evaluated by the server; a new version de-counts existing results for that key.
- TARGET: rupee thresholds, currency-aware thresholds for later foreign use (F).
- GAP: no currency semantics; a silent reset of in-flight leads on version change.
- IMPACT: after P1-1, every undecided lead shows "NOT_QUALIFIED suggested" until the changed criteria are re-recorded.
- DEPENDENCY: INR values (BQ-1).
- RECOMMENDED TASK: P1-1 (data), P1-3 (display), and optionally a structured `currency` column later with F.

**F-05 — Clear requirements (decision B)**
- CURRENT CODE: no verification type is required; screening answers + one evidence id suffice.
- TARGET: KYB, AML and sanctions passed in the current cycle, plus existing rules.
- GAP: a new policy dimension, a cycle concept, and a served list of required types (the UI's `COMPANY_CHECK_TYPES` is a client-side constant, `verification-labels.ts:23`).
- IMPACT: sample data and every CLEAR test need KYB/AML/SANCTIONS results; manual results are acceptable until providers exist.
- DEPENDENCY: P2-3 (cycles), definition of "passed" (IQ-2).
- RECOMMENDED TASK: P3-2.

**F-06 — Evidence per check (R12)**
- CURRENT CODE: each verification result already shows its evidence through `EvidenceList`; decisions show counts; screening items store only a `comment`.
- TARGET: every check with result, who, when, provenance and evidence.
- GAP: decision-level evidence resolution (ids → readable items) and screening-item evidence.
- IMPACT: new read shape on decisions; new nullable column on an append-only table.
- DEPENDENCY: none.
- RECOMMENDED TASK: P2-1a–c.

**F-07 — Automated/manual labels (R13)**
- CURRENT CODE: `provenanceLabel` shows "Manual (person)", "RXIL stub, not RXIL" or the provider name on each result.
- TARGET: labels plus filters All/Automated/Manual/Flagged.
- GAP: filters only. No `PROVIDER` result can exist today (route manual-only, D7), so "Automated" is empty until P7.
- IMPACT: frontend only.
- DEPENDENCY: none.
- RECOMMENDED TASK: P2-2.

**F-08 — Re-KYC / Re-KYB (R14, decision E)**
- CURRENT CODE: only "reopen"; no cycle grouping; placeholders block `CLEAR` forever.
- TARGET: a new cycle per Re-KYC/Re-KYB; previous cycles visible; Clear valid 1 year.
- GAP: the cycle model, seam change, UI.
- IMPACT: legacy rows cannot be updated, so they belong to "cycle 1" by read rule; scoping the Clear rule to the current cycle also resolves the placeholder-blocks-forever item (source §1.5 item 3) for new cycles.
- DEPENDENCY: P0-2 (seam v2), cycle semantics (IQ-3).
- RECOMMENDED TASK: P2-3a–d.

**F-09 — Website removal (R11)**
- CURRENT CODE: column, create/edit forms, CSV template (exact header), RXIL package field, http(s) validation, screening item `website-reviewed`.
- TARGET: removed; screening 8 → 7; old Clears keep their 8-item evidence (K).
- GAP: removal plus a CSV transition; `rules_version` on decisions.
- IMPACT: existing CSV files stop importing unless the old header is still accepted.
- DEPENDENCY: rules_version column (bundled).
- RECOMMENDED TASK: P2-4a–b.

**F-10 — Buyer as a company (R1, decisions C, D, 9 rewrite)**
- CURRENT CODE: `deal_buyer` per deal; checks keyed by `deal_buyer.id`; buyer masking mirrors company masking; buyer is "foreign by definition" (no PAN/GSTIN).
- TARGET: `deal.buyer_company_id`; buyer-only companies `NOT_IN_PIPELINE`; full checks on the company.
- GAP: identity model, search/create, FK, migration, seam, guard, UI.
- IMPACT: ~10 backend test files and 3 frontend test files reference the buyer model; the seam contract test changes.
- DEPENDENCY: P2-7, BQ-2 (identifier disclosure), BQ-3 (5.1.1), IQ-6 (`source` for buyer-created companies).
- RECOMMENDED TASK: P4-1–P4-11.

**F-11 — RM search by identifier**
- CURRENT CODE: `IdentifierSearchNotPermittedError` for OPERATIONS/DEVELOPER on `pan`/`gstin`/`iec` search.
- TARGET: the RM finds a buyer by PAN, GSTIN, country + registration number, or name.
- GAP: a policy conflict with decision 12 and the open duplicate-PAN disclosure item.
- IMPACT: without a decision, P4-3 cannot be specified.
- DEPENDENCY: BQ-2.
- RECOMMENDED TASK: P4-3 (a server-side "match or create" that returns a match without revealing identifiers is one option).

**F-12 — Consequence 5.1.1 is not automatic**
- CURRENT CODE: the guard reads the gauge, and a new `FAILED` result does not move a `CLEAR` gauge.
- TARGET: a company failing sanctions as a buyer also blocks its seller deals.
- GAP: the guard must read the seller's own latest sanctions/AML results, or compliance must reopen.
- IMPACT: this defines what "company-level compliance" means in the guard.
- DEPENDENCY: BQ-3.
- RECOMMENDED TASK: P3-4 / P4-7.

**F-13 — Providers (R15)**
- CURRENT CODE: CRM route `provider: Literal["manual"]` (`api/schemas/verification.py:49`, D7); Sumsub code is the legacy applicant/SDK client; the adapter protocol is synchronous; Middesk/Trulioo sit in the untouchable `kyb` module / integrations.
- TARGET: Sumsub and others through the existing adapters; clear results auto-pass, flagged go to review.
- GAP: a real adapter, async I/O, a D7 amendment, routing rules, coverage.
- IMPACT: a blocking HTTP call inside the event loop if implemented naively.
- DEPENDENCY: coverage verification (BQ-8).
- RECOMMENDED TASK: P7-1–P7-3.

**F-14 — Trade history as a "new module"**
- CURRENT CODE: import-linter forbids other modules importing `onboarding` internals, and the architecture says nothing uses `onboarding`.
- TARGET: a new trade-history module.
- GAP: a module-rule conflict.
- IMPACT: it must be a sub-area of `onboarding` (entities, service, router), or a written EX-00x exception.
- DEPENDENCY: none.
- RECOMMENDED TASK: P5 (inside `onboarding`).

**F-15 — Data provenance (R4)**
- CURRENT CODE: `exporter_profile.source` (immutable), qualification `source`/`decided_by_kind`, verification `provider`/provenance, document `source`/`uploaded_by`, history `actor_id` + code path. No `source_ref`, no consent, no field-level provenance, no encryption of tax IDs.
- TARGET: provenance on every business record, plus consent (shape pending the DPDP meeting).
- GAP: most of it; the design is unknown until the meeting.
- DEPENDENCY: BQ-7.
- RECOMMENDED TASK: P7-4, P7-5; interim: give every new table in P4–P6 `created_by` + `source` columns so they need no retrofit.

### 5.3 Smaller findings

- `exporter_profile.relationship_manager` is free text shown as "Owner"; `relationship_manager_user_id` is never written. "RM" in the target is a role label, not this field. They should not be conflated in the UI.
- `catalog.py` OPERATIONS description ("masked unless you own the record") is stale.
- The handover document snapshot includes documents whatever their scan status (known, `architecture.md` §12). A "required documents present" rule must decide whether only `AVAILABLE` documents count (IQ-11).
- `verification_result.valid_until` exists and could carry provider expiry per check. The target's expiry is per Clear, not per result.
- `search_profiles` has no background-check or expiry filter and returns no `total`, so "Re-KYC due" on Home needs a new filter.
- Deal and history routes will need buyer-company-aware history (a buyer company's timeline currently has nothing about the deals it is buyer on).
- No time-control library (no freezegun/time-machine) in `requirements-dev.txt`; expiry tests need an injected clock.

---

## 6. Gap Analysis

Legend for layers: DB = schema/constraints, API = routes/response shapes (plus OpenAPI regeneration), FE = screens, MIG = data migration.

### 6.1 Settings

| Requirement | Current code | Gap | Affected files | DB | API | FE | MIG | Depends on | Risk | Phase |
|---|---|---|---|---|---|---|---|---|---|---|
| Domestic qualification: IEC and export record optional | Both `required=true` v1 | New versions with `required=false` | migration seed or ADMIN screen; `sample_data.py` | – | – | – | data (new versions) | none | Low | P1-1 |
| INR thresholds | "USD" unit, USD values | New versions: `unit='INR'`, rupee values; de-count side effect | same | – | – | display formatting | data | BQ-1 values | Medium (silent de-count) | P1-1, P1-3 |
| Export-specific reason codes | 3 export codes active; no admin route | Deactivate/relabel; add domestic codes | migration data | – | – | – | data | IQ-12 list | Low | P1-2 |
| Export criteria optionality (corridor) | `geography` already `required=false` | none | – | – | – | – | – | – | – | – |
| Branding "Aner Labs" | "ANER"/"Exporter CRM" in `index.html:7`, `Sidebar.tsx:133-134`, `LoginPage.tsx:52-53` | Replace UI strings; keep backend `APP_NAME` (the OpenAPI title is compared by a test) | frontend only | – | – | yes | – | none | Low | P1-4 |
| RM label | `humanize(user.role)` in `AppShell.tsx:64`, `HomePage.tsx:38`; raw `user.role` in `MyProfileTab.tsx:123`; `roles.ts:23` text; roles table name "Operations" | Central `roleLabel()`; decide the roles-table display name | frontend; optional data | – | – | yes | optional | IQ-13 | Low | P1-5 |
| Maker-checker configuration | None | Build (see compliance rules) | – | – | – | – | – | – | – | P1-6 → P3-1 |

### 6.2 Compliance UX

| Requirement | Current code | Gap | Affected files | DB | API | FE | MIG | Depends on | Risk | Phase |
|---|---|---|---|---|---|---|---|---|---|---|
| Evidence per check | `EvidenceList` on verification rows; counts on decisions; none on screening | Decision evidence detail; screening `evidence_refs` | `background_check_service.py`, `background_check_views.py`, `screening_review_service.py`, `DecisionHistory.tsx`, `ScreeningChecklist.tsx` | new nullable column on `screening_review_item` | new/extended read | yes | none | none | Low | P2-1 |
| Automated/manual labels | Labels exist | Filters | `VerificationSection.tsx` | – | – | yes | – | none | Low | P2-2 |
| Re-KYC / Re-KYB | Reopen only | Cycle model + actions | new `check_cycle`; seam; `VerificationService`; `ScreeningReviewService`; `BackgroundCheckService` | new table + nullable `cycle_id` columns | new routes; seam v2 | yes | cycle 1 per company | P0-2, IQ-3 | Medium | P2-3 |
| Website removal | 7 touchpoints | Remove; 8 → 7; CSV transition | `exporter_profile.py`, schemas, `company_import_service.py`, `company_package.py`, `screening_review_service.py`, `AddExporterPage.tsx`, `CompanyPanel.tsx` | keep column; add `rules_version` to decisions | request schemas | yes | none (keep data) | none | Medium (CSV compatibility) | P2-4 |
| Required documents | None | Settings table + guard condition | new entity/service/router; `deal_service.py` guard | new table | ADMIN CRUD; guard reason | settings screen + deal page | none | business list (IQ-10) | Low (empty list = no-op) | P2-5 |
| GST verification link | None | Link next to each GSTIN | `CompanyPanel.tsx` | – | – | yes | – | portal URL (UNKNOWN), masking | Low | P2-6 |

### 6.3 Compliance rules

| Requirement | Current code | Gap | Affected files | DB | API | FE | MIG | Depends on | Risk | Phase |
|---|---|---|---|---|---|---|---|---|---|---|
| Maker-checker | None | Proposal → approval → decision | `background_check_service.py`, `background_check_router.py`, new entities, `BackgroundCheckPanel.tsx`, `BackgroundCheckMoveDialog.tsx` | new tables + decision columns | new routes; read model `awaiting_approval` | yes | none | P0-5, IQ-1 | High (every CLEAR test) | P3-1 |
| KYB+AML+sanctions for Clear | Not required | Policy field + cycle scope + served list | `background_check_views.py` (`ClearPolicy`), seam | – | read model lists required types | checklist | none | P2-3, IQ-2 | Medium | P3-2 |
| One-year Clear validity | None | `expires_at` on CLEAR + current value on company | decision entity, reader, guard, search | columns | read + filter | Home card, gauge | legacy read rule / current-value backfill | P2-4 (`rules_version` migration), BQ-5 | Medium | P3-3 |
| Expiry handling | None | Guard condition; Home; no auto move | `deal_service.py`, `background_check_reader.py`, `HomeCards.tsx` | index | filter | yes | – | P3-3a | Low | P3-3 |
| Buyer AML/sanctions guard | Buyer checks never block (decision 9) | Guard condition via seam | `deal_service.py`, `compliance_inputs.py` | – | blocked reason | deal page | – | BQ-3; final form after P4-5 | Medium | P3-4 → P4-7 |

### 6.4 Company architecture

| Requirement | Current code | Gap | Affected files | DB | API | FE | MIG | Depends on | Risk | Phase |
|---|---|---|---|---|---|---|---|---|---|---|
| One company record for buyer and seller | Seller only | Identity + pipeline status + buyer FK | entity, service, schemas, routers | columns | yes | yes | yes | P2-7 | High | P4 |
| Foreign company identity | `country` only; CIN India-only | `identity_type`, `registration_number`, unique `(country, registration_number)` | `exporter_profile.py`, `tax_identifiers.py`, `company_matching.py` | columns + partial unique | create/patch/search | forms | none (existing = `IN_PAN` or unknown) | IQ-7 | Medium | P4-1 |
| `pipeline_status` | None; journey `NOT NULL DEFAULT 'LEAD'` | Column + default exclusion from lists/pipeline/Home counts | `search_profiles`, `PipelinePage.tsx`, `HomeCards.tsx`, qualification/conversation services | column + check | filter param | yes | all existing = `IN_PIPELINE` | P4-1 | Medium (leaks into LEAD counts) | P4-1/P4-2 |
| `buyer_company_id` | `deal_buyer` | FK + write path + snapshot | `deal.py`, `deal_service.py`, `schemas/deal.py`, `DealDetailPage.tsx` | column, check seller≠buyer, trigger update | `PUT /deals/{id}/buyer` shape | buyer picker | backfill | P4-1, P2-7 | High | P4-4 |
| Buyer search/create | None | Match-or-create | `company_matching.py`, new route | – | new | picker | – | BQ-2 | High (disclosure) | P4-3 |
| Buyer migration | – | Dedupe + create + map | new command, mapping table | mapping table | – | – | yes | P4-1, P4-4, P0-3 | High | P4-6 |
| Buyer compliance migration | BUYER results keyed by `deal_buyer.id` | `subject_company_id` | `verification_result.py`, `compliance_inputs.py`, `verification_service.py` | column + trigger | seam v2 | `BuyerChecks.tsx` → company panel | backfill via mapping | P4-6 | High | P4-5 |
| Company-level compliance | Company gauge only for sellers | Same background check for any company | services unchanged; guards read buyer company | – | – | yes | – | P4-5, P3-1 | Medium | P4-7, P4-11 |

### 6.5 Trade history

| Requirement | Current code | Gap | DB | API | FE | MIG | Depends on | Risk | Phase |
|---|---|---|---|---|---|---|---|---|---|
| Trade relationship | None | `trade_relationship(seller, buyer)` unique pair | new | new | yes | backfill from deals | P4-4 | Low | P5-1 |
| Invoices | None | `trade_invoice` | new | new | yes | none | P5-1 | Low | P5-2 |
| Payment status | None | Outcome records | new | new | yes | – | P5-2 | Medium (financial record integrity) | P5-2/P5-6 |
| Proof status | None | `PROVEN/CLAIMED` | new | new | yes | – | P5-2 | Low | P5-2 |
| Evidence | Documents exist | Evidence refs (document/url) in the standard `{type, ref}` shape | new | – | `EvidenceList` reuse | – | – | Low | P5-4 |
| Outcomes after handover | None | Record against deal/invoice | new | new | deal page | – | P5-2 | Low | P5-6 |

### 6.6 GST branches

| Requirement | Current code | Gap | DB | API | FE | MIG | Depends on | Risk | Phase |
|---|---|---|---|---|---|---|---|---|---|
| `gst_registration` | `exporter_gstin` | Columns + soft deactivation + state reference | yes | yes | yes | state derivation | P0-3 | Medium | P6-1 |
| GST migration | – | Duplicates, NULL-PAN backfill | constraints | – | – | yes | IQ-9 | High (duplicates may block the unique index) | P6-3/P6-4 |
| Branch identification | GSTIN strings | Per-registration id, state name | yes | yes | yes | – | P6-1 | Low | P6-1 |
| Deal invoicing branch | None | `deal.seller_gst_registration_id` | column + trigger update | yes | yes | legacy NULL | P6-1, P4-4 (same table) | Medium | P6-6 |
| Branch flagging | None | Flag + reason + history + company warning | columns | yes | yes | – | P6-1 | Low | P6-5 |
| Guard | None | "Invoicing branch is flagged" | – | reason | – | – | P6-6, BQ-6 | Medium | P6-7 |

### 6.7 External systems

| Requirement | Current code | Gap | Depends on | Risk | Phase |
|---|---|---|---|---|---|
| DPDP provenance/consent | Partial provenance, no consent, no encryption | Everything beyond today's fields | DPDP meeting (BQ-7) | High (legal) | P7-4/P7-5 |
| Sumsub/providers | Manual only; legacy Sumsub client; sync protocol | Adapter, async, routing, D7 amendment | Coverage (BQ-8) | High (vendor fit) | P7-1–P7-3 |
| RXIL | Company intake (ADMIN paste, provisional); results stub | Results intake, attestation evidence, machine identity | D12, J (BQ-9) | Medium | P7-6 |

---

## 7. Phase 0 — Codebase Audit

This document is the audit. Phase 0's remaining work turns its open points into decisions and fixed contracts before code starts.

### P0-1 — Answer the blocking questions
- **Objective:** get written answers to §19 BLOCKING items, each tagged with the task it unblocks.
- **Current state:** decisions A–K agreed; BQ-1…BQ-9 open.
- **Required change:** a decision log entry per question (append to `docs/open-items.md` or a decisions section in `docs/plan.md`).
- **Backend / Frontend / Database / Migration:** none.
- **Tests:** none.
- **Dependencies:** stakeholders.
- **Parallelization:** runs while P1 and P2 proceed (they need only BQ-1).
- **Acceptance criteria:** each BLOCKING question has an owner, an answer or a date; tasks list which answer they rely on.

### P0-2 — Contract revision v2 (designed once)
- **Objective:** design every contract change the phases need, so the frozen 4A↔4B seam, the history dimensions and the deal contract change once.
- **Current state:** `domain/compliance_inputs.py` says its output shape is frozen; `test_l4b_compliance_inputs_contract.py` pins it. `history-row.md` lists dimensions. `deal-and-buyer.md` and `event-envelope.md` describe `deal_buyer`.
- **Required change:** a v2 of `docs/contracts/background-check.md` §6 seam: `VerificationInput.cycle_id`, `ScreeningItemInput.cycle_id`, `CompanyComplianceInputs.current_cycle_id`, inputs keyed by `subject_company_id`; `buyer_checks(deal_buyer_id)` kept for legacy reads and replaced by `company_inputs(buyer_company_id)`. New history dimensions: `check_cycle`, `background_check_approval`, `gst_registration`, `trade`, `pipeline`. `deal.handed_over` payload: buyer snapshot + `buyer_company_id`.
- **Backend / Frontend / Database / Migration:** docs only in this task.
- **Tests:** list which contract tests change (see §18.2).
- **Dependencies:** P0-1 answers for IQ-2/IQ-3.
- **Parallelization:** with P1.
- **Acceptance criteria:** all affected contracts updated and agreed by their owners (architecture §10 ownership table).

### P0-3 — Data inventory on every live database
- **Objective:** size the migrations with facts, not assumptions.
- **Current state:** data is sample/UAT (`crm_uat_walk`, `crm_release_audit`, demo DB, shared test DB). Contents UNKNOWN / NEEDS VERIFICATION.
- **Required change:** read-only SQL report per database: deal buyers (count, per country, `tax_id` shaped as PAN/GSTIN), BUYER verification results, GSTINs held by more than one company, companies with `pan IS NULL` and GSTINs, `CLEAR` companies and their clearing decision dates, open proposals (none yet), screening rows on `website-reviewed`, documents per category on deals.
- **Tests:** none.
- **Dependencies:** none.
- **Parallelization:** anytime.
- **Acceptance criteria:** a report per environment attached to the migration tickets; each migration states which environments it must run on.

### P0-4 — Migration and gate conventions
- **Objective:** make the long migration sequence safe.
- **Current state:** one head `onboarding_0022_integrity`; revision ids ≤ 32 characters (`migration-register.md`); DDL `ADD COLUMN` does not fire row triggers (0013's pattern); no CI.
- **Required change:** reserve revision numbers from `onboarding_0023_*` in merge order; adopt expand → backfill → contract for P4 and P6; mandatory `pg_dump` before any data migration; each migration's downgrade either reverses cleanly or documents why it cannot (append-only rows); run gates by hand per `docs/development.md` §7 until CI exists.
- **Tests:** `alembic heads` = 1 after each merge; `test_orm_matches_the_onboarding_schema.py` passes.
- **Dependencies:** none.
- **Parallelization:** anytime.
- **Acceptance criteria:** conventions written into `docs/development.md` and `migration-register.md`.

### P0-5 — Test fixtures for two approvers and for time
- **Objective:** keep the suite green through maker-checker and expiry.
- **Current state:** tests clear companies as one user; no freezegun/time-machine; `datetime.now(tz=UTC)` is called inline (for example `deal_service.py:353`).
- **Required change:** fixtures for a second COMPLIANCE user and an `approve_as(...)` helper; an injectable clock (`app/shared` utility or service argument) for Clear expiry.
- **Tests:** fixtures themselves.
- **Dependencies:** none.
- **Parallelization:** with P1.
- **Acceptance criteria:** a test can clear a company with maker ≠ checker in one call; a test can move "now" past an expiry without sleeping.

---

## 8. Phase 1 — Settings and Labels

### P1-1 — Domestic criteria version
- **Objective:** a domestic company with no IEC or export history can be qualified. Thresholds stay in USD (BQ-1, answered 1 October).
- **Current state:** v1 seed (`onboarding_0017_qualification.py:92-104`); ADMIN can add versions in the UI.
- **Required change:** new versions of `export_history` and `export_licence` with `required=false`. `revenue` and `deal_size` are **not** changed (USD kept), so their existing results keep counting. Do it as a data migration (`onboarding_0023_domestic_criteria`) so every environment gets identical versions, with `created_by` set to a recognisable migration actor, rather than by hand per environment.
- **Backend:** none beyond the migration; update `sample_data.py` so sample companies pass the new versions.
- **Frontend:** none (P1-3 handles display).
- **Database:** inserts only (the table is append-only).
- **Migration:** as above. Side effect limited to the two criteria that change: existing IEC/export results stop counting, which is harmless because those criteria are no longer required. QUALIFIED companies are unaffected (A2).
- **Tests:** a test that a company with PASS on revenue and years and no IEC/export results gets a `QUALIFIED` suggestion; the version chain test; sample-data tests.
- **Dependencies:** none (BQ-1 answered: keep USD).
- **Parallelization:** with P1-2 … P1-5.
- **Acceptance criteria:** source §7 1.1 "Done when"; `GET /qualification/criteria` shows the new versions; the de-count effect is written in the release note.

### P1-2 — Reason codes for domestic qualification
- **Objective:** no rejection reason assumes export.
- **Current state:** 9 codes; 3 export-specific; `active` flag exists; inactive codes are refused on new outcomes; old outcomes keep their strings.
- **Required change:** data migration: **deactivate** `no_export_history`, `no_export_licence`, `geography_not_supported` (IQ-12, answered); they can be reactivated when export returns (decision F). Add domestic codes if the business supplies any.
- **Backend / Frontend:** none (codes are served).
- **Database / Migration:** row updates/inserts on the mutable `qualification_reason_code`.
- **Tests:** outcome with an inactive code → 422; history rendering of old outcomes unchanged.
- **Dependencies:** IQ-12 (the list).
- **Parallelization:** with P1-1.
- **Acceptance criteria:** the reason list shows no export-only code; old outcomes still render.

### P1-3 — Currency-aware display of thresholds and observed values (DEFERRED)
- **Status:** deferred on 1 October: thresholds stay in USD (BQ-1). Pick up when a rupee criterion or foreign trade (decision F) needs it.
- **Objective:** INR is shown as rupees (₹, lakh/crore grouping) wherever a criterion shows its threshold or unit.
- **Current state:** `QualificationCriteriaPage.tsx:76` joins comparison, threshold, unit as text; `QualificationPanel.tsx:144` shows "Observed (USD)".
- **Required change:** a small formatter used by both; free-text `unit` stays; optional validation of `unit` against a short list (INR, USD, YEARS) in `_check_definition`.
- **Backend:** optional validation only.
- **Frontend:** formatter + tests.
- **Database / Migration:** none.
- **Tests:** formatter unit tests; criteria page snapshot.
- **Dependencies:** none.
- **Parallelization:** yes.
- **Acceptance criteria:** "₹10,00,00,000" style output for INR; USD unchanged.

### P1-4 — "Aner Labs" branding
- **Objective:** internal UI says "Aner Labs" (R9).
- **Current state:** `frontend/index.html:7`, `src/layout/Sidebar.tsx:133-134`, `src/pages/auth/LoginPage.tsx:52-53`.
- **Required change:** replace UI strings only. Do **not** change backend `APP_NAME`: the OpenAPI artifact test compares `info.title` (`open-items.md` §2).
- **Tests:** `Sidebar.test.tsx`, login page test if any; grep test for "ANER Exporter CRM".
- **Dependencies:** none. **Parallelization:** yes.
- **Acceptance criteria:** no screen shows the old product name; `test_openapi_artifact_is_current.py` still passes.

### P1-5 — "Operations" shown as "RM"
- **Objective:** no screen shows "Operations"; the API and stored values are unchanged (R10).
- **Current state:** role rendered via `humanize()` in `AppShell.tsx:64` and `HomePage.tsx:38`; raw enum in `MyProfileTab.tsx:123`; text in `modules/settings/roles.ts:23`; role picker in `UserFormDialog.tsx`/`UsersTab.tsx` (rendering to confirm); the roles table's display name for OPERATIONS is "Operations" (`catalog.py`), shown on Settings → Roles.
- **Required change:** one `roleLabel(role)` in `frontend/src/platform/auth` (`OPERATIONS → "RM"` or "Relationship Manager"), used everywhere a role is shown; settings descriptions updated. Per IQ-13 (answered), the built-in role's **display name** in the roles data also becomes "RM (Relationship Manager)" (a small data migration on the seeded row, or an ADMIN edit in Settings; the `OPERATIONS` enum and slug are untouched), and the stale description in `catalog.py` is corrected.
- **Backend:** none. Server 403 messages ("OPERATIONS, COMPLIANCE or ADMIN role required") stay; the UI should not surface them verbatim.
- **Tests:** a unit test for `roleLabel`; a test that renders each role site with OPERATIONS.
- **Dependencies:** none. **Parallelization:** yes.
- **Acceptance criteria:** source §7 1.3 "Done when"; grep of the built bundle for user-visible "Operations" is empty.

### P1-6 — Maker-checker switch: report
- **Objective:** answer source §7 1.4 before the follow-up meeting.
- **Current state / result:** **NO — it does not exist** (§5.1 item 1). No code change in P1; the build is P3-1.
- **Acceptance criteria:** the answer is recorded in the decision log with the evidence lines.

---

## 9. Phase 2 — Compliance UX

### P2-1a — Resolve a decision's pinned evidence into readable items
- **Objective:** a reviewer sees what a decision rested on, not a count.
- **Current state:** decisions return `evidence` as kinds + ids (`EvidenceItemView`, "ids only, never content"); `DecisionHistory.tsx:30-53` shows counts.
- **Required change:** `GET /exporters/{id}/background-check/decisions/{decision_id}/evidence` (or an `?expand=evidence` flag) resolving each pinned id to: for a verification, type, status, provenance, recorded by/at, latest review, `evidence_note`, `evidence_refs`; for a screening item, key, label, status, comment, evidence refs (after P2-1b), by/at; for a document, file name, category, scan status, `is_downloadable`.
- **Backend:** a read method in `BackgroundCheckService` or a new read service; reuse `VerificationService.views_for`, the screening view, the document repository. D8: DEVELOPER refused (same gate as the decisions route).
- **Frontend:** none in this task.
- **Database / Migration:** none.
- **Tests:** API test per evidence kind; D8 test; masking test (no identifiers in these shapes); route-authorisation row.
- **Dependencies:** none. **Parallelization:** with P2-1b, P2-2.
- **Acceptance criteria:** every pinned id on a sample CLEAR decision resolves; OpenAPI regenerated.

### P2-1b — Evidence on screening items
- **Objective:** a screening answer can carry evidence like a verification result.
- **Current state:** `screening_review_item` has only `comment`; append-only trigger.
- **Required change:** `evidence_refs JSONB NOT NULL DEFAULT '[]'` (DDL fills existing rows without firing the row trigger) + `ck_…_evidence_refs_array`; the PUT accepts `evidence_refs` in the `{type, ref}` shape and applies `verification_evidence.check_evidence_shape` and the document-ownership/AVAILABLE rule. Whether PASSED requires evidence is IQ-14 (default: optional, as today's comment).
- **Backend:** `ScreeningReviewService.upsert_review_item`, schema, seam unchanged.
- **Frontend:** P2-1c.
- **Database:** column + check. **Migration:** none beyond the DDL default.
- **Tests:** shape validation; foreign-company document refused; append-only still refuses UPDATE (raw SQL).
- **Dependencies:** none. **Parallelization:** with P2-1a.
- **Acceptance criteria:** a screening PASSED with a document ref round-trips and opens via `EvidenceList`.

### P2-1c — Show evidence per check in the background-check panel
- **Objective:** source §7 2.1 "Done when": reviewers see why each result was given without leaving the page.
- **Current state:** `VerificationResultRow` already renders `EvidenceList`; `ScreeningChecklist` and `DecisionHistory` do not.
- **Required change:** `EvidenceList` under each screening item and inside an expandable decision row (data from P2-1a); keep its props contract (`note`, `refs`).
- **Tests:** `ScreeningChecklist.test.tsx`, `BackgroundCheckPanel.test.tsx`, a new `DecisionHistory` test.
- **Dependencies:** P2-1a, P2-1b.
- **Acceptance criteria:** each check shows result, who, when, provenance label and evidence with open links.

### P2-2 — Automated / manual labels and filters
- **Objective:** filter results by All / Automated / Manual / Flagged.
- **Current state:** labels exist (`verification-labels.ts:63-70`); no filter; `provenance` is served.
- **Required change:** client-side filter in `VerificationSection.tsx` over served fields: Automated = `PROVIDER` (IQ-15: include `STUB`?), Manual = `MANUAL`, Flagged = `status == FAILED` or `risk_level in (HIGH, CRITICAL)` (to confirm).
- **Backend / Database / Migration:** none.
- **Tests:** `VerificationSection.test.tsx` filter cases.
- **Dependencies:** none. **Parallelization:** yes.
- **Acceptance criteria:** filters work with sample data; "Automated" shows an honest empty state until P7.

### P2-3a — Check cycle model
- **Objective:** group each KYC/KYB round so a second round can run with the first still visible.
- **Current state:** none (§5.1 item 4).
- **Required change (PROPOSED names):** `onboarding.check_cycle` (append-only): `id`, `company_id` FK, `number` (unique per company), `kind` (`INITIAL`, `RE_KYC`, `RE_KYB`, `FULL` per IQ-3), `reason`, `started_by`, `started_at`, `rules_version`. Nullable `cycle_id` FK on `verification_result`, `screening_review_item`, `background_check_decision`. New rows always carry it; a `NULL` means "the company's cycle 1" by rule. Cycle 1 is created per company that has any input, dated at its earliest input.
- **Backend:** repository; `VerificationService`/`ScreeningReviewService`/`BackgroundCheckService` stamp the current cycle.
- **Database:** new table; nullable FK columns (DDL; no trigger fires); partial unique "one current cycle" enforced under the company row lock.
- **Migration:** create cycle 1 rows (INSERT only). Do **not** update existing input rows.
- **Tests:** migration test (cycle 1 exists for companies with inputs; legacy rows unchanged); append-only on `check_cycle`; ORM drift.
- **Dependencies:** P0-2 (seam v2), IQ-3.
- **Parallelization:** with P2-1, P2-2, P2-5.
- **Acceptance criteria:** every company with inputs has cycle 1; new inputs carry `cycle_id`.

### P2-3b — Seam v2: cycle-scoped inputs
- **Objective:** the background check decides on the current cycle.
- **Current state:** `ComplianceInputsService.company_inputs` returns every EXPORTER result ever and the latest screening row per key.
- **Required change:** implement the P0-2 seam shape: current cycle's results (legacy `NULL` = cycle 1), latest screening row per key within the current cycle, with the cycle id. Placeholders from earlier cycles no longer block (this settles source §1.5 item 3 going forward).
- **Tests:** `test_l4b_compliance_inputs.py`, `test_l4b_compliance_inputs_contract.py`, `test_l4a_background_check_rules.py` (policy over cycle-scoped inputs).
- **Dependencies:** P2-3a.
- **Acceptance criteria:** a company in cycle 2 with no cycle-2 screening answers cannot be cleared even though cycle 1 had eight PASSED.

### P2-3c — Re-KYC / Re-KYB actions
- **Objective:** buttons that start a new cycle.
- **Current state:** only reopen (`CLEAR → IN_REVIEW`).
- **Required change:** `POST /exporters/{id}/background-check/cycles` `{kind, reason}` (COMPLIANCE, ADMIN; IQ-3 on whether OPERATIONS may start). Recommended semantics: starting a cycle on a `CLEAR` company also records the existing reopen move (`CLEAR → IN_REVIEW`, reason "Re-KYC: …") in the same transaction, because there is no `CLEAR → CLEAR` move and the gauge must not read `CLEAR` while the new cycle's inputs are pending. On `NOT_STARTED`/`IN_REVIEW`/`MORE_INFO` it starts the cycle without a gauge move; on `FLAGGED`/`ON_HOLD` it is refused (reassess first). History row `dimension='check_cycle'`.
- **Tests:** each starting state; concurrency (two starts at once → one cycle); history; roles; D8.
- **Dependencies:** P2-3a, P2-3b, IQ-3.
- **Acceptance criteria:** source §7 2.3 "Done when": a second cycle can be run and both are visible.

### P2-3d — Cycle UI
- **Objective:** see cycles and their results.
- **Required change:** cycle selector/grouping in `VerificationSection`, `ScreeningChecklist`, `DecisionHistory`; Re-KYC/Re-KYB buttons shown from a served `allowed_actions`.
- **Tests:** component tests with two cycles.
- **Dependencies:** P2-3c.
- **Acceptance criteria:** previous cycles readable; the current one editable.

### P2-4a — Screening 8 → 7 and `rules_version`
- **Objective:** remove the website item without disturbing old Clears (K).
- **Current state:** `SCREENING_CATALOGUE_ITEMS[0] = website-reviewed`; policy in code; decisions carry no rule version.
- **Required change:** remove the item from the catalogue (the UI is catalogue-driven); `list_review_items` filters to catalogue keys so the retired key's rows stay stored but are not listed as current; `_check_item_key` refuses new writes to it. Add `rules_version String NULL` to `background_check_decision` (and `check_cycle`); constants `CLEAR_RULES_V1 = "clear-2026-09-28-8items"` (implied for legacy `NULL`) and `CLEAR_RULES_V2` set on every new CLEAR. Old decisions keep their pinned website rows.
- **Backend:** `screening_review_service.py`, `background_check_views.py`, `background_check_service.py`.
- **Database:** nullable column on an append-only table (DDL).
- **Migration:** none (legacy `NULL` = v1 by rule).
- **Tests:** 11 backend test files reference the catalogue or `website-reviewed` (§18.2); a test that a legacy CLEAR still resolves its pinned website row in P2-1a; a test that a new CLEAR stores `rules_version`.
- **Dependencies:** none (coordinate with P2-3a; both add decision columns, so use one migration if they land together).
- **Acceptance criteria:** checklist shows 7; old decisions show 8 pinned items; new CLEARs record the rule version.

### P2-4b — Remove the website field
- **Objective:** R11: no website on forms, CSV or validation; a missing website is never a failure.
- **Current state:** `website` on create/patch schemas, `AddExporterPage.tsx`, `CompanyPanel.tsx`, `TEMPLATE_COLUMNS`, RXIL package, `normalise_website`.
- **Required change:** drop from forms and the template; request schemas stop accepting it (or accept and ignore for one release). CSV: accept both the new header and the old header (ignore the `website` column) for a transition period, because the importer refuses any other header (`company_import_service.py:262`). RXIL: ignore `website` in the package (provisional format). Keep the DB column and stored values (no data destruction); stop showing them unless IQ-16 says otherwise.
- **Tests:** `test_company_website.py` (rewrite as "website ignored/refused"), `test_company_import.py` (both headers), `AddExporterPage.test.tsx`, `CompanyImportPage.test.tsx`; OpenAPI regeneration.
- **Dependencies:** P2-4a (same release).
- **Acceptance criteria:** source §7 2.4; an old CSV with a website column still imports.

### P2-5a — Required document categories as a setting
- **Objective:** ADMIN defines which document categories a deal must have before handover (R7, "verify each deal with evidence before handover", is met by this rule plus P2-1's evidence per check).
- **Current state:** categories are an enum; types are YAML; no requirement concept for deals (the legacy `document_requirements_service.py` serves `onboarding_request`, not deals).
- **Required change (PROPOSED):** `onboarding.deal_required_document` versioned like criteria (append-only rows: `category`, optional `document_type`, `active`, `version`, `created_by`) + `GET/POST /settings/deal-required-documents` (read Staff, write ADMIN) + a Settings screen. Seeded with one requirement, **category `PRE_SHIPMENT`** (IQ-10, answered). This **changes behaviour**: an open deal with no scanned-clean pre-shipment document (invoice, PO, contract or letter of credit) can no longer be handed over. The sample data has no documents (`open-items.md` §2), so the demo walk-through and `test_crm_end_to_end.py` must upload one before handover; already handed-over deals are unaffected.
- **Tests:** CRUD, roles, append-only, route-authorisation rows.
- **Dependencies:** none. **Parallelization:** yes.
- **Acceptance criteria:** ADMIN can add/remove a category; history of changes is kept.

### P2-5b — "Required documents present" in the handover guard
- **Objective:** name missing categories like the other unmet conditions.
- **Current state:** guard in `deal_service.py:535-588`.
- **Required change:** in `_handover_blocked_reason`, read active requirements and the deal's documents; count only `AVAILABLE` documents (IQ-11, answered); append "missing required documents: PRE_SHIPMENT, …".
- **Tests:** `test_l3b_handover.py` new cases; the unlocked read path shows the same reason; e2e.
- **Dependencies:** P2-5a.
- **Acceptance criteria:** with a requirement set, a deal lacking it is refused with 409 naming the category; with none set, behaviour is unchanged.

### P2-6 — "Verify GSTIN" link
- **Objective:** R16.
- **Current state:** GSTINs shown masked for OPERATIONS (`CompanyPanel.tsx:266-269`).
- **Required change:** a link to the GST portal's taxpayer search next to each GSTIN. Whether the portal accepts a GSTIN in the URL is **UNKNOWN / NEEDS VERIFICATION** (the public search appears to require manual entry and a captcha). For masked roles the link can only open the portal, since the full GSTIN is not in their response; a "copy GSTIN" action for masked roles would breach decision 12.
- **Tests:** component test per role.
- **Dependencies:** none.
- **Acceptance criteria:** COMPLIANCE/ADMIN can open the portal from each GSTIN; OPERATIONS gets no reveal.

### P2-7 — Persist the handover snapshot on the deal
- **Objective:** keep what the lending team was given, independent of later company edits (prerequisite for P4).
- **Current state:** §5.2 F-02.
- **Required change:** `deal.handover_snapshot JSONB NULL` holding `{buyer: {...}, document_ids: [...], snapshot_source}`, written in `transition_stage` on `HANDED_OVER`; add the column to `prevent_terminal_deal_change()` so it cannot change once set. Backfill existing `HANDED_OVER` deals from `deal_buyer` + the handover history row's `document_ids`, marked `snapshot_source: "backfilled_from_deal_buyer"` (the best evidence available). Include `handover_snapshot` in the deal response (masked for OPERATIONS/DEVELOPER like the buyer today).
- **Tests:** snapshot written; immutable after handover (raw SQL); backfill migration test; masking.
- **Dependencies:** none.
- **Parallelization:** with all P2 tasks.
- **Acceptance criteria:** every `HANDED_OVER` deal has a snapshot; editing the buyer data afterwards does not change it.

---

## 10. Phase 3 — Compliance Rules

### P3-1a — Maker-checker schema
- **Objective:** store a recorded decision awaiting approval and its resolution (decision A).
- **Current state:** §5.1 item 1. `ck_background_check_decision_move` and the chain FK pin the nine moves.
- **Design choice:** the source proposes "a new sub-state `AWAITING_APPROVAL` within In review". Two ways to build it:
  - **(Recommended) Proposal records, gauge unchanged.** This keeps the source's own wording ("a sub-state within In review") and leaves the gauge's six values untouched. `background_check_proposal` (append-only: `company_id`, `based_on_decision_id` = chain head, `from_value`, `to_value`, `risk_rating`, `reason`, `proposed_by`, `proposed_at`, `inputs_fingerprint`, `cycle_id`) and `background_check_proposal_resolution` (append-only, unique `proposal_id`: `outcome` APPROVED/REJECTED/WITHDRAWN, `resolved_by`, `resolved_at`, `reason`, `decision_id`, a copy of `proposed_by` so `CHECK (outcome <> 'APPROVED' OR resolved_by <> proposed_by)` holds inside one row). Decision rows gain `proposal_id`, `approved_by`, `approved_at` (nullable) with `CHECK (approved_by IS NULL OR approved_by <> decided_by)`. The gauge stays `IN_REVIEW` (or `FLAGGED` for an `ON_HOLD` proposal); "Awaiting approval" is a served sub-state. No change to `background_check_enum`, the move constraint, the chain FK, promotion, or the handover guard.
  - **(Alternative) New gauge value `AWAITING_APPROVAL`.** Needs `ALTER TYPE … ADD VALUE`, a rewritten move constraint, and a way to carry the *proposed* destination and risk (risk is refused on non-CLEAR moves by `ck_background_check_decision_risk_only_on_clear`). Every consumer that reads the gauge would see a seventh value.
- **Database:** two tables, three decision columns, checks, "one open proposal per company" enforced under the company row lock.
- **Migration:** none (no legacy proposals).
- **Tests:** schema tests; append-only raw SQL; self-approval refused at the DB.
- **Dependencies:** P0-5, IQ-1.
- **Parallelization:** with P3-2, P3-3a.
- **Acceptance criteria:** the schema refuses self-approval and edits.

### P3-1b — Maker-checker service and API
- **Objective:** record → approve (different user) → final state; or reject back with a reason.
- **Required change:** for moves that need approval (IQ-1, answered: **CLEAR, FLAGGED, ON_HOLD**; MORE_INFO, start, answer, reassess and reopen do not): `POST …/background-check/decisions` creates a proposal (prerequisites evaluated, fingerprint of the evidence selection stored). `POST …/proposals/{id}/approve` locks the company, refuses the proposer (409/403), refuses a stale head or changed fingerprint (409, re-record), re-evaluates `CLEAR_POLICY`, writes the decision with `decided_by = proposer`, `approved_by = approver`, pins evidence and promotes, all in one transaction. `…/reject` requires a reason; `…/withdraw` is proposer only. OPERATIONS never approves. History: `background_check_approval` rows for propose/approve/reject/withdraw. `allowed_moves` becomes role- **and user**-aware (the approver sees Approve/Reject; the proposer sees Withdraw).
- **Config (IQ-17, answered):** a setting `CRM_BACKGROUND_CHECK_MAKER_CHECKER`, default on. It may be turned off only when `ENVIRONMENT` is local or test; the application refuses to start with it off anywhere else (UAT, production).
- **Tests:** every move needing approval; self-approval; ADMIN approving COMPLIANCE and vice versa; stale approval after a new input; concurrent approve/reject; promotion on approval; D8; route authorisation; e2e.
- **Dependencies:** P3-1a.
- **Acceptance criteria:** source §7 3.1; no path lets one user take a company to CLEAR.

### P3-1c — Maker-checker UI
- **Required change:** the "Awaiting approval" state in `BackgroundCheckPanel` and `BackgroundCheckGauge` description; approve/reject dialog; a queue of proposals awaiting me (a Home card for COMPLIANCE/ADMIN; needs `GET /background-check/proposals?status=open`).
- **Tests:** `BackgroundCheckPanel.test.tsx`, `BackgroundCheckMoveDialog` tests, HomeCards.
- **Dependencies:** P3-1b.
- **Acceptance criteria:** a second user can approve from Home in two clicks; the maker sees who approved.

### P3-1d — Bring the existing suite and sample data onto maker-checker
- **Objective:** no silent single-user path left in tests or seeds.
- **Required change:** `sample_data_background_check.py` records approvals by a second seeded user; `test_l4a_background_check_service.py` (1,435 lines), `test_l4a_background_check_api.py`, `test_customer_promotion.py`, `test_crm_end_to_end.py`, `test_l3b_handover.py` use the P0-5 helper.
- **Acceptance criteria:** suite back to baseline with maker-checker on.

### P3-2 — KYB, AML and sanctions must pass for Clear (decision B)
- **Objective:** `CLEAR` refused unless KYB, AML and SANCTIONS passed in the current cycle.
- **Current state:** `ClearPolicy` has no required-type field; seam scoped by cycle after P2-3b.
- **Required change:** `ClearPolicy.required_passed_types = {KYB, AML, SANCTIONS}`, and a prerequisite per missing type (`kyb_passed`, `aml_passed`, `sanctions_passed`) so the refusal names each. "Passed" by default means: the latest non-placeholder result of that type in the current cycle has `status=PASSED` (IQ-2 decides whether `REVIEW` + `ACCEPTED` counts). The background-check read serves the required types and their state, so the UI stops relying on `COMPANY_CHECK_TYPES` for this.
- **Tests:** `test_l4a_background_check_rules.py` (pure policy), service/API tests, e2e, sample data.
- **Dependencies:** P2-3b; with P2-4a in the same `rules_version` bump.
- **Parallelization:** with P3-1.
- **Acceptance criteria:** source §7 3.2; the guard names what is missing.

### P3-3a — Clear expiry: schema and backfill
- **Objective:** each Clear carries `expires_at` (decision E).
- **Required change:** `background_check_decision.expires_at NULL` (set on new CLEAR = `decided_at + validity`, validity a setting defaulting to 365 days) and `exporter_profile.background_check_expires_at NULL` (the current value, like the other gauge columns; set on CLEAR, cleared on any move away, indexed for Home). Legacy CLEAR decisions keep `NULL` (append-only). Their expiry is the read rule "decided_at + 1 year" (rule 5.1.3, confirmed as BQ-5 on 1 October), and the current-value column is **backfilled** for currently-CLEAR companies (the profile row is mutable).
- **Tests:** backfill test; CLEAR sets both; reopen clears the profile column.
- **Dependencies:** P2-4a (same decision-table migration cluster), BQ-5 for release.
- **Acceptance criteria:** every CLEAR company has an expiry; new decisions store theirs.

### P3-3b — Expiry in the reader, the guard and promotion
- **Required change:** `BackgroundCheckStanding.expires_at` and an `is_clear_and_current(now)` helper, keeping `is_clear` as is for existing consumers. Handover guard: "the background check expired on <date>" (seller; buyer per BQ-3/BQ-4). No automatic gauge move: decisions stay manual, and "new adverse information → reopen" remains the existing flow. Promotion to CUSTOMER with an expired Clear is **refused** (IQ-18, answered): `promote_to_customer_if_ready` checks the Clear is current, and the company stays a PROSPECT with "Re-KYC due" until a new Clear promotes it.
- **Tests:** injected clock (P0-5); guard; unlocked read path; promotion.
- **Dependencies:** P3-3a.
- **Acceptance criteria:** source §7 3.3: an expired check blocks new handovers.

### P3-3c — "Re-KYC due" on Home and in lists
- **Required change:** `search_profiles(background_check_expires_before=…)` + a Home card ("Re-KYC due", expired and due within N days) for COMPLIANCE/ADMIN (and RM read-only); a gauge badge "Re-KYC due".
- **Tests:** API filter; HomeCards test; masking (no identifiers).
- **Dependencies:** P3-3a.
- **Acceptance criteria:** Home lists expired and soon-expiring companies.

### P3-4 — Buyer sanctions/AML in the handover guard (decision C), interim
- **Objective:** a failed sanctions or AML result on the buyer blocks handover.
- **Current state:** buyer checks are keyed by `deal_buyer.id`; the seam already has `buyer_checks(deal_buyer_id)`.
- **Required change (BQ-3, BQ-4, IQ-2 answered):** a single guard helper `_party_compliance_blockers(deal)` reading the seam:
  - **Buyer:** the latest SANCTIONS and the latest AML result must each be **PASSED** (or REVIEW with an ACCEPTED review). A missing or FAILED result blocks ("buyer sanctions not checked" / "buyer: failed AML"). Incomplete KYB and other buyer checks are warnings in the deal view.
  - **Seller:** a FAILED latest SANCTIONS or AML result in the current cycle blocks, even while the gauge still reads CLEAR (consequence 5.1.1, confirmed). The seller's CLEAR gauge rule stays as it is.
  - P4-7 replaces only where the buyer results are read from (the buyer company instead of `deal_buyer`).
- **Tests:** `test_l3b_handover.py`, `test_l4b_buyer_checks.py`, e2e.
- **Dependencies:** none left (BQ-3/BQ-4 answered).
- **Parallelization:** with P3-1..3.
- **Acceptance criteria:** a deal whose buyer has no PASSED sanctions/AML result, or whose seller has a FAILED one, cannot be handed over and says why. The seeded sample buyers need sanctions and AML results recorded for the demo handover to work.

---

## 11. Phase 4 — Company Unification (keystone)

Sequencing: P4-1 → (P4-2 ∥ P4-3 ∥ P4-4) → P4-5 → **P4-6 migration checkpoint** → P4-7 → (P4-8, P4-9) → P4-10 contract → P4-11.

### P4-1 — Company identity and pipeline status
- **Objective:** any legal entity, Indian or foreign, can be a company, inside or outside the sales pipeline (R1; decision F: domestic first is temporary, so foreign identity is built now).
- **Current state:** §3.1.
- **Required change (PROPOSED names):** `identity_type` (`IN_PAN` | `FOREIGN_REG`, nullable for legacy companies without PAN), `registration_number` (foreign) with partial unique `(country, normalised registration_number)`, `pipeline_status` (`IN_PIPELINE` | `NOT_IN_PIPELINE`, `NOT NULL DEFAULT 'IN_PIPELINE'`), `created_via` (`MANUAL` | `CSV` | `RXIL` | `DEAL_BUYER` | `SAMPLE`) + `created_via_deal_id`. Check: `NOT_IN_PIPELINE ⇒ journey='LEAD' AND qualification='NOT_YET_REVIEWED' AND conversation='NOT_CONTACTED'` (the journey column stays `NOT NULL`; it is simply not applied). `QualificationService` and `ConversationService` refuse a `NOT_IN_PIPELINE` company; `open_deal` already refuses it as a seller (journey `LEAD`).
- **Backend:** entity, `tax_identifiers.py` (foreign number normalisation), `ExporterProfileService.create_*`, schemas, masking (registration number masked like CIN for masked roles).
- **Database:** columns, partial unique, check. **Migration:** `created_via` backfilled from each company's first journey history row (`event_metadata.source`: `exporter_profile_service.create_lead`/`create_or_get_profile` → MANUAL, `company_import.csv` → CSV, `partner_intake.rxil` → RXIL, `sample_data` → SAMPLE, anything else → NULL + report); `identity_type='IN_PAN'` where `pan` is set.
- **Tests:** create foreign company; duplicate `(country, reg no)` refused; `NOT_IN_PIPELINE` refused by qualification and conversation; backfill test; ORM drift.
- **Answered on 1 October:** a company first created as a buyer gets the new `ExporterSource.DEAL_BUYER` (IQ-6), which requires adding a value to `exporter_source_enum`. A foreign company must have a registration number on create and edit (IQ-7). The only exception is buyers created by the P4-6 migration without one, which get `registration_number NULL` plus a "registration number missing" warning and appear in a completion list.
- **Dependencies:** none left. **Parallelization:** with P3.
- **Acceptance criteria:** a foreign buyer-only company can be created by the service; existing companies are `IN_PIPELINE` with `created_via` set where derivable.

### P4-2 — Keep buyer-only companies out of pipeline views
- **Objective:** the target "Buyer-only companies stay outside [the journey]".
- **Current state:** Pipeline and Home counts query `journey=LEAD|PROSPECT|CUSTOMER` (`PipelinePage.tsx:58-75`, `HomeCards.tsx:177-178`).
- **Required change:** `search_profiles` excludes `NOT_IN_PIPELINE` by default (like `ENDED`) and includes it with `pipeline_status=` or an identifier/name search; the company page shows "Not in pipeline" instead of a journey chip; qualification and conversation panels show "Not needed".
- **Tests:** list defaults; pipeline counts; company page rendering.
- **Dependencies:** P4-1.
- **Acceptance criteria:** creating a buyer company changes no LEAD count.

### P4-3 — Buyer search and match-or-create
- **Objective:** the RM picks an existing company or creates one while recording a deal's buyer.
- **Current state:** `CompanyMatcher` (PAN decides; GSTIN/IEC/CIN conflicts; possible duplicates) serves RXIL and CSV; masked roles cannot search by identifiers; name search is `ILIKE`.
- **Required change:** `POST /companies/match` (Staff) taking `{name, country, pan?, gstins?, registration_number?}` and returning `MATCHED` (company id, name, country — identifiers masked per role), `POSSIBLE_DUPLICATE` (candidates by name similarity), `CONFLICT` or `NEW`; then `PUT /deals/{id}/buyer {buyer_company_id}` or `{create: {...}}`. Rule for masked roles (BQ-2, answered): the RM may submit a **full** PAN or GSTIN and the server names the matching company, with its identifiers still masked. Partial or prefix identifier search stays refused, and every identifier lookup writes an audit record (who, when, which company matched). The same rule governs the duplicate-PAN refusal message. Because GSTINs stay warn-only (IQ-9), a GSTIN held by two companies returns both as `POSSIBLE_DUPLICATE` for the RM to choose between. Name similarity: `pg_trgm` availability is UNKNOWN / NEEDS VERIFICATION; fall back to normalised-name equality plus legal-suffix stripping.
- **Tests:** each match kind; masking per role; OPERATIONS search behaviour per BQ-2; route authorisation.
- **Dependencies:** P4-1.
- **Acceptance criteria:** the RM can find a company by name, or by an exact PAN/GSTIN/(country, registration number), or create a `NOT_IN_PIPELINE` one with `source=DEAL_BUYER` and `created_via=DEAL_BUYER`; each identifier lookup is audited.

### P4-4 — `deal.buyer_company_id`
- **Objective:** a deal links a seller company to a buyer company.
- **Required change:** `deal.buyer_company_id` FK → `exporter_profile.customer_id` (RESTRICT), `CHECK (buyer_company_id IS NULL OR buyer_company_id <> company_id)`, added to `prevent_terminal_deal_change()`. `DealService.set_buyer` takes a company (or creates one via P4-3); `_NEEDS_BUYER` checks `buyer_company_id` once the cut-over flag is on; `_handover_snapshot` builds the snapshot from the buyer company (+ contact) into `handover_snapshot` (P2-7). Response: `buyer_company` summary masked per role; `buyer` (legacy) still served read-only until P4-10.
- **Frontend:** buyer picker in `DealDetailPage.tsx` (replaces `BuyerForm`), with P4-3.
- **Database:** column, check, trigger function update.
- **Migration:** backfill in P4-6.
- **Tests:** `test_l3b_deal_buyer.py` rewritten for companies; seller ≠ buyer; terminal freeze includes the new column (raw SQL); masking; OpenAPI.
- **Dependencies:** P4-1, P2-7.
- **Acceptance criteria:** a deal can record a buyer company; handover snapshots it.

### P4-5 — Checks on the company, whatever its role
- **Objective:** buyer checks become company checks (decisions D and the rewrite of 9).
- **Current state:** BUYER results keyed by `deal_buyer.id`; history on the seller timeline; `share_lock_companies` locks the seller for buyer inputs.
- **Required change:** `verification_result.subject_company_id` (FK, nullable), set on every new EXPORTER-subject result (= `entity_reference`) and on buyer-company checks; frozen once set (add to `trg_verification_result_input_immutability`). New buyer checks are recorded against the buyer **company** (entity type `EXPORTER`, read as "company subject"; renaming the enum is not worth it). History goes to the buyer company's timeline with `deal_id` context. Seam: `company_inputs` reads by `subject_company_id` (legacy rows by `entity_reference`). `buyer_checks(deal_buyer_id)` stays for legacy reads only.
- **Frontend:** `BuyerChecks.tsx` replaced by a link to the buyer company's background-check panel plus a compact "buyer sanctions/AML" summary on the deal.
- **Tests:** `test_l4b_buyer_checks.py`, `test_l4b_evidence_and_subjects.py`, `test_exp2_verification_service.py`, seam tests.
- **Dependencies:** P4-4, P0-2.
- **Acceptance criteria:** one set of checks per company; a company that is buyer in deal 1 and seller in deal 2 shows the same results in both.

### P4-6 — Buyer migration (checkpoint)
- **Objective:** existing deal buyers become companies without losing history. Details in §17.2.
- **Required change:** a mapping table `deal_buyer_company_map(deal_buyer_id PK, company_id, match_rule, matched_by, matched_at, run_id)` and an idempotent command `python -m app.modules.onboarding.migrate_deal_buyers --dry-run | --apply --run-id …` that reports, lets a person confirm name-only duplicates, creates `NOT_IN_PIPELINE` companies, fills `deal.buyer_company_id` and `verification_result.subject_company_id`, and writes one history row per created company.
- **Tests:** migration tests on a fixture DB with duplicates, Indian buyers (PAN/GSTIN in `tax_id`), a buyer matching an existing seller, a buyer matching the deal's own seller (refused), terminal deals, BUYER results with snapshots, idempotent re-run.
- **Dependencies:** P4-1, P4-4, P4-5, P0-3, `pg_dump`.
- **Acceptance criteria:** the §17.2 validation queries all pass on every live DB.

### P4-7 — Handover guard on company-level compliance (final C)
- **Required change:** change `_party_compliance_blockers` (P3-4) to read the buyer **company's** current-cycle SANCTIONS/AML (must be PASSED, BQ-4), and keep reading the seller's (a FAILED result blocks, BQ-3). Share-lock **both** company rows in a fixed order (by `customer_id`) to avoid deadlocks with background-check writers. An expired or incomplete buyer background check is a warning, not a block (BQ-4 requires only sanctions and AML).
- **Tests:** concurrency (a flag on the buyer company during handover waits); deadlock ordering; e2e "B is seller and buyer; failed sanctions blocks both" if BQ-3 is confirmed.
- **Dependencies:** P4-5, P4-6, P3-4.
- **Acceptance criteria:** decision C holds on the unified model; the target diagram's case works (B fails sanctions: every deal where B is seller or buyer is blocked, naming B's role).

### P4-8 — Frontend: company roles and buyer-only companies
- **Required change:** company page section "Deals as seller / as buyer" (deals where `buyer_company_id = id`, served by a new `GET /exporters/{id}/deals?as=buyer`); buyer-only company page (identity, checks, documents, history; no qualification/conversation); deal page links to both companies; history for a buyer company includes deal rows where it is the buyer (read-side union; D8 applies).
- **Tests:** page tests for the three sample companies of the target diagram (A seller, B buyer-only then seller, C both).
- **Dependencies:** P4-4, P4-5.
- **Acceptance criteria:** the target's "same dashboard, three companies" view renders from sample data.

### P4-9 — Onboard a buyer into the pipeline
- **Required change:** `POST /exporters/{id}/pipeline` (Staff): `NOT_IN_PIPELINE → IN_PIPELINE`, journey starts at `LEAD` with its initial journey history row now. Existing checks remain; a later `QUALIFIED` on an already-`CLEAR` company promotes it through the existing path. No automatic move (source §8 "do not make buyers into Leads automatically").
- **Tests:** onboarding; promotion via qualification when already CLEAR; refusal when already in the pipeline.
- **Dependencies:** P4-1.
- **Acceptance criteria:** no new record is created; journey history starts at the onboarding moment.

### P4-10 — Contract step: retire `deal_buyer` writes
- **Required change:** after P4-6 validates everywhere: `PUT /deals/{id}/buyer` no longer writes `deal_buyer`; a trigger refuses `INSERT`/`UPDATE` on `deal_buyer`; `buyer` legacy field removed from the deal response (or kept read-only for one release); docs: rewrite decision 9 in `architecture.md`, `deal-and-buyer.md`, `event-envelope.md` (`deal.handed_over` payload), `history-row.md`. **Do not drop `deal_buyer`**: BUYER results and snapshots reference its ids.
- **Tests:** raw-SQL refusal; OpenAPI; frontend no longer calls the old shape.
- **Dependencies:** P4-6 on all environments.
- **Acceptance criteria:** no code path writes `deal_buyer`.

### P4-11 — Full-depth buyer checks (4.2, decision D)
- **Required change:** buyer-only companies run the same background check (start, cycles, maker-checker, B, expiry) with no special-casing; the deal page shows the buyer's gauge. Providers for foreign companies are P7 (manual meanwhile).
- **Tests:** a `NOT_IN_PIPELINE` company can be cleared with approval; it does not get promoted.
- **Dependencies:** P4-5, P3-1, P3-2.
- **Acceptance criteria:** source §7 4.2.

---

## 12. Phase 5 — Trade History

Implements R2 (the buyer–seller trading history we underwrite). Lives inside `onboarding` (§5.2 F-14). Every new record carries `created_by` + `source` so P7-4 needs no retrofit. Decision G ("build both together") is honoured by running P5 alongside P4-11 (full buyer checks); both start once P4-4 exists.

### P5-1 — Trade relationship model
- **Objective:** one record per (seller, buyer) pair.
- **Required change:** `trade_relationship(id, seller_company_id FK, buyer_company_id FK, created_by, created_at, source)`, unique `(seller_company_id, buyer_company_id)`, `CHECK seller <> buyer`; `deal.relationship_id` FK, set automatically when a deal records its buyer company (get-or-create in the same transaction).
- **Tests:** uniqueness; auto-link; concurrency (two deals for the same new pair → one relationship).
- **Dependencies:** P4-4. **Parallelization:** with P6 and P4-11.
- **Acceptance criteria:** every deal with a buyer company has a relationship.

### P5-2 — Invoice and outcome model
- **Required change (PROPOSED):** `trade_invoice` (identity fixed once set by trigger: `relationship_id`, `deal_id` NULL for past trade, `invoice_number`, `invoice_date`, `amount Numeric`, `currency` (IQ-4), `created_by`, `source`), unique `(relationship_id, invoice_number)`; `trade_invoice_outcome` (append-only superseding chain like `verification_review`: `payment_status` PAID/UNPAID/PARTIAL/DISPUTED/UNKNOWN, `amount_paid`, `proof_status` PROVEN/CLAIMED, `evidence_note`, `evidence_refs`, `recorded_by/at`, `supersedes_outcome_id`).
- **Tests:** chain integrity; append-only raw SQL; evidence shape.
- **Dependencies:** P5-1.
- **Acceptance criteria:** an invoice's payment story is a chain; nothing is edited.

### P5-3 — Relationship API
- **Required change:** `GET /exporters/{id}/trade-relationships` (as seller and as buyer), `GET /trade-relationships/{id}` (invoices + current outcome), roles Staff read, DEVELOPER per IQ-19.
- **Dependencies:** P5-1.

### P5-4 — Invoice and outcome API
- **Required change:** `POST /trade-relationships/{id}/invoices`, `POST /trade-invoices/{id}/outcomes` (roles IQ-19); evidence validated like verification evidence; history `dimension='trade'` on the seller's timeline (and the buyer's by read-side union).
- **Dependencies:** P5-2.

### P5-5 — Backfill relationships for existing deals
- **Required change:** after P4-6: create relationships for every deal with `buyer_company_id`; set `deal.relationship_id` (the terminal-deal trigger must allow this one-time set, or the column is added to the trigger only after the backfill).
- **Dependencies:** P4-6, P5-1.

### P5-6 — Record the payment outcome after handover
- **Required change:** on a `HANDED_OVER` deal, "Record outcome" creates the invoice (if absent) and an outcome; not a deal stage (source §3.3).
- **Dependencies:** P5-4.
- **Acceptance criteria:** source §4 step 8.

### P5-7 — Trade history UI
- **Required change:** relationship panel on the deal page ("Company A → Company B", invoices with status chips, like the target diagram) and on the company page; `EvidenceList` for proof.
- **Dependencies:** P5-3, P5-4.

### P5-8 — Claimed past trade
- **Required change:** add past invoices with `deal_id NULL` and `proof_status=CLAIMED`, shown as "No proof yet".
- **Dependencies:** P5-4.

---

## 13. Phase 6 — GST Registrations and Branches

**Ordering change, justified by the code:** 6-A (P6-1…P6-5) touches only the company record and `exporter_gstin`, not `deal_buyer` or the verification seam, so it can start after P4-1 lands, in parallel with P4-3…P4-6. 6-B (P6-6, P6-7) edits `deal` and the handover guard and should follow P4-4/P4-7 to avoid conflicting migrations on the same trigger function and guard.

### P6-1 — Evolve `exporter_gstin` into GST registrations
- **Objective:** R3's per-branch record.
- **Recommendation:** extend `exporter_gstin` in place (API name "GST registrations") instead of creating `gst_registration` and copying. Rows, FK and repository stay; nothing has to be moved.
- **Required change:** `state_code` (chars 1–2), `state_name` (from a static state-code reference list), `status` (`UNVERIFIED` default | `ACTIVE` | `CANCELLED` | `SUSPENDED`), `address`, `flag_status` (`NONE`/`FLAGGED`), `flag_reason`, `active` (soft-deactivation), `deactivated_at/by`. Remove `delete-orphan` from `gstin_rows` and refuse `DELETE` by trigger.
- **Migration:** derive `state_code`/`state_name`; unknown codes reported (the regex accepts any two digits).
- **Tests:** derivation; no delete (raw SQL); ORM drift.
- **Dependencies:** P4-1 merged (same entity file).
- **Acceptance criteria:** every GSTIN row has a state; none can be deleted.

### P6-2 — Registration edit API
- **Required change:** `POST /exporters/{id}/gst-registrations`, `POST …/{gstin}/deactivate`; `PATCH /exporters/{id}` stops accepting `gstins` (or maps to add-only for one release). History `dimension='gst_registration'` (masked GSTIN).
- **Tests:** `test_company_identity.py`, `test_company_record_0014.py`, `test_profile_edit_history.py`, frontend `CompanyPanel`.
- **Dependencies:** P6-1.

### P6-3 — One GSTIN, one company (DROPPED on 1 October)
- **Decision (IQ-9):** GSTIN duplicates stay **warn-only**; decision 4 is kept. No global unique index and no "match instead of warn". This departs from source §3.3/§7 4.4 (a PROPOSED design) by the lead's choice.
- **Consequences to build in instead:**
  - `uq_exporter_gstin_customer_gstin` (unique per company) stays the only uniqueness rule.
  - A branch flag (P6-5) belongs to one company's row. When a flagged GSTIN is also held by another company, the flag action and both company pages show "this GSTIN is also on company X".
  - A deal's invoicing branch (P6-6) is a row id, not a GSTIN string, so it can never point at the other company's copy.
  - Buyer matching by GSTIN may return two companies (`POSSIBLE_DUPLICATE`); the RM chooses (P4-3).
  - P0-3 still reports duplicates so they are known; clean-up stays manual.
- **Tests:** a flag on one holder warns on the other; P4-3 returns both holders for a shared GSTIN.
- **Dependencies:** P6-1, P6-5.

### P6-4 — PAN from GSTIN for PAN-less companies
- **Required change:** for companies with `pan IS NULL` whose active GSTINs embed one PAN held by no other company, set `pan` (profile history row, masked); conflicts reported. Optional under IQ-9 (duplicates allowed): run it only if the P0-3 report shows PAN-less companies worth fixing.
- **Dependencies:** P6-1.

### P6-5 — Flag a branch
- **Required change:** `POST /gst-registrations/{id}/flag` / `…/unflag` (COMPLIANCE, ADMIN; reason required), history row, company warning chip "1 branch flagged".
- **Dependencies:** P6-1.
- **Acceptance criteria:** target diagram's "Flagged" branch row renders.

### P6-6 — Deal invoicing branch
- **Required change:** `deal.seller_gst_registration_id` FK (must belong to the seller; checked in service and by a composite FK `(seller_gst_registration_id, company_id)` → `(id, customer_id)` if a unique key is added); may be set any time before handover (IQ-20, answered); added to the terminal-deal trigger; legacy deals `NULL`.
- **Dependencies:** P6-1, P4-4 (same table/trigger).

### P6-7 — "Invoicing branch is flagged" in the guard
- **Required change (BQ-6, IQ-20 answered):** a deal whose invoicing branch is flagged is blocked ("invoicing branch Maharashtra is flagged"); deals from other branches proceed, and the company shows a warning. A deal with no invoicing branch recorded is blocked at handover when the seller has at least one active GST registration ("record the invoicing branch"); sellers with no registration are not affected.
- **Dependencies:** P6-5, P6-6.

---

## 14. Phase 7 — External Integrations

**Status after 1 October:** P7-1, P7-2 and P7-3 are **deferred**. Checks stay manual this quarter (BQ-8), so decision B's KYB/AML/sanctions results and decision D's buyer checks are recorded manually. P7-4 is partly pulled forward: basic provenance is built into every new table now (BQ-7), and field-level provenance and consent wait for the DPDP meeting. P7-6's responsibility question is settled (BQ-9); automatic intake still waits for D12.

### P7-1 — Provider adapter foundation
- **Required change:** an async variant of `VerificationAdapter` (or run sync adapters in a threadpool); a provider route beside the manual route, or widening `ManualRouteProvider` (a **D7 amendment**); webhook/polling path through the existing `get_verification_status` + outcome freeze.
- **Dependencies:** none (can start early). **Risk:** blocking I/O in the event loop if skipped.

### P7-2 — Provider coverage spike
- **Required change:** confirm Sumsub (and alternatives) coverage for Indian PAN/GSTIN KYB, AML, sanctions, and foreign companies (decisions D + F). **UNKNOWN / NEEDS VERIFICATION.** The existing Sumsub client is the legacy applicant/SDK flow for people, not company KYB.
- **Dependencies:** commercial access.

### P7-3 — Provider adapter and routing
- **Required change:** adapter in `app/integrations/…` plus registration; normalised outcomes; "clear results pass automatically; flagged go to manual review" = a `PASSED` provider result is final, a `REVIEW`/`FAILED` result needs a compliance review. The gauge move stays manual under maker-checker unless the lead decides otherwise.
- **Dependencies:** P7-1, P7-2, BQ-8.

### P7-4 — Data provenance (R4)
- **Now (BQ-7, answered):** every new table in P3–P6 (approvals, cycles, required documents, GST columns, trade relationship/invoice/outcome, buyer companies) carries `created_by`, `created_at`, `source` (MANUAL/CSV/RXIL/PROVIDER/MIGRATION) and `source_ref` (free text: where the data came from). No retrofit of existing tables yet.
- **After the DPDP meeting:** extend to existing business records and field level if required; history `event_metadata` carries the provenance of the change.
- **Dependencies:** BQ-7 for the second half only.

### P7-5 — Consent records
- **Required change:** shape pending the DPDP meeting; reconcile with 7-year no-delete retention.
- **Dependencies:** BQ-7.

### P7-6 — RXIL results intake and attestation
- **Objective:** R8 — ANER runs its own checks and yearly re-KYC on RXIL companies and keeps RXIL's AML report as evidence with its source and date (BQ-9, answered). Until D12 arrives, an RXIL report can already be uploaded as a company document and cited as evidence on a manual AML result. That needs no new code.
- **Required change:** real `RxilAdapter` (replacing `StubRxilAdapter`, same protocols); RXIL's attestation stored as evidence with source and date; RXIL companies still go through ANER's own check; machine identity (never `API_USER`).
- **Dependencies:** D12 (the package specification and machine identity). J is settled (BQ-9).

### P7-7 — Precondition for real data (outside the change plan, listed for completeness)
- Field-level encryption of tax identifiers, a real scanner, S3 with Object Lock (gate §7.6). Source §8: "Do not load real customer data until tax identifiers are encrypted and the DPDP rules are known."

---

## 15. Dependency Map

### 15.1 Chains

```
Company unification (keystone)
  P2-7 persisted handover snapshot
    → P4-1 identity + pipeline_status
      → P4-3 buyer match/create  (BQ-2 answered: exact match, name only)
      → P4-4 deal.buyer_company_id
        → P4-5 subject_company_id + seam v2 (needs P0-2)
          → P4-6 BUYER MIGRATION  ◆ checkpoint
            → P4-7 company-level handover guard (needs P3-4; BQ-3/BQ-4 answered)
            → P4-10 retire deal_buyer writes
            → P5-5 relationship backfill → P5 trade history UI/outcomes
      → P4-11 full buyer checks (needs P3-1, P3-2)

GST
  P4-1 → P6-1 evolve exporter_gstin → P6-2 edit API → P6-5 branch flag
                                   → P6-3 warn-only consequences (IQ-9: no uniqueness) ; P6-4 PAN backfill optional
  P4-4 + P6-1 → P6-6 deal invoicing branch → P6-7 guard (BQ-6 answered)

Verification cycles
  P0-2 seam v2 → P2-3a cycle model → P2-3b cycle-scoped seam → P2-3c Re-KYC/Re-KYB → P2-3d UI
                                   → P3-2 KYB/AML/sanctions in current cycle
  P2-4a rules_version → P3-3a expires_at → P3-3b guard/reader → P3-3c Home "Re-KYC due"

Maker-checker
  P0-5 fixtures → P3-1a schema → P3-1b service/API → P3-1c UI ; P3-1d suite/sample migration
  P3-1 → P4-11 (buyers inherit approval)

Handover guard (one function, many writers — serialise edits)
  P2-5b required documents → P3-3b expiry → P3-4 buyer sanctions/AML → P4-7 company-level → P6-7 branch
```

### 15.2 Task matrix (major tasks)

| Task | Must exist first | DB changes | APIs that depend on it | Screens that depend on it | Migrations that depend on it | Tests to change | Parallel with | Blocked by |
|---|---|---|---|---|---|---|---|---|
| P1-1 criteria | – | inserts | – | qualification panel | – | `test_qualification.py`, sample | all P1, P2 | BQ-1 (values) |
| P2-1 evidence | – | screening column | decisions read | BC panel | – | BC/screening tests | P2-2..7 | – |
| P2-3 cycles | P0-2 | table + FKs | seam, BC read, cycles route | verification/screening/decision UI | P3-2, P3-3 | seam contract, rules, 4B tests | P2-1/2/5/6/7 | IQ-3 |
| P2-4 website | – | `rules_version` | create/patch/CSV | forms, import | P3-3 | 11 catalogue tests, website/import tests | P2-1/2/5/6/7 | – |
| P2-5 required docs | – | settings table | guard | settings, deal page | – | handover tests | yes | IQ-10 (to switch on) |
| P2-7 snapshot | – | deal column + trigger | deal read | deal page | P4-4, P4-6 | 0022 guard tests, handover | yes | – |
| P3-1 maker-checker | P0-5 | 2 tables + columns | BC routes | BC panel, Home | – | all CLEAR tests | P3-2, P3-3, P4-1..4 | IQ-1 |
| P3-2 rule B | P2-3b | – | BC read | checklist | – | rules/service/e2e | P3-1 | IQ-2 |
| P3-3 expiry | P2-4a | columns | BC read, search filter | Home, gauge | – | reader/guard | P3-1 | BQ-5 (release) |
| P3-4 buyer guard | – | – | deal read | deal page | – | handover, buyer checks | P3-1..3 | BQ-3 |
| P4-1 identity | P0-1 | columns | create/patch/search | forms, lists | P4-*, P6-1 | identity/record tests | P3 | IQ-6, IQ-7 |
| P4-4 buyer FK | P4-1, P2-7 | column + trigger | deal routes | deal page | P4-6, P5-1, P6-6 | deal/buyer tests | P4-3 | – |
| P4-5 company checks | P4-4, P0-2 | column + trigger | verification, seam | BuyerChecks → company | P4-6 | 4B tests | – | – |
| P4-6 migration | P4-1/4/5, P0-3 | mapping table | – | – | P4-7, P4-10, P5-5 | new migration tests | P6-1..5 | IQ-8 duplicates policy |
| P5 trade | P4-4 (P4-6 for backfill) | new tables | new | new | – | new | P6, P4-11 | IQ-19 |
| P6-A GST | P4-1 | columns + unique | registrations API | company panel | P6-6 | identity/import tests | P4-3..6 | IQ-9 |
| P6-B branch on deal | P6-1, P4-4 | column + trigger | deal routes | deal page | – | handover | P5 | BQ-6 |
| P7 | varies | varies | varies | varies | – | – | anything | BQ-7, BQ-8, BQ-9 |

---

## 16. Execution Sequence

### 16.1 Change to the source ordering, and why

The source says "Work Phase 1 → 4" with Phase 4 after Phase 3. The repository shows:

1. P4's first tasks (P4-1 identity/pipeline, P4-4 buyer FK) touch `exporter_profile`/`deal`/`deal_buyer` and depend on nothing in P2/P3 except **P2-7** (the snapshot). Starting them late only lengthens the critical path.
2. The real ordering constraints between P3 and P4 are narrow: P4-7 needs P3-4's guard helper; P4-11 needs P3-1/P3-2. Both are late P4 tasks.
3. P2-3 cycles and P4-5 both change the frozen seam; designing both in **P0-2** avoids two contract breaks.
4. GST 6-A depends only on P4-1 (§13), so it need not wait for trade history or full buyer checks.
5. All guard changes (P2-5b, P3-3b, P3-4, P4-7, P6-7) edit one function (`_handover_blocked_reason`) and the terminal-deal trigger. They must be serialised through one owner, not parallelised.

The phase numbering stays; phases overlap.

### 16.2 Sequence

```
P0 (decisions, seam v2, inventory, conventions, fixtures)
 ├─ Lane A (settings/UX):  P1-1..P1-5 → P2-1, P2-2, P2-5, P2-6 → P2-4 → P2-3 → P3-2, P3-3
 ├─ Lane B (compliance):   P2-7 → P3-1 (a→b→c, d) → P3-4
 └─ Lane C (keystone):     P4-1 → P4-2, P4-3, P4-4 → P4-5 → ◆P4-6 MIGRATION CHECKPOINT
                                   → P4-7 → P4-8, P4-9 → P4-10 → P4-11
                          after P4-1:  P6-1 → P6-2 → P6-5 → P6-3 (warn-only consequences) ; P6-4 optional
                          after P4-4/P4-6: P5-1 → P5-2 → P5-3/P5-4 → P5-5 → P5-6/P5-7/P5-8
                          after P4-7:  P6-6 → P6-7
 P7: P7-4 (basic provenance) is built into P3–P6; P7-1/2/3 deferred (manual checks);
     P7-5 waits for DPDP*; P7-6 waits for D12*
 (* = waits on an external party)
 (P1-3 deferred: thresholds stay USD)
```

- **Critical path:** P0-2 (seam v2) → P2-7 → P4-1 → P4-4 → P4-5 → P4-6 → P4-7 → P4-10 → P5. (P0-1 is done: all questions answered on 1 October.)
- **Parallel work:** Lanes A and B throughout; P6-A beside P4-3…P4-6; P5 beside P6-B and P4-11; P7-1/P7-2 anytime.
- **Blockers (after 1 October):** none inside the build. External only: the DPDP meeting (consent P7-5, any real data) and RXIL's D12 specification (P7-6 automatic intake). Provider work is deferred by choice (BQ-8).
- **Architectural keystone:** P4-4 + P4-5 (buyer as a company record with company-level checks).
- **Migration checkpoint:** P4-6 on every live database, with backup, dry-run report, human confirmation of name-only duplicates, and all §17.2 validation queries green, before P4-7/P4-10/P5-5 start.

---

## 17. Migration Strategy

### 17.1 Conventions (all migrations)

- Next revisions from `onboarding_0023_*`, ids ≤ 32 characters, one head after every merge.
- **Expand → backfill → contract.** Add nullable columns/tables; backfill with an idempotent step; add `NOT NULL`/unique/trigger rules only after validation.
- **Append-only tables are never updated** (history, decisions, evidence, screening rows, criteria, outcomes, reviews). Legacy rows are interpreted by documented read rules (`cycle_id NULL` = cycle 1; `rules_version NULL` = v1 8-item rules; `expires_at NULL` on a CLEAR decision = `decided_at + 1 year`). Disabling a protective trigger to backfill is **not** recommended; if ever unavoidable, it needs a written exception.
- `pg_dump` of every live DB before any data migration; the dry-run report is attached to the ticket.
- Downgrades: schema-only migrations drop what they added. Data migrations that write history rows cannot be undone by deleting (append-only + RESTRICT FKs), so their recovery is **restore from backup** or a **logical rollback** (clear the new FK columns, mark created records by `run_id`), and each says which.

### 17.2 Company unification — buyer migration (highest risk)

**Inputs.** `deal_buyer` rows (name, country, registration_number, tax_id, contact_email, contact_phone); their deals (stage); BUYER `verification_result` rows (`entity_reference = deal_buyer.id`, `subject_snapshot`); deal documents in category `BUYER`; seller-timeline history rows (`deal_buyer_changed`, BUYER verification rows with `deal_id`).

**Identity resolution** (deterministic first, human for the rest):
1. Normalise: trim/case-fold the name and strip legal suffixes (Pvt Ltd, Private Limited, LLC, GmbH, BV, …) for comparison only; upper-case country; normalise registration numbers (strip spaces/dashes).
2. `country = IN` and `tax_id` matches `PAN_RE` or `GSTIN_RE` → PAN (embedded for a GSTIN) → `CompanyMatcher`: `MATCHED` joins an existing company (possibly an existing seller, which is the R1 case), `CONFLICT` is reported.
3. Foreign: same `(country, normalised registration_number)` across deal buyers → one company; matching an existing company's `(country, registration_number)` → join it.
4. Same `(country, normalised name)` with no identifier → **possible duplicate**: reported and not auto-merged; a person confirms in the dry-run report (IQ-8).
5. A buyer resolving to the deal's own seller → refused; reported for manual correction.

**Duplicate merging.** Only through steps 2–3 (hard identifiers) or explicit human confirmation of step 4. The merge is *logical*: several `deal_buyer` rows map to one company in `deal_buyer_company_map`. No company-to-company merge is performed (not built).

**Creation.** Each new company: `pipeline_status=NOT_IN_PIPELINE`, `created_via=DEAL_BUYER`, `created_via_deal_id` = earliest deal, `identity_type` per identifiers (foreign buyers without a registration number keep it `NULL` and go on the completion list, IQ-7), `source=DEAL_BUYER` (IQ-6), contacts from buyer email/phone (as a contact record, masked as today). One history row on the new company (`dimension='pipeline'`, event `company_created_from_deal_buyer`, details `{run_id, deal_buyer_ids, deal_ids, match_rule}`) and no journey row.

**Buyer checks.** Set `verification_result.subject_company_id` for BUYER rows from the map (a new column, set once, then frozen). `entity_type`/`entity_reference`/`subject_snapshot` stay untouched. The buyer company's background check starts `NOT_STARTED`; results remain valid inputs; decision C reads results, not the gauge.

**History.** Existing rows stay on the seller timeline (they cannot move). The buyer company's timeline shows them by a read-side union on `deal_id`. No history rewrite.

**Deal references.** `deal.buyer_company_id` from the map; `deal_buyer` rows untouched, then write-refused in P4-10; never dropped.

**Frozen snapshots.** Guaranteed by P2-7 before this runs: `HANDED_OVER` deals carry `handover_snapshot` taken from `deal_buyer`, so later edits to the buyer company do not change what was handed over.

**Rollback.** Before contract (P4-10): logical rollback = `UPDATE deal SET buyer_company_id = NULL WHERE …run_id`, `UPDATE verification_result SET subject_company_id = NULL` (needs the freeze trigger to allow NULL→value only, so do the rollback before enabling it, or restore). Companies created by the run stay, marked by `run_id`, `NOT_IN_PIPELINE` and unreferenced (history rows prevent deletion). After contract: restore from backup.

**Validation queries (all must return 0 / match).**
- deals with a `deal_buyer` and `buyer_company_id IS NULL`;
- BUYER results with `subject_company_id IS NULL`;
- deals with `buyer_company_id = company_id`;
- map rows ≠ `deal_buyer` rows;
- created companies without exactly one creation history row;
- `HANDED_OVER` deals without `handover_snapshot`;
- any value containing the mask character `•` in migrated identifiers;
- re-running the command creates nothing (idempotency);
- per-environment counts equal the dry-run report.

### 17.3 GST migration

- **Existing GSTIN data:** extend rows in place (P6-1); derive `state_code`; map to `state_name` from a static list; unknown codes reported; `status='UNVERIFIED'` (the CRM has never verified a registration).
- **Duplicate GSTINs:** P0-3 finds GSTINs on more than one company. They can only exist where at most one of those companies has a PAN (PAN is unique and must be embedded). **Per IQ-9 (1 October) they stay as they are**: no unique index and no forced clean-up. The migration only reports them, and flags/branches work per company row (P6-3 consequences).
- **PAN matching:** PAN-less companies whose GSTINs embed a PAN held by no other company get `pan` set (profile history row); a PAN already held elsewhere is a conflict report (likely the same entity twice).
- **State derivation:** chars 1–2; the reference list is data (a module constant or YAML beside the document types).
- **Existing deals:** `seller_gst_registration_id` stays `NULL`. Terminal deals are historical; open deals ask the RM before handover (IQ-20). No guessing, even when a seller has one registration, unless the business agrees.
- **Rollback:** columns droppable; PAN backfill recorded in a small audit table (`company_id`, previous `NULL`, new value, `run_id`) so it can be reversed.

### 17.4 Other migrations

| Change | Legacy data | Approach |
|---|---|---|
| Criteria (P1-1) | v1 rows | Insert v2 rows; announce the de-count effect |
| Reason codes (P1-2) | 9 codes | Update `active`/labels; insert new |
| Screening evidence (P2-1b) | append-only rows | `ADD COLUMN … DEFAULT '[]'` (DDL) |
| Cycles (P2-3a) | inputs without cycle | Insert cycle 1 per company; `NULL` = cycle 1 |
| `rules_version` (P2-4a) | CLEAR decisions | `NULL` = v1 by rule |
| Handover snapshot (P2-7) | `HANDED_OVER` deals | Backfill from `deal_buyer` + history `document_ids`, before the trigger covers the column |
| Expiry (P3-3a) | CLEAR decisions / CLEAR companies | Decision `NULL` = +1 year by rule; profile current value backfilled |
| Identity/pipeline (P4-1) | all companies | `IN_PIPELINE`; `created_via` from first history row |

---

## 18. Testing Strategy

### 18.1 By phase

| Phase | Unit | API | Integration | Authorisation | Regression | Migration | Concurrency | Audit/history | Masking |
|---|---|---|---|---|---|---|---|---|---|
| P1 | criteria suggestion with optional IEC; formatters; `roleLabel` | criteria versions | qualification flow | criteria ADMIN-only unchanged | QUALIFIED companies unchanged | 0023 data migration test | – | – | – |
| P2 | `ClearPolicy` over cycle-scoped inputs; screening evidence shape | evidence resolution; cycles; required docs; CSV both headers | Re-KYC end-to-end | D8 on evidence and cycles; required-docs ADMIN | legacy CLEAR decisions still render 8 items | cycle 1 creation; snapshot backfill | two cycle starts at once | `check_cycle` rows; screening evidence | evidence views carry no identifiers |
| P3 | policy B; expiry maths with injected clock | propose/approve/reject/withdraw; Home filter | e2e with two users | proposer ≠ approver; OPERATIONS never approves | promotion on approval only | expiry backfill | approve vs reject race; approval after input change → 409 | every approval step in history | – |
| P4 | identity normalisation; match kinds | match-or-create; buyer set; onboarding | company as buyer and seller in two deals | OPERATIONS match behaviour per BQ-2 | seller flows unchanged | buyer migration fixtures (§17.2) | handover locks both companies (ordering) | creation rows; buyer timeline union | buyer company identifiers masked like companies; snapshot masked |
| P5 | outcome chain | invoices/outcomes | outcome after handover | roles per IQ-19 | – | relationship backfill | two deals, one new pair | `trade` rows | DEVELOPER per IQ-19 |
| P6 | state derivation; GSTIN/PAN rules | registrations; flag | flagged branch blocks handover | flag COMPLIANCE/ADMIN | company edit without GSTIN list | duplicate report; PAN backfill | flag during handover waits | `gst_registration` rows | GSTIN masked in history |
| P7 | adapter normalisation | provider route | webhook/poll with outcome freeze | machine identity ≠ API_USER | manual route unchanged | – | poll vs review race (existing trigger) | provider provenance | raw results never served to masked roles |

### 18.2 Existing tests that must change

- **Buyer model:** `test_l3b_deal_buyer.py`, `test_l3b_handover.py`, `test_l4b_buyer_checks.py`, `test_l4b_evidence_and_subjects.py`, `test_exp2_verification_service.py`, `test_exp3_stub_rxil_adapter.py`, `test_l4a_background_check_reader.py`, `test_l4a_background_check_service.py`, `test_l4b_compliance_inputs.py`, `unit/test_l4b_compliance_inputs_contract.py`; frontend `DealDetailPage.test.tsx`, `BuyerChecks.test.tsx`, one more referencing buyer shapes.
- **Screening catalogue / website item:** `test_crm_end_to_end.py`, `test_customer_promotion.py`, `test_e9_screening_review_service.py`, `test_l4a_background_check_repository.py`, `test_l4a_background_check_schema.py`, `test_l4b_compliance_inputs.py`, `test_l4b_screening_integrity.py`, `test_l4b_verification_schema.py`, `test_route_authorization.py`, `unit/test_l4b_compliance_inputs_contract.py`, `unit/test_l4b_verification_integrity_rules.py`; frontend `ScreeningChecklist.test.tsx` and one more.
- **Website field:** `test_company_website.py`, `test_company_import.py`, RXIL intake tests, `AddExporterPage.test.tsx`, `CompanyImportPage.test.tsx`.
- **GSTIN:** `test_company_identity.py`, `test_company_record_0014.py`, `test_profile_edit_history.py`, `test_company_import.py`, `test_rxil_intake.py`, frontend `ExporterDetailPage.test.tsx`.
- **Maker-checker / Clear rule:** `test_l4a_background_check_service.py`, `test_l4a_background_check_api.py`, `unit/test_l4a_background_check_rules.py`, `test_customer_promotion.py`, `test_crm_end_to_end.py`, `BackgroundCheckPanel.test.tsx`.
- **Handover guard:** `test_l3b_handover.py`, `test_crm_integrity_guards_0022.py` (trigger function changes), `unit/test_crm_handover_events.py` (event payload).
- **Always:** `test_route_authorization.py` (one row per new route), `tests/contract/test_openapi_artifact_is_current.py` (regenerate `openapi.json` and `schema.ts`), `tests/contract/test_orm_matches_the_onboarding_schema.py`.

### 18.3 Missing tests to add

- Raw-SQL tests for every new append-only table and every trigger extension (P2-7, P3-1a, P4-5, P5-2, P6-1).
- A migration test harness that runs each data migration on a fixture DB seeded with the §17.2/§17.3 edge cases and asserts the validation queries.
- Two-user e2e: lead → qualified → check with approval → customer → deal with buyer company → required docs → handover → outcome.
- Concurrency: handover vs flag on the buyer company; approve vs new input; cycle start vs decision.
- Masking sweep: a parametrised test calling every CRM read as OPERATIONS and DEVELOPER and asserting no unmasked PAN/GSTIN/IEC/CIN/registration number/contact appears (today masking is tested per route).

---

## 19. Open Questions

Agreed decisions (A–K, source §5) are not reopened here. Items marked "to confirm" in the source are listed as questions.

### 19.0 Answered on 1 October 2026

Answered by the programme lead in this session. Where any other section of this file disagrees, this table wins.

| # | Answer | Effect on the plan |
|---|---|---|
| BQ-1 | **Keep the USD thresholds; no change** to revenue (USD 100,000,000) or deal size (USD 50,000) | P1-1 is reduced to making IEC and export history not required. No threshold version bump, so no de-count of revenue/deal-size results. P1-3 (rupee display) deferred. Differs from source §7 1.1 ("change thresholds to rupee values"), by the lead's choice |
| BQ-2 | **Exact match, name only.** The RM may type a full PAN/GSTIN; the server names the matching company with identifiers still masked; exact match only, no partial search; every lookup audited | P4-3 unblocked; the same rule answers the duplicate-PAN message question (source §1.5 item 5) |
| BQ-3 | **Yes: a FAILED sanctions/AML result blocks every role.** The handover check reads the latest sanctions/AML results of **both** the seller and the buyer company | P3-4 and P4-7 read both parties; consequence 5.1.1 confirmed |
| BQ-4 | **Buyer's sanctions and AML must be PASSED** in the current cycle for handover. Missing = blocked; incomplete KYB or other checks = warning | P3-4/P4-7 require PASSED, not only "no FAILED". Buyer still gets the full check (D). Source §5.1 item 2 (confirming D with Bhargava) remains a courtesy confirmation |
| BQ-5 | **1 year from the last Clear** for companies already cleared | P3-3a backfill rule fixed |
| BQ-6 | **Block the flagged branch's deals;** other branches proceed with a warning on the company | P6-7 as assumed in decision H |
| BQ-7 | **Basic provenance now:** every new table records who, when and from where (`created_by`, `created_at`, `source`, `source_ref`); no consent model and no real data until the DPDP meeting | Applied to every new table in P3–P6; consent (P7-5) still waits |
| BQ-8 | **Stay manual for now;** no provider work this quarter | P7-1, P7-2, P7-3 deferred; KYB/AML/sanctions for decision B are recorded manually; the "Automated" filter stays empty |
| BQ-9 | **ANER re-checks RXIL companies;** RXIL's AML report is stored as evidence with its source and date | P7-6 responsibility settled; automatic intake still needs the D12 specification |
| IQ-1 | Second approver on **CLEAR, FLAGGED, ON_HOLD**; not on MORE_INFO, start, answer, reassess or reopen | P3-1b scope fixed |
| IQ-2 | **Latest real result in the current cycle is PASSED, or REVIEW with an ACCEPTED review**; the latest result wins; placeholders never count | P3-2 rule fixed; the same meaning of "passed" applies to BQ-4 |
| IQ-3 | **Re-KYC on a CLEAR company reopens it at once** (reason "Re-KYC"); handovers pause until the new cycle is cleared | P2-3c as recommended |
| IQ-4 | **Store each invoice's currency; no conversion** | P5-2 |
| IQ-6 | New source value **`DEAL_BUYER`** for companies first created as a buyer | P4-1, P4-6 |
| IQ-7 | **Registration number required** for foreign companies; `(country, registration number)` unique | P4-1. Buyers migrated without a number (P4-6) are created with the number missing and listed for completion, since the rule cannot be met retroactively |
| IQ-8 | **Keep name-only matches separate;** Compliance reviews the migration report | P4-6 as recommended |
| IQ-9 | **Keep GSTIN duplicates warn-only** (decision 4 stays) | **P6-3 dropped**: no global GSTIN uniqueness and no "match instead of warn". Differs from source §3.3/§7 4.4 (PROPOSED design), by the lead's choice. Consequences in P6-3 |
| IQ-10 | Required before handover: **Pre-shipment** category only (Admin can change later) | P2-5a seeds one requirement; see P2-5a for the effect on sample data |
| IQ-11 | **By category; only scanned-clean (`AVAILABLE`) documents count** | P2-5b |
| IQ-12 | **Deactivate** the three export-specific reason codes | P1-2 |
| IQ-13 | **"RM" on every screen, including Settings → Roles;** the `OPERATIONS` value is unchanged | P1-5 also updates the built-in role's display name (data only) |
| IQ-14 | Screening evidence **optional** | P2-1b |
| IQ-16 | **Keep stored websites, hide them;** ignore websites in RXIL packages; old CSV files still import | P2-4b |
| IQ-17 | Maker-checker **always on; a switch may turn it off only in local/test**; the server refuses "off" elsewhere | P3-1b |
| IQ-18 | **No promotion to CUSTOMER on an expired Clear** | P3-3b |
| IQ-19 | **RM, Compliance and Admin record** invoices and outcomes; Developer reads masked; API user nothing | P5-3, P5-4 |
| IQ-20 | Invoicing branch **required before handover** when the seller has an active GST registration | P6-6, P6-7 |

Not asked; the recommended defaults stand: IQ-5 (no consumer of `deal.handed_over` yet) and IQ-15 ("Automated" excludes the RXIL stub).

**What still blocks after 1 October:** the DPDP meeting (consent, P7-5, and any real data); the RXIL D12 specification (automatic RXIL results intake); the provider choice, deferred by decision BQ-8.

### 19.1 BLOCKING (must be answered before the named task starts; all answered or deferred on 1 October, see 19.0)

| # | Question | Blocks | Source |
|---|---|---|---|
| BQ-1 | Exact rupee thresholds for annual revenue and deal size (the meeting mentioned 100,000 for deal size; currency and value unconfirmed) | P1-1 threshold part | source §6 |
| BQ-2 | Identifier disclosure: may the RM (masked role) search by, or be told the holder of, a PAN/GSTIN when matching a buyer or refusing a duplicate? | P4-3, P6-3 | source §1.5 item 5, §6; decision 12 |
| BQ-3 | Consequence 5.1.1: does a failed sanctions/AML result on a company block its seller deals too? If yes, the guard reads the seller's own results, not only the CLEAR gauge (§5.2 F-12) | P3-4, P4-7 | source §5.1 item 1 |
| BQ-4 | Confirm decision D with Bhargava (full checks for buyers). Must a **buyer's** check also be unexpired, or only sanctions/AML not failed? | P4-7, P4-11 | source §5.1 item 2 |
| BQ-5 | Existing Clears: expiry = 1 year from their last Clear? | releasing P3-3 | source §5.1 item 3 |
| BQ-6 | Decision H assumption: deals from a flagged branch blocked, others proceed with a warning? | P6-7 | source §5 H |
| BQ-7 | DPDP: data-source and consent rules; how the 7-year no-delete rule sits with DPDP rights | P7-4, P7-5, any real data | source §6 I |
| BQ-8 | Provider coverage: does Sumsub cover Indian PAN/GSTIN KYB, AML, sanctions, and foreign companies? Which provider for India? | P7-3; foreign-buyer checks under D | source §7 4.6 |
| BQ-9 | RXIL responsibilities (J) and the D12 package/machine-identity specification | P7-6 | source §6 J, D12 |

### 19.2 IMPORTANT (can be answered during implementation, but shape the design)

| # | Question | Affects | Recommended default |
|---|---|---|---|
| IQ-1 | Which background-check moves need approval? The diagram places "awaiting approval" before CLEAR, MORE INFO and FLAGGED | P3-1 | CLEAR, FLAGGED, ON_HOLD; not start, answer, reassess, reopen (confirm MORE_INFO) |
| IQ-2 | What counts as "passed" for KYB/AML/sanctions (B) and "failed" for C: latest result only? Does `REVIEW` + `ACCEPTED` count as passed? Does a later PASSED override a FAILED? | P3-2, P3-4 | Latest non-placeholder result in the current cycle; `PASSED`, or `REVIEW` with an `ACCEPTED` review |
| IQ-3 | Cycle semantics: does Re-KYC on a CLEAR company reopen it? Which check types are KYC vs KYB? Does a new cycle reset all screening items? Who may start one? | P2-3 | Reopen in the same transaction; screening resets; COMPLIANCE/ADMIN start |
| IQ-4 | Trade currency and FX: invoices in any currency; is conversion needed for reporting? Structured currency on criteria for foreign use (decision F)? | P5-2, later P1-3 | Store currency; no conversion |
| IQ-5 | `deal.handed_over` event payload change (buyer company + snapshot) — any consumer to warn? | P4-10 | None exists (no receiver) |
| IQ-6 | What `source` does a buyer-created company carry (`source` is NOT NULL and immutable)? | P4-1, P4-6 | New `ExporterSource.DEAL_BUYER`, or nullable for `NOT_IN_PIPELINE` |
| IQ-7 | Foreign identity: which registration number per country; is `(country, registration_number)` enough? Are foreign companies with no number allowed? | P4-1 | Required for `FOREIGN_REG`; normalised uniqueness |
| IQ-8 | Buyer migration: who confirms name-only duplicates, and is "keep separate + warning" acceptable when unsure? | P4-6 | Keep separate; warn |
| IQ-9 | Duplicate GSTINs across companies: deactivate on the duplicate, or build company merge? | P6-3 | Deactivate + "possible duplicate of X"; merge later |
| IQ-10 | The required-document list per deal | switching on P2-5b | – |
| IQ-11 | Required-documents rule: category or type level? Only `AVAILABLE` (scanned) documents count? | P2-5a, P2-5b | Category level; only `AVAILABLE` |
| IQ-12 | Which reason codes to retire or relabel, and which domestic codes to add | P1-2 | – |
| IQ-13 | Rename the built-in role display name "Operations" in the roles table as well as the UI? | P1-5 | UI label only (source §7 1.3) |
| IQ-14 | Evidence on screening items: required for PASSED? | P2-1b | Optional |
| IQ-15 | Does the "Automated" filter include the RXIL stub? What does "Flagged" mean for a result? | P2-2 | Exclude stub; FAILED or HIGH/CRITICAL |
| IQ-16 | Keep existing website values visible read-only, or hide them? Ignore `website` in RXIL packages? | P2-4b | Hide; ignore |
| IQ-17 | Is the maker-checker "config switch" wanted at all (demo convenience), and never off in production? | P3-1b | No switch, or local/test-only |
| IQ-18 | Promotion to CUSTOMER when the Clear has expired | P3-3b | Refuse |
| IQ-19 | Who records trade invoices and outcomes; may DEVELOPER read trade data? | P5-3, P5-4 | Staff record; DEVELOPER read masked |
| IQ-20 | Invoicing branch: required at deal open or only before handover? Blocking when unset? | P6-6, P6-7 | Before handover, when the seller has an active registration |

### 19.3 NON-BLOCKING (safe to defer)

- Placeholder verification results that can never stop blocking Clear (source §1.5 item 3): cycle scoping (P2-3b) removes the problem for new cycles; decide the legacy case when providers connect.
- Confirm U4 (CUSTOMER in one transaction); the target keeps it.
- Verify-GSTIN portal deep link format (UNKNOWN; the link can open the search page meanwhile).
- `pg_trgm` availability for name-similarity warnings (UNKNOWN; equality fallback exists).
- Group companies (different PANs) link (source §7 4.4, "later").
- Stale OPERATIONS description in `catalog.py`; the two screens still showing user ids.
- Retiring `GET /exporters/activities/pending`; cross-company Deals/Documents lists; the search `total`.
- Reload-burst sign-outs (open-items §1.2).
- CI (U6).

---

## 20. Risks

| # | Risk | Type | Rank | Why | Mitigation |
|---|---|---|---|---|---|
| R-1 | Buyer migration mis-merges or splits companies | Migration / data integrity | **HIGH** | No hard identifiers on most foreign buyers; merges drive compliance consequences (C + D); append-only history makes mistakes permanent | Hard-identifier-only auto-merge; human-confirmed name matches; dry run; mapping table; backup; validation queries |
| R-2 | Handover snapshot lost for already-handed-over deals | Data integrity | **HIGH** | Only `deal_buyer` holds it today and nothing freezes it at the DB | P2-7 before P4; trigger coverage |
| R-3 | Maker-checker bypass through an unconverted path (sample data, tests, a legacy route) | Compliance / authorisation | **HIGH** | Many code paths clear companies today; one missed path defeats decision A | DB check `approved_by <> decided_by`; required when `to_value` needs approval; grep audit; e2e |
| R-4 | Identifier disclosure to the RM through buyer matching | Authorisation / compliance | MEDIUM (was HIGH) | BQ-2 accepted disclosing the holder's name on an exact identifier match | Exact match only; identifiers stay masked in the answer; every lookup audited; a test that partial search is refused |
| R-5 | Silent de-count of qualification results when criteria change | Backward compatibility | MEDIUM | Undecided leads flip to a NOT_QUALIFIED suggestion | Release note; optional "re-record unchanged result" helper |
| R-6 | Consequence 5.1.1 misunderstood (gauge-only guard) | Compliance | MEDIUM→HIGH | A sanctioned company could still hand over seller deals while its gauge reads CLEAR | BQ-3; guard reads results of both parties |
| R-7 | The same GSTIN on two companies after branch flags exist: one copy flagged, the other not | Data integrity | MEDIUM | IQ-9 kept duplicates warn-only, so a branch problem can be recorded against one holder only | Flag action warns about other holders; both company pages show it; P0-3 report lets Compliance clean up by hand |
| R-8 | Frozen-seam and contract churn across developers | Architecture | MEDIUM | Three changes (cycles, buyer-as-company, required types) to one "frozen" contract | P0-2 single v2 revision |
| R-9 | Handover guard becomes a merge hotspot | Architecture | MEDIUM | Five tasks edit one function and one trigger | One owner; serialised merges; a condition-list structure |
| R-10 | Deadlocks when locking two companies at handover | Concurrency | MEDIUM | Seller and buyer rows locked by different transactions in different orders | Lock by sorted `customer_id`; tests |
| R-11 | `NOT_IN_PIPELINE` companies leaking into pipeline counts and lists | Frontend regression | MEDIUM | Journey stays `LEAD` for them | Server-side default exclusion; tests on every list |
| R-12 | CSV users' files rejected after website removal | Backward compatibility | MEDIUM | Exact header match | Accept both headers for a transition |
| R-13 | Manual entry of KYB/AML/sanctions for every seller and buyer (B + D) becomes a Compliance bottleneck while providers are deferred | Provider / operational | MEDIUM | BQ-8 keeps checks manual; decision B now requires three results per company per cycle | Watch Compliance workload in UAT; revisit BQ-8 with P7-2 (coverage spike) when volumes grow; P7-1 async plumbing is ready to build when needed |
| R-14 | DPDP outcome forces field-level provenance/consent retrofits | Compliance / architecture | MEDIUM | Unknown shape | `created_by` + `source` on every new table now |
| R-15 | Expiry logic makes currently-CLEAR sample companies expire on an unexpected date | Compliance | LOW | Sample data only; rule is configurable | BQ-5; injected clock tests |
| R-16 | Branding/RM label changes miss a screen | Frontend regression | LOW | Six known sites | Central label helper; bundle grep |
| R-17 | Sumsub legacy code mistaken for a CRM adapter | Provider / architecture | LOW | Name suggests reuse | Documented here (F-13) |
| R-18 | Trade history built as a separate module breaks import-linter | Architecture | LOW | Contract exists | Build inside `onboarding` |

---

## 21. Final Verdict

1. **Is the current architecture suitable for incremental extension?** Yes. Services own one concern each, the rules are data where it matters (`ClearPolicy`, `PERMITTED_STAGE_MOVES`, `allowed_moves`), masking is server-side, and every protected record has a DB guard. Every requirement in the source plan maps onto an extension point that already exists: policy fields, the seam, the guard function, new append-only tables, and the adapter protocol. No rewrite is needed.
2. **Biggest architectural limitation:** the buyer is a per-deal row (`deal_buyer`) that the compliance seam, verification subjects, history placement and masking are all keyed to. Combined with append-only tables that cannot be updated, this makes unification an additive re-keying (new FK columns plus a mapping table) rather than a move. Second: the 4A↔4B seam is "frozen", so it must be revised deliberately.
3. **Keystone:** P4-4 + P4-5 — `deal.buyer_company_id` plus checks keyed by company (`subject_company_id`), made safe by P2-7 (persisted handover snapshot) and completed by the P4-6 migration.
4. **What first:** P0-1/P0-2 (BQ-2, BQ-3, IQ-1–IQ-3 answered; seam v2 written), then in parallel: P1 (settings, labels, no schema risk), P2-7 (snapshot) and P4-1 (identity and pipeline status).
5. **What should NOT be started yet:** P4-6 buyer migration (until P4-1/P4-4/P4-5 and the inventory exist); P7-1–P7-3 provider work (deferred, BQ-8); P7-5 consent (until the DPDP meeting); P7-6 RXIL automatic intake (until D12); any work that loads real customer data. GSTIN uniqueness (P6-3) is dropped (IQ-9).
6. **Highest-risk migration:** the deal-buyer → company migration (§17.2), because identity resolution drives compliance consequences under C + D, and its history effects cannot be undone by delete.
7. **Decisions currently blocking implementation:** none inside the build since 1 October (§19.0). Still external: the DPDP meeting (consent, real data) and RXIL's D12 specification. Source §5.1 item 2 (confirming decision D with Bhargava) is worth closing before P4-11 ships, but it no longer blocks the design.
8. **Tasks that can safely run in parallel:** all of P1; P2-1, P2-2, P2-5a, P2-6, P2-7; P3-1 alongside P3-2/P3-3; P4-1…P4-4 alongside P2/P3; P6-1…P6-5 alongside P4-3…P4-6; P5 alongside P6-6/P6-7 and P4-11; P7-1/P7-2 anytime. Handover-guard edits must not run in parallel with each other.
9. **First engineering execution sequence:** P0-4 conventions → P0-5 fixtures → P1-4/P1-5 labels and P1-1 (IEC/export optional part) → P2-7 snapshot → P4-1 identity/pipeline → P2-1/P2-2 evidence and filters → P2-4 website + `rules_version` → P2-3 cycles → P3-1 maker-checker → P3-2 rule B → P3-3 expiry → P4-4 → P4-5 → P4-6 checkpoint → P4-7 → P5/P6.

---

## 22. First Implementation Tasks

Ordered; each is merge-sized and has no unanswered dependency except where noted.

| # | Task | Size | Why first | Done when |
|---|---|---|---|---|
| 1 | **P0-4** Migration and gate conventions written into `docs/development.md` / `migration-register.md` (0023+, expand/backfill/contract, backups) | S | Every later task relies on it | Conventions merged |
| 2 | **P0-3** Read-only data inventory on each live DB | S | Sizes P4-6 and P6-3; reveals duplicates | Reports attached |
| 3 | **P0-5** Second-approver fixtures + injectable clock | S | Keeps the suite green through P3 | Helper used by one test |
| 4 | **P1-4 / P1-5** "Aner Labs" branding and `roleLabel()` (RM) | S | No dependencies; visible to stakeholders | No "Operations"/old name on any screen; OpenAPI test green |
| 5 | **P1-1 + P1-2** Criteria versions making IEC and export history not required (USD thresholds unchanged); deactivate the three export reason codes | S | Fully decided | Domestic company gets a QUALIFIED suggestion; export codes gone from new decisions |
| 6 | **P2-7** Persist `deal.handover_snapshot`, extend the terminal-deal trigger, backfill | M | Prerequisite of the keystone; closes a real integrity gap | Every HANDED_OVER deal has an immutable snapshot |
| 7 | **P2-1a/b/c** Evidence per check (decision evidence resolution, screening evidence refs, UI) | M | Pure extension; high stakeholder value | Each check shows its evidence |
| 8 | **P2-2** Automated/manual filters | S | Frontend only | Filters work |
| 9 | **P4-1** Company identity + `pipeline_status` + `created_via` backfill + `DEAL_BUYER` source (IQ-6, IQ-7 answered) | M | Opens the keystone lane | Foreign buyer-only company can exist; lists unchanged (with P4-2) |
| 10 | **P0-2** Seam v2 and contract revisions agreed by owners | S (docs) | Gates P2-3 and P4-5 | Contracts updated |
| 11 | **P2-4a/b** Screening 8→7, `rules_version`, website removal with CSV transition | M | Needed by B and E | Checklist shows 7; old CSV still imports |
| 12 | **P2-3a–d** Check cycles and Re-KYC/Re-KYB | L | Needed by B and E | Two cycles visible; Clear scoped to current cycle |
| 13 | **P3-1a–d** Maker-checker | L | Decision A | No single-user Clear path remains |

After these: P3-2 → P3-3 → P3-4 (interim) → P4-4 → P4-5 → **P4-6 checkpoint** → P4-7 → P5 / P6 as in §16.
