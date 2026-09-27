"""Deal and buyer routes — **owner: Developer 3B** (L3-05, L3-06).

Empty on purpose; see `follow_up_router.py`'s docstring for why it is mounted
now rather than when it is filled. Developer 3B adds the deal routes here.

No prefix: a deal is its own thing, not a company sub-resource, so its paths are
absolute (`/deals/...`) the way `history_router.py`'s deal route already is.
Developer 3B decides the exact paths.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["Exporter CRM"])

__all__ = ["router"]
