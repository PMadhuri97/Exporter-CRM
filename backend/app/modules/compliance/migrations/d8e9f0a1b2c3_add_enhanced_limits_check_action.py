"""add_enhanced_limits_check_action

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-08-12 09:40:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8e9f0a1b2c3"
down_revision: str | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "compliance"
ENUM_NAME = f"{SCHEMA}.compliance_required_action_enum"
NEW_VALUE = "enhanced_limits_check"

#: The three that shipped in c7d8e9f0a1b2, in their original order.
ORIGINAL_VALUES = ("edd_required", "manual_review", "enhanced_monitoring")


def upgrade() -> None:
    op.execute(f"ALTER TYPE {ENUM_NAME} ADD VALUE IF NOT EXISTS '{NEW_VALUE}'")


def downgrade() -> None:
    # Refuse rather than corrupt: dropping the value while a rule still requires
    # it would silently retire a compliance obligation.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM {SCHEMA}.compliance_rule
                WHERE required_action = '{NEW_VALUE}'
            ) THEN
                RAISE EXCEPTION
                    'cannot remove {NEW_VALUE}: compliance_rule rows still require it';
            END IF;
        END $$;
        """
    )

    values = ", ".join(f"'{value}'" for value in ORIGINAL_VALUES)
    op.execute(f"ALTER TYPE {ENUM_NAME} RENAME TO compliance_required_action_enum_old")
    op.execute(f"CREATE TYPE {ENUM_NAME} AS ENUM ({values})")
    op.execute(
        f"ALTER TABLE {SCHEMA}.compliance_rule "
        f"ALTER COLUMN required_action TYPE {ENUM_NAME} "
        f"USING required_action::text::{ENUM_NAME}"
    )
    op.execute(f"DROP TYPE {SCHEMA}.compliance_required_action_enum_old")
