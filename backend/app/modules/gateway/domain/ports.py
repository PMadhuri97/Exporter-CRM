"""Repository interfaces the gateway module depends on.

Owned here, not in infrastructure/ — ARCHITECTURE.md §2: "Ports (interfaces)
are owned by the consumer." infrastructure/repository.py provides the only
implementation today.
"""
import uuid
from typing import Protocol


class ApiRequestLogPort(Protocol):
    """Persists one gateway request-log row."""

    async def record(
        self,
        *,
        correlation_id: str,
        method: str,
        path: str,
        status_code: int,
        duration_ms: int,
        customer_id: uuid.UUID | None = None,
    ) -> None: ...
