import os
import pathlib
from collections.abc import AsyncGenerator

import pytest
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

# Load .env variables first so they take precedence over test defaults
load_dotenv(pathlib.Path(__file__).parent / ".env")
load_dotenv()

# Set dummy environment variables for tests to avoid import-time KeyErrors in
# app.platform.audit_framework.config. Must run before any app.* import below —
# app.main pulls in app.bootstrap, which now reaches audit_framework.config at
# module scope (SettlementLifecycleConsumer imports it eagerly), and that module
# reads os.environ["GCP_PROJECT_ID"] unconditionally at import time.
os.environ.setdefault("GCP_PROJECT_ID", "test-gcp-project-id")
os.environ.setdefault("AUDIT_BUCKET_NAME", "test-audit-bucket-name")
os.environ.setdefault("LOG_SINK_LOGGER_NAME", "test-log-sink-logger-name")
os.environ.setdefault("SERVICE_ACCOUNT_EMAIL", "test-service-account@example.com")

from app.main import app  # noqa: E402 — must follow the environ.setdefault calls above
from app.platform.database import services as database  # noqa: E402
from app.platform.database.read_only import READ_ONLY_CONNECT_ARGS  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
async def _use_nullpool_engine() -> AsyncGenerator[None, None]:
    """
    Replace the app's pooled engine with a NullPool engine for the test session.

    On Windows, asyncpg's overlapped I/O futures are cancelled for idle pooled
    connections between tests, causing spurious failures on the second+ request
    per test. NullPool creates a fresh TCP connection per request, so there is
    no stale state to carry over.
    """
    from app.platform.configuration.config import get_settings

    settings = get_settings()

    test_engine = create_async_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
    )
    test_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    def _read_only(url: str):
        """A NullPool twin of one of the app's read-only engines.

        connect_args must be carried over: without them the transaction is not
        READ ONLY, and a test asserting that a write is refused would pass or
        fail on the role's privileges alone — proving one layer while silently
        skipping the other.
        """
        ro_engine = create_async_engine(
            url,
            poolclass=NullPool,
            connect_args=READ_ONLY_CONNECT_ARGS,
        )
        return ro_engine, async_sessionmaker(
            bind=ro_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

    test_ro_engine, test_ro_factory = _read_only(settings.database_ro_url)
    test_settlement_ro_engine, test_settlement_ro_factory = _read_only(
        settings.database_settlement_ro_url
    )
    test_audit_ro_engine, test_audit_ro_factory = _read_only(settings.database_audit_ro_url)

    original_engine = database.engine
    original_factory = database.AsyncSessionLocal
    original_ro_engine = database.ro_engine
    original_ro_factory = database.AsyncSessionLocalRO
    original_settlement_ro_engine = database.settlement_ro_engine
    original_settlement_ro_factory = database.AsyncSessionLocalSettlementRO
    original_audit_ro_engine = database.audit_ro_engine
    original_audit_ro_factory = database.AsyncSessionLocalAuditRO

    database.engine = test_engine
    database.AsyncSessionLocal = test_factory
    database.ro_engine = test_ro_engine
    database.AsyncSessionLocalRO = test_ro_factory
    database.settlement_ro_engine = test_settlement_ro_engine
    database.AsyncSessionLocalSettlementRO = test_settlement_ro_factory
    database.audit_ro_engine = test_audit_ro_engine
    database.AsyncSessionLocalAuditRO = test_audit_ro_factory

    original_integrity_enabled = settings.INTEGRITY_CHECK_ENABLED
    settings.INTEGRITY_CHECK_ENABLED = False
    original_relay_enabled = settings.LEG_SIGNAL_RELAY_ENABLED
    settings.LEG_SIGNAL_RELAY_ENABLED = False

    yield

    settings.INTEGRITY_CHECK_ENABLED = original_integrity_enabled
    settings.LEG_SIGNAL_RELAY_ENABLED = original_relay_enabled

    database.engine = original_engine
    database.AsyncSessionLocal = original_factory
    database.ro_engine = original_ro_engine
    database.AsyncSessionLocalRO = original_ro_factory
    database.settlement_ro_engine = original_settlement_ro_engine
    database.AsyncSessionLocalSettlementRO = original_settlement_ro_factory
    database.audit_ro_engine = original_audit_ro_engine
    database.AsyncSessionLocalAuditRO = original_audit_ro_factory

    await test_engine.dispose()
    await test_ro_engine.dispose()
    await test_settlement_ro_engine.dispose()
    await test_audit_ro_engine.dispose()


async def _load_reference_registries() -> bool:
    """Load all three GitOps registries. False if the load did not succeed.

    Deliberately catches everything. The driver does not present connection
    failures consistently — asyncpg raises ``InvalidPasswordError`` straight
    through rather than wrapped in ``SQLAlchemyError`` — and enumerating the
    ways a database can be unreachable is a losing game. A unit-only run on a
    machine with no database is legitimate and must not error here; anything
    that genuinely needs the data fails on its own terms, and the teardown
    caller asserts on the return value rather than ignoring it.
    """
    from app.bootstrap import (
        load_compliance_rule_seed_data,
        load_purpose_code_seed_data,
        load_sector_registry_seed_data,
    )

    try:
        await load_purpose_code_seed_data()
        await load_sector_registry_seed_data()
        await load_compliance_rule_seed_data()
    except Exception:
        return False
    return True


@pytest.fixture(scope="session", autouse=True)
async def _reference_data(
    _use_nullpool_engine: None,
) -> AsyncGenerator[None, None]:
    """Load the GitOps reference registries around the whole session.

    Loaded up front because nothing else does it. The registries are populated
    in the application lifespan, and the suite never enters one — ``client``
    drives the app through ``ASGITransport``, which does not emit lifespan
    events. On a freshly migrated database the tables therefore exist and are
    empty, and screening resolves every sector to ``standard``: no payment is
    ever designated for enhanced due diligence, and the tests that assert EDD
    fail with no indication that reference data was the cause.

    Loaded again at the end because the suite can still empty them.

    Historically this was because ``test_settlement_migration`` downgraded below
    the settlement schema to prove the chain was reversible, reverting the
    registry migrations and dropping their rows. That test no longer drives
    Alembic at all — the module was squashed into a single baseline and the test
    now asserts the resulting schema instead — so nothing in the suite reverts a
    migration any more. The reload is kept because individual compliance tests
    still delete registry rows as part of their own fixtures, and a developer or
    CI job pointed at a shared database would otherwise leave sector screening
    silently disabled until the next application boot.

    Depends on ``_use_nullpool_engine`` so this tears down first, while the
    engine it writes through is still open.
    """
    from app.modules.compliance.domain.entities.compliance_rule import ComplianceRule
    from app.modules.compliance.domain.entities.registry import PurposeCodeCanonical
    from app.modules.compliance.domain.entities.sector_registry import SectorCodeRegistry

    reachable = await _load_reference_registries()

    yield

    if not reachable:
        return

    assert await _load_reference_registries(), (
        "the reference registries could not be reloaded at the end of the session"
    )

    # Asserted rather than assumed: a silent failure here is the exact state
    # this fixture exists to prevent, and it would otherwise surface as a
    # screening bug days later.
    async with database.AsyncSessionLocal() as session:
        # ComplianceRule included since S0T3 became the policy source: a suite
        # that reseeds the rule registry and fails to restore it leaves every
        # subsequent screening imposing no obligation at all.
        for model in (SectorCodeRegistry, PurposeCodeCanonical, ComplianceRule):
            count = await session.scalar(select(func.count()).select_from(model))
            assert count, (
                f"{model.__tablename__} is empty after the reference-data reload; "
                f"the shared database has been left without its GitOps seed data"
            )


@pytest.fixture(scope="session")
async def client(
    _use_nullpool_engine: None,
) -> AsyncGenerator[AsyncClient, None]:
    """
    Session-scoped ASGI test client.

    Depends on _use_nullpool_engine so the engine swap happens before the
    app lifespan starts.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
