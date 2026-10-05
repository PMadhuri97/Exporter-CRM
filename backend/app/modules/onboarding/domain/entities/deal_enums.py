"""Enums for deals.

Its own file, deliberately. Not ``exporter_enums.py`` (the company's
values) and not ``engagement_enums.py`` (the conversation gauge): each area has
its own enum module so two people adding a
value never share a hunk.

The database type these map to is ``onboarding.deal_stage_enum`` (migration
0018), named on the column in ``deal.py``. Adding a class here changes no schema
on its own.
"""

import enum


class DealStage(str, enum.Enum):
    """Where a deal has got to — architecture §3.3 ("The deal"), and
    ``docs/contracts/deal-and-buyer.md`` §1.

    One thing only: whether there is a real, current financing need and how far
    the paperwork has got. Not the sales conversation (``ExporterConversation``),
    not whether the company is safe to lend to (the background check),
    and not whether the company met our requirements (``QualificationState``).

    **Unlike the conversation gauge, any-value-to-any-value is not allowed.** A
    stage is a claim about what has happened to a deal, not a judgement about a
    relationship, so the moves are a fixed table (contract §1.1) and an illegal
    one is refused.
    """

    #: A current need has been identified. Opening a deal also sets the
    #: company's conversation to READY_NOW (seam S1).
    OPEN = "OPEN"
    #: Documents and buyer details are being collected.
    GATHERING_PAPERWORK = "GATHERING_PAPERWORK"
    #: Complete, and passed to the lending team. Terminal.
    HANDED_OVER = "HANDED_OVER"
    #: The deal fell through. Terminal, and needs a reason.
    WITHDRAWN = "WITHDRAWN"

    @property
    def is_terminal(self) -> bool:
        """Whether anything may follow this stage.

        A deal withdrawn in error is a **new deal**, not a reopened one: a record
        of what was decided must not be editable into a different decision. Same
        rule the journey uses, for the same reason.
        """
        return self in (DealStage.HANDED_OVER, DealStage.WITHDRAWN)
