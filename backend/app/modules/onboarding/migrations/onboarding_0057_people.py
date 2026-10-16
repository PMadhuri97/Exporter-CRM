"""Directors and beneficial owners are people on ``exporter_contact``.

Revision ID: onboarding_0057_people
Revises: onboarding_0056_buyer_map_cols

Why
---
The CRM screens a company's directors and beneficial owners, and suggests group
companies from the people they share, but it had nowhere of its own to record them. It
read beneficial owners from the old onboarding system's ``ubo_record`` (through
``onboarding_request``), which the CRM never writes, and took directors as free text on
each screening run. A screening run's ``subject_reference`` pointed at a ``ubo_record``
by convention only.

A person is now one ``exporter_contact`` row with roles: ``is_contact`` (someone we talk
to; every existing row), ``is_director``, ``is_ubo``. A director who is also the main
contact is one row, not two. The person fields are optional; only the name and a role
are required:

* ``date_of_birth``, ``nationality``, ``residence_country``;
* ``din`` (Director Identification Number) — a director's only;
* ``ownership_pct`` and ``control_type`` — a beneficial owner's only;
* ``identification_type`` with the number **encrypted**
  (``identification_encrypted``, the bank-account field cipher) and its last four
  characters for the masked view (``identification_last4``);
* ``source`` / ``source_ref`` — where the row came from when not typed in.

The rules:

* every row has a role (``ck_exporter_contact_has_role``);
* the primary contact is a contact (``ck_exporter_contact_primary_is_contact``);
* the director-only and owner-only fields belong to that role, and are shaped;
* the identification number, type and last four are set together;
* a person is never deleted (``trg_exporter_contact_no_delete``, through the new
  ``onboarding.prevent_delete()``): leaving is a status, and screening runs point at
  the row;
* a screening run's person is a person of the **same company**
  (``fk_sanctions_run_subject_person``, on ``(subject_reference, company_id)``, through
  the new ``uq_exporter_contact_id_customer``). A free-text director run has no
  ``subject_reference`` and is unaffected.

Data
----
Beneficial owners already in ``ubo_record``, whose request names a company, are copied
with **the same ids**, so any screening run that references one stays valid. The old
system's tables are only read: nothing in them changes. A ``ubo_record``'s date of birth
and identification number may be encrypted with the old system's cipher, which SQL
cannot read, so the revision copies only rows that have neither; it refuses, with the
count, if any other linked row exists (that row then needs a command). Each copied
person gets one ``contact`` history row, ``person_added``.

The new person FK is added ``NOT VALID`` and validated in the same transaction when no
run violates it; otherwise it is left ``NOT VALID`` (it still applies to every new and
changed run) and the count is printed, as 0054 does.

Rollback
--------
The downgrade refuses while any director or beneficial owner exists that was not copied
from ``ubo_record``: those people exist nowhere else. Restore the dump taken before the
upgrade instead. Otherwise it removes the copied rows (``ubo_record`` still holds them;
their history rows stay, the log being append-only), then the FK, trigger, constraints
and columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "onboarding_0057_people"
down_revision: str | None = "onboarding_0056_buyer_map_cols"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
LEGACY_SOURCE = "LEGACY_UBO_RECORD"

CONTROL_TYPES = ("DIRECT_OWNERSHIP", "INDIRECT_OWNERSHIP", "VOTING_RIGHTS", "OTHER_CONTROL")
IDENTIFICATION_TYPES = ("PASSPORT", "NATIONAL_ID", "DRIVING_LICENCE")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


#: (name, expression) — mirrored on ``ExporterContact``.
CHECKS: tuple[tuple[str, str], ...] = (
    ("ck_exporter_contact_has_role", "is_contact OR is_director OR is_ubo"),
    ("ck_exporter_contact_primary_is_contact", "NOT is_primary_contact OR is_contact"),
    (
        "ck_exporter_contact_din",
        "din IS NULL OR (is_director AND din ~ '^[0-9]{8}$')",
    ),
    (
        "ck_exporter_contact_ownership",
        "ownership_pct IS NULL OR (is_ubo AND ownership_pct >= 0 AND ownership_pct <= 100)",
    ),
    (
        "ck_exporter_contact_control_type",
        f"control_type IS NULL OR (is_ubo AND {_in('control_type', CONTROL_TYPES)})",
    ),
    ("ck_exporter_contact_nationality", "nationality IS NULL OR nationality ~ '^[A-Z]{2}$'"),
    (
        "ck_exporter_contact_residence",
        "residence_country IS NULL OR residence_country ~ '^[A-Z]{2}$'",
    ),
    (
        "ck_exporter_contact_identification",
        "(identification_encrypted IS NULL) = (identification_type IS NULL) "
        "AND (identification_encrypted IS NULL) = (identification_last4 IS NULL) "
        f"AND (identification_type IS NULL OR {_in('identification_type', IDENTIFICATION_TYPES)})",
    ),
)

#: (name, type, nullable, server default)
COLUMNS: tuple[tuple[str, sa.types.TypeEngine, bool, str | None], ...] = (
    ("is_contact", sa.Boolean(), False, "true"),
    ("is_director", sa.Boolean(), False, "false"),
    ("is_ubo", sa.Boolean(), False, "false"),
    ("date_of_birth", sa.Date(), True, None),
    ("nationality", sa.String(2), True, None),
    ("residence_country", sa.String(2), True, None),
    ("din", sa.String(8), True, None),
    ("ownership_pct", sa.Numeric(5, 2), True, None),
    ("control_type", sa.String(24), True, None),
    ("identification_type", sa.String(24), True, None),
    ("identification_encrypted", sa.String(512), True, None),
    ("identification_last4", sa.String(4), True, None),
    ("source", sa.String(64), True, None),
    ("source_ref", sa.String(255), True, None),
)

#: Legacy beneficial owners whose request names an existing company.
_LINKED_UBOS = f"""
    FROM {SCHEMA}.ubo_record u
    JOIN {SCHEMA}.onboarding_request r ON r.id = u.onboarding_request_id
    JOIN {SCHEMA}.exporter_profile p ON p.customer_id = r.customer_id
"""


def upgrade() -> None:
    bind = op.get_bind()

    unreadable = bind.execute(
        sa.text(
            f"SELECT count(*) {_LINKED_UBOS} "
            "WHERE u.date_of_birth IS NOT NULL OR u.identification_number IS NOT NULL"
        )
    ).scalar_one()
    if unreadable:
        raise RuntimeError(
            f"{unreadable} beneficial owner(s) in ubo_record carry a date of birth or an "
            "identification number, which may be encrypted with the old system's cipher and "
            "cannot be copied in SQL. Copy them with a command first; nothing was changed."
        )

    for name, type_, nullable, default in COLUMNS:
        op.add_column(
            "exporter_contact",
            sa.Column(
                name,
                type_,
                nullable=nullable,
                server_default=sa.text(default) if default else None,
            ),
            schema=SCHEMA,
        )
    for name, expression in CHECKS:
        op.create_check_constraint(name, "exporter_contact", expression, schema=SCHEMA)
    op.create_unique_constraint(
        "uq_exporter_contact_id_customer", "exporter_contact", ["id", "customer_id"], schema=SCHEMA
    )
    # Not `public.prevent_mutation()`: its message says UPDATE is forbidden too, and a
    # person is edited all the time.
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.prevent_delete() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Rows of % are never deleted: change their status instead',
                TG_TABLE_NAME;
        END;
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_exporter_contact_no_delete
        BEFORE DELETE ON {SCHEMA}.exporter_contact
        FOR EACH STATEMENT
        EXECUTE FUNCTION {SCHEMA}.prevent_delete();
        """
    )

    # The old system's owners, with their ids, so runs that name them stay valid.
    op.execute(
        f"""
        WITH copied AS (
            INSERT INTO {SCHEMA}.exporter_contact (
                id, customer_id, name, is_contact, is_director, is_ubo,
                nationality, residence_country, ownership_pct, control_type,
                status, source, source_ref, created_at, updated_at
            )
            SELECT u.id, p.customer_id,
                   left(btrim(btrim(u.first_name) || ' ' || btrim(u.last_name)), 255),
                   false, false, true,
                   u.nationality, u.residence_country, u.ownership_percentage,
                   u.control_type::text, 'ACTIVE', '{LEGACY_SOURCE}',
                   u.onboarding_request_id::text, u.created_at, u.updated_at
            {_LINKED_UBOS}
            ON CONFLICT (id) DO NOTHING
            RETURNING id, customer_id, name
        )
        INSERT INTO {SCHEMA}.exporter_lifecycle_history (
            id, customer_id, dimension, event_type, from_status, to_status, actor_id,
            event_metadata
        )
        SELECT gen_random_uuid(), customer_id, 'contact', 'person_added', NULL, 'UBO',
               'migration:{revision}',
               jsonb_build_object(
                   'source', 'migration.{revision}',
                   'contact_id', id::text,
                   'contact_name', name,
                   'roles', jsonb_build_array('UBO')
               )
          FROM copied
        """
    )

    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.sanctions_run
        ADD CONSTRAINT fk_sanctions_run_subject_person
        FOREIGN KEY (subject_reference, company_id)
        REFERENCES {SCHEMA}.exporter_contact (id, customer_id)
        ON DELETE RESTRICT NOT VALID
        """
    )
    dangling = bind.execute(
        sa.text(
            f"""
            SELECT count(*) FROM {SCHEMA}.sanctions_run s
             WHERE s.subject_reference IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM {SCHEMA}.exporter_contact c
                    WHERE c.id = s.subject_reference AND c.customer_id = s.company_id)
            """
        )
    ).scalar_one()
    if dangling:
        print(
            f"fk_sanctions_run_subject_person left NOT VALID: {dangling} screening run(s) "
            "name a person who is not one of their company's people. List them with: "
            f"SELECT s.id, s.company_id, s.subject_type, s.subject_reference FROM {SCHEMA}."
            "sanctions_run s WHERE s.subject_reference IS NOT NULL AND NOT EXISTS (SELECT 1 "
            f"FROM {SCHEMA}.exporter_contact c WHERE c.id = s.subject_reference AND "
            "c.customer_id = s.company_id)"
        )
    else:
        op.execute(
            f"ALTER TABLE {SCHEMA}.sanctions_run VALIDATE CONSTRAINT fk_sanctions_run_subject_person"
        )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        DECLARE recorded integer;
        BEGIN
            SELECT count(*) INTO recorded FROM {SCHEMA}.exporter_contact
             WHERE (is_director OR is_ubo) AND source IS DISTINCT FROM '{LEGACY_SOURCE}';
            IF recorded > 0 THEN
                RAISE EXCEPTION
                    '% director(s) or beneficial owner(s) were recorded after this revision and '
                    'exist nowhere else. Restore the pg_dump taken before the upgrade instead '
                    'of downgrading.', recorded;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"ALTER TABLE {SCHEMA}.sanctions_run DROP CONSTRAINT IF EXISTS fk_sanctions_run_subject_person")
    op.execute(f"DROP TRIGGER IF EXISTS trg_exporter_contact_no_delete ON {SCHEMA}.exporter_contact")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.prevent_delete()")

    # The copies go: ubo_record still holds them. Their `person_added` history rows
    # stay, like every history row: the log is append-only.
    op.execute(f"DELETE FROM {SCHEMA}.exporter_contact WHERE source = '{LEGACY_SOURCE}'")

    op.drop_constraint("uq_exporter_contact_id_customer", "exporter_contact", schema=SCHEMA)
    for name, _expression in reversed(CHECKS):
        op.drop_constraint(name, "exporter_contact", schema=SCHEMA)
    for name, *_rest in reversed(COLUMNS):
        op.drop_column("exporter_contact", name, schema=SCHEMA)
