"""Audit — public facade.

The only import surface other modules may use (ARCHITECTURE.md §6). Exports exactly
what the rest of the platform depends on today, and nothing else.
"""
from app.modules.audit.api.schemas import AuditEventListResponse
from app.modules.audit.application.services import AuditService
from app.modules.audit.domain.entities.audit import ActorType
from app.modules.audit.infrastructure.idempotency_violations import AuditViolationSource

__all__ = [
    "ActorType",
    "AuditEventListResponse",
    "AuditService",
    # Satisfies app.platform.idempotency.ports.ViolationSource.
    "AuditViolationSource",
]
