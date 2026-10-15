"""Drop what the CRM retired: two tables, five columns and one trigger.

Revision ID: onboarding_0060_drop_retired
Revises: onboarding_0059_deal_reference

Why
---
The release before this one stopped reading and writing each of these, and kept them
in the database only so that an instance of the release before it, still running
during the deploy, never met a missing column. One release later they go:

* ``qualification_reason_code`` — the reasons are served from code
  (``domain/qualification_reason_codes.py``); only migrations ever changed the table.
* ``bank_activity_finding`` — nothing writes it, and no bank feed is planned.
* ``verification_result.reviewed_by`` and ``review_status`` — the review chain
  (``verification_review``, 0021) is the one record of a review; 0021 copied every
  earlier verdict into it. ``trg_verification_result_field_immutability`` (0006) guards
  only these two and goes with them.
* ``verification_result.evidence_reference`` — never written; evidence is
  ``evidence_refs``.
* ``exporter_profile.relationship_manager`` — the free-text owner. A company's RM is
  ``relationship_manager_user_id``; ``backfill_relationship_managers`` matched each name
  it could to a user, and the names it could not are discarded (decided 14 October
  2026).
* ``exporter_gstin.address`` — the branch's free-text address;
  ``convert_gst_addresses`` turned each into a linked company address.

``prevent_reviewed_verification_outcome_change()`` (0021) read ``OLD.review_status`` as
"reviewed the old way". It is rewritten first to read the review chain alone, so the
outcome freeze holds without the column; the guard below proves no result depends on
the old reading.

Guards
------
Nothing is dropped while it still holds something that exists nowhere else. The
revision **refuses**, listing every reason at once, while:

* ``bank_activity_finding`` holds a row;
* a result has a legacy ``review_status`` and no review in the chain, or any
  ``evidence_reference`` is set;
* a GST branch has address text and no linked address (run ``convert_gst_addresses``
  from the release before this one);
* a company with no RM has RM text naming exactly one active OPERATIONS account —
  a name ``backfill_relationship_managers`` would still match (run it from the release
  before this one). A name it cannot match is dropped, as decided; the count is printed.

Data
----
None is moved. Take a ``pg_dump -Fc`` first: the RM names nobody matched exist only in
it afterwards.

Rollback
--------
The downgrade recreates both tables as they were (the reason codes re-seeded with the
nine rows 0017 and 0031 left), re-adds the five columns **empty**, restores the trigger
and the old function. What the columns held comes back only from the dump.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0060_drop_retired"
down_revision: str | None = "onboarding_0059_deal_reference"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"


def _normalised(column: str) -> str:
    """The backfill's comparison: trimmed, inner whitespace collapsed, case-folded."""
    return rf"lower(regexp_replace(btrim({column}), '\s+', ' ', 'g'))"


_UNMATCHED_RM = """
    p.relationship_manager_user_id IS NULL
    AND NULLIF(btrim(p.relationship_manager), '') IS NOT NULL
"""

#: (why the revision refuses, the query counting the rows that make it refuse)
GUARDS: tuple[tuple[str, str], ...] = (
    (
        "bank_activity_finding holds rows",
        f"SELECT count(*) FROM {SCHEMA}.bank_activity_finding",
    ),
    (
        "verification results carry a legacy review_status with no review in the chain",
        f"""
        SELECT count(*) FROM {SCHEMA}.verification_result r
         WHERE r.review_status IS NOT NULL
           AND NOT EXISTS (
               SELECT 1 FROM {SCHEMA}.verification_review v
                WHERE v.verification_result_id = r.id)
        """,
    ),
    (
        "verification results carry an evidence_reference",
        f"SELECT count(*) FROM {SCHEMA}.verification_result WHERE evidence_reference IS NOT NULL",
    ),
    (
        "GST branches have address text and no linked address (run convert_gst_addresses)",
        f"""
        SELECT count(*) FROM {SCHEMA}.exporter_gstin
         WHERE NULLIF(btrim(address), '') IS NOT NULL AND address_id IS NULL
        """,
    ),
    (
        "companies with no RM have RM text naming exactly one active OPERATIONS account "
        "(run backfill_relationship_managers)",
        f"""
        SELECT count(*) FROM {SCHEMA}.exporter_profile p
         WHERE {_UNMATCHED_RM}
           AND (SELECT count(*) FROM auth.users u
                 WHERE u.is_active AND u.role = 'OPERATIONS'
                   AND {_normalised('u.full_name')} = {_normalised('p.relationship_manager')}
               ) = 1
        """,
    ),
)

#: The outcome freeze, reading the review chain alone.
_FREEZE_BODY = """
    BEGIN
        IF (NEW.status IS DISTINCT FROM OLD.status
            OR NEW.risk_level IS DISTINCT FROM OLD.risk_level
            OR NEW.normalized_result IS DISTINCT FROM OLD.normalized_result
            OR NEW.valid_until IS DISTINCT FROM OLD.valid_until)
           AND {reviewed}
        THEN
            RAISE EXCEPTION
                'verification_result % has been reviewed: status, risk_level, '
                'normalized_result and valid_until can no longer change', OLD.id;
        END IF;
        RETURN NEW;
    END;
"""
_REVIEW_EXISTS = f"""EXISTS (
                SELECT 1 FROM {SCHEMA}.verification_review rv
                WHERE rv.verification_result_id = OLD.id
            )"""


def _replace_freeze(reviewed: str) -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.prevent_reviewed_verification_outcome_change()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        {_FREEZE_BODY.format(reviewed=reviewed)}
        $$;
        """
    )


#: The reason codes as migrations 0017 and 0031 left them: (code, label, requires_note,
#: active). Written out, not imported: a downgrade restores what this revision dropped.
REASON_CODES: tuple[tuple[str, str, bool, bool], ...] = (
    ("deal_size_out_of_range", "Deal size outside our range", False, True),
    ("geography_not_supported", "Trade corridor we do not serve", False, False),
    ("industry_not_supported", "Industry we do not finance", False, True),
    ("insufficient_information", "Not enough information to qualify", False, True),
    ("no_export_history", "No export track record", False, False),
    ("no_export_licence", "No export licence", False, False),
    ("other", "Other (explain in the note)", True, True),
    ("revenue_below_threshold", "Revenue below the threshold", False, True),
    ("years_in_business_below_threshold", "Too few years in business", False, True),
)


def upgrade() -> None:
    bind = op.get_bind()

    failures = []
    for reason, query in GUARDS:
        count = int(bind.execute(sa.text(query)).scalar() or 0)
        if count:
            failures.append(f"{count} {reason}")
    if failures:
        raise RuntimeError(
            "onboarding_0060 refuses, so nothing is dropped and nothing was changed: "
            + "; ".join(failures)
            + ". Deal with each, then upgrade again."
        )

    discarded = int(
        bind.execute(
            sa.text(f"SELECT count(*) FROM {SCHEMA}.exporter_profile p WHERE {_UNMATCHED_RM}")
        ).scalar()
        or 0
    )
    if discarded:
        print(
            f"onboarding_0060: {discarded} company(ies) with no RM lose RM text no account "
            "matches, as decided; the pg_dump taken before this upgrade still holds it."
        )

    # The freeze first: it must not read a column about to go.
    _replace_freeze(_REVIEW_EXISTS)
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_verification_result_field_immutability "
        f"ON {SCHEMA}.verification_result"
    )
    for column in ("reviewed_by", "review_status", "evidence_reference"):
        op.drop_column("verification_result", column, schema=SCHEMA)
    op.drop_column("exporter_profile", "relationship_manager", schema=SCHEMA)
    op.drop_column("exporter_gstin", "address", schema=SCHEMA)

    op.drop_table("bank_activity_finding", schema=SCHEMA)
    op.drop_table("qualification_reason_code", schema=SCHEMA)


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    reason_codes = op.create_table(
        "qualification_reason_code",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        *_timestamps(),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("requires_note", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("id", name="pk_qualification_reason_code"),
        sa.UniqueConstraint("code", name="uq_qualification_reason_code_code"),
        schema=SCHEMA,
    )
    op.execute(
        reason_codes.insert().values(
            [
                {
                    "id": sa.text("gen_random_uuid()"),
                    "code": code,
                    "label": label,
                    "requires_note": requires_note,
                    "active": active,
                }
                for code, label, requires_note, active in REASON_CODES
            ]
        )
    )

    op.create_table(
        "bank_activity_finding",
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("finding_type", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(32), nullable=False, server_default=sa.text("'REVIEW'")),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'OPEN'")),
        sa.Column("provider_reference", sa.String(255), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="bank_activity_finding_pkey"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_bank_activity_finding_customer_id", "bank_activity_finding", ["customer_id"], schema=SCHEMA
    )
    op.create_index(
        "ix_bank_activity_finding_customer_status",
        "bank_activity_finding",
        ["customer_id", "status"],
        schema=SCHEMA,
    )

    op.add_column("exporter_gstin", sa.Column("address", sa.Text(), nullable=True), schema=SCHEMA)
    op.add_column(
        "exporter_profile",
        sa.Column("relationship_manager", sa.String(255), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "verification_result",
        sa.Column("evidence_reference", sa.String(1024), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "verification_result",
        sa.Column("reviewed_by", sa.String(255), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "verification_result",
        sa.Column(
            "review_status",
            postgresql.ENUM(name="verification_review_status_enum", schema=SCHEMA, create_type=False),
            nullable=True,
        ),
        schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_verification_result_field_immutability
        BEFORE UPDATE ON {SCHEMA}.verification_result
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.prevent_field_mutation_when_set('reviewed_by', 'review_status');
        """
    )
    _replace_freeze(f"(OLD.review_status IS NOT NULL\n                OR {_REVIEW_EXISTS})")
