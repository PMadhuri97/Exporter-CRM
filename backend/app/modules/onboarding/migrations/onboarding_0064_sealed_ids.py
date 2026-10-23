"""Room for an encrypted value in thirteen identifier and address columns.

Revision ID: onboarding_0064_sealed_ids
Revises: onboarding_0063_contact_pii

Why
---
The rest of the PII work after ``exporter_contact.phone`` (0062) and ``email`` (0063):
a company's PAN, CIN, IEC and GSTINs, a director's DIN, a deal buyer's identifiers and
contact details, and a company's addresses, all of which sat in plain text behind a
response-layer mask that does nothing for a ``pg_dump``, a replica or a query log.

Sealed **in the columns they already live in**, with AES-SIV, by the application:
the columns are declared ``SealedString`` (``app/platform/security/sealed_type.py``),
which seals on write and opens on read. Deterministic because these values are
compared — ``uq_exporter_profile_pan``, ``uq_exporter_gstin_customer_gstin``, the
``?pan=`` / ``?gstin=`` / ``?iec=`` filters and the duplicate checks behind them.

``exporter_profile.registration_number`` is **not** here: it is shown as typed but
compared in a normalised form (``uq_exporter_profile_country_registration_number`` is
an expression index), which needs a second column and is a change of its own.

Data
----
**No value is encrypted here**, as in 0062 and 0063. Existing rows stay plain; what the
application writes from now on is sealed. The ORM comparison matches both forms
(``SealedString``'s comparator), so a lookup finds an old row and a new one alike.

The format checks
-----------------
Each regex check would refuse every ciphertext, so each gains one alternative: the
whole shape of a sealed value. A plain value is still checked by the database exactly
as before, and ``SealedString`` writes a value that fails its format **unsealed**, so a
malformed PAN is refused by this same constraint, with the same error, as it always
was. Only a well-formed value is ever encrypted. Names are unchanged.

``ck_exporter_gstin_state_code`` compares ``state_code`` with ``left(gstin, 2)``, which
means nothing for a ciphertext; for a sealed GSTIN the service's ``state_code_of`` is
what keeps the two in step.

Widths
------
A ciphertext is about ``1.33 × (bytes + 16) + 10`` characters. Identifiers become
``varchar(255)``, which holds a sealed value of up to ~165 bytes (a 100-character tax id
seals to 164). Free text — ``line1``, ``line2``, ``city``, ``contact_email`` — becomes
``text``: the API accepts 255 *characters*, and in Devanagari that is 765 bytes, 1052
characters sealed. NOT NULL stays where it was.

Rollback
--------
The downgrade opens anything sealed — the columns, and the identifier leaves of
``deal.handover_snapshot`` and ``verification_result.subject_snapshot``, which the
application seals from this revision on (``SealedJSON``) — narrows each column back and
restores each check. Frozen rows are restored with their freeze trigger disabled for
that one ``UPDATE``: the plain spelling of a value is not an edit to it.
It needs a key that wrote those rows to still be configured, and it refuses — before
changing anything — when a value would not fit its old width.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op

from app.modules.onboarding.domain.sealed_columns import HANDOVER_SNAPSHOT, SUBJECT_SNAPSHOT
from app.platform.security.field_cipher import decrypt_deterministic

revision: str = "onboarding_0064_sealed_ids"
down_revision: str | None = "onboarding_0063_contact_pii"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

#: The shape of an AES-SIV value (``sealed_type.looks_sealed``), as a Postgres regex.
SEALED = r"^d1\.[^.[:space:]]+\.[A-Za-z0-9+/]+={0,2}$"

#: (table, column, width before, width after — ``None`` for ``text`` — nullable)
COLUMNS: tuple[tuple[str, str, int, int | None, bool], ...] = (
    ("exporter_contact", "din", 8, 255, True),
    ("exporter_profile", "pan", 10, 255, True),
    ("exporter_profile", "cin", 21, 255, True),
    ("exporter_profile", "iec", 10, 255, True),
    ("exporter_gstin", "gstin", 15, 255, False),
    ("deal_buyer", "tax_id", 100, 255, True),
    ("deal_buyer", "registration_number", 100, 255, True),
    ("deal_buyer", "contact_email", 255, None, True),
    ("deal_buyer", "contact_phone", 50, 255, True),
    ("company_address", "line1", 255, None, False),
    ("company_address", "line2", 255, None, True),
    ("company_address", "city", 120, None, False),
    ("company_address", "postal_code", 20, 255, True),
)


def _sealed_type(width: int | None) -> sa.types.TypeEngine:
    return sa.String(width) if width is not None else sa.Text()

PAN = "^[A-Z]{5}[0-9]{4}[A-Z]$"
CIN = "^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$"
IEC = "^[A-Z0-9]{10}$"
GSTIN = "^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"
DIN = "^[0-9]{8}$"

#: (table, constraint, before, after)
CHECKS: tuple[tuple[str, str, str, str], ...] = (
    (
        "exporter_contact",
        "ck_exporter_contact_din",
        f"din IS NULL OR (is_director AND din ~ '{DIN}')",
        f"din IS NULL OR (is_director AND (din ~ '{DIN}' OR din ~ '{SEALED}'))",
    ),
    (
        "exporter_profile",
        "ck_exporter_profile_pan_format",
        f"pan IS NULL OR pan ~ '{PAN}'",
        f"pan IS NULL OR pan ~ '{PAN}' OR pan ~ '{SEALED}'",
    ),
    (
        "exporter_profile",
        "ck_exporter_profile_cin_format",
        f"cin IS NULL OR cin ~ '{CIN}'",
        f"cin IS NULL OR cin ~ '{CIN}' OR cin ~ '{SEALED}'",
    ),
    (
        "exporter_profile",
        "ck_exporter_profile_iec_format",
        f"iec IS NULL OR iec ~ '{IEC}'",
        f"iec IS NULL OR iec ~ '{IEC}' OR iec ~ '{SEALED}'",
    ),
    (
        "exporter_gstin",
        "ck_exporter_gstin_format",
        f"gstin ~ '{GSTIN}'",
        f"gstin ~ '{GSTIN}' OR gstin ~ '{SEALED}'",
    ),
    (
        "exporter_gstin",
        "ck_exporter_gstin_state_code",
        "state_code IS NULL OR state_code = left(gstin, 2)",
        f"state_code IS NULL OR gstin ~ '{SEALED}' OR state_code = left(gstin, 2)",
    ),
)


#: The purpose each column's values are sealed for: ``"<table>.<column>"``.
def _purpose(table: str, column: str) -> str:
    return f"{table}.{column}"


def _replace_checks(*, upgrade: bool) -> None:
    for table, name, before, after in CHECKS:
        op.drop_constraint(name, table, type_="check", schema=SCHEMA)
        op.create_check_constraint(name, table, after if upgrade else before, schema=SCHEMA)


def upgrade() -> None:
    for table, column, width, sealed_width, nullable in COLUMNS:
        op.alter_column(
            table,
            column,
            type_=_sealed_type(sealed_width),
            existing_type=sa.String(width),
            existing_nullable=nullable,
            schema=SCHEMA,
        )
    _replace_checks(upgrade=True)


def downgrade() -> None:
    bind = op.get_bind()

    # Open every sealed value first, and refuse before writing anything if one would not
    # fit its old width: narrowing a column over a too-long value fails half-way.
    opened: list[tuple[str, str, str, str]] = []
    too_long: list[str] = []
    for table, column, width, _sealed_width, _nullable in COLUMNS:
        rows = bind.execute(
            sa.text(
                f"SELECT id::text, {column} FROM {SCHEMA}.{table} "  # noqa: S608
                f"WHERE {column} ~ :sealed"
            ),
            {"sealed": SEALED},
        )
        for row_id, stored in list(rows):
            plain = decrypt_deterministic(stored, purpose=_purpose(table, column))
            if len(plain) > width:
                too_long.append(f"{table}.{column} id={row_id}")
            opened.append((table, column, row_id, plain))
    if too_long:
        raise RuntimeError(
            f"onboarding_0064: {len(too_long)} sealed value(s) are longer than their "
            f"column was before this migration, so it cannot be narrowed back. First: "
            f"{too_long[0]}."
        )

    # A legacy deal buyer is frozen (`trg_deal_buyer_frozen`); restoring the plain
    # spelling of a value it already holds is not an edit, but the trigger cannot tell.
    with _triggers_off("deal_buyer", "trg_deal_buyer_frozen"):
        for table, column, row_id, plain in opened:
            bind.execute(
                sa.text(
                    f"UPDATE {SCHEMA}.{table} SET {column} = :value WHERE id = :id"  # noqa: S608
                ),
                {"value": plain, "id": row_id},
            )
    opened_snapshots = _open_snapshots(bind)

    _replace_checks(upgrade=False)
    for table, column, width, sealed_width, nullable in COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.String(width),
            existing_type=_sealed_type(sealed_width),
            existing_nullable=nullable,
            schema=SCHEMA,
        )
    if opened or opened_snapshots:
        print(
            f"onboarding_0064: {len(opened)} sealed value(s) and {opened_snapshots} "
            "snapshot(s) returned to plain text."
        )


@contextmanager
def _triggers_off(table: str, *triggers: str) -> Iterator[None]:
    """Disable ``triggers`` on ``table`` for the statements inside, within this
    migration's transaction — so a failure part-way leaves them enabled."""
    for trigger in triggers:
        op.execute(f"ALTER TABLE {SCHEMA}.{table} DISABLE TRIGGER {trigger}")
    yield
    for trigger in triggers:
        op.execute(f"ALTER TABLE {SCHEMA}.{table} ENABLE TRIGGER {trigger}")


def _open_snapshots(bind: sa.engine.Connection) -> int:
    """Return every sealed snapshot leaf to plain text, the snapshots' own triggers
    disabled: a handed-over deal's snapshot and a result's subject are frozen, and the
    plain spelling of the same document is not a change to what was handed over."""
    opened = 0
    for table, column, trigger, sealed_type in (
        ("deal", "handover_snapshot", "trg_deal_terminal_freeze", HANDOVER_SNAPSHOT),
        (
            "verification_result",
            "subject_snapshot",
            "trg_verification_result_input_immutability",
            SUBJECT_SNAPSHOT,
        ),
    ):
        rows = bind.execute(
            sa.text(
                f"SELECT id::text, {column}::text FROM {SCHEMA}.{table} "  # noqa: S608
                f"WHERE {column}::text ~ :sealed"
            ),
            {"sealed": r'"d1\.[^."[:space:]]+\.[A-Za-z0-9+/]+={0,2}"'},
        )
        changed = []
        for row_id, document in list(rows):
            plain = sealed_type.process_result_value(json.loads(document), None)
            changed.append((row_id, json.dumps(plain)))
        with _triggers_off(table, trigger):
            for row_id, document in changed:
                bind.execute(
                    sa.text(
                        f"UPDATE {SCHEMA}.{table} SET {column} = CAST(:value AS jsonb) "  # noqa: S608
                        "WHERE id = :id"
                    ),
                    {"value": document, "id": row_id},
                )
        opened += len(changed)
    return opened
