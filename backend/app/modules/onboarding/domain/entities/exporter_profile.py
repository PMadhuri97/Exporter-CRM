"""``ExporterProfile`` — the enduring exporter/customer relationship record
(EXP-1, Exporter CRM Phase 1).

Not a facet of any single ``OnboardingRequest``: a profile may exist before an
onboarding journey ever starts (a Lead entered by Sales, nothing verified
yet), and a customer keeps exactly one profile across every historical
``OnboardingRequest`` row for its ``customer_id`` (re-verification, renewed
KYB, a second financing product each start a new ``OnboardingRequest``, never
a new ``ExporterProfile``). ``customer_id`` is therefore unique here, and
deliberately not a foreign key to ``onboarding_request`` — see the module
docstring on ``exporter_enums.ExporterLifecycleStatus`` for why the two
lifecycles are independent state machines.

``gstin``/``pan``/``iec`` are India-specific identifiers not already covered
by ``OnboardingRequest.registration_number``: confirmed against that column
(CIN-equivalent — the country-generic company-registration number captured at
onboarding-request creation), which is a different identifier from all three
of GSTIN (tax registration), PAN (income-tax id) and IEC (import-export
code). None of the three duplicate anything ``OnboardingRequest`` already
stores, so they live here rather than being derived.

``legal_name`` is deliberately **not** a column here — ``search_profiles``'s
``legal_name_contains`` criterion joins to ``OnboardingRequest.legal_name``
instead (see ``application/exporter_profile_service.py``), per the ticket's
explicit instruction not to duplicate a field ``OnboardingRequest`` already
has. A profile with no ``OnboardingRequest`` yet (a bare Lead) simply has no
``legal_name`` to search by until one exists.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterLifecycleStatus,
    ExporterSource,
)
from app.platform.database.models import AnerModel

if TYPE_CHECKING:
    pass

SCHEMA = "onboarding"


class ExporterProfile(AnerModel):
    """One enduring profile per exporter/customer identity.

    ``source`` is immutable once set — enforced both here at the service
    layer (``ExporterProfileService.update_profile`` refuses to touch it) and
    by ``trg_exporter_profile_source_immutability`` at the database level
    (migration ``onboarding_0005_exporter_crm``, reusing the existing
    ``onboarding.prevent_field_mutation_when_set`` function rather than
    defining a second copy of it).

    ``date_added`` is likewise immutable (``server_default=now()``, never
    written to after insert) — it records when the relationship began, which
    must not silently move if the row is later edited.
    """

    __tablename__ = "exporter_profile"
    __table_args__ = (
        UniqueConstraint("customer_id", name="uq_exporter_profile_customer_id"),
        {"schema": SCHEMA},
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # ── India-specific identifiers (not covered by OnboardingRequest) ────────
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    pan: Mapped[str | None] = mapped_column(String(10), nullable=True)
    iec: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # ── Origin (immutable once set — see class docstring) ────────────────────
    source: Mapped[ExporterSource] = mapped_column(
        Enum(ExporterSource, name="exporter_source_enum", schema=SCHEMA), nullable=False
    )

    relationship_manager: Mapped[str | None] = mapped_column(String(255), nullable=True)

    #: Which `auth.users` row this display string refers to, when known —
    #: added in `onboarding_0009_relationship_manager_user` specifically so
    #: the frontend's ownership-scoped PII-reveal check (`OPERATIONS` may
    #: reveal on exporters they own) has something reliable to compare
    #: against. No FK to `auth.users` — see that migration's docstring for
    #: why (matches this codebase's `assigned_to`/`actor_id` convention).
    #: Nothing sets this yet; a future "assign relationship manager" action
    #: is expected to validate it against a real, active user before
    #: writing it.
    relationship_manager_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    lifecycle_status: Mapped[ExporterLifecycleStatus] = mapped_column(
        Enum(ExporterLifecycleStatus, name="exporter_lifecycle_status_enum", schema=SCHEMA),
        nullable=False,
    )

    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    export_markets: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    products: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    year_established: Mapped[int | None] = mapped_column(Integer, nullable=True)
    website: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    date_added: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = ["ExporterProfile"]
