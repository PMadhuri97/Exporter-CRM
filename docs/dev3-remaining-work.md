# Developer 3 — what is done, and what is left

**As of 1 October 2026.** Lane: the company record, settings, GST branches and trade
history (`developer-allocation.md` §5).

Six of the twenty-five tasks are merged. The rest are **blocked, not unstarted** — the
lane's foundation PR cannot be written until Developer 1's lands, and §6 of the
allocation says so by design. This file says exactly what is waiting on what, so the
next person re-checks in a minute rather than re-deriving it.

| | |
|---|---|
| **Done** | F-prerequisites aside: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6 |
| **Blocked on Dev 1 (F1)** | F3, and everything downstream of it |
| **Blocked on Dev 2 (F2)** | 3.9's deal list, 3.23's backfill |
| **Ready the day F3 lands** | 3.18 – 3.22 (trade history), 3.24 |

---

## 1. Done

### 3.3 + 3.4 — Domestic-first qualification (P1-1, P1-2)

One migration, `onboarding_0023_domestic_first`:

- version 2 of `export_history` and `export_licence`, `required = false`, `created_by`
  = `migration:onboarding_0023_domestic_first`;
- `no_export_history`, `no_export_licence` and `geography_not_supported` deactivated.

`revenue` and `deal_size` untouched — thresholds stay in USD (BQ-1).
`sample_data.py`'s `_REQUIRED_KEYS` narrowed to `("revenue", "years_in_business")`, so
the sample companies now *demonstrate* qualifying with no export evidence.

**Proof:** `pytest app/modules/onboarding/tests/integration/test_qualification.py`
— 57 passed, including five new tests, chief among them
`test_a_domestic_company_qualifies_without_export_evidence`.

> ### Release note — the de-count
>
> After this migration, existing `export_history` and `export_licence` results **stop
> counting towards the qualification suggestion**, because `_suggest()` considers only
> criteria that are active *and required*.
>
> * A company already `QUALIFIED` is **unaffected** — qualification is final (A2) and
>   nothing recalculates it.
> * An **undecided lead re-suggests**, and may now read `QUALIFIED` where it read
>   `NOT_QUALIFIED`. That is the point of the change, but it will look like data moved
>   on its own if nobody is told.
>
> Old outcomes still render their retired reason codes: an outcome stores codes as
> JSONB strings, not foreign keys. New outcomes citing one are refused (422).

### 3.5 — "Aner Labs" (P1-4)

Four user-visible strings in `index.html`, `Sidebar.tsx` and `LoginPage.tsx`. Backend
`APP_NAME` untouched, so `openapi.json` did not move.

Storage keys containing "aner" were **deliberately left alone** — `aner.theme`,
`aner.refreshToken`, `aner.sidebar.collapsed`, the `aner-refresh` Web Lock and the
`@aner/...` package name. Renaming any of them signs users out or loses their theme
without changing a single visible word.

**Proof:** `grep -r ANER dist/` → 0.

### 3.6 — `roleLabel()` and "RM (Relationship Manager)" (P1-5)

`roleLabel()` and `roleShortLabel()` added to `platform/auth/roles.ts` and exported
from the barrel, then used at all seven sites that render a role: the app header,
`HomePage`, the Users table chip and filter, the user form's Role select and its
"Default for …" option, and the My Profile chip.

**The enum is not renamed**, per §2.3. `OPERATIONS` is written into history rows
already recorded and into both route-authorisation tables; renaming it would make the
past read as a role that never existed.

Three things worth knowing:

- **`HomePage` lowercased the label** (`humanize(role).toLowerCase()`), which would
  have rendered "rm (relationship manager)". The `.toLowerCase()` is gone.
- **The header uses the short form** ("RM"), because the full label does not fit a
  right-aligned `text-xs` line. That is what `roleShortLabel()` is for.
- **`ROLE_DESCRIPTION.COMPLIANCE` hard-coded the word** — it opened "Everything
  Operations can do". Now "Everything an RM can do". Easy to miss, and it would have
  left the retired word in the product after every other site had moved.

Backend: `catalog.py`'s OPERATIONS description said identifiers are "masked unless you
own the record". **That ownership exception no longer exists** (decision 12 —
`can_reveal_identifiers` admits COMPLIANCE and ADMIN only), so the description, the
module docstring and an inline comment were all corrected. `BUILTIN_ROLE_METADATA` has
no runtime consumer, so this is documentation.

**Proof:** `grep -r Operations dist/` → 0; 294 frontend tests pass.

### 3.1 — Conventions (P0-4)

Most of P0-4 was **already written down** — the gate list in `development.md` §7, one
head and the 32-character limit in both files, re-parenting in the register §2. Adding
it again would have created two places to keep in step, so only the genuine gaps went
in:

- the naming pattern `onboarding_00NN_<lane>_<topic>`, in both files;
- re-point `down_revision` before merging (folded into the existing re-parent rule);
- `pg_dump` before any data migration;
- expand → backfill → contract.

The naming rule carries a real example: **`onboarding_0023_domestic_criteria`, the name
`plan.md` P1-1 prescribes, is 33 characters and fails on the database** after the
migration body has run. It shipped as `onboarding_0023_domestic_first` (30). Worth
fixing in `plan.md` so the next person does not copy it.

Register updated: row for 0023, head now `onboarding_0023_domestic_first`, next free
number 0024.

### 3.2 — Data inventory (P0-3)

`backend/scripts/crm_data_inventory.sql` — read-only, every statement a `SELECT`, runs
against any environment with `psql`. Covers all seven of P0-3's questions.

**The script is the deliverable; the reports are not.** P0-3 asks for a report *per
live database* (`crm_uat_walk`, `crm_release_audit`, demo, shared test), attached to
the migration tickets. Those need someone with access to those environments. Numbers
from a development database must not be attached as findings — it carries sample data
and whatever the suite last left behind.

---

## 2. F3 — blocked on Developer 1's F1

F3 must be rebased on F1 (`developer-allocation.md` §6: merge order **F1 → F3 → F2**).
**F1 has not merged.** Checked today:

| F1 marker | Present? |
|---|---|
| `backend/app/shared/clock.py` | no |
| `ComplianceFactsReader` | no |
| `exporter_profile.background_check_expires_at` | no |
| History dimensions `check_cycle`, `gst_registration`, `trade`, `pipeline` | no |

Re-run those four checks before assuming this is still true.

When it lands, F3 is: the migration adding `identity_type`, `registration_number`,
`pipeline_status`, `created_via` and `created_via_deal_id`; the `ExporterSource.DEAL_BUYER`
enum value; the `CompanyDirectory` and `BranchFlagReader` interfaces with working stubs;
and the `CompanyPicker` / `TradeHistoryPanel` component stubs with their final props.

**Dev 2's F2 consumes those interfaces**, so F3 blocks their foundation too.

---

## 3. Blocked on F3

| # | Task | Needs |
|---|---|---|
| 3.7 | Remove website from forms, schemas and CSV (IQ-16) | — in principle startable, but it moves request schemas and so `openapi.json`; cleaner after F3 to avoid two artifact regenerations |
| 3.8 | Service create paths set `identity_type` / `created_via`; foreign registration number required (IQ-7); mask `registration_number`; refuse `NOT_IN_PIPELINE` | F3's columns |
| 3.9 | `search_profiles` excludes `NOT_IN_PIPELINE`; "Not in pipeline" on the company page; mount `CompanyDealsList` | F3's columns **and Dev 2's F2** for the deal list |
| 3.10 | `POST /companies/match` (BQ-2), `CompanyPicker` full version | F3 |
| 3.11 | `POST /exporters/{id}/pipeline` | F3 |
| 3.12 | Evolve `exporter_gstin` in place: state, status, address, flag, soft deactivation | F3 |
| 3.13 | GST registration add/deactivate routes; `GstRegistrationsSection.tsx` | 3.12 |
| 3.14 | Flag / unflag a GST registration; real `BranchFlagReader` | 3.12 |
| 3.15 | Warn-only consequences of a flagged GSTIN held by two companies (IQ-9) | 3.14 |
| 3.16 | Derive a PAN for PAN-less companies — **only if 3.2's report says it is worth it** | 3.2 reports |
| 3.17 | "Verify GSTIN" link for COMPLIANCE and ADMIN | 3.12 |

---

## 4. Needs Developer 2

- **3.9's `CompanyDealsList`** (as seller / as buyer) is Dev 2's component, delivered in
  F2.
- **3.23, the relationship backfill**, runs **after** Dev 2's buyer migration P4-6 has
  been applied to an environment. That is operational order, not a coding dependency —
  the code can be written first.

---

## 5. Ready as soon as F3 lands

Trade history (P5) needs nothing from Dev 1 or Dev 2 beyond `deal.buyer_company_id`,
which arrives in F2:

| # | Task |
|---|---|
| 3.18 | `trade_relationship(seller_company_id, buyer_company_id)`, unique pair, seller ≠ buyer, `get_or_create` |
| 3.19 | `trade_invoice` (identity frozen) and `trade_invoice_outcome` (append-only chain); currency stored, never converted (IQ-4) |
| 3.20 | Read and write routes, roles and masking (IQ-19), `trade` history rows |
| 3.21 | Record an outcome after handover; claimed past trade with `proof_status = CLAIMED` |
| 3.22 | `TradeHistoryPanel` full version |
| 3.24 | Masking sweep: every CRM read as OPERATIONS and DEVELOPER, asserting no unmasked PAN, GSTIN, IEC, CIN, registration number or contact |

Note the design adjustment in §1 of the allocation: **the relationship is found by the
pair `(deal.company_id, deal.buyer_company_id)` — there is no `relationship_id` column
on `deal`.** That is deliberate, and it keeps this lane out of the deal table and its
terminal-deal trigger.

---

## 6. Operational order — do not reorder

From `developer-allocation.md` §6. Not a coding dependency; it is the order things run
on a live database.

1. `pg_dump`.
2. Dev 2's buyer migration **P4-6**, after their task 2.4 merges. Dry run first,
   Compliance reviews the name-only duplicates (IQ-8), then apply, then the validation
   queries.
3. Dev 3's relationship backfill **P5-5** (task 3.23).
4. Dev 2's **P4-10** (retire `deal_buyer` writes), only once *every* environment has
   passed step 2.

---

## 7. Open questions this lane will hit

- **3.16** is explicitly conditional on what 3.2's reports show. Do not build it first.
- **3.7** needs a decision on companies already cleared when the website screening item
  retires: their decision pinned the eight items as they stood. The safe answer is that
  they stay cleared — but it should be decided, not inherited.
- **`plan.md` P1-1 prescribes a migration id that cannot work** (33 characters). Worth
  correcting at the source.
