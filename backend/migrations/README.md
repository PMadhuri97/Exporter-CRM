# migrations

Runner, not a store. `env.py` discovers and applies `app/modules/*/migrations/`.
`versions/` holds platform-level / cross-domain migrations only (ARCHITECTURE.md §4).

---

# Checklist: before you open a PR with a migration in it

Work through this every time. Items 1 and 2 are not hypothetical — both have
already cost this repo a broken database, and the postmortem for each is at
`docs/exporter-crm-frontend-tickets.md:350-362`.

## 1. Is the revision id 32 characters or fewer?

```
python -c "print(len('your_revision_id_here'))"
```

`alembic_version.version_num` is `varchar(32)`. A longer id does not fail at
review, at import, or at `alembic heads` — it fails at the moment Alembic writes
the bookkeeping row, *after* your DDL has already run.

What that cost last time: `onboarding_0009_relationship_manager_user` was 41
characters. `alembic upgrade head` ran the schema change, then blew up stamping
the version. Renamed to `onboarding_0009_rm_user_id` (26).

Descriptive is good. Descriptive and over 32 is a broken deploy. Shorten the id,
put the long explanation in the module docstring.

## 2. Does this migration contain `ALTER TYPE ... ADD VALUE`?

If yes, understand what you are signing up for before you write it.

`migrations/env.py` runs an entire `alembic upgrade head` invocation inside one
transaction, so a failure anywhere rolls back every migration in that run. But
`op.get_context().autocommit_block()` — which `ALTER TYPE ... ADD VALUE` needs,
because Postgres refuses to add an enum value inside a transaction that later
uses it — is **not transactional**. It commits immediately and independently.

So when a *later* migration in the same run fails, you get the worst outcome
available: `alembic_version` rolls back to before your migration, while the enum
value is really, permanently there. The recorded schema and the actual schema now
disagree, and nothing reports it.

That is exactly what happened: `auth_0002_developer_role` added `DEVELOPER` to
`user_role_enum` inside an `autocommit_block()`; `onboarding_0009` then failed on
item 1 above; the rollback reverted the version row but not the enum value.

Rules for an `ALTER TYPE ... ADD VALUE` migration:

- **Always `ADD VALUE IF NOT EXISTS`.** This is what makes the re-run after a
  rollback safe, and it is the only thing that made the incident recoverable.
  Copy `app/modules/cases/migrations/cases_0002_intake_type.py` verbatim.
- **Put the `ALTER TYPE` in its own migration.** Nothing else in the `upgrade()`.
  A partially-applied migration whose other half rolled back is far harder to
  reason about than one that only ever does the one non-transactional thing.
- **Do not reference the new value in the same migration.** Postgres will reject
  it. That is what forces the `autocommit_block()` in the first place.
- **Say in `downgrade()` that you cannot remove it.** Postgres has no supported
  way to drop an enum value without recreating the type. A `pass` with a comment
  explaining why is the honest downgrade; a silent `pass` is not.
- **After any failed run involving one, verify by hand** before re-running:

  ```
  docker exec aner-postgres psql -U aner -d aner_settlement \
    -c "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid WHERE t.typname = 'your_enum';"
  docker exec aner-postgres psql -U aner -d aner_settlement \
    -c "SELECT version_num FROM alembic_version;"
  ```

  If the value is present and the version row does not reflect the migration that
  added it, you are in the split state described above. `ADD VALUE IF NOT EXISTS`
  means re-running `alembic upgrade head` is the fix.

## 3. Is the migration's directory listed in `alembic.ini`?

`version_locations` is explicit, not globbed. A `migrations/` directory that
exists but is unlisted is silently skipped by `alembic upgrade head` — schema
drift behind a green build. `tests/contract/test_migration_discovery.py` derives
the expected list from the filesystem and fails the build if you forget, so let
it; just do not override it.

Keep `version_locations` on **one line**. Alembic splits it on `", *|(?: +)"` —
commas and spaces, never newlines — so an indented multi-line list resolves to
zero locations and applies nothing.

## 4. Does the revision number collide?

Two migrations landing in the same week against the same module is normal here.
Check what already exists in your module's `migrations/` directory *and* what is
in flight on other branches before claiming a number. Two files claiming
`onboarding_0011` is a merge conflict at best and a lost migration at worst.

## 5. Have you run it, both ways, against a real database?

Not `alembic upgrade head` alone — the round trip:

```
docker compose up -d postgres        # repo root
cd backend
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

Both incidents above were invisible to typecheck, to unit tests, and to review.
Each one was caught the first time somebody actually ran the migration. A
`downgrade()` that has never been executed is not a downgrade, it is a guess.

## 6. Does the table need a mutation guard?

If the table records decisions, transitions, or anything an auditor would ask
about later, it is probably append-only. Twenty tables in this schema already
carry the same trigger — copy one rather than inventing a variant:

```sql
CREATE TRIGGER trg_<table>_append_only
BEFORE UPDATE OR DELETE ON <schema>.<table>
FOR EACH STATEMENT
EXECUTE FUNCTION public.prevent_mutation();
```

Precedents: `onboarding.onboarding_event`
(`onboarding_0002_orchestration_schema.py:313-319`) and
`onboarding.exporter_activity` (`onboarding_0005_exporter_crm.py:215-220`). For
freezing a single column instead of the whole row, there is
`{schema}.prevent_field_mutation_when_set('<column>')` — same file, just above.

And drop the trigger in `downgrade()`, before dropping the table.
