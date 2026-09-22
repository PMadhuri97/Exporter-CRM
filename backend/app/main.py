import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import bootstrap as _bootstrap  # noqa: F401 — registers all ORM models with Base.metadata
from app.api.rest.router import api_router
from app.modules.gateway import (
    GatewayRequestMiddleware,
    fallback_router,
    health_router,
    v1_router,
)
from app.platform.configuration.config import settings
from app.platform.middleware.handlers import (
    aner_exception_handler,
    currency_not_registered_handler,
    unhandled_exception_handler,
)
from app.platform.middleware.services import (
    CorrelationIdMiddleware,
    IdempotencyMiddleware,
)
from app.platform.middleware.utilities import document_idempotent_routes
from app.platform.observability import setup_metrics
from app.platform.observability.logging import configure_logging
from app.platform.observability.tracing import configure_telemetry
from app.shared.exceptions import AnerBaseException
from app.shared.value_objects import CurrencyNotRegisteredError

configure_logging(log_level=settings.LOG_LEVEL, log_format=settings.LOG_FORMAT)
logger = structlog.get_logger(__name__)

_worker_task: "asyncio.Task | None" = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _worker_task

    logger.info(
        "application_starting",
        name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        temporal_enabled=settings.TEMPORAL_ENABLED,
    )

    # ledger_accounts.precision is a denormalised copy of a versioned registry
    # value and is immutable once set. If they ever diverge, every amount posted
    # against the affected account is silently wrong by a power of ten. This is a
    # correctness emergency, so drift ABORTS startup rather than logging a warning
    # — a mis-scaled ledger must never serve traffic.
    from app.bootstrap import (
        enforce_ledger_account_precision,
        load_case_sla_config_seed_data,
        load_compliance_rule_seed_data,
        load_kyb_vendor_registry_seed_data,
        load_purpose_code_seed_data,
        load_sector_registry_seed_data,
        load_stub_rail_registry_seed_data,
    )
    await enforce_ledger_account_precision()
    await load_purpose_code_seed_data()
    await load_sector_registry_seed_data()
    await load_compliance_rule_seed_data()
    # Case Management Console SLA targets (Epic 4.3, S1T2).
    await load_case_sla_config_seed_data()
    # KYB vendor registry (S1T4). A no-op until Epic 4.1 ships real adapters.
    await load_kyb_vendor_registry_seed_data()
    # epic4-reference: load_dev_rail_registry_seed_data() call removed — it
    # seeds app.modules.rails.infrastructure, which is out of scope here (see
    # bootstrap.py). Rails migrations still create rail_registration's table;
    # it is just never populated by this checkout.
    #
    # S3T2 configurable stub rails. A no-op unless the environment is a test one
    # AND STUB_RAIL_CONFIG_DIR is set; both are unset in every deployment.
    await load_stub_rail_registry_seed_data()

    if settings.EVENT_CONSUMERS_ENABLED:
        from app.bootstrap import start_event_tier
        await start_event_tier()
        logger.info("event_tier_enabled", kafka=settings.KAFKA_ENABLED)

    # epic4-reference: the real lifespan starts the Temporal worker here when
    # settings.TEMPORAL_ENABLED is true. run_worker() was removed from
    # bootstrap.py (it wires onboarding together with orchestration/
    # settlement/rails, which are out of scope), so that branch is dropped.
    # TEMPORAL_ENABLED defaults to false — see RUNNING.md if you need it.

    # Start the background audit event dispatcher
    from app.platform.audit_framework import start_audit_dispatcher, stop_audit_dispatcher
    await start_audit_dispatcher()

    # Start the background scheduler: the S3T1 key expiry sweep and the
    # platform-level idempotency violation checks.
    #
    # epic4-reference: the real lifespan also registers here (all removed,
    # each because its module's application/infrastructure is out of scope):
    #   - the ledger integrity check (app.modules.ledger.LedgerIntegrityService)
    #   - the rail polling manager (app.modules.rails.build_polling_manager,
    #     run_rail_polling_tick_task) — gated on RAIL_POLLING_ENABLED anyway
    #   - the settlement leg-signal relay (app.modules.settlement.application
    #     .tasks.run_leg_signal_relay_task)
    #   - the rail performance aggregation job (app.modules.rails.application
    #     .tasks.run_rail_performance_aggregation_task)
    #   - the rail health monitor (app.modules.rails.run_rail_health_monitor_task)
    # See RUNNING.md. Their config flags (RAIL_POLLING_ENABLED, etc.) still
    # exist in Settings but are now unread dead config.
    from app.platform.idempotency import get_sweep_interval
    from app.platform.idempotency.tasks import (
        run_idempotency_expiry_sweep_task,
        run_scheduled_violation_check_task,
        run_violation_detector_liveness_task,
    )
    from app.platform.scheduler.services import (
        register_scheduled_task,
        start_scheduler,
        stop_scheduler,
    )

    # Cadence comes from key-expiry.yaml, next to the windows it acts on; the flag is the
    # per-environment kill switch.
    register_scheduled_task(
        run_idempotency_expiry_sweep_task,
        interval_seconds=int(get_sweep_interval().total_seconds()),
        enabled=settings.IDEMPOTENCY_EXPIRY_SWEEP_ENABLED,
    )

    # S4T2 15-minute scheduled violation check task
    register_scheduled_task(
        run_scheduled_violation_check_task,
        interval_seconds=900,
        enabled=True,
    )

    # S4T2 5-minute detector liveness meta-monitoring check task
    register_scheduled_task(
        run_violation_detector_liveness_task,
        interval_seconds=300,
        enabled=True,
    )

    start_scheduler()


    # Start the idempotency archival nightly scheduler (S3T3)
    from app.platform.idempotency.archival_service import run_archival_job

    _archival_scheduler: AsyncIOScheduler | None = None  # noqa: N806
    if settings.ARCHIVAL_ENABLED:
        from apscheduler.triggers.cron import CronTrigger

        _archival_scheduler = AsyncIOScheduler()
        _archival_scheduler.add_job(
            run_archival_job,
            trigger=CronTrigger(hour=settings.ARCHIVAL_CRON_HOUR, timezone="UTC"),
            id="idempotency_archival_job",
            replace_existing=True,
        )
        _archival_scheduler.start()
        logger.info(
            "archival_scheduler_started",
            cron_hour=settings.ARCHIVAL_CRON_HOUR,
        )

    # Start the idempotency registry size metrics collector (S4T1)
    from app.platform.idempotency.services import collect_registry_size_metrics

    _registry_metrics_scheduler: AsyncIOScheduler | None = None  # noqa: N806
    _registry_metrics_scheduler = AsyncIOScheduler()
    _registry_metrics_scheduler.add_job(
        collect_registry_size_metrics,
        trigger="interval",
        seconds=30,
        id="idempotency_registry_size_collector",
        replace_existing=True,
    )
    _registry_metrics_scheduler.start()
    logger.info("registry_size_metrics_collector_started", interval_seconds=30)

    yield

    # Stop the scheduler before the audit dispatcher, so no job can emit an audit event
    # into a dispatcher that has already shut down.
    await stop_scheduler()

    # Release the polling manager only after the scheduler has stopped, so no
    # in-flight tick can find it already gone. Losing it costs nothing: the poll
    # queue is a database column, so the next process picks up exactly where
    # this one left off.
    #
    # epic4-reference: set_polling_manager(None) removed along with the rail
    # polling manager above (app.modules.rails is out of scope).

    # Stop the registry size metrics collector (S4T1)
    if _registry_metrics_scheduler is not None and _registry_metrics_scheduler.running:
        _registry_metrics_scheduler.shutdown(wait=False)
        logger.info("registry_size_metrics_collector_stopped")

    # Stop the archival scheduler
    if _archival_scheduler is not None and _archival_scheduler.running:
        _archival_scheduler.shutdown(wait=False)
        logger.info("archival_scheduler_stopped")

    # Stop the background audit event dispatcher
    await stop_audit_dispatcher()

    if settings.EVENT_CONSUMERS_ENABLED:
        from app.bootstrap import stop_event_tier
        await stop_event_tier()

    if _worker_task is not None and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None

    if settings.TEMPORAL_ENABLED:
        from app.platform.workflow.adapters.client import close_temporal_client
        await close_temporal_client()

    logger.info("application_shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Cross-border payment settlement platform for US-to-India USD→INR transfers. "
            "DNFBP-classified with maker-checker compliance workflow and Temporal-orchestrated settlement."
        ),
        docs_url=f"{settings.API_V1_PREFIX}/docs",
        redoc_url=f"{settings.API_V1_PREFIX}/redoc",
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        lifespan=lifespan,
    )

    # ── Middleware (innermost first) ──────────────────────────────────────────
    # add_middleware() inserts at position 0, so the LAST call below is the
    # OUTERMOST layer at runtime. Reading top to bottom is reading inside out.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Inside CorrelationIdMiddleware so a correlation ID is already bound when a
    # request is gated, and outside CORSMiddleware so a key rejected before the
    # handler still comes back with CORS headers — otherwise a browser client
    # sees a network error instead of the 400 explaining what was wrong.
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    # Gateway pipeline (Epic 4.4 S1T1) — correlation-ID validation and
    # api_request_logs writes for the gateway's own /health and /v{n}/...
    # surface only. A pure pass-through for every other path (see
    # GatewayRequestMiddleware.dispatch), so it cannot change behavior for the
    # platform's existing internal /api/v1 traffic. Outermost of all four, so
    # its own X-Correlation-Id header write — after gateway-side validation —
    # always wins.
    app.add_middleware(GatewayRequestMiddleware)

    # ── Tracing (OpenTelemetry) ───────────────────────────────────────────────
    # Must run at construction, before uvicorn builds the middleware stack —
    # instrument_app() adds the span middleware, so doing it during lifespan
    # startup would be too late to wrap requests. Added after CorrelationIdMiddleware
    # so the OTel span is the outermost layer and is active when the correlation ID
    # is bound onto it.
    configure_telemetry(app)

    # ── Exception handlers ────────────────────────────────────────────────────
    app.add_exception_handler(AnerBaseException, aner_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(CurrencyNotRegisteredError, currency_not_registered_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # ── Observability: Prometheus /metrics + default HTTP metrics ─────────────
    # Must run at construction, before the app starts serving. Tracing (OTel) is
    # wired later in the lifespan via configure_telemetry once settings are read.
    setup_metrics(app)

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    # ── Gateway (Epic 4.4) — the external, versioned entry point ──────────────
    # Deliberately NOT under settings.API_V1_PREFIX ("/api/v1"), which is the
    # internal service surface. /health and /v1 are the gateway's own,
    # unprefixed namespace. gateway.fallback_router is registered separately,
    # after every other route including the redirects below — see there for
    # why order matters for it specifically.
    app.include_router(health_router)
    app.include_router(v1_router, prefix="/v1")

    # ── OpenAPI: document what the middleware enforces ────────────────────────
    # IdempotencyMiddleware requires X-Idempotency-Key on its allowlisted routes,
    # but a middleware runs outside routing and FastAPI builds the schema from
    # route signatures alone — so without this the document would omit both the
    # header and the 400, and generated clients would never send the key.
    # Derived from IDEMPOTENT_ROUTES so the allowlist stays the single source of
    # truth and a new gated route documents itself.
    _base_openapi = app.openapi

    def _openapi() -> dict:
        if app.openapi_schema is None:
            app.openapi_schema = document_idempotent_routes(_base_openapi())
        return app.openapi_schema

    app.openapi = _openapi  # type: ignore[method-assign]

    # ── Static developer harness (optional, safe to delete) ───────────────────
    # Serves the internal onboarding test page at /static/onboarding-test.html.
    # This is a developer-only test harness, NOT a production frontend. The mount
    # is guarded on the directory existing, so deleting the `static/` folder is a
    # clean removal that never breaks application startup.
    _static_dir = Path(__file__).resolve().parent.parent / "static"
    if _static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=_static_dir), name="static")

    # ── Convenience redirects ─────────────────────────────────────────────────
    @app.get("/", include_in_schema=False)
    @app.get("/docs", include_in_schema=False)
    async def root_redirect() -> RedirectResponse:
        return RedirectResponse(url=f"{settings.API_V1_PREFIX}/docs")

    # gateway.fallback_router matches "/{version}" and "/{version}/{rest:path}"
    # at the application root — registered dead last, after api_router, the
    # gateway's own routers, the static mount, and the redirects above, so
    # every one of those is matched first. FastAPI/Starlette match routes in
    # registration order; registering this any earlier would let it shadow
    # "/", "/docs", or "/static/..." before they ever got a chance.
    app.include_router(fallback_router)

    return app


app = create_app()
