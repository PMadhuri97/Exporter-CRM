"""
EventProducer — the single entry point producers use to broadcast lifecycle events.

One typed method per phase event. Every call is best-effort: a publish failure is
logged and swallowed so it never breaks the business operation that triggered it
(same discipline as the Temporal approval-signal helper). Correlation IDs are read
from structlog contextvars when not supplied explicitly.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import structlog
import structlog.contextvars

from app.platform.messaging.ports import EventBus, get_event_bus
from app.platform.messaging.schemas import EventType, build_envelope
from app.platform.observability.metrics import record_event

logger = structlog.get_logger(__name__)


def _resolve_correlation_id(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    raw = structlog.contextvars.get_contextvars().get("correlation_id")
    return str(raw) if raw else None


class EventProducer:
    """Publishes the eight settlement-lifecycle events to the event bus."""

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus = bus or get_event_bus()

    async def _emit(
        self,
        event_type: EventType,
        *,
        partition_key: str,
        transaction_id: str | None,
        correlation_id: str | None,
        payload: dict,
    ) -> bool:
        envelope = build_envelope(
            event_type,
            partition_key=partition_key,
            transaction_id=transaction_id,
            correlation_id=_resolve_correlation_id(correlation_id),
            payload=payload,
        )
        try:
            await self._bus.publish(envelope)
            record_event(event_type.value)
            logger.info(
                "event_published",
                event_type=event_type.value,
                topic=envelope.topic.value,
                event_id=envelope.event_id,
                transaction_id=transaction_id,
            )
            return True
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning(
                "event_publish_failed",
                event_type=event_type.value,
                transaction_id=transaction_id,
                error=str(exc),
            )
            return False

    # ── The eight lifecycle events ───────────────────────────────────────────

    async def payment_created(
        self,
        *,
        transaction_id: str | uuid.UUID,
        sender_id: str,
        beneficiary_id: str,
        amount: str,
        source_currency: str,
        destination_currency: str,
        correlation_id: str | None = None,
    ) -> None:
        tx = str(transaction_id)
        await self._emit(
            EventType.PAYMENT_CREATED,
            partition_key=tx,
            transaction_id=tx,
            correlation_id=correlation_id,
            payload={
                "sender_id": sender_id,
                "beneficiary_id": beneficiary_id,
                "amount": amount,
                "source_currency": source_currency,
                "destination_currency": destination_currency,
            },
        )

    async def compliance_approved(
        self,
        *,
        transaction_id: str | uuid.UUID,
        approval_id: str,
        approver_role: str,
        correlation_id: str | None = None,
    ) -> None:
        tx = str(transaction_id)
        await self._emit(
            EventType.COMPLIANCE_APPROVED,
            partition_key=tx,
            transaction_id=tx,
            correlation_id=correlation_id,
            payload={"approval_id": approval_id, "approver_role": approver_role},
        )

    async def ledger_updated(
        self,
        *,
        transaction_id: str | uuid.UUID,
        account_id: str,
        debit_entry_id: str,
        credit_entry_id: str,
        amount: str,
        currency: str,
        correlation_id: str | None = None,
    ) -> None:
        tx = str(transaction_id)
        # Ledger events partition on account_id (architecture-temporal-and-kafka.md).
        await self._emit(
            EventType.LEDGER_UPDATED,
            partition_key=account_id,
            transaction_id=tx,
            correlation_id=correlation_id,
            payload={
                "account_id": account_id,
                "debit_entry_id": debit_entry_id,
                "credit_entry_id": credit_entry_id,
                "amount": amount,
                "currency": currency,
            },
        )

    async def account_suspended(
        self,
        *,
        account_id: str | uuid.UUID,
        previous_status: str,
        reason_code: str,
        operator_id: str | uuid.UUID | None = None,
        correlation_id: str | None = None,
        transaction_id: str | None = None,
    ) -> None:
        acc = str(account_id)
        await self._emit(
            EventType.ACCOUNT_SUSPENDED,
            partition_key=acc,
            transaction_id=transaction_id,
            correlation_id=correlation_id,
            payload={
                "account_id": acc,
                "previous_status": previous_status,
                "new_status": "suspended",
                "reason_code": reason_code,
                "operator_id": str(operator_id) if operator_id else None,
            },
        )

    async def account_closed(
        self,
        *,
        account_id: str | uuid.UUID,
        previous_status: str,
        reason_code: str,
        operator_id: str | uuid.UUID | None = None,
        correlation_id: str | None = None,
        transaction_id: str | None = None,
    ) -> None:
        acc = str(account_id)
        await self._emit(
            EventType.ACCOUNT_CLOSED,
            partition_key=acc,
            transaction_id=transaction_id,
            correlation_id=correlation_id,
            payload={
                "account_id": acc,
                "previous_status": previous_status,
                "new_status": "closed",
                "reason_code": reason_code,
                "operator_id": str(operator_id) if operator_id else None,
            },
        )

    async def settlement_started(
        self,
        *,
        transaction_id: str | uuid.UUID,
        amount: str,
        correlation_id: str | None = None,
    ) -> None:
        tx = str(transaction_id)
        await self._emit(
            EventType.SETTLEMENT_STARTED,
            partition_key=tx,
            transaction_id=tx,
            correlation_id=correlation_id,
            payload={"amount": amount},
        )

    async def settlement_completed(
        self,
        *,
        transaction_id: str | uuid.UUID,
        bank_reference: str,
        correlation_id: str | None = None,
    ) -> None:
        tx = str(transaction_id)
        await self._emit(
            EventType.SETTLEMENT_COMPLETED,
            partition_key=tx,
            transaction_id=tx,
            correlation_id=correlation_id,
            payload={"bank_reference": bank_reference},
        )

    async def settlement_failed(
        self,
        *,
        transaction_id: str | uuid.UUID,
        failure_reason: str,
        correlation_id: str | None = None,
    ) -> None:
        tx = str(transaction_id)
        await self._emit(
            EventType.SETTLEMENT_FAILED,
            partition_key=tx,
            transaction_id=tx,
            correlation_id=correlation_id,
            payload={"failure_reason": failure_reason},
        )

    async def compensation_started(
        self,
        *,
        transaction_id: str | uuid.UUID,
        failure_reason: str,
        correlation_id: str | None = None,
    ) -> None:
        tx = str(transaction_id)
        await self._emit(
            EventType.COMPENSATION_STARTED,
            partition_key=tx,
            transaction_id=tx,
            correlation_id=correlation_id,
            payload={"failure_reason": failure_reason},
        )

    async def compensation_completed(
        self,
        *,
        transaction_id: str | uuid.UUID,
        failure_reason: str,
        correlation_id: str | None = None,
    ) -> None:
        tx = str(transaction_id)
        await self._emit(
            EventType.COMPENSATION_COMPLETED,
            partition_key=tx,
            transaction_id=tx,
            correlation_id=correlation_id,
            payload={"failure_reason": failure_reason},
        )

    # ── Recall and return ────────────────────────────────────────────────────
    # Each payload carries the parties, the money and the rail's reference, so a
    # consumer can address a customer or open a case from the event alone
    # without reading settlement's tables. Deliberately no notification channel,
    # template, case type or severity: those are the consumer's vocabulary, and
    # naming them here would couple settlement to systems it must not know.

    async def settlement_recalled(
        self,
        *,
        settlement_id: str | uuid.UUID,
        recall_reference: str,
        reason: str,
        rail_id: str | None = None,
        sender_account_id: str | uuid.UUID | None = None,
        beneficiary_account_id: str | uuid.UUID | None = None,
        amount: int | None = None,
        asset_code: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """The rail has been asked to return a payment it already executed."""
        sid = str(settlement_id)
        await self._emit(
            EventType.SETTLEMENT_RECALLED,
            partition_key=sid,
            transaction_id=sid,
            correlation_id=correlation_id,
            payload={
                "settlement_id": sid,
                "recall_reference": recall_reference,
                "reason": reason,
                "rail_id": rail_id,
                "sender_account_id": str(sender_account_id) if sender_account_id else None,
                "beneficiary_account_id": (
                    str(beneficiary_account_id) if beneficiary_account_id else None
                ),
                "amount": amount,
                "asset_code": asset_code,
            },
        )

    async def settlement_returned(
        self,
        *,
        settlement_id: str | uuid.UUID,
        recall_reference: str | None = None,
        reversal_transaction_ids: list[str] | None = None,
        sender_account_id: str | uuid.UUID | None = None,
        beneficiary_account_id: str | uuid.UUID | None = None,
        amount: int | None = None,
        asset_code: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """The rail confirmed the recall and the money is back on our books.

        ``reversal_transaction_ids`` are the compensating ledger transactions,
        so a consumer reconciling the return has the authoritative record of
        what moved rather than a figure recomputed from settlement columns.
        """
        sid = str(settlement_id)
        await self._emit(
            EventType.SETTLEMENT_RETURNED,
            partition_key=sid,
            transaction_id=sid,
            correlation_id=correlation_id,
            payload={
                "settlement_id": sid,
                "recall_reference": recall_reference,
                "reversal_transaction_ids": reversal_transaction_ids or [],
                "sender_account_id": str(sender_account_id) if sender_account_id else None,
                "beneficiary_account_id": (
                    str(beneficiary_account_id) if beneficiary_account_id else None
                ),
                "amount": amount,
                "asset_code": asset_code,
            },
        )

    async def settlement_recall_failed(
        self,
        *,
        settlement_id: str | uuid.UUID,
        failure_reason: str,
        recall_reference: str | None = None,
        failure_code: str | None = None,
        sender_account_id: str | uuid.UUID | None = None,
        beneficiary_account_id: str | uuid.UUID | None = None,
        amount: int | None = None,
        asset_code: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """The rail refused the recall. The money stays where it went.

        ``failure_code`` is the rail vocabulary the adapter already maps its
        proprietary errors onto, carried through as its string value so a
        consumer can branch on it without importing the rails module.
        """
        sid = str(settlement_id)
        await self._emit(
            EventType.SETTLEMENT_RECALL_FAILED,
            partition_key=sid,
            transaction_id=sid,
            correlation_id=correlation_id,
            payload={
                "settlement_id": sid,
                "failure_reason": failure_reason,
                "recall_reference": recall_reference,
                "failure_code": failure_code,
                "sender_account_id": str(sender_account_id) if sender_account_id else None,
                "beneficiary_account_id": (
                    str(beneficiary_account_id) if beneficiary_account_id else None
                ),
                "amount": amount,
                "asset_code": asset_code,
            },
        )

    async def rail_leg_stuck(
        self,
        *,
        leg_id: str | uuid.UUID,
        settlement_id: str | uuid.UUID,
        rail_id: str,
        rail_reference: str,
        submitted_at: datetime,
        expected_settlement_minutes_p99: float,
        correlation_id: str | None = None,
    ) -> None:
        """A submitted leg has outlived its rail's declared p99 settlement window.

        Emitted at most once per leg by the Polling Manager,
        which claims the leg in the platform idempotency registry in the same
        transaction so a poll every ``polling_interval_seconds`` does not become
        an alert every ``polling_interval_seconds``.

        Two consumers, deliberately one event. The SRE on-call needs to know a
        rail is not delivering; the Case Management Console needs to
        open a manual investigation. ``case_type`` is carried so the console can
        route it without inferring anything from the event name, mirroring
        ``emit_case_creation_activity``'s payload
        (``settlement/application/finality_compensation.py:526``).

        Not a failure. The leg is still in the poll queue and the rail may yet
        settle it — only a settled or failed status ends a leg's polling.
        """
        sid = str(settlement_id)
        await self._emit(
            EventType.RAIL_LEG_STUCK,
            # Keyed on the settlement, like every other settlement-topic event,
            # so a stuck leg lands on the same partition as the payment it
            # belongs to and stays ordered against it.
            partition_key=sid,
            transaction_id=sid,
            correlation_id=correlation_id,
            payload={
                "leg_id": str(leg_id),
                "settlement_id": sid,
                "rail_id": rail_id,
                "rail_reference": rail_reference,
                "submitted_at": submitted_at.isoformat(),
                "expected_settlement_minutes_p99": expected_settlement_minutes_p99,
                "case_type": "stuck_leg",
                "requires_manual_investigation": True,
            },
        )

    async def settlement_transition(
        self,
        *,
        settlement_id: str | uuid.UUID,
        from_status: str,
        to_status: str,
        correlation_id: str | None = None,
    ) -> None:
        sid = str(settlement_id)
        await self._emit(
            EventType.SETTLEMENT_TRANSITION,
            partition_key=sid,
            transaction_id=sid,
            correlation_id=correlation_id,
            payload={
                "settlement_id": sid,
                "from_status": from_status,
                "to_status": to_status,
            },
        )

    # ── Rail webhooks (Epic 2.4 / S5) ───────────────────────────────────────

    async def rail_webhook_received(
        self,
        *,
        rail_id: str,
        rail_reference: str,
        raw_body_b64: str,
        headers: dict[str, str],
        correlation_id: str | None = None,
    ) -> None:
        """Queue a signature-verified inbound rail webhook for the processor.

        Partitioned on ``rail_reference`` so every status update for one
        leg-submission is ordered on a single partition. The raw body travels
        base64-encoded and the (sanitised) headers travel alongside it, so the
        processor can re-run the adapter's ``handle_webhook`` as the source of
        truth for what it stores.
        """
        await self._emit(
            EventType.RAIL_WEBHOOK_RECEIVED,
            partition_key=rail_reference,
            transaction_id=None,
            correlation_id=correlation_id,
            payload={
                "rail_id": rail_id,
                "rail_reference": rail_reference,
                "raw_body_b64": raw_body_b64,
                "headers": headers,
            },
        )

    async def reconciliation_triggered(
        self,
        *,
        settlement_id: str | uuid.UUID,
        settled_at: str,
        legs: list[dict],
        funding_transaction_id: str,
        credit_transaction_id: str,
        correlation_id: str | None = None,
    ) -> bool:
        sid = str(settlement_id)
        return await self._emit(
            EventType.RECONCILIATION_TRIGGERED,
            partition_key=sid,
            transaction_id=sid,
            correlation_id=correlation_id,
            payload={
                "settlement_id": sid,
                "settled_at": settled_at,
                "legs": legs,
                "funding_transaction_id": funding_transaction_id,
                "credit_transaction_id": credit_transaction_id,
            },
        )

    # ── Circuit breaker events (Epic 2.4 / S4T2) ─────────────────────────────

    async def circuit_breaker_opened(
        self,
        *,
        rail_id: str,
        failure_count: int,
        open_duration_seconds: int,
        timestamp: str,
        correlation_id: str | None = None,
    ) -> bool:
        """Emit a circuit_breaker_opened event.

        Partitioned on ``rail_id`` so all CB events for one rail are ordered.
        Consumed by the settlement routing engine to immediately exclude the rail.
        """
        return await self._emit(
            EventType.CIRCUIT_BREAKER_OPENED,
            partition_key=rail_id,
            transaction_id=None,
            correlation_id=correlation_id,
            payload={
                "rail_id": rail_id,
                "failure_count": failure_count,
                "open_duration_seconds": open_duration_seconds,
                "timestamp": timestamp,
            },
        )

    async def circuit_breaker_probing(
        self,
        *,
        rail_id: str,
        timestamp: str,
        correlation_id: str | None = None,
    ) -> bool:
        """Emit a circuit_breaker_probing event (informational — open → half_open)."""
        return await self._emit(
            EventType.CIRCUIT_BREAKER_PROBING,
            partition_key=rail_id,
            transaction_id=None,
            correlation_id=correlation_id,
            payload={
                "rail_id": rail_id,
                "timestamp": timestamp,
            },
        )

    async def circuit_breaker_closed(
        self,
        *,
        rail_id: str,
        timestamp: str,
        correlation_id: str | None = None,
    ) -> bool:
        """Emit a circuit_breaker_closed event (half_open → closed).

        Signals the settlement routing engine that the rail is healthy again.
        """
        return await self._emit(
            EventType.CIRCUIT_BREAKER_CLOSED,
            partition_key=rail_id,
            transaction_id=None,
            correlation_id=correlation_id,
            payload={
                "rail_id": rail_id,
                "timestamp": timestamp,
            },
        )

