"""ANER-4.1 S1 schema fix: rename kyb_result -> screening_result, add edd_required/edd_reason

Two real bugs in the S1 onboarding schema (``onboarding_0002_orchestration_schema``),
found and worked around (not fixed) by the later S5 risk-rating and S7
service-API builds:

1. ``onboarding_request.kyb_result`` is typed with ``onboarding_screening_result_enum``
   (``CLEAR`` / ``REVIEW_REQUIRED`` / ``HARD_BLOCK``) — it is the screening
   result, not a KYB result (KYB verification is a separate concept, handled
   via ``kyb_vendor_result`` / ``app.modules.kyb``). It was simply misnamed
   when S1 was built. This migration renames the column (and, via
   ``op.alter_column(new_column_name=...)``, preserves any existing data) to
   ``screening_result``.

   The column is also one of the three arguments to the shared
   ``trg_onboarding_request_field_immutability`` write-once trigger. Postgres
   has no ``ALTER TRIGGER`` for changing a trigger's arguments, so this
   migration drops and recreates that exact trigger (same name, so nothing
   that references it by name breaks) with ``screening_result`` in place of
   ``kyb_result``; ``ubo_mapping`` and ``risk_rating_factors`` are unchanged.

2. ``edd_required`` (boolean) and ``edd_reason`` (text) are part of the Epic
   4.1 data model for ``onboarding_request`` but were never added to the S1
   schema. ``RiskRatingResult.to_risk_rating_factors_json()`` (S5 build)
   embeds both inside the ``risk_rating_factors`` JSONB column as a
   workaround. This migration adds the two real, nullable columns; the
   application layer now writes to them directly (see
   ``risk_rating_assignment_service.py`` / ``config_driven_risk_rater.py``).
   The JSON embedding is kept too, deliberately, as a write-once audit-grade
   duplicate captured at the moment of assignment — see
   ``RiskRatingResult.to_risk_rating_factors_json``'s docstring.

Revision ID: onboarding_0004_screening_fix
Revises: 87608d21fcb5
Create Date: 2026-09-19
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "onboarding_0004_screening_fix"
down_revision: str | None = "87608d21fcb5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"


def upgrade() -> None:
    # 1. Rename the mislabeled column in place (preserves any existing data).
    op.alter_column(
        "onboarding_request",
        "kyb_result",
        new_column_name="screening_result",
        schema=SCHEMA,
    )

    # 2. Postgres has no ALTER TRIGGER for changing arguments: drop and
    #    recreate the write-once trigger, same name, with the corrected
    #    argument. ubo_mapping / risk_rating_factors are unchanged.
    op.execute(f"DROP TRIGGER IF EXISTS trg_onboarding_request_field_immutability ON {SCHEMA}.onboarding_request;")
    op.execute(f"""
    CREATE TRIGGER trg_onboarding_request_field_immutability
    BEFORE UPDATE ON {SCHEMA}.onboarding_request
    FOR EACH ROW
    EXECUTE FUNCTION {SCHEMA}.prevent_field_mutation_when_set('screening_result', 'ubo_mapping', 'risk_rating_factors');
    """)

    # 3. Add the two missing columns from the Epic 4.1 data model.
    op.add_column(
        "onboarding_request",
        sa.Column("edd_required", sa.Boolean(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "onboarding_request",
        sa.Column("edd_reason", sa.Text(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("onboarding_request", "edd_reason", schema=SCHEMA)
    op.drop_column("onboarding_request", "edd_required", schema=SCHEMA)

    op.execute(f"DROP TRIGGER IF EXISTS trg_onboarding_request_field_immutability ON {SCHEMA}.onboarding_request;")
    op.execute(f"""
    CREATE TRIGGER trg_onboarding_request_field_immutability
    BEFORE UPDATE ON {SCHEMA}.onboarding_request
    FOR EACH ROW
    EXECUTE FUNCTION {SCHEMA}.prevent_field_mutation_when_set('kyb_result', 'ubo_mapping', 'risk_rating_factors');
    """)

    op.alter_column(
        "onboarding_request",
        "screening_result",
        new_column_name="kyb_result",
        schema=SCHEMA,
    )
