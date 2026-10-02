"""Clear expiry (plan P3-3a, decision E, BQ-5) — **owner: Developer 1** (allocation §3,
task 1.15).

Revision ID: onboarding_0027_dev1_expiry
Revises: onboarding_0026_dev1_approval

``onboarding_0027_dev1_expiry`` is 27 characters, inside the register's 32-character
limit.

What it does
------------
* **Schema.** ``background_check_decision.expires_at`` (nullable ``timestamptz``):
  when a ``CLEAR`` stops being current. ``BackgroundCheckService`` sets it on every
  new ``CLEAR`` to ``decided_at`` + the validity setting
  (``CRM_BACKGROUND_CHECK_CLEAR_VALIDITY_DAYS``, default 365), from one server
  timestamp so the two agree exactly. ``ck_background_check_decision_expiry``: only a
  ``CLEAR`` carries one, and it is after ``decided_at``.
* **Legacy decisions are never updated** (append-only, plan §17.1). A ``CLEAR``
  decision with ``expires_at IS NULL`` expires by the documented read rule
  ``decided_at + 1 year`` (BQ-5, answered 1 October 2026: "1 year from the last
  Clear"), 8,760 hours exactly — the same ``timedelta(days=365)`` the readers use.
* **Data: the current value is backfilled.** ``exporter_profile.background_check_expires_at``
  (added empty by 0023) is the company's current expiry — set on ``CLEAR``, cleared on
  any move away — and the Re-KYC due list (P3-3c) reads it through its index. The
  profile row is mutable, so every company that is ``CLEAR`` now gets its value from
  its last ``CLEAR`` decision (BQ-5): the stored ``expires_at`` if it has one, else
  the legacy rule. Idempotent: a company that already has a value is skipped.
  No other column and no other table is written; no trigger is disabled.

Before running it on a live database
------------------------------------
1. ``pg_dump`` the database (allocation §2.3).
2. **Dry run** — read-only, writes nothing, prints each company the backfill would set
   and the value::

       cd backend
       ./.venv/Scripts/python.exe -m app.modules.onboarding.migrations.onboarding_0027_dev1_expiry --dry-run

   ``alembic upgrade onboarding_0027_dev1_expiry --sql`` prints the DDL and the
   ``UPDATE`` without running them.
3. ``alembic upgrade head``; then the dry run again must report **0** companies, and
   ``VALIDATION_SQL`` (``--validate``) must report 0 CLEAR companies without an expiry.

Rollback
--------
``alembic downgrade onboarding_0026_dev1_approval`` drops ``expires_at`` from the
decisions and **sets every profile's ``background_check_expires_at`` back to NULL**
— the state before this migration, when nothing wrote it. **Lossy**: the expiry of
every ``CLEAR`` recorded after the upgrade is lost from both places (the profile
value can be recomputed by re-running the upgrade, which re-derives it by the legacy
rule, i.e. as if the validity setting were 365 days). For anything else, restore the
pre-upgrade dump.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "onboarding_0027_dev1_expiry"
down_revision: str | None = "onboarding_0026_dev1_approval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
DECISION = "background_check_decision"
PROFILE = "exporter_profile"

#: BQ-5's "1 year from the last Clear", as hours so it matches ``timedelta(days=365)``
#: whatever the session's time zone (``interval '365 days'`` is calendar days and
#: would shift by an hour across a DST change).
LEGACY_VALIDITY_SQL = "interval '8760 hours'"

def _candidates(*, stored_expiry: bool = True) -> str:
    """Each currently-CLEAR company without an expiry, its **last** CLEAR decision
    (BQ-5: "1 year from the last Clear") and the expiry the backfill would set.

    For a company the services moved, the last CLEAR decision is the chain head. Taking
    the latest CLEAR rather than requiring the head to be one also covers a company
    whose gauge and chain disagree (only a raw-SQL write can do that), instead of
    leaving it without an expiry.

    ``stored_expiry=False`` is for the dry run **before** the upgrade, when
    ``background_check_decision.expires_at`` does not exist yet (every Clear then
    expires by the legacy rule)."""
    stored = "last_clear.expires_at" if stored_expiry else "NULL::timestamptz"
    return f"""
        SELECT p.customer_id AS company_id,
               last_clear.id AS clearing_decision_id,
               last_clear.decided_at,
               COALESCE({stored}, last_clear.decided_at + {LEGACY_VALIDITY_SQL}) AS expires_at,
               {stored} IS NULL AS by_legacy_rule
        FROM {SCHEMA}.{PROFILE} p
        JOIN LATERAL (
            SELECT d.* FROM {SCHEMA}.{DECISION} d
            WHERE d.company_id = p.customer_id AND d.to_value = 'CLEAR'
            ORDER BY d.decided_at DESC, d.id DESC
            LIMIT 1
        ) AS last_clear ON true
        WHERE p.background_check = 'CLEAR'
          AND p.background_check_expires_at IS NULL
    """


def preview_sql(*, stored_expiry: bool = True) -> str:
    """The dry run: what the backfill would write. Read-only."""
    return _candidates(stored_expiry=stored_expiry) + " ORDER BY expires_at, company_id"


#: The backfill. Updates only ``exporter_profile.background_check_expires_at``, only
#: where it is NULL, so a second run changes nothing.
BACKFILL_SQL = f"""
    UPDATE {SCHEMA}.{PROFILE} AS target
    SET background_check_expires_at = candidate.expires_at
    FROM ({_candidates()}) AS candidate
    WHERE target.customer_id = candidate.company_id
"""

#: After the upgrade: CLEAR companies that still have no expiry. Must be 0.
VALIDATION_SQL = f"""
    SELECT count(*) FROM {SCHEMA}.{PROFILE}
    WHERE background_check = 'CLEAR' AND background_check_expires_at IS NULL
"""

_HAS_STORED_EXPIRY_SQL = f"""
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = '{SCHEMA}' AND table_name = '{DECISION}' AND column_name = 'expires_at'
    )
"""


def upgrade() -> None:
    op.add_column(
        DECISION,
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_background_check_decision_expiry",
        DECISION,
        "expires_at IS NULL OR (to_value = 'CLEAR' AND expires_at > decided_at)",
        schema=SCHEMA,
    )
    op.execute(sa.text(BACKFILL_SQL))


def downgrade() -> None:
    op.execute(
        sa.text(
            f"UPDATE {SCHEMA}.{PROFILE} SET background_check_expires_at = NULL "
            "WHERE background_check_expires_at IS NOT NULL"
        )
    )
    op.drop_constraint(
        "ck_background_check_decision_expiry", DECISION, schema=SCHEMA, type_="check"
    )
    op.drop_column(DECISION, "expires_at", schema=SCHEMA)


# ── Dry run / validation, outside Alembic ──────────────────────────────────────


def _main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - operator tool
    parser = argparse.ArgumentParser(
        prog="onboarding_0027_dev1_expiry",
        description="Preview (read-only) or validate the Clear-expiry backfill.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="list what the backfill would set")
    mode.add_argument(
        "--validate", action="store_true", help="count CLEAR companies with no expiry"
    )
    args = parser.parse_args(argv)

    from app.platform.configuration.config import get_settings

    engine = sa.create_engine(get_settings().DATABASE_SYNC_URL)
    with engine.connect() as connection:
        connection.execute(sa.text("SET TRANSACTION READ ONLY"))
        if args.validate:
            missing = connection.execute(sa.text(VALIDATION_SQL)).scalar_one()
            print(f"CLEAR companies without an expiry: {missing}")
            return 0 if missing == 0 else 1
        stored = bool(connection.execute(sa.text(_HAS_STORED_EXPIRY_SQL)).scalar_one())
        rows = connection.execute(sa.text(preview_sql(stored_expiry=stored))).all()
        for row in rows:
            rule = "legacy rule (decided + 1 year)" if row.by_legacy_rule else "stored"
            print(
                f"{row.company_id}  decision {row.clearing_decision_id}  "
                f"decided {row.decided_at.isoformat()}  -> expires {row.expires_at.isoformat()}"
                f"  [{rule}]"
            )
        print(f"{len(rows)} company(ies) would be set; nothing was written.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main())
