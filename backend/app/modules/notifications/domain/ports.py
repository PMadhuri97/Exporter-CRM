"""
Notification delivery port — the pluggable channel abstraction.

Each channel (webhook, email) is backed by a provider implementing this interface,
so the service dispatches without knowing how delivery happens. Owned by this module
(ARCHITECTURE.md §2/§6); implementations live in infrastructure/ or integrations/.
"""
from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass, field

from app.modules.notifications.domain.entities.notifications import NotificationChannel


@dataclass
class DeliveryResult:
    """Outcome of a single delivery attempt."""

    success: bool
    detail: str | None = None
    # Transport metadata a live provider would emit — captured for audit/tests.
    signature: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


class NotificationProvider(abc.ABC):
    """A delivery channel. Implementations must be side-effect-isolated and never
    raise for a *delivery* failure — they return ``DeliveryResult(success=False)``.
    Only programmer errors (bad inputs) should raise."""

    channel: NotificationChannel

    @abc.abstractmethod
    async def send(
        self,
        *,
        event_id: uuid.UUID,
        destination: str,
        event_type: str,
        body: dict,
    ) -> DeliveryResult:
        raise NotImplementedError
