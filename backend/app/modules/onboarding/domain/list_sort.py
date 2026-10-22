"""How the Companies list may be sorted.

The list is paged on the server ("Show more" asks for the next rows), so the order is
the server's too: sorting only the rows already on screen would put the wrong company
first as soon as there were more than one page of them.

* ``created_at`` — when the company was added; the default, newest first. It never
  changes, so paging through it cannot repeat or skip a company;
* ``updated_at`` — when the company record last changed (an edit to the record itself,
  not to its contacts or deals). Chosen, not the default: a company edited while
  someone pages through the list moves, and can be seen twice or not at all;
* ``name`` — alphabetically, ignoring case; a company with no name yet sorts last;
* ``stage`` — the journey, in its own order (Lead, Prospect, Customer), not the
  alphabet's.

Every order ends on when the company was added and then the company id, so two
companies that tie never swap places between one page and the next.
"""

from __future__ import annotations

import enum


class CompanySort(str, enum.Enum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    NAME = "name"
    STAGE = "stage"


class SortOrder(str, enum.Enum):
    ASC = "asc"
    DESC = "desc"


__all__ = ["CompanySort", "SortOrder"]
