"""Add five RXIL-specific evidence types to evidence_type_enum (ANER-4.3-S2T2)

RXIL — the platform's initial data source, an Indian invoice/receivables
marketplace — already performs KYC, AML/CFT screening, invoice duplication
checks, vessel tracking, MLETR electronic bill-of-lading verification, buyer
ratings, and insurance. RXIL's KYC output maps to the existing `KYB_RESULT`
value and its AML/CFT screening output maps to the existing
`SCREENING_RESULT` value — both already fit and get no new value here. The
five artifacts with no existing home get one each:

  DUPLICATION_CHECK      — RXIL's invoice-duplication-financing check
  VESSEL_TRACKING        — RXIL's vessel tracking data
  BILL_OF_LADING         — RXIL's MLETR electronic bill of lading
  BUYER_RATING           — RXIL's buyer credit rating
  INSURANCE_CERTIFICATE  — RXIL's insurance certificate

See `domain/entities/enums.py`'s `PII_BEARING_EVIDENCE_TYPES` docstring for
which two of these five are treated as PII-bearing (BUYER_RATING and
INSURANCE_CERTIFICATE) and why.

Wrapped in `op.get_context().autocommit_block()`, same as
`cases_0002_intake_type`: this repo's `migrations/env.py` runs a whole
`alembic upgrade` invocation in one ambient transaction
(`transaction_per_migration` is not set), so without forcing a commit here, a
migration added later in the same run that referenced one of these five new
values would hit Postgres's `UnsafeNewEnumValueUsage` the same way
`cases_0003_intake_sla_null` did against `cases_0002_intake_type` before that
fix — see `cases_0002_intake_type`'s docstring for the full explanation.

Revision ID: cases_0004_rxil_evidence
Revises: cases_0003_intake_sla_null
Create Date: 2026-09-18
"""
from collections.abc import Sequence

from alembic import op

revision: str = "cases_0004_rxil_evidence"
down_revision: str | None = "cases_0003_intake_sla_null"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "cases"

_NEW_VALUES = (
    "DUPLICATION_CHECK",
    "VESSEL_TRACKING",
    "BILL_OF_LADING",
    "BUYER_RATING",
    "INSURANCE_CERTIFICATE",
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for value in _NEW_VALUES:
            op.execute(
                f"ALTER TYPE {SCHEMA}.evidence_type_enum ADD VALUE IF NOT EXISTS '{value}'"
            )


def downgrade() -> None:
    # Postgres has no supported way to remove a value from an existing enum
    # type without recreating it — the same non-goal
    # cases_0002_intake_type's downgrade documents.
    pass
