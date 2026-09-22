"""reconcile audit_events sink-sync objects onto databases that predate them

WHY THIS REVISION EXISTS
------------------------
AL-47 added `synced_to_sink_at`, its index, two functions and two triggers by
**editing `audit_0001_baseline` in place** rather than appending a revision.

That works for a database created afterwards: the baseline runs once and creates
the final shape. It cannot work for a database that had already applied
`audit_0001_baseline` — Alembic records that revision as done and never reruns
it, so `alembic upgrade head` is a no-op and the schema silently stays behind the
ORM. The symptom is every audit write failing with

    UndefinedColumnError: column "synced_to_sink_at" of relation
    "audit_events" does not exist

which, because almost every module writes an audit event, reads as a few hundred
unrelated test failures.

This revision is appended after the current head so it actually runs, and brings
such a database up to the shape `audit_0001_baseline` now declares.

Its parent moved from `9f8e7d6c5b4a` to `a1b2c3d4e5f6` when develop's idempotency
archive chain landed: two branches had each appended onto `9f8e7d6c5b4a`, leaving
two heads. Re-parenting rather than adding a merge revision is what
`backend/README.md` prescribes when the fork exists only on the feature branch,
and it is what keeps this revision at the tip — which is the whole point of it.

IDEMPOTENT BY CONSTRUCTION
--------------------------
On a fresh database the baseline has already created every object here, so this
revision must be a no-op there. Each statement is therefore written to converge
rather than to create: `ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`,
`CREATE OR REPLACE FUNCTION`, and `DROP TRIGGER IF EXISTS` before each
`CREATE TRIGGER`. Running it against an already-correct database changes nothing.

The DDL is copied verbatim from `audit_0001_baseline` so the two cannot drift.

WHAT IS DELIBERATELY NOT TOUCHED
--------------------------------
`public.prevent_mutation()` — the function the old `audit_events_immutable`
trigger pointed at — is shared with the compliance, ledger and onboarding
modules. Only the audit trigger is repointed; the function itself is left alone.

Revision ID: audit_0002_sink_sync_reconcile
Revises: a1b2c3d4e5f6
Create Date: 2026-08-20

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "audit_0002_sink_sync_reconcile"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "audit"


def upgrade() -> None:
    # ── Column and index ──────────────────────────────────────────────────────
    op.execute(
        f"ALTER TABLE {SCHEMA}.audit_events "
        f"ADD COLUMN IF NOT EXISTS synced_to_sink_at TIMESTAMP WITH TIME ZONE;"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_audit_events_synced_to_sink_at "
        f"ON {SCHEMA}.audit_events (synced_to_sink_at);"
    )

    # ── Functions ─────────────────────────────────────────────────────────────
    # Verbatim from audit_0001_baseline. CREATE OR REPLACE is idempotent.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.prevent_audit_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF (OLD.id IS DISTINCT FROM NEW.id) OR
                   (OLD.created_at IS DISTINCT FROM NEW.created_at) OR
                   (OLD.transaction_id IS DISTINCT FROM NEW.transaction_id) OR
                   (OLD.correlation_id IS DISTINCT FROM NEW.correlation_id) OR
                   (OLD.event_type IS DISTINCT FROM NEW.event_type) OR
                   (OLD.actor_id IS DISTINCT FROM NEW.actor_id) OR
                   (OLD.actor_type IS DISTINCT FROM NEW.actor_type) OR
                   (OLD.payload IS DISTINCT FROM NEW.payload) THEN
                    RAISE EXCEPTION 'Table audit_events is append-only: UPDATE is only allowed on synced_to_sink_at';
                END IF;
                RETURN NEW;
            ELSIF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Table audit_events is append-only: DELETE is forbidden';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.notify_audit_event()
        RETURNS trigger AS $$
        BEGIN
            NOTIFY audit_event_channel;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # ── Triggers ──────────────────────────────────────────────────────────────
    # On a pre-AL-47 database this trigger exists and points at
    # public.prevent_mutation(), which blocks *every* UPDATE and so would reject
    # the sink writing synced_to_sink_at back. Dropping and recreating repoints
    # it; the shared public function is not touched, since compliance, ledger and
    # onboarding all still use it.
    op.execute(f"DROP TRIGGER IF EXISTS audit_events_immutable ON {SCHEMA}.audit_events;")
    op.execute(
        f"""
        CREATE TRIGGER audit_events_immutable
        BEFORE UPDATE OR DELETE ON {SCHEMA}.audit_events
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.prevent_audit_event_mutation();
        """
    )

    op.execute(
        f"DROP TRIGGER IF EXISTS audit_event_notify_trigger ON {SCHEMA}.audit_events;"
    )
    op.execute(
        f"""
        CREATE TRIGGER audit_event_notify_trigger
        AFTER INSERT ON {SCHEMA}.audit_events
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.notify_audit_event();
        """
    )


def downgrade() -> None:
    """Deliberately a no-op.

    Every object this revision creates is part of the schema
    `audit_0001_baseline` now declares. On any database created after AL-47 the
    baseline owns them, so dropping them here would leave that database
    inconsistent with the revision that is supposed to define its shape — the
    mirror image of the bug this revision exists to fix.

    To remove these objects, downgrade past `audit_0001_baseline` itself.
    """
