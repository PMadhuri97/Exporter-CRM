"""The shared history log's ``dimension`` values — **owner: Developer 1** (the history
log, ``docs/contracts/history-row.md`` §2; allocation F1).

``dimension`` is a plain string column on purpose (history-row §1): a new dimension
needs no migration. This module is the code's one list of them, so a writer imports
its constant instead of typing the string, and the read route's D8 rule names the
same values the writers use. ``history-row.md`` §2 remains the definition of what each
one means; a value added here without a row there is the thing that contract exists
to prevent.

The last five were added together in F1 so that no lane edits this list again
(allocation §2.2): ``check_cycle`` and ``background_check_approval`` are Developer 1's,
``gst_registration``, ``trade`` and ``pipeline`` Developer 3's. Developer 1's two have
writers (``check_cycle``, plan P2-3c; ``background_check_approval``, plan P3-1b);
Developer 3's have none yet.
"""

from __future__ import annotations

JOURNEY = "journey"
QUALIFICATION = "qualification"
MARKER = "marker"
PROFILE = "profile"
CONVERSATION = "conversation"
DEAL = "deal"
BACKGROUND_CHECK = "background_check"
VERIFICATION = "verification"
SCREENING = "screening"
#: A check cycle started (Re-KYC / Re-KYB) — Developer 1, plan P2-3c.
CHECK_CYCLE = "check_cycle"
#: A maker-checker proposal proposed / approved / rejected / withdrawn — Developer 1,
#: plan P3-1b.
BACKGROUND_CHECK_APPROVAL = "background_check_approval"
#: A GST registration added, deactivated, flagged or unflagged — Developer 3, P6-2/P6-5.
GST_REGISTRATION = "gst_registration"
#: A trade relationship, invoice or payment outcome recorded — Developer 3, P5-3/P5-4.
TRADE = "trade"
#: A company entering or leaving the sales pipeline — Developer 3, P4-6/P4-9.
PIPELINE = "pipeline"

ALL_DIMENSIONS: tuple[str, ...] = (
    JOURNEY,
    QUALIFICATION,
    MARKER,
    PROFILE,
    CONVERSATION,
    DEAL,
    BACKGROUND_CHECK,
    VERIFICATION,
    SCREENING,
    CHECK_CYCLE,
    BACKGROUND_CHECK_APPROVAL,
    GST_REGISTRATION,
    TRADE,
    PIPELINE,
)

#: Dimensions DEVELOPER does not receive from the history routes (decision D8): the
#: background check, its inputs, its cycles and its approvals carry the values,
#: reasons, review notes and comments D8 refuses DEVELOPER on their own routes.
HIDDEN_FROM_DEVELOPER: frozenset[str] = frozenset(
    {BACKGROUND_CHECK, VERIFICATION, SCREENING, CHECK_CYCLE, BACKGROUND_CHECK_APPROVAL}
)

__all__ = [
    "ALL_DIMENSIONS",
    "BACKGROUND_CHECK",
    "BACKGROUND_CHECK_APPROVAL",
    "CHECK_CYCLE",
    "CONVERSATION",
    "DEAL",
    "GST_REGISTRATION",
    "HIDDEN_FROM_DEVELOPER",
    "JOURNEY",
    "MARKER",
    "PIPELINE",
    "PROFILE",
    "QUALIFICATION",
    "SCREENING",
    "TRADE",
    "VERIFICATION",
]
