"""Room in ``exporter_contact.phone`` for an encrypted number.

Revision ID: onboarding_0062_phone_sealed
Revises: onboarding_0061_drop_columns

Why
---
``exporter_contact.phone`` is personal data and sat in plain text, protected only by
the API masking the field for a viewer without ``exporters:view_full_tax_id``. That
control works in the response layer, so it does nothing for a ``pg_dump``, a read
replica, a restored backup or a query log.

From here the application seals every phone number it writes
(``contact_phone.seal_phone``), **in the column it already lived in** rather than in a
``phone_encrypted`` column beside it. A sealed value no longer fits ``varchar(50)``:
it is ``d1.<key id>.`` plus base64, 48 characters for a number like
``+919876543210`` and longer as the key id grows. Hence 512, the width
``company_bank_account.account_number_encrypted`` already uses.

First of the PII columns to be converted; the rest follow once this one has proved
itself.

Data
----
**None. Numbers already in the table are left exactly as they are**, in plain text.
Only what is written from here on is sealed.

That leaves the column holding both kinds at once, which is deliberate and safe,
because a sealed value announces itself: it begins ``d1.``, and no phone number can.
Every path that touches the column checks (``is_deterministic_ciphertext``):

* ``seal_phone`` leaves an already-sealed value alone, so re-saving a contact cannot
  seal a ciphertext a second time;
* ``open_phone`` returns a plain number as it stands and decrypts a sealed one;
* the response masks a sealed number after decrypting it, and a plain one as before,
  so no client ever receives a ciphertext either way.

A later migration can seal the rest once there is a reason to — the read path already
copes with whichever state each row is in. On this database that was done and then
undone deliberately: the existing numbers are test data and worth more as they are.

AES-SIV, not AES-GCM
--------------------
The application seals this column deterministically, so the same line always stores
identically and the column can still be compared — a unique constraint or an equality
lookup needs that, and ``encrypt_field``'s random nonce prevents it. Determinism is
only useful over a canonical input, so the number is normalised first
(``contact_phone.normalise_phone``): ``+91 98765 43210``, ``09876543210`` and
``9876543210`` all become ``+919876543210``.

**A bare national number is read as Indian** (``DEFAULT_COUNTRY_CODE``). The
assumption is baked into what gets stored, so a bare non-Indian number normalises
wrongly and no later read recovers it. See ``contact_phone``'s own docstring.

Rollback
--------
The downgrade narrows the column back to ``varchar(50)``, decrypting any sealed value
on the way so nothing is truncated into nonsense. That needs a key that wrote those
rows to still be configured; without one it raises rather than destroying data. What
it restores is the canonical form, not the characters originally typed —
``09876543210`` comes back as ``+919876543210``, which is not reversible and is the
cost of normalising.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.modules.onboarding.domain.contact_phone import PHONE_PURPOSE
from app.platform.security.field_cipher import (
    decrypt_deterministic,
    is_deterministic_ciphertext,
)

revision: str = "onboarding_0062_phone_sealed"
down_revision: str | None = "onboarding_0061_drop_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
TABLE = "exporter_contact"

#: Wide enough for the ciphertext of any number anyone could enter, matching the width
#: `company_bank_account.account_number_encrypted` already uses.
SEALED_WIDTH = 512
TYPED_WIDTH = 50


def upgrade() -> None:
    op.alter_column(
        TABLE,
        "phone",
        type_=sa.String(SEALED_WIDTH),
        existing_type=sa.String(TYPED_WIDTH),
        existing_nullable=True,
        schema=SCHEMA,
    )


def downgrade() -> None:
    bind = op.get_bind()

    rows = list(
        bind.execute(
            sa.text(
                f"SELECT id::text, phone FROM {SCHEMA}.{TABLE} "  # noqa: S608 - no user input
                "WHERE phone IS NOT NULL ORDER BY id"
            )
        )
    )
    update = sa.text(
        f"UPDATE {SCHEMA}.{TABLE} SET phone = :phone WHERE id = :id"  # noqa: S608
    )

    opened = 0
    for contact_id, phone in rows:
        if not is_deterministic_ciphertext(phone):
            continue
        # Raises if no configured key opens it. Better than narrowing the column and
        # truncating a ciphertext into something unrecoverable.
        bind.execute(
            update,
            {
                "phone": decrypt_deterministic(phone, purpose=PHONE_PURPOSE),
                "id": contact_id,
            },
        )
        opened += 1

    op.alter_column(
        TABLE,
        "phone",
        type_=sa.String(TYPED_WIDTH),
        existing_type=sa.String(SEALED_WIDTH),
        existing_nullable=True,
        schema=SCHEMA,
    )
    if opened:
        print(f"onboarding_0062: {opened} sealed phone number(s) returned to plain text.")
