"""``ConversationService`` — the conversation gauge.

The conversation gauge answers *how is the sales conversation going?* and nothing
else. The contract is ``docs/contracts/engagement.md``; architecture §3.3 defines
the six values.

**It is the only writer of ``exporter_profile.conversation`` and of
``exporter_profile.conversation_check_back_on``.** ``docs/contracts/company-record.md``
§2.4: only a gauge's owner writes its field, "including just to keep it in sync".
Deals move the gauge by calling ``mark_ready_now_for_opened_deal``, not by
assigning to the column; follow-ups read the check-back date and never write it.

**One transaction per operation.** ``set_conversation`` locks the company row,
validates, assigns, writes the history row through the shared
``HistoryService`` — which flushes and never commits — and commits once at the
end. Architecture §3.8: the current value and the record of how it got there
commit together or not at all. An illegal move raises before anything is
assigned, so a refused move leaves nothing behind (history contract §5).

**What it does not decide.** Which roles may move the gauge is the route's, via
``require_role`` in ``engagement_router.py``, matching the §3.7 matrix. This
service holds the *rules* — which moves exist, which need a reason, which need a
check-back date, and that the gauge applies from ``PROSPECT`` onward — and
``allowed_moves`` is those rules as data, so the screen asks the server instead of
keeping a copy (§7.5). That split is ``ExporterProfileService.allowed_marker_moves``'s
and is deliberately the same shape.

**Nothing here touches an activity.** ``exporter_activity`` is append-only and a
check-back date is not a mark on an activity — it lives on the company, and
completion is a row in a table follow-ups own. Architecture §9.3's "Watch out for"
lists this first because it is the mistake this design invites.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.domain.engagement_views import ConversationMove, ConversationView
from app.modules.onboarding.domain.entities.engagement_enums import ExporterConversation
from app.modules.onboarding.domain.entities.exporter_enums import (
    CompanyPipelineStatus,
    ExporterJourney,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.exceptions import (
    CompanyNotInPipelineError,
    ConversationCheckBackInPastError,
    ConversationCheckBackNotAllowedError,
    ConversationCheckBackRequiredError,
    ConversationNotAvailableError,
    ExporterProfileNotFoundError,
    InvalidConversationTransitionError,
)
from app.shared.exceptions import ValidationError

logger = structlog.get_logger(__name__)

#: The history dimension, fixed by `docs/contracts/history-row.md` §2. Never
#: invented: the contract is what records what the value means.
HISTORY_DIMENSION_CONVERSATION = "conversation"

#: The journeys the gauge applies to — "from PROSPECT onward".
#: `CUSTOMER` is "onward": an existing customer's next shipment is a fresh
#: conversation.
_GAUGED_JOURNEYS = frozenset({ExporterJourney.PROSPECT, ExporterJourney.CUSTOMER})

#: The one value that carries a reason and a check-back date (engagement contract
#: §4). Written as a set rather than an `is NOT_NOW` comparison so that
#: `allowed_moves` and `set_conversation` read the same rule from one place.
_NEEDS_REASON = frozenset({ExporterConversation.NOT_NOW})
_NEEDS_CHECK_BACK = frozenset({ExporterConversation.NOT_NOW})


class ConversationService:
    """Reads and writes the conversation gauge.

    Holds the caller's session and never opens its own, so
    ``mark_ready_now_for_opened_deal`` can join a transaction ``DealService``
    started.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._history = HistoryService(db)

    # ── Read ─────────────────────────────────────────────────────────────────

    async def get_conversation(self, company_id: uuid.UUID) -> ConversationView:
        """The gauge, its check-back date, and the moves the rules allow.

        ``allowed_moves`` here is the **rules'** answer. The route narrows it to
        the moves this viewer may make, because whose role may write is the
        route's business — see the module docstring.
        """
        profile = await self._require_profile(company_id)
        return ConversationView(
            company_id=company_id,
            conversation=profile.conversation,
            check_back_on=profile.conversation_check_back_on,
            journey=profile.journey,
            allowed_moves=tuple(self.allowed_moves(profile.conversation, profile.journey)),
        )

    @staticmethod
    def allowed_moves(
        current: ExporterConversation, journey: ExporterJourney
    ) -> list[ConversationMove]:
        """Every move the rules allow from ``current``, with what each needs.

        Any value may follow any other (engagement contract §1.1) — a
        conversation is a judgement, not a pipeline — so this is every value
        except the one already held, which would record nothing.

        Empty on a ``LEAD``: the gauge applies from ``PROSPECT`` onward,
        so there is no move to offer and
        ``set_conversation`` would refuse every one of them.

        A ``staticmethod`` because it is the rule table and touches no session —
        the same shape as ``ExporterProfileService.allowed_marker_moves``, so a
        reader comparing the two gauges finds the same pattern.
        """
        if journey not in _GAUGED_JOURNEYS:
            return []
        return [
            ConversationMove(
                to=value,
                reason_required=value in _NEEDS_REASON,
                check_back_required=value in _NEEDS_CHECK_BACK,
            )
            for value in ExporterConversation
            if value is not current
        ]

    # ── Write ────────────────────────────────────────────────────────────────

    async def set_conversation(
        self,
        company_id: uuid.UUID,
        conversation: ExporterConversation,
        *,
        reason: str | None = None,
        check_back_on: date | None = None,
        actor_id: str | None,
    ) -> ExporterProfile:
        """Move the conversation gauge, and record the move.

        The rules, in the order they are checked — each one before anything is
        assigned, so a refused move leaves no partial write and no history row:

        1. The company exists (404).
        2. Its journey is ``PROSPECT`` or ``CUSTOMER`` (409).
        3. The move is not to the value already held (409).
        4. ``NOT_NOW`` carries a reason (422) and a check-back date (422), and
           that date is today or later (422).
        5. Nothing else carries a check-back date (422) — refused, not ignored,
           because silently dropping it would leave the operator believing a date
           was stored.

        Moving **away** from ``NOT_NOW`` clears the check-back date, in this same
        transaction and without the caller asking: a stale date would keep the
        company on the Follow-ups list for a conversation that has moved on, and
        ``ck_exporter_profile_conversation_check_back`` refuses the row anyway.

        The gauge, the check-back date and one ``conversation`` history row —
        from, to, reason, the signed-in user — commit together.
        """
        # Locked, so two concurrent moves are judged one after the other and the
        # second sees the first: the history never shows two moves from the same
        # value. The same reason `set_marker` and `record_outcome` lock.
        profile = await self._lock_profile(company_id)
        from_value = profile.conversation

        if profile.journey not in _GAUGED_JOURNEYS:
            raise ConversationNotAvailableError(company_id, profile.journey.value)
        if conversation is from_value:
            raise InvalidConversationTransitionError(company_id, from_value.value)

        cleaned_reason = (reason or "").strip() or None
        if conversation in _NEEDS_REASON and cleaned_reason is None:
            raise ValidationError(
                f"a reason is required to set the conversation to {conversation.value}"
            )

        if conversation in _NEEDS_CHECK_BACK:
            if check_back_on is None:
                raise ConversationCheckBackRequiredError(company_id)
            today = _today()
            if check_back_on < today:
                raise ConversationCheckBackInPastError(company_id, check_back_on, today)
        elif check_back_on is not None:
            raise ConversationCheckBackNotAllowedError(company_id, conversation.value)

        profile.conversation = conversation
        # `None` for every value but `NOT_NOW`, which is what clears a stale date
        # when the conversation moves on.
        profile.conversation_check_back_on = (
            check_back_on if conversation in _NEEDS_CHECK_BACK else None
        )
        await self._record(
            company_id,
            from_value=from_value,
            to_value=conversation,
            actor_id=actor_id,
            reason=cleaned_reason,
            source="conversation_service.set_conversation",
            check_back_on=profile.conversation_check_back_on,
        )
        await self._db.commit()
        await self._db.refresh(profile)

        logger.info(
            "conversation.set.ok",
            company_id=str(company_id),
            from_value=from_value.value,
            to_value=conversation.value,
            check_back_on=str(profile.conversation_check_back_on),
            actor_id=actor_id,
        )
        return profile

    # ── Seam S1: opening a deal sets READY_NOW ───────────────────────────────

    async def mark_ready_now_for_opened_deal(
        self,
        company_id: uuid.UUID,
        *,
        deal_id: uuid.UUID,
        actor_id: str,
    ) -> None:
        """Set conversation to READY_NOW because a deal was opened.

        Idempotent: already READY_NOW writes no history row. Flushes; does not
        commit — the caller owns the transaction, so the deal row, the deal
        history row and this gauge move land together or not at all.

        Architecture §3.3: "READY_NOW … The screen offers to open a deal; opening
        a deal also sets this." ``DealService`` calls this from
        ``DealService.open_deal``, in the same session, passing ``deal_id`` so the
        history row says which deal did it (history contract §2).

        Three deliberate differences from ``set_conversation``, each stated in the
        engagement contract §6 so deals can rely on them:

        * **No journey check.** A deal is only opened for a company that got that
          far, and refusing the gauge move *after* the deal row is written would
          fail the deal's whole transaction over a gauge.
        * **No role check.** The deal route's roles are the deal route's to enforce;
          a second gate here would be a second copy of them, drifting.
        * **Idempotent rather than refusing.** Opening a second deal for a
          company that is already ready is normal, not an error — so this is the
          one path that may be called with the value unchanged.

        The check-back date is cleared if the company was ``NOT_NOW``: the
        database requires it (``ck_exporter_profile_conversation_check_back``), and
        a company with an open deal is not waiting to be called back.
        """
        profile = await self._lock_profile(company_id)
        from_value = profile.conversation
        if from_value is ExporterConversation.READY_NOW:
            logger.debug(
                "conversation.ready_now_for_deal.noop",
                company_id=str(company_id),
                deal_id=str(deal_id),
            )
            return

        profile.conversation = ExporterConversation.READY_NOW
        profile.conversation_check_back_on = None
        await self._record(
            company_id,
            from_value=from_value,
            to_value=ExporterConversation.READY_NOW,
            actor_id=actor_id,
            reason=None,
            source="conversation_service.mark_ready_now_for_opened_deal",
            check_back_on=None,
            deal_id=deal_id,
            details={"cause": "deal_opened"},
        )
        # Flush, never commit: the caller owns the transaction.
        #
        # `HistoryService.record` has already flushed this session, and the column
        # change above was dirty when it did, so both statements are on the wire by
        # now. This call is therefore usually a no-op — it is here so that "flushes;
        # does not commit" is true of *this* method rather than true only as long as
        # the shared history writer keeps flushing. ``DealService`` relies on that
        # sentence, and it should not depend on another service's internals.
        await self._db.flush()

        logger.info(
            "conversation.ready_now_for_deal.ok",
            company_id=str(company_id),
            from_value=from_value.value,
            deal_id=str(deal_id),
            actor_id=actor_id,
        )

    # ── Internals ────────────────────────────────────────────────────────────

    async def _record(
        self,
        company_id: uuid.UUID,
        *,
        from_value: ExporterConversation,
        to_value: ExporterConversation,
        actor_id: str | None,
        reason: str | None,
        source: str,
        check_back_on: date | None,
        deal_id: uuid.UUID | None = None,
        details: dict | None = None,
    ) -> None:
        """One ``conversation`` history row. Flushes; does not commit.

        ``from_value`` is always a real value here, never ``None``: the column has
        a ``NOT_CONTACTED`` default, so every row this service writes is a
        transition. That is also why no ``conversation_initial`` row is ever
        written — see the engagement contract §8. ``event_type`` is therefore left
        to ``HistoryService``, which derives ``conversation_transition`` from the
        dimension and the presence of ``from_value``.

        The values are passed as ``.value`` strings, per the history contract: the
        columns are ``varchar`` so the log can outlive an enum change, and they are
        validated against ``ExporterConversation`` before they get here by being
        typed as enum members all the way in.
        """
        await self._history.record(
            company_id,
            dimension=HISTORY_DIMENSION_CONVERSATION,
            from_value=from_value.value,
            to_value=to_value.value,
            actor_id=actor_id,
            reason=reason,
            source=source,
            deal_id=deal_id,
            details={
                # Recorded on every row, including as `null` when a move clears a
                # date: "this move cleared the check-back" is worth reading, and
                # its absence would be indistinguishable from an older row.
                "check_back_on": check_back_on.isoformat() if check_back_on else None,
                **(details or {}),
            },
        )

    async def _require_profile(self, company_id: uuid.UUID) -> ExporterProfile:
        result = await self._db.execute(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            raise ExporterProfileNotFoundError(company_id)
        return profile

    async def _lock_profile(self, company_id: uuid.UUID) -> ExporterProfile:
        """The company row, locked for the rest of the transaction and read fresh
        — as ``ExporterProfileService._lock_profile`` and ``QualificationService``
        do before a decision."""
        result = await self._db.execute(
            select(ExporterProfile)
            .where(ExporterProfile.customer_id == company_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            raise ExporterProfileNotFoundError(company_id)
        # A buyer-only company is not being sold to. Refused on the
        # locking path, which every write in this service goes through, rather
        # than once per route: a sales step that slipped past would move the
        # journey and be refused by `ck_exporter_profile_not_in_pipeline_start`
        # as a constraint violation instead of a clear 409.
        if profile.pipeline_status is CompanyPipelineStatus.NOT_IN_PIPELINE:
            raise CompanyNotInPipelineError(company_id)
        return profile


def _today() -> date:
    """Today, from the server clock.

    UTC rather than a business timezone. The only thing this date is compared
    against is an operator's "check back on" choice, and India is UTC+5:30, so the
    UTC date is never *ahead* of the Indian one — which makes this the permissive
    side of the boundary. It can accept a date that is already yesterday in IST
    for a few hours after midnight UTC; it can never reject one an operator would
    call today. Rejecting a legitimate "today" is the failure worth avoiding.
    """
    return datetime.now(UTC).date()


__all__ = ["HISTORY_DIMENSION_CONVERSATION", "ConversationService"]
