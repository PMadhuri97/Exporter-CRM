# CRM database audit — 4. Migration plan and validation strategy

**Part 4 of 4.** [1 Inventory](inventory.md) · [2 Audit](audit.md) ·
[3 Options](options.md) · [4 Migration plan](migration-plan.md)

This file holds Deliverable F (the ordered migration plan) and the Phase 7 validation
strategy for **Design A**, the optimised design that takes the CRM's own tables from 35 to
32 ([options.md §2](options.md)). The old system's 14 tables are out of scope, so the
`onboarding` schema goes from 49 to 46. Design B's optional step is §3, step 16. The squash of the
CRM's migrations into **one baseline file** (step 17) is **deferred to the CRM's separation** from the
other modules.

**Status (14 October 2026):** checkpoint 1 (steps 1–3) is built. Every business question
is answered ([audit.md §6](audit.md)). Opportunity ids (O-) and questions (Q-) are
defined in [audit.md](audit.md).

## Scope (decided 14 October 2026)

**Only CRM files change.** The old onboarding system shares the `onboarding` schema with
the CRM but is not part of it. That covers the 14 tables of the request, case,
identity-provider (Sumsub) and KYB machinery, with their entities, services, workflow,
routes and 23 test files. None of it is touched, **even though the CRM does not need
it**. Nor is any file of another module or of the platform: `app/main.py`,
`app/bootstrap.py`, `backend/conftest.py`, the `cases` module, and
`app/platform/authentication/migrations`.

The only exceptions are three shared files that a CRM route change forces. Only their
CRM entries change:

- `backend/tests/contract/test_route_authorization_coverage.py`;
- the generated OpenAPI artifact;
- the frontend's generated API types.

So:

- **Step 13 (retire the old system) is out of scope.** The CRM stops *reading*
  `ubo_record` (step 5). The legacy tables, code and routes stay exactly as they are.
- **Steps 9 and 17 do not run.** Step 9 because Q9 = keep both entry paths; step 17
  stays deferred to the separation.
- **Step 16 stays optional and later.**
- **The CRM's own tables go from 35 to 32.** The `onboarding` schema goes from 49 to 46.

## Ground rules

These come from `docs/database.md` §10 and the migration register:

- **Migration shape.** One chain, one head. Revision ids are at most 32 characters. The
  next free number is **`onboarding_0054`**.
- **Backups.** Take a `pg_dump` before any migration that changes data.
- **Populated tables.** Change a column on a populated table in three steps: expand,
  backfill, contract.
- **Append-only tables.** They refuse `DELETE`, so clearing one needs `TRUNCATE`.
- **Tests.** Every new constraint gets a direct-SQL violation test.
- **Data steps that need a person** are commands with `--dry-run`, `--apply` and
  `--validate`, never revisions. This follows the `migrate_deal_buyers.py` precedent.
- **Removing a table or column takes two releases.** Release *N* stops all code from
  reading or writing it. Release *N+1* drops it. During a rolling deploy, an instance
  still on *N−1* must never meet a missing table. **Here:** `fix/migration-crm` is
  release *N*. Every drop goes in a separate follow-up PR, built once this branch is
  deployed (§1.1). One exception: `0056` drops `deal_buyer_company_map` on this branch.
  Only the offline `migrate_deal_buyers` command ever reads it, never a request, so an
  instance still on *N−1* cannot meet the missing table.
- **Data commands are run by the user.** A command that changes `aner_settlement` is
  built and tested on scratch databases. The user runs `--apply` (Q7: `aner_settlement`
  is the only database with data; neither the buyer migration nor the RM backfill has
  run).
- **"Every environment"** means every database that holds data someone needs. Today
  that is `aner_settlement` only (Q7, 14 October). Scratch and test databases are
  rebuilt from empty.

---

## 1. Sequence at a glance

| Step | What | Opportunity | Kind | Reversible? | Phase |
|---|---|---|---|---|---|
| 0 | Pre-flight on `aner_settlement`: dump, read-only checks | — | read only | — | before each phase |
| 1 | ORM catch-up; a stronger contract test | O11 | code | yes | 1 (built) |
| 2 | Integrity constraints | O7, O8 | DDL, additive (`0054`) | yes | 1 (built) |
| 3 | Freeze old configuration versions | O9 | triggers (`0055`) | yes | 1 (built) |
| 4 | Fold the buyer map into `deal_buyer` | O21 | DDL + command change (`0056`) | yes, until the buyer migration runs | 2 |
| 5 | People in `exporter_contact`; the CRM stops reading `ubo_record` | O2 | DDL + code + frontend (`0057`) | yes, until a person is recorded | 2 |
| 6 | Reason codes into code | O20 | code | yes | 3 |
| 7 | Remove the bank placeholder from code | O10 | code | yes | 3 |
| 8 | Remove the legacy result columns from code | O3 | code | yes | 3 |
| 10 | Retire the RM free text from code | O4 | code (backfill run by the user) | yes | 4 |
| 11 | Convert the GST free-text address | O5 | new command + code | yes | 4 |
| 12 | Stop writing `deal_buyer`; freeze it | O6 | code + trigger (`0058`) | the freeze, yes | 4 |
| 14 | Deal reference unique per seller | O18 | DDL (`0059`) | yes | 4 |
| 15 | Update documents | — | docs | — | each phase |
| D | **Follow-up PR: the drops** | O20, O10, O3, O4, O5, O21 | DDL (`0060`) | **no** for the RM text (discarded, Q4) | after this branch is deployed |
| — | ~~9 One sanctions entry path~~ | O19 | — | — | **not done** (Q9: keep both paths) |
| — | ~~13a/13b Retire the old system~~ | O1 | — | — | **out of scope** (not CRM) |
| 16 | *(optional, Design B)* Retire `deal_buyer` | O15 | code, then drop | **no** (archived first) | later, not this branch |
| 17 | Squash the CRM's migrations into one baseline file | O24 | — | — | **deferred to the separation** |

**Dependencies:**

- Steps 1–3 need nothing and change no data.
- **Step 4 must land before the buyer migration runs.** In `aner_settlement` the map is
  empty and the migration has not run (Q7), so the fold moves no data.
- Step 5 must come before step 12, because the people picker and the buyer-company
  screens share the company views.
- Steps 6–8, 10 and 11 remove code paths. Their columns and tables are dropped only in
  the follow-up PR (D).
- Step 12's freeze lands after step 4, so the command can still fill the mapping
  columns, which the trigger allows.

**Table count.** `onboarding` schema: 49 → 48 (step 4, `0056` drops the empty map,
which is unused once the command writes the columns) → 48 at the end of this branch →
**46** after the follow-up PR. Of those, the CRM's own tables go 35 → 34 → **32**. The 14
old-system tables stay.

### 1.1 Delivery: branch `fix/migration-crm`, four phases, then one follow-up PR

The work ships as one PR, `fix/migration-crm` (based on `main`), built one phase at a
time. Each phase is left **unstaged** for the user to review and commit. Nothing is
staged or committed by Claude.

| Phase | Steps | Migrations | Status |
|---|---|---|---|
| 1 | 1–3: ORM catch-up, integrity rules, frozen configuration versions | `0054`, `0055` | Committed (`9224daf`) |
| 2 | 4–5: buyer mapping onto `deal_buyer`; people in `exporter_contact` | `0056_buyer_map_cols`, `0057_people` | Committed (`a103c12`) |
| 3 | 6–8: reason codes into code; bank placeholder and legacy result columns out of code | none | Built |
| 4 | 10–12, 14, 15: RM text and GST address out of code, GST command, `deal_buyer` freeze, deal reference rule, documents | `0058`, `0059` | — |
| Follow-up PR | D: drop `qualification_reason_code`, `bank_activity_finding`, the three `verification_result` columns, `exporter_profile.relationship_manager`, `exporter_gstin.address` | `0060` | after deploy |

**Tests at each phase.**

- Phase 1 and the end of phase 4 run the full `pytest --crm`, split across three copies
  of a freshly migrated database, one copy per chunk, run in parallel.
- Phases 2 and 3 run the tests that touch what changed, plus the contract and new
  direct-SQL tests.
- Every phase runs `alembic check`, `ruff`, and `lint-imports --config importlinter.ini`.
  A phase that changes the frontend also runs `tsc -b`, `eslint` and `vitest`.

**What phase 1 found.** The new rules caught two write-order bugs that the
services had always had:

- `ExporterProfileService.update_profile` wrote its history rows, each of which
  flushes, before recomputing `identity_type`. For a moment the database held a new
  PAN with the old type. It now recomputes `identity_type` first.
- `SanctionsScreeningService.record_run` could insert a hit before its run's list rows.
  There is no relationship between the two, so the session does not order them. It now
  flushes the list rows first.

The new rules also caught test fixtures that wrote invented values:

- History rows naming deals that never existed. These now use `make_bare_deal`.
- Raw-SQL PANs written without `identity_type`.
- Two schema tests asserting the old shape. They were updated.

---

## 2. Step 0 — pre-flight, in every environment

1. Record the environment: `SELECT current_database(), version_num FROM
   alembic_version` and `pg_is_in_recovery()`.
2. Take a `pg_dump -Fc` and keep it with the release record.
3. Run the read-only checks below and attach their output to the change ticket. A step
   whose check is not zero in some environment does not run there until the rows are
   explained.

Every statement is a `SELECT`. Run them with:

```
psql -v ON_ERROR_STOP=1 -c "SET default_transaction_read_only = on" -f <file>
```

They were run against the development database on 12 October 2026; the results are in
§2.1.

```sql
-- 1. Where am I
SELECT current_database() AS db, (SELECT version_num FROM public.alembic_version) AS revision, pg_is_in_recovery() AS replica;

-- 2. Legacy tables: any rows anywhere?
SELECT 'onboarding_request' AS t, count(*) FROM onboarding.onboarding_request
UNION ALL SELECT 'ubo_record', count(*) FROM onboarding.ubo_record
UNION ALL SELECT 'onboarding_event', count(*) FROM onboarding.onboarding_event
UNION ALL SELECT 'onboarding_document', count(*) FROM onboarding.onboarding_document
UNION ALL SELECT 'kyb_vendor_result', count(*) FROM onboarding.kyb_vendor_result
UNION ALL SELECT 'kyb_vendor_registration', count(*) FROM onboarding.kyb_vendor_registration
UNION ALL SELECT 'onboarding_case', count(*) FROM onboarding.onboarding_case
UNION ALL SELECT 'case_state_transition', count(*) FROM onboarding.case_state_transition
UNION ALL SELECT 'kyc_case', count(*) FROM onboarding.kyc_case
UNION ALL SELECT 'person_profile', count(*) FROM onboarding.person_profile
UNION ALL SELECT 'onboarding_customers', count(*) FROM onboarding.onboarding_customers
UNION ALL SELECT 'onboarding_applicant_mappings', count(*) FROM onboarding.onboarding_applicant_mappings
UNION ALL SELECT 'onboarding_verifications', count(*) FROM onboarding.onboarding_verifications
UNION ALL SELECT 'onboarding_webhook_events', count(*) FROM onboarding.onboarding_webhook_events
UNION ALL SELECT 'bank_activity_finding', count(*) FROM onboarding.bank_activity_finding;

-- 3. UBOs the CRM can see today, and those it cannot (request names no company)
SELECT count(*) FILTER (WHERE p.customer_id IS NOT NULL) AS ubos_matching_a_company,
       count(*) FILTER (WHERE p.customer_id IS NULL)     AS ubos_matching_nothing
FROM onboarding.ubo_record u
JOIN onboarding.onboarding_request r ON r.id = u.onboarding_request_id
LEFT JOIN onboarding.exporter_profile p ON p.customer_id = r.customer_id;

-- 4. Sanctions runs whose UBO subject is a legacy ubo_record
SELECT count(*) AS ubo_runs,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM onboarding.ubo_record u WHERE u.id = s.subject_reference)) AS ubo_runs_dangling
FROM onboarding.sanctions_run s WHERE s.subject_type = 'UBO';

-- 5. Integrity rules O7 would add: violations
SELECT 'evidence -> verification_review' AS rule, count(*) FROM onboarding.background_check_evidence e
 WHERE e.verification_review_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM onboarding.verification_review v WHERE v.id = e.verification_review_id)
UNION ALL SELECT 'history.deal_id -> deal', count(*) FROM onboarding.exporter_lifecycle_history h
 WHERE h.deal_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM onboarding.deal d WHERE d.id = h.deal_id)
UNION ALL SELECT 'sanctions_run cycle of another company', count(*) FROM onboarding.sanctions_run s
 JOIN onboarding.check_cycle c ON c.id = s.cycle_id WHERE c.company_id <> s.company_id
UNION ALL SELECT 'verification_result cycle of another company', count(*) FROM onboarding.verification_result v
 JOIN onboarding.check_cycle c ON c.id = v.cycle_id WHERE v.subject_company_id IS NOT NULL AND c.company_id <> v.subject_company_id
UNION ALL SELECT 'hit list not screened in its run', count(*) FROM onboarding.sanctions_hit h
 WHERE NOT EXISTS (SELECT 1 FROM onboarding.sanctions_run_list l WHERE l.run_id = h.run_id AND l.code = h.list_code)
UNION ALL SELECT 'completion company <> activity company', count(*) FROM onboarding.follow_up_completion f
 JOIN onboarding.exporter_activity a ON a.id = f.activity_id WHERE a.customer_id <> f.customer_id
UNION ALL SELECT 'bank finding without company', count(*) FROM onboarding.bank_activity_finding b
 WHERE NOT EXISTS (SELECT 1 FROM onboarding.exporter_profile p WHERE p.customer_id = b.customer_id);

-- 6. Derived-column rules O8 would add: violations
SELECT 'identity_type disagrees with pan/registration_number' AS rule, count(*) FROM onboarding.exporter_profile
 WHERE identity_type IS DISTINCT FROM (CASE WHEN pan IS NOT NULL THEN 'IN_PAN' WHEN registration_number IS NOT NULL THEN 'FOREIGN_REG' END)::onboarding.company_identity_type_enum
UNION ALL SELECT 'state_code <> first two characters of gstin', count(*) FROM onboarding.exporter_gstin
 WHERE state_code IS NOT NULL AND state_code <> left(gstin, 2);

-- 7. Superseded columns: what would be dropped
SELECT 'profile: RM text only (no user id)' AS what, count(*) FROM onboarding.exporter_profile
 WHERE btrim(coalesce(relationship_manager, '')) <> '' AND relationship_manager_user_id IS NULL
UNION ALL SELECT 'profile: RM text and user id', count(*) FROM onboarding.exporter_profile
 WHERE btrim(coalesce(relationship_manager, '')) <> '' AND relationship_manager_user_id IS NOT NULL
UNION ALL SELECT 'gstin: free-text address, no address_id', count(*) FROM onboarding.exporter_gstin
 WHERE btrim(coalesce(address, '')) <> '' AND address_id IS NULL
UNION ALL SELECT 'verification_result: legacy review, no chain', count(*) FROM onboarding.verification_result v
 WHERE (v.review_status IS NOT NULL OR v.reviewed_by IS NOT NULL)
   AND NOT EXISTS (SELECT 1 FROM onboarding.verification_review r WHERE r.verification_result_id = v.id)
UNION ALL SELECT 'verification_result: evidence_reference set', count(*) FROM onboarding.verification_result WHERE evidence_reference IS NOT NULL
UNION ALL SELECT 'deal_buyer rows', count(*) FROM onboarding.deal_buyer
UNION ALL SELECT 'deal_buyer rows not yet mapped to a company', count(*) FROM onboarding.deal_buyer b
 WHERE NOT EXISTS (SELECT 1 FROM onboarding.deal_buyer_company_map m WHERE m.deal_buyer_id = b.id);

-- 8. Business rules awaiting a decision
SELECT 'duplicate deal reference per seller' AS what, count(*) FROM (
  SELECT company_id, reference FROM onboarding.deal GROUP BY 1, 2 HAVING count(*) > 1) x
UNION ALL SELECT 'duplicate deal reference globally', count(*) FROM (
  SELECT reference FROM onboarding.deal GROUP BY 1 HAVING count(*) > 1) y;

-- 9. Cached gauges agree with their chains (should be 0)
SELECT 'qualification cache' AS what, count(*) FROM onboarding.exporter_profile p
 WHERE p.qualification::text <> coalesce((SELECT o.outcome::text FROM onboarding.qualification_outcome o
   WHERE o.customer_id = p.customer_id AND NOT EXISTS (SELECT 1 FROM onboarding.qualification_outcome n WHERE n.supersedes_outcome_id = o.id)), 'NOT_YET_REVIEWED')
UNION ALL SELECT 'background-check cache', count(*) FROM onboarding.exporter_profile p
 WHERE p.background_check::text <> coalesce((SELECT d.to_value::text FROM onboarding.background_check_decision d
   WHERE d.company_id = p.customer_id AND NOT EXISTS (SELECT 1 FROM onboarding.background_check_decision n WHERE n.supersedes_decision_id = d.id)), 'NOT_STARTED');
-- 10. The buyer map must be empty before it is folded into deal_buyer
SELECT 'deal_buyer_company_map rows' AS what, count(*) FROM onboarding.deal_buyer_company_map;

-- 11. Every reason code ever cited (the code catalogue must contain each)
SELECT DISTINCT jsonb_array_elements_text(reason_codes) AS cited_reason_code FROM onboarding.qualification_outcome ORDER BY 1;

-- 12. Sanctions results not written by the structured screening
SELECT entity_type, count(*) FILTER (WHERE provider_reference LIKE 'sanctions-screening:%') AS from_screening,
       count(*) FILTER (WHERE provider_reference IS NULL OR provider_reference NOT LIKE 'sanctions-screening:%') AS entered_directly
FROM onboarding.verification_result WHERE verification_type = 'SANCTIONS' GROUP BY 1 ORDER BY 1;

-- 13. People: contacts, and legacy UBOs whose name already matches a contact of the same company
SELECT 'contacts' AS what, count(*) FROM onboarding.exporter_contact
UNION ALL SELECT 'legacy UBO with a same-name contact', count(*)
FROM onboarding.ubo_record u JOIN onboarding.onboarding_request r ON r.id = u.onboarding_request_id
JOIN onboarding.exporter_contact c ON c.customer_id = r.customer_id
 AND lower(btrim(c.name)) = lower(btrim(u.first_name || ' ' || u.last_name));
```

Also run the existing commands in their read-only modes:

- `python -m app.modules.onboarding.backfill_relationship_managers --dry-run`, before
  step 10;
- `python -m app.modules.onboarding.migrate_deal_buyers --dry-run`, before step 12.

### 2.1 Results on the development database (12 October 2026)

| Check | Result |
|---|---|
| 1 Revision | `onboarding_0053_auto_criteria`, not a replica |
| 2 Legacy tables, `bank_activity_finding` | 0 rows each |
| 3 UBOs visible / unmatched | 0 / 0 |
| 4 UBO sanctions runs | 0 |
| 5 Integrity violations | 0 for every rule |
| 6 Derived-column violations | 0 / 0 |
| 7 RM text only | **100** |
| 7 GST text address without `address_id` | **6** |
| 7 Legacy review without chain / `evidence_reference` set | 0 / 0 |
| 7 `deal_buyer` rows / not yet mapped | **4 / 4** |
| 8 Duplicate deal references (per seller / global) | 0 / 0 |
| 9 Cache disagreements | 0 / 0 |
| 10 `deal_buyer_company_map` rows | **0**, so step 4 needs no data move |
| 11 Reason codes ever cited | `industry_not_supported`, `insufficient_information`, `revenue_below_threshold`, `years_in_business_below_threshold`: all in the 9-row catalogue |
| 12 SANCTIONS results from the screening / entered directly | EXPORTER 2 / **58**; BUYER 0 / 1 |
| 13 Contacts / legacy UBOs matching a contact | 181 / 0 |

**These results say nothing about any other environment.**

---

## 3. The steps

Each step is one PR unless it says otherwise.

### Step 1 — ORM catch-up (O11). Code only; reversible

- **Declare in the models** what so far exists only in the database: the 12 CHECKs and
  the server defaults listed in [inventory.md §7.2](inventory.md). (The
  `DealBuyerCompanyMap` primary-key mismatch disappears with step 4.)
- **Extend `tests/contract/test_orm_matches_the_onboarding_schema.py`** to compare, for
  each table, the primary-key columns, the CHECK constraint names and whether a server
  default is present. The comparison script described in inventory §7.2 is the method.
- **Validation:**
  - `alembic check` reports no operations.
  - The extended test passes, and fails when any one declaration is removed.
- **Rollback:** revert the PR.

### Step 2 — integrity constraints (O7, O8). Migration `onboarding_0054`; additive; reversible

| Target | DDL |
|---|---|
| `background_check_evidence` | FK `(verification_review_id)` → `verification_review (id)`, `NOT VALID`; partial index `WHERE verification_review_id IS NOT NULL` |
| `exporter_lifecycle_history` | FK `(deal_id)` → `deal (id)`, `NOT VALID` |
| `sanctions_run` | Add `(cycle_id, company_id)` → `check_cycle (id, company_id)`, `NOT VALID`; drop `fk_sanctions_run_cycle` |
| `verification_result` | Add `(cycle_id, subject_company_id)` → `check_cycle (id, company_id)`, `NOT VALID`; drop `fk_verification_result_cycle_id` |
| `sanctions_hit` | FK `(run_id, list_code)` → `sanctions_run_list (run_id, code)`, `NOT VALID` |
| `exporter_activity` | `UNIQUE (id, customer_id)` |
| `follow_up_completion` | Add `(activity_id, customer_id)` → `exporter_activity (id, customer_id)`, `NOT VALID`; drop the single-column FK |
| `exporter_profile` | `CHECK (identity_type IS NOT DISTINCT FROM CASE WHEN pan IS NOT NULL THEN 'IN_PAN' WHEN registration_number IS NOT NULL THEN 'FOREIGN_REG' END)`, `NOT VALID` |
| `exporter_gstin` | `CHECK (state_code IS NULL OR state_code = left(gstin, 2))`, `NOT VALID` |

**Validating the new rules.** In the same migration, for each rule, count the existing
violations (checks 5 and 6):

- If the count is 0, run `VALIDATE CONSTRAINT`.
- Otherwise, print the count and the listing query, and leave the rule `NOT VALID`.
  It still applies to every new or changed row. This follows the 0042 precedent.

**Locks.** `ADD … NOT VALID` takes `ACCESS EXCLUSIVE` briefly. `VALIDATE` takes
`SHARE UPDATE EXCLUSIVE`, so writes continue. Run it in a quiet window.

**Code.**

- Each model declares its new rule.
- Each rule gets one direct-SQL violation test, through `psycopg2`.
- Services are unchanged: they already refuse each of these violations.

**Rollback.** The downgrade drops the new constraints and restores the single-column
FKs. Nothing is lost.

### Step 3 — freeze old configuration versions (O9). Migration `onboarding_0055`; reversible

**Triggers.** Both use `onboarding.prevent_field_mutation_when_set`:

| Table | Trigger | Frozen columns |
|---|---|---|
| `payment_term` | `trg_payment_term_version_immutability` | `code`, `version`, `label`, `kind`, `days`, `created_by`, `created_at` |
| `sanctions_list` | `trg_sanctions_list_version_immutability` | `code`, `version`, `name`, `authority`, `mandatory`, `list_version_date`, `created_by`, `created_at` |

`is_current`, `active` and `updated_at` stay writable.

**Precondition.** Confirm that `payment_term_service` and `sanctions_list_service` only
ever flip `is_current` or `active` on an existing row. Their docstrings say every other
change writes a new version.

**Validation.**

- A direct-SQL test shows that changing a frozen column fails.
- Flipping `is_current` still succeeds.
- The service suites pass unchanged.

**Rollback.** Drop the triggers.

### Step 4 — fold the buyer map into `deal_buyer` (O21). Migration `onboarding_0056` + command change

**Precondition.** Check 10 = 0 in every environment. If any environment has run the
buyer migration, the map holds rows. In that case the migration copies them first:

```sql
UPDATE onboarding.deal_buyer b
   SET mapped_company_id = m.company_id, match_rule = m.match_rule,
       matched_by = m.matched_by, matched_at = m.matched_at, mapping_run_id = m.run_id
  FROM onboarding.deal_buyer_company_map m
 WHERE m.deal_buyer_id = b.id;
```

`deal_buyer` has no update trigger yet, and the map's primary key guarantees one row
per buyer.

**DDL.**

- Add the five columns, the completeness CHECK and the two indexes
  ([options.md §2.3](options.md)).
- Add a set-once trigger on the five columns.
- Then drop `deal_buyer_company_map`. The map is append-only, but `DROP TABLE` is not a
  row operation.

**Code.**

- `migrate_deal_buyers.py` writes the five columns through the ORM, instead of a map
  row.
- Idempotency becomes "skip a row whose `mapped_company_id` is set".
- `--rollback` reports by `mapping_run_id`.
- `DealBuyerCompanyMap` is removed.
- The command's 32 safety tests are re-pointed at the new columns. Each tested
  guarantee must still hold:
  - a re-run creates nothing;
  - a mapping is never changed;
  - `ALREADY_LINKED` behaves as before;
  - name confirmations behave as before.

**Validation.**

- `--dry-run` reports the same plan before and after the change, on a seeded copy.
- After `--apply`, a second `--apply` creates nothing.
- After the step, `count(*) WHERE mapped_company_id IS NOT NULL` equals the old map row
  count, which is 0 where the map was empty.

**Rollback.** The downgrade recreates the map from the columns and drops the columns.
That is lossless, because the relationship is one-to-one.

### Step 5 — people in `exporter_contact` (O2). Migration `onboarding_0057`; code

**Decided (Q2, 14 October).**

- Only name and role are required. Date of birth, nationality, DIN, ownership %,
  control type and identification are optional, and masked when filled.
- The existing `view_full_tax_id` permission reveals them, so there is **no
  `auth_0011`** and no file under `app/platform` changes.
- The old system is not touched. The copy below only **reads** `ubo_record` and
  `onboarding_request`, and no old-system file changes. Nothing has written those
  tables since the CRM replaced them (their worker is not started and their request
  routes are not mounted), so a one-time copy loses nothing.

**DDL.** As in [options.md §2.2](options.md):

- role flags and person fields, the CHECKs, and `UNIQUE (id, customer_id)`;
- `DELETE` refused;
- the `NOT VALID` composite FK from `sanctions_run (subject_reference, company_id)`.

Validate the FK once the copy below has run.

**Data: copy legacy UBOs, keeping their ids.** Copy only `ubo_record` rows whose
request names an existing company:

| `exporter_contact` | From |
|---|---|
| `id` | `ubo_record.id`, **preserved** so existing runs stay valid |
| `customer_id` | `onboarding_request.customer_id` |
| `name` | `btrim(first_name \|\| ' ' \|\| last_name)` |
| `is_contact` / `is_director` / `is_ubo` | false / false / true |
| `date_of_birth` | `ubo_record.date_of_birth` is `varchar(512)` and may be encrypted. Decrypt and parse it in the command; a value that does not parse is reported and left NULL |
| `nationality`, `residence_country` | the same values |
| `ownership_pct` | `ownership_percentage` |
| `control_type` | `control_type::text` |
| `identification_*` | from `identification_type` and `identification_number`, re-encrypted with the field cipher |
| `status` | `ACTIVE` |
| `source` / `source_ref` | `LEGACY_UBO_RECORD` / `onboarding_request_id` |
| `created_at` | `ubo_record.created_at` |

- **Edge cases.** Rows whose request names no company are reported and not copied.
  They stay in `ubo_record`, which is not changed. A UBO whose name matches an existing
  contact of the same company (check 13) is copied as its own row and reported, so a
  person can decide whether to merge them.
- **Where the copy runs.** `aner_settlement` has 0 rows to copy, so the copy lives in
  the revision, with `ON CONFLICT (id) DO NOTHING`. Encrypted values cannot be decrypted
  in SQL. The revision therefore copies only rows whose `date_of_birth` and
  `identification_number` are NULL. It refuses, with the count, if any other linked row
  exists; that row then needs a command.
- **History.** Each copied person gets one `person` history row.

**Code.**

- `ExporterContact` gains the fields.
- The contact service adds people operations: add a director or UBO, and set roles.
- Every reader that means "contacts" adds `is_contact`: `deal_service:1320`,
  `company_directory:470`, the Contacts panel and the engagement views.
- `sanctions_screening_service` (`_ubos_of`, `_subject_name`, `rescreen_due`) and
  `company_group_service` (`_people_of`, `_people_with`) read people with
  `is_director OR is_ubo`. DIRECTOR runs reference a person; free-text directors are
  still accepted only when `subject_reference` is NULL.
- Masking in `api/schemas/masking.py` covers `date_of_birth`, `din` and the
  identification number, revealed by `view_full_tax_id`.
- People are written with the existing contact permissions. No new permission.

**Frontend.**

- A People view lists contacts, directors and UBOs.
- The sanctions subject picker lists people.

**Tests.**

- Rewrite `test_sanctions_screening.py:249` and `test_company_groups.py:124` to create
  people through the API, instead of raw legacy SQL.
- Add masking tests.
- Add a direct-SQL test for each new CHECK and for the delete refusal.

**Validation.**

```sql
SELECT count(*) FROM onboarding.ubo_record u
  JOIN onboarding.onboarding_request r ON r.id = u.onboarding_request_id
  JOIN onboarding.exporter_profile p ON p.customer_id = r.customer_id
 WHERE NOT EXISTS (SELECT 1 FROM onboarding.exporter_contact c WHERE c.id = u.id);       -- expect 0
SELECT count(*) FROM onboarding.sanctions_run s WHERE s.subject_reference IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM onboarding.exporter_contact c
                    WHERE c.id = s.subject_reference AND c.customer_id = s.company_id);  -- expect 0
```

**Rollback.** The downgrade drops the new columns and constraints. It refuses while any
row has `is_director OR is_ubo` and was not copied from the legacy table. After that
point, restore the step 0 dump instead.

### Steps 6, 7 and 8 — small removals (O20, O10, O3)

**Phase 3 of this branch is release N: code only.** The drops (release N+1) go in the
follow-up PR, step D. Q3 = no bank feed is planned, so the placeholder goes.

- **O20 (reason codes).** Add `domain/qualification_reason_codes.py`, holding the 9 rows
  exactly as they are, including the 3 inactive ones.
  - `GET /qualification/reason-codes` and the outcome validation read the catalogue.
  - Add a test that every code cited in any `qualification_outcome.reason_codes` (check
    11) is in the catalogue.
  - Remove `QualificationReasonCode` from the repository.
- **O10 (bank placeholder).** Remove `list_bank_findings`, the
  `/exporters/{id}/bank-activity` route and its schema.
  - `BankActivityPanel` renders "no bank-monitoring feed is connected" without a request.
  - Update `test_route_authorization_coverage.py`.
- **O3 (legacy result columns).** **Precondition:** check 7's "legacy review, no chain"
  and "`evidence_reference` set" are both 0 in every environment. If either is not, stop:
  those values exist nowhere else.
  - Remove the `VERIFICATION_LEGACY_REVIEW_UNCHAINED` path (`verification_service.py`
    around lines 541 and 1026).
  - Remove `evidence_reference`, `reviewed_by` and `review_status` from the model, the
    API schema (`api/schemas/verification.py:188,248`) and the frontend types.
  - Regenerate OpenAPI.

**Release N+1: in the follow-up PR's migration (step D).**

- Drop `qualification_reason_code`.
- Drop `bank_activity_finding`.
- Drop `trg_verification_result_field_immutability`, then drop the three columns.
- `verification_review_status_enum` stays, because `verification_review` uses it.

**Validation.**

- The qualification, screening and verification suites pass.
- The table count is 46.

**Rollback.** The downgrade recreates both tables, re-seeding the reason codes from the
catalogue, and re-adds the empty columns and the trigger. Nothing is lost: the bank
table and the columns were empty.

### Step 9 — one entry path for sanctions (O19). **Not done**

**Q9 = keep both paths (14 October).** A person may still record a SANCTIONS result
directly. Nothing below is built; it is kept for reference.

- `POST /verifications` refuses `verification_type = SANCTIONS` for EXPORTER and
  DIRECTOR. Return a 422 that says to record a screening run instead.
- `SanctionsScreeningService._sync_company_result` keeps calling
  `VerificationService.trigger_verification` internally. That call does not go through
  the route.
- Sample data (`sample_data_deals.py:326`, and the background-check sample) records
  runs instead of direct results.
- Existing directly-entered results stay valid. Nothing is rewritten.
- **Validation:** a route test asserts that a hand-entered SANCTIONS result is refused,
  and the Clear and handover suites still pass when results come only from runs.
- **Rollback:** revert.

### Step 10 — the RM free text (O4). Code in phase 4; drop in the follow-up PR

**Decided (Q4, 14 October):** names that match no user are **discarded**. There is no
archive mode and no history row.

1. **The user runs the backfill on `aner_settlement`:** `backfill_relationship_managers
   --dry-run`, read the report, `--apply --run-id …`, `--validate`. Before that, phase 4
   runs it on a scratch copy and reports how many of the 100 names match a user.
2. **Phase 4 (release N):** remove the field from the model's read paths, from the list
   and detail schemas, from CSV export, and from the `create_or_get_profile` signature.
   The API already refuses it on input. The column stays.
3. **Follow-up PR (release N+1):** `DROP COLUMN relationship_manager`.

**Validation.** The filters (`me`, `none`, `inactive`) are unchanged. No response carries
`relationship_manager` text.

**Irreversible after the drop.** The unmatched text survives only in the `pg_dump` taken
before the follow-up PR's migration runs.

### Step 11 — the GST free-text address (O5). Command and code in phase 4; drop in the follow-up PR

**Decided (Q5, 14 October):** convert automatically, as type `CORRESPONDENCE`.

1. A new `convert_gst_addresses` command, with `--dry-run`, `--apply` and `--validate`.
   For each branch with text and no `address_id`, it creates a `company_address`
   through `CompanyAddressService` and links the branch. The address has:
   - `line1` = the text, truncated to 255 characters, with any remainder in `line2`;
   - `country = 'IN'`;
   - `address_type = 'CORRESPONDENCE'`.

   History is written for each address. Two branches of one company with the same text
   share one address. Text longer than 510 characters is reported and skipped, for a
   person to handle. The user runs `--apply` on `aner_settlement` (6 branches).
2. **Phase 4 (release N):** the API stops returning and accepting `address`. The
   structured address is the only one.
3. **Follow-up PR (release N+1):** `DROP COLUMN address`, guarded. The migration refuses
   while `btrim(coalesce(address, '')) <> '' AND address_id IS NULL` matches any row.

**Irreversible** after the drop. The text survives in the address row and its history.

### Step 12 — stop writing `deal_buyer`; freeze it (O6). Code + migration `onboarding_0058`

**Running the buyer migration is the user's step,** on `aner_settlement`, after phase 4
is merged. The order is:

1. `pg_dump`;
2. `--dry-run`, and read the report;
3. confirm name matches with `--confirm-name`;
4. `--apply`;
5. `--validate`;
6. a second `--apply`, which must create nothing.

Then run `backfill_trade_relationships`. Phase 4 rehearses the whole sequence on a
scratch copy of `aner_settlement`.

**Code.**

- `deal_service` stops writing `DealBuyer`. New deals name buyer companies only.
- The legacy buyer form goes from the frontend.
- `sample_data_deals.py` moves to buyer companies.
- The deal API's `buyer` field stays, read-only, for one release.

**Migration `0058`.** Add `trg_deal_buyer_frozen`. It refuses INSERT, and refuses any
UPDATE except NULL → value on the five mapping columns. The command can therefore still
map rows after the freeze.

**Validation.** A direct-SQL test shows that an INSERT and an update of `name` both
fail, and that filling the mapping columns once succeeds. After the user's run,
`count(*) FROM deal_buyer WHERE mapped_company_id IS NULL` = 0.

**Rollback.** Drop the trigger.

### Step 13 — retire the old onboarding system (O1). **Out of scope**

**Decided 14 October:** only CRM files change. The 14 old-system tables keep their
entities, services, workflow, the 9 mounted routes, `app/main.py`'s KYB seed,
`app/bootstrap.py`, `backend/conftest.py`'s legacy test list and the 23 legacy test files,
all unchanged. After step 5 the CRM no longer reads any of them. If the old system is
ever retired, it is a separate programme, with Q1 asked again.

### Step 14 — deal reference unique per seller (O18). Migration `onboarding_0059`

**Decided (Q6, 14 October):** unique per seller.

- Add `UNIQUE (company_id, reference)` to `deal`. The migration first counts duplicates
  (check 8), and refuses with the listing if there are any. Today there are 0.
- `deal_service` turns the unique violation into a 409 with a clear message.
- A direct-SQL test and a route test cover it.

**Rollback:** drop the constraint.

### Step D — follow-up PR: the drops. Migration `onboarding_0060`

This PR is built **after `fix/migration-crm` is deployed**, so no running instance still
reads what it drops. Precondition: a `pg_dump -Fc` of `aner_settlement`.

| Drop | Guard in the migration |
|---|---|
| `qualification_reason_code` | none (re-seeded from the code catalogue on downgrade) |
| `bank_activity_finding` | refuse if it holds rows |
| `trg_verification_result_field_immutability`, then `verification_result.evidence_reference`, `reviewed_by`, `review_status` | refuse while check 7's "legacy review, no chain" or "`evidence_reference` set" is not 0 |
| `exporter_profile.relationship_manager` | none: Q4 discards the text |
| `exporter_gstin.address` | refuse while a branch has text and no `address_id` |

`verification_review_status_enum` stays, because `verification_review` uses it.

**Validation.** `alembic check` is clean, the CRM has **32** tables, and the qualification,
verification, GST and exporter suites pass.

**Rollback.** The downgrade recreates both tables (reason codes re-seeded), re-adds the
columns empty and restores the trigger. The RM text comes back only from the dump.

### Step 15 — documents

Update these in the same PRs as the steps they describe:

- `docs/database.md`:
  - the counts;
  - §6: the buyer table;
  - §7: the CRM no longer reads the old system's tables (the old system itself is
    unchanged);
  - §13: traps;
  - people in contacts.
- `docs/contracts/migration-register.md`: 0044–0053, which it does not cover today,
  plus every new revision.
- `docs/contracts/company-record.md`: people.
- `docs/contracts/deal-and-buyer.md`: the mapping columns.
- `docs/contracts/verification-and-screening.md`: the legacy result columns are gone;
  people as sanctions subjects.

### Step 16 — optional (Design B): retire `deal_buyer` (O15)

**Preconditions.**

- Step 12 is complete in every environment.
- The `buyer` API field has been gone for one release.
- `compliance_inputs.buyer_inputs` has no callers.

**Release N.**

- `decision_evidence` reads the seller timeline from the
  `company_created_from_deal_buyer` history rows (`deal_ids`), instead of joining
  `deal_buyer`.
- `deal_repository` stops falling back to `DealBuyer.name` and `country`.

**Release N+1.** Archive `deal_buyer`, then drop it.

**Result:** 31 tables. **Irreversible**; recover from the archive.

### Step 17 — squash the CRM's migrations into one baseline file (O24). **Deferred to the separation**

**Decision (13 October).** There is no squash now. Steps 1–16 refine the schema through
ordinary migrations on the existing chain. The squash happens **once, when the CRM is
separated** from the platform's other modules. At that point those modules' migration
files are deleted anyway.

#### 17.1 Why not now

Alembic keeps **one chain** for the whole platform. The CRM's 56 revision files are
woven through it at 22 points, as these examples show:

- `auth_0002`–`auth_0010` sit between `onboarding` revisions.
- `customers_0002` descends from `onboarding_0002`.
- Two merge revisions (`0a772fd562e8`, `2807a84d72ba`) join `onboarding` heads with other
  modules' heads.

The two ways to squash now both cost work that the separation would throw away:

| Option, if done now | Work | Thrown away at separation |
|---|---|---|
| Squash the whole chain into one file | Rewrite and verify all 16 schemas, the three read-only roles of the ledger, settlement and audit modules, and their grants | Most of it: the non-CRM schemas, their roles and their grants leave with their modules |
| Squash only the CRM's files | Re-parent 12 non-CRM revisions onto the new CRM baseline (the 9 `auth` revisions, `customers_0002`, the 2 merges), under a module-rule exception, and verify the result | `customers_0002` and the merges are deleted at separation anyway. Only the `auth` re-parenting survives |

The squash does not change any table. Its benefits are one readable file and a faster
fresh install, and those are worth the most when the chain is CRM-only. Until then,
[inventory.md](inventory.md) Appendix C is the readable definition of the schema.

#### 17.2 When it happens

After the separation has removed the other modules' migration files and every remaining
revision has been re-parented into one CRM-only chain, which the separation has to do
regardless. The squash then needs no edits outside what the CRM keeps. Preconditions:

1. The refinement steps that were approved are applied in **every** environment, and
   every environment is at the same head, *H*.
2. One release has passed with no rollback. After the squash, downgrades below the
   baseline no longer exist.
3. In each environment, `pg_dump --schema-only` matches a fresh reference build at *H*,
   apart from the `\restrict` token. Any drift stops the squash for that environment
   until an ordinary migration fixes it.
4. The user tags the pre-squash commit. Git writes stay with the user.

#### 17.3 What the single file will contain

`baseline_0001.py`, `down_revision = None`, covering exactly the schemas the separated
CRM keeps: expected to be `onboarding`, `auth` and `audit`, plus
`public.prevent_mutation()`. It contains these parts, in order:

| # | Part | Notes |
|---|---|---|
| 1 | **Guard** | Refuse if any of those schemas already holds a table. An existing database is *stamped*, never upgraded through the baseline (the 0014 guard pattern) |
| 2 | Extensions | Only those the kept schemas use. Today the CRM uses none: `btree_gist` belongs to `compliance` |
| 3 | Roles | Only roles the kept schemas need. If `audit` keeps its read-only query service, `audit_ro` is created with its password from the environment, as `d4f2a9c7b118` does today |
| 4 | **Schema DDL** | `pg_dump --schema-only --no-owner --no-privileges` of a fresh reference build, embedded as one SQL string, with session lines removed |
| 5 | Privileges | Grants and default privileges for the roles in part 3 |
| 6 | **Seed rows** | `pg_dump --data-only` of every table that is non-empty in a **fresh** build: expected `auth.role`, `auth.role_permission`, `qualification_criterion`, `deal_required_document`, `payment_term`, `sanctions_list`. Fixed ids |
| 7 | `downgrade()` | Raises: there is no earlier revision |

#### 17.4 Generation and verification

1. Build `squash_ref_old` from empty at *H*.
2. Take the schema, ACL and seed dumps from it.
3. Write the baseline file.
4. Build `squash_ref_new` from the baseline alone.
5. Compare the two builds (V21–V24): identical schema, roles, privileges and seed rows;
   `alembic check` clean; all gates green.

#### 17.5 Code and tests in the same PR

- **Delete the CRM's revision files**: those left after the separation.
- **Move three constants out of migration files and into the domain.** Three tests
  import them from migration files:
  - `onboarding_0033._CHANNEL_BY_SOURCE` (`test_company_identity_create_paths.py:64`);
  - `onboarding_0040.IEC_PATTERN` (`test_company_identity_foundation.py:43`);
  - `onboarding_0035._STATE_NAMES` (`test_gst_branch.py:50`).

  The assertions that compared a migration constant with the domain constant lose
  their purpose and go.
- **Review the 20 test files that name a revision.** Delete tests of historical data
  steps:
  - the 0014 reset guard;
  - the 0027, 0029, 0031, 0033, 0035 and 0043 backfills;
  - 0007's schema test.

  Tests of the *resulting rules* (constraints, triggers, defaults) keep running.
- **Remove the `__main__` entry point of `onboarding_0027_clear_expiry`.**
- **Update the documents**: restart `migration-register.md` at the baseline, and
  update `database.md` §10.

#### 17.6 Switching existing environments over

The container runs `alembic upgrade head` on start (`backend/Dockerfile:56`). In each
environment, follow these steps in order:

1. `alembic current` must show *H*.
2. Compare the schema (17.2, point 3).
3. Take a `pg_dump -Fc`.
4. Using the new image, run a one-off `alembic stamp --purge baseline_0001`. It changes
   `alembic_version` only.
5. Start the new release. Its `upgrade head` is a no-op.
6. Check that `alembic current` shows `baseline_0001` and `alembic check` is clean.

If step 4 is forgotten, the new image fails at start-up with "Can't locate revision
*H*" and nothing changes.

An alternative is to give the baseline the id *H* itself, so no stamp is needed. That
works only when every environment is at exactly *H*.

**Rollback:**

- **Before step 4:** nothing has changed.
- **After step 4:** run `alembic stamp --purge H` with the old image, then redeploy it.
- **Once later migrations are on top:** restore the dump from step 3.

#### 17.7 If the separation slips

If the separation moves far out and a single CRM file is wanted sooner, the
"CRM files only" row of §17.1 is the way to do it. It needs:

- a module-rule exception (EX-002) for re-parenting the 12 non-CRM revisions;
- the same verification as above;
- the same environment switch-over as above.

---

## 4. Cross-cutting considerations

| Concern | How it is handled |
|---|---|
| Production records | Every destructive step has a read-only gate (§2), and refuses to run on rows it would lose |
| Historical audit data | No append-only CRM table is altered or truncated. The GST text goes to an address row with history before its drop (step 11). The unmatched RM text is discarded (Q4); only the pre-drop dump keeps it |
| Documents | `crm_document` is untouched |
| Assignment history | RM changes keep their history rows. The backfill adds rows and removes none |
| Workflow history | The background-check, qualification, verification, sanctions and trade chains are untouched |
| Idempotency and retry | Every data step either uses `ON CONFLICT DO NOTHING` (step 5) or is a command that skips work already done (steps 4, 10, 11 and 12) |
| External identifiers | `ubo_record.id` is preserved as the person's id. Sanctions-run references, RXIL `source_ref` and verification `provider_reference` are untouched |
| Constraints and indexes | Added `NOT VALID`, then `VALIDATE`. No CRM index is dropped except those on dropped tables |
| Concurrent writes | DDL steps are short, and run at low traffic. Commands lock each company row (`with_for_update`), as the existing commands do. Drops follow the two-release rule |
| Data not in local fixtures | `aner_settlement` has 0 legacy rows, 4 legacy buyers, 6 GST text addresses and 100 RM texts. It is the only database with data (Q7); §2 runs there before each phase |
| Backward compatibility | Field removals ship one release after their deprecation: this branch stops using them, the follow-up PR drops them. No legacy route changes (old system out of scope) |
| Migration history | Unchanged by this programme: this branch adds `onboarding_0054`–`0059`, the follow-up PR adds `0060`. The squash into one baseline file waits for the separation (step 17). Then the old files stay in git (pre-squash tag), and downgrades below the baseline are impossible by design |

---

## 5. Validation and regression strategy (Phase 7)

Unless a row says otherwise, run each check twice:

- **(a)** on a database built from empty with `alembic upgrade head`;
- **(b)** on a copy of each populated environment, upgraded from its current revision
  (make the copy with `createdb -T`, or `pg_dump | psql`, as `database.md` §12
  describes).

| # | Test | Expected result |
|---|---|---|
| V1 | Fresh build: `alembic upgrade head` on an empty database | Succeeds with one head. `onboarding` has 48 tables at the end of this branch, **46** after the follow-up PR (32 CRM + 14 old system; 45 after step 16). Old-system enum types unchanged |
| V2 | Upgrade build of a copy of each environment | Succeeds. Each step's gate prints 0, or a count that was reported and accepted |
| V3 | Equivalence: `pg_dump --schema-only -n onboarding -n auth` of V1 and V2 | Identical apart from the `\restrict` token |
| V4 | ORM against the database: `alembic check` plus the extended contract test | No operations. Primary-key, CHECK and default sets are equal for each table |
| V5 | Round trip: `downgrade -1` / `upgrade head` for each new revision on the V2 copy | Clean for `0054`–`0059`. The follow-up PR's `0060` documents that its downgrade recreates empty structure |
| V6 | Constraint validity: `SELECT conname FROM pg_constraint WHERE NOT convalidated AND connamespace = 'onboarding'::regnamespace` | Empty, or exactly the rules reported as `NOT VALID`, with their row lists |
| V7 | Row reconciliation: per-table `count(*)` before and after, on the V2 copy | Equal for every retained table, except where a command reports the difference: `exporter_contact` (+ copied UBOs), `company_address` (+ converted GST addresses), `exporter_lifecycle_history` (+ person and address rows) and `deal_buyer` (mapping columns filled, row count unchanged) |
| V8 | Orphans: the queries in check 5, plus the people-reference query in step 5 | All 0 |
| V9 | Duplicate business identifiers: PAN, normalised registration number per country, GSTIN per company | 0 duplicates. A GSTIN held by two companies is still allowed (a warning only) |
| V10 | Company identity and several GSTINs: the existing company-record and GST suites, plus O8's SQL tests | All GSTINs kept. Deactivation works and delete is refused. An `identity_type` mismatch is refused by SQL |
| V11 | Lead → prospect → customer: the journey and qualification suites, plus the reason-catalogue test | The pass count is unchanged. Every cited code resolves to a label |
| V12 | RM assignment and access: the assignment, worklist and masking tests; the `relationship_manager=me\|none\|inactive` filters | Pass. No response carries `relationship_manager` text after step 10 |
| V13 | People and masking: new tests | A director or UBO can be added, masked for viewers without the reveal permission, screened through the API, and never deleted. A primary contact must be a contact |
| V14 | Compliance and documents: the background-check, maker-checker, verification, screening, sanctions and document suites | Pass. Hand-entered SANCTIONS results are still accepted (Q9); DIRECTOR and UBO runs reference a person |
| V15 | Buyer migration (step 4 + step 12): its 32 safety tests, re-pointed | Every guarantee holds. A second `--apply` creates nothing |
| V16 | Audit preservation: count each append-only table before and after every step | Never lower. Higher only by the rows a step says it writes |
| V17 | API: `test_route_authorization_coverage.py`, `test_openapi_artifact_is_current.py`, and frontend `tsc`/`vitest` against the regenerated schema | Pass. Routes: −1 bank activity, + people routes. Old-system routes unchanged |
| V18 | Gates: `pytest --crm`, `ruff`, `lint-imports --config importlinter.ini`, and frontend `tsc -b`, `eslint`, `vitest`, `vite build` | At their recorded baselines. Test counts change only as intended |
| V19 | Recovery: restore the pre-follow-up-PR dump into a scratch database | Row counts equal the dump's; the RM text is present there |
| V20 | Performance: `EXPLAIN (ANALYZE, BUFFERS)`, before and after, for the exporter list (all filters), a company's history, the contacts and people lists, the background-check worklist, the re-screen worklist and the deal list | No plan regression. Contacts queries use `ix_exporter_contact_customer_id`; add a partial index on people roles only if a plan shows it is needed |
| V21 | *(at separation)* Squash, schema: `pg_dump --schema-only` (the schemas the CRM keeps, and `public`) of `squash_ref_old` and `squash_ref_new` | Identical, apart from the `\restrict` token |
| V22 | *(at separation)* Squash, roles and privileges: `pg_roles` for any read-only role the CRM keeps; `\dp` and `pg_default_acl` in both builds | The same roles, grants and default privileges |
| V23 | *(at separation)* Squash, seed data: `pg_dump --data-only` of the seeded tables in both builds | Identical rows (fixed ids in the baseline) |
| V24 | *(at separation)* Squash, application: `alembic heads` (1), `alembic check`, the extended ORM contract test, `test_migration_discovery.py`, `pytest --crm`, then the whole suite on a database built by the baseline | One head, no drift, every gate at its baseline. Removed tests are exactly the historical data-step tests listed in step 17.5 |
| V25 | *(at separation)* Squash, cut-over: on a copy of each environment, the step 17.6 sequence, then start the new image | `alembic current` = `baseline_0001`; the container starts; `upgrade head` does nothing. On a copy left stamped *H*, the new image fails at start-up with no change, which proves the guard and the stamp order |

**Data has been validated on the development database only** (§2.1). No representative
production data was available to this audit. V2, V3, V7 and V16 must run on a copy of
each environment that holds data, before the matching step ships.

---

## 6. Approval gate

All groups were answered on 14 October 2026. Each phase is built, then reviewed and
committed by the user before the next one starts.

| Phase | Steps | Decisions |
|---|---|---|
| 1 | 1–3 | Built |
| 2 | 4, 5 | Q2: name and role required; `view_full_tax_id` reveals; no auth migration. Q7: map empty |
| 3 | 6–8 | Q3: no bank feed, the placeholder goes |
| 4 | 10–12, 14, 15 | Q4: discard unmatched RM text. Q5: auto-convert as `CORRESPONDENCE`. Q6: unique per seller. Q7: the user runs the commands on `aner_settlement` |
| Follow-up PR | D | After this branch is deployed |
| — | 9 | Not done (Q9: keep both paths) |
| — | 13a, 13b | Out of scope: not CRM (Q1) |
| — | 16 | Optional, later |
| — | 17 | At the separation (Q10) |

Design C's merges are not proposed (Q8).
