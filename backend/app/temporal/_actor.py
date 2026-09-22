"""Lightweight system actor used by Temporal activities for service calls."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class TemporalActor:
    """
    Duck-typed actor satisfying the `.id` attribute required by service calls.
    Used in place of a User SQLAlchemy model inside Temporal activities, which
    run outside a FastAPI request context and have no authenticated user.
    """
    id: uuid.UUID = field(
        default_factory=lambda: uuid.UUID("00000000-0000-0000-0000-000000000001")
    )
    email: str = "temporal-worker@aner.internal"
    is_active: bool = True


SYSTEM_ACTOR = TemporalActor()
SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
