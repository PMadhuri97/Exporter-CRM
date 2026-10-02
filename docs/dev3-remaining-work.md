# Developer 3 — what is done, and what is left

**As of 2 October 2026**, after the PR audit of `feature/trade_history` and its merge with
`main` (Developer 1's F1 + lane, Developer 2's F2 + 2.1–2.3). Lane: the company record,
settings, GST branches and trade history (`developer-allocation.md` §5). Re-check the
code before trusting a "not built" below — this file says what was true on that date.

| | |
|---|---|
| **Done (merged)** | 3.1, 3.3, 3.4, 3.5, 3.6 — and 3.2's script |
| **Still owed on a done task** | 3.2's per-environment **reports**; the 0031 **release note** (§1) |
| **Next, and on the critical path** | **F3** — Developer 2 is now waiting on it (§3) |
| **Not started** | 3.7 – 3.24 |
| **Next free migration number** | **0032**, parent `auth_0005_rm_role_name` (`contracts/migration-register.md` §1) |

**The merge order changed.** The allocation planned F1 → F3 → F2. What happened was
**F1 → F2 → F3**: Developer 2's foundation merged before yours, so it declared the one
interface of yours it needed (`BranchFlagReader`) itself and left hooks for the rest. F3 no
longer defines everything from scratch — part of what it was meant to publish is already on
`main`, and F3 must fit it (§2).

---

## 1. Done

### 3.3 + 3.4 — Domestic-first qualification (P1-1, P1-2)

`onboarding_0031_domestic_first` (written as 0023, renumbered at merge — the number had
been taken by Developer 1):

- the **next** version of `export_history` and `export_licence`, copied from the current
  one with `required = false` (`created_by = migration:onboarding_0031_domestic_first`).
  The version is read from the table, not assumed to be 2: an ADMIN may already have
  versioned a criterion on a live database, and the first draft failed there with
  `UniqueViolation`;
- `no_export_history`, `no_export_licence`, `geography_not_supported` deactivated.

`revenue` and `deal_size` untouched — thresholds stay in USD (BQ-1). `sample_data.py`'s
`_REQUIRED_KEYS` is `("revenue", "years_in_business")`. Contract: `criterion-result.md`
§2 and §5.2. Rollback: `pg_dump`; the downgrade deletes only its own rows and is refused
once any result points at them.

**Proof:** `test_qualification.py` — `test_a_domestic_company_qualifies_without_export_evidence`
and four more, plus `test_the_migration_builds_on_whatever_version_an_admin_left`, which
runs the migration's own SQL in a rolled-back transaction.

> **Release note still owed — the de-count.** After 0031, `export_history` and
> `export_licence` results stop counting towards the suggestion. A company already
> `QUALIFIED` is unaffected (A2); an **undecided lead re-suggests** and may now read
> `QUALIFIED`. Tell users before it ships, or it will look like data moved on its own.

### 3.5 — "Aner Labs" (P1-4)

`index.html`, `Sidebar.tsx`, `LoginPage.tsx`. Backend `APP_NAME` unchanged, so
`openapi.json` did not move. Storage keys containing "aner" were deliberately left
(`aner.theme`, `aner.refreshToken`, `aner.sidebar.collapsed`, the `aner-refresh` Web
Lock, `@aner/...`): renaming them signs users out without changing a visible word.

### 3.6 — "RM (Relationship Manager)" (P1-5, IQ-13)

- `roleLabel()` / `roleShortLabel()` in `platform/auth/roles.ts`, used at every site that
  renders a role: header (short form), Home, Users chip and filter, user form Role select
  and "Default for …", My Profile chip. `ROLE_DESCRIPTION.COMPLIANCE` no longer says
  "Operations". Test: `platform/auth/roles.test.ts`.
- **`auth_0005_rm_role_name`** renames the built-in OPERATIONS row in `auth.role` (and
  drops its "unless you own the record" description, decision 12) unless an ADMIN already
  changed it. That row — not `catalog.py`'s `BUILTIN_ROLE_METADATA`, which nothing reads at
  runtime — is what the Roles tab, the user form's role picker and "Signed in as …" show.
- `GET /me/permissions`'s `role_name` falls back to the **built-in row** for an account with
  no `role_id` (it used to title-case the enum into "Operations").
  Test: `test_role_management.py::test_the_operations_role_reads_rm_everywhere_it_is_named`.
- **The enum is not renamed** (§2.3): `OPERATIONS` is in every history row and both
  route-authorisation tables.

### 3.1 — Conventions (P0-4)

`development.md` §7 and `migration-register.md` §2: the `onboarding_00NN_<lane>_<topic>`
pattern with the 33-character example, re-point `down_revision` before merging (and take
the next free number if yours was used meanwhile), `pg_dump` before a data migration,
expand → backfill → contract.

### 3.2 — Data inventory (P0-3) — script done, **reports not**

`backend/scripts/crm_data_inventory.sql` — read-only, every statement a `SELECT`; parses
and runs on the schema at 0030. **The task is the reports**: run it on every live
database (`crm_uat_walk`, `crm_release_audit`, demo, shared test) and attach the output to
the migration tickets. Developer 2's P4-6 (task 2.6) and your 3.16 are sized from them.
Numbers from a development database must not be attached — it carries sample data and
whatever the suite last left behind.

---

## 2. F3 — Company foundation (next)

Spec: allocation §5 "F3". Build it as specified, with these adjustments for what is already
on `main`:

| F3 item | State on `main` | What F3 does |
|---|---|---|
| `exporter_profile.identity_type`, `registration_number` (+ partial unique index on `(country, normalised registration_number)`), `pipeline_status` (`NOT NULL DEFAULT 'IN_PIPELINE'`, `NOT_IN_PIPELINE ⇒` LEAD / NOT_YET_REVIEWED / NOT_CONTACTED), `created_via`, `created_via_deal_id`; `identity_type = 'IN_PAN'` where `pan` is set | absent | Migration **0032**. Re-point `down_revision` to the head at merge time |
| `ExporterSource.DEAL_BUYER` (IQ-6) | absent | Add the enum value in an **ordinary transactional** migration — never `ALTER TYPE … ADD VALUE` in an autocommit block (`migration-register.md` §2) |
| `CompanyDirectory` (`create_buyer_company`, `match`) | absent | Publish it with working stubs (`match` = exact PAN only; `create_buyer_company` fully working). Developer 2's 2.6 needs `create_buyer_company` |
| `BranchFlagReader` | **declared by Developer 2** as a `Protocol` in `domain/handover_conditions.py`, with the null `NoBranchFlags` injected into `DealService` | **Do not declare a second one.** Provide your stub class satisfying that Protocol (`is_flagged(gst_registration_id) -> (bool, state_name \| None)`); the real reader is 3.14. Injecting it into `DealService` is Developer 2's 2.9 |
| `CompanyPicker.tsx` `{ onSelect(companyId) }`, `TradeHistoryPanel.tsx` `{ sellerId, buyerId, dealId? }` | absent | Frontend stubs with final props. Developer 2's 2.4 and 2.11 mount them |
| History dimensions `gst_registration`, `trade`, `pipeline` | **present** (Developer 1's F1, `domain/history_dimensions.py`) — no writers yet | Nothing; your tasks write them |
| `app/shared/clock.py` | present | Use it for "now" in new code |
| `deal.buyer_company_id`, `deal.seller_gst_registration_id` (FK → `exporter_gstin.id`, `RESTRICT`) | present (Developer 2's `onboarding_0028_deal_foundation`) | Nothing — but see 3.12 |
| `DealResponse.buyer_company.pipeline_status` | present, always `null` — reads `getattr(company, "pipeline_status", None)` | Lights up by itself once your column exists |
| `CompanyDealsList` `{ companyId, as }` | present (Developer 2's F2 stub; `as="buyer"` says "not available yet" until 2.7) | Mount it in 3.9 |

**After F3 merges:** re-run Developer 1's `test_dev1_company_keyed.py` — its P4-11 tests set
`pipeline_status = 'NOT_IN_PIPELINE'` on their buyer-only company automatically once the
column exists (`dev1-handover.md` §2.2). Tell Developer 1, who may then add
`pipeline_status` to the Re-KYC due list (`dev1-handover.md` §3, optional). Leave
`exporter_profile.background_check_expires_at` to Developer 1.

**Done when:** merged; existing companies are `IN_PIPELINE`; ORM drift test green;
Developer 2 can import `CompanyDirectory` and use your `BranchFlagReader` stub.

---

## 3. Lane tasks after F3

Specs are in allocation §5; this column says what has changed since it was written.

| # | Task | Needs | Notes as of 2 October |
|---|---|---|---|
| 3.7 | Remove website from forms, request schemas, CSV template; CSV accepts old and new headers; RXIL ignores `website`; stored values kept and hidden (IQ-16) | — | **The open question is settled**: Developer 1 retired the `website-reviewed` screening item in 0025 with `rules_version`, so decisions taken under the eight-item checklist keep reading. 3.7 is only the company field. Moves request schemas → regenerate `openapi.json` + `schema.ts` |
| 3.8 | Create paths set `identity_type` / `created_via`; foreign registration number required (IQ-7) except migrated buyers; mask `registration_number` like CIN; backfill `created_via` from the first history row; qualification and conversation refuse `NOT_IN_PIPELINE` | F3 | Masking: add new functions to `api/schemas/masking.py` only (§2.2). The refusal is what keeps a buyer-only company from ever being promoted (Developer 1's P4-11 relies on it) |
| 3.9 | `search_profiles` excludes `NOT_IN_PIPELINE`; "Not in pipeline" / "Not needed" on the company page; mount `CompanyDealsList` (as seller / as buyer) | F3 | `as="buyer"` shows "not available yet" until Developer 2's 2.7 — mount it anyway |
| 3.10 | `POST /companies/match` (BQ-2: a full PAN/GSTIN names the company, identifiers masked, no partial search, every lookup audited); GSTIN on two companies returns both (IQ-9); name similarity; `CompanyPicker` full version | F3 | Open lead decision in `open-items.md` §1 ("Identifier disclosure to masked roles") applies to what the match response may name |
| 3.11 | `POST /exporters/{id}/pipeline`: `NOT_IN_PIPELINE → IN_PIPELINE`, journey history starts at LEAD | F3 | Writes the `pipeline` history dimension |
| 3.12 | Evolve `exporter_gstin` in place (state, status, address, flag, `active`, soft deactivation); remove `delete-orphan`; trigger refuses DELETE | F3 | **Must land before Developer 2's 2.8.** Today a company edit that drops a GSTIN *deletes* its row (`exporter_profile_service.py`, `cascade="all, delete-orphan"`); once 2.8 records a deal's invoicing branch, that delete hits 0028's `RESTRICT` FK and fails |
| 3.13 | `POST /exporters/{id}/gst-registrations`, `POST …/{gstin}/deactivate`; PATCH stops accepting `gstins`; `GstRegistrationsSection.tsx` replaces the GSTIN block in `CompanyPanel` | 3.12 | Writes `gst_registration` history. Moves request schemas → regenerate artifacts |
| 3.14 | Flag / unflag (COMPLIANCE, ADMIN, reason required); company warning chip; **real `BranchFlagReader`** | 3.12 | Developer 2's 2.9 swaps it in |
| 3.15 | Warn-only consequences of a flagged GSTIN held by two companies (IQ-9) | 3.14 | — |
| 3.16 | Optional: PAN from GSTIN for PAN-less companies, with an audit table for rollback | 3.2 reports | **Only if the reports say it is worth doing** |
| 3.17 | "Verify GSTIN" link (GST portal) for COMPLIANCE and ADMIN; no reveal for masked roles | 3.12 | — |
| 3.18 | `trade_relationship(seller_company_id, buyer_company_id)`, unique pair, seller ≠ buyer, `get_or_create` | F3 | Found by the pair `(deal.company_id, deal.buyer_company_id)` — **no column on `deal`** (allocation §1, adjustment 1) |
| 3.19 | `trade_invoice` (identity frozen), `trade_invoice_outcome` (append-only chain); currency stored, never converted (IQ-4) | 3.18 | Every new table: `created_by`, `created_at`, `source`, `source_ref` (BQ-7); direct-SQL append-only tests |
| 3.20 | Read routes (as seller / as buyer / one relationship) and write routes; RM, Compliance, Admin write; Developer reads masked (IQ-19); `trade` history rows | 3.19 | Route-authorisation rows in your lane's block; D8 handling |
| 3.21 | Outcome after handover (creates the invoice if absent); claimed past trade with `deal_id NULL`, `proof_status = CLAIMED` | 3.20 | — |
| 3.22 | `TradeHistoryPanel` full version; company-page panel | 3.20 | Developer 2's 2.11 mounts it on the deal page |
| 3.23 | Relationship backfill for every deal with `buyer_company_id` | 3.18 | Code can be written any time; **run** it only after Developer 2's P4-6 has been applied (§5) |
| 3.24 | Masking sweep: every CRM read as OPERATIONS and DEVELOPER, no unmasked PAN, GSTIN, IEC, CIN, registration number or contact | everything | Final integration (allocation §6) |

### Inherited items in this lane (from `open-items.md` §2)

- **IEC has no `CHECK` constraint**, unlike PAN, GSTIN and CIN — the service checks it, the
  database does not. A migration (next free number) with a direct-SQL violation test.
- **`POST /exporters` without `name` or `country` still creates a company** — remove the
  unnamed path once nothing calls it, then make both columns `NOT NULL` (expand → backfill →
  contract). Fits naturally beside 3.8.

---

## 4. Who is waiting on you

| Developer 2's task | Needs from you |
|---|---|
| 2.4 buyer company on the deal | `CompanyPicker` (F3 stub, 3.10 full) |
| 2.6 buyer migration (P4-6) | `CompanyDirectory.create_buyer_company` (F3), and **3.2's reports** |
| 2.8 invoicing branch on the deal | **3.12** first (see the 3.12 note) |
| 2.9 "invoicing branch is flagged" | `BranchFlagReader` stub (F3), real one (3.14) |
| 2.11 trade history on the deal page | `TradeHistoryPanel` (F3 stub, 3.22 full) |
| 2.12 main end-to-end ("… → payment outcome") | 3.21 |

---

## 5. Operational order on live databases — do not reorder

From allocation §6. Not a coding dependency; the order things run on a live database.

1. `pg_dump`.
2. Developer 2's buyer migration **P4-6** (after their 2.4 merges): dry run, Compliance
   reviews the name-only duplicates (IQ-8), apply, validation queries.
3. Your relationship backfill **P5-5** (3.23).
4. Developer 2's **P4-10** (retire `deal_buyer` writes), only once every environment has
   passed step 2.

---

## 6. Before every PR

- `alembic heads` prints one; your migration's `down_revision` is the head **at merge
  time**; take the next free number from the register (and update its §1); id ≤ 32
  characters.
- A data migration: `pg_dump` first, a dry run, read the current state rather than assume
  it (the 0031 lesson), and say in the docstring how it rolls back.
- Request or response schema changed → regenerate `frontend/openapi.json` and
  `frontend/src/lib/api/schema.ts`; never hand-merge them.
- New route → a row in your block of `test_route_authorization.py`, D8 (DEVELOPER)
  handling, and a masking test for OPERATIONS and DEVELOPER on any new response shape.
- A label is not renamed until every place it is **stored** says the new thing (the
  `auth.role` lesson from 3.6).
- Gates (`development.md` §7). Baseline on 2 October 2026: backend 4,932 passed, 7
  skipped, 27 xfailed; the one failure,
  `idempotency/test_expiry_sweep.py::test_sweep_can_use_the_partial_ck_index`, also fails on
  `main` (query-planner choice as the ledger table grows) — not yours to chase. Frontend 39
  files / 372 tests; ruff 16; import-linter 19 kept / 0 broken.
- Name the PR after what it contains.

---

## 7. Open questions this lane will hit

- **3.16** is conditional on 3.2's reports. Do not build it first.
- **Identifier disclosure to masked roles** (`open-items.md` §1) — a lead decision that
  bounds what 3.10's match response and 3.15's warnings may name.
- The 0031 release note (§1) — someone has to send it.
