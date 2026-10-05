"""``exporter_gstin`` becomes a branch record.

Revision ID: onboarding_0035_gst_branch
Revises: onboarding_0034_deal_buyer_co

Why
---
The CRM needs a per-branch record: a company trading from Maharashtra and Karnataka has
two addresses, two portal statuses, and possibly a compliance problem in one of
them. The design grows ``exporter_gstin`` **in place** rather than
create ``gst_registration`` and copy — every row, FK and repository stays, and
nothing has to be moved.

What it adds
------------
* ``gst_registration_status_enum`` (``UNVERIFIED`` | ``ACTIVE`` | ``CANCELLED`` |
  ``SUSPENDED``) and ``gst_registration_flag_enum`` (``NONE`` | ``FLAGGED``), both
  created in the ordinary transactional body.
* ``state_code``, ``state_name``, ``status`` (``NOT NULL DEFAULT 'UNVERIFIED'``),
  ``address``, ``flag_status`` (``NOT NULL DEFAULT 'NONE'``), ``flag_reason``,
  ``active`` (``NOT NULL DEFAULT true``), ``deactivated_at``, ``deactivated_by``.
* ``uq_exporter_gstin_id_customer_id`` — redundant on its own, since ``id`` is the
  primary key, and that is the point: it is what lets migration 0036 tie a deal's
  invoicing branch to its seller with a **composite** FK, so the database refuses a
  deal pointing at another company's branch.
* ``ck_exporter_gstin_flag_reason``: ``FLAGGED`` implies a non-blank reason.
* ``ck_exporter_gstin_deactivation``: an active row has no deactivation stamp, a
  deactivated one has a timestamp.
* ``trg_exporter_gstin_no_delete``: **DELETE is refused.** Until now a company edit
  that dropped a GSTIN deleted its row (``cascade="all, delete-orphan"``, removed in
  this task). Once a deal records its invoicing branch that delete would hit
  ``fk_deal_seller_gst_registration_id``'s ``RESTRICT`` and fail; and where it
  succeeded it destroyed the record of a branch the company really traded through.
  Dropping a registration is now a deactivation.

Data steps
----------
``state_code`` from the GSTIN's first two characters, and ``state_name`` from the
code, for every row — the same mapping ``domain/gst_states.py`` applies going
forward, restated here as SQL because a migration must not depend on code that
keeps changing. ``test_gst_branch.py`` asserts the two agree, so a code added
to one and not the other fails a test.

**Unknown codes are reported, not refused**. The
format check accepts any two digits, so a row may carry a code this release does
not know; it keeps ``state_name = NULL``, and the count is printed for the
operator. ``state_code`` is still filled, because the GSTIN really does carry it.

Everything else needs no backfill: the server defaults make every existing row
``UNVERIFIED``, ``NONE`` and ``active``, which is what they all are.

Rollback
--------
``pg_dump`` first. The downgrade drops the trigger, the two check constraints, the
composite unique key, the nine columns and the two enums. Dropping the columns
loses every address, portal status, flag and deactivation recorded since — and
re-enables deletion of rows a deal may point at, so downgrade only if you mean it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0035_gst_branch"
down_revision: str | None = "onboarding_0034_deal_buyer_co"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

_STATUS = postgresql.ENUM(
    "UNVERIFIED",
    "ACTIVE",
    "CANCELLED",
    "SUSPENDED",
    name="gst_registration_status_enum",
    schema=SCHEMA,
)
_FLAG = postgresql.ENUM(
    "NONE", "FLAGGED", name="gst_registration_flag_enum", schema=SCHEMA
)

#: GST state code → name, frozen as of this migration. The live mapping is
#: ``GST_STATE_NAMES`` in ``domain/gst_states.py``; a test asserts they agree.
_STATE_NAMES: tuple[tuple[str, str], ...] = (
    ("01", "Jammu and Kashmir"),
    ("02", "Himachal Pradesh"),
    ("03", "Punjab"),
    ("04", "Chandigarh"),
    ("05", "Uttarakhand"),
    ("06", "Haryana"),
    ("07", "Delhi"),
    ("08", "Rajasthan"),
    ("09", "Uttar Pradesh"),
    ("10", "Bihar"),
    ("11", "Sikkim"),
    ("12", "Arunachal Pradesh"),
    ("13", "Nagaland"),
    ("14", "Manipur"),
    ("15", "Mizoram"),
    ("16", "Tripura"),
    ("17", "Meghalaya"),
    ("18", "Assam"),
    ("19", "West Bengal"),
    ("20", "Jharkhand"),
    ("21", "Odisha"),
    ("22", "Chhattisgarh"),
    ("23", "Madhya Pradesh"),
    ("24", "Gujarat"),
    ("25", "Daman and Diu (merged into Dadra and Nagar Haveli and Daman and Diu)"),
    ("26", "Dadra and Nagar Haveli and Daman and Diu"),
    ("27", "Maharashtra"),
    ("28", "Andhra Pradesh (before the 2014 reorganisation)"),
    ("29", "Karnataka"),
    ("30", "Goa"),
    ("31", "Lakshadweep"),
    ("32", "Kerala"),
    ("33", "Tamil Nadu"),
    ("34", "Puducherry"),
    ("35", "Andaman and Nicobar Islands"),
    ("36", "Telangana"),
    ("37", "Andhra Pradesh"),
    ("38", "Ladakh"),
    ("97", "Other Territory"),
    ("99", "Centre Jurisdiction"),
)

_NO_DELETE_FUNCTION = f"""
CREATE OR REPLACE FUNCTION {SCHEMA}.prevent_gst_registration_delete()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
BEGIN
    RAISE EXCEPTION
        'GST registration % is a branch this company traded through: deactivate it instead of deleting it',
        OLD.id;
END;
$fn$;
"""


def upgrade() -> None:
    bind = op.get_bind()
    _STATUS.create(bind, checkfirst=False)
    _FLAG.create(bind, checkfirst=False)

    op.add_column(
        "exporter_gstin", sa.Column("state_code", sa.String(2), nullable=True), schema=SCHEMA
    )
    op.add_column(
        "exporter_gstin", sa.Column("state_name", sa.String(100), nullable=True), schema=SCHEMA
    )
    op.add_column(
        "exporter_gstin",
        sa.Column("status", _STATUS, nullable=False, server_default="UNVERIFIED"),
        schema=SCHEMA,
    )
    op.add_column("exporter_gstin", sa.Column("address", sa.Text(), nullable=True), schema=SCHEMA)
    op.add_column(
        "exporter_gstin",
        sa.Column("flag_status", _FLAG, nullable=False, server_default="NONE"),
        schema=SCHEMA,
    )
    op.add_column(
        "exporter_gstin", sa.Column("flag_reason", sa.Text(), nullable=True), schema=SCHEMA
    )
    op.add_column(
        "exporter_gstin",
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        schema=SCHEMA,
    )
    op.add_column(
        "exporter_gstin",
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "exporter_gstin",
        sa.Column("deactivated_by", sa.String(255), nullable=True),
        schema=SCHEMA,
    )

    # ── Data: the state every existing registration was issued in ────────────
    bind.execute(
        sa.text(
            f"UPDATE {SCHEMA}.exporter_gstin "
            "SET state_code = substring(gstin from 1 for 2) "
            "WHERE gstin ~ '^[0-9]{2}'"
        )
    )
    whens = "\n".join(
        f"            WHEN '{code}' THEN '{name.replace(chr(39), chr(39) * 2)}'"
        for code, name in _STATE_NAMES
    )
    bind.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA}.exporter_gstin
            SET state_name = CASE state_code
{whens}
                ELSE NULL
            END
            WHERE state_code IS NOT NULL
            """
        )
    )
    unknown = bind.execute(
        sa.text(
            f"SELECT count(*) FROM {SCHEMA}.exporter_gstin "
            "WHERE state_code IS NOT NULL AND state_name IS NULL"
        )
    ).scalar_one()
    no_code = bind.execute(
        sa.text(f"SELECT count(*) FROM {SCHEMA}.exporter_gstin WHERE state_code IS NULL")
    ).scalar_one()
    print(  # noqa: T201 — a migration's report belongs on the operator's console
        f"onboarding_0035_gst_branch: {unknown} registration(s) carry a state code this "
        f"release does not know (state_name left NULL); {no_code} have no numeric code at all"
    )

    # ── The constraints, added after the data so they validate against it ────
    op.create_unique_constraint(
        "uq_exporter_gstin_id_customer_id",
        "exporter_gstin",
        ["id", "customer_id"],
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_exporter_gstin_flag_reason",
        "exporter_gstin",
        "flag_status <> 'FLAGGED' OR (flag_reason IS NOT NULL AND length(btrim(flag_reason)) > 0)",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_exporter_gstin_deactivation",
        "exporter_gstin",
        "(active AND deactivated_at IS NULL AND deactivated_by IS NULL)"
        " OR (NOT active AND deactivated_at IS NOT NULL)",
        schema=SCHEMA,
    )

    op.execute(_NO_DELETE_FUNCTION)
    op.execute(
        f"""
        CREATE TRIGGER trg_exporter_gstin_no_delete
        BEFORE DELETE ON {SCHEMA}.exporter_gstin
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.prevent_gst_registration_delete();
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_exporter_gstin_no_delete ON {SCHEMA}.exporter_gstin;"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.prevent_gst_registration_delete();")
    for name in ("ck_exporter_gstin_deactivation", "ck_exporter_gstin_flag_reason"):
        op.drop_constraint(name, "exporter_gstin", type_="check", schema=SCHEMA)
    op.drop_constraint(
        "uq_exporter_gstin_id_customer_id", "exporter_gstin", type_="unique", schema=SCHEMA
    )
    for column in (
        "deactivated_by",
        "deactivated_at",
        "active",
        "flag_reason",
        "flag_status",
        "address",
        "status",
        "state_name",
        "state_code",
    ):
        op.drop_column("exporter_gstin", column, schema=SCHEMA)

    bind = op.get_bind()
    _FLAG.drop(bind, checkfirst=False)
    _STATUS.drop(bind, checkfirst=False)
