"""Backfill ``exporter_profile.created_via`` — **owner: Developer 3**
(allocation task 3.8, plan P4-1).

Revision ID: onboarding_0033_created_via
Revises: onboarding_0032_company_identity

Why
---
Migration 0032 added ``created_via`` and left it ``NULL``: a company's creation
channel was not recorded anywhere on the company itself, only in the first
history row's ``event_metadata.source`` (audit §3.1). Task 3.8 makes every create
path write the column going forward; this migration gives the companies already
on file the same answer, read from the one place that has it.

Task 3.8's ``domain/company_identity.py`` maps ``history_source`` → channel for
the live path. The ``CASE`` below is that same mapping expressed as SQL, and
``test_dev3_company_identity.py`` asserts the two agree, so a new channel added to
one and not the other fails a test rather than quietly backfilling ``NULL``.

What it does
------------
#. **Normalises** any ``created_via`` already written. F3 shipped the buyer path
   writing the lower-case ``'deal_buyer'`` before ``CreatedVia`` settled on
   upper-case names; one ``upper()`` makes both spellings read the same, and it
   is a no-op on a database where only this release has run.
#. **Backfills** from each company's **earliest creation row**. The earliest, not
   any: later rows carry ``qualification_service.record_outcome`` and
   ``background_check_service.clear``, which say how a company progressed rather
   than how it arrived. Two dimensions count as a creation row — ``journey``, which
   every company entered into the pipeline starts with, and ``pipeline``, which is
   what a buyer-only company gets *instead* (plan P4-6: a company that exists only
   because it was somebody's buyer has no journey yet, so it has no journey row to
   read). Looking only at ``journey`` would leave exactly the buyer companies
   ``DEAL_BUYER`` was added for reading ``NULL``.
#. Leaves ``NULL`` where the source is unmapped or missing, and **reports the
   count** rather than guessing ``MANUAL``: "entered by hand" is a claim about
   how a company reached us, and an unmapped channel is not evidence of it. A
   handful of such rows is expected — early seed and test data.

``identity_type`` is **not** touched: 0032 set it for every company holding a
PAN, which is the only case that can be inferred, and task 3.8 sets it on the
way in from here on.

Rollback
--------
The downgrade sets ``created_via`` back to ``NULL`` for every company. That is
lossless in the sense that matters — the history rows it was derived from are
append-only and still there, so re-running the upgrade reproduces it exactly —
but any value written by a create path *after* this migration ran is lost, so
downgrade only to re-run the backfill.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "onboarding_0033_created_via"
down_revision: str | None = "onboarding_0032_company_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

#: ``history_source`` → ``created_via``, frozen as of this migration. The live
#: mapping is ``_HISTORY_SOURCE_CHANNELS`` in ``domain/company_identity.py``; a
#: test asserts they agree. Anything unlisted stays ``NULL`` (module docstring).
_CHANNEL_BY_SOURCE: tuple[tuple[str, str], ...] = (
    ("exporter_profile_service.create_lead", "MANUAL"),
    ("exporter_profile_service.create_or_get_profile", "MANUAL"),
    ("company_import.csv", "CSV"),
    ("partner_intake.rxil", "RXIL"),
    ("company_directory.create_buyer_company", "DEAL_BUYER"),
    ("sample_data", "SAMPLE"),
)


def _case_expression() -> str:
    """The mapping as a SQL ``CASE``, built from one list so the two cannot drift."""
    whens = "\n".join(
        f"            WHEN first_source.source = '{source}' THEN '{channel}'"
        for source, channel in _CHANNEL_BY_SOURCE
    )
    return f"        CASE\n{whens}\n            ELSE NULL\n        END"


def upgrade() -> None:
    bind = op.get_bind()

    # 1. One spelling. See the module docstring: F3 wrote 'deal_buyer'.
    bind.execute(
        sa.text(
            f"UPDATE {SCHEMA}.exporter_profile "
            "SET created_via = upper(created_via) "
            "WHERE created_via IS NOT NULL AND created_via <> upper(created_via)"
        )
    )

    # 2. The backfill. `DISTINCT ON` takes each company's earliest journey row;
    #    `created_at, id` breaks a tie deterministically, because two rows written
    #    in one transaction share a timestamp.
    result = bind.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA}.exporter_profile AS p
            SET created_via = v.channel
            FROM (
                SELECT first_source.customer_id,
{_case_expression()} AS channel
                FROM (
                    SELECT DISTINCT ON (h.customer_id)
                           h.customer_id,
                           h.event_metadata->>'source' AS source
                    FROM {SCHEMA}.exporter_lifecycle_history AS h
                    WHERE h.dimension IN ('journey', 'pipeline')
                    ORDER BY h.customer_id, h.created_at, h.id
                ) AS first_source
            ) AS v
            WHERE p.customer_id = v.customer_id
              AND p.created_via IS NULL
              AND v.channel IS NOT NULL
            """
        )
    )
    filled = result.rowcount

    # 3. The report the plan asks for: how many companies this could not answer.
    unmapped = bind.execute(
        sa.text(
            f"SELECT count(*) FROM {SCHEMA}.exporter_profile WHERE created_via IS NULL"
        )
    ).scalar_one()
    print(  # noqa: T201 — a migration's report belongs on the operator's console
        f"onboarding_0033_created_via: filled {filled} companies; "
        f"{unmapped} still NULL (unmapped or missing first-history source)"
    )


def downgrade() -> None:
    op.execute(f"UPDATE {SCHEMA}.exporter_profile SET created_via = NULL")
