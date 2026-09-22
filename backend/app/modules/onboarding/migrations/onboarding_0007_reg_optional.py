"""Relax onboarding_request.registration_number/registered_address to nullable

A Sales-sourced Lead often has nothing but a company name and an
incorporation country on day one — it may take weeks before anyone has the
registration number or registered address on file, and until now there was
nowhere to durably store even the ``legal_name`` because both of those
columns were ``NOT NULL``, so ``OnboardingRequest`` itself could not be
created at all for a cold Lead. This blocks "Add Exporter" from working for
exactly that case.

``incorporation_country`` deliberately stays ``NOT NULL``: it is normally
known even for a cold lead, and it is needed early to route to the right KYB
vendor once verification starts (Middesk for US, Trulioo for India — see
``kyb``'s vendor routing). Only the two fields that are genuinely unknowable
at first contact are loosened here. Both are filled in later via
``OnboardingRequestService.submit_entity_details``, which already exists for
exactly this "complete what wasn't known at initiation" purpose.

One-directional in practice
----------------------------
Same shape as ``cases_0003_intake_sla_null`` (loosening a NOT NULL column,
one case_type deliberately allowed to violate the old constraint): the
``downgrade()`` below re-imposes ``NOT NULL`` directly, with no backfill
invented for it. It will fail with a NOT NULL violation if any row acquired a
NULL ``registration_number``/``registered_address`` after this migration
applied — which, in any environment with real Lead data, is the expected and
accepted case, not a bug to route around. A downgrade is only safe once every
such row has been completed (via ``submit_entity_details``) or removed;
that is left to whoever downgrades, exactly as ``cases_0003_intake_sla_null``
leaves its own one-directional downgrade to whoever runs it.

Revision ID: onboarding_0007_reg_optional
Revises: f1c7a3e6b9d2
Create Date: 2026-09-21
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "onboarding_0007_reg_optional"
down_revision: str | None = "f1c7a3e6b9d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "onboarding"


def upgrade() -> None:
    op.alter_column(
        "onboarding_request",
        "registration_number",
        existing_type=sa.String(length=100),
        nullable=True,
        schema=SCHEMA,
    )
    op.alter_column(
        "onboarding_request",
        "registered_address",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=True,
        schema=SCHEMA,
    )


def downgrade() -> None:
    # One-directional in practice — see module docstring. Fails on any row
    # that still has a NULL registration_number/registered_address; no
    # placeholder backfill is invented here, following the precedent set by
    # cases_0003_intake_sla_null's own one-directional downgrade.
    op.alter_column(
        "onboarding_request",
        "registered_address",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
        schema=SCHEMA,
    )
    op.alter_column(
        "onboarding_request",
        "registration_number",
        existing_type=sa.String(length=100),
        nullable=False,
        schema=SCHEMA,
    )
