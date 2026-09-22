"""
`person_profile` — the subject's identity attributes (decision D1).

**This is where PII lives**, and it is the only core case table that holds any. The
PII-handling rules in `docs/project-memory.md` §5.3 apply to every column below:
never log it, never put it in an event payload, never echo it into a traceback.

Per decision **D2**, only `person_profile` is modelled now — it is the sole profile
table the backlog names. `entity_profile` is built when the first KYB route is
actually exercised, not speculatively; `Case.subject_type` already discriminates.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.platform.database.models import AnerModel

SCHEMA = "onboarding"

if TYPE_CHECKING:
    from app.modules.onboarding.domain.entities.case import Case


class PersonProfile(AnerModel):
    """
    Identity attributes of the individual a case is about. One row per case.

    Every attribute is nullable: a case is created in `DRAFT` and a profile is
    filled in progressively as the subject supplies it. Validation of *which*
    attributes a given provider requires is the adapter's job, not this table's.
    """

    __tablename__ = "person_profile"
    __table_args__ = (
        Index("ix_person_profile_case_id", "case_id", unique=True),
        {"schema": SCHEMA},
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.onboarding_case.id", ondelete="CASCADE"),
        nullable=False,
    )

    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    nationality: Mapped[str | None] = mapped_column(String(2), nullable=True)
    residence_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    case: Mapped[Case] = relationship(back_populates="profile")

    def __repr__(self) -> str:
        """Identifiers only. The default SQLAlchemy repr would print PII into logs
        and tracebacks, which §5.3 forbids outright."""
        return f"<PersonProfile id={self.id} case_id={self.case_id}>"
