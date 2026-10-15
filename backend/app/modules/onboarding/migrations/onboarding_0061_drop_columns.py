"""Drop the five columns the CRM retired, and the trigger that guarded two of them.

Revision ID: onboarding_0061_drop_columns
Revises: onboarding_0060_drop_tables

Why
---
The release with 0060 stopped mapping these columns (declared on their tables, left out
of the ORM by ``exclude_properties``), so no instance of it names them; the release
before it still inserted ``NULL`` into them, which is why they outlived 0060:

* ``exporter_profile.relationship_manager`` — the free-text owner. A company's RM is
  ``relationship_manager_user_id``; ``backfill_relationship_managers`` matched each name
  it could to a user, and the names it could not are discarded (decided 14 October
  2026).
* ``exporter_gstin.address`` — the branch's free-text address; ``convert_gst_addresses``
  turned each into a linked company address.
* ``verification_result.reviewed_by`` and ``review_status`` — the review chain
  (``verification_review``, 0021) is the one record of a review; 0021 copied every
  earlier verdict into it. ``trg_verification_result_field_immutability`` (0006) guards
  only these two and goes with them.
* ``verification_result.evidence_reference`` — never written; evidence is
  ``evidence_refs``.

``prevent_reviewed_verification_outcome_change()`` (0021) read ``OLD.review_status`` as
"reviewed the old way". It is rewritten first to read the review chain alone, so the
outcome freeze holds without the column; the guard below proves no result depends on
the old reading.

Guards
------
Nothing is dropped while it still holds something that exists nowhere else. The
revision **refuses**, listing every reason at once and changing nothing, while:

* a result has a legacy ``review_status`` and no review in the chain, or any
  ``evidence_reference`` is set;
* a GST branch has address text and no linked address (run ``convert_gst_addresses``
  from the release with 0060);
* a company with no RM has RM text naming exactly one active OPERATIONS account — a
  name ``backfill_relationship_managers`` would still match (run it from the release
  with 0060). A name it cannot match is dropped, as decided; the count is printed.

Data
----
None is moved. Take a ``pg_dump -Fc`` first: the RM names nobody matched exist only in
it afterwards.

Rollback
--------
The downgrade re-adds the five columns **empty** and restores the trigger and the old
function. What the columns held comes back only from the dump.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0061_drop_columns"
down_revision: str | None = "onboarding_0060_drop_tables"
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

#: The outcome freeze; ``{reviewed}`` is what counts as "has been reviewed".
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


def upgrade() -> None:
    bind = op.get_bind()

    failures = []
    for reason, query in GUARDS:
        count = int(bind.execute(sa.text(query)).scalar() or 0)
        if count:
            failures.append(f"{count} {reason}")
    if failures:
        raise RuntimeError(
            "onboarding_0061 refuses, so nothing is dropped and nothing was changed: "
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
            f"onboarding_0061: {discarded} company(ies) with no RM lose RM text no account "
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


def downgrade() -> None:
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
