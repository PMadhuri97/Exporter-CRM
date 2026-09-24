"""Add RISK_RATING to verification_type_enum

`VerificationType` had 18 members and no risk-rating one, so the composite
rating this platform computes itself (`ConfigDrivenRiskRater`, via
`RiskRatingService`) had no `VerificationResult` row to be recorded on. The
three nearest existing names are different concepts — `VerificationRiskLevel`
is the banding *on* a result row, `OnboardingRiskRating` is the rating
persisted on the onboarding request, and
`OnboardingRequestStatus.RISK_RATING_IN_PROGRESS` is a workflow state — so
none of them could stand in for "a risk rating was run, here is the evidence".

`verification_result.verification_type` is a *native* Postgres enum
(`onboarding_0006_verif_result.py`, `create_type=False`), not a string column,
so the label has to be added to the type itself.

Follows the same autocommit-block pattern as `onboarding_0012_risk_critical`,
`app/modules/cases/migrations/cases_0002_intake_type.py` and
`app/platform/authentication/migrations/auth_0002_developer_role.py`: Postgres
refuses to let a freshly `ALTER TYPE ... ADD VALUE`'d label be referenced
until that ADD VALUE has committed, so it cannot run inside the migration's
own transaction. Per `backend/migrations/README.md` item 2, this migration
therefore does *nothing else*: no default is assigned, no existing row is
touched, no column is altered, and the new value is not referenced here.

Revision ID: onboarding_0013_risk_check   (26 chars — README item 1)
Revises: onboarding_0012_risk_critical
Create Date: 2026-09-24
"""
from collections.abc import Sequence

from alembic import op

revision: str = "onboarding_0013_risk_check"
down_revision: str | None = "onboarding_0012_risk_critical"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"ALTER TYPE {SCHEMA}.verification_type_enum "
            "ADD VALUE IF NOT EXISTS 'RISK_RATING'"
        )


def downgrade() -> None:
    # Postgres has no supported way to remove a value from an existing enum
    # type without recreating it — the same non-goal every other
    # enum-value-add migration in this codebase already accepts, and the
    # honest `pass` `backend/migrations/README.md` item 2 asks for rather
    # than a silent one.
    pass
