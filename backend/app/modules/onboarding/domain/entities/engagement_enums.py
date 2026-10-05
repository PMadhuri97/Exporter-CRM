"""Enums for contacts and the activity log (architecture §8.1, §9.3).

Split out of `exporter_enums.py`, which now holds only the company's
own values. `ExporterConversation` belongs here for the same
reason, and is deliberately **not** added to that file: the conversation gauge is
engagement, and `exporter_enums.py` is where the company record's values
live.

The database enums these map to are `onboarding.exporter_activity_type_enum`
(migration 0005) and `onboarding.exporter_conversation_enum` (0016), named on
their columns in `exporter_activity.py` and `exporter_profile.py`. Moving or
adding a Python class here changes no schema on its own.
"""

import enum


class ExporterActivityType(str, enum.Enum):
    CALL = "CALL"
    MEETING = "MEETING"
    EMAIL = "EMAIL"
    NOTE = "NOTE"
    TASK = "TASK"
    FOLLOW_UP = "FOLLOW_UP"


class ExporterConversation(str, enum.Enum):
    """How the sales conversation is going — architecture §3.3, and
    `docs/contracts/engagement.md` §1.

    One thing only. Not the journey (`ExporterJourney`), not whether the company
    met our requirements (`QualificationState`), not whether it is safe to lend
    to (the background check), and not a commercial pause
    (`ExporterMarker`). Collapsing those into one line is what the retired
    ten-status `ExporterLifecycleStatus` did.

    **Any value may follow any other** (contract §1.1). A conversation is a
    judgement, not a pipeline: someone who said `NOT_NOW` in March can be
    `READY_NOW` in April without passing back through `INTERESTED`. So there is
    no transition table here, and none in the frontend — the server serves the
    moves a given user may make (contract §3.1). The only refusal is a move to
    the value already held.

    Two rules deliberately do **not** live in this enum, and must not be
    inferred from the order of its members:

    * The gauge applies **from `PROSPECT` onward**. A `LEAD`
      reads `NOT_CONTACTED` because the column is `NOT NULL`, not because
      anyone judged its conversation.
    * `NOT_NOW` carries a reason **and** a check-back date
      (`exporter_profile.conversation_check_back_on`).

    Both belong to `ConversationService`, the column's only writer.
    """

    NOT_CONTACTED = "NOT_CONTACTED"
    REACHING_OUT = "REACHING_OUT"
    SPOKE_TO_THEM = "SPOKE_TO_THEM"
    INTERESTED = "INTERESTED"
    NOT_NOW = "NOT_NOW"
    READY_NOW = "READY_NOW"


__all__ = ["ExporterActivityType", "ExporterConversation"]
