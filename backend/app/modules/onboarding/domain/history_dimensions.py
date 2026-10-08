"""The shared history log's ``dimension`` values (``docs/contracts/history-row.md`` §2).

``dimension`` is a plain string column on purpose (history-row §1): a new dimension
needs no migration. This module is the code's one list of them, so a writer imports
its constant instead of typing the string, and the read route's DEVELOPER rule names the
same values the writers use. ``history-row.md`` §2 remains the definition of what each
one means; a value added here without a row there is the thing that contract exists
to prevent.

``relationship_manager`` and ``background_check_assignment`` record who is working on a
company. The five before them were added together: ``check_cycle`` and ``background_check_approval``
(the compliance engine), and ``gst_registration``, ``trade`` and ``pipeline`` (the
company record).
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
#: A check cycle started (Re-KYC / Re-KYB).
CHECK_CYCLE = "check_cycle"
#: A maker-checker proposal proposed / approved / rejected / withdrawn.
BACKGROUND_CHECK_APPROVAL = "background_check_approval"
#: A GST registration added, deactivated, flagged or unflagged.
GST_REGISTRATION = "gst_registration"
#: A trade relationship, invoice or payment outcome recorded.
TRADE = "trade"
#: A company entering or leaving the sales pipeline.
PIPELINE = "pipeline"
#: A company's relationship manager assigned, reassigned or cleared.
RELATIONSHIP_MANAGER = "relationship_manager"
#: A background-check review claimed, assigned, reassigned, released or ended.
BACKGROUND_CHECK_ASSIGNMENT = "background_check_assignment"

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
    RELATIONSHIP_MANAGER,
    BACKGROUND_CHECK_ASSIGNMENT,
)

#: Dimensions DEVELOPER does not receive from the history routes: the
#: background check, its inputs, its cycles and its approvals carry the values,
#: reasons, review notes and comments DEVELOPER is refused on their own routes. Who
#: holds a review is compliance work too.
HIDDEN_FROM_DEVELOPER: frozenset[str] = frozenset(
    {
        BACKGROUND_CHECK,
        VERIFICATION,
        SCREENING,
        CHECK_CYCLE,
        BACKGROUND_CHECK_APPROVAL,
        BACKGROUND_CHECK_ASSIGNMENT,
    }
)

__all__ = [
    "ALL_DIMENSIONS",
    "BACKGROUND_CHECK",
    "BACKGROUND_CHECK_APPROVAL",
    "BACKGROUND_CHECK_ASSIGNMENT",
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
    "RELATIONSHIP_MANAGER",
    "SCREENING",
    "TRADE",
    "VERIFICATION",
]
