"""Request and response shapes for ``POST /companies/match`` — **owner:
Developer 3** (allocation task 3.10, plan P4-3).

Its own file rather than ``exporter.py``, because none of these shapes is a
company: they are the answer to "which company is this?", and that answer is
deliberately *not* a company response. See ``company_directory_router.py`` for the
disclosure rule the shapes implement (decision BQ-2) — in short, a candidate
carries a company's id, name, country and pipeline status, and never an identifier.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.onboarding.api.schemas.masking import NotMasked
from app.modules.onboarding.domain.company_directory import MatchKind
from app.modules.onboarding.domain.company_identity import REGISTRATION_NUMBER_MAX, IdentityGap
from app.modules.onboarding.domain.entities.exporter_enums import CompanyPipelineStatus


class CompanyMatchRequest(BaseModel):
    """What is known about a company at the moment somebody needs to find it.

    ``name`` and ``country`` are always required, even when an identifier is given.
    Two reasons: the country is part of the registration-number identity, and the
    name is what the answer is *checked* against by the person reading it — a
    MATCHED result naming a company whose name looks nothing like what they typed
    is the signal that something is wrong, and without the name there is nothing
    for the matcher to fall back to when no identifier matches.

    Each identifier is optional and must be **complete**. There is no partial or
    prefix form of any of them: an exact match is a lookup, a prefix match is a way
    to read identifiers out of the CRM one character at a time.
    """

    model_config = ConfigDict(extra="forbid")

    #: The company's legal name, as the person has it.
    name: str = Field(min_length=1, max_length=255)
    #: Country of incorporation, ISO 3166-1 alpha-2.
    country: str = Field(min_length=2, max_length=2)
    #: A complete PAN. `NotMasked`, because a client that sent back a masked value
    #: it had read would be asking "which company holds ••••••1234F".
    pan: Annotated[str | None, NotMasked] = Field(default=None, max_length=32)
    #: One complete GSTIN. A GSTIN held by two companies is a POSSIBLE_DUPLICATE
    #: rather than a match (decision IQ-9).
    gstin: Annotated[str | None, NotMasked] = Field(default=None, max_length=32)
    #: A complete foreign registration number, matched within `country`.
    registration_number: Annotated[str | None, NotMasked] = Field(
        default=None, max_length=REGISTRATION_NUMBER_MAX
    )

    @field_validator("country")
    @classmethod
    def _country_is_alpha2(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if len(cleaned) != 2 or not cleaned.isascii() or not cleaned.isalpha():
            raise ValueError("country must be a two-letter ISO 3166-1 code, e.g. IN")
        return cleaned

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned

    @model_validator(mode="after")
    def _identifiers_are_whole(self):
        """Refuse an identifier too short to be one.

        Not a format check — the matcher normalises and the database constrains
        formats — but a length floor, because the thing this route must never
        become is a prefix search. "ABCDE" is not a PAN; accepting it and finding
        nothing would still have answered "no company's PAN starts this way" had
        the lookup been a prefix one, and the floor makes that impossible by
        construction rather than by the query happening to use `=`.
        """
        if self.pan is not None and len(self.pan.strip()) != 10:
            raise ValueError("pan must be the complete 10-character value")
        if self.gstin is not None and len(self.gstin.strip()) != 15:
            raise ValueError("gstin must be the complete 15-character value")
        if self.registration_number is not None and len(self.registration_number.strip()) < 2:
            raise ValueError("registration_number must be the complete value")
        return self


class CompanyMatchCandidate(BaseModel):
    """One company the matcher found.

    No identifiers, for any role (``company_directory_router.py``). ``name`` and
    ``country`` are nullable because the older unnamed create path left them empty
    on some companies; a candidate with no name is still worth returning, since its
    id is what the caller needs.
    """

    company_id: uuid.UUID
    name: str | None
    country: str | None
    #: Whether this company is in the sales pipeline. A `NOT_IN_PIPELINE` candidate
    #: exists only because it was somebody's buyer — usually exactly the record the
    #: person is looking for.
    pipeline_status: CompanyPipelineStatus


class CompanyMatchResponse(BaseModel):
    """The matcher's answer."""

    kind: MatchKind
    #: The company this is — set only for `MATCHED`. A `POSSIBLE_DUPLICATE`
    #: deliberately refuses to pick one.
    company_id: uuid.UUID | None = None
    #: Why, in words a person can act on. `null` for `NEW`.
    reason: str | None = None
    #: Whether a person has to decide (`POSSIBLE_DUPLICATE` or `CONFLICT`, IQ-8).
    #: Served rather than inferred from `kind`, so a screen and the buyer migration
    #: apply one rule.
    needs_a_person: bool = False
    #: Every company considered, in a stable order, including the match itself.
    candidates: list[CompanyMatchCandidate] = Field(default_factory=list)


__all__ = [
    "CompanyMatchCandidate",
    "CompanyMatchRequest",
    "CompanyMatchResponse",
]


class IdentityCompletionItem(BaseModel):
    """One company the CRM cannot yet identify (IQ-7's completion list, R-28).

    Carries **no identifier**: the company has none, which is why it is here. What it
    lacks is ``missing``; ``required`` says whether a rule requires it (a foreign
    company's registration number, IQ-7; any company's country) or it is only worth
    doing (an Indian company's PAN).
    """

    company_id: uuid.UUID
    name: str | None
    country: str | None
    pipeline_status: CompanyPipelineStatus
    #: Which channel created it — `DEAL_BUYER` for the P4-6 migration's buyers.
    created_via: str | None
    missing: IdentityGap
    required: bool
    created_at: datetime


class IdentityCompletionListResponse(BaseModel):
    """Companies with no ``identity_type``, the ones a rule requires completing
    first. Ended companies are left out: completing a record nobody works on is not
    work. ``total`` counts the same filter."""

    items: list[IdentityCompletionItem]
    total: int
    limit: int
    offset: int
