# Contract — the migration register

**Owner:** Developer 1 · **Config:** `backend/alembic.ini` · **Head today:** `onboarding_0023_domestic_first`

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
| 0023 | Dev 3 | Domestic-first qualification: `export_history` and `export_licence` get a version 2 that is not required, and the three export-only rejection reasons are deactivated | `onboarding_0022_integrity` |

**Next free onboarding number: 0024.**

The two `auth_*` revisions belong to the platform's user-management work, not to the
CRM; they sit in this chain because there is only one chain (§2), so a CRM migration
written after them parents on them like on any other.

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
(`company`, `deal`, `domestic`, `verif`), `<topic>` what it does. The lane matters when
several people are migrating at once: it is what tells a reviewer whose change this is
without opening the file. Other modules use their own prefix — `auth_0004_rbac`.

Keep `<lane>_<topic>` short, because of the next rule. The limit is easy to breach:
`onboarding_0023_domestic_criteria` — the name `plan.md` P1-1 prescribed — is **33
characters** and failed on the database with `value too long for type character
varying(32)` after the migration body had already run. It shipped as
`onboarding_0023_domestic_first` (30).

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

**If the merge order changes, re-parent — do not renumber.** The later migration
updates its own `down_revision` (a one-line change) and whoever does it tells
Dev 1 to update the table above. Numbers are labels, not order; `down_revision`
is the order.

The same rule, from the other direction: **before you merge, re-point
`down_revision` to whatever head is there now and re-run `alembic heads`.** A branch
that sat for a week was written against a head that has since moved. Reserve numbers
from §1 in the order the work is expected to merge, and accept that the expectation
will sometimes be wrong — which costs one line, as long as nobody renumbers instead.

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
