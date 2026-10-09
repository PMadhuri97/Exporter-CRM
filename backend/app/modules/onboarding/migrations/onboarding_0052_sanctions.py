"""Structured sanctions screening: the lists, the runs, the hits and their dispositions

* ``sanctions_list`` — the lists administrators keep under Settings → Sanctions lists.
  Versioned like payment terms: an edit (including recording a new version date of the
  list itself) writes the next version and supersedes the old one. Seeded, active and
  mandatory: the UN Security Council Consolidated List and India's MHA / UAPA list.
* ``sanctions_run`` — one screening of one subject (the company, a director or a
  beneficial owner): who, when, by which provider, the search terms, the check cycle,
  and the SANCTIONS verification result it fed.
* ``sanctions_run_list`` — each list a run covered, with the version date used.
* ``sanctions_hit`` — a possible match on one list. Append-only.
* ``sanctions_disposition`` — what a person decided about a hit: OPEN,
  FALSE_POSITIVE, TRUE_MATCH_PROPOSED (awaiting a second officer), TRUE_MATCH or
  ESCALATED, with the reason, who and when. Append-only: a changed decision is a new
  row that supersedes the previous one (one successor each).

Revision ID: onboarding_0052_sanctions
Revises: onboarding_0051_company_groups
Create Date: 2026-10-09
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0052_sanctions"
down_revision: str | None = "onboarding_0051_company_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
SUBJECTS = ("COMPANY", "DIRECTOR", "UBO")
DISPOSITIONS = ("OPEN", "FALSE_POSITIVE", "TRUE_MATCH_PROPOSED", "TRUE_MATCH", "ESCALATED")
SEED = (
    (
        "UN_SC",
        "UN Security Council Consolidated List",
        "United Nations Security Council",
    ),
    (
        "IN_MHA_UAPA",
        "India MHA / UAPA designated list",
        "Ministry of Home Affairs, Government of India",
    ),
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def _id() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True)


def _stamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    ]


def _append_only(table: str) -> None:
    op.execute(
        f"""
        CREATE TRIGGER trg_{table}_append_only
        BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
        FOR EACH ROW
        EXECUTE FUNCTION public.prevent_mutation();
        """
    )


def upgrade() -> None:
    op.create_table(
        "sanctions_list",
        _id(),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("authority", sa.String(length=200), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("mandatory", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("list_version_date", sa.Date(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        *_stamps(),
        sa.UniqueConstraint("code", "version", name="uq_sanctions_list_code_version"),
        sa.CheckConstraint("code ~ '^[A-Z0-9_]+$'", name="ck_sanctions_list_code"),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_sanctions_list_current_code",
        "sanctions_list",
        ["code"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("is_current"),
    )
    table = sa.table(
        "sanctions_list",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("version", sa.Integer),
        sa.column("name", sa.String),
        sa.column("authority", sa.String),
        sa.column("mandatory", sa.Boolean),
        sa.column("list_version_date", sa.Date),
        sa.column("created_by", sa.String),
        schema=SCHEMA,
    )
    op.bulk_insert(
        table,
        [
            {
                "id": uuid.uuid4(),
                "code": code,
                "version": 1,
                "name": name,
                "authority": authority,
                "mandatory": True,
                "list_version_date": date(2026, 10, 9),
                "created_by": "seed",
            }
            for code, name, authority in SEED
        ],
    )

    op.create_table(
        "sanctions_run",
        _id(),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("subject_name", sa.String(length=255), nullable=False),
        #: The beneficial-owner record screened, for a UBO subject.
        sa.Column("subject_reference", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cycle_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("performed_by", sa.String(length=255), nullable=False),
        sa.Column("performed_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False, server_default="MANUAL"),
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
        sa.Column(
            "search_terms",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("note", sa.Text(), nullable=True),
        *_stamps(),
        sa.ForeignKeyConstraint(
            ["company_id"],
            [f"{SCHEMA}.exporter_profile.customer_id"],
            name="fk_sanctions_run_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cycle_id"], [f"{SCHEMA}.check_cycle.id"], name="fk_sanctions_run_cycle"
        ),
        sa.CheckConstraint(_in("subject_type", SUBJECTS), name="ck_sanctions_run_subject_type"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_sanctions_run_company", "sanctions_run", ["company_id", "performed_at"], schema=SCHEMA
    )
    _append_only("sanctions_run")

    op.create_table(
        "sanctions_run_list",
        _id(),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("list_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("list_version_date", sa.Date(), nullable=False),
        *_stamps(),
        sa.ForeignKeyConstraint(["run_id"], [f"{SCHEMA}.sanctions_run.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["list_id"], [f"{SCHEMA}.sanctions_list.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("run_id", "code", name="uq_sanctions_run_list_code"),
        schema=SCHEMA,
    )
    _append_only("sanctions_run_list")

    op.create_table(
        "sanctions_hit",
        _id(),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("list_code", sa.String(length=40), nullable=False),
        sa.Column("matched_name", sa.String(length=255), nullable=False),
        sa.Column("list_entry_id", sa.String(length=100), nullable=True),
        sa.Column("score", sa.Numeric(5, 2), nullable=True),
        *_stamps(),
        sa.ForeignKeyConstraint(["run_id"], [f"{SCHEMA}.sanctions_run.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="ck_sanctions_hit_score"),
        schema=SCHEMA,
    )
    op.create_index("ix_sanctions_hit_run", "sanctions_hit", ["run_id"], schema=SCHEMA)
    _append_only("sanctions_hit")

    op.create_table(
        "sanctions_disposition",
        _id(),
        sa.Column("hit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("disposition", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(length=255), nullable=False),
        sa.Column("decided_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        #: The second officer who confirmed a true match.
        sa.Column("approved_by", sa.String(length=255), nullable=True),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_stamps(),
        sa.ForeignKeyConstraint(["hit_id"], [f"{SCHEMA}.sanctions_hit.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["supersedes_id"], [f"{SCHEMA}.sanctions_disposition.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("supersedes_id", name="uq_sanctions_disposition_supersedes"),
        sa.CheckConstraint(_in("disposition", DISPOSITIONS), name="ck_sanctions_disposition_value"),
        sa.CheckConstraint(
            "disposition = 'OPEN' OR (reason IS NOT NULL AND length(btrim(reason)) > 0)",
            name="ck_sanctions_disposition_reason",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_sanctions_disposition_hit", "sanctions_disposition", ["hit_id"], schema=SCHEMA
    )
    # One first decision per hit: every later one names the decision it replaces.
    op.create_index(
        "uq_sanctions_disposition_first",
        "sanctions_disposition",
        ["hit_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("supersedes_id IS NULL"),
    )
    _append_only("sanctions_disposition")


def downgrade() -> None:
    for table in ("sanctions_disposition", "sanctions_hit", "sanctions_run_list", "sanctions_run"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {SCHEMA}.{table};")
    op.drop_table("sanctions_disposition", schema=SCHEMA)
    op.drop_table("sanctions_hit", schema=SCHEMA)
    op.drop_table("sanctions_run_list", schema=SCHEMA)
    op.drop_table("sanctions_run", schema=SCHEMA)
    op.drop_index("uq_sanctions_list_current_code", "sanctions_list", schema=SCHEMA)
    op.drop_table("sanctions_list", schema=SCHEMA)
