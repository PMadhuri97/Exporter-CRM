"""Sumsub — the only real vendor client in this codebase.

Exposes the adapter implementing the onboarding module's identity-provider port
(ARCHITECTURE.md §9).
"""
from app.integrations.identity_providers.sumsub.client import SumsubProvider

__all__ = ["SumsubProvider"]
