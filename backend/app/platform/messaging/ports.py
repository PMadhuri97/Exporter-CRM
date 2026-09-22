"""
EventBus abstraction and the in-process default implementation.

The bus is the seam between producers and consumers. In-memory mode delivers
synchronously to subscribed handlers in-process (used by tests and by single-process
deployments); Kafka mode (kafka_bus.py) publishes to the broker and runs consumer
groups as background tasks. Producers and consumers never import a concrete bus —
they go through get_event_bus().
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

import structlog

from app.platform.messaging.schemas import EventEnvelope, Topic

logger = structlog.get_logger(__name__)

# A consumer handler: receives one envelope, returns when done. Must be idempotent.
Handler = Callable[[EventEnvelope], Awaitable[None]]


class EventBus(ABC):
    """Publish/subscribe contract shared by the in-memory and Kafka backends."""

    @abstractmethod
    def subscribe(self, group: str, topics: list[Topic], handler: Handler) -> None:
        """Register a consumer group handler for one or more topics."""

    @abstractmethod
    async def publish(self, envelope: EventEnvelope) -> None:
        """Publish one event. Best-effort — must never raise to the caller."""

    @abstractmethod
    async def start(self) -> None:
        """Start any background machinery (no-op for in-memory)."""

    @abstractmethod
    async def stop(self) -> None:
        """Flush and shut down."""


class InMemoryEventBus(EventBus):
    """
    Process-local bus. publish() fans out synchronously to every subscribed
    handler whose group is registered for the event's topic. A handler that
    raises is logged and isolated so one failing consumer never blocks another
    or the producer (mirrors at-least-once: redelivery would be a retry).
    """

    def __init__(self) -> None:
        # topic -> list of (group, handler)
        self._subscriptions: dict[Topic, list[tuple[str, Handler]]] = {}
        # Every envelope ever published — for test assertions and observability.
        self.published: list[EventEnvelope] = []
        self._started = False

    def subscribe(self, group: str, topics: list[Topic], handler: Handler) -> None:
        for topic in topics:
            self._subscriptions.setdefault(topic, []).append((group, handler))

    async def publish(self, envelope: EventEnvelope) -> None:
        self.published.append(envelope)
        handlers = self._subscriptions.get(envelope.topic, [])
        for group, handler in handlers:
            try:
                await handler(envelope)
            except Exception as exc:  # noqa: BLE001 — isolate consumer failures
                logger.warning(
                    "event_consumer_failed",
                    consumer_group=group,
                    topic=envelope.topic.value,
                    event_type=envelope.event_type.value,
                    event_id=envelope.event_id,
                    error=str(exc),
                )

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    # ── Test/inspection helpers ──────────────────────────────────────────────
    def events_of_type(self, event_type) -> list[EventEnvelope]:
        return [e for e in self.published if e.event_type == event_type]

    def clear(self) -> None:
        self.published.clear()


# ── Process singleton ────────────────────────────────────────────────────────
_bus: EventBus | None = None
_lock = asyncio.Lock()


def get_event_bus() -> EventBus:
    """
    Return the process-wide bus singleton, constructing it on first use.

    Backend selection: KafkaEventBus when settings.KAFKA_ENABLED, else
    InMemoryEventBus. Consumers are NOT auto-registered here — registry.py wires
    them when the app (or a test) explicitly starts the event tier.
    """
    global _bus
    if _bus is None:
        from app.platform.configuration.config import settings

        if settings.KAFKA_ENABLED:
            from app.platform.messaging.adapters.kafka import KafkaEventBus

            _bus = KafkaEventBus(settings.KAFKA_BOOTSTRAP_SERVERS)
            logger.info("event_bus_initialised", backend="kafka")
        else:
            _bus = InMemoryEventBus()
            logger.info("event_bus_initialised", backend="in_memory")
    return _bus


def set_event_bus(bus: EventBus | None) -> None:
    """Override the singleton. Used by tests to inject a fresh in-memory bus."""
    global _bus
    _bus = bus
