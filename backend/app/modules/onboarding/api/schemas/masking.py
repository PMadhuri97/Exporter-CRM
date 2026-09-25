"""Server-side masking of tax identifiers and contact details — the viewer's
role decides what a response may carry (architecture decision 12, task L1-10).

**Owner: Developer 1** (tax-ID visibility is L1-10). Shared by the company
shapes (`exporter.py`, Developer 2) and the contact shapes (`engagement.py`,
Developer 3), which is why it is its own file: it used to live inside
`exporter.py`, and once the contact shapes moved out that would have made the
two schema files import each other. Moved without change (L2-01).
"""

from __future__ import annotations

from pydantic import AfterValidator

from app.platform.authentication.models import User, UserRole

# ── Identifier masking ───────────────────────────────────────────────────────
# Server-side twin of the frontend's `maskIdentifier`/`canReveal`
# (frontend/src/platform/mask/maskIdentifier.ts), implementing the role
# capability matrix in docs/exporter-crm-frontend-tickets.md. The API must not
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

    The exception was inert in practice (nothing writes
    `exporter_profile.relationship_manager_user_id`), which is exactly why it
    was worth removing rather than leaving: the first code that populated that
    column would have silently switched PII visibility on for a whole role,
    with no change to this function to review. The column and the response
    field stay for the post-prototype work that will use them.
    """
    return viewer.role in _ALWAYS_REVEAL_ROLES


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
