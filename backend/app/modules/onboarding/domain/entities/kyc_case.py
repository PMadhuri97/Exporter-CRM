"""
`kyc_case` — the KYC-specific detail hanging off a case (decision D1).

D1 defines this table as "required checks, and the provider runs belonging to it".
Only the first half is buildable today: the `provider_run` table lands later, which
is where the `provider_run.kyc_case_id` foreign key and the `runs` relationship are
added. That dependency is documented, not stubbed.

`required_checks` is JSONB rather than a set of columns for the same reason
`normalized_result.check_outcomes` will be (§5.8): a new check type must never cost
a migration. Values are `CheckType` members; the schema layer validates them, the
column stores strings.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.platform.database.models import AnerModel

SCHEMA = "onboarding"

if TYPE_CHECKING:
    from app.modules.onboarding.domain.entities.case import Case


class KycCase(AnerModel):
    """KYC detail for exactly one `Case`."""

    __tablename__ = "kyc_case"
    __table_args__ = (
        Index("ix_kyc_case_case_id", "case_id", unique=True),
        {"schema": SCHEMA},
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.onboarding_case.id", ondelete="CASCADE"),
        nullable=False,
    )

    # The checks this case must satisfy, e.g. ["IDENTITY", "DOCUMENT", "LIVENESS"].
    # Populated by the caller today; produced by the route resolver later,
    # which is the point at which required checks stop being a client concern.
    required_checks: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    case: Mapped[Case] = relationship(back_populates="kyc_case")
