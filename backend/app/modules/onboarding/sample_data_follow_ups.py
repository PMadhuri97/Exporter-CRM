"""Sample data for follow-up completion — **owner: Developer 3A, Phase 2**
(L3-04b).

A hook, called once from ``sample_data.py``'s ``load_sample_data``. That file is
Developer 2's and was edited once, in the seam commit; this seeder is why Phase 2
never has to open it.

**What it seeds, and why it logs activities of its own.** Developer 2's sample data
gives exactly one activity a ``due_at`` — company A's "Check back on Q1 shipments" —
which is one row, and a Follow-ups screen with one outstanding row demonstrates
neither *overdue* nor *done*. Rather than edit Dev 2's file to add more, this seeder
logs the follow-ups it needs against the companies Dev 2 created, which is what this
prompt's §2 asks of it ("seed completed and outstanding follow-ups against the
companies Phase 1's seeder creates"). The result covers all three states a person
opening the screen should see:

* **overdue** — a follow-up whose due date has passed and which nobody has dealt with
* **outstanding** — one due in the future
* **done** — one with a completion row, including a ``RESCHEDULED`` one, which leaves
  a *second*, outstanding follow-up behind it, so the reschedule chain is visible too

**Converges, never duplicates** — the same rule as every other step in
``sample_data.py``. Each follow-up is matched by ``(customer_id, subject)``, and each
completion by whether one already points at the activity. A repeat run reports zero; a
run interrupted halfway is finished by the next one.

**Through the service**, so every rule applies exactly as it does for a person using
the CRM: the refusal on an activity with no due date, the one-completion-per-follow-up
rule, and the future-date rule on a reschedule.

Due dates are **relative to today**, never literals. A literal would rot: the moment
the clock passed it, the "outstanding" row would become overdue and a
``RESCHEDULED`` seed would start failing the future-date check.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select

from app.modules.onboarding.application.exporter_contact_activity_service import (
    ExporterContactActivityService,
)
from app.modules.onboarding.application.follow_up_service import FollowUpService
from app.modules.onboarding.domain.entities.engagement_enums import ExporterActivityType
from app.modules.onboarding.domain.entities.exporter_activity import ExporterActivity
from app.modules.onboarding.domain.entities.follow_up_completion import FollowUpOutcome
from app.platform.database import services as db_services

logger = structlog.get_logger(__name__)

#: The actor on seeded follow-ups. `exporter_activity.actor_id` is NOT NULL, so a
#: seeded activity needs a name; `SAMPLE_DATA_ACTOR` is Developer 2's and this reuses
#: it so the whole sample set reads as one hand.
_ACTOR = "sample-data"


@dataclass(frozen=True)
class _SampleFollowUp:
    """One follow-up to seed, and how it should end up.

    ``company_slug`` names a company from Developer 2's ``COMPANIES``; ``due_in_days``
    is relative to now, negative for overdue. ``outcome`` is ``None`` to leave the
    follow-up outstanding.
    """

    company_slug: str
    subject: str
    due_in_days: int
    notes: str | None = None
    outcome: FollowUpOutcome | None = None
    completion_note: str | None = None
    #: Only for `RESCHEDULED`, relative to now and always positive.
    reschedule_in_days: int | None = None


#: Architecture §3.9 fixes each company's gauges, not its follow-ups, so these are
#: chosen to cover the three states rather than taken from it. Company A said "not
#: now" and already carries a check-back date from Phase 1's seeder, so the screen
#: shows a check-back row for it as well.
_SAMPLE_FOLLOW_UPS: tuple[_SampleFollowUp, ...] = (
    _SampleFollowUp(
        company_slug="company-c",
        subject="Send the Dubai order indicative terms",
        due_in_days=-6,
        notes="Sample data: they are waiting on us — this is what overdue looks like.",
    ),
    _SampleFollowUp(
        company_slug="company-b",
        subject="Confirm the Rotterdam shipment documents",
        due_in_days=9,
        notes="Sample data: outstanding, not yet due.",
    ),
    _SampleFollowUp(
        company_slug="company-b",
        subject="Introductory call with the export manager",
        due_in_days=-20,
        notes="Sample data: done, and done late — late is still done, not overdue.",
        outcome=FollowUpOutcome.DONE,
        completion_note="Sample data: spoke to Anita Rao; nothing outstanding.",
    ),
    _SampleFollowUp(
        company_slug="company-c",
        subject="Chase the audited FY25 accounts",
        due_in_days=-3,
        notes="Sample data: nobody picked up.",
        outcome=FollowUpOutcome.NO_ANSWER,
        completion_note="Sample data: called twice, no answer; closed without a new date.",
    ),
    _SampleFollowUp(
        company_slug="company-a",
        subject="Review the Q1 shipment forecast",
        due_in_days=-1,
        notes="Sample data: moved, which leaves a fresh follow-up behind it.",
        outcome=FollowUpOutcome.RESCHEDULED,
        completion_note="Sample data: they asked for another three weeks.",
        reschedule_in_days=21,
    ),
)


def _at(days: int) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


async def load_follow_up_sample_data() -> int:
    """Seed the sample follow-ups and their completions.

    Returns the number of **completions** this run recorded — the number the report
    row is named for (``follow_ups_completed``). ``0`` on a repeat run. Logging a
    missing follow-up activity is not counted: it is setup for a completion, and
    counting it would make the figure mean two things.
    """
    # Imported here, not at module scope: `sample_data` imports this module, so a
    # module-level import back into it would be circular.
    from app.modules.onboarding.sample_data import COMPANIES

    by_slug = {company.slug: company.customer_id for company in COMPANIES}

    completed = 0
    for sample in _SAMPLE_FOLLOW_UPS:
        customer_id = by_slug.get(sample.company_slug)
        if customer_id is None:
            # A company Developer 2 renamed or removed. Skipped rather than raised:
            # sample data that refuses to load is worse than sample data with one
            # fewer row, and the log line is enough to find it.
            logger.warning(
                "sample_data.follow_up.unknown_company", slug=sample.company_slug
            )
            continue
        activity_id = await _ensure_follow_up(customer_id, sample)
        if activity_id is None:
            continue
        if sample.outcome is not None and await _ensure_completion(activity_id, sample):
            completed += 1
    return completed


async def _ensure_follow_up(
    customer_id: uuid.UUID, sample: _SampleFollowUp
) -> uuid.UUID | None:
    """The activity for this follow-up, logging it if it is not already there.

    Matched by ``(customer_id, subject)``, the same way Developer 2's seeder matches
    activities. Returns its id, or ``None`` if the company does not exist yet — which
    happens only if this hook is somehow called before Dev 2's company step.
    """
    async with db_services.AsyncSessionLocal() as db:
        existing = await db.scalar(
            select(ExporterActivity).where(
                ExporterActivity.customer_id == customer_id,
                ExporterActivity.subject == sample.subject,
            )
        )
    if existing is not None:
        return existing.id

    async with db_services.AsyncSessionLocal() as db:
        activity = await ExporterContactActivityService(db).log_activity(
            customer_id,
            activity_type=ExporterActivityType.FOLLOW_UP,
            subject=sample.subject,
            notes=sample.notes,
            due_at=_at(sample.due_in_days),
            actor_id=_ACTOR,
            occurred_at=_at(sample.due_in_days - 7),
        )
    return activity.id


async def _ensure_completion(activity_id: uuid.UUID, sample: _SampleFollowUp) -> bool:
    """Complete this follow-up unless it already has a completion.

    Goes through ``FollowUpService``, so a ``RESCHEDULED`` seed logs its replacement
    follow-up exactly as a person's reschedule would — which is what puts a second,
    outstanding row on the screen behind the completed one.
    """
    from app.modules.onboarding.infrastructure.repositories import (
        FollowUpCompletionRepository,
    )

    async with db_services.AsyncSessionLocal() as db:
        if await FollowUpCompletionRepository(db).get_by_activity(activity_id) is not None:
            return False

    next_due_at = (
        _at(sample.reschedule_in_days)
        if sample.outcome is FollowUpOutcome.RESCHEDULED and sample.reschedule_in_days
        else None
    )
    async with db_services.AsyncSessionLocal() as db:
        await FollowUpService(db).complete_follow_up(
            activity_id,
            sample.outcome,
            note=sample.completion_note,
            next_due_at=next_due_at,
            # The platform acting on its own, the meaning `None` carries everywhere in
            # this CRM. Developer 2's seeder records history rows the same way.
            actor_id=None,
        )
    return True


__all__ = ["load_follow_up_sample_data"]
