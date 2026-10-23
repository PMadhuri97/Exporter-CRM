"""Room for an encrypted value in ``exporter_profile.registration_number``.

Revision ID: onboarding_0065_sealed_regno
Revises: onboarding_0064_sealed_ids

Why apart from 0064
-------------------
A registration number is shown as the registrar writes it (``KVK 12.345``) but
compared normalised (``KVK12345``): ``uq_exporter_profile_country_registration_number``
is an index on ``upper(regexp_replace(registration_number, '[^A-Za-z0-9]', '', 'g'))``.
A ciphertext cannot be normalised by the database, so one deterministic seal of the
value cannot serve both.

The column instead holds two seals of one value, written by ``SealedKeyedString``
(``app/platform/security/sealed_type.py``)::

    <AES-SIV of registration_key(value)>|<AES-GCM of value>

The first half is the same for every spelling of one registration, and is what the
new unique index compares; the second reads back as typed.

Two indexes, one rule
---------------------
**No value is encrypted here**, as in 0062–0064, so the column holds old plain rows and
new sealed ones, and each needs the rule:

- ``uq_exporter_profile_country_registration_number`` keeps its expression and name,
  and becomes partial to plain rows;
- ``uq_exporter_profile_country_registration_key`` is the same rule over sealed rows,
  on ``split_part(registration_number, '|', 1)``.

A plain row and a sealed row for one registration fall under different indexes, so
the database alone does not refuse the pair; the service's duplicate check
(``get_by_registration_number``, which looks in both) does, as for a PAN.

Width
-----
The two halves run to about 350 characters for a 100-character number, so the column
becomes ``text``. The API's own limit (100) is unchanged.

Rollback
--------
The downgrade opens every sealed value, refuses — before changing anything — when one
is longer than the old ``varchar(100)`` or when two would then collide under the old
index, and restores the column and its single index as they were.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.modules.onboarding.domain.sealed_columns import PROFILE_REGISTRATION_NUMBER

revision: str = "onboarding_0065_sealed_regno"
down_revision: str | None = "onboarding_0064_sealed_ids"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
TABLE = "exporter_profile"
OLD_WIDTH = 100

#: ``sealed_type.KEYED_SQL``, restated so this revision does not move if that does.
KEYED = r"^d1\.[^.[:space:]|]+\.[A-Za-z0-9+/]+={0,2}\|v1\.[^.[:space:]|]+\.[A-Za-z0-9+/]+={0,2}$"
PLAIN_INDEX = "uq_exporter_profile_country_registration_number"
KEY_INDEX = "uq_exporter_profile_country_registration_key"
NORMALISED = "upper(regexp_replace(registration_number, '[^A-Za-z0-9]', '', 'g'))"
PRESENT = "registration_number IS NOT NULL AND country IS NOT NULL"


def upgrade() -> None:
    op.execute(f"DROP INDEX {SCHEMA}.{PLAIN_INDEX}")
    op.alter_column(
        TABLE,
        "registration_number",
        type_=sa.Text(),
        existing_type=sa.String(OLD_WIDTH),
        existing_nullable=True,
        schema=SCHEMA,
    )
    op.execute(
        f"CREATE UNIQUE INDEX {PLAIN_INDEX} ON {SCHEMA}.{TABLE} (country, {NORMALISED}) "
        f"WHERE {PRESENT} AND registration_number !~ '{KEYED}'"
    )
    op.execute(
        f"CREATE UNIQUE INDEX {KEY_INDEX} ON {SCHEMA}.{TABLE} "
        f"(country, split_part(registration_number, '|', 1)) "
        f"WHERE {PRESENT} AND registration_number ~ '{KEYED}'"
    )


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            f"SELECT id::text, country, registration_number FROM {SCHEMA}.{TABLE} "  # noqa: S608
            "WHERE registration_number ~ :keyed"
        ),
        {"keyed": KEYED},
    )
    opened = [
        (row_id, country, PROFILE_REGISTRATION_NUMBER.process_result_value(stored, None))
        for row_id, country, stored in list(rows)
    ]

    too_long = [row_id for row_id, _, plain in opened if len(plain) > OLD_WIDTH]
    if too_long:
        raise RuntimeError(
            f"onboarding_0065: {len(too_long)} registration number(s) are longer than "
            f"varchar({OLD_WIDTH}); first: exporter_profile id={too_long[0]}."
        )

    # A sealed row and a plain row for one registration were under different indexes;
    # back under one, they would make `CREATE UNIQUE INDEX` fail half-way. Said here.
    plain_keys = {
        (country, key)
        for country, key in bind.execute(
            sa.text(
                f"SELECT country, {NORMALISED} FROM {SCHEMA}.{TABLE} "  # noqa: S608
                f"WHERE {PRESENT} AND registration_number !~ :keyed"
            ),
            {"keyed": KEYED},
        )
    }
    seen: set[tuple[str, str]] = set()
    for row_id, country, plain in opened:
        if country is None:
            continue
        key = (country, PROFILE_REGISTRATION_NUMBER.normalise(plain))
        if key in plain_keys or key in seen:
            raise RuntimeError(
                "onboarding_0065: a sealed registration number duplicates another once "
                f"opened, so the old index cannot be rebuilt; exporter_profile id={row_id}."
            )
        seen.add(key)

    for row_id, _country, plain in opened:
        bind.execute(
            sa.text(
                f"UPDATE {SCHEMA}.{TABLE} SET registration_number = :value WHERE id = :id"  # noqa: S608
            ),
            {"value": plain, "id": row_id},
        )

    op.execute(f"DROP INDEX {SCHEMA}.{KEY_INDEX}")
    op.execute(f"DROP INDEX {SCHEMA}.{PLAIN_INDEX}")
    op.alter_column(
        TABLE,
        "registration_number",
        type_=sa.String(OLD_WIDTH),
        existing_type=sa.Text(),
        existing_nullable=True,
        schema=SCHEMA,
    )
    op.execute(
        f"CREATE UNIQUE INDEX {PLAIN_INDEX} ON {SCHEMA}.{TABLE} (country, {NORMALISED}) "
        f"WHERE {PRESENT}"
    )
    if opened:
        print(f"onboarding_0065: {len(opened)} registration number(s) returned to plain text.")
