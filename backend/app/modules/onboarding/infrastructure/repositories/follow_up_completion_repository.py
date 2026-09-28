"""Repository for ``follow_up_completion``, and the due/overdue read query
(L3-04b). **Owner: Developer 3A, Phase 2.**

Append-only: ``AppendOnlyRepository`` exposes no ``update`` and no ``delete``, and
``trg_follow_up_completion_append_only`` enforces the same rule at the database —
the same pair of guarantees ``ExporterActivityRepository`` has.

**Why the due/overdue query lives here and not in the activity repository.** It
selects across ``exporter_activity``, ``follow_up_completion`` and
``exporter_profile``, so it *could* sit in any of the three. It sits here because
``exporter_activity_repository.py`` is Phase 1's file and the phase agreement (§6.3)
says Phase 2 adds no method to it. A read repository that selects across two tables
is ordinary; reaching into another owner's repository for one method is what creates
the conflict the phase split exists to avoid.

**There is no status column, and there must never be one.** "Outstanding" is the
absence of a completion row, expressed as a ``LEFT JOIN … WHERE completion.id IS
NULL``. Architecture §9.3's "Watch out for" lists the alternative first: marking the
activity would mean updating an append-only row, which the database refuses.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.engagement_enums import ExporterActivityType
from app.modules.onboarding.domain.entities.exporter_activity import ExporterActivity
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.follow_up_completion import FollowUpCompletion
from app.modules.onboarding.domain.follow_up_views import FollowUpState
from app.platform.database.adapters.repository import AppendOnlyRepository

#: One row of the due/overdue query: the follow-up, its completion (`None` when it
#: is outstanding) and the company's display name, all from one statement.
FollowUpRow = tuple[ExporterActivity, FollowUpCompletion | None, str | None]


class FollowUpCompletionRepository(AppendOnlyRepository[FollowUpCompletion]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(FollowUpCompletion, session)

    # ── Completions ──────────────────────────────────────────────────────────

    async def get_by_activity(self, activity_id: uuid.UUID) -> FollowUpCompletion | None:
        """The completion for one follow-up, or ``None`` if it is outstanding.

        At most one can exist — ``uq_follow_up_completion_activity_id`` — so this
        returns a row rather than a list, and the service uses it to refuse a second
        completion with a clean 409 instead of letting the unique constraint surface
        as a 500.
        """
        result = await self.session.execute(
            select(FollowUpCompletion).where(FollowUpCompletion.activity_id == activity_id)
        )
        return result.scalar_one_or_none()

    async def list_for_customer(
        self, customer_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[FollowUpCompletion]:
        """One company's completions, newest first — the order
        ``ix_follow_up_completion_customer_recent`` serves.

        ``completed_at`` defaults to the transaction clock, so ``id`` breaks the tie;
        between two completions written in one transaction the order is deterministic
        rather than chronological.
        """
        result = await self.session.execute(
            select(FollowUpCompletion)
            .where(FollowUpCompletion.customer_id == customer_id)
            .order_by(FollowUpCompletion.completed_at.desc(), FollowUpCompletion.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    # ── The due/overdue read query ───────────────────────────────────────────

    def _follow_up_query(
        self,
        *,
        now: datetime,
        state: FollowUpState | None,
        customer_id: uuid.UUID | None,
        actor_id: str | None,
        activity_type: ExporterActivityType | None,
        due_before: datetime | None,
        due_after: datetime | None,
    ) -> Select:
        """The shared `FROM`/`WHERE` for the list and its count.

        Built once so the total can never describe a different set from the page —
        the bug a hand-written second query invites.

        `due_at IS NOT NULL` is what makes an activity a follow-up: the append-only
        log has no "is a follow-up" flag, and a due date is the log's own stand-in
        for a promise, which is the convention `list_pending` already established.
        """
        stmt = (
            select(ExporterActivity, FollowUpCompletion, ExporterProfile.name)
            # LEFT JOIN, not INNER: an outstanding follow-up has no completion row,
            # and those are most of the list.
            .outerjoin(
                FollowUpCompletion,
                FollowUpCompletion.activity_id == ExporterActivity.id,
            )
            .outerjoin(
                ExporterProfile,
                ExporterProfile.customer_id == ExporterActivity.customer_id,
            )
            .where(ExporterActivity.due_at.isnot(None))
        )

        if state is FollowUpState.DONE:
            stmt = stmt.where(FollowUpCompletion.id.isnot(None))
        elif state is FollowUpState.OUTSTANDING:
            stmt = stmt.where(FollowUpCompletion.id.is_(None))
        elif state is FollowUpState.OVERDUE:
            # Overdue narrows outstanding rather than sitting beside it: a follow-up
            # someone dealt with late is done, not overdue.
            stmt = stmt.where(FollowUpCompletion.id.is_(None), ExporterActivity.due_at < now)

        if customer_id is not None:
            stmt = stmt.where(ExporterActivity.customer_id == customer_id)
        if actor_id is not None:
            # Filtering *by* a person, never a permission: follow-ups are the whole
            # team's (decision D2), so this narrows the list and does not gate it.
            stmt = stmt.where(ExporterActivity.actor_id == actor_id)
        if activity_type is not None:
            stmt = stmt.where(ExporterActivity.activity_type == activity_type)
        if due_before is not None:
            stmt = stmt.where(ExporterActivity.due_at < due_before)
        if due_after is not None:
            stmt = stmt.where(ExporterActivity.due_at > due_after)
        return stmt

    async def list_follow_ups(
        self,
        *,
        now: datetime,
        state: FollowUpState | None = None,
        customer_id: uuid.UUID | None = None,
        actor_id: str | None = None,
        activity_type: ExporterActivityType | None = None,
        due_before: datetime | None = None,
        due_after: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[FollowUpRow]:
        """Every follow-up matching the filters, soonest-due first.

        Overdue items sort to the very front, because their ``due_at`` is furthest in
        the past — the natural reading order for "what needs attention", and the same
        order ``list_pending`` uses.

        One statement: the completion and the company's display name come back with
        the activity, so a list of any length costs one round trip and never an N+1.
        """
        stmt = self._follow_up_query(
            now=now,
            state=state,
            customer_id=customer_id,
            actor_id=actor_id,
            activity_type=activity_type,
            due_before=due_before,
            due_after=due_after,
        )
        stmt = (
            stmt.order_by(ExporterActivity.due_at.asc(), ExporterActivity.id.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return [(row[0], row[1], row[2]) for row in result.all()]

    async def count_follow_ups(
        self,
        *,
        now: datetime,
        state: FollowUpState | None = None,
        customer_id: uuid.UUID | None = None,
        actor_id: str | None = None,
        activity_type: ExporterActivityType | None = None,
        due_before: datetime | None = None,
        due_after: datetime | None = None,
    ) -> int:
        """How many match, ignoring paging — from the same builder as the page."""
        inner = self._follow_up_query(
            now=now,
            state=state,
            customer_id=customer_id,
            actor_id=actor_id,
            activity_type=activity_type,
            due_before=due_before,
            due_after=due_after,
        ).subquery()
        return int(await self.session.scalar(select(func.count()).select_from(inner)) or 0)

    # ── Check-backs: companies parked at NOT_NOW ─────────────────────────────
    #
    # Read-only, and read straight off the company record. `ConversationService` is
    # the only writer of `conversation_check_back_on`
    # (`docs/contracts/engagement.md` §2.1), and Phase 2 never writes it — the same
    # rule that stops Developer 3B writing `conversation`.

    def _check_back_query(self, *, customer_id: uuid.UUID | None, due_on_or_before: date | None):
        stmt = select(ExporterProfile).where(
            ExporterProfile.conversation_check_back_on.isnot(None)
        )
        if customer_id is not None:
            stmt = stmt.where(ExporterProfile.customer_id == customer_id)
        if due_on_or_before is not None:
            stmt = stmt.where(ExporterProfile.conversation_check_back_on <= due_on_or_before)
        return stmt

    async def list_check_backs(
        self,
        *,
        customer_id: uuid.UUID | None = None,
        due_on_or_before: date | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExporterProfile]:
        """Companies with a check-back date, soonest first.

        The filter is on the **date**, not on ``conversation = 'NOT_NOW'``:
        ``ck_exporter_profile_conversation_check_back`` already guarantees a date
        exists exactly when the conversation is ``NOT_NOW``, so a second condition
        would be a copy of that invariant, and the partial index
        ``ix_exporter_profile_conversation_check_back`` is on the date column.
        """
        stmt = (
            self._check_back_query(customer_id=customer_id, due_on_or_before=due_on_or_before)
            .order_by(
                ExporterProfile.conversation_check_back_on.asc(),
                ExporterProfile.customer_id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_check_backs(
        self,
        *,
        customer_id: uuid.UUID | None = None,
        due_on_or_before: date | None = None,
    ) -> int:
        inner = self._check_back_query(
            customer_id=customer_id, due_on_or_before=due_on_or_before
        ).subquery()
        return int(await self.session.scalar(select(func.count()).select_from(inner)) or 0)


__all__ = ["FollowUpCompletionRepository", "FollowUpRow"]
