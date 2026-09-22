"""merge AL-669 with develop heads

Revision ID: e849a8d1c41e
Revises: 45ede5960506, settlement_0002_signal_outbox
Create Date: 2026-09-11 19:40:15.666568

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "e849a8d1c41e"
down_revision: str | Sequence[str] | None = ("45ede5960506", "settlement_0002_signal_outbox")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
