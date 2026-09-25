# Contract — the migration register

**Owner:** Developer 1 · **Config:** `backend/alembic.ini` · **Head today:** `onboarding_0013_shared_history`

Seven migrations land in the prototype, from four developers, into one chain.
This is the running order and the rules. Dev 1 keeps it current.

---

## 1. The register

| No. | Owner | Change | Parent | State |
|---|---|---|---|---|
| **0013** | Dev 1 | Generalise the history table: `dimension`, `deal_id`, `reason`, two indexes | `onboarding_0012_risk_critical` | **merged** |
| 0014 | Dev 2 | Fresh company record: name, country, identifiers, journey (3 values), marker, current gauge fields, PAN unique; real links from contacts, activities, screening items **and history** | `0013` | not started |
| 0015 | Dev 4 | Background-check decisions (locked, superseding); superseding reviews on verification results; risk scale | `0014` | not started |
| 0016 | Dev 3 | Follow-up completion (locked) | `0014` | not started |
| 0017 | Dev 2 | Qualification criteria and results | `0014` | not started |
| 0018 | Dev 3 | Deal and buyer | `0014` | not started |
| 0019 | Dev 3 | Documents | `0018` | not started |

**Next free onboarding number: 0014.**

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

Baseline as of 0013: **22 failed, 2965 passed, 6 skipped, 5 errors**. The 27 red
items are all payments/FX/compliance-screening tests hitting routes this
checkout does not mount. Any other failure is new and blocks the merge.

---

## 5. History before this register

71 revisions existed before 0013, with one head (`onboarding_0012_risk_critical`).
Two duplicate numbers exist in other modules — `compliance_0002` and
`rails_0003` each appear twice. They are historical, they resolve correctly, and
they are **left alone**.
