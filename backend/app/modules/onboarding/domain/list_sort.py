"""How the Companies list may be sorted.

The list is paged on the server ("Show more" asks for the next rows), so the order is
the server's too: sorting only the rows already on screen would put the wrong company
first as soon as there were more than one page of them.

* ``updated_at`` — when the company record last changed; the default, newest first, so
  what was worked on today is at the top;
* ``name`` — alphabetically, ignoring case; a company with no name yet sorts last;
* ``stage`` — the journey, in its own order (Lead, Prospect, Customer), not the
  alphabet's.

Every order ends on the newest change and then the company id, so two companies that
tie never swap places between one page and the next.
"""

from __future__ import annotations

import enum


class CompanySort(str, enum.Enum):
    UPDATED_AT = "updated_at"
    NAME = "name"
    STAGE = "stage"


class SortOrder(str, enum.Enum):
    ASC = "asc"
    DESC = "desc"


__all__ = ["CompanySort", "SortOrder"]
