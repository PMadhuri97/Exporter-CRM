"""Engagement: the conversation gauge, its check-back date, and the follow-up
completion table (L3-03, L3-04).

Revision ID: onboarding_0016_engagement
Revises: onboarding_0020_retire_lifecycle

Numbered 0016 per the migration register, and parented on 0020 because 0020 is
the head when this is written: 0014, 0017 and 0020 have landed and Developer 4's
0015 has not. Numbers are labels, not order — ``down_revision`` is the order
(register §2). Developer 3B's 0018 then parents onto this revision and 0019 onto
0018; if 3B somehow merges first, **3B re-parents**, because the rule puts
re-parenting on the later merger, and whoever does it tells Developer 1 to update
the register.

``onboarding_0016_engagement`` is 26 characters, inside the register's 32-character
limit on ``alembic_version.version_num``.

What it adds, all in the ``onboarding`` schema:

* ``exporter_conversation_enum`` — the six architecture §3.3 values.
* ``exporter_profile.conversation`` — the gauge's current value, ``NOT NULL
  DEFAULT 'NOT_CONTACTED'``. This is the field
  ``docs/contracts/company-record.md`` §2.4 reserves for Developer 3; it is a
  column on Developer 2's table, so **this migration needs Developer 2's review**
  (architecture §8.1). Nothing else in ``exporter_profile`` is Developer 3's.
* ``exporter_profile.conversation_check_back_on`` — ``DATE NULL``, the date a
  ``NOT_NOW`` conversation is to be picked up again
  (``docs/contracts/engagement.md`` §4). Named in that contract before Phase 2
  started, because Phase 2's Follow-ups list reads it.
* ``follow_up_completion`` — append-only, with real links to the activity and the
  company. **Phase 1 creates it and writes no code against it**; Phase 2 fills
  it (phase agreement §6.2 says why the table is still Phase 1's to create). Its
  columns are the ones ``engagement.md`` §5.2 fixes.

**Both enums are created in the ordinary transactional body**, never with
``ALTER TYPE ... ADD VALUE`` in an autocommit block — the register calls that out
by name as something that has broken this repository before, and
``onboarding_0012_risk_critical`` is the pattern followed here.

**No foreign key is re-added for contacts or activities.** 0014 already created
``fk_exporter_contact_customer_id`` and ``fk_exporter_activity_customer_id`` (its
``_LINKED`` tuple, step 4). L3-02 declares them on the ORM entities, where the
docstrings previously claimed the opposite, and adds the direct-SQL test; it adds
no DDL, because there is nothing left to add.

The ``CHECK`` on the check-back date is the invariant, not a convenience: a
check-back date may exist **exactly** when the conversation is ``NOT_NOW``. A
stale date on a company that has since moved to ``READY_NOW`` would put it on
Phase 2's Follow-ups list for a conversation that is over. Same shape, and the
same reasoning, as ``ck_exporter_profile_marker_reason``. Every existing row
satisfies it, since the default is ``NOT_CONTACTED`` with no date, which is why
this can be added to a populated table in one statement.

Downgrade drops everything this adds, **including every follow-up completion
row** — that is lossy, and a completion is an append-only record of work someone
did, so downgrade only if you mean it. The conversation values already recorded
in ``exporter_lifecycle_history`` survive, because that table stores them as
strings and this migration does not touch it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0016_engagement"
down_revision: str | None = "onboarding_0020_retire_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"

#: The six conversation values (architecture §3.3, engagement contract §1).
CONVERSATION_VALUES = (
    "NOT_CONTACTED",
    "REACHING_OUT",
    "SPOKE_TO_THEM",
    "INTERESTED",
    "NOT_NOW",
    "READY_NOW",
)

#: How a follow-up was dealt with (engagement contract §5.3). Phase 2's
#: `FollowUpOutcome` maps to this type; Phase 1 creates the type and no Python
#: enum, because `engagement_enums.py` is Phase 1's file and the phase agreement
#: gives no file to both phases.
FOLLOW_UP_OUTCOMES = ("DONE", "NO_ANSWER", "RESCHEDULED", "CANCELLED")

conversation_enum = postgresql.ENUM(
    *CONVERSATION_VALUES, name="exporter_conversation_enum", schema=SCHEMA, create_type=False
)
follow_up_outcome_enum = postgresql.ENUM(
    *FOLLOW_UP_OUTCOMES, name="follow_up_outcome_enum", schema=SCHEMA, create_type=False
)
_ENUMS = (conversation_enum, follow_up_outcome_enum)

#: The invariant behind the check-back date (engagement contract §2.3): a date
#: exactly when the conversation is `NOT_NOW`, and never otherwise.
_CHECK_BACK_CONSTRAINT = (
    "(conversation = 'NOT_NOW' AND conversation_check_back_on IS NOT NULL)"
    " OR (conversation <> 'NOT_NOW' AND conversation_check_back_on IS NULL)"
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in _ENUMS:
        enum_type.create(bind, checkfirst=False)

    # ── 1. The gauge on the company record (Developer 2 reviews) ─────────────
    op.add_column(
        "exporter_profile",
        sa.Column("conversation", conversation_enum, nullable=False, server_default="NOT_CONTACTED"),
        schema=SCHEMA,
    )
    op.add_column(
        "exporter_profile",
        sa.Column("conversation_check_back_on", sa.Date(), nullable=True),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_exporter_profile_conversation_check_back",
        "exporter_profile",
        _CHECK_BACK_CONSTRAINT,
        schema=SCHEMA,
    )
    # Beside `ix_exporter_profile_journey` and `ix_exporter_profile_qualification`
    # (0017): the company list filters on the gauge, and §3.8 keeps the current
    # value on the record precisely so that needs no join.
    op.create_index(
        "ix_exporter_profile_conversation", "exporter_profile", ["conversation"], schema=SCHEMA
    )
    # Partial, because a check-back date is set on a small minority of companies
    # and Phase 2's Follow-ups list asks only for those: "whose check-back is due".
    op.create_index(
        "ix_exporter_profile_conversation_check_back",
        "exporter_profile",
        ["conversation_check_back_on"],
        schema=SCHEMA,
        postgresql_where=sa.text("conversation_check_back_on IS NOT NULL"),
    )

    # ── 2. Follow-up completion — created here, filled by Phase 2 ───────────
    #
    # Append-only, with real links both ways. `customer_id` is denormalised from
    # the activity deliberately (contract §5.2): one company's completions then
    # need no join, and the FK keeps it honest.
    op.create_table(
        "follow_up_completion",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("activity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outcome", follow_up_outcome_enum, nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.String(255), nullable=True),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_follow_up_completion"),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            [f"{SCHEMA}.exporter_activity.id"],
            name="fk_follow_up_completion_activity_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            [f"{SCHEMA}.exporter_profile.customer_id"],
            name="fk_follow_up_completion_customer_id",
            ondelete="RESTRICT",
        ),
        # One completion per follow-up. A reschedule is a *new* activity — the
        # activity table is append-only and nothing may move a `due_at` — so
        # nothing legitimate completes the same activity twice.
        sa.UniqueConstraint("activity_id", name="uq_follow_up_completion_activity_id"),
        sa.CheckConstraint(
            "(outcome = 'RESCHEDULED' AND next_due_at IS NOT NULL)"
            " OR (outcome <> 'RESCHEDULED' AND next_due_at IS NULL)",
            name="ck_follow_up_completion_next_due",
        ),
        schema=SCHEMA,
    )
    # One company's completions, newest first. `created_at` is transaction time,
    # so `id` breaks the tie and the order is deterministic rather than
    # chronological — the same caveat `exporter_lifecycle_history`'s indexes carry.
    op.create_index(
        "ix_follow_up_completion_customer_recent",
        "follow_up_completion",
        ["customer_id", sa.text("completed_at DESC"), sa.text("id DESC")],
        schema=SCHEMA,
    )
    # No index on `activity_id`: the unique constraint above already provides
    # one, and a second would be dead weight on an append-only table.

    # Locked by the same shared guard every other append-only table in this
    # repository uses. Phase 1 proves this with a direct-SQL test that has no ORM
    # entity to go through, so Phase 2 inherits a table it already knows is safe.
    op.execute(
        f"CREATE TRIGGER trg_follow_up_completion_append_only "
        f"BEFORE UPDATE OR DELETE ON {SCHEMA}.follow_up_completion "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.prevent_mutation();"
    )


def downgrade() -> None:
    # Lossy: every follow-up completion row goes, and a completion is an
    # append-only record that someone did the work. Downgrade only if you mean
    # it. Conversation values already in `exporter_lifecycle_history` survive —
    # that table stores them as strings and is not touched here.
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_follow_up_completion_append_only "
        f"ON {SCHEMA}.follow_up_completion"
    )
    op.drop_table("follow_up_completion", schema=SCHEMA)

    op.drop_index(
        "ix_exporter_profile_conversation_check_back",
        table_name="exporter_profile",
        schema=SCHEMA,
    )
    op.drop_index("ix_exporter_profile_conversation", table_name="exporter_profile", schema=SCHEMA)
    op.drop_constraint(
        "ck_exporter_profile_conversation_check_back",
        "exporter_profile",
        type_="check",
        schema=SCHEMA,
    )
    op.drop_column("exporter_profile", "conversation_check_back_on", schema=SCHEMA)
    op.drop_column("exporter_profile", "conversation", schema=SCHEMA)

    bind = op.get_bind()
    for enum_type in reversed(_ENUMS):
        enum_type.drop(bind, checkfirst=False)
