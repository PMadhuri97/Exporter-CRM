# ANER CRM — Work Allocation for 3 Developers

| | |
|---|---|
| Date | 1 October 2026 |
| Based on | The implementation plan ([`plan.md`](plan.md), audited at `main` @ `632a824`). Task ids such as P2-3a and section numbers such as §17.2 refer to that plan |
| Decisions | A–K (30 Sep) and BQ/IQ answers (1 Oct, plan §19.0). Nothing here reopens them |
| Purpose | Split the plan into three lanes a developer can finish without waiting for another developer's feature code |
| Status | **Historical since 4 October 2026.** The three lanes are closed and one developer completes the project; what is still pending is in [`remaining-work.md`](remaining-work.md). Kept because the code, the contracts and the plan cite its sections ("allocation §2.2") |

---

## 1. How the split works

Complete independence from the first day isn't possible. The plan's keystone (a buyer is a company) needs columns on the company table, the deal table and the verification table, and those belong to three different areas. This allocation reduces that to one short step:

1. **Foundation week (days 1–4).** Each developer merges one small **foundation PR** containing only new columns, interfaces and stub components with their final props. Merge order: **F1 → F3 → F2**. Foundation PRs contain no feature logic, so they are quick to review.
2. **After the foundations merge, no one waits.** Each lane owns its own tables, files and screens. Where a lane needs something from another lane, it codes against the interface fixed in that lane's foundation and tests with a fake. When the other lane's real implementation merges, the behaviour switches on with no code change.
3. **Operational order only (not code dependencies):** the buyer migration (P4-6) and the trade-relationship backfill (P5-5) run on live databases in a set order (§6). Nobody's coding is blocked by that.

### Four design adjustments made to remove cross-lane coupling

These change *how* some tasks are built, not *what* the plan delivers.

| # | Plan said | This allocation does | Why |
|---|---|---|---|
| 1 | P5-1 adds `deal.relationship_id` | The trade relationship is found by the pair `(deal.company_id, deal.buyer_company_id)`; no column on `deal` | Keeps Developer 3 out of the deal table and the terminal-deal trigger |
| 2 | P3-4 builds an interim buyer guard, then P4-7 rewrites it | The guard is written once, against the `ComplianceFactsReader` interface, with a fallback for legacy deals that still use `deal_buyer` | One guard change instead of two, and the guard owner never waits for compliance code |
| 3 | P3-3c adds a filter to `search_profiles` | "Re-KYC due" gets its own endpoint in the background-check area | Keeps Developer 1 out of the company search service |
| 4 | P4-4 adds `buyer_company_id` to the terminal-deal trigger | The trigger allows `buyer_company_id` and `seller_gst_registration_id` to go from NULL to a value once, then freezes them | The buyer migration (P4-6) can fill already-handed-over deals without switching the trigger off |

---

## 2. Rules every developer follows

### 2.1 Ownership

| Area | Owner | Others may |
|---|---|---|
| Background check, verification, screening, check cycles, approvals: entities, services, routers, `compliance_inputs.py`, `ClearPolicy` | **Dev 1** | Call the published interfaces only |
| Deal, `deal_buyer`, deal documents rules, `prevent_terminal_deal_change()`, `deal_service.py` including `_handover_blocked_reason`, deal routers/schemas | **Dev 2** | Call the published interfaces only |
| Company record (`exporter_profile`), `exporter_gstin` / GST registrations, qualification criteria and reason codes, conversation/engagement, CSV and RXIL intake, company search and match, trade history | **Dev 3** | Call the published interfaces only |
| Frontend: `BackgroundCheckPanel`, `BackgroundCheckGauge`, `BackgroundCheckMoveDialog`, `ScreeningChecklist`, `DecisionHistory`, `VerificationSection`, `VerificationResultRow`, `EvidenceList`, `BuyerChecks`, `HomeCards.tsx` | **Dev 1** | Mount components |
| Frontend: `DealDetailPage.tsx`, buyer form/picker mounting, deal settings screen | **Dev 2** | — |
| Frontend: `ExporterDetailPage.tsx`, `CompanyPanel.tsx`, `AddExporterPage.tsx`, `CompanyImportPage.tsx`, `PipelinePage.tsx`, qualification screens, Settings labels, `Sidebar`, `LoginPage` | **Dev 3** | — |

### 2.2 Shared files (the only files more than one person edits)

| File | Rule |
|---|---|
| Alembic chain | One head at all times. When merging, set your migration's `down_revision` to the current head and re-run `alembic heads`. Revision ids ≤ 32 characters, named `onboarding_00NN_<lane>_<topic>` |
| `frontend/openapi.json`, `frontend/src/lib/api/schema.ts` | Never hand-merge. After rebasing, regenerate both and commit |
| `onboarding/tests/integration/test_route_authorization.py` | Add rows only, in a block commented with your lane |
| `api/schemas/masking.py` | Add new functions only; don't change existing ones |
| `exporter_profile.py` (entity) | Dev 3 owns it. Dev 1 adds one column (`background_check_expires_at`) in F1 and nothing else |
| `exporter_profile_service.py` | Dev 3 owns it. Dev 1 changes `promote_to_customer_if_ready` once in F1 (to call the facts reader) and nothing else |
| History dimensions list | All new dimensions are added once in F1: `check_cycle`, `background_check_approval`, `gst_registration`, `trade`, `pipeline` |
| Sample data | Dev 1: `sample_data_background_check.py`. Dev 3: `sample_data.py`. Dev 2: a new `sample_data_deals.py` (buyer companies, documents) |
| `test_crm_end_to_end.py` | Dev 2 owns it. Others put lane end-to-end tests in new files (`test_e2e_compliance_*.py`, `test_e2e_company_*.py`) |
| `app/shared/clock.py` | Created in F1; everyone uses it for "now" in new code |

### 2.3 Standing rules from the plan

- Append-only tables are never updated. Legacy rows are read through documented rules (`cycle_id NULL` = cycle 1; `rules_version NULL` = 8-item rules; CLEAR `expires_at NULL` = decided + 1 year).
- Every new table carries `created_by`, `created_at`, `source`, `source_ref` (BQ-7).
- Masking stays on the server. A new response shape gets a masking test for OPERATIONS and DEVELOPER.
- Every new route gets a route-authorisation row and D8 (DEVELOPER) handling.
- Take a `pg_dump` before any data migration. Each data migration has a dry run and states how it is rolled back.
- Don't rename the `OPERATIONS` enum, don't make buyers into Leads automatically, don't let the RM approve compliance, and don't load real customer data (plan §8).

---

## 3. Developer 1 — Compliance engine

**Owns:** background check, verification, screening, check cycles, maker-checker, Clear rules, expiry, company-keyed checks, and the compliance facts used by the handover guard.

**Progress:** F1 and the lane are merged; what remains is in [`remaining-work.md`](remaining-work.md).

### F1 — Compliance foundation PR (days 1–2, merge first) · M

- **Docs:** seam v2 (plan P0-2) in `docs/contracts/background-check.md` §6, covering `cycle_id` on inputs, `current_cycle_id`, inputs keyed by `subject_company_id`, and legacy `buyer_checks(deal_buyer_id)`. Also update `history-row.md` with the five new dimensions.
- **History dimensions:** add `check_cycle`, `background_check_approval`, `gst_registration`, `trade`, `pipeline`.
- **Migration:**
  - `verification_result.subject_company_id` (nullable FK → `exporter_profile.customer_id`), set-once, then frozen by `trg_verification_result_input_immutability`.
  - `exporter_profile.background_check_expires_at` (nullable) with an index.
- **Interface `ComplianceFactsReader`** (in `domain/`, published to other lanes):
  ```
  for_company(company_id, now) -> PartyComplianceFacts
  for_legacy_buyer(deal_buyer_id, now) -> PartyComplianceFacts
  PartyComplianceFacts:
    background_check: BackgroundCheckValue
    is_clear: bool
    clear_expires_at: datetime | None
    is_clear_current: bool
    sanctions: CheckState   # PASSED | FAILED | MISSING | PENDING
    aml: CheckState
  ```
  The first implementation uses today's data: no cycles, and expiry from the legacy rule (last CLEAR decision + 1 year).
- **Promotion:** change `promote_to_customer_if_ready` to require `facts.is_clear_current` (IQ-18). This is the one allowed edit to Dev 3's service.
- **Test utilities (plan P0-5):** a second-COMPLIANCE-user fixture and an `approve_as(...)` helper, plus the injectable clock in `app/shared/clock.py`.
- **Frontend stub:** `CompanyComplianceSummary.tsx` with props `{ companyId: string }`, showing the current gauge and the sanctions/AML state. Dev 2 mounts it on the deal page.
- **Done when:** merged; `ComplianceFactsReader` returns correct facts for sample companies; other lanes can import it.

### Lane tasks (in order)

| # | Plan id | Task | Size | Done when |
|---|---|---|---|---|
| 1.1 | P2-1a | Evidence endpoint: resolve a decision's pinned ids into readable items (verification, screening item, document); D8 refused | M | Every pinned id on a sample CLEAR resolves; masking and D8 tests pass |
| 1.2 | P2-1b | `screening_review_item.evidence_refs JSONB DEFAULT '[]'`; PUT accepts `{type, ref}` evidence (optional, IQ-14) | S | A screening PASSED with a document ref round-trips; append-only still enforced |
| 1.3 | P2-1c | `EvidenceList` under each screening item and inside expandable decision rows | M | Each check shows result, who, when, provenance and evidence |
| 1.4 | P2-2 | Filters All / Automated / Manual / Flagged in `VerificationSection` (Automated excludes the stub; Flagged = FAILED or HIGH/CRITICAL) | S | Filters work; "Automated" shows an honest empty state |
| 1.5 | P2-4a | Screening 8 → 7 (remove `website-reviewed` from the catalogue; refuse new writes; stored rows kept); `background_check_decision.rules_version` with `CLEAR_RULES_V2` on new CLEARs | M | Checklist shows 7; old decisions still show 8 pinned items; 11 catalogue tests updated (plan §18.2) |
| 1.6 | P2-3a | `check_cycle` table (append-only); nullable `cycle_id` on `verification_result`, `screening_review_item`, `background_check_decision`; insert cycle 1 per company (no updates to old rows) | M | Every company with inputs has cycle 1; new inputs carry `cycle_id` |
| 1.7 | P2-3b | Seam v2 implemented: inputs scoped to the current cycle; `ComplianceFactsReader` switched to cycle scope | M | A company in cycle 2 with no cycle-2 answers can't be cleared |
| 1.8 | P2-3c | `POST …/background-check/cycles {kind, reason}` (COMPLIANCE, ADMIN). On a CLEAR company it reopens to IN_REVIEW in the same transaction (IQ-3); refused on FLAGGED/ON_HOLD | M | A second cycle can run; concurrency test gives one cycle |
| 1.9 | P2-3d | Cycle grouping and Re-KYC / Re-KYB buttons from served `allowed_actions` | M | Earlier cycles readable; current one editable |
| 1.10 | P3-1a | Proposal and resolution tables (append-only); decision gets `proposal_id`, `approved_by`, `approved_at`; DB check `approved_by <> decided_by`; one open proposal per company | M | Schema refuses self-approval and edits |
| 1.11 | P3-1b | Propose / approve / reject / withdraw for CLEAR, FLAGGED, ON_HOLD (IQ-1); fingerprint check; setting `CRM_BACKGROUND_CHECK_MAKER_CHECKER`, which may be off only in local/test (IQ-17) | L | No path lets one user take a company to CLEAR |
| 1.12 | P3-1c | "Awaiting approval" state, approve/reject dialog, Home card "Proposals awaiting me" (`GET /background-check/proposals?status=open`) | M | A second user approves from Home in two clicks |
| 1.13 | P3-1d | Move the existing suite and `sample_data_background_check.py` onto two users | M | Suite back to baseline with maker-checker on |
| 1.14 | P3-2 | Rule B: `ClearPolicy.required_passed_types = {KYB, AML, SANCTIONS}`, meaning of "passed" per IQ-2; read model serves required types | M | CLEAR refused naming each missing type |
| 1.15 | P3-3a | `background_check_decision.expires_at` on new CLEARs (validity setting, default 365 days); write and clear `exporter_profile.background_check_expires_at`; backfill the profile column for CLEAR companies (BQ-5) | M | Every CLEAR company has an expiry |
| 1.16 | P3-3b | Expiry in the reader and in `ComplianceFactsReader.is_clear_current` (no automatic gauge move) | S | Facts report expired checks; promotion refused on expired Clear |
| 1.17 | P3-3c | `GET /background-check/due?before=…` (own endpoint) + Home card "Re-KYC due" + gauge badge | M | Home lists expired and soon-expiring companies |
| 1.18 | P4-5 | Company-keyed checks: every new result sets `subject_company_id`; buyer checks are recorded against a company id; seam reads by `subject_company_id` (legacy rows by `entity_reference`); `for_legacy_buyer` kept for old deals | M | One set of checks per company; the same results show wherever the company appears |
| 1.19 | P4-11 | Full background check for companies with `pipeline_status = NOT_IN_PIPELINE`: start, cycles, approval, rule B, expiry; never promoted | S | A buyer-only company can be cleared with approval and stays out of the journey |
| 1.20 | — | `CompanyComplianceSummary.tsx` full version (gauge, expiry, sanctions/AML, link to the company's background-check panel); replaces `BuyerChecks.tsx` | S | Renders for seller and buyer companies |

**Interfaces Dev 1 provides:** `ComplianceFactsReader` (used by Dev 2's guard); `CompanyComplianceSummary` component (mounted by Dev 2); `subject_company_id` column (written by Dev 2's migration).
**Interfaces Dev 1 consumes:** none beyond existing code. Buyer companies are ordinary company ids.
**Before 1.19 ships:** close plan §5.1 item 2 (confirm decision D with Bhargava).

---

## 4. Developer 2 — Deals, handover and buyer migration

**Owns:** the deal and its buyer, the handover snapshot, the handover guard (every condition), required documents, the deal-buyer → company migration, the invoicing branch on the deal, and retiring `deal_buyer`.

**Progress (2 October 2026):** F2, 2.1–2.3 merged; 2.4–2.12 open. Task-by-task state as of 4 October 2026: [`remaining-work.md`](remaining-work.md) §1.

### F2 — Deal foundation PR (days 3–4, merge last; uses F1 and F3 interfaces) · M

- **Migration:**
  - `deal.buyer_company_id` (nullable FK → `exporter_profile.customer_id`, RESTRICT) with `CHECK (buyer_company_id IS NULL OR buyer_company_id <> company_id)`.
  - `deal.handover_snapshot JSONB NULL`.
  - `deal.seller_gst_registration_id` (nullable FK → `exporter_gstin.id`). **VERIFY** that `exporter_gstin` has an `id` primary key. If not, agree the key with Dev 3 inside F3.
  - Do not extend the terminal trigger yet. That happens in 2.1 and 2.4.
- **Guard refactor:** turn `_handover_blocked_reason` into an ordered list of condition functions, each returning an unmet-condition string or None. Providers are injected:
  - `ComplianceFactsReader` (F1)
  - `RequiredDocumentsPolicy` (own; empty by default)
  - `BranchFlagReader` (F3 stub)

  Behaviour is unchanged in this PR.
- **Deal response:** add `buyer_company` (nullable summary: id, name, country, pipeline status, identifiers masked per role). The shape is fixed now.
- **Frontend stub:** `CompanyDealsList.tsx` with props `{ companyId: string; as: 'seller' | 'buyer' }`. Dev 3 mounts it on the company page.
- **Done when:** merged; the guard's existing tests pass unchanged; new columns are in the ORM (drift test green).

### Lane tasks (in order)

| # | Plan id | Task | Size | Done when |
|---|---|---|---|---|
| 2.1 | P2-7 | Write `handover_snapshot` on HANDED_OVER (buyer + `document_ids` + `snapshot_source`); backfill existing handed-over deals from `deal_buyer` and the history row; **then** add the column to `prevent_terminal_deal_change()` | M | Every HANDED_OVER deal has a snapshot that can't change (raw-SQL test) |
| 2.2 | P2-5a | `deal_required_document` (versioned, append-only), `GET/POST /settings/deal-required-documents` (read Staff, write ADMIN), Settings screen; seed `PRE_SHIPMENT` (IQ-10) | M | ADMIN can add/remove a category; history kept |
| 2.3 | P2-5b | Guard condition "missing required documents: …", counting only `AVAILABLE` documents (IQ-11); add a pre-shipment document to `sample_data_deals.py` and the main e2e | S | A deal missing it gets 409 naming the category; no requirement means no change |
| 2.4 | P4-4 | `PUT /deals/{id}/buyer {buyer_company_id}` (seller ≠ buyer); "needs buyer" reads `buyer_company_id` when set, else legacy `deal_buyer`; snapshot built from the buyer company; trigger updated with the set-once rule for `buyer_company_id`; deal page mounts `CompanyPicker` (Dev 3) and `CompanyComplianceSummary` (Dev 1) | M | A deal records a buyer company; handover snapshots it |
| 2.5 | P3-3b, P3-4, P4-7 | Compliance guard conditions using `ComplianceFactsReader`: seller must be CUSTOMER with `is_clear_current`; seller with a FAILED sanctions or AML blocks (BQ-3); buyer sanctions and AML must be PASSED (BQ-4); missing buyer company falls back to `for_legacy_buyer`; share-lock seller and buyer rows sorted by `customer_id` | M | With a fake reader: each rule blocks with its own message; deadlock-order test passes |
| 2.6 | P4-6 | Buyer migration: `deal_buyer_company_map`, idempotent command `--dry-run / --apply --run-id` (plan §17.2 identity rules), creates companies through `CompanyDirectory.create_buyer_company` (F3), fills `deal.buyer_company_id` and `verification_result.subject_company_id`; migration test harness with the edge cases; validation queries | L | All §17.2 validation queries pass on a fixture DB; re-run creates nothing |
| 2.7 | P4-8 (deals part) | `GET /exporters/{id}/deals?as=buyer`; `CompanyDealsList` full version; buyer company history includes deal rows where it is the buyer (read-side union, D8 applies) | M | A company shows deals as seller and as buyer |
| 2.8 | P6-6 | Invoicing branch on the deal: set any time before handover; must belong to the seller; set-once rule in the trigger; picker on the deal page (lists the seller's active registrations) | M | A deal records its branch; legacy deals stay NULL |
| 2.9 | P6-7 | Guard conditions: "invoicing branch <state> is flagged" via `BranchFlagReader`; "record the invoicing branch" when the seller has an active registration (IQ-20) | S | With a fake reader: flagged branch blocks; other branches pass |
| 2.10 | P4-10 | Retire `deal_buyer` writes (trigger refuses INSERT/UPDATE; table kept); remove legacy `buyer` from the response after one release; rewrite decision 9 in `architecture.md`, `deal-and-buyer.md`, `event-envelope.md` (`deal.handed_over` payload) | S | No code path writes `deal_buyer` |
| 2.11 | — | Mount `TradeHistoryPanel` (Dev 3) on the deal page with `{sellerId, buyerId, dealId}` | S | Panel shows on deals that have a buyer company |
| 2.12 | — | Main `test_crm_end_to_end.py`: two users, required document, buyer company, full handover | M | Green on the combined code (final integration, §6) |

**Interfaces Dev 2 provides:** deal columns (read by Dev 3's trade history); `CompanyDealsList` component (mounted by Dev 3).
**Interfaces Dev 2 consumes:** `ComplianceFactsReader` (F1), `CompanyComplianceSummary` (F1), `CompanyDirectory.create_buyer_company`, `CompanyPicker`, `BranchFlagReader`, `TradeHistoryPanel` (all F3). All exist as stubs after foundation week, so Dev 2 tests against fakes and never waits.

---

## 5. Developer 3 — Company record, settings, GST branches, trade history

**Owns:** the company master (identity, pipeline status, intake, search and match), settings and labels, GST registrations and branch flags, and trade history.

**Progress (2 October 2026):** 3.1, 3.3–3.6 and 3.2's script merged (3.2's reports still owed); F3 next — Developer 2 now waits on it; 3.7–3.24 open. Task-by-task state as of 4 October 2026: [`remaining-work.md`](remaining-work.md) §1.

### F3 — Company foundation PR (days 2–3, merge second) · M

- **Migration (plan P4-1 schema):**
  - On `exporter_profile`:
    - `identity_type` (`IN_PAN` | `FOREIGN_REG`, nullable for legacy companies)
    - `registration_number`, with a partial unique index on `(country, normalised registration_number)`
    - `pipeline_status` (`NOT NULL DEFAULT 'IN_PIPELINE'`), with a check that `NOT_IN_PIPELINE` implies LEAD / NOT_YET_REVIEWED / NOT_CONTACTED
    - `created_via` and `created_via_deal_id`
  - New enum value `ExporterSource.DEAL_BUYER` (IQ-6).
  - `identity_type = 'IN_PAN'` where `pan` is set.
- **Interface `CompanyDirectory`** (published):
  ```
  create_buyer_company(name, country, pan?, gstins?, registration_number?, contact?, created_via_deal_id, actor, source_ref) -> company_id
  match(name, country, pan?, gstin?, registration_number?, actor_role) -> MatchResult  # MATCHED | POSSIBLE_DUPLICATE | CONFLICT | NEW
  ```
  The stub returns a match on exact PAN only, and `create_buyer_company` works fully.
- **Interface `BranchFlagReader`:** `is_flagged(gst_registration_id) -> (bool, state_name | None)`. The stub always returns `(False, None)`.
- **Frontend stubs:**
  - `CompanyPicker.tsx` with props `{ onSelect(companyId: string): void }` (name search + create form)
  - `TradeHistoryPanel.tsx` with props `{ sellerId: string; buyerId: string; dealId?: string }`
- **Done when:** merged; existing companies are `IN_PIPELINE`; ORM drift test green; Dev 2 can import both interfaces.

### Lane tasks (in order)

| # | Plan id | Task | Size | Done when |
|---|---|---|---|---|
| 3.1 | P0-4 | Write the migration and gate conventions from §2.2 and §2.3 into `docs/development.md` and `migration-register.md` | S | Merged |
| 3.2 | P0-3 | Read-only data inventory per live database (buyers, BUYER results, duplicate GSTINs, PAN-less companies, CLEAR companies, website screening rows, deal documents); share with Dev 1 and Dev 2 | S | Reports attached to tickets |
| 3.3 | P1-1 | Data migration: new criteria versions making `export_history` and `export_licence` not required (USD thresholds unchanged, BQ-1); update `sample_data.py` | S | A domestic company gets a QUALIFIED suggestion |
| 3.4 | P1-2 | Deactivate `no_export_history`, `no_export_licence`, `geography_not_supported` (IQ-12) | S | Codes gone from new decisions; old outcomes still render |
| 3.5 | P1-4 | "Aner Labs" in `index.html`, `Sidebar.tsx`, `LoginPage.tsx`; backend `APP_NAME` unchanged | S | OpenAPI artifact test still green |
| 3.6 | P1-5 | `roleLabel()` used on every screen that shows a role; built-in role display name becomes "RM (Relationship Manager)" (IQ-13); fix the stale `catalog.py` description | S | No visible "Operations" in the built bundle |
| 3.7 | P2-4b | Remove website from forms, request schemas and CSV template; CSV accepts old and new headers; RXIL ignores `website`; stored values kept and hidden (IQ-16). The screening item is Dev 1's task 1.5 | M | An old CSV with a website column still imports |
| 3.8 | P4-1 (rest) | Service create paths set `identity_type`, `created_via`; foreign registration number required (IQ-7) except migrated buyers; masking of `registration_number` like CIN; backfill `created_via` from the first history row; qualification and conversation refuse `NOT_IN_PIPELINE` | M | A foreign buyer-only company can exist; backfill report clean |
| 3.9 | P4-2 | `search_profiles` excludes `NOT_IN_PIPELINE` by default; company page shows "Not in pipeline" and "Not needed" for qualification and conversation; mount `CompanyDealsList` (as seller / as buyer) | S | Creating a buyer company changes no LEAD count |
| 3.10 | P4-3 | `POST /companies/match` with the BQ-2 rule (a full PAN/GSTIN names the company, identifiers stay masked, no partial search, every lookup audited); GSTIN on two companies returns both (IQ-9); name similarity (`pg_trgm` if available, else normalised equality); `CompanyPicker` full version | M | RM finds by name or exact identifier, or creates a `NOT_IN_PIPELINE` company |
| 3.11 | P4-9 | `POST /exporters/{id}/pipeline`: `NOT_IN_PIPELINE → IN_PIPELINE`, journey history starts at LEAD now | S | No new record; promotion via qualification works if already CLEAR |
| 3.12 | P6-1 | Evolve `exporter_gstin` in place: `state_code`, `state_name`, `status`, `address`, `flag_status`, `flag_reason`, `active`, `deactivated_at/by`; remove delete-orphan; trigger refuses DELETE; derive states | M | Every row has a state; none can be deleted |
| 3.13 | P6-2 | `POST /exporters/{id}/gst-registrations`, `POST …/{gstin}/deactivate`; PATCH stops accepting `gstins`; `GstRegistrationsSection.tsx` replaces the GSTIN block in `CompanyPanel` | M | GSTIN edits are add/deactivate only, with history |
| 3.14 | P6-5 | `POST /gst-registrations/{id}/flag` and `/unflag` (COMPLIANCE, ADMIN, reason required); company warning chip; `BranchFlagReader` real version | S | A flagged branch shows on the company; the reader reports it |
| 3.15 | P6-3 | Warn-only consequences (IQ-9): flagging a GSTIN held by another company warns on both company pages | S | Test: a flag on one holder warns on the other |
| 3.16 | P6-4 | Optional: set PAN from GSTIN for PAN-less companies, if the 3.2 report shows it is worth doing; audit table for rollback | S | Only if needed |
| 3.17 | P2-6 | "Verify GSTIN" link to the GST portal search for COMPLIANCE and ADMIN; no reveal for masked roles | S | Link per GSTIN; OPERATIONS sees no full GSTIN |
| 3.18 | P5-1 | `trade_relationship(seller_company_id, buyer_company_id)` unique pair, seller ≠ buyer, `get_or_create` (no column on `deal`, see §1 adjustment 1) | S | Concurrency test: two calls, one row |
| 3.19 | P5-2 | `trade_invoice` (identity frozen) and `trade_invoice_outcome` (append-only chain); currency stored, no conversion (IQ-4) | M | Chain integrity and raw-SQL append-only tests pass |
| 3.20 | P5-3, P5-4 | Read routes (as seller / as buyer, one relationship) and write routes for invoices and outcomes; RM, Compliance, Admin write; Developer reads masked (IQ-19); history `trade` rows | M | Routes, roles and masking tests pass |
| 3.21 | P5-6, P5-8 | Record outcome after handover (creates the invoice if absent); claimed past trade with `deal_id NULL` and `proof_status = CLAIMED` | S | Outcome recorded on a HANDED_OVER deal; "No proof yet" shows |
| 3.22 | P5-7 | `TradeHistoryPanel` full version (relationship, invoices, status chips, `EvidenceList` for proof); company-page panel | M | Matches the target diagram's trade history block |
| 3.23 | P5-5 | Backfill script: `get_or_create` a relationship for every deal with `buyer_company_id` (run after P4-6, see §6) | S | Every deal with a buyer company has a relationship |
| 3.24 | — | Masking sweep test: every CRM read as OPERATIONS and DEVELOPER, asserting no unmasked PAN, GSTIN, IEC, CIN, registration number or contact (plan §18.3) | M | Green on the combined code |

**Interfaces Dev 3 provides:** `CompanyDirectory`, `BranchFlagReader`, `CompanyPicker`, `TradeHistoryPanel`.
**Interfaces Dev 3 consumes:** `CompanyDealsList` (F2) and `deal.buyer_company_id` (F2 column). Both exist after foundation week.

---

## 6. Merge and run order

### Foundation week

| Day | Step |
|---|---|
| 1–2 | Dev 1 merges **F1** |
| 2–3 | Dev 3 merges **F3** (rebased on F1) |
| 3–4 | Dev 2 merges **F2** (rebased on F1 and F3; consumes their interfaces) |

**As it happened:** F1 → **F2 → F3**. F2 merged before F3, declaring `BranchFlagReader` itself and stubbing around the rest, so F3 must fit what F2 put on `main` and Developer 2's 2.4, 2.6, 2.8, 2.9 and 2.11 wait on F3 (or on 3.12). See `remaining-work.md` §1.
| From day 1 | Everyone starts lane tasks on their own branches (Dev 3's 3.1–3.6 and Dev 1's 1.1–1.4 don't need any foundation) |

### After foundation week

Lanes merge independently, in their own order. The guard's behaviour grows as providers land: fakes in tests, real readers in production.

### Operational order on live databases (not a coding dependency)

1. `pg_dump`.
2. Dev 2's buyer migration **P4-6**, after Dev 2's 2.4 is merged. Dry run, Compliance reviews name-only duplicates (IQ-8), then apply, then run the validation queries.
3. Dev 3's relationship backfill **P5-5** (3.23).
4. Dev 2's **P4-10** (retire `deal_buyer` writes), only once every environment has passed step 2.

### Final integration (last 3–5 days, all three together)

| Task | Owner |
|---|---|
| Main two-user end-to-end: lead → qualified → check with approval → customer → deal with buyer company → required document → handover → payment outcome | Dev 2 (2.12) |
| Masking sweep across every read | Dev 3 (3.24) |
| Concurrency: handover vs flag on the buyer company; approve vs new input; cycle start vs decision | Dev 1 |
| Full backend suite, import-linter, ORM drift, OpenAPI artifact, frontend tests, one Alembic head | Each developer for their lane, then together |
| Demo walk-through against the target diagram (three sample companies) | All |

---

## 7. Not allocated (deferred or waiting on outside parties)

| Item | Status |
|---|---|
| P1-3 rupee display | Deferred: thresholds stay in USD (BQ-1) |
| P6-3 global GSTIN uniqueness | Dropped (IQ-9); only its warn-only consequences are in task 3.15 |
| P7-1, P7-2, P7-3 provider adapters (Sumsub etc.) | Deferred: checks stay manual this quarter (BQ-8) |
| P7-4 field-level provenance and retrofit | Waits for the DPDP meeting. Basic provenance on new tables is already in every lane (§2.3) |
| P7-5 consent records | Waits for the DPDP meeting |
| P7-6 RXIL automatic intake | Waits for the D12 specification. Meanwhile an RXIL report can be uploaded as a document and cited on a manual AML result |
| P7-7 encryption, real scanner, S3 Object Lock | Precondition for real data; outside this plan |

---

## 8. Summary

| | Developer 1 | Developer 2 | Developer 3 |
|---|---|---|---|
| Lane | Compliance engine | Deals, handover, buyer migration | Company record, settings, GST, trade history |
| Foundation | F1 (merge 1st) | F2 (merge 3rd) | F3 (merge 2nd) |
| Largest tasks | Check cycles (P2-3), maker-checker (P3-1) | Buyer migration (P4-6), handover guard | Trade history (P5), GST registrations (P6) |
| Provides | `ComplianceFactsReader`, `CompanyComplianceSummary`, `subject_company_id` | `CompanyDealsList`, deal columns | `CompanyDirectory`, `BranchFlagReader`, `CompanyPicker`, `TradeHistoryPanel` |
| Owns screens | Background check, verification, screening, Home cards | Deal page, required-documents settings | Company pages, intake, qualification, labels, GST, trade history |
| Final integration | Concurrency tests | Main end-to-end | Masking sweep |
