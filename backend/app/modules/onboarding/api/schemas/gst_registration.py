"""A company's GST registrations, as the API serves them — **owner: Developer 3**
(allocation tasks 3.13, 3.14, 3.15, 3.17; plan P6-2, P6-5).

Its own file rather than ``exporter.py``: a registration is a record in its own
right now (task 3.12), with its own routes, and the company shapes are already a
long file three lanes edit.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field

from app.modules.onboarding.api.schemas.masking import (
    NotMasked,
    can_reveal_identifiers,
    mask_identifier,
)
from app.modules.onboarding.domain.entities.exporter_enums import (
    GstRegistrationFlag,
    GstRegistrationStatus,
)
from app.platform.authentication.models import User, UserRole

#: The GST portal's own search page. The link is built per registration so a
#: COMPLIANCE or ADMIN user can check a GSTIN against the source without copying it
#: out by hand (task 3.17). Not an API we call: it is a page for a person.
GST_PORTAL_SEARCH = "https://services.gst.gov.in/services/searchtp?tin="


def withholds_branch_flags(viewer: User) -> bool:
    """Whether a branch's flag status, reason and count are withheld from `viewer`.

    DEVELOPER only (R-47, decision D-05 of 4 October 2026): a flag is a compliance
    judgement, and D8 already refuses DEVELOPER the background check, its decisions
    and the screening answers for the same reason. OPERATIONS keeps them — a flag
    blocks the deals it is working on, and the refusal names it.
    """
    return viewer.role == UserRole.DEVELOPER


class AddGstRegistrationRequest(BaseModel):
    """Record a GST registration for a company (task 3.13).

    **No state.** ``state_code`` and ``state_name`` come from the GSTIN's first two
    characters (``domain/gst_states.py``); accepting them here would let someone
    record "Maharashtra" against a GSTIN issued in Karnataka, and the record would
    contradict itself with no way to tell which half was wrong.

    ``status`` defaults to ``UNVERIFIED``, which means "nobody has checked this
    against the portal" — deliberately not ``ACTIVE``, which would be a claim.
    """

    model_config = ConfigDict(extra="forbid")

    #: The complete GSTIN. It must carry the company's PAN in characters 3–12, the
    #: same rule every other write path applies.
    gstin: Annotated[str, NotMasked] = Field(min_length=15, max_length=15)
    #: The branch's registered address, as the portal prints it. Free text: it is
    #: shown and printed, never parsed.
    address: str | None = Field(default=None, max_length=2000)
    status: GstRegistrationStatus = GstRegistrationStatus.UNVERIFIED


class DeactivateGstRegistrationRequest(BaseModel):
    """Stop using a branch. Not a delete — the row is kept, because a deal handed
    over through it names it."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=1000)


class FlagGstRegistrationRequest(BaseModel):
    """Flag or unflag a branch (task 3.14). The reason is **required** both ways.

    Flagging: the reason is what the blocked handover will say, so without it the
    person who hits the block has nothing to act on. Unflagging: "why we decided the
    problem is resolved" is the half a later reader needs most, and the flag's own
    reason is about to stop being readable on the row.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


class GstRegistrationResponse(BaseModel):
    """One branch.

    ``gstin`` is masked for a role that may not reveal identifiers, by the same rule
    as the company's own. ``verify_url`` is served **only** to a role that sees the
    full GSTIN (task 3.17): the link contains the GSTIN, so sending it to a masked
    role would hand over the value the masking exists to withhold.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    gstin: str
    #: Derived from the GSTIN, never entered. `state_name` is `null` for a state code
    #: this release does not know — recorded as unknown rather than guessed.
    state_code: str | None
    state_name: str | None
    status: GstRegistrationStatus
    address: str | None
    #: `null` for DEVELOPER: a flag is a compliance judgement, withheld from that role
    #: like the background check itself (D8; R-47, decision D-05 of 4 October 2026).
    flag_status: GstRegistrationFlag | None
    #: Why it is flagged. `null` when it is not, and always `null` for DEVELOPER.
    flag_reason: str | None
    active: bool
    deactivated_at: datetime | None
    created_at: datetime
    #: A link to the GST portal's own search page for this GSTIN. `null` for a role
    #: that sees the GSTIN masked — the link would carry the value (task 3.17).
    verify_url: str | None = None
    #: Other companies whose active registrations include this GSTIN (decision IQ-9:
    #: a warning, never a refusal). A flag here does not touch theirs.
    also_held_by: list[uuid.UUID] = Field(default_factory=list)

    def masked_for(self, viewer: User) -> Self:
        if can_reveal_identifiers(viewer):
            return self.model_copy(
                update={"verify_url": f"{GST_PORTAL_SEARCH}{self.gstin}"}
            )
        update: dict[str, object] = {"gstin": mask_identifier(self.gstin), "verify_url": None}
        if withholds_branch_flags(viewer):
            update |= {"flag_status": None, "flag_reason": None}
        return self.model_copy(update=update)


class GstRegistrationListResponse(BaseModel):
    """A company's branches, newest last.

    Deactivated ones are included: a branch that was deactivated is how a deal handed
    over through it is explained, and hiding it would make that deal's invoicing
    branch look as though it came from nowhere. `active` tells them apart.
    """

    registrations: list[GstRegistrationResponse]
    #: How many **active** branches are flagged — what the company page's warning
    #: chip counts, served rather than recomputed so the screen and the guard agree.
    #: `null` for DEVELOPER, who is not served flags (R-47).
    flagged_count: int | None = 0


__all__ = [
    "GST_PORTAL_SEARCH",
    "AddGstRegistrationRequest",
    "DeactivateGstRegistrationRequest",
    "FlagGstRegistrationRequest",
    "GstRegistrationListResponse",
    "GstRegistrationResponse",
    "withholds_branch_flags",
]
