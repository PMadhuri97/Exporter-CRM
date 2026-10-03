# Developer 3 — what is done, and what is left

**As of 2 October 2026**, after `feature/trade_history` merged (PR #17) on top of Developer 1's
F1 + lane and Developer 2's F2 + 2.1–2.3. Lane: the company record,
settings, GST branches and trade history (`developer-allocation.md` §5). Re-check the
code before trusting a "not built" below — this file says what was true on that date.

| | |
|---|---|
| **Done (merged)** | 3.1, 3.3, 3.4, 3.5, 3.6 — and 3.2's script |
| **Done, awaiting merge** | **F3** (0032); **3.7, 3.8** (0033), **3.9, 3.10, 3.11**; **3.12** (0035), **3.13, 3.14, 3.15, 3.17**; **3.18, 3.19** (0037); **3.20, 3.21, 3.22, 3.23, 3.24**; the inherited IEC `CHECK` (0040) |
| **Still owed on a done task** | 3.2's per-environment **reports**; the 0031 **release note** (§1); **3.23's run**, which waits on Developer 2's P4-6 being applied (§5) |
| **Next** | Nothing in this lane blocks anything. 3.16 if 3.2's reports say it is worth doing |
| **Not started** | 3.16 (conditional on 3.2's reports) and one inherited item: `name` / `country` `NOT NULL` (the IEC `CHECK` is done, 0040) |
| **Next free migration number** | **0041** — 0032, 0033, 0035, 0037 and 0040 are this lane's; 0034, 0036, 0038 and 0039 are Developer 2's (`contracts/migration-register.md` §1) |

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
column exists (`dev1-remaining-work.md` §2). Tell Developer 1, who may then add
`pipeline_status` to the Re-KYC due list (`dev1-remaining-work.md` §2, optional). Leave
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
| 3.20 | **Done.** Five routes in `api/trade_history_router.py` (both sides of a company's relationships, one relationship with its invoices, one invoice with its whole outcome chain, and the two writes). `trade` history rows on every write. **IQ-19 is satisfied by the response shape, not by a masking pass**: `TradeCounterparty` carries an id, a name, a country and a pipeline status and *no identifiers for any role*, so there is nothing for DEVELOPER to be served masked — which is also what `history-row.md` already says about `trade` rows. No totals anywhere (IQ-4) | 3.19 | Rows added to **both** authorisation tables (`test_route_authorization.py` and `tests/contract/test_route_authorization_coverage.py`) |
| 3.21 | **Done.** `POST /deals/{id}/payment-outcome`: requires `HANDED_OVER` and a buyer **company**, creates the deal's invoice if it has none (the four invoice fields are required together or not at all) and appends the outcome. Claimed past trade is the same write with `deal_id` null and `proof_status = CLAIMED`. Not a deal stage (architecture §3.3) | 3.20 | Three new refusals: `DealNotHandedOverError`, `DealBuyerIsNotACompanyError`, `TradeInvoiceAlreadyRecordedError` |
| 3.22 | **Done.** `TradeHistoryPanel` filled in (the pair as "A → B", invoices with status chips, the outcome chain on demand, `EvidenceList` for proof) plus `CompanyTradePanel` for the company page — both sides, one relationship open at a time. `TradeInvoiceList` is the part they share. **The stub's props were not touched**, which is why 2.11's mounting did not change | 3.20 | `TradeOutcomeChip` keeps "nobody looked" (no outcome) apart from "looked and could not say" (`UNKNOWN`) — a distinction only the screen shows |
| 3.23 | **Code done; not run.** `python -m app.modules.onboarding.backfill_trade_relationships --dry-run / --apply / --validate / --report-run`. **P5-5's `deal.relationship_id` is not needed and was not added**: a relationship is keyed on the ordered pair and a deal carries both sides, so nothing is written to `deal` and the terminal-deal freeze is never involved — which removes the whole difficulty P5-5 anticipated. Only deals linked *without* `set_buyer_company` need it (that method creates the relationship itself), so its subject is exactly the deals P4-6 links | 3.18 | **Run it only after P4-6 has been applied** (§5). The dry run says so itself when most deals still have no buyer company |
| 3.24 | **Done.** `test_dev3_masking_sweep.py`: reads the mounted routes out of the OpenAPI document, calls **every** CRM `GET` as OPERATIONS and as DEVELOPER against one company carrying all six secrets, and searches the whole response text — not a field — for the raw value. A new `GET` is swept with no edit, and one whose path parameter the module cannot fill **fails the test** rather than being skipped. Two by-products: an anti-vacuity check (every secret must be found *masked* somewhere, so a wall of 404s cannot pass) and a refusal table asserted both ways | everything | Writing it found two gates nobody had written down — the proposal queue is closed to OPERATIONS, the import template to DEVELOPER — and one leak of its own making: the fixture had put the PAN in the company name, which is not masked and never will be |

### Inherited items in this lane (from `open-items.md` §2)

- ~~**IEC has no `CHECK` constraint**~~ — **done**, migration **0040**
  (`ck_exporter_profile_iec_format`). The violation test goes through raw SQL, because the
  only writer the constraint exists for is one that skipped the service, and it asserts the
  SQL pattern **equals `IEC_RE.pattern`** rather than restating it: two copies of a regex
  drifting is how a constraint stops matching the rule it was meant to be. One thing the
  test taught — an over-long IEC never reaches the constraint, `varchar(10)` refuses it
  first — so every bad case in it is short, lower-case or punctuated.
- **`POST /exporters` without `name` or `country` still creates a company** — remove the
  unnamed path once nothing calls it, then make both columns `NOT NULL` (expand → backfill →
  contract). Fits naturally beside 3.8.

---

## 4. Who is waiting on you

Developer 2's side of each is in `dev2-remaining-work.md` §3–§4.

| Developer 2's task | Needs from you | State |
|---|---|---|
| 2.4 buyer company on the deal | `CompanyPicker` (F3 stub, 3.10 full) | delivered |
| 2.6 buyer migration (P4-6) | `CompanyDirectory.create_buyer_company` (F3), and **3.2's reports** | code delivered; **the reports are still owed**, and they are what sizes the run |
| 2.8 invoicing branch on the deal | **3.12** first (see the 3.12 note) | delivered |
| 2.9 "invoicing branch is flagged" | `BranchFlagReader` stub (F3), real one (3.14) | delivered |
| 2.11 trade history on the deal page | `TradeHistoryPanel` (F3 stub, 3.22 full) | delivered, and mounted — the stub's props never changed |
| 2.12 main end-to-end ("… → payment outcome") | 3.21 | delivered |

---

## 5. Operational order on live databases — do not reorder

From allocation §6. Not a coding dependency; the order things run on a live database.

1. `pg_dump`.
2. Developer 2's buyer migration **P4-6** (after their 2.4 merges): dry run, Compliance
   reviews the name-only duplicates (IQ-8), apply, validation queries.
3. Your relationship backfill **P5-5** (3.23):
   `python -m app.modules.onboarding.backfill_trade_relationships --dry-run`, then
   `--apply --run-id <id>`, then `--validate`. The dry run tells you if step 2 has not
   happened — most deals without a buyer company is what that looks like. Undoing a run
   is one `DELETE` (the module's docstring has it), unless an invoice has been recorded
   against one of its relationships, which `--report-run` counts before you try.
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
