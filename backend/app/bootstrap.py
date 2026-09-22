from __future__ import annotations

import structlog

# Import all ORM models here so SQLAlchemy's Base.metadata is fully populated
# before any FK resolution or schema introspection happens.
from app.modules.audit.domain.entities.audit import AuditEvent  # noqa: F401
from app.modules.compliance.domain.entities.compliance import (  # noqa: F401
    ComplianceApproval,
    ComplianceCase,
    ComplianceScreening,
)
from app.modules.compliance.domain.entities.compliance_rule import (  # noqa: F401
    ComplianceRule,
)
from app.modules.compliance.domain.entities.registry import (  # noqa: F401
    PurposeCodeCanonical,
    PurposeCodeCorridorMapping,
)
from app.modules.compliance.domain.entities.sector_registry import (  # noqa: F401
    SectorCodeRegistry,
    SectorRiskClassification,
)
from app.modules.customers.domain.entities.customers import (  # noqa: F401
    BeneficiaryBankAccount,
    Customer,
)
from app.modules.fx.domain.entities.fx import FxQuote  # noqa: F401
from app.modules.ledger.domain.entities.ledger import (  # noqa: F401
    AccountBalance,
    LedgerAccount,
    LedgerEntry,
    LedgerTransaction,
)
from app.modules.notifications.domain.entities.notifications import NotificationEvent  # noqa: F401
from app.modules.notifications.events.consumers import NotificationConsumer
from app.modules.onboarding.domain.entities import (  # noqa: F401
    ApplicantMapping,
    Case,
    CaseStateTransition,
    KycCase,
    PersonProfile,
    Verification,
)
from app.modules.payments.domain.entities.payments import (  # noqa: F401
    IdempotencyKey,
    Transaction,
    TransactionStatusHistory,
)
from app.modules.reconciliation.domain.entities.reconciliation import (  # noqa: F401
    Reconciliation,
    ReconciliationCheck,
)
from app.modules.settlement.domain.entities.settlement import SettlementLeg  # noqa: F401
from app.modules.settlement.domain.entities.settlement_aggregate import (  # noqa: F401
    Settlement,
    SettlementEvent,
)
from app.platform.authentication.models import RefreshToken, User  # noqa: F401
from app.platform.idempotency.models import IdempotencyRecord  # noqa: F401
from app.platform.idempotency.stream_processor import IdempotencyViolationStreamProcessor
from app.platform.messaging.consumers import AuditEventConsumer, BaseConsumer
from app.platform.messaging.models import EventLog, ProcessedEvent  # noqa: F401
from app.platform.messaging.ports import EventBus, get_event_bus

logger = structlog.get_logger(__name__)

#: Environments in which the capability-only rail stubs are seeded into the
#: rail registry. They declare capabilities but cannot contact a rail, so a
#: production registry must never carry them — there, a real adapter registers
#: itself. These are the values ``Settings.ENVIRONMENT`` takes outside production.
_DEV_RAIL_SEED_ENVIRONMENTS: frozenset[str] = frozenset({"development", "test", "local"})

#: Environments in which the S3T2 stub rail adapters are registered. Narrower
#: than the capability-only stubs above, and deliberately so: those decline to
#: execute anything, whereas a stub rail returns a successful-looking submission
#: without moving money. That is safe to have in a test run and nowhere else, so
#: `development` and `local` are excluded as well as production. Registration
#: additionally requires STUB_RAIL_CONFIG_DIR to be set, and the stub adapter
#: module refuses to import in a production environment at all.
_STUB_RAIL_SEED_ENVIRONMENTS: frozenset[str] = frozenset({"test", "testing"})


# ============================================================================
# Event tier — consumer wiring and lifecycle.
#
# Event-tier wiring (moved here from app/events/registry.py).
#
# start_event_tier() subscribes every consumer and starts the bus; it is called
# from the FastAPI lifespan when settings.EVENT_CONSUMERS_ENABLED is true (on in
# docker-compose, off by default so the existing API test suite is unaffected).
# Tests that exercise the flow call register_consumers() against their own bus.
# ============================================================================

#: Every consumer group wired into the bus. Assembled here, in the composition
#: root, because platform/ may not import a module (ARCHITECTURE.md §2).
#:
#: epic4-reference: ReconciliationConsumer, SettlementLifecycleConsumer and
#: RailWebhookConsumer are deliberately absent. They live in
#: reconciliation/events/consumers.py and settlement/events/consumers.py,
#: which are application-tier code for modules that are out of scope for this
#: reference checkout (only their schema — migrations, and entities where an
#: in-scope module's relationships need them — was brought over). Consuming
#: their event topics belongs to the excluded modules' own business logic.
ALL_CONSUMERS: tuple[BaseConsumer, ...] = (
    AuditEventConsumer(),
    NotificationConsumer(),
    IdempotencyViolationStreamProcessor(),
)


def register_consumers(bus: EventBus) -> None:
    """Subscribe all consumer groups to their topics on the given bus."""
    for consumer in ALL_CONSUMERS:
        bus.subscribe(consumer.group, consumer.topics, consumer)
        logger.info(
            "consumer_registered",
            consumer_group=consumer.group,
            topics=[t.value for t in consumer.topics],
        )

    # epic4-reference: the real bootstrap.py also registers the rails routing
    # engine's in-memory circuit-breaker consumer here
    # (app.modules.rails.application.routing_engine.register_cb_consumer).
    # rails is out of scope (application/ not present), so that registration
    # is intentionally dropped.


async def verify_ledger_account_precision() -> list[str]:
    """Assert every ledger account's precision still matches the currency registry.

    ledger_accounts.precision is a denormalised copy of a *versioned* reference
    value and is immutable once set. If the registry's precision for an asset ever
    changes, existing accounts keep the old scale and every amount posted against
    them is silently wrong by a factor of ten. That is not something to discover
    from a reconciliation break, so it is checked at startup.

    Returns the list of problems found (empty when consistent) and logs each.
    """
    from sqlalchemy import select

    from app.platform.database.services import AsyncSessionLocal
    from app.shared.value_objects import CURRENCY_REGISTRY

    problems: list[str] = []
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(
                LedgerAccount.id, LedgerAccount.asset_code, LedgerAccount.precision
            ).distinct()
        )
        for account_id, asset_code, precision in rows.all():
            asset = CURRENCY_REGISTRY.get(asset_code)
            if asset is None:
                problems.append(
                    f"account {account_id} uses asset {asset_code}, which is not registered"
                )
            elif asset.precision != precision:
                problems.append(
                    f"account {account_id} has precision {precision} for {asset_code}, "
                    f"but the registry says {asset.precision}"
                )

    for problem in problems:
        logger.error("ledger_account_precision_mismatch", problem=problem)
    if not problems:
        logger.info("ledger_account_precision_verified")
    return problems


class LedgerPrecisionDriftError(RuntimeError):
    """Raised at startup when a ledger account's stored precision no longer matches
    the currency registry. Startup must abort: every amount posted against a
    drifted account is silently mis-scaled, so serving traffic is not safe."""


async def enforce_ledger_account_precision() -> None:
    """Verify precision and ABORT startup on any drift.

    Distinct from :func:`verify_ledger_account_precision`, which only reports. This
    is the one wired into the application lifespan — a mismatch here is a
    correctness emergency, not a warning to be logged and ignored.
    """
    problems = await verify_ledger_account_precision()
    if problems:
        raise LedgerPrecisionDriftError(
            "Ledger account precision has drifted from the currency registry; "
            "refusing to start. Problems: " + "; ".join(problems)
        )


async def load_purpose_code_seed_data() -> None:
    """Load purpose code definitions and mappings idempotently at startup.

    Every replica runs this on boot. The reload is serialised by a Postgres
    advisory lock taken inside :func:`load_purpose_codes` (BUILD.md #6), so
    concurrent replicas queue rather than racing each other's DELETE/re-insert.
    """
    from app.modules.compliance.infrastructure.purpose_code_seed_loader import (
        SEED_DATA_DIR,
        load_purpose_codes,
    )
    from app.platform.database.services import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await load_purpose_codes(session, SEED_DATA_DIR)


async def load_sector_registry_seed_data() -> None:
    """Load sector codes and their risk classifications idempotently at startup.

    Every replica runs this on boot. The reload is serialised by a Postgres
    advisory lock taken inside :func:`load_sector_registry` (BUILD.md #6), so
    concurrent replicas queue rather than racing each other's DELETE/re-insert.
    """
    from app.modules.compliance.infrastructure.sector_registry_seed_loader import (
        SEED_DATA_DIR,
        load_sector_registry,
    )
    from app.platform.database.services import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await load_sector_registry(session, SEED_DATA_DIR)


async def load_compliance_rule_seed_data() -> None:
    from app.modules.compliance.infrastructure.compliance_rule_seed_loader import (
        SEED_DATA_DIR,
        load_compliance_rules,
    )
    from app.platform.database.services import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await load_compliance_rules(session, SEED_DATA_DIR)


async def load_case_sla_config_seed_data() -> None:
    """Load Case Management Console SLA targets idempotently at startup (S1T2).

    Every replica runs this on boot. The reload is serialised by a Postgres
    advisory lock taken inside :func:`load_sla_config_table` (BUILD.md #6), so
    concurrent replicas queue rather than racing each other's DELETE/re-insert.
    A redeploy of the config changes what the *next* case created gets; it
    never touches `sla_deadline` on a case already open (see
    `app.modules.cases.application.sla_service`'s module docstring).
    """
    from app.modules.cases.infrastructure.sla_config_loader import load_sla_config_table
    from app.platform.database.services import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await load_sla_config_table(session)


# epic4-reference: load_dev_rail_registry_seed_data() is intentionally removed.
# The real bootstrap.py registers the capability-only rail stubs here via
# app.modules.rails.infrastructure.dev_rail_seed_loader, but rails is out of
# scope for this checkout (only its schema — migrations + the entities other
# modules' relationships resolve against — is present; infrastructure/ is
# not). main.py no longer calls this function. See RUNNING.md.


async def load_stub_rail_registry_seed_data() -> None:
    """Register the S3T2 configurable stub rails at startup.

    Unlike the capability-only stubs above, these execute: ``submit_leg``
    returns a configured outcome and a rail reference without contacting
    anything. Two independent conditions therefore have to hold before a single
    one is registered — the environment must name a test environment, and
    ``STUB_RAIL_CONFIG_DIR`` must point at a configuration directory (it is
    ``None`` in every deployed environment). Either one absent is a no-op.

    The loader import is deliberately inside the guard: it pulls in the stub
    adapter module, which raises ``ImportError`` in a production environment.
    """
    from app.platform.configuration.config import get_settings

    settings = get_settings()
    environment = settings.ENVIRONMENT
    if environment.lower() not in _STUB_RAIL_SEED_ENVIRONMENTS:
        logger.info("stub_rail_seed_skipped", environment=environment, reason="environment")
        return

    if not settings.STUB_RAIL_CONFIG_DIR:
        logger.info("stub_rail_seed_skipped", environment=environment, reason="unconfigured")
        return

    from pathlib import Path

    from app.modules.rails.infrastructure.stub_rail_seed_loader import (
        load_stub_rail_registry,
    )
    from app.platform.database.services import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await load_stub_rail_registry(session, Path(settings.STUB_RAIL_CONFIG_DIR))


async def load_kyb_vendor_registry_seed_data() -> None:
    """Register the platform's KYB vendor adapters at startup (S1T4).

    Each adapter's ``declare_capabilities()`` is upserted into
    ``onboarding.kyb_vendor_registration`` through ``KybVendorRegistryService``,
    so the onboarding orchestration engine can resolve a vendor by registration
    country and entity type.

    Not environment-gated: unlike the rail *stubs*, real KYB vendors belong in
    every environment. It is a no-op until Epic 4.1 ships the Middesk and
    Trulioo adapters (``KNOWN_KYB_ADAPTERS`` is empty until then).
    """
    from app.modules.onboarding.infrastructure.kyb_vendor_seed_loader import (
        load_kyb_vendor_registry,
    )
    from app.platform.database.services import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await load_kyb_vendor_registry(session)


async def start_event_tier() -> EventBus:
    """Register consumers and start the process bus. Returns the bus."""
    bus = get_event_bus()
    register_consumers(bus)
    await bus.start()
    logger.info("event_tier_started")
    return bus


async def stop_event_tier() -> None:
    bus = get_event_bus()
    await bus.stop()
    logger.info("event_tier_stopped")


# ============================================================================
# Temporal worker — REMOVED for epic4-reference.
#
# The real bootstrap.py's run_worker() registers a single Temporal worker
# across workflows/activities from onboarding (in scope), orchestration,
# settlement and rails (all out of scope). Those three modules'
# application/workflows code is not present in this checkout, and the set
# cannot be split cleanly — the worker is one Temporal task queue shared by
# all of them.
#
# main.py's lifespan only starts a worker when settings.TEMPORAL_ENABLED is
# true, which is false by default (see .env.example), so removing this has no
# effect on normal boot, `alembic upgrade head`, or the test suite. Setting
# TEMPORAL_ENABLED=true against this checkout is not supported — see
# RUNNING.md.
# ============================================================================
