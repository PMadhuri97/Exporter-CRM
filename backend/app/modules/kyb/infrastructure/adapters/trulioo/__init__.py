"""Trulioo KYB vendor adapter — Epic 4.1 / S2T2 (AL-669).

International entity verification covering India and all markets not served by
Middesk.  Processing mode: **synchronous** — every ``verify_entity`` call
returns a complete result; no webhook or polling is required.
"""
from app.modules.kyb.infrastructure.adapters.trulioo.adapter import TruliooAdapter

__all__ = ["TruliooAdapter"]
