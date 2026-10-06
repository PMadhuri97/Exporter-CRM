"""The handover snapshot: backfilled, then frozen.

Revision ID: onboarding_0029_deal_snapshot
Revises: onboarding_0028_deal_foundation

``onboarding_0029_deal_snapshot`` is 29 characters, inside the register's
32-character limit.

Why
---
Until now a handover's buyer existed only as the live ``deal_buyer`` row
(``deal_service.py``'s ``_handover_snapshot`` built a dict, announced it on the bus
and kept nothing). The history row carried ``document_ids`` and no buyer at all.
Once buyers become shared company records their details change after the handover,
so "what the lending team was given" has to be a persisted snapshot — and it is the
prerequisite for the buyer migration.

What it does
------------
1. **Backfills** every ``HANDED_OVER`` deal that has no snapshot yet, from the two
   best sources available: its ``deal_buyer`` row for the buyer, and its handover
   history row's ``event_metadata->'document_ids'`` for the paperwork. Marked
   ``snapshot_source = 'backfilled_from_deal_buyer'`` so a reader can always tell a
   reconstruction from a snapshot taken at the moment of the handover
   (``taken_at_handover``). A deal whose buyer row is gone still gets a snapshot,
   with ``buyer: null`` — an honest "we no longer know" rather than no row — and
   likewise ``document_ids: null`` for a deal with no handover history row, which
   is not the same as ``[]`` ("handed over with no paperwork").
2. **Freezes it**, by replacing ``prevent_terminal_deal_change()`` with a version
   that adds ``handover_snapshot`` under a **set-once** rule: on a terminal deal it
   may go from ``NULL`` to a value once, and never change again. Frozen outright
   would refuse this migration's own backfill and the buyer migration's; not frozen at all would
   let the record of a handover be rewritten.

The five columns 0022 froze outright (``stage``, ``handed_over_at``,
``withdrawal_reason``, ``company_id``, ``reference``) keep exactly the rule 0022
gave them. The backfill runs **before** the function is replaced, so it is governed
by 0022's version either way.

Rollback
--------
``downgrade`` restores 0022's function verbatim and then clears every snapshot it
can prove this migration wrote (``snapshot_source = 'backfilled_from_deal_buyer'``),
leaving snapshots taken at handover time alone — those are records, not migration
output. The order matters: 0022's version does not guard the column, so the clear
is only possible once it is back.

Dry run
-------
``_VALIDATION`` below carries the queries the register asks a data migration to
state. Run the first one before and after an apply: it must be non-zero before and
zero after.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "onboarding_0029_deal_snapshot"
down_revision: str | None = "onboarding_0028_deal_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

#: Run these by hand before and after an apply on a live database (register §4).
_VALIDATION = """
-- Must be 0 afterwards: every handed-over deal has a snapshot.
SELECT count(*) FROM onboarding.deal
 WHERE stage = 'HANDED_OVER' AND handover_snapshot IS NULL;

-- Must be 0: no snapshot names a buyer the deal never had.
SELECT count(*) FROM onboarding.deal d
 WHERE d.handover_snapshot -> 'buyer' ->> 'name' IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM onboarding.deal_buyer b
                    WHERE b.deal_id = d.id
                      AND b.name = d.handover_snapshot -> 'buyer' ->> 'name');

-- Informational: how many snapshots are reconstructions rather than records.
SELECT handover_snapshot ->> 'snapshot_source' AS source, count(*)
  FROM onboarding.deal WHERE handover_snapshot IS NOT NULL GROUP BY 1;

-- Informational: reconstructions whose buyer or paperwork could not be recovered.
SELECT count(*) FILTER (WHERE handover_snapshot -> 'buyer' = 'null'::jsonb) AS no_buyer,
       count(*) FILTER (WHERE handover_snapshot -> 'document_ids' = 'null'::jsonb)
           AS no_document_record
  FROM onboarding.deal
 WHERE handover_snapshot ->> 'snapshot_source' = 'backfilled_from_deal_buyer';
"""

#: 0022's five columns, frozen outright on a terminal deal, plus
#: ``handover_snapshot`` under the set-once rule.
_FREEZE_FUNCTION = """
CREATE OR REPLACE FUNCTION onboarding.prevent_terminal_deal_change()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
BEGIN
    IF OLD.stage IN ('HANDED_OVER', 'WITHDRAWN')
       AND (NEW.stage IS DISTINCT FROM OLD.stage
            OR NEW.handed_over_at IS DISTINCT FROM OLD.handed_over_at
            OR NEW.withdrawal_reason IS DISTINCT FROM OLD.withdrawal_reason
            OR NEW.company_id IS DISTINCT FROM OLD.company_id
            OR NEW.reference IS DISTINCT FROM OLD.reference)
    THEN
        RAISE EXCEPTION
            'deal % is %: a closed deal no longer changes', OLD.id, OLD.stage;
    END IF;

    -- Set once, then never again: a snapshot may be filled in for a deal handed
    -- over before snapshots existed (this migration, and the buyer
    -- migration), but what the lending team was given is never rewritten.
    IF OLD.stage IN ('HANDED_OVER', 'WITHDRAWN')
       AND OLD.handover_snapshot IS NOT NULL
       AND NEW.handover_snapshot IS DISTINCT FROM OLD.handover_snapshot
    THEN
        RAISE EXCEPTION
            'deal %: its handover snapshot is what the lending team was given and does not change',
            OLD.id;
    END IF;

    RETURN NEW;
END;
$fn$;
"""

#: 0022's function, verbatim, for the downgrade.
_FREEZE_FUNCTION_0022 = """
CREATE OR REPLACE FUNCTION onboarding.prevent_terminal_deal_change()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
BEGIN
    IF OLD.stage IN ('HANDED_OVER', 'WITHDRAWN')
       AND (NEW.stage IS DISTINCT FROM OLD.stage
            OR NEW.handed_over_at IS DISTINCT FROM OLD.handed_over_at
            OR NEW.withdrawal_reason IS DISTINCT FROM OLD.withdrawal_reason
            OR NEW.company_id IS DISTINCT FROM OLD.company_id
            OR NEW.reference IS DISTINCT FROM OLD.reference)
    THEN
        RAISE EXCEPTION
            'deal % is %: a closed deal no longer changes', OLD.id, OLD.stage;
    END IF;
    RETURN NEW;
END;
$fn$;
"""

#: The reconstruction. ``to_jsonb`` on the buyer row rather than a hand-written
#: object, minus the bookkeeping columns, so a buyer column added later lands in
#: new snapshots without this query being the place that forgot it. The whole
#: ``buyer`` key is JSON ``null`` when the row is gone — "we no longer know".
#:
#: ``document_ids`` comes from the handover history row, the only record of which
#: documents the handover rested on. A deal has exactly one such row, but the
#: correlated subquery is ordered anyway so the query is total rather than
#: accidentally right. With no such row (or one without the key) it is JSON
#: ``null``, like ``buyer``: "not recorded", never ``[]``, which would claim the
#: deal went over with no paperwork.
_BACKFILL = """
UPDATE onboarding.deal d
   SET handover_snapshot = jsonb_build_object(
           'buyer',
           (SELECT to_jsonb(b) - 'id' - 'deal_id' - 'created_at' - 'updated_at'
              FROM onboarding.deal_buyer b WHERE b.deal_id = d.id),
           'buyer_company_id', to_jsonb(d.buyer_company_id),
           'document_ids',
           (SELECT h.event_metadata -> 'document_ids'
              FROM onboarding.exporter_lifecycle_history h
             WHERE h.dimension = 'deal'
               AND h.to_status = 'HANDED_OVER'
               AND h.deal_id = d.id
             ORDER BY h.created_at DESC, h.id DESC
             LIMIT 1),
           'snapshot_source', 'backfilled_from_deal_buyer',
           'snapshot_at', to_jsonb(d.handed_over_at)
       )
 WHERE d.stage = 'HANDED_OVER'
   AND d.handover_snapshot IS NULL;
"""


def upgrade() -> None:
    # Backfill first, under 0022's function: it names five columns and not this
    # one, so the UPDATE is allowed on an already-terminal deal. The set-once
    # rule installed afterwards would allow it too — both, deliberately, so
    # neither the order nor the rule is the only thing keeping this working.
    op.execute(_BACKFILL)
    op.execute(_FREEZE_FUNCTION)


def downgrade() -> None:
    op.execute(_FREEZE_FUNCTION_0022)
    op.execute(
        """
        UPDATE onboarding.deal
           SET handover_snapshot = NULL
         WHERE handover_snapshot ->> 'snapshot_source' = 'backfilled_from_deal_buyer';
        """
    )
