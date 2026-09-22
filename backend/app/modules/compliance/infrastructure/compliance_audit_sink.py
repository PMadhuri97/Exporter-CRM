"""Writes compliance evaluation warnings to the platform audit trail."""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import ActorType, AuditService

logger = structlog.get_logger(__name__)

#: The event type a reviewer filters on. Named for what happened rather than for
#: what it caused, so a rule firing under the fail-safe and a rule firing on its
#: merits stay distinguishable in the trail.
FX_RATE_UNAVAILABLE_EVENT = "compliance.threshold_rate.unavailable"


class AuditServiceComplianceAuditSink:
    """Satisfies ``ComplianceAuditSink`` by recording an ``audit_events`` row.

    Goes through ``AuditService`` rather than writing the table directly, so the
    correlation-id resolution, actor defaulting and append-only guarantees that
    every other module's audit events get apply to these too. No second audit
    table and no competing abstraction.

    Flushes into the caller's transaction and never commits it. If the caller
    rolls back, the warning goes with the decision it describes — which is
    correct: a decision that was never recorded needs no explanation.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._audit = AuditService(session)

    async def record_threshold_rate_unavailable(
        self,
        *,
        from_asset_code: str,
        to_asset_code: str,
        reason: str,
        error_type: str | None = None,
        rule_ids: tuple[str, ...] = (),
    ) -> None:
        await self._audit.record(
            FX_RATE_UNAVAILABLE_EVENT,
            actor_type=ActorType.SYSTEM,
            payload={
                "from_asset_code": from_asset_code,
                "to_asset_code": to_asset_code,
                # Which rules were let through unchecked. A reviewer looking at
                # this row needs to know what the missing rate would have
                # decided, not merely that a rate was missing.
                "rule_ids": list(rule_ids),
                "reason": reason,
                "error_type": error_type,
                # Stated rather than inferred: the reader of this row needs to
                # know the threshold was not actually checked.
                "threshold_condition": "treated_as_met",
            },
        )
