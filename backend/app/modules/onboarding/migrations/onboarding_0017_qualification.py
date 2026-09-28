"""Qualification: criteria, results, outcomes — and the journey they move
(L2-09, L2-10).

Revision ID: onboarding_0017_qualification
Revises: onboarding_0014_company_record

Numbered 0017 per the migration register. Its parent is 0014 because 0015
(Dev 4) and 0016 (Dev 3) have not been written yet; whichever of them merges
after this re-parents onto it (a one-line ``down_revision`` change, register
§2), keeping one head.

What it adds, all in the ``onboarding`` schema:

* ``exporter_profile.journey`` — ``LEAD``/``PROSPECT``/``CUSTOMER``, default
  ``LEAD``. The three-stage journey qualification moves (decided by the
  programme lead for this phase: add the column now, beside the ten old
  ``lifecycle_status`` values, which L2-04 retires).
* ``exporter_profile.qualification`` — the gauge's current value, default
  ``NOT_YET_REVIEWED``.
* ``qualification_criterion`` — one **immutable** row per version of each
  criterion. Seeded with version 1 of the seven initial criteria; their
  thresholds are settings an ADMIN changes by adding a version, never code.
* ``qualification_reason_code`` — the codes a ``NOT_QUALIFIED`` outcome must
  give at least one of. Seeded.
* ``qualification_result`` and ``qualification_outcome`` — append-only.

The three versioned/decision tables use the shared ``public.prevent_mutation()``
guard every other append-only table uses, so the database itself refuses to
change a criterion version, a result or an outcome. The rules the contract
states as invariants are checks here too: a ``NOT_QUALIFIED`` outcome carries a
reason code; a ``PASS``/``FAIL`` result carries evidence; only an automated
result has a confidence, between 0 and 1; each company's outcomes form one
chain (one first outcome, and no outcome superseded twice).

Nothing here touches the screening checklist, the background check or
``verification_result``.

Downgrade drops everything this adds, results and outcomes included.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0017_qualification"
down_revision: str | None = "onboarding_0014_company_record"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"
_APPEND_ONLY = ("qualification_criterion", "qualification_result", "qualification_outcome")


def _enum(name: str, *values: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, schema=SCHEMA, create_type=False)


journey_enum = _enum("exporter_journey_enum", "LEAD", "PROSPECT", "CUSTOMER")
state_enum = _enum(
    "qualification_state_enum", "NOT_YET_REVIEWED", "QUALIFIED", "NOT_QUALIFIED"
)
kind_enum = _enum(
    "qualification_criterion_kind_enum", "NUMBER_THRESHOLD", "YES_NO", "ALLOWED_VALUES"
)
comparison_enum = _enum("qualification_threshold_comparison_enum", "AT_LEAST", "AT_MOST")
result_enum = _enum("qualification_result_value_enum", "PASS", "FAIL", "UNKNOWN")
source_enum = _enum("qualification_source_enum", "MANUAL", "IMPORT", "RXIL", "AUTOMATED")
decided_enum = _enum("qualification_decided_by_kind_enum", "MANUAL", "AUTOMATED")
outcome_enum = _enum("qualification_outcome_value_enum", "QUALIFIED", "NOT_QUALIFIED")
_ENUMS = (
    journey_enum,
    state_enum,
    kind_enum,
    comparison_enum,
    result_enum,
    source_enum,
    decided_enum,
    outcome_enum,
)

#: Version 1 of the seven initial criteria (architecture §3.3). The CEO's
#: examples — revenue of at least $100M, at least five years in business — are
#: seed values here, not rules in code.
_INDUSTRIES = [
    "Textiles", "Engineering goods", "Seafood", "Leather goods", "Spices",
    "Agriculture", "Chemicals", "Pharmaceuticals",
]
_CORRIDORS = ["IN-AE", "IN-US", "IN-GB", "IN-NL", "IN-DE", "IN-SG"]
_SEED_CRITERIA = [
    # key, label, kind, comparison, threshold, unit, allowed_values, required
    ("revenue", "Annual revenue", "NUMBER_THRESHOLD", "AT_LEAST", 100_000_000, "USD", None, True),
    ("years_in_business", "Years in business", "NUMBER_THRESHOLD", "AT_LEAST", 5, "YEARS",
     None, True),
    ("export_history", "Has an export track record", "YES_NO", None, None, None, None, True),
    ("export_licence", "Holds an export licence (IEC)", "YES_NO", None, None, None, None, True),
    ("industry", "Industry we finance", "ALLOWED_VALUES", None, None, None, _INDUSTRIES, False),
    ("geography", "Trade corridor", "ALLOWED_VALUES", None, None, None, _CORRIDORS, False),
    ("deal_size", "Typical deal size", "NUMBER_THRESHOLD", "AT_LEAST", 50_000, "USD", None,
     False),
]

#: The reason codes a NOT_QUALIFIED outcome may give (criterion-result §5.2).
_SEED_REASON_CODES = [
    ("revenue_below_threshold", "Revenue below the threshold", False),
    ("years_in_business_below_threshold", "Too few years in business", False),
    ("no_export_history", "No export track record", False),
    ("no_export_licence", "No export licence", False),
    ("industry_not_supported", "Industry we do not finance", False),
    ("geography_not_supported", "Trade corridor we do not serve", False),
    ("deal_size_out_of_range", "Deal size outside our range", False),
    ("insufficient_information", "Not enough information to qualify", False),
    ("other", "Other (explain in the note)", True),
]


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in _ENUMS:
        enum_type.create(bind, checkfirst=False)

    # ── The journey and the gauge on the company record ─────────────────────
    op.add_column(
        "exporter_profile",
        sa.Column("journey", journey_enum, nullable=False, server_default="LEAD"),
        schema=SCHEMA,
    )
    op.add_column(
        "exporter_profile",
        sa.Column("qualification", state_enum, nullable=False, server_default="NOT_YET_REVIEWED"),
        schema=SCHEMA,
    )
    op.create_index("ix_exporter_profile_journey", "exporter_profile", ["journey"], schema=SCHEMA)
    op.create_index(
        "ix_exporter_profile_qualification", "exporter_profile", ["qualification"], schema=SCHEMA
    )

    # ── Criteria: one immutable row per version ─────────────────────────────
    op.create_table(
        "qualification_criterion",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("kind", kind_enum, nullable=False),
        sa.Column("comparison", comparison_enum, nullable=True),
        sa.Column("threshold", sa.Numeric(20, 4), nullable=True),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("allowed_values", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_qualification_criterion"),
        sa.UniqueConstraint("key", "version", name="uq_qualification_criterion_key_version"),
        sa.CheckConstraint("key ~ '^[a-z][a-z0-9_]*$'", name="ck_qualification_criterion_key"),
        sa.CheckConstraint("version >= 1", name="ck_qualification_criterion_version"),
        sa.CheckConstraint(
            "(kind = 'NUMBER_THRESHOLD' AND comparison IS NOT NULL AND threshold IS NOT NULL "
            " AND allowed_values IS NULL)"
            " OR (kind = 'YES_NO' AND comparison IS NULL AND threshold IS NULL "
            " AND allowed_values IS NULL)"
            " OR (kind = 'ALLOWED_VALUES' AND comparison IS NULL AND threshold IS NULL "
            " AND jsonb_typeof(allowed_values) = 'array' AND jsonb_array_length(allowed_values) > 0)",
            name="ck_qualification_criterion_kind_shape",
        ),
        schema=SCHEMA,
    )

    # ── Reason codes ─────────────────────────────────────────────────────────
    op.create_table(
        "qualification_reason_code",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("requires_note", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id", name="pk_qualification_reason_code"),
        sa.UniqueConstraint("code", name="uq_qualification_reason_code_code"),
        schema=SCHEMA,
    )

    # ── Results ──────────────────────────────────────────────────────────────
    op.create_table(
        "qualification_result",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("criterion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("result", result_enum, nullable=False),
        sa.Column("observed_value", sa.Text(), nullable=True),
        sa.Column("source", source_enum, nullable=False),
        sa.Column("decided_by_kind", decided_enum, nullable=False),
        sa.Column("evidence_note", sa.Text(), nullable=True),
        sa.Column(
            "evidence_refs", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("recorded_by", sa.String(255), nullable=True),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_qualification_result"),
        sa.ForeignKeyConstraint(
            ["customer_id"], [f"{SCHEMA}.exporter_profile.customer_id"],
            name="fk_qualification_result_customer_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["criterion_id"], [f"{SCHEMA}.qualification_criterion.id"],
            name="fk_qualification_result_criterion_id", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "result = 'UNKNOWN' OR btrim(coalesce(evidence_note, '')) <> '' "
            "OR jsonb_array_length(evidence_refs) > 0",
            name="ck_qualification_result_evidence",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (decided_by_kind = 'AUTOMATED' "
            "AND confidence >= 0 AND confidence <= 1)",
            name="ck_qualification_result_confidence",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_qualification_result_customer_recent",
        "qualification_result",
        ["customer_id", sa.text("recorded_at DESC"), sa.text("id DESC")],
        schema=SCHEMA,
    )

    # ── Outcomes: one chain per company ──────────────────────────────────────
    op.create_table(
        "qualification_outcome",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outcome", outcome_enum, nullable=False),
        sa.Column(
            "reason_codes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("suggested_outcome", outcome_enum, nullable=False),
        sa.Column("result_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("source", source_enum, nullable=False),
        sa.Column("decided_by_kind", decided_enum, nullable=False),
        sa.Column("supersedes_outcome_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_by", sa.String(255), nullable=True),
        sa.Column(
            "decided_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_qualification_outcome"),
        sa.ForeignKeyConstraint(
            ["customer_id"], [f"{SCHEMA}.exporter_profile.customer_id"],
            name="fk_qualification_outcome_customer_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_outcome_id"], [f"{SCHEMA}.qualification_outcome.id"],
            name="fk_qualification_outcome_supersedes", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "supersedes_outcome_id", name="uq_qualification_outcome_supersedes_once"
        ),
        sa.CheckConstraint(
            "outcome = 'QUALIFIED' OR jsonb_array_length(reason_codes) >= 1",
            name="ck_qualification_outcome_reason_codes",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_qualification_outcome_first_per_company",
        "qualification_outcome",
        ["customer_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("supersedes_outcome_id IS NULL"),
    )
    op.create_index(
        "ix_qualification_outcome_customer_recent",
        "qualification_outcome",
        ["customer_id", sa.text("decided_at DESC"), sa.text("id DESC")],
        schema=SCHEMA,
    )

    # ── Append-only, by the shared guard ─────────────────────────────────────
    for table in _APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {SCHEMA}.{table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION public.prevent_mutation();"
        )

    # ── Seed: version 1 of each criterion, and the reason codes ─────────────
    criterion_table = sa.table(
        "qualification_criterion",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("key"), sa.column("version"), sa.column("label"),
        sa.column("kind", kind_enum), sa.column("comparison", comparison_enum),
        sa.column("threshold"), sa.column("unit"),
        # none_as_null: a missing list is SQL NULL, not the JSON value null,
        # which ck_qualification_criterion_kind_shape would refuse.
        sa.column("allowed_values", postgresql.JSONB(none_as_null=True)),
        sa.column("required"), sa.column("active"),
        schema=SCHEMA,
    )
    op.bulk_insert(
        criterion_table,
        [
            {
                "id": uuid.uuid4(),
                "key": key,
                "version": 1,
                "label": label,
                "kind": kind,
                "comparison": comparison,
                "threshold": threshold,
                "unit": unit,
                "allowed_values": allowed,
                "required": required,
                "active": True,
            }
            for key, label, kind, comparison, threshold, unit, allowed, required in _SEED_CRITERIA
        ],
    )
    reason_table = sa.table(
        "qualification_reason_code",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code"), sa.column("label"), sa.column("requires_note"), sa.column("active"),
        schema=SCHEMA,
    )
    op.bulk_insert(
        reason_table,
        [
            {"id": uuid.uuid4(), "code": code, "label": label, "requires_note": note,
             "active": True}
            for code, label, note in _SEED_REASON_CODES
        ],
    )


def downgrade() -> None:
    # Drops every criterion version, result and outcome.
    for table in reversed(_APPEND_ONLY):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {SCHEMA}.{table}")
    op.drop_table("qualification_outcome", schema=SCHEMA)
    op.drop_table("qualification_result", schema=SCHEMA)
    op.drop_table("qualification_reason_code", schema=SCHEMA)
    op.drop_table("qualification_criterion", schema=SCHEMA)
    op.drop_index(
        "ix_exporter_profile_qualification", table_name="exporter_profile", schema=SCHEMA
    )
    op.drop_index("ix_exporter_profile_journey", table_name="exporter_profile", schema=SCHEMA)
    op.drop_column("exporter_profile", "qualification", schema=SCHEMA)
    op.drop_column("exporter_profile", "journey", schema=SCHEMA)
    bind = op.get_bind()
    for enum_type in reversed(_ENUMS):
        enum_type.drop(bind, checkfirst=False)

