"""Domestic-first qualification: export evidence stops being required, and the
export-only rejection reasons retire (P1-1, P1-2).

The first phase of the product is domestic trade — a buyer and a seller, no trade
corridors — so a company with no IEC and no export track record must be able to
qualify. Two criteria stand in the way today, both seeded by
``onboarding_0017_qualification`` at version 1 with ``required = true``:
``export_history`` and ``export_licence``.

**Criteria are versioned, never edited.** ``qualification_criterion`` is append-only
(``trg_qualification_criterion_append_only``) and keyed ``(key, version)``, so this
inserts **the next version** of each — a copy of the current one with
``required = false`` and nothing else changed. Results already recorded keep pointing
at the version they were judged against, which is the whole reason the table works
this way.

The next version is read from the table, not assumed to be 2: an ADMIN can version a
criterion from the criteria screen, so a live database may already hold a version 2
(the insert would then fail on ``uq_qualification_criterion_key_version``), and
copying the current row keeps whatever label or ``active`` flag that ADMIN chose. A
criterion whose current version is already not required gets no new row.

``revenue`` and ``deal_size`` are deliberately untouched. Their thresholds stay in
USD (BQ-1, answered 1 October), so their existing results keep counting.

**Release note — the de-count.** After this runs, existing ``export_history`` and
``export_licence`` results **stop counting towards the suggestion**, because
``_suggest()`` looks only at criteria that are *active and required*. Two consequences,
both intended:

* a company already ``QUALIFIED`` is unaffected — qualification is final (assumption
  A2) and nothing recalculates it;
* an **undecided lead re-suggests**: it may now read ``QUALIFIED`` where it read
  ``NOT_QUALIFIED`` before, which is exactly the point.

The three export-only rejection reasons retire at the same time (IQ-12), so no new
decision can cite a reason that assumes export. ``qualification_reason_code`` carries
no append-only trigger, and an outcome stores its codes as JSONB **strings** rather
than foreign keys, so deactivating them leaves every past outcome rendering unchanged
while ``QualificationService`` refuses them on new ones. They can be reactivated if
export returns (decision F).

**Rollback.** ``pg_dump`` first. The downgrade removes only the rows this migration
inserted, and is refused (foreign key) once any result has been recorded against
them — after first use, rolling back means restoring the dump.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "onboarding_0031_domestic_first"
down_revision: str | None = "onboarding_0030_deal_req_docs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

#: Recognisable in `created_by` so these rows are never mistaken for an
#: administrator's edit in the criteria screen's version history — and so the
#: downgrade removes exactly these rows and nothing an ADMIN added.
MIGRATION_ACTOR = "migration:onboarding_0031_domestic_first"

#: The two criteria that stop being required.
_RELAXED = ("export_history", "export_licence")

#: Rejection reasons that assume export (IQ-12). Deactivated, not deleted: a past
#: outcome's JSONB still names them, and they can come back with decision F.
_RETIRED_REASON_CODES = (
    "no_export_history",
    "no_export_licence",
    "geography_not_supported",
)

_APPEND_ONLY_TRIGGER = "trg_qualification_criterion_append_only"

#: The next version of each relaxed criterion, copied from its current version with
#: `required` off; nothing for a criterion that is already not required. Inserted
#: rather than updated — the table is append-only by design. Module-level so the
#: test runs this exact statement.
INSERT_NEXT_VERSIONS = sa.text(
    f"""
    INSERT INTO {SCHEMA}.qualification_criterion
        (id, key, version, label, kind, comparison, threshold, unit,
         allowed_values, required, active, created_by)
    SELECT gen_random_uuid(), c.key, c.version + 1, c.label, c.kind,
           c.comparison, c.threshold, c.unit, c.allowed_values,
           false, c.active, :actor
    FROM {SCHEMA}.qualification_criterion AS c
    WHERE c.key = ANY(:keys)
      AND c.required
      AND c.version = (
          SELECT max(latest.version)
          FROM {SCHEMA}.qualification_criterion AS latest
          WHERE latest.key = c.key
      )
    """
).bindparams(
    sa.bindparam("keys", value=list(_RELAXED)),
    sa.bindparam("actor", value=MIGRATION_ACTOR),
)


def upgrade() -> None:
    op.execute(INSERT_NEXT_VERSIONS)

    op.execute(
        sa.text(
            f"UPDATE {SCHEMA}.qualification_reason_code "
            "SET active = false, updated_at = now() "
            "WHERE code = ANY(:codes)"
        ).bindparams(sa.bindparam("codes", value=list(_RETIRED_REASON_CODES)))
    )


def downgrade() -> None:
    """Remove the rows this migration inserted and bring the three reason codes back.

    The append-only trigger refuses ``DELETE`` — that is its job, and nothing in the
    application can reach past it. A migration is the one place where undoing a data
    change is legitimate, so the trigger is lifted for exactly that statement and
    restored immediately. Alembic runs this inside one transaction, so a failure
    rolls the trigger change back with everything else and the table stays protected.

    A result recorded against one of these rows holds a foreign key to it, so the
    delete is refused rather than losing data — restore the ``pg_dump`` instead.
    """
    op.execute(
        f"ALTER TABLE {SCHEMA}.qualification_criterion "
        f"DISABLE TRIGGER {_APPEND_ONLY_TRIGGER}"
    )
    op.execute(
        sa.text(
            f"DELETE FROM {SCHEMA}.qualification_criterion "
            "WHERE created_by = :actor AND key = ANY(:keys)"
        ).bindparams(
            sa.bindparam("actor", value=MIGRATION_ACTOR),
            sa.bindparam("keys", value=list(_RELAXED)),
        )
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.qualification_criterion "
        f"ENABLE TRIGGER {_APPEND_ONLY_TRIGGER}"
    )

    op.execute(
        sa.text(
            f"UPDATE {SCHEMA}.qualification_reason_code "
            "SET active = true, updated_at = now() "
            "WHERE code = ANY(:codes)"
        ).bindparams(sa.bindparam("codes", value=list(_RETIRED_REASON_CODES)))
    )
