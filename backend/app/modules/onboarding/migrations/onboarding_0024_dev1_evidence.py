"""Evidence on screening answers (plan P2-1b) — **owner: Developer 1** (allocation §3,
task 1.2).

Revision ID: onboarding_0024_dev1_evidence
Revises: onboarding_0023_dev1_foundation

``onboarding_0024_dev1_evidence`` is 29 characters, inside the register's 32-character
limit.

What it adds
------------
* ``screening_review_item.evidence_refs`` — ``jsonb NOT NULL DEFAULT '[]'``: what a
  checklist answer rests on, in the verification result's ``{type, ref}`` shape
  (``document`` or ``url``). Optional on every answer (IQ-14).
* ``ck_screening_review_item_evidence_refs_array`` — always a JSON array.

``screening_review_item`` is append-only (``trg_screening_review_item_append_only``,
``public.prevent_mutation()`` on ``UPDATE``/``DELETE``). ``ADD COLUMN … DEFAULT`` is DDL:
it fills the existing rows without firing that trigger, so no decision already on
record is updated — every earlier answer simply reads as "no evidence".

Downgrade drops the check and the column. **Lossy:** every evidence reference recorded
on a screening answer since this migration is lost.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0024_dev1_evidence"
down_revision: str | None = "onboarding_0023_dev1_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
SCREENING = "screening_review_item"


def upgrade() -> None:
    op.add_column(
        SCREENING,
        sa.Column(
            "evidence_refs",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_screening_review_item_evidence_refs_array",
        SCREENING,
        "jsonb_typeof(evidence_refs) = 'array'",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_screening_review_item_evidence_refs_array", SCREENING, schema=SCHEMA, type_="check"
    )
    op.drop_column(SCREENING, "evidence_refs", schema=SCHEMA)
