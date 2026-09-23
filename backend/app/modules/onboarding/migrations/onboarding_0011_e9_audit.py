"""E9: stop destroying compliance decisions, and start recording lifecycle changes.

Two changes, both about the same thing — a decision someone took is currently
either overwritten or never written down at all.

**1. `screening_review_item` becomes an append-only decision log.**

`onboarding_0010_screen_review` gave it a `UniqueConstraint(customer_id,
item_key)`, so a second decision on the same checklist item could only be
recorded by overwriting the first. Marking an item `PASSED` erased that it had
ever been `FAILED`, and erased who failed it and when — on a compliance
checklist, which is precisely the record an auditor asks for.

The constraint goes, and the table gets the same guard twenty other tables in
this schema already carry: `BEFORE UPDATE OR DELETE`, `FOR EACH STATEMENT`,
`public.prevent_mutation()`. Copied from `onboarding.onboarding_event`
(`onboarding_0002_orchestration_schema.py:313-319`) and
`onboarding.exporter_activity` (`onboarding_0005_exporter_crm.py:215-220`), no
variant.

`ScreeningReviewService.list_review_items` compensates with `DISTINCT ON
(item_key) ... ORDER BY item_key, created_at DESC, id DESC`, so
`GET /screening-review` still returns one row per `item_key` — the current
state — with its response schema untouched.

`ix_screening_review_customer_item_recent` serves that read. Dropping the unique
constraint drops the index that backed it, and without a replacement every
checklist read degrades to a sequential scan. Its column order and direction
mirror the query exactly so Postgres satisfies the ordering from the index
instead of sorting. `id DESC` is the tie-break: `created_at` defaults to
`now()`, which is transaction time, so two decisions written in one transaction
share a timestamp and would otherwise order non-deterministically.

The entity stays on `AnerModel`, not `AppendOnlyModel`, even though the rows are
now append-only: `AppendOnlyModel` uses `CreatedOnlyMixin`, which has no
`updated_at`, and `ScreeningReviewItemResponse` declares `updated_at` as
required. Dropping the column would be an API response change. `updated_at` now
always equals `created_at`.

**2. `exporter_lifecycle_history` is new.**

`ExporterProfileService.transition_lifecycle_status` validated the edge, wrote
`lifecycle_status`, and logged a line to stdout. `actor_id` was accepted as a
parameter and persisted nowhere. Who moved an exporter to `ONBOARDED`, and when,
survived only as long as the log retention.

The obvious fix was to reuse `onboarding_event`, which this service already
holds a repository for. **It cannot carry this.**
`onboarding_event.onboarding_request_id` is `NOT NULL` with an FK to
`onboarding_request`, and an `ExporterProfile` does not require an
`OnboardingRequest`: `create_or_get_profile` — the path behind
`POST /onboarding/exporters`, the primary way a profile is created — makes a
profile and no request at all. Only `create_lead` makes both. Measured against
this database at the time of writing: 13 of 20 exporter profiles have no
onboarding request. Writing lifecycle transitions to `onboarding_event` would
therefore raise `IntegrityError` for most exporters, or — if guarded with "write
it only when a request happens to exist" — silently skip the audit record for
exactly the sales-entered leads that most need one. Relaxing that FK is not a
local change: `onboarding_event` is shared, and `list_by_request` /
`find_transition` both assume a request is always present.

So: a dedicated table, shaped after `exporter_activity` (same schema, same
`AppendOnlyModel` base, same bare indexed `customer_id` with no formal FK, same
shared trigger) rather than a new pattern.

It carries `from_status`, `to_status`, `actor_id` and a JSONB `event_metadata`.
That last one is deliberate: ANER-4.2-S1T2 needs a completion hook on the
`COMPLIANCE_REVIEW -> ONBOARDED` edge, and Epic 4.1 does not have one. A
consumer polling `to_status = ONBOARDED` on this table is that hook, which is
why `ix_exporter_lifecycle_history_to_status` exists — without it that consumer
sequential-scans the whole history on every poll.

No `ALTER TYPE` in this migration, so no `autocommit_block()` and none of the
split-state risk that comes with it (`migrations/README.md`, item 2).
`screening_review_item.status` was `String(32)` from the start, not an enum, and
`exporter_lifecycle_history` stores its statuses as plain strings for the same
reason: a lifecycle status added to `ExporterLifecycleStatus` must never require
a second migration against a history table before it can be recorded.

Revision ID: onboarding_0011_e9_audit
Revises: onboarding_0010_screen_review
Create Date: 2026-09-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0011_e9_audit"
down_revision: str | None = "onboarding_0010_screen_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
REVIEW_TABLE = "screening_review_item"
HISTORY_TABLE = "exporter_lifecycle_history"


def upgrade() -> None:
    # ── 1. screening_review_item becomes append-only ──────────────────────
    op.drop_constraint(
        "uq_screening_review_customer_item", REVIEW_TABLE, schema=SCHEMA, type_="unique"
    )

    op.create_index(
        "ix_screening_review_customer_item_recent",
        REVIEW_TABLE,
        ["customer_id", "item_key", sa.text("created_at DESC"), sa.text("id DESC")],
        schema=SCHEMA,
    )

    op.execute(f"""
    CREATE TRIGGER trg_screening_review_item_append_only
    BEFORE UPDATE OR DELETE ON {SCHEMA}.{REVIEW_TABLE}
    FOR EACH STATEMENT
    EXECUTE FUNCTION public.prevent_mutation();
    """)

    # ── 2. exporter_lifecycle_history ─────────────────────────────────────
    op.create_table(
        HISTORY_TABLE,
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("from_status", sa.String(length=64), nullable=False),
        sa.Column("to_status", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("event_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_exporter_lifecycle_history_customer_id",
        HISTORY_TABLE,
        ["customer_id"],
        schema=SCHEMA,
    )
    # Serves one exporter's history, newest first, from the index.
    op.create_index(
        "ix_exporter_lifecycle_history_recent",
        HISTORY_TABLE,
        ["customer_id", sa.text("created_at DESC"), sa.text("id DESC")],
        schema=SCHEMA,
    )
    # Serves the ANER-4.2-S1T2 completion hook: a consumer polling for
    # COMPLIANCE_REVIEW -> ONBOARDED, which would otherwise scan the table.
    op.create_index(
        "ix_exporter_lifecycle_history_to_status",
        HISTORY_TABLE,
        ["to_status", sa.text("created_at DESC")],
        schema=SCHEMA,
    )

    op.execute(f"""
    CREATE TRIGGER trg_exporter_lifecycle_history_append_only
    BEFORE UPDATE OR DELETE ON {SCHEMA}.{HISTORY_TABLE}
    FOR EACH STATEMENT
    EXECUTE FUNCTION public.prevent_mutation();
    """)


def downgrade() -> None:
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_exporter_lifecycle_history_append_only "
        f"ON {SCHEMA}.{HISTORY_TABLE};"
    )
    op.drop_index(
        "ix_exporter_lifecycle_history_to_status", table_name=HISTORY_TABLE, schema=SCHEMA
    )
    op.drop_index(
        "ix_exporter_lifecycle_history_recent", table_name=HISTORY_TABLE, schema=SCHEMA
    )
    op.drop_index(
        "ix_exporter_lifecycle_history_customer_id", table_name=HISTORY_TABLE, schema=SCHEMA
    )
    op.drop_table(HISTORY_TABLE, schema=SCHEMA)

    op.execute(
        f"DROP TRIGGER IF EXISTS trg_screening_review_item_append_only "
        f"ON {SCHEMA}.{REVIEW_TABLE};"
    )
    op.drop_index(
        "ix_screening_review_customer_item_recent", table_name=REVIEW_TABLE, schema=SCHEMA
    )

    # Restoring the unique constraint requires the duplicates this migration
    # exists to permit to be gone first. Collapsing to the most recent decision
    # per (customer_id, item_key) is the only reversal that preserves the
    # current state the API reports; the superseded decisions are discarded,
    # which is exactly the data loss the upgrade was written to stop. Downgrade
    # only if you mean it.
    op.execute(f"""
    DELETE FROM {SCHEMA}.{REVIEW_TABLE} a
    USING {SCHEMA}.{REVIEW_TABLE} b
    WHERE a.customer_id = b.customer_id
      AND a.item_key = b.item_key
      AND (a.created_at, a.id) < (b.created_at, b.id);
    """)

    op.create_unique_constraint(
        "uq_screening_review_customer_item",
        REVIEW_TABLE,
        ["customer_id", "item_key"],
        schema=SCHEMA,
    )
