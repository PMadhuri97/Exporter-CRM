"""Who is working on a company: its relationship manager and its background-check reviewer.

Revision ID: onboarding_0044_assignment
Revises: onboarding_0043_identity_type

Why
---
``exporter_profile.relationship_manager_user_id`` has existed since 0009 and nothing
wrote it. It now names the company's relationship manager (an active OPERATIONS user),
written only by ``ExporterProfileService.assign_relationship_manager``. "My companies",
"Unassigned" and bulk reassignment all filter on it, hence the partial index.

A background check had no named reviewer: the review is a gauge state, not a row. Two
current-value columns carry who holds it and since when, written only by
``BackgroundCheckService`` (the gauge's single writer). The trail of every claim,
assignment, release and end is in the shared history log
(``background_check_assignment``), so there is no assignment table.

Schema
------
* ``ix_exporter_profile_rm_user`` — partial index on ``relationship_manager_user_id``.
* ``background_check_reviewer_id`` (``varchar(255)``, the codebase's actor-id type) and
  ``background_check_reviewer_assigned_at``, both nullable.
* ``ck_exporter_profile_reviewer_assigned_at`` — both set or both null.
* ``ck_exporter_profile_reviewer_under_review`` — a reviewer only while the check is
  ``IN_REVIEW`` or ``MORE_INFO``, so a missed clear cannot leave a reviewer on a decided
  company.
* ``ix_exporter_profile_reviewer`` — partial index for "My reviews".

``ck_background_check_proposal_resolution_who`` is relaxed. It said "a withdrawal is by
the proposer, and an approval or rejection never is". A compliance lead may now withdraw
a proposal whose proposer has left, so it says only the second half: the proposer never
approves or rejects their own proposal. Who may withdraw (the proposer, ADMIN, or a
holder of ``compliance:assign``) is the service's rule.

Data
----
Nothing is backfilled. The legacy free-text ``relationship_manager`` is matched to users
by the separate backfill command, with a dry run first.

Rollback
--------
The downgrade drops the columns and indexes and restores the stricter CHECK. It fails if
a resolution withdrawn by someone other than its proposer exists, which is correct: that
row could not have been written under the old rule.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "onboarding_0044_assignment"
down_revision: str | None = "onboarding_0043_identity_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
TABLE = "exporter_profile"


def upgrade() -> None:
    op.create_index(
        "ix_exporter_profile_rm_user",
        TABLE,
        ["relationship_manager_user_id"],
        schema=SCHEMA,
        postgresql_where=sa.text("relationship_manager_user_id IS NOT NULL"),
    )
    op.add_column(
        TABLE,
        sa.Column("background_check_reviewer_id", sa.String(length=255), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column(
            "background_check_reviewer_assigned_at", sa.DateTime(timezone=True), nullable=True
        ),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_exporter_profile_reviewer_assigned_at",
        TABLE,
        "(background_check_reviewer_id IS NULL) = (background_check_reviewer_assigned_at IS NULL)",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_exporter_profile_reviewer_under_review",
        TABLE,
        "background_check_reviewer_id IS NULL "
        "OR background_check IN ('IN_REVIEW', 'MORE_INFO')",
        schema=SCHEMA,
    )
    op.create_index(
        "ix_exporter_profile_reviewer",
        TABLE,
        ["background_check_reviewer_id"],
        schema=SCHEMA,
        postgresql_where=sa.text("background_check_reviewer_id IS NOT NULL"),
    )

    op.drop_constraint(
        "ck_background_check_proposal_resolution_who",
        "background_check_proposal_resolution",
        schema=SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_background_check_proposal_resolution_who",
        "background_check_proposal_resolution",
        "outcome = 'WITHDRAWN' OR created_by <> proposed_by",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_background_check_proposal_resolution_who",
        "background_check_proposal_resolution",
        schema=SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_background_check_proposal_resolution_who",
        "background_check_proposal_resolution",
        "(outcome = 'WITHDRAWN') = (created_by = proposed_by)",
        schema=SCHEMA,
    )
    op.drop_index("ix_exporter_profile_reviewer", table_name=TABLE, schema=SCHEMA)
    op.drop_constraint(
        "ck_exporter_profile_reviewer_under_review", TABLE, schema=SCHEMA, type_="check"
    )
    op.drop_constraint(
        "ck_exporter_profile_reviewer_assigned_at", TABLE, schema=SCHEMA, type_="check"
    )
    op.drop_column(TABLE, "background_check_reviewer_assigned_at", schema=SCHEMA)
    op.drop_column(TABLE, "background_check_reviewer_id", schema=SCHEMA)
    op.drop_index("ix_exporter_profile_rm_user", table_name=TABLE, schema=SCHEMA)
