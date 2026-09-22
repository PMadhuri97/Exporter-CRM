"""Data half of the idempotency violation port.

``app.platform.idempotency.ports.ViolationSource`` is declared in the platform and
satisfied by an adapter in ``app.modules.audit``, which owns the table violations
are recorded in. The records it returns live here rather than beside the port, per
ADR 0001 rule 2: an adapter that has to import its port's owner to construct a
return value is not satisfying a port, it is depending on one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ViolationRecord:
    """One recorded idempotency failure: an operation that executed more than once.

    ``scope`` and ``operation_type`` are the detector's vocabulary, not the
    registry's. ``scope`` is a customer, entity or rail identifier rather than a
    registry ``scope_id``, and ``operation_type`` is a category such as
    ``settlement_creation`` rather than a route template — so neither joins to
    ``idempotency_record`` directly, and the field is deliberately not called
    ``scope_id``.

    The detector re-records a violation on every run that still finds it, so one
    incident appears as several records sharing a ``violation_hash``.
    ``already_alerted`` marks the records that did not page.
    """

    id: uuid.UUID
    detected_at: datetime
    key_value: str | None
    scope: str | None
    operation_type: str | None
    execution_count: int | None
    involved_object_ids: list[str]
    correlation_id: str | None
    violation_hash: str | None
    already_alerted: bool | None


@dataclass(frozen=True)
class ViolationPage:
    """A page of violations, newest first. ``total`` counts every match."""

    total: int
    limit: int
    offset: int
    violations: list[ViolationRecord]
