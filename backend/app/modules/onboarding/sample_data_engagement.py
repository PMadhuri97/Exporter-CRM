"""Sample data for the conversation gauge.

A hook, called once from ``sample_data.py``'s ``load_sample_data``, so that file
gained one call site and is never edited for this again.

**What it seeds.** Architecture §3.9 gives each sample company a conversation
value, recorded on ``SampleCompany.target["conversation"]`` in ``sample_data.py`` for
exactly this moment. This reads that target rather than keeping a second copy of
it: §3.9 is the source, and a company whose target changes needs no edit here.

**Converges, never duplicates** — the same rule as every other step in
``sample_data.py``. A company already at its target value is left alone, so a
repeat run writes no second history row. A run interrupted halfway is finished by
the next one, because each company is a separate transaction.

**Through the service**, so every rule applies exactly as it does for a person
using the CRM: the reason and check-back date ``NOT_NOW`` requires, the refusal on
a ``LEAD``, the history row in the same transaction. Two consequences worth
naming:

* A company whose journey is still ``LEAD`` is **skipped**, not forced. The gauge
  applies from ``PROSPECT`` onward and sample data does not get a
  private exemption from the rules it exists to demonstrate.
* Company B's §3.9 target is ``READY_NOW`` with two deals. The deals are
  seeded by ``sample_data_deals.py``, so this sets the gauge directly
  rather than through seam S1 — the honest thing to do while there is no deal to
  open. When the deals seeder runs, opening those deals finds the gauge already
  ``READY_NOW`` and its seam call is a no-op, which is what makes S1 idempotent.

History rows carry ``actor_id = None`` — the platform acting on its own, per the
history contract — matching every other step in ``sample_data.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import structlog

from app.modules.onboarding.application.conversation_service import ConversationService
from app.modules.onboarding.domain.entities.engagement_enums import ExporterConversation
from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney
from app.platform.database import services as db_services

logger = structlog.get_logger(__name__)

#: The reason a `NOT_NOW` sample company gives. `NOT_NOW` is the one value that
#: requires one (`docs/contracts/engagement.md` §4), and sample data goes through
#: the service, so it has to supply one like anybody else.
_NOT_NOW_REASON = "Sample data: said not now; revisit next quarter"

#: How far ahead a sample `NOT_NOW` check-back date sits. Relative to today rather
#: than a fixed date so the sample data never rots into a past date the service
#: would refuse — which a literal would, the moment the clock passed it.
_CHECK_BACK_DAYS = 45


def _check_back_on() -> date:
    return (datetime.now(UTC) + timedelta(days=_CHECK_BACK_DAYS)).date()


async def load_conversation_sample_data() -> int:
    """Bring each sample company to its §3.9 conversation value.

    Returns the number of companies this run moved — ``0`` on a repeat run, and
    ``0`` for any company whose target is the default or whose journey has not
    reached ``PROSPECT``.
    """
    # Imported here, not at module scope: `sample_data` imports this module, so a
    # module-level import back into it would be circular.
    from app.modules.onboarding.sample_data import COMPANIES

    moved = 0
    for company in COMPANIES:
        target_name = company.target.get("conversation")
        if target_name is None:
            continue
        target = ExporterConversation(target_name)
        if await _ensure_conversation(company.customer_id, target):
            moved += 1
    return moved


async def _ensure_conversation(company_id: uuid.UUID, target: ExporterConversation) -> bool:
    """Move one company's gauge to ``target`` unless it is already there.

    Each company gets its own session and therefore its own transaction, so one
    company's refusal cannot roll back another's move — and a run interrupted
    between two companies is finished by the next one.
    """
    async with db_services.AsyncSessionLocal() as db:
        view = await ConversationService(db).get_conversation(company_id)

    if view.conversation is target:
        return False
    if view.journey is ExporterJourney.LEAD:
        # Not an error and not something to force: the gauge applies from PROSPECT
        # onward, and sample data follows the rules it demonstrates.
        logger.debug(
            "sample_data.conversation.skipped_lead",
            company_id=str(company_id),
            target=target.value,
        )
        return False

    needs_check_back = target is ExporterConversation.NOT_NOW
    async with db_services.AsyncSessionLocal() as db:
        await ConversationService(db).set_conversation(
            company_id,
            target,
            reason=_NOT_NOW_REASON if needs_check_back else None,
            check_back_on=_check_back_on() if needs_check_back else None,
            actor_id=None,
        )
    return True


__all__ = ["load_conversation_sample_data"]
