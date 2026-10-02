"""Superseding verification reviews, the reviewed-outcome freeze, evidence and
subject snapshots on verification results, and the screening status check —
**owner: Developer 4B** (``docs/contracts/verification-and-screening.md``).

Revision ID: onboarding_0021_verif_review
Revises: auth_0004_rbac

``onboarding_0021_verif_review`` is 28 characters, inside the register's 32-character
limit on ``alembic_version.version_num``. 0021 is the next free label after 0020 so
Dev4A's ``onboarding_0015_bg_check`` and this file never share a filename; both
branches start from the same head, and whichever merges second re-parents its own
``down_revision`` onto the other (a one-line change, never a merge revision).

What it adds, all in the ``onboarding`` schema
-----------------------------------------------
* ``verification_review`` — one row per review of a verification result, append-only
  (``trg_verification_review_append_only`` → ``public.prevent_mutation()``). A later
  review **supersedes** the current one by naming it in ``supersedes_review_id``;
  nothing is ever edited. The database keeps it one chain per result:

  - ``uq_verification_review_supersedes`` — a review is superseded at most once, so two
    concurrent reviewers naming the same head cannot fork the chain;
  - ``uq_verification_review_first`` (partial, ``WHERE supersedes_review_id IS NULL``)
    — one first review per result, so two concurrent *first* reviews cannot both land;
  - ``fk_verification_review_supersedes`` — a composite FK onto
    ``(id, verification_result_id)``, so a review can only supersede a review **of the
    same result**;
  - ``ck_verification_review_not_self`` and ``ck_verification_review_supersede_note``
    (a superseding review states why).

  ``review_status`` reuses the existing ``verification_review_status_enum``; no enum is
  created or altered. ``reviewed_at`` defaults to the database clock.
* **Copy of existing reviews.** Every result whose legacy ``review_status`` is set gets
  that review as its first ``verification_review`` row, so there is one source of
  "latest". Legacy storage never recorded a review time, so ``reviewed_at`` is the
  result's ``updated_at`` — the closest stored fact — and the copied row's ``note`` says
  so. The legacy columns and ``trg_verification_result_field_immutability`` are **kept**
  untouched; nothing writes the legacy columns after this migration.
* ``trg_verification_result_outcome_freeze`` → the new
  ``onboarding.prevent_reviewed_verification_outcome_change()``: once a result has any
  review (a ``verification_review`` row, or a legacy ``review_status``), ``UPDATE`` of
  ``status``, ``risk_level``, ``normalized_result`` or ``valid_until`` is refused.
  ``prevent_field_mutation_when_set()`` does not fit — these columns are set from the
  start; what freezes them is a row in another table — hence a new function.
* Evidence (contract §3): ``evidence_note`` and ``evidence_refs`` (a JSON array of
  ``{type, ref}``, the qualification contract's shape) on ``verification_result``.
* Subject snapshot (contract §6): ``subject_snapshot`` — a buyer's identity as it was when the
  check was recorded.
* ``trg_verification_result_input_immutability`` — the evidence and the snapshot are
  facts about the moment of recording, frozen once set, through the existing
  ``onboarding.prevent_field_mutation_when_set()``.
* ``ck_verification_result_evidence_refs_array`` — ``evidence_refs`` is always an array.
* ``ix_verification_result_entity_recent`` — one subject's results newest first, the
  order the reader and the list route use; ``ix_verification_review_result`` — one
  result's reviews.
* ``ck_screening_review_item_status`` — a screening decision's status is one of
  ``NEEDS_REVIEW``, ``PASSED``, ``FAILED``, ``EXEMPT``; until now only the API's
  ``Literal`` said so. ``trg_screening_review_item_append_only`` is untouched.

Nothing here touches the background check (Dev4A), its gauge, decisions or risk.

A narrow race the trigger alone does not close: a raw-SQL ``UPDATE`` of a result racing
a raw-SQL review ``INSERT`` in another uncommitted transaction can pass the ``EXISTS``
check. The service closes it by taking the result row ``FOR UPDATE`` on both paths (poll
and review); the trigger is the backstop for everything that does not come through it.

Downgrade — **lossy**
---------------------
Drops the review table, the triggers, the new function, the three new columns, the
checks and the indexes. Before dropping the table, each result's current review (the
chain head) is written back into the legacy ``reviewed_by`` / ``review_status`` where
those are still empty — which the legacy immutability trigger allows — so the current
verdict survives. **Lost:** every superseded review, every review note, every review
time, all evidence notes and references, and all subject snapshots. Downgrade only if
you mean it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0021_verif_review"
# Re-parented when `main` was merged in. Written against `onboarding_0019_documents`,
# which Dev4A's `onboarding_0015_bg_check` took as its parent first, followed on `main`
# by `auth_0003_user_admin` and `auth_0004_rbac`; this merged second, so it moves onto
# the head (`migration-register.md` §2). Nothing here depends on the background check or auth
# schema — the parent only fixes where it sits in the order.
down_revision: str | None = "auth_0004_rbac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
RESULT = "verification_result"
REVIEW = "verification_review"
SCREENING = "screening_review_item"

SCREENING_STATUSES = ("NEEDS_REVIEW", "PASSED", "FAILED", "EXEMPT")

#: The existing type, created by onboarding_0006_verif_result. Never created or
#: altered here.
review_status_enum = postgresql.ENUM(
    "ACCEPTED",
    "REJECTED",
    "ESCALATED",
    name="verification_review_status_enum",
    schema=SCHEMA,
    create_type=False,
)

LEGACY_REVIEW_NOTE = (
    "Copied from verification_result.review_status by migration "
    "onboarding_0021_verif_review. The legacy column recorded no review time; "
    "reviewed_at is the result's updated_at at migration time."
)


def upgrade() -> None:
    # ── Evidence and subject snapshot on verification_result ────────────────
    op.add_column(RESULT, sa.Column("evidence_note", sa.Text(), nullable=True), schema=SCHEMA)
    op.add_column(
        RESULT,
        sa.Column(
            "evidence_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema=SCHEMA,
    )
    op.add_column(
        RESULT,
        sa.Column("subject_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_verification_result_evidence_refs_array",
        RESULT,
        "jsonb_typeof(evidence_refs) = 'array'",
        schema=SCHEMA,
    )
    op.create_index(
        "ix_verification_result_entity_recent",
        RESULT,
        [
            "entity_type",
            "entity_reference",
            sa.text("performed_at DESC"),
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
        schema=SCHEMA,
    )

    # ── The review table ─────────────────────────────────────────────────────
    op.create_table(
        REVIEW,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("verification_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_status", review_status_enum, nullable=False),
        sa.Column("reviewed_by", sa.String(length=255), nullable=False),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("supersedes_review_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["verification_result_id"],
            [f"{SCHEMA}.{RESULT}.id"],
            name="fk_verification_review_result_id",
            ondelete="RESTRICT",
        ),
        # The composite target the supersedes FK needs.
        sa.UniqueConstraint("id", "verification_result_id", name="uq_verification_review_id_result"),
        sa.UniqueConstraint("supersedes_review_id", name="uq_verification_review_supersedes"),
        sa.CheckConstraint(
            "supersedes_review_id IS NULL OR supersedes_review_id <> id",
            name="ck_verification_review_not_self",
        ),
        sa.CheckConstraint(
            "supersedes_review_id IS NULL OR (note IS NOT NULL AND btrim(note) <> '')",
            name="ck_verification_review_supersede_note",
        ),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_verification_review_supersedes",
        REVIEW,
        REVIEW,
        ["supersedes_review_id", "verification_result_id"],
        ["id", "verification_result_id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_index(
        "uq_verification_review_first",
        REVIEW,
        ["verification_result_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("supersedes_review_id IS NULL"),
    )
    op.create_index(
        "ix_verification_review_result",
        REVIEW,
        ["verification_result_id", sa.text("created_at DESC"), sa.text("id DESC")],
        schema=SCHEMA,
    )

    # Copy existing reviews before the append-only trigger exists (it would not
    # matter — INSERT is allowed — but the order reads as "data, then guard").
    op.execute(
        sa.text(
            f"""
            INSERT INTO {SCHEMA}.{REVIEW}
                (id, created_at, verification_result_id, review_status, reviewed_by,
                 reviewed_at, note, supersedes_review_id)
            SELECT gen_random_uuid(), now(), r.id, r.review_status,
                   COALESCE(r.reviewed_by, 'unknown (pre-0021)'),
                   r.updated_at, :note, NULL
            FROM {SCHEMA}.{RESULT} r
            WHERE r.review_status IS NOT NULL
            """
        ).bindparams(note=LEGACY_REVIEW_NOTE)
    )

    op.execute(
        f"""
        CREATE TRIGGER trg_verification_review_append_only
        BEFORE UPDATE OR DELETE ON {SCHEMA}.{REVIEW}
        FOR EACH STATEMENT
        EXECUTE FUNCTION public.prevent_mutation();
        """
    )

    # ── Reviewed outcome freeze (contract §2) ───────────────────────────────────────
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.prevent_reviewed_verification_outcome_change()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF (NEW.status IS DISTINCT FROM OLD.status
                OR NEW.risk_level IS DISTINCT FROM OLD.risk_level
                OR NEW.normalized_result IS DISTINCT FROM OLD.normalized_result
                OR NEW.valid_until IS DISTINCT FROM OLD.valid_until)
               AND (OLD.review_status IS NOT NULL
                    OR EXISTS (
                        SELECT 1 FROM {SCHEMA}.{REVIEW} rv
                        WHERE rv.verification_result_id = OLD.id
                    ))
            THEN
                RAISE EXCEPTION
                    'verification_result % has been reviewed: status, risk_level, '
                    'normalized_result and valid_until can no longer change', OLD.id;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_verification_result_outcome_freeze
        BEFORE UPDATE ON {SCHEMA}.{RESULT}
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.prevent_reviewed_verification_outcome_change();
        """
    )
    # Evidence and snapshot are facts about the moment of recording.
    op.execute(
        f"""
        CREATE TRIGGER trg_verification_result_input_immutability
        BEFORE UPDATE ON {SCHEMA}.{RESULT}
        FOR EACH ROW
        EXECUTE FUNCTION {SCHEMA}.prevent_field_mutation_when_set(
            'evidence_note', 'evidence_refs', 'subject_snapshot'
        );
        """
    )

    # ── Screening status (contract §5) ──────────────────────────────────────────────
    op.create_check_constraint(
        "ck_screening_review_item_status",
        SCREENING,
        "status IN (" + ", ".join(f"'{s}'" for s in SCREENING_STATUSES) + ")",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint("ck_screening_review_item_status", SCREENING, schema=SCHEMA, type_="check")

    op.execute(
        f"DROP TRIGGER IF EXISTS trg_verification_result_input_immutability "
        f"ON {SCHEMA}.{RESULT};"
    )
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_verification_result_outcome_freeze ON {SCHEMA}.{RESULT};"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.prevent_reviewed_verification_outcome_change();")

    # Keep the current verdict: write each chain head back into the legacy columns
    # where they are still empty (null → value is what the legacy trigger allows).
    op.execute(
        f"""
        UPDATE {SCHEMA}.{RESULT} r
        SET reviewed_by = head.reviewed_by, review_status = head.review_status
        FROM {SCHEMA}.{REVIEW} head
        WHERE head.verification_result_id = r.id
          AND r.review_status IS NULL
          AND r.reviewed_by IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM {SCHEMA}.{REVIEW} later
              WHERE later.supersedes_review_id = head.id
          );
        """
    )

    op.execute(f"DROP TRIGGER IF EXISTS trg_verification_review_append_only ON {SCHEMA}.{REVIEW};")
    op.drop_index("ix_verification_review_result", table_name=REVIEW, schema=SCHEMA)
    op.drop_index("uq_verification_review_first", table_name=REVIEW, schema=SCHEMA)
    op.drop_constraint(
        "fk_verification_review_supersedes", REVIEW, schema=SCHEMA, type_="foreignkey"
    )
    op.drop_table(REVIEW, schema=SCHEMA)

    op.drop_index("ix_verification_result_entity_recent", table_name=RESULT, schema=SCHEMA)
    op.drop_constraint(
        "ck_verification_result_evidence_refs_array", RESULT, schema=SCHEMA, type_="check"
    )
    op.drop_column(RESULT, "subject_snapshot", schema=SCHEMA)
    op.drop_column(RESULT, "evidence_refs", schema=SCHEMA)
    op.drop_column(RESULT, "evidence_note", schema=SCHEMA)
