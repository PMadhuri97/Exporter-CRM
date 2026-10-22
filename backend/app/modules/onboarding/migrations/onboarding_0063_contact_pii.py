"""Room in a contact's email and date of birth for an encrypted value.

Revision ID: onboarding_0063_contact_pii
Revises: onboarding_0062_phone_sealed

Why
---
The second and third columns of the PII work, after ``exporter_contact.phone`` in
0062, and sealed the same way: **in the columns they already live in**, with the
application encrypting what it writes from here on.

Both are personal data that sat in plain text, protected only by the API masking them
for a viewer without ``exporters:view_full_tax_id`` — a response-layer control that
does nothing for a ``pg_dump``, a read replica, a restored backup or a query log.

Two ciphers, because the two columns are used differently
---------------------------------------------------------
``email`` is **compared** — the duplicate rule asks whether a company already has a
contact at an address — so it is sealed deterministically (AES-SIV), and the address
is trimmed and lower-cased first so identical addresses seal identically.

``date_of_birth`` is **never compared**, so it gets the stronger cipher: AES-GCM with
a fresh random nonce, which leaks nothing at all, not even which two people share a
birthday. Deterministic encryption would leak that for no benefit.

The type change
---------------
``date_of_birth`` was a ``date``. A ciphertext is text, so the column becomes
``varchar(512)`` and holds the ISO spelling of the date, sealed. **Existing dates are
converted to their ISO text** — that is a type change, not an encryption, and it is
the one thing here that does touch existing rows, because a ``date`` column cannot
hold a ciphertext alongside.

The database therefore stops knowing this is a date: no ordering, no age arithmetic,
no range filter in SQL. Nothing did any of those — checked before writing this — and
anything that needs to must do it after decrypting.

Data
----
**No value is encrypted here.** Existing emails stay as they are, and existing dates
of birth are rewritten only from ``date`` to the identical ISO text. Only what the
application writes from here on is sealed.

That leaves each column holding both kinds at once, which is deliberate and safe: a
sealed value announces itself (``d1.`` for the deterministic seal, ``v1.`` for the
random one) and no address or date can begin either way. ``seal_*`` leaves an
already-sealed value alone, ``open_*`` returns a plain one as it stands, and the
response masks either way, so no client receives a ciphertext.

Rollback
--------
The downgrade decrypts anything sealed, turns the ISO text back into a ``date`` and
narrows ``email`` to its old width. It needs a key that wrote those rows to still be
configured; without one it raises rather than writing a truncated ciphertext into a
narrower column and calling it restored.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.modules.onboarding.domain.contact_privacy import (
    DATE_OF_BIRTH_PURPOSE,
    EMAIL_PURPOSE,
)
from app.platform.security.field_cipher import (
    decrypt_deterministic,
    decrypt_field,
    is_deterministic_ciphertext,
    is_random_ciphertext,
)

revision: str = "onboarding_0063_contact_pii"
down_revision: str | None = "onboarding_0062_phone_sealed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
TABLE = "exporter_contact"

SEALED_WIDTH = 512
EMAIL_WIDTH = 255

#: What the column holds for a row written before it was sealed.
_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def upgrade() -> None:
    op.alter_column(
        TABLE,
        "email",
        type_=sa.String(SEALED_WIDTH),
        existing_type=sa.String(EMAIL_WIDTH),
        existing_nullable=True,
        schema=SCHEMA,
    )
    # `date` to text, keeping each date's own ISO spelling. `USING` is required:
    # Postgres will not cast a date to varchar implicitly.
    op.alter_column(
        TABLE,
        "date_of_birth",
        type_=sa.String(SEALED_WIDTH),
        existing_type=sa.Date(),
        existing_nullable=True,
        postgresql_using="to_char(date_of_birth, 'YYYY-MM-DD')",
        schema=SCHEMA,
    )


def downgrade() -> None:
    bind = op.get_bind()
    update = sa.text(
        f"UPDATE {SCHEMA}.{TABLE} SET email = :value WHERE id = :id"  # noqa: S608
    )
    rows = bind.execute(
        sa.text(
            f"SELECT id::text, email FROM {SCHEMA}.{TABLE} "  # noqa: S608
            "WHERE email IS NOT NULL"
        )
    )
    opened = 0
    for contact_id, email in list(rows):
        if not is_deterministic_ciphertext(email):
            continue
        bind.execute(
            update,
            {"value": decrypt_deterministic(email, purpose=EMAIL_PURPOSE), "id": contact_id},
        )
        opened += 1

    update_dob = sa.text(
        f"UPDATE {SCHEMA}.{TABLE} SET date_of_birth = :value WHERE id = :id"  # noqa: S608
    )
    rows = bind.execute(
        sa.text(
            f"SELECT id::text, date_of_birth FROM {SCHEMA}.{TABLE} "  # noqa: S608
            "WHERE date_of_birth IS NOT NULL"
        )
    )
    unreadable: list[str] = []
    for contact_id, dob in list(rows):
        if is_random_ciphertext(dob):
            bind.execute(
                update_dob,
                {"value": decrypt_field(dob, purpose=DATE_OF_BIRTH_PURPOSE), "id": contact_id},
            )
            opened += 1
        elif not _ISO_DATE.match(dob):
            # Neither this migration's own ciphertext nor a date. The cast below would
            # fail with `invalid input syntax for type date`, naming the value and not
            # the row; said here instead, before anything is altered.
            unreadable.append(contact_id)

    if unreadable:
        raise RuntimeError(
            f"onboarding_0063: {len(unreadable)} exporter_contact row(s) hold a "
            "date_of_birth that is neither an ISO date nor a value this migration "
            f"sealed, so the column cannot go back to `date`. First: {unreadable[0]}. "
            "List them with: SELECT id, date_of_birth FROM onboarding.exporter_contact "
            "WHERE date_of_birth IS NOT NULL AND date_of_birth !~ "
            "'^[0-9]{4}-[0-9]{2}-[0-9]{2}$' AND date_of_birth NOT LIKE 'v1.%';"
        )

    op.alter_column(
        TABLE,
        "date_of_birth",
        type_=sa.Date(),
        existing_type=sa.String(SEALED_WIDTH),
        existing_nullable=True,
        postgresql_using="date_of_birth::date",
        schema=SCHEMA,
    )
    op.alter_column(
        TABLE,
        "email",
        type_=sa.String(EMAIL_WIDTH),
        existing_type=sa.String(SEALED_WIDTH),
        existing_nullable=True,
        schema=SCHEMA,
    )
    if opened:
        print(f"onboarding_0063: {opened} sealed value(s) returned to plain text.")
