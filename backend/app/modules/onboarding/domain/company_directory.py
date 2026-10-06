"""``CompanyDirectory`` — find a company, or create one for a buyer.

Published so the buyer migration and the RM's "record this deal's
buyer" screen can turn a name and a country into a company record without
either of them reaching into the company service's create paths. Pure data structures
and one ``Protocol``; no I/O. ``application/company_directory.py::CompanyDirectoryService``
implements it.

Two questions, deliberately apart
---------------------------------
* **``match``** — "do we already have this company?" Answers with a
  :class:`MatchKind` and, where it can, the company it means. It never creates and
  never writes.
* **``create_buyer_company``** — "make one, as somebody's buyer." Writes a company at
  ``pipeline_status = NOT_IN_PIPELINE`` and ``source = DEAL_BUYER``, so it is a real
  company record that is not a lead (a buyer becomes a lead only when
  somebody onboards it).

Keeping them apart is what lets the buyer migration do the thing the plan asks for:
match first, hand ``POSSIBLE_DUPLICATE`` and ``CONFLICT`` to Compliance for review
and create only for ``NEW``.

What ``match`` means by each answer
-----------------------------------
========================  ====================================================
``MATCHED``               One company, named with confidence: a full PAN, GSTIN
                          or registration number identified it
``POSSIBLE_DUPLICATE``    One or more candidates on weaker evidence — a similar
                          name in the same country. A person decides
``CONFLICT``              Identifiers point at **different** companies (a PAN
                          naming one and a GSTIN another). Never auto-resolved
``NEW``                   Nothing matched
========================  ====================================================

``company_id`` is set for ``MATCHED``; ``candidates`` carries every company the other
kinds found, so a reviewer sees what the matcher saw.

**Identifier disclosure is the caller's problem, not this module's.** ``match`` takes
``actor_role`` and records it on the result so a route can decide what it may say
(a full identifier may name a company; identifiers themselves stay masked). What the
match route's response may carry is the route's decision; this module reports what it
found and lets the route narrow it.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import Protocol


class MatchKind(str, enum.Enum):
    """How confident the directory is, in four words."""

    MATCHED = "MATCHED"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    CONFLICT = "CONFLICT"
    NEW = "NEW"


@dataclass(frozen=True)
class MatchResult:
    """What the directory found."""

    kind: MatchKind

    company_id: uuid.UUID | None = None
    """The company this is, when ``kind`` is ``MATCHED``. ``None`` otherwise — a
    ``POSSIBLE_DUPLICATE`` deliberately refuses to pick one."""

    candidates: tuple[uuid.UUID, ...] = field(default_factory=tuple)
    """Every company considered, in a stable order, so two calls agree and a reviewer
    sees what the matcher saw. Includes the match itself when there is one."""

    reason: str | None = None
    """Why, in words a reviewer can act on — "a company already holds this PAN", "the
    PAN and the GSTIN name different companies". ``None`` for ``NEW``."""

    @property
    def needs_a_person(self) -> bool:
        """Whether the buyer migration must stop and ask."""
        return self.kind in (MatchKind.POSSIBLE_DUPLICATE, MatchKind.CONFLICT)


@dataclass(frozen=True)
class BuyerCompanyDraft:
    """What is known about a buyer at the moment it becomes a company.

    Everything but ``name`` and ``country`` is optional, because that is all a legacy
    ``deal_buyer`` row is guaranteed to have (``deal-and-buyer.md`` §3). The
    "a foreign company needs a registration number" rule does **not** apply to these:
    requiring one would make the buyer migration impossible for rows that never had it.
    """

    name: str
    country: str
    pan: str | None = None
    gstins: tuple[str, ...] = field(default_factory=tuple)
    registration_number: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    #: The deal this buyer came from, recorded on the company as ``created_via_deal_id``.
    created_via_deal_id: uuid.UUID | None = None
    #: Where the row came from, for ``source_ref`` — a migration run id, or the
    #: route that recorded the buyer.
    source_ref: str | None = None


class CompanyDirectory(Protocol):
    """Find or create. ``match`` never writes; ``create_buyer_company`` commits once."""

    async def match(
        self,
        *,
        name: str,
        country: str,
        pan: str | None = None,
        gstin: str | None = None,
        registration_number: str | None = None,
        actor_role: str | None = None,
    ) -> MatchResult: ...

    async def create_buyer_company(
        self,
        draft: BuyerCompanyDraft,
        *,
        actor_id: str | None,
        history_event_type: str | None = None,
        history_details: dict | None = None,
    ) -> uuid.UUID: ...


__all__ = [
    "BuyerCompanyDraft",
    "CompanyDirectory",
    "MatchKind",
    "MatchResult",
]
