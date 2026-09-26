"""The company record: identity, tax-ID rules, the marker, and real links
(L2-05, L2-06, L2-08).

Revision ID: onboarding_0014_company_record
Revises: onboarding_0013_shared_history

**This migration empties the CRM's company tables.** The project lead approved
it for the prototype's development database ("this is a dev db we can clear
the contents"), which is architecture decision 1 — start fresh with sample
data — applied to the one conflict the migration register left open: the
company links below cannot be added while rows point at companies that do not
exist, and the history log's append-only trigger forbids deleting just those
rows. The five tables this migration links or constrains are emptied, in one
statement, and nothing else:

    exporter_profile, exporter_contact, exporter_activity,
    screening_review_item, exporter_lifecycle_history

``TRUNCATE`` is used because it is not an ``UPDATE`` or ``DELETE``: the
append-only triggers (``public.prevent_mutation()``) stay exactly as they are
and keep refusing every row-level change afterwards. No trigger is disabled,
dropped or altered here. Legacy onboarding tables, verification results, the
bank-activity table and every other module's tables are not touched. Load the
sample data afterwards with ``python -m app.modules.onboarding.sample_data``.

What it adds:

* **Identity on the company record** — ``name``, ``country``, ``cin`` — so the
  transitional identity store and its ``onboarding_request`` rows are no
  longer needed. ``name``/``country`` stay nullable while the API's unnamed
  create path exists; the database refuses a blank name or a malformed
  country whenever one is given.
* **PAN** — format checked by the database and **unique across companies**
  (decision 4). Still optional: a lead may be entered before its PAN is known.
* **GSTINs** — several per company in ``exporter_gstin``, one row each, format
  checked, unique **within** a company only. A GSTIN held by two companies is a
  warning the service raises, never a constraint (decision 4). The single
  ``exporter_profile.gstin`` column it replaces is dropped.
* **The marker** — ``NONE``/``PAUSED``/``ENDED`` with its current reason, a
  commercial state kept apart from the journey (decision 3). The database
  refuses a ``PAUSED`` or ``ENDED`` marker without a reason.
* **Real links** from contacts, activities, screening items and history to
  the company (migration register, 0014). ``ON DELETE RESTRICT``: a company
  with any of them can never be deleted out from under them.
  ``verification_result.entity_reference`` deliberately gets no link — it
  names several kinds of subject.

The three-value journey is **not** here: the ten old statuses stay until
L2-04 replaces them. The gauge fields (qualification, conversation,
background check) are added by their owners' migrations.

Downgrade restores the previous shape but **not the data**: the emptied rows
are gone, and every GSTIN beyond a company's first is dropped.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0014_company_record"
down_revision: str | None = "onboarding_0013_shared_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

#: The tables the approved decision clears, all in one ``TRUNCATE``.
_CLEARED = (
    "exporter_lifecycle_history",
    "exporter_activity",
    "exporter_contact",
    "screening_review_item",
    "exporter_profile",
)

#: Child tables that gain a real link to their company.
_LINKED = (
    "exporter_contact",
    "exporter_activity",
    "screening_review_item",
    "exporter_lifecycle_history",
)

PAN_PATTERN = "^[A-Z]{5}[0-9]{4}[A-Z]$"
GSTIN_PATTERN = "^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"
CIN_PATTERN = "^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$"
COUNTRY_PATTERN = "^[A-Z]{2}$"

marker_enum = postgresql.ENUM(
    "NONE", "PAUSED", "ENDED", name="exporter_marker_enum", schema=SCHEMA, create_type=False
)


def upgrade() -> None:
    # ── 1. Start fresh (approved decision; see module docstring) ─────────────
    op.execute(
        "TRUNCATE " + ", ".join(f"{SCHEMA}.{table}" for table in _CLEARED)
    )

    # ── 2. Identity, CIN and the marker on the company record ───────────────
    marker_enum.create(op.get_bind(), checkfirst=False)
    op.add_column("exporter_profile", sa.Column("name", sa.String(255)), schema=SCHEMA)
    op.add_column("exporter_profile", sa.Column("country", sa.String(2)), schema=SCHEMA)
    op.add_column("exporter_profile", sa.Column("cin", sa.String(21)), schema=SCHEMA)
    op.add_column(
        "exporter_profile",
        sa.Column("marker", marker_enum, nullable=False, server_default="NONE"),
        schema=SCHEMA,
    )
    op.add_column("exporter_profile", sa.Column("marker_reason", sa.Text()), schema=SCHEMA)
    op.drop_column("exporter_profile", "gstin", schema=SCHEMA)

    op.create_check_constraint(
        "ck_exporter_profile_name_not_blank",
        "exporter_profile",
        "name IS NULL OR btrim(name) <> ''",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_exporter_profile_country_format",
        "exporter_profile",
        f"country IS NULL OR country ~ '{COUNTRY_PATTERN}'",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_exporter_profile_pan_format",
        "exporter_profile",
        f"pan IS NULL OR pan ~ '{PAN_PATTERN}'",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_exporter_profile_cin_format",
        "exporter_profile",
        f"cin IS NULL OR cin ~ '{CIN_PATTERN}'",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_exporter_profile_marker_reason",
        "exporter_profile",
        "marker = 'NONE' OR (marker_reason IS NOT NULL AND btrim(marker_reason) <> '')",
        schema=SCHEMA,
    )
    op.create_unique_constraint(
        "uq_exporter_profile_pan", "exporter_profile", ["pan"], schema=SCHEMA
    )
    op.create_index(
        "ix_exporter_profile_marker", "exporter_profile", ["marker"], schema=SCHEMA
    )

    # ── 3. GSTINs: several per company, duplicates across companies allowed ──
    op.create_table(
        "exporter_gstin",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gstin", sa.String(15), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_exporter_gstin"),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            [f"{SCHEMA}.exporter_profile.customer_id"],
            name="fk_exporter_gstin_customer_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("customer_id", "gstin", name="uq_exporter_gstin_customer_gstin"),
        sa.CheckConstraint(f"gstin ~ '{GSTIN_PATTERN}'", name="ck_exporter_gstin_format"),
        schema=SCHEMA,
    )
    # Not unique: a GSTIN held by two companies is a warning, not an error.
    op.create_index("ix_exporter_gstin_gstin", "exporter_gstin", ["gstin"], schema=SCHEMA)

    # ── 4. Real links to the company ─────────────────────────────────────────
    for table in _LINKED:
        op.create_foreign_key(
            f"fk_{table}_customer_id",
            table,
            "exporter_profile",
            ["customer_id"],
            ["customer_id"],
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    # Lossy: rows emptied by upgrade() are not restored, and only each
    # company's first GSTIN survives the move back to a single column.
    for table in _LINKED:
        op.drop_constraint(f"fk_{table}_customer_id", table, type_="foreignkey", schema=SCHEMA)

    op.add_column("exporter_profile", sa.Column("gstin", sa.String(15)), schema=SCHEMA)
    op.execute(
        f"""
        UPDATE {SCHEMA}.exporter_profile p
        SET gstin = g.gstin
        FROM (
            SELECT DISTINCT ON (customer_id) customer_id, gstin
            FROM {SCHEMA}.exporter_gstin
            ORDER BY customer_id, created_at, gstin
        ) g
        WHERE g.customer_id = p.customer_id
        """
    )
    op.drop_index("ix_exporter_gstin_gstin", table_name="exporter_gstin", schema=SCHEMA)
    op.drop_table("exporter_gstin", schema=SCHEMA)

    op.drop_index("ix_exporter_profile_marker", table_name="exporter_profile", schema=SCHEMA)
    op.drop_constraint("uq_exporter_profile_pan", "exporter_profile", type_="unique", schema=SCHEMA)
    for name in (
        "ck_exporter_profile_marker_reason",
        "ck_exporter_profile_cin_format",
        "ck_exporter_profile_pan_format",
        "ck_exporter_profile_country_format",
        "ck_exporter_profile_name_not_blank",
    ):
        op.drop_constraint(name, "exporter_profile", type_="check", schema=SCHEMA)
    for column in ("marker_reason", "marker", "cin", "country", "name"):
        op.drop_column("exporter_profile", column, schema=SCHEMA)
    marker_enum.drop(op.get_bind(), checkfirst=False)
