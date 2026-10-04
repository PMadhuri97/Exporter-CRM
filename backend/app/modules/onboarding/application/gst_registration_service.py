"""``GstRegistrationService`` — a company's GST branches — **owner: Developer 3**
(allocation tasks 3.13, 3.14, 3.15; plan P6-2, P6-5, and P6-3's consequences).

A GST registration is a **branch**: a state, an address, a portal status, and
possibly a compliance flag (``domain/entities/exporter_gstin.py``). Until task 3.12
it was a string in a list that a company edit replaced wholesale; this service is
what replaced that.

Three things it will not do
---------------------------
* **Delete.** ``trg_exporter_gstin_no_delete`` refuses it, and so does this service:
  a branch the company traded through is part of the record, and a handed-over deal
  names the one it invoiced from. Dropping a branch is ``deactivate``.
* **Take a state.** ``state_code`` and ``state_name`` are derived from the GSTIN
  (``domain/gst_states.py``). A form that accepted both would let someone record
  "Maharashtra" against a GSTIN issued in Karnataka.
* **Refuse a GSTIN another company holds.** Decision IQ-9 keeps duplicates
  warn-only. ``add`` returns the other holders so the screen can say "this GSTIN is
  also on company X" — and ``flag`` returns them too (task 3.15), because a flag
  belongs to *one* company's row and whoever flags it should know the other copy is
  unaffected.

Reactivation is deliberately absent. Re-adding a GSTIN that was deactivated
reactivates the same row rather than inserting a second one — ``add`` handles that —
so there is one row per ``(company, GSTIN)`` forever, which is what
``uq_exporter_gstin_customer_gstin`` already said.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain import history_dimensions
from app.modules.onboarding.domain.entities.exporter_enums import (
    GstRegistrationFlag,
    GstRegistrationStatus,
)
from app.modules.onboarding.domain.entities.exporter_gstin import ExporterGstin
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.gst_states import state_code_of, state_name_of
from app.modules.onboarding.domain.tax_identifiers import (
    check_gstins_match_pan,
    normalise_gstins,
)
from app.modules.onboarding.exceptions import (
    ExporterProfileNotFoundError,
    GstRegistrationAlreadyActiveError,
    GstRegistrationNotFoundError,
)
from app.shared import clock
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)

#: The history dimension every write here records. Developer 1's one list, so the
#: read route's D8 rule and this writer cannot disagree about the spelling.
HISTORY_DIMENSION_GST = history_dimensions.GST_REGISTRATION


class GstRegistrationService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._history = HistoryService(db)

    # ── Read ─────────────────────────────────────────────────────────────────

    async def list_for_company(
        self, customer_id: uuid.UUID, *, include_inactive: bool = True
    ) -> list[ExporterGstin]:
        """Every registration, newest last — deactivated ones included by default.

        Included because the company page shows them: a branch that was deactivated
        is how a deal handed over last year is explained, and hiding it would make
        that deal's invoicing branch look like it came from nowhere.
        """
        statement = select(ExporterGstin).where(ExporterGstin.customer_id == customer_id)
        if not include_inactive:
            statement = statement.where(ExporterGstin.active.is_(True))
        rows = await self._db.scalars(
            statement.order_by(ExporterGstin.created_at, ExporterGstin.gstin)
        )
        return list(rows)

    async def other_holders(
        self, gstin: str, *, excluding: uuid.UUID
    ) -> list[uuid.UUID]:
        """Other companies holding this GSTIN (decision IQ-9: a warning, never a
        refusal). Active rows only — a company that deactivated its copy is no longer
        claiming it."""
        rows = await self._db.scalars(
            select(ExporterGstin.customer_id).where(
                ExporterGstin.gstin == gstin,
                ExporterGstin.customer_id != excluding,
                ExporterGstin.active.is_(True),
            )
        )
        return sorted(set(rows), key=str)

    # ── Write ────────────────────────────────────────────────────────────────

    async def add(
        self,
        customer_id: uuid.UUID,
        *,
        gstin: str,
        address: str | None = None,
        status: GstRegistrationStatus = GstRegistrationStatus.UNVERIFIED,
        actor_id: str | None,
    ) -> tuple[ExporterGstin, list[uuid.UUID]]:
        """Record a GST registration for this company.

        Returns ``(registration, other_holders)``: the other companies holding the
        same GSTIN are a warning the caller shows, never a refusal (IQ-9).

        A GSTIN this company **deactivated** earlier reactivates that row rather than
        inserting a second one, so there is one row per ``(company, GSTIN)`` forever
        — which is what `uq_exporter_gstin_customer_gstin` says, and what keeps a
        handed-over deal's invoicing branch pointing at the branch it really used.
        Re-adding an **active** one is a 409: nothing would change, and silently
        succeeding would suggest something had.

        Raises:
            ExporterProfileNotFoundError: no such company.
            ValidationError: a malformed GSTIN, or one that does not carry the
                company's PAN.
            GstRegistrationAlreadyActiveError: the company already has it, active.
        """
        profile = await self._lock_profile(customer_id)

        [normalised] = normalise_gstins([gstin]) or [None]
        if normalised is None:
            raise ValidationError("a GST registration needs a GSTIN")
        # The same rule every other write path applies: a GSTIN carries its company's
        # PAN in characters 3–12. Checked against the PAN on file plus this GSTIN.
        check_gstins_match_pan(profile.pan, [normalised])

        existing = await self._db.scalar(
            select(ExporterGstin).where(
                ExporterGstin.customer_id == customer_id,
                ExporterGstin.gstin == normalised,
            )
        )
        if existing is not None and existing.active:
            raise GstRegistrationAlreadyActiveError(customer_id, existing.id)

        if existing is not None:
            registration = existing
            registration.active = True
            registration.deactivated_at = None
            registration.deactivated_by = None
            event = "gst_registration_reactivated"
        else:
            registration = ExporterGstin(
                customer_id=customer_id,
                gstin=normalised,
                state_code=state_code_of(normalised),
                state_name=state_name_of(normalised),
                status=status,
                address=(address or "").strip() or None,
            )
            self._db.add(registration)
            event = "gst_registration_added"

        if existing is not None and address is not None:
            registration.address = (address or "").strip() or None

        await self._db.flush()
        await self._record(
            registration,
            event_type=event,
            to_value=registration.state_name or registration.state_code or "unknown state",
            actor_id=actor_id,
        )
        await self._db.commit()
        await self._db.refresh(registration)

        others = await self.other_holders(normalised, excluding=customer_id)
        logger.info(
            "gst_registration.added",
            customer_id=str(customer_id),
            registration_id=str(registration.id),
            reactivated=existing is not None,
            other_holders=len(others),
            actor_id=actor_id,
        )
        return registration, others

    async def deactivate(
        self, registration_id: uuid.UUID, *, reason: str | None = None, actor_id: str | None
    ) -> ExporterGstin:
        """Stop using this branch, keeping its row.

        Not a delete: ``trg_exporter_gstin_no_delete`` refuses that, and a deal
        handed over through this branch records its id. Deactivating twice is a
        no-op, because the second request asks for a state the row is already in and
        failing it would make a retry an error.
        """
        registration = await self._lock_company_then_registration(registration_id)
        if not registration.active:
            return registration

        registration.active = False
        registration.deactivated_at = clock.now()
        registration.deactivated_by = actor_id
        await self._record(
            registration,
            event_type="gst_registration_deactivated",
            to_value=registration.state_name or registration.state_code or "unknown state",
            actor_id=actor_id,
            reason=reason,
        )
        await self._db.commit()
        await self._db.refresh(registration)
        logger.info(
            "gst_registration.deactivated",
            registration_id=str(registration_id),
            actor_id=actor_id,
        )
        return registration

    async def flag(
        self, registration_id: uuid.UUID, *, reason: str, actor_id: str | None
    ) -> tuple[ExporterGstin, list[uuid.UUID]]:
        """Flag this branch (task 3.14). A reason is required.

        Returns the other companies holding the same GSTIN (task 3.15): the flag
        belongs to **this** company's row and does not touch theirs, which is a
        consequence of IQ-9 keeping duplicates warn-only. Whoever flags it needs to
        know the other copy exists and is unaffected — otherwise they will believe
        they have stopped trade that is still running on the other company.

        Flagging an already-flagged branch replaces the reason and records the
        change, because a reason that has been superseded is still a decision worth
        a history row.
        """
        cleaned = (reason or "").strip()
        if not cleaned:
            # Also `ck_exporter_gstin_flag_reason`; this names the field instead of
            # surfacing a constraint violation.
            raise ValidationError("a flag needs a reason: it is what the block will say")

        registration = await self._lock_company_then_registration(registration_id)
        was = registration.flag_status
        registration.flag_status = GstRegistrationFlag.FLAGGED
        registration.flag_reason = cleaned
        await self._record(
            registration,
            event_type="gst_registration_flagged",
            to_value=GstRegistrationFlag.FLAGGED.value,
            from_value=was.value,
            actor_id=actor_id,
            reason=cleaned,
        )
        await self._db.commit()
        await self._db.refresh(registration)

        others = await self.other_holders(
            registration.gstin, excluding=registration.customer_id
        )
        logger.info(
            "gst_registration.flagged",
            registration_id=str(registration_id),
            other_holders=len(others),
            actor_id=actor_id,
        )
        return registration, others

    async def unflag(
        self, registration_id: uuid.UUID, *, reason: str, actor_id: str | None
    ) -> ExporterGstin:
        """Lift the flag. A reason is required here too: "why we decided the problem
        is resolved" is the half of the story that a later reader needs most, and the
        flag's own reason is about to stop being readable on the row."""
        cleaned = (reason or "").strip()
        if not cleaned:
            raise ValidationError("lifting a flag needs a reason")

        registration = await self._lock_company_then_registration(registration_id)
        was = registration.flag_status
        registration.flag_status = GstRegistrationFlag.NONE
        registration.flag_reason = None
        await self._record(
            registration,
            event_type="gst_registration_unflagged",
            to_value=GstRegistrationFlag.NONE.value,
            from_value=was.value,
            actor_id=actor_id,
            reason=cleaned,
        )
        await self._db.commit()
        await self._db.refresh(registration)
        logger.info(
            "gst_registration.unflagged",
            registration_id=str(registration_id),
            actor_id=actor_id,
        )
        return registration

    # ── Internals ────────────────────────────────────────────────────────────

    async def _record(
        self,
        registration: ExporterGstin,
        *,
        event_type: str,
        to_value: str,
        actor_id: str | None,
        from_value: str | None = None,
        reason: str | None = None,
    ) -> None:
        """One ``gst_registration`` history row.

        The GSTIN is **masked** in the row's details. The history read route shows a
        row to every CRM reader, including roles that only ever see a GSTIN masked on
        the company itself, so a full value here would be a way around that — the
        same rule `_MASKED_IN_HISTORY` applies to a profile edit.
        """
        from app.modules.onboarding.api.schemas.masking import mask_identifier

        await self._history.record(
            registration.customer_id,
            dimension=HISTORY_DIMENSION_GST,
            to_value=to_value,
            from_value=from_value,
            actor_id=actor_id,
            source="gst_registration_service",
            event_type=event_type,
            reason=reason,
            details={
                "registration_id": str(registration.id),
                "gstin": mask_identifier(registration.gstin),
                "state_name": registration.state_name,
                "state_code": registration.state_code,
                "active": registration.active,
                "flag_status": registration.flag_status.value,
            },
        )

    async def _lock_profile(self, customer_id: uuid.UUID) -> ExporterProfile:
        profile = await self._db.scalar(
            select(ExporterProfile)
            .where(ExporterProfile.customer_id == customer_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if profile is None:
            raise ExporterProfileNotFoundError(customer_id)
        return profile

    async def _lock_company_then_registration(
        self, registration_id: uuid.UUID
    ) -> ExporterGstin:
        """Lock the owning company ``FOR UPDATE``, then the registration (R-18).

        The handover guard reads a seller's branches under ``FOR SHARE`` on the
        **company** row (D10, P4-7) — so a flag, an unflag or a deactivation that
        locked only the branch could commit between the guard's read and the
        handover's commit, and a deal would go to the lending team through a branch
        flagged a moment before. Taking the company first makes such a write wait for
        the handover, and the next guard read see it. Company then registration is the
        order ``add`` already takes, so the two cannot deadlock each other.

        The registration's company is read first, unlocked: a branch never changes
        company, so that read cannot go stale.
        """
        customer_id = await self._db.scalar(
            select(ExporterGstin.customer_id).where(ExporterGstin.id == registration_id)
        )
        if customer_id is None:
            raise GstRegistrationNotFoundError(registration_id)
        await self._lock_profile(customer_id)
        return await self._lock_registration(registration_id)

    async def _lock_registration(self, registration_id: uuid.UUID) -> ExporterGstin:
        registration = await self._db.scalar(
            select(ExporterGstin)
            .where(ExporterGstin.id == registration_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if registration is None:
            raise GstRegistrationNotFoundError(registration_id)
        return registration


__all__ = ["HISTORY_DIMENSION_GST", "GstRegistrationService"]
