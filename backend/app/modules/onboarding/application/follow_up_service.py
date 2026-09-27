"""``FollowUpService`` — completing follow-ups, and the due/overdue list
(L3-04b). **Owner: Developer 3A, Phase 2.**

What we owe an exporter next, and whether we did it. The contract is
``docs/contracts/engagement.md`` §5.

**Completing a follow-up inserts a row. It never updates one.**
``exporter_activity`` is append-only, enforced by
``trg_exporter_activity_append_only``, so there is no ``completed_at`` on the
activity to set and there must never be one. Architecture §9.3's "Watch out for"
lists this mistake first because it is the one this design invites. A completion is a
``follow_up_completion`` row; ``follow_up_completion`` is append-only too, so a
correction is a **new activity** plus its own completion.

**A reschedule is a new activity, not a moved date.** Nothing may change an
activity's ``due_at``, and nothing should: the old row is the record of what was
promised, and the promise did get broken. So ``RESCHEDULED`` writes the completion
*and* logs a fresh follow-up for the new moment, in one transaction, so the list can
never show a rescheduled follow-up with nothing to replace it.

**Follow-ups are the whole team's** (decision D2). The list is a reader route with no
default owner filter; ``actor_id`` narrows it and never gates it. Who may *complete*
one is the route's business, via ``require_role`` — the three staff roles, per
contract §5.5.

**No history row.** A completion is its own permanent record, and
``docs/contracts/history-row.md`` §2 fixes the dimension list: ``conversation``,
``journey``, ``qualification``, ``marker``, ``profile``, ``deal``,
``background_check``, ``verification``. None of them is a follow-up, ``engagement.md``
does not ask for one, and this prompt's §7.4 says not to invent a ``follow_up``
dimension. The conversation gauge is what the history log carries for this
developer's slice, and that is Phase 1's. Recorded explicitly in ``engagement.md``
§5.7 so the next reader does not have to infer it from silence.

**One transaction per operation.** Every write goes through the session the service
was given; the completion and any replacement activity are flushed together and
committed once at the end, so a reschedule cannot leave a completion with no
replacement.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.engagement_enums import ExporterActivityType
from app.modules.onboarding.domain.entities.exporter_activity import ExporterActivity
from app.modules.onboarding.domain.entities.follow_up_completion import (
    FollowUpCompletion,
    FollowUpOutcome,
)
from app.modules.onboarding.domain.follow_up_views import (
    CheckBackView,
    FollowUpCompletionView,
    FollowUpListView,
    FollowUpState,
    FollowUpView,
)
from app.modules.onboarding.exceptions import (
    ActivityIsNotAFollowUpError,
    FollowUpAlreadyCompletedError,
    FollowUpCompletionIsImmutableError,
    FollowUpNextDueNotAllowedError,
    FollowUpNotFoundError,
    FollowUpRescheduleInPastError,
    FollowUpRescheduleNeedsDateError,
)
from app.modules.onboarding.infrastructure.repositories import (
    ExporterActivityRepository,
    FollowUpCompletionRepository,
)

logger = structlog.get_logger(__name__)

#: The one outcome that carries — and requires — a new due moment (contract §5.3).
#: A set rather than an `is RESCHEDULED` comparison so the two directions of the rule
#: are read from one place.
_NEEDS_NEXT_DUE = frozenset({FollowUpOutcome.RESCHEDULED})


class FollowUpService:
    """Completes follow-ups and reads the due/overdue list.

    Holds the caller's session and never opens its own, so a caller that already has a
    transaction can complete a follow-up inside it.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._completions = FollowUpCompletionRepository(db)
        # Phase 1's repository, **used** and not extended: the phase agreement (§6.3)
        # forbids adding a method to it, not calling the ones it has. A reschedule
        # needs to log a replacement activity, and `AppendOnlyRepository.create` is
        # already the way every activity in this CRM is written.
        self._activities = ExporterActivityRepository(db)

    # ── Write ────────────────────────────────────────────────────────────────

    async def complete_follow_up(
        self,
        activity_id: uuid.UUID,
        outcome: FollowUpOutcome,
        *,
        note: str | None = None,
        next_due_at: datetime | None = None,
        actor_id: str | None,
    ) -> FollowUpCompletion:
        """Record that a follow-up was dealt with. Returns the completion row.

        The rules, in the order they are checked — each one before anything is
        written, so a refusal leaves neither a completion nor a replacement activity:

        1. The activity exists (404). Its row is locked from here to the commit, so
           a concurrent completion of the same follow-up waits and then meets rule 3.
        2. It carries a ``due_at``, so it is a follow-up at all (409).
        3. It has no completion already (409) — a refusal, never an upsert.
        4. ``RESCHEDULED`` carries a ``next_due_at`` (422), and that moment is in the
           future (422).
        5. No other outcome carries one (422) — refused, not ignored, because
           silently dropping it would leave the operator believing the follow-up had
           been moved rather than closed.

        On ``RESCHEDULED`` this also logs a **new** follow-up activity for
        ``next_due_at``, in the same transaction. The original activity is untouched,
        as it must be: it is the record of what was promised.
        """
        activity = await self._require_follow_up(activity_id)

        existing = await self._completions.get_by_activity(activity_id)
        if existing is not None:
            raise FollowUpAlreadyCompletedError(
                activity_id, existing.id, existing.outcome.value
            )

        if outcome in _NEEDS_NEXT_DUE:
            if next_due_at is None:
                raise FollowUpRescheduleNeedsDateError(activity_id)
            if next_due_at <= _now():
                raise FollowUpRescheduleInPastError(activity_id, next_due_at.isoformat())
        elif next_due_at is not None:
            raise FollowUpNextDueNotAllowedError(activity_id, outcome.value)

        completion = await self._completions.create(
            FollowUpCompletion(
                activity_id=activity_id,
                # Denormalised from the activity, never from the caller: the company
                # a follow-up belongs to is the activity's to say (contract §5.2).
                customer_id=activity.customer_id,
                outcome=outcome,
                note=(note or "").strip() or None,
                next_due_at=next_due_at,
                # From the login session, never from a request body (§7.5).
                completed_by=actor_id,
            )
        )

        replacement: ExporterActivity | None = None
        if outcome in _NEEDS_NEXT_DUE:
            replacement = await self._log_replacement(
                activity, next_due_at=next_due_at, actor_id=actor_id
            )

        await self._db.commit()
        await self._db.refresh(completion)

        logger.info(
            "follow_up.completed",
            activity_id=str(activity_id),
            completion_id=str(completion.id),
            customer_id=str(activity.customer_id),
            outcome=outcome.value,
            replacement_activity_id=str(replacement.id) if replacement is not None else None,
            actor_id=actor_id,
        )
        return completion

    async def _log_replacement(
        self,
        original: ExporterActivity,
        *,
        next_due_at: datetime,
        actor_id: str | None,
    ) -> ExporterActivity:
        """Log the follow-up that replaces a rescheduled one. Flushes; the caller
        commits.

        Keeps the original subject, so the list reads as one continuing promise rather
        than as an unrelated new task, and records in the notes when it was moved
        from — the only place that fact would otherwise live is the completion row,
        which is attached to the *old* activity.

        ``FOLLOW_UP`` regardless of the original's type: what is being created is a
        thing somebody now owes, which is what that type means. A rescheduled
        ``MEETING`` is not another meeting that happened; it is a promise to meet.
        ``actor_id`` is whoever rescheduled it, not whoever logged the original —
        they are the person who now owns it.
        """
        return await self._activities.create(
            ExporterActivity(
                customer_id=original.customer_id,
                activity_type=ExporterActivityType.FOLLOW_UP,
                subject=original.subject,
                notes=(
                    f"Rescheduled from {original.due_at.isoformat()}."
                    + (f" {original.notes}" if original.notes else "")
                ),
                actor_id=actor_id or "platform",
                occurred_at=_now(),
                due_at=next_due_at,
            )
        )

    # ── Read ─────────────────────────────────────────────────────────────────

    async def list_follow_ups(
        self,
        *,
        state: FollowUpState | None = None,
        customer_id: uuid.UUID | None = None,
        actor_id: str | None = None,
        activity_type: ExporterActivityType | None = None,
        due_before: datetime | None = None,
        due_after: datetime | None = None,
        include_check_backs: bool = True,
        check_backs_due_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> FollowUpListView:
        """The Follow-ups screen's answer: follow-ups, and companies parked at
        ``NOT_NOW``.

        No default owner filter — follow-ups are the whole team's (decision D2), and
        ``actor_id`` narrows the list rather than gating it.

        ``now`` is taken **once** and used for every ``is_overdue`` in the response, so
        no two rows of one answer are judged against different clocks. That is why the
        repository takes it as an argument instead of calling
        ``datetime.now()`` itself.

        Check-backs ignore ``state``, ``actor_id`` and ``activity_type``: none of them
        applies to a company parked at ``NOT_NOW``, which has no activity and no
        completion. They ignore ``offset`` too — see the comment below — and
        ``include_check_backs=False`` leaves them out entirely for a caller that only
        wants activities.

        ``check_backs_due_only=True`` keeps only the check-backs that are due — on or
        before today — so an "Overdue" view does not list a company parked until next
        quarter beside the work that is late. "Today" is the same UTC date
        ``is_overdue`` is judged against, from the same single ``now``.
        """
        now = _now()
        rows = await self._completions.list_follow_ups(
            now=now,
            state=state,
            customer_id=customer_id,
            actor_id=actor_id,
            activity_type=activity_type,
            due_before=due_before,
            due_after=due_after,
            limit=limit,
            offset=offset,
        )
        total = await self._completions.count_follow_ups(
            now=now,
            state=state,
            customer_id=customer_id,
            actor_id=actor_id,
            activity_type=activity_type,
            due_before=due_before,
            due_after=due_after,
        )

        check_backs: tuple[CheckBackView, ...] = ()
        check_backs_total = 0
        if include_check_backs:
            # `limit` is honoured; `offset` deliberately is not. `offset` pages the
            # follow-ups, and applying it to a second, unrelated list would silently
            # drop every check-back the moment a caller asked for page two — a bug
            # that looks like "the check-backs disappeared". Check-backs are a small
            # set (companies parked at NOT_NOW) shown as their own section rather than
            # a paged table, so the first `limit` of them, with a true
            # `check_backs_total` beside them, is the useful answer. A caller that
            # needs to page them can ask per company.
            due_on_or_before = now.date() if check_backs_due_only else None
            profiles = await self._completions.list_check_backs(
                customer_id=customer_id,
                due_on_or_before=due_on_or_before,
                limit=limit,
                offset=0,
            )
            check_backs = tuple(_check_back_view(p, today=now.date()) for p in profiles)
            check_backs_total = await self._completions.count_check_backs(
                customer_id=customer_id, due_on_or_before=due_on_or_before
            )

        return FollowUpListView(
            follow_ups=tuple(
                _follow_up_view(activity, completion, name, now=now)
                for activity, completion, name in rows
            ),
            follow_ups_total=total,
            check_backs=check_backs,
            check_backs_total=check_backs_total,
        )

    # ── The lock, as a service-level refusal ─────────────────────────────────

    async def refuse_completion_edit(self, completion_id: uuid.UUID) -> None:
        """Always raises ``FollowUpCompletionIsImmutableError``.

        Phase 2 adds no constraint, so what it owes the database instead is the
        service-level proof that the existing lock holds (prompt §3). There is no
        "edit a completion" route and there never will be one; this method exists so
        that the refusal is a named, tested behaviour of the service rather than an
        absence somebody could fill in later without noticing.

        The database says the same thing independently:
        ``trg_follow_up_completion_append_only`` raises on UPDATE and DELETE, and
        ``FollowUpCompletionRepository`` exposes neither, so there are three layers
        and this is the one that produces a clean 409 instead of a 500.
        """
        raise FollowUpCompletionIsImmutableError(completion_id)

    # ── Internals ────────────────────────────────────────────────────────────

    async def _require_follow_up(self, activity_id: uuid.UUID) -> ExporterActivity:
        """The activity, if it exists and is a follow-up.

        Two separate refusals on purpose: "no such activity" (404) and "that activity
        is not something anyone promised to do" (409) send a person looking in
        completely different places.

        **Locked** for the rest of the transaction, so two people completing the same
        follow-up at once are judged one after the other: the second waits here, then
        finds the first one's completion and gets ``FOLLOW_UP_ALREADY_COMPLETED`` (409)
        instead of tripping ``uq_follow_up_completion_activity_id`` as a 500. The same
        reason ``set_marker`` and ``set_conversation`` lock their row. ``SELECT … FOR
        UPDATE`` is not an ``UPDATE``, so the activity's append-only trigger does not
        fire.
        """
        result = await self._db.execute(
            select(ExporterActivity)
            .where(ExporterActivity.id == activity_id)
            .with_for_update()
        )
        activity = result.scalar_one_or_none()
        if activity is None:
            raise FollowUpNotFoundError(activity_id)
        if activity.due_at is None:
            raise ActivityIsNotAFollowUpError(activity_id)
        return activity


def _follow_up_view(
    activity: ExporterActivity,
    completion: FollowUpCompletion | None,
    exporter_display_name: str | None,
    *,
    now: datetime,
) -> FollowUpView:
    """One row, with ``is_overdue`` judged against the caller's single ``now``.

    A completed follow-up is **not** overdue whatever its due date: it was dealt
    with, late or not, and leaving it flagged would make the overdue count a list of
    old work rather than of outstanding work.
    """
    assert activity.due_at is not None  # the query filters on `due_at IS NOT NULL`
    return FollowUpView(
        activity_id=activity.id,
        customer_id=activity.customer_id,
        exporter_display_name=exporter_display_name,
        activity_type=activity.activity_type,
        subject=activity.subject,
        notes=activity.notes,
        actor_id=activity.actor_id,
        occurred_at=activity.occurred_at,
        due_at=activity.due_at,
        is_overdue=completion is None and activity.due_at < now,
        completion=(
            None
            if completion is None
            else FollowUpCompletionView(
                id=completion.id,
                outcome=completion.outcome,
                note=completion.note,
                next_due_at=completion.next_due_at,
                completed_by=completion.completed_by,
                completed_at=completion.completed_at,
            )
        ),
    )


def _check_back_view(profile, *, today: date) -> CheckBackView:
    """One parked company.

    ``is_overdue`` is inclusive of today being past the date but not of today itself:
    a check-back due today is due, not late.
    """
    check_back_on = profile.conversation_check_back_on
    assert check_back_on is not None  # the query filters on IS NOT NULL
    return CheckBackView(
        customer_id=profile.customer_id,
        exporter_display_name=profile.name,
        conversation=profile.conversation,
        check_back_on=check_back_on,
        is_overdue=check_back_on < today,
    )


def _now() -> datetime:
    """The server clock, UTC and timezone-aware.

    Aware, not naive: every ``timestamptz`` column in this schema comes back aware, and
    comparing an aware column to a naive ``now`` raises rather than quietly comparing
    wrong.
    """
    return datetime.now(UTC)


__all__ = ["FollowUpService"]
