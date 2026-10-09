"""``CollectionsOwnerService`` — who chases a company's payments.

The rules follow the relationship manager's:

* naming, changing or clearing a collections owner needs ``exporters:assign_collector``
  (COMPLIANCE and whoever may assign relationship managers);
* changing or clearing one already named needs a reason;
* the owner is an **active** relationship manager or compliance officer — collectors
  are usually finance staff, and there is no finance role yet; the administrator runs
  the system and works no company, so is never named;
* the caller says which owner they saw (``seen_user_id``), so a screen that is out of
  date is refused rather than overwriting someone else's change;
* each change writes one ``collections_owner`` history row with both names as they
  were; a bulk reassignment gives every company its own row, sharing one run id.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain import history_dimensions
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.exceptions import (
    CollectionsOwnerAssignNotAllowedError,
    CollectionsOwnerChangedError,
    ExporterProfileNotFoundError,
)
from app.platform.authentication import staff_member, staff_members
from app.platform.authentication.models import UserRole
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)

ASSIGN_COLLECTOR = ("exporters", "assign_collector")
#: Who may be named: the people who work the business — relationship managers and
#: compliance. The administrator runs the system and works no company; API_USER and
#: DEVELOPER never collect.
COLLECTOR_ROLES = frozenset({UserRole.OPERATIONS, UserRole.COMPLIANCE})
UNASSIGNED = "UNASSIGNED"


@dataclass(frozen=True)
class BulkCollectorReassignment:
    run_id: str | None
    dry_run: bool
    matched: tuple[uuid.UUID, ...]
    moved: tuple[uuid.UUID, ...]
    skipped: tuple[uuid.UUID, ...]


class CollectionsOwnerService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._history = HistoryService(db)

    async def assign(
        self,
        customer_id: uuid.UUID,
        *,
        user_id: uuid.UUID | None,
        reason: str | None,
        seen_user_id: uuid.UUID | None,
        actor_id: str,
        actor_permissions: Collection[tuple[str, str]],
    ) -> ExporterProfile:
        if ASSIGN_COLLECTOR not in actor_permissions:
            raise CollectionsOwnerAssignNotAllowedError(customer_id)
        profile = await self._lock(customer_id)
        if profile.collections_owner_user_id != seen_user_id:
            raise CollectionsOwnerChangedError(
                customer_id, seen_user_id, profile.collections_owner_user_id
            )
        await self._set(profile, user_id=user_id, reason=reason, actor_id=actor_id)
        await self._db.commit()
        await self._db.refresh(profile)
        return profile

    async def reassign(
        self,
        *,
        from_user_id: uuid.UUID,
        to_user_id: uuid.UUID,
        company_ids: list[uuid.UUID] | None,
        reason: str | None,
        dry_run: bool,
        actor_id: str,
        actor_permissions: Collection[tuple[str, str]],
    ) -> BulkCollectorReassignment:
        """Move one owner's companies — all, or the ones listed — to another. Locked in
        ``customer_id`` order; a company whose owner changed since is skipped."""
        if ASSIGN_COLLECTOR not in actor_permissions:
            raise CollectionsOwnerAssignNotAllowedError("(bulk)")
        text = (reason or "").strip() or None
        if text is None:
            raise ValidationError("A reason is required to reassign collections")
        if from_user_id == to_user_id:
            raise ValidationError("the companies already belong to that collections owner")
        await self._require_eligible(to_user_id)

        statement = (
            select(ExporterProfile.customer_id)
            .where(ExporterProfile.collections_owner_user_id == from_user_id)
            .order_by(ExporterProfile.customer_id)
        )
        if company_ids is not None:
            statement = statement.where(ExporterProfile.customer_id.in_(company_ids))
        candidates = list(await self._db.scalars(statement))
        not_owned = (
            sorted(set(company_ids) - set(candidates), key=str) if company_ids is not None else []
        )
        if dry_run:
            return BulkCollectorReassignment(None, True, tuple(candidates), (), tuple(not_owned))

        run_id = str(uuid.uuid4())
        moved: list[uuid.UUID] = []
        skipped: list[uuid.UUID] = list(not_owned)
        for company_id in candidates:
            profile = await self._lock(company_id)
            if profile.collections_owner_user_id != from_user_id:
                skipped.append(company_id)
                continue
            await self._set(
                profile, user_id=to_user_id, reason=text, actor_id=actor_id, bulk_run_id=run_id
            )
            moved.append(company_id)
        await self._db.commit()
        logger.info(
            "exporter_profile.collections_owners_reassigned",
            bulk_run_id=run_id,
            moved=len(moved),
            skipped=len(skipped),
            actor_id=actor_id,
        )
        return BulkCollectorReassignment(
            run_id, False, tuple(candidates), tuple(moved), tuple(skipped)
        )

    async def _set(
        self,
        profile: ExporterProfile,
        *,
        user_id: uuid.UUID | None,
        reason: str | None,
        actor_id: str,
        bulk_run_id: str | None = None,
    ) -> bool:
        current = profile.collections_owner_user_id
        if user_id == current:
            return False
        text = (reason or "").strip() or None
        if current is not None and text is None:
            raise ValidationError("A reason is required to change or clear the collections owner")
        if user_id is not None:
            await self._require_eligible(user_id)
        from_id = str(current) if current is not None else None
        to_id = str(user_id) if user_id is not None else None
        members = await staff_members(self._db, [from_id, to_id])
        event = (
            "collections_owner_assigned"
            if current is None
            else "collections_owner_cleared"
            if user_id is None
            else "collections_owner_reassigned"
        )
        profile.collections_owner_user_id = user_id
        await self._history.record(
            profile.customer_id,
            dimension=history_dimensions.COLLECTIONS_OWNER,
            from_value=from_id or UNASSIGNED,
            to_value=to_id or UNASSIGNED,
            actor_id=actor_id,
            source="collections_owner_service",
            reason=text,
            event_type=event,
            details={
                "from_user_id": from_id,
                "to_user_id": to_id,
                "from_user_name": members[from_id].name if from_id in members else None,
                "to_user_name": members[to_id].name if to_id in members else None,
                "bulk_run_id": bulk_run_id,
            },
        )
        return True

    async def _require_eligible(self, user_id: uuid.UUID) -> None:
        member = await staff_member(self._db, str(user_id))
        if member is None:
            raise ValidationError("No such user")
        if not member.is_active:
            raise ValidationError("That account is deactivated")
        if member.role not in COLLECTOR_ROLES:
            raise ValidationError(
                "Only a relationship manager or a compliance officer can own a company's "
                "collections"
            )

    async def _lock(self, customer_id: uuid.UUID) -> ExporterProfile:
        profile = await self._db.scalar(
            select(ExporterProfile)
            .where(ExporterProfile.customer_id == customer_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if profile is None:
            raise ExporterProfileNotFoundError(customer_id)
        return profile


__all__ = ["BulkCollectorReassignment", "CollectionsOwnerService"]
