"""Document and storage routes — **owner: Developer 3B** (L3-07 … L3-10).

Empty on purpose; see `follow_up_router.py`'s docstring for why it is mounted
now rather than when it is filled. Developer 3B adds the upload, download and
document-list routes here.

No prefix, for the same reason as `deal_router.py`: documents hang off deals as
well as companies, so a single router prefix would fit neither.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["Exporter CRM"])

__all__ = ["router"]
