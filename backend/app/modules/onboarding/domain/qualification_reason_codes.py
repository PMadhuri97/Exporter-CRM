"""The reasons a ``NOT_QUALIFIED`` outcome may give (contract §5.2).

A fixed list, kept in code. It used to be a table, ``qualification_reason_code``, but
only migrations ever changed it (0017 seeded it, 0031 retired the three export
reasons), no screen edits it, and an outcome cites its codes as plain strings with no
foreign key. So a change ships as code either way, and here it is reviewed with the
code that reads it.

A code is **retired**, never removed: ``active=False`` refuses it on a new outcome while
an outcome decided before keeps showing its label. Every code ever cited must stay here
(``test_every_cited_reason_code_is_in_the_catalogue``).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReasonCode:
    code: str
    label: str
    #: ``other`` needs a note alongside it.
    requires_note: bool = False
    #: A retired code is refused on a new outcome and still read on an old one.
    active: bool = True


#: By code, in code order — what ``GET /qualification/reason-codes`` serves. These are
#: the table's rows exactly as migrations 0017 and 0031 left them.
REASON_CODES: dict[str, ReasonCode] = {
    code.code: code
    for code in (
        ReasonCode("deal_size_out_of_range", "Deal size outside our range"),
        ReasonCode("geography_not_supported", "Trade corridor we do not serve", active=False),
        ReasonCode("industry_not_supported", "Industry we do not finance"),
        ReasonCode("insufficient_information", "Not enough information to qualify"),
        ReasonCode("no_export_history", "No export track record", active=False),
        ReasonCode("no_export_licence", "No export licence", active=False),
        ReasonCode("other", "Other (explain in the note)", requires_note=True),
        ReasonCode("revenue_below_threshold", "Revenue below the threshold"),
        ReasonCode("years_in_business_below_threshold", "Too few years in business"),
    )
}


def active_reason_codes() -> dict[str, ReasonCode]:
    """The codes a new outcome may give."""
    return {code: entry for code, entry in REASON_CODES.items() if entry.active}


__all__ = ["REASON_CODES", "ReasonCode", "active_reason_codes"]
