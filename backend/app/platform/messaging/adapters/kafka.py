"""
Kafka-backed EventBus using aiokafka.

aiokafka is imported lazily inside methods so the package only needs to be
installed when KAFKA_ENABLED is true — the test suite and in-memory deployments
never import it. Only the Kafka *protocol* API is used (producer + consumer); no
admin client, keeping Redpanda viable until the Phase-0 broker decision is final.

Topic creation is left to the cluster (auto-create or platform IaC) — this layer
never issues admin RPCs.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from app.platform.messaging.ports import EventBus, Handler
from app.platform.messaging.schemas import EventEnvelope, Topic

if TYPE_CHECKING:
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

logger = structlog.get_logger(__name__)


class KafkaEventBus(EventBus):
    """One AIOKafkaProducer; one AIOKafkaConsumer task per registered group."""

    def __init__(self, bootstrap_servers: str) -> None:
        self._bootstrap = bootstrap_servers
        self._producer: AIOKafkaProducer | None = None
        # group -> (topics, handler)
        self._groups: dict[str, tuple[list[Topic], Handler]] = {}
        self._consumer_tasks: list[asyncio.Task] = []
        self._consumers: list[AIOKafkaConsumer] = []
        self._running = False

    def subscribe(self, group: str, topics: list[Topic], handler: Handler) -> None:
        # Last registration per group wins; a group maps to one logical consumer.
        self._groups[group] = (topics, handler)

    async def start(self) -> None:
        from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

        self._producer = AIOKafkaProducer(bootstrap_servers=self._bootstrap)
        await self._producer.start()

        for group, (topics, handler) in self._groups.items():
            consumer = AIOKafkaConsumer(
                *[t.value for t in topics],
                bootstrap_servers=self._bootstrap,
                group_id=group,
                enable_auto_commit=False,  # commit only after the handler succeeds
                auto_offset_reset="earliest",
            )
            await consumer.start()
            self._consumers.append(consumer)
            task = asyncio.create_task(
                self._consume_loop(group, consumer, handler), name=f"kafka-consumer-{group}"
            )
            self._consumer_tasks.append(task)

        self._running = True
        logger.info(
            "kafka_event_bus_started",
            bootstrap=self._bootstrap,
            groups=list(self._groups.keys()),
        )

    async def _consume_loop(self, group: str, consumer, handler: Handler) -> None:
        try:
            async for msg in consumer:
                try:
                    envelope = EventEnvelope.from_kafka_value(msg.value)
                    await handler(envelope)
                    # At-least-once: commit only after the handler completes.
                    await consumer.commit()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "kafka_consumer_handler_failed",
                        consumer_group=group,
                        error=str(exc),
                    )
                    # No commit → message is redelivered; handler idempotency protects us.
        except asyncio.CancelledError:
            raise

    async def publish(self, envelope: EventEnvelope) -> None:
        if self._producer is None:
            logger.warning("kafka_publish_before_start", event_id=envelope.event_id)
            return
        try:
            await self._producer.send_and_wait(
                envelope.topic.value,
                value=envelope.to_kafka_value(),
                key=envelope.partition_key.encode("utf-8"),
            )
        except Exception as exc:  # noqa: BLE001 — publishing is best-effort
            logger.warning(
                "kafka_publish_failed",
                topic=envelope.topic.value,
                event_type=envelope.event_type.value,
                error=str(exc),
            )

    async def stop(self) -> None:
        for task in self._consumer_tasks:
            task.cancel()
        for task in self._consumer_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        for consumer in self._consumers:
            await consumer.stop()
        if self._producer is not None:
            await self._producer.stop()
        self._running = False
        logger.info("kafka_event_bus_stopped")
