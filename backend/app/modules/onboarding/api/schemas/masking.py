"""Server-side masking of tax identifiers and contact details — the viewer's
role decides what a response may carry (architecture decision 12).

Shared by the company shapes (`exporter.py`) and the contact shapes
(`engagement.py`), which is why it is its own file: it used to live inside
`exporter.py`, and once the contact shapes moved out that would have made the
two schema files import each other. Moved without change.
"""

from __future__ import annotations

from pydantic import AfterValidator

from app.platform.authentication.models import User, UserRole

# ── Identifier masking ───────────────────────────────────────────────────────
# Server-side twin of the frontend's `maskIdentifier`/`canReveal`
# (frontend/src/platform/mask/maskIdentifier.ts), implementing the role
# matrix in docs/architecture.md, "Roles and masking". The API must not
# hand a raw PAN/GSTIN/IEC to a caller the matrix says may not see it: browser
# masking protects nothing from a caller reading the JSON directly.
#
# Same mask shape as the frontend, so an already-masked value passes through
# the frontend's own masking unchanged.

_MASK_CHAR = "•"
_VISIBLE_SUFFIX_LENGTH = 4
_ALWAYS_REVEAL_ROLES = frozenset({UserRole.COMPLIANCE, UserRole.ADMIN})


def mask_identifier(value: str | None) -> str | None:
    """Mask all but the trailing four characters (all of a short value)."""
    if value is None:
        return None
    if len(value) <= _VISIBLE_SUFFIX_LENGTH:
        return _MASK_CHAR * len(value)
    return _MASK_CHAR * (len(value) - _VISIBLE_SUFFIX_LENGTH) + value[-_VISIBLE_SUFFIX_LENGTH:]


def mask_email(value: str | None) -> str | None:
    """Keep the first character of the local part and the whole domain
    (`j•••@acme.com`): the domain is the exporter's company, which the viewer
    can already see, and a fixed-width mask hides the local part's length.
    A value with no `@` falls back to `mask_identifier`."""
    if value is None:
        return None
    local, at, domain = value.partition("@")
    if not at or not local:
        return mask_identifier(value)
    return f"{local[0]}{_MASK_CHAR * 3}@{domain}"


def mask_phone(value: str | None) -> str | None:
    """Same shape as the identifiers: only the last four characters visible."""
    return mask_identifier(value)


def can_reveal_identifiers(viewer: User) -> bool:
    """COMPLIANCE and ADMIN see full tax IDs; every other role sees them masked.

    This used to carry an ownership exception: OPERATIONS could see the raw
    identifiers on exporters it was the assigned relationship manager for.
    Architecture decision 12 settles the prototype the other way — sales staff
    see masked values, and relationship-manager ownership waits until after the
    prototype — so that branch is gone.

    The exception was inert while nothing wrote
    `exporter_profile.relationship_manager_user_id`, which is exactly why it
    was removed rather than left: the column is now written (a company's
    relationship manager, `ExporterProfileService.assign_relationship_manager`),
    and ownership deliberately grants nothing — an RM sees the companies they
    own masked, like every other OPERATIONS user (`test_masking_sweep.py`).
    """
    return viewer.role in _ALWAYS_REVEAL_ROLES


#: Who may read a company's background-check state (decision D8). The same three
#: roles the background-check routes admit; DEVELOPER is absent there and must be
#: absent here, or the company list would report what those routes withhold.
_COMPLIANCE_READING_ROLES = frozenset({UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN})


def can_read_background_check(viewer: User) -> bool:
    """Whether a response may carry the background-check state.

    The company list row carries it so a screen can show the check beside the
    company. That makes the list a second way to read compliance work, and it has
    to answer the same way the first one does: the background-check routes admit
    OPERATIONS, COMPLIANCE and ADMIN and refuse DEVELOPER, so the column is blanked
    for every other role and the matching filter is refused outright
    (`BackgroundCheckFilterNotPermittedError`) — a filtered list names the flagged
    companies whether or not the column is rendered.
    """
    return viewer.role in _COMPLIANCE_READING_ROLES


def _reject_masked(value: str | None) -> str | None:
    """Refuse a value carrying the mask character. A client that writes back
    what it read (a masked PAN is still exactly 10 characters) would otherwise
    overwrite the real identifier with bullets."""
    if value is not None and _MASK_CHAR in value:
        raise ValueError("looks like a masked value; send the full, unmasked value")
    return value


#: Write-side guard for any field a response may have masked.
NotMasked = AfterValidator(_reject_masked)


__all__ = [
    "NotMasked",
    "can_reveal_identifiers",
    "mask_email",
    "mask_identifier",
    "mask_phone",
]
