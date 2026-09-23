"""Add CRITICAL to verification_risk_level_enum

`VerificationRiskLevel` (LOW/MEDIUM/HIGH) sits between two banding
vocabularies that both carry a CRITICAL band — `domain.dto.RiskLevel`
(LOW/MEDIUM/HIGH/CRITICAL) and `OnboardingRiskRating`. An adapter normalising
a vendor's "critical" verdict had nowhere to put it and had to flatten it onto
HIGH, losing exactly the distinction the band exists to make.

`verification_result.risk_level` is a *native* Postgres enum
(`onboarding_0006_verif_result.py`, `create_type=False`), not a string column,
so the label has to be added to the type itself.

Follows the established autocommit-block pattern
(`app/modules/cases/migrations/cases_0002_intake_type.py`,
`app/platform/authentication/migrations/auth_0002_developer_role.py`):
Postgres refuses to let a freshly `ALTER TYPE ... ADD VALUE`'d label be
referenced until that ADD VALUE has committed, so it cannot run inside the
migration's own transaction. Nothing here uses the new value yet — no default
is assigned, no existing row is touched, no column is altered.

Revision ID: onboarding_0012_risk_critical
Revises: onboarding_0010_screen_review
Create Date: 2026-09-23
"""
from collections.abc import Sequence

from alembic import op

revision: str = "onboarding_0012_risk_critical"
down_revision: str | None = "onboarding_0010_screen_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"ALTER TYPE {SCHEMA}.verification_risk_level_enum "
            "ADD VALUE IF NOT EXISTS 'CRITICAL'"
        )


def downgrade() -> None:
    # Postgres has no supported way to remove a value from an existing enum
    # type without recreating it — the same non-goal every other
    # enum-value-add migration in this codebase already accepts.
    pass
