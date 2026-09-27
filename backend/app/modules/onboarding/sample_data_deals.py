"""Sample data for deals, buyers and documents — **owner: Developer 3B**
(L3-05 … L3-10).

Empty on purpose, for the same reason as ``sample_data_follow_ups.py``:
Developer 3B fills this in without opening ``sample_data.py``.

Architecture §3.9 gives company B two deals, one handed over, and company C one
open deal that cannot be handed over because its background check is flagged —
each sample company's target is recorded on ``SampleCompany.target``.
"""

from __future__ import annotations


async def load_deal_sample_data() -> int:
    """Bring each sample company's deals to their §3.9 state.

    Returns the number of deals this run created — ``0`` until Developer 3B
    fills it in, and ``0`` on a repeat run.
    """
    return 0


__all__ = ["load_deal_sample_data"]
