"""Cached Temporal client — one connection reused across the process lifetime."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from temporalio.client import Client

logger = structlog.get_logger(__name__)

_client: Client | None = None
_lock = asyncio.Lock()


async def get_temporal_client() -> Client:
    """Return the cached Temporal client, creating it on first call."""
    global _client
    if _client is not None:
        return _client
    async with _lock:
        if _client is None:
            from temporalio.client import Client

            from app.platform.configuration.config import get_settings
            settings = get_settings()
            _client = await Client.connect(
                settings.TEMPORAL_HOST,
                namespace=settings.TEMPORAL_NAMESPACE,
            )
            logger.info(
                "temporal_client_connected",
                host=settings.TEMPORAL_HOST,
                namespace=settings.TEMPORAL_NAMESPACE,
            )
    return _client


async def close_temporal_client() -> None:
    """Discard the cached client (call on app shutdown).

    temporalio's Client has no explicit close/disconnect method — the
    underlying gRPC connection is managed by the Rust core and released on
    garbage collection. Dropping our reference is all that's needed.
    """
    global _client
    if _client is not None:
        _client = None
        logger.info("temporal_client_closed")
