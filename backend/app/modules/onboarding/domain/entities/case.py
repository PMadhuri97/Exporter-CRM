"""
`onboarding_case` — the KYC/KYB case aggregate root.

This is the table decision **D1** describes: the case carries the eight fields the
backlog names, plus the state machine. Its subject's identity attributes live in
`person_profile`; its KYC-specific detail lives in `kyc_case`.

**No provider-specific columns. Ever.** `provider_route_id` is the one column that
sounds like an exception and is not: it is an opaque route identifier produced by
the route resolver, not a vendor name, a vendor id, or a vendor field.
A Sumsub applicant id or a ComplyAdvantage screening id must never appear here —
those belong in provider metadata or an evidence reference, per §5.3 of
`docs/project-memory.md`.

`tenant_id`, `cell_id`, `policy_id` and `product_context` are **opaque** by decision
D4. Nothing in this module interprets them; the route resolver will match on them
without knowing what they mean.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Enum, Index, String, UniqueConstraint, event, inspect
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modules.onboarding.domain.dto import SubjectType
from app.modules.onboarding.domain.entities.enums import CaseState, CaseType
from app.modules.onboarding.domain.policies.state_machine import (
    DirectStateAssignmentError,
    state_write_permitted,
)
from app.platform.database.models import AnerModel

SCHEMA = "onboarding"

if TYPE_CHECKING:
    # Type-checking only: at runtime SQLAlchemy resolves these names through its
    # declarative class registry, so importing them here would only create a cycle.
    from app.modules.onboarding.domain.entities.case_state_transition import CaseStateTransition
    from app.modules.onboarding.domain.entities.kyc_case import KycCase
    from app.modules.onboarding.domain.entities.person_profile import PersonProfile


class Case(AnerModel):
    """
    A single onboarding/KYC case. Starts in `CaseState.DRAFT`.

    Creation is idempotent on `(tenant_id, idempotency_key)` and, when supplied, on
    `(tenant_id, external_case_id)`. Both are enforced by UNIQUE constraints rather
    than by an application-level check, so a concurrent duplicate loses at the
    database rather than racing past a `SELECT` — decision D6 puts durable
    idempotency in PostgreSQL, in the same transaction as the effect it guards.
    """

    __tablename__ = "onboarding_case"

    # ── Idempotency handles ───────────────────────────────────────────────────
    # The client's replay key. Required: a create-case call without one is a 400.
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    # The caller's own id for this case, if it has one. Optional, but when present
    # it is a second, equally binding handle: the same external id must never
    # produce a second case.
    external_case_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── The eight fields the case must support ────────────────
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cell_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    case_type: Mapped[CaseType] = mapped_column(
        Enum(CaseType, name="onboarding_case_type_enum", schema=SCHEMA), nullable=False
    )
    subject_type: Mapped[SubjectType] = mapped_column(
        Enum(SubjectType, name="onboarding_subject_type_enum", schema=SCHEMA), nullable=False
    )
    product_context: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Set by the route resolver. Deliberately **no ForeignKey**: the
    # `provider_route` table does not exist yet, and inventing it here would be
    # pulling that work forward. The FK is added by the route resolver's migration.
    provider_route_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # ── State ─────────────────────────────────────────────────────────────────
    # Written only by the state machine. Three doors are locked:
    # `CaseRepository.update()` refuses the column, `UpdateCaseRequest` cannot
    # express it, and the `_guard_state_assignment` listener below rejects a raw
    # `case.state = …` on any case that already exists in the database.
    state: Mapped[CaseState] = mapped_column(
        Enum(CaseState, name="onboarding_case_state_enum", schema=SCHEMA),
        nullable=False,
        default=CaseState.DRAFT,
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    profile: Mapped[PersonProfile | None] = relationship(
        back_populates="case",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    kyc_case: Mapped[KycCase | None] = relationship(
        back_populates="case",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    transitions: Mapped[list[CaseStateTransition]] = relationship(
        back_populates="case",
        order_by="CaseStateTransition.created_at",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_onboarding_case_tenant_idem_key"),
        UniqueConstraint("tenant_id", "external_case_id", name="uq_onboarding_case_tenant_external_id"),
        Index("ix_onboarding_case_tenant_id", "tenant_id"),
        Index("ix_onboarding_case_state", "state"),
        {"schema": SCHEMA},
    )


@event.listens_for(Case.state, "set")
def _guard_state_assignment(target: Case, value: Any, oldvalue: Any, initiator: Any) -> None:
    """
    Make "the state machine is the only writer of case state" an enforced invariant
    rather than a convention (design decision 8).

    The listener fires on Python attribute assignment only — never when SQLAlchemy
    loads or refreshes a row from the database — so it distinguishes the two writes
    that matter:

      • **Initialisation.** `Case(state=DRAFT)` on a transient object, before the row
        exists. Permitted: creating a case in `DRAFT` is not a transition, and there
        is no previous state to transition from.
      • **Reassignment.** `case.state = …` on a case with a database identity. This is
        a transition, and it is permitted only inside `permit_state_write()`, which
        only `CaseService.transition()` enters — after `assert_legal()` has passed.
    """
    if state_write_permitted() or not inspect(target).has_identity:
        return
    raise DirectStateAssignmentError(
        f"Case.state cannot be assigned directly (attempted → {value}). "
        "State changes must go through CaseService.transition()."
    )
