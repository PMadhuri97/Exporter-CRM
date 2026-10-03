# Contract — the migration register

**Owner:** Developer 1 · **Config:** `backend/alembic.ini` · **Head today:** `onboarding_0037_trade_history`

The prototype's migrations, from four developers and one platform change, in one
chain. This is the running order and the rules. Dev 1 keeps it current.

---

## 1. The register

Numbers are labels, not order (§2): the **Parent** column is the order. Every row is
merged.

| No. | Owner | Change | Parent |
|---|---|---|---|
| 0013 | Dev 1 | Generalise the history table: `dimension`, `deal_id`, `reason`, two indexes | `onboarding_0012_risk_critical` |
| 0014 | Dev 2 | Fresh company record: name, country, identifiers, marker, PAN unique, several GSTINs; real links from contacts, activities, screening items **and history**. Refuses to empty CRM tables that hold rows unless `E9_ALLOW_CRM_RESET=1` | `onboarding_0013_shared_history` |
| 0017 | Dev 2 | Qualification criteria, results and outcomes; the `journey` (3 values) and `qualification` columns | `onboarding_0014_company_record` |
| 0020 | Dev 2 | Retire the ten-status `lifecycle_status` (L2-04) | `onboarding_0017_qualification` |
| 0016 | Dev 3A | The conversation gauge and its check-back date; follow-up completion (locked) | `onboarding_0020_retire_lifecycle` |
| 0018 | Dev 3B | Deal and buyer | `onboarding_0016_engagement` |
| 0019 | Dev 3B | Documents | `onboarding_0018_deal_buyer` |
| 0015 | Dev 4A | The background-check gauge, locked superseding decisions, evidence snapshots, the CRM risk type | `onboarding_0019_documents` |
| `auth_0003` | Platform (user management) | User administration | `onboarding_0015_bg_check` |
| `auth_0004` | Platform (user management) | Roles and permissions as data (RBAC) | `auth_0003_user_admin` |
| 0021 | Dev 4B | Superseding verification reviews, the outcome freeze, evidence and subject snapshots | `auth_0004_rbac` |
| 0022 | Release audit | Database guards: no document or verification result is deleted, a document's identity is fixed once set, and a `HANDED_OVER` or `WITHDRAWN` deal no longer changes | `onboarding_0021_verif_review` |
| 0023 | Dev 1 (F1) | `onboarding_0023_dev1_foundation`: `verification_result.subject_company_id` (FK, set once then frozen by `trg_verification_result_input_immutability`); `exporter_profile.background_check_expires_at` (indexed). Downgrade lossy since P4-5/P3-3a write both (drops every result's subject company and every current expiry; both re-derivable) — verified 1 Oct 2026 by a downgrade to 0022 and upgrade on a copy of the test database | `onboarding_0022_integrity` |
| 0024 | Dev 1 (P2-1b) | `onboarding_0024_dev1_evidence`: `screening_review_item.evidence_refs` (`jsonb NOT NULL DEFAULT '[]'`, DDL — no row updated). Lossy downgrade (drops the references) | `onboarding_0023_dev1_foundation` |
| 0025 | Dev 1 (P2-3a, P2-4a) | `onboarding_0025_dev1_check_cycle`: append-only `check_cycle`; `cycle_id` on results, screening answers and decisions (composite FK on the last two), frozen on results; `background_check_decision.rules_version`; **inserts** one cycle 1 per company with inputs — no existing row updated (`NULL` cycle = cycle 1, `NULL` rules = v1). Lossy downgrade | `onboarding_0024_dev1_evidence` |
| 0026 | Dev 1 (P3-1a) | `onboarding_0026_dev1_approval`: maker-checker — append-only `background_check_proposal` and `background_check_proposal_resolution` (one per proposal; `(outcome = 'WITHDRAWN') = (created_by = proposed_by)`, the proposer copy pinned by a composite FK); `background_check_decision.proposal_id`, `approved_by`, `approved_at` with `CHECK (approved_by IS NULL OR approved_by <> decided_by)` and a composite FK to the proposal (same company, proposer and move). Schema only, no data. Lossy downgrade (proposals and approvals) | `onboarding_0025_dev1_check_cycle` |
| 0027 | Dev 1 (P3-3a) | `onboarding_0027_dev1_expiry`: `background_check_decision.expires_at` (`CHECK`: CLEAR only, after `decided_at`); **data: backfills `exporter_profile.background_check_expires_at`** for every company now `CLEAR` from its last CLEAR decision (stored expiry, else `decided_at` + 8,760 h — BQ-5), only where NULL, idempotent; no append-only row touched. Dry run: `python -m app.modules.onboarding.migrations.onboarding_0027_dev1_expiry --dry-run`; after: `--validate` must print 0. `pg_dump` first. Lossy downgrade (drops the stored expiries; sets the profile column back to NULL) | `onboarding_0026_dev1_approval` |
| 0028 | Dev 2 (F2) | `onboarding_0028_deal_foundation`: the deal's new columns — `buyer_company_id` (FK to `exporter_profile.customer_id`, `RESTRICT`, with `ck_deal_buyer_is_not_the_seller`), `handover_snapshot` (`jsonb`), `seller_gst_registration_id` (FK to `exporter_gstin.id`, `RESTRICT`). Schema only, no data. Downgrade drops the three columns | `onboarding_0027_dev1_expiry` |
| 0029 | Dev 2 (P2-7) | `onboarding_0029_deal_snapshot`: **data: backfills `deal.handover_snapshot`** for every `HANDED_OVER` deal without one, from its `deal_buyer` row and its handover history row (`snapshot_source = 'backfilled_from_deal_buyer'`; `buyer` / `document_ids` are `null` where that record no longer exists), **then** replaces `prevent_terminal_deal_change()` so the column is set once and never changed. No append-only row touched. Run the module's `_VALIDATION` queries before and after; the first must print 0 afterwards. `pg_dump` first. Downgrade restores 0022's function and clears only the backfilled snapshots | `onboarding_0028_deal_foundation` |
| 0030 | Dev 2 (P2-5a) | `onboarding_0030_deal_req_docs`: `deal_required_document` (versioned, append-only, reuses 0019's `crm_document_category_enum`), **seeded with one `PRE_SHIPMENT` requirement. Changes behaviour:** from this revision a deal with no `AVAILABLE` pre-shipment document cannot be handed over, so open deals on a live database need one uploaded first; deals already handed over are not re-judged. Lossy downgrade (drops the record of what was required when) | `onboarding_0029_deal_snapshot` |
| 0031 | Dev 3 (P1-1, P1-2) | `onboarding_0031_domestic_first`: **data:** the next version of `export_history` and `export_licence`, copied from the current one with `required = false` (none where the current version is already not required; `created_by = migration:onboarding_0031_domestic_first`), and `no_export_history`, `no_export_licence`, `geography_not_supported` deactivated. **Changes behaviour:** export results stop counting towards the suggestion, so an undecided lead may now read QUALIFIED; decided companies are not re-judged. `pg_dump` first. Downgrade deletes only its own rows and is refused once a result has been recorded against them (restore the dump instead) | `onboarding_0030_deal_req_docs` |
| `auth_0005` | Dev 3 (P1-5) | `auth_0005_rm_role_name`: **data:** the built-in OPERATIONS row in `auth.role` is named "RM (Relationship Manager)" and loses the "unless you own the record" description (IQ-13, decision 12) — only where an administrator has not already changed them. Slug and enum unchanged. Downgrade restores both | `onboarding_0031_domestic_first` |
| 0032 | Dev 3 | Company identity and pipeline status (F3): `identity_type`, `registration_number`, `pipeline_status`, `created_via`, `created_via_deal_id`; `ExporterSource.DEAL_BUYER` (IQ-6); the not-in-pipeline check and the normalised registration-number unique index | `auth_0005_rm_role_name` |

| 0033 | Dev 3 (3.8) | `onboarding_0033_created_via`: **data: backfills `exporter_profile.created_via`** from each company's earliest creation history row (`journey`, or `pipeline` for a buyer-only company), with the same source → channel mapping `domain/company_identity.py` applies to new companies — a test asserts the two agree. Also normalises any `created_via` already written to upper case (F3 shipped `'deal_buyer'`). Unmapped or missing sources stay `NULL` and are **reported as a count** rather than guessed as `MANUAL`. No append-only row touched. `pg_dump` first. Downgrade sets the column back to `NULL` for every company — lossless in that re-running reproduces it from the history rows, but it discards values written by a create path since | `onboarding_0032_company_identity` |
| 0034 | Dev 2 (2.4) | `onboarding_0034_deal_buyer_co`: `deal.buyer_company_id` becomes **set once** (`trg_deal_buyer_company_set_once`, via `prevent_field_mutation_when_set` — `NULL` → a value is allowed once, so the P4-6 migration can still fill it) and is added to `prevent_terminal_deal_change()`, so a closed deal's buyer no longer changes. Schema only, no data. Downgrade drops the trigger and restores 0022's function body | `onboarding_0033_created_via` |

| 0035 | Dev 3 (3.12) | `onboarding_0035_gst_branch`: `exporter_gstin` becomes a **branch record** (P6-1, extended in place rather than copied to a new table) — `state_code`, `state_name`, `status`, `address`, `flag_status`, `flag_reason`, `active`, `deactivated_at/by`; `uq_exporter_gstin_id_customer_id` (exists to be referenced: it is what lets 0036's composite FK tie a deal's branch to its seller); checks for a flag's reason and for deactivation; **`trg_exporter_gstin_no_delete` refuses DELETE** — dropping a registration is now a deactivation, and `cascade="all, delete-orphan"` came off `gstin_rows` in the same task. **Data:** `state_code` from each GSTIN's first two characters and `state_name` from the code, with the same mapping `domain/gst_states.py` applies going forward (a test asserts they agree); **unknown codes keep `state_name NULL` and are reported as a count**. `pg_dump` first. Lossy downgrade (every address, status, flag and deactivation) and it re-enables deleting rows a deal may point at | `onboarding_0034_deal_buyer_co` |
| 0036 | Dev 2 (2.8) | `onboarding_0036_deal_branch`: `deal.seller_gst_registration_id`'s FK becomes **composite** — `(seller_gst_registration_id, company_id)` → `(exporter_gstin.id, customer_id)` — so the database refuses a deal invoiced through another company's branch; and the column joins `prevent_terminal_deal_change()`. Settable and **changeable** before handover (IQ-20), unlike `buyer_company_id`'s set-once rule. Restates 0022's columns, 0029's snapshot block and 0034's `buyer_company_id`, because `CREATE OR REPLACE FUNCTION` keeps nothing. Schema only, no data. Downgrade restores 0028's single-column FK and 0034's function body | `onboarding_0035_gst_branch` |
| 0037 | Dev 3 (3.18, 3.19) | `onboarding_0037_trade_history`: `trade_relationship` (unique ordered pair, seller ≠ buyer — **no column on `deal`**, allocation §1 adjustment 1), `trade_invoice` (identity frozen by `trg_trade_invoice_identity_immutability`; `deal_id` nullable for past trade; currency stored and never converted, IQ-4) and `trade_invoice_outcome` (append-only superseding chain via `public.prevent_mutation()`, one head per invoice and one superseder per row, so the chain is a line not a tree). Every table carries `created_by`/`source`/`source_ref` (BQ-7). Schema only; the relationship backfill is task 3.23 and runs separately. Lossy downgrade (everything recorded about past trade) | `onboarding_0036_deal_branch` |

**Next free onboarding number: 0038.** Revision ids follow `onboarding_00NN_<lane>_<topic>`,
32 characters at most (`docs/developer-allocation.md` §2.2, and §2 below).

`auth_0003` and `auth_0004` belong to the platform's user-management work, not to the
CRM (`auth_0005` only renames a row they seeded); they sit in this chain because
there is only one chain (§2), so a CRM migration written after them parents on them
like on any other.

### 0014 also adds the history foreign key

`exporter_lifecycle_history.customer_id` has no foreign key, and 0013
deliberately does not add one (decision U3). 0014 recreates the CRM's own tables
and already owns the links for contacts, activities and screening items; the
history link goes in with them.

Putting it in 0013 instead would have forced 0014 to drop the constraint before
recreating `exporter_profile` and re-add it afterwards, for no gain — both land
in the same week. There are 1,498 history rows and zero orphans today, so the
constraint applies cleanly whenever 0014 runs.

---

## 2. Rules

**Name a migration `onboarding_00NN_<lane>_<topic>`.** `onboarding` is the module
whose directory holds it, `NN` the next free number from §1, `<lane>` the area of work
(`dev1`, `deal`, `domestic`, `verif`), `<topic>` what it does. The lane matters when
several people are migrating at once: it is what tells a reviewer whose change this is
without opening the file. Other modules use their own prefix — `auth_0004_rbac`.

Keep `<lane>_<topic>` short, because of the next rule. The limit is easy to breach:
`onboarding_0023_domestic_criteria` — the name `plan.md` P1-1 prescribed — is **33
characters** and failed on the database with `value too long for type character
varying(32)` after the migration body had already run. It shipped as
`onboarding_0031_domestic_first` (30).

**One chain, one head.** `alembic heads` must print exactly one revision. If it
prints two, someone branched: fix it by re-parenting, not by adding a merge
revision. The repository already carries three historical merge points from
before this register; do not add a fourth.

**Revision IDs are 32 characters or fewer.** Alembic's `version_num` column is
`varchar(32)`. A longer id fails at upgrade time, on the database, after the DDL
has started. `onboarding_0013_shared_history` is 30. The name first chosen for it,
`onboarding_0013_history_dimension`, is 33 and would have failed on the
database partway through the DDL — which is why the rule is written down.

**Never `ALTER TYPE ... ADD VALUE` inside an autocommit block.** It has broken
this repository before: the enum value commits, the rest of the migration does
not, and the database is left in a state no revision describes. `alembic_version`
still says the old revision, so a re-run tries to add a value that already
exists. Add the value in an ordinary transactional migration, as
`onboarding_0012_risk_critical` does.

**If the merge order changes, re-parent.** The later migration updates its own
`down_revision` (a one-line change) and whoever does it tells Dev 1 to update the
table above. Numbers are labels, not order; `down_revision` is the order. **If the
number itself has meanwhile been taken by a migration that merged first, take the
next free one as well** — two files carrying one number make §1 ambiguous. That is
what happened on 2 October 2026: Dev 2's 0025–0027 became 0028–0030 and Dev 3's
0023 became 0031.

The same rule, from the other direction: **before you merge, re-point
`down_revision` to whatever head is there now and re-run `alembic heads`.** A branch
that sat for a week was written against a head that has since moved. Reserve numbers
from §1 in the order the work is expected to merge, and accept that the expectation
will sometimes be wrong.

**Take a `pg_dump` before any migration that changes data**, not just schema. A data
migration that inserts rows into an append-only table cannot be undone by a plain
`DELETE` — the trigger refuses it — so its downgrade has to lift the trigger
deliberately, and a dump is what makes that safe to attempt. Each data migration says
in its docstring how it rolls back and what it changes about existing rows.

**Grow a column in three steps when a table is in use: expand, backfill, contract.**
Add the new column nullable, fill it, and only then make it `NOT NULL` or drop the old
one — in separate migrations. One migration that adds a `NOT NULL` column to a
populated table fails on the row it cannot fill.

**Register a new module migration directory in `alembic.ini`.** `version_locations`
is explicit, must stay on one line (Alembic splits it on commas and spaces, so a
multi-line list silently resolves to zero locations), and is checked by
`tests/contract/test_migration_discovery.py`, which derives the expected list
from the filesystem. A directory that exists but is unlisted is silently ignored
by `alembic upgrade head` — schema drift behind a green build.

**Every new constraint gets a direct-SQL violation test.** Established
throughout this project: the test bypasses the ORM with `psycopg2` and attempts
the violation, so it proves the *database* refuses it and not just the
application. This is how the append-only triggers are covered.

**0014 may drop and recreate the CRM's own tables** — the prototype starts from
sample data, so there is no data to migrate (decision 1). It must not touch the
legacy onboarding tables (`onboarding_request`, `onboarding_event`,
`onboarding_case`, `case_state_transition`) or any other module's tables.

**Downgrades are written, and lossy ones say so.** `onboarding_0011`'s downgrade
deletes superseded checklist decisions to restore a unique constraint and says
"Downgrade only if you mean it". Follow that: write the downgrade, and if it
destroys data, say which.

---

## 3. What must not be removed

The generalised history table is an **addition**. These stay:

- `public.prevent_mutation()` and every trigger that executes it (21 statements
  plus a loop in `customers_0002`).
- `onboarding.prevent_field_mutation_when_set()` and its column-level triggers.
- `AppendOnlyModel` / `AppendOnlyRepository`.
- `onboarding_event` — the legacy request path writes it, and its
  `onboarding_request_id` is `NOT NULL` with an FK, which is why lifecycle
  history needed its own table in the first place.
- `screening_review_item` — the checklist's own superseding log. Dev 4 needs it.
- `case_state_transition` and the 12-state legacy case machine — out of scope
  for the prototype (assumption A6), not deleted.
- Existing `exporter_lifecycle_history` rows. 0013 backfills them; it does not
  truncate them.

---

## 4. Before and after every migration

```bash
cd backend
alembic heads                 # exactly one
alembic upgrade head
alembic downgrade -1          # and back
alembic upgrade head          # the round trip must be clean
python -m pytest -q --no-cov -p no:cacheprovider
```

Compare the suite against the current baseline in `docs/development.md` — the
known failures are payments/FX/compliance-screening tests hitting routes this
checkout does not mount. Any other failure is new and blocks the merge.

`backend/tests/contract/test_orm_matches_the_onboarding_schema.py` also fails when a
migration adds an index or constraint in the `onboarding` schema without the model
declaring it (or the other way round), so `alembic revision --autogenerate` never
proposes dropping one.

---

## 5. History before this register

71 revisions existed before 0013, with one head (`onboarding_0012_risk_critical`).
Two duplicate numbers exist in other modules — `compliance_0002` and
`rails_0003` each appear twice. They are historical, they resolve correctly, and
they are **left alone**.
