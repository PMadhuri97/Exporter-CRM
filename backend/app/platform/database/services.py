from collections.abc import AsyncGenerator

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.platform.configuration.config import settings
from app.platform.database.read_only import READ_ONLY_CONNECT_ARGS, forbid_writes

logger = structlog.get_logger(__name__)

engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

def _read_only_engine(url: str) -> AsyncEngine:
    """An engine whose every transaction starts READ ONLY.

    One per read-only role. BUILD.md #15 gives a module exactly one such role
    and forbids sharing it, so a query service reading several schemas holds
    several connections rather than one wide-reaching credential.
    """
    return create_async_engine(
        url,
        echo=settings.DEBUG,
        pool_pre_ping=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        connect_args=READ_ONLY_CONNECT_ARGS,
    )


def _read_only_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


ro_engine: AsyncEngine = _read_only_engine(settings.database_ro_url)
AsyncSessionLocalRO = _read_only_sessionmaker(ro_engine)

settlement_ro_engine: AsyncEngine = _read_only_engine(settings.database_settlement_ro_url)
AsyncSessionLocalSettlementRO = _read_only_sessionmaker(settlement_ro_engine)

audit_ro_engine: AsyncEngine = _read_only_engine(settings.database_audit_ro_url)
AsyncSessionLocalAuditRO = _read_only_sessionmaker(audit_ro_engine)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_ro_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocalRO() as session:
        forbid_writes(session)
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_settlement_ro_db() -> AsyncGenerator[AsyncSession, None]:
    """A session on the settlement schema, readable and nothing more."""
    async with AsyncSessionLocalSettlementRO() as session:
        forbid_writes(session)
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_audit_ro_db() -> AsyncGenerator[AsyncSession, None]:
    """A session on the audit schema, readable and nothing more."""
    async with AsyncSessionLocalAuditRO() as session:
        forbid_writes(session)
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def check_db_connection() -> bool:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("database_connection_failed", error=str(exc))
        return False


async def close_db() -> None:
    await engine.dispose()
    await ro_engine.dispose()
    await settlement_ro_engine.dispose()
    await audit_ro_engine.dispose()
    logger.info("database_connections_closed")
