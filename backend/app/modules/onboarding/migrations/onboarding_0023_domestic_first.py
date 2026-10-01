"""Domestic-first qualification: export evidence stops being required, and the
export-only rejection reasons retire (P1-1, P1-2).

The first phase of the product is domestic trade — a buyer and a seller, no trade
corridors — so a company with no IEC and no export track record must be able to
qualify. Two criteria stand in the way today, both seeded by
``onboarding_0017_qualification`` at version 1 with ``required = true``:
``export_history`` and ``export_licence``.

**Criteria are versioned, never edited.** ``qualification_criterion`` is append-only
(``trg_qualification_criterion_append_only``) and keyed ``(key, version)``, so this
inserts **version 2** of each with ``required = false`` and changes nothing else.
Results already recorded keep pointing at version 1, which is the whole reason the
table works this way.

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
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "onboarding_0023_domestic_first"
down_revision: str | None = "onboarding_0022_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

#: Recognisable in `created_by` so these rows are never mistaken for an
#: administrator's edit in the criteria screen's version history.
MIGRATION_ACTOR = "migration:onboarding_0023_domestic_first"

#: The two criteria that stop being required, with the v1 values copied forward.
#: Both are `YES_NO`, so comparison, threshold, unit and allowed_values stay NULL.
_RELAXED = (
    ("export_history", "Has an export track record"),
    ("export_licence", "Holds an export licence (IEC)"),
)

#: Rejection reasons that assume export (IQ-12). Deactivated, not deleted: a past
#: outcome's JSONB still names them, and they can come back with decision F.
_RETIRED_REASON_CODES = (
    "no_export_history",
    "no_export_licence",
    "geography_not_supported",
)

_APPEND_ONLY_TRIGGER = "trg_qualification_criterion_append_only"


def upgrade() -> None:
    criterion = sa.table(
        "qualification_criterion",
        sa.column("id", sa.dialects.postgresql.UUID(as_uuid=True)),
        sa.column("key"),
        sa.column("version"),
        sa.column("label"),
        sa.column("kind"),
        sa.column("required"),
        sa.column("active"),
        sa.column("created_by"),
        schema=SCHEMA,
    )
    # Version 2 of each: identical to version 1 but no longer required. Inserted
    # rather than updated — the table is append-only by design.
    op.bulk_insert(
        criterion,
        [
            {
                "id": uuid.uuid4(),
                "key": key,
                "version": 2,
                "label": label,
                "kind": "YES_NO",
                "required": False,
                "active": True,
                "created_by": MIGRATION_ACTOR,
            }
            for key, label in _RELAXED
        ],
    )

    op.execute(
        sa.text(
            f"UPDATE {SCHEMA}.qualification_reason_code "
            "SET active = false, updated_at = now() "
            "WHERE code = ANY(:codes)"
        ).bindparams(sa.bindparam("codes", value=list(_RETIRED_REASON_CODES)))
    )


def downgrade() -> None:
    """Remove the version-2 rows and bring the three reason codes back.

    The append-only trigger refuses ``DELETE`` — that is its job, and nothing in the
    application can reach past it. A migration is the one place where undoing a data
    change is legitimate, so the trigger is lifted for exactly that statement and
    restored immediately. Alembic runs this inside a transaction, so a failure
    anywhere leaves the table protected.

    Deleting version 2 is safe: a result recorded against it would hold a foreign key
    and the delete would be refused, which is the outcome we want rather than silent
    data loss.
    """
    op.execute(
        f"ALTER TABLE {SCHEMA}.qualification_criterion "
        f"DISABLE TRIGGER {_APPEND_ONLY_TRIGGER}"
    )
    try:
        op.execute(
            sa.text(
                f"DELETE FROM {SCHEMA}.qualification_criterion "
                "WHERE version = 2 AND key = ANY(:keys)"
            ).bindparams(
                sa.bindparam("keys", value=[key for key, _ in _RELAXED])
            )
        )
    finally:
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
