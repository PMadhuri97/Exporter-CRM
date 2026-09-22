from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    APP_NAME: str = "Business Platform"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production"

    # ── API ───────────────────────────────────────────────────────────────────
    API_V1_PREFIX: str = "/api/v1"

    # ── Exporter CRM (EXP-3) ─────────────────────────────────────────────────
    # `OnboardingRequest.tenant_id` is inherited multi-tenant schema that
    # predates the Exporter CRM narrowing (see the real platform's `cases`
    # module for where multi-tenant actually matters). ANER is a single
    # financier here, not a multi-tenant SaaS serving multiple client orgs —
    # per the confirmed product decision, this is one fixed platform constant,
    # never a value a caller supplies or a user picks in a form. Revisit only
    # if ANER genuinely becomes multi-tenant.
    ANER_TENANT_ID: str = "00000000-0000-0000-0000-000000000001"

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://aner:aner@localhost:5432/aner_settlement"
    DATABASE_SYNC_URL: str = "postgresql+psycopg2://aner:aner@localhost:5432/aner_settlement"
    LEDGER_RO_DB_USER: str = "ledger_ro"
    # Deliberately not defaulted. A checked-in default is a shared public
    # credential for a role that can read the whole ledger, and it is the value
    # every environment silently ends up running with. Supply it through the
    # environment or the untracked backend/.env; migration b7e4c9a15d20 and
    # database_ro_url below both fail with an actionable message when it is
    # missing, rather than falling back to something guessable.
    LEDGER_RO_DB_PASSWORD: str | None = None
    DATABASE_RO_URL_OVERRIDE: str | None = None
    # One read-only role per module, never one role spanning several. The audit
    # query interface reads three schemas and therefore holds three connections;
    # a single role with USAGE on all three would be one credential whose blast
    # radius is three modules.
    SETTLEMENT_RO_DB_USER: str = "settlement_ro"
    SETTLEMENT_RO_DB_PASSWORD: str | None = None
    DATABASE_SETTLEMENT_RO_URL_OVERRIDE: str | None = None
    AUDIT_RO_DB_USER: str = "audit_ro"
    AUDIT_RO_DB_PASSWORD: str | None = None
    DATABASE_AUDIT_RO_URL_OVERRIDE: str | None = None
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    def _read_only_url(
        self,
        *,
        user: str,
        password: str | None,
        override: str | None,
        password_setting: str,
        role: str,
        revision: str,
        override_setting: str,
    ) -> str:
        """DATABASE_URL with its credentials swapped for a read-only role's.

        A blank password aborts rather than defaulting. A default would be a
        shared credential every environment silently ends up running with, and
        the failure it replaces — a connection refused at startup with a named
        setting to fix — is the cheaper one.
        """
        if override:
            return override

        from urllib.parse import quote, urlparse, urlunparse

        if not password:
            raise RuntimeError(
                f"{password_setting} is not set, so the read-only connection URL "
                f"for {role} cannot be built. Export it in the environment or add "
                f"it to the untracked backend/.env; it must match the password the "
                f"{role} role was provisioned with by migration {revision}. Set "
                f"{override_setting} instead if the read replica has its own "
                f"connection string."
            )

        parsed = urlparse(self.DATABASE_URL)
        netloc_parts = parsed.netloc.split("@")
        if len(netloc_parts) == 2:
            host_port = netloc_parts[1]
        else:
            host_port = netloc_parts[0]
        # quote() so a user/password containing '@', ':', '/', etc. doesn't
        # corrupt the URL structure or get parsed as the wrong component.
        new_netloc = f"{quote(user, safe='')}:{quote(password, safe='')}@{host_port}"
        return urlunparse(parsed._replace(netloc=new_netloc))

    @property
    def database_ro_url(self) -> str:
        return self._read_only_url(
            user=self.LEDGER_RO_DB_USER,
            password=self.LEDGER_RO_DB_PASSWORD,
            override=self.DATABASE_RO_URL_OVERRIDE,
            password_setting="LEDGER_RO_DB_PASSWORD",
            role="ledger_ro",
            revision="b7e4c9a15d20",
            override_setting="DATABASE_RO_URL_OVERRIDE",
        )

    @property
    def database_settlement_ro_url(self) -> str:
        return self._read_only_url(
            user=self.SETTLEMENT_RO_DB_USER,
            password=self.SETTLEMENT_RO_DB_PASSWORD,
            override=self.DATABASE_SETTLEMENT_RO_URL_OVERRIDE,
            password_setting="SETTLEMENT_RO_DB_PASSWORD",
            role="settlement_ro",
            revision="d4f2a9c7b118",
            override_setting="DATABASE_SETTLEMENT_RO_URL_OVERRIDE",
        )

    @property
    def database_audit_ro_url(self) -> str:
        return self._read_only_url(
            user=self.AUDIT_RO_DB_USER,
            password=self.AUDIT_RO_DB_PASSWORD,
            override=self.DATABASE_AUDIT_RO_URL_OVERRIDE,
            password_setting="AUDIT_RO_DB_PASSWORD",
            role="audit_ro",
            revision="d4f2a9c7b118",
            override_setting="DATABASE_AUDIT_RO_URL_OVERRIDE",
        )


    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Kafka ────────────────────────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_ENABLED: bool = False              # False → in-memory event bus (keeps tests broker-free)
    EVENT_CONSUMERS_ENABLED: bool = False    # True → lifespan registers + starts consumers

    # ── Temporal ─────────────────────────────────────────────────────────────
    TEMPORAL_HOST: str = "localhost:7233"
    TEMPORAL_NAMESPACE: str = "default"
    TEMPORAL_TASK_QUEUE: str = "aner-settlement"
    TEMPORAL_ENABLED: bool = False                 # False keeps existing tests unchanged
    TEMPORAL_AUTO_CONFIRM_BANK: bool = True        # Thin-slice: skip signal-wait for bank confirmation
    TEMPORAL_MAX_RETRY_ATTEMPTS: int = 3
    TEMPORAL_RETRY_INITIAL_INTERVAL_SECONDS: int = 1   # 1s dev/test; 30s production
    TEMPORAL_FIAT_TIMEOUT_DAYS: int = 5
    TEMPORAL_CRYPTO_TIMEOUT_HOURS: int = 1
    # How long an onboarding may wait on the customer with no customer action
    # before it is abandoned. Passed to the onboarding workflow as input when it
    # starts; the workflow never reads configuration itself.
    ONBOARDING_INACTIVITY_TIMEOUT_DAYS: int = 30
    # How long a settlement may sit in SETTLED without a published reconciliation
    # trigger before the catch-up workflow re-emits it. 1 hour is the safe default
    # for production; set lower (e.g. 0.1 hours) in tests that exercise catch-up.
    RECONCILIATION_CATCHUP_INTERVAL_HOURS: int = 1

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # json | console

    # ── Auth / JWT ────────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = "change-me-in-production-32-chars-minimum"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Notifications ─────────────────────────────────────────────────────────
    NOTIFICATION_WEBHOOK_SECRET: str = "change-me-webhook-hmac-secret"  # shared secret for X-Aner-Signature
    NOTIFICATION_MAX_ATTEMPTS: int = 3        # attempts before a delivery is EXHAUSTED (per webhook contract)
    NOTIFICATION_EMAIL_FROM: str = "no-reply@aner.example"

    # ── FX ────────────────────────────────────────────────────────────────────
    FX_QUOTE_EXPIRY_MINUTES: int = 5
    FX_DEFAULT_SPREAD: str = "0.006000"          # 0.60% platform margin
    FX_MOCK_USD_INR_MID_RATE: str = "94.670000"  # mock mid-market rate
    # Bridge-leg rates for the USD -> USDC -> INR path. Deterministic
    # fixed values, not market quotes: USDC is dollar-pegged so the first
    # leg is 1:1, and 90.000000 is chosen so the canonical worked example lands
    # on exactly INR 45,000 for USD 500. Deliberately independent of
    # FX_MOCK_USD_INR_MID_RATE — that rate prices a direct USD->INR leg and
    # applying it to the bridged amount would give a different answer.
    FX_MOCK_USD_USDC_MID_RATE: str = "1.000000"
    FX_MOCK_USDC_INR_MID_RATE: str = "90.000000"
    LIMITS_STUB_RESULT: str = "approved"

    # ── OpenTelemetry ─────────────────────────────────────────────────────────
    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = "aner-settlement-platform"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4318"

    # ── Onboarding / Sumsub KYC ───────────────────────────────────────────────
    # SUMSUB_ENABLED mirrors the KAFKA_ENABLED / TEMPORAL_ENABLED / OTEL_ENABLED
    # pattern: off by default so CI and the test suite run against the in-process
    # MockIdentityProvider with no network calls or real credentials. Set to True
    # (with real sandbox credentials) to route through the live SumsubProvider.
    SUMSUB_ENABLED: bool = False
    SUMSUB_APP_TOKEN: str = ""
    SUMSUB_SECRET_KEY: str = ""
    SUMSUB_BASE_URL: str = "https://api.sumsub.com"
    SUMSUB_LEVEL_NAME: str = "basic-kyc-level"
    SUMSUB_WEBHOOK_SECRET: str = "change-me-sumsub-webhook-secret"  # verifies inbound X-Payload-Digest

    # ── Onboarding / Middesk KYB ──────────────────────────────────────────────
    MIDDESK_ENABLED: bool = False
    MIDDESK_BASE_URL: str = "https://api.middesk.com/v1"
    MIDDESK_WEBHOOK_SECRET: str = "change-me-middesk-webhook-secret"

    # ── KYB / Trulioo (Epic 4.1 S2T2) ────────────────────────────────────────
    # Mirrors the SUMSUB_ENABLED pattern: off by default so CI and the test
    # suite run without network calls or real credentials.  In deployed
    # environments the API key is provisioned from Vault.
    TRULIOO_ENABLED: bool = False
    TRULIOO_API_KEY: str = ""
    TRULIOO_API_URL: str = "https://gateway.trulioo.com"
    TRULIOO_MAX_RETRIES: int = 3
    TRULIOO_TIMEOUT_SECONDS: int = 30

    # ── Onboarding provider orchestration ─────────────────────────────────────
    # Comma-separated registry names of the provider adapters enabled in this
    # environment. Every known adapter is registered; only these are resolvable.
    # Defaults to the two mock adapters so CI and local development run with no
    # vendor credentials and no network. Adding a provider is a change here plus a
    # new adapter module — never a change to business logic.
    ONBOARDING_ENABLED_PROVIDERS: str = "mock,mock_screening"

    # ── Sanctions and compliance screening ─────────────────────────────
    SCREENING_STUB_RESULT: str = "clear"  # "clear" | "review_required" | "hard_block"

    # ── Rail recall ───────────────────────────────────────────────────────────
    # Outcome the simulated rail recall adapter reports when the caller does not
    # pass an explicit flag. Lets an environment exercise the refusal path
    # without changing how the adapter is constructed.
    RECALL_STUB_RESULT: str = "accepted"  # "accepted" | "rejected"


    # ── Integrity Check ───────────────────────────────────────────────────────
    INTEGRITY_CHECK_ENABLED: bool = True
    INTEGRITY_CHECK_INTERVAL_SECONDS: int = 3600

    # ── Rail Health Monitor (S6) ──────────────────────────────────────────────
    RAIL_HEALTH_MONITOR_ENABLED: bool = True
    RAIL_HEALTH_MONITOR_INTERVAL_SECONDS: int = 60

    # ── Settlement: leg-signal outbox relay (S5) ─────────────────────────────
    # Delivers leg_settled (and future) signals recorded transactionally by the
    # LegStatusNormaliser to the running Temporal workflow. On by default — it is
    # core settlement correctness, not an optional tier — but the task itself is
    # a no-op when TEMPORAL_ENABLED is false, so it stays quiet in dev/test.
    LEG_SIGNAL_RELAY_ENABLED: bool = True
    LEG_SIGNAL_RELAY_INTERVAL_SECONDS: int = 15

    # ── Rails: S3T2 stub rail adapter (TEST ONLY) ─────────────────────────────
    # Directory of stub rail YAML files registered at boot by
    # app.bootstrap.load_stub_rail_registry_seed_data. None — the default —
    # means no stub rail is registered anywhere, which is what every deployed
    # environment runs with. Pointing it at a directory is not enough on its
    # own: ENVIRONMENT must also name a test environment, and the stub adapter
    # module itself refuses to import in production. Mirrors
    # IDEMPOTENCY_CONFIG_DIR below: a path override, not a behaviour switch.
    STUB_RAIL_CONFIG_DIR: str | None = None

    # ── Rails: Rail Performance Tracking ─────────────────────────────────────
    RAIL_PERFORMANCE_TRACKING_ENABLED: bool = True
    RAIL_PERFORMANCE_AGGREGATION_INTERVAL_SECONDS: int = 3600

    # ── Rails: polling manager ────────────────────────────────────────────────
    # Operational kill switch for the poll tick. The per-rail CADENCE is not
    # here and must never be — polling_interval_seconds is a rail capability
    # declaration, and putting an interval in Settings would let a deployment
    # override what a vendor's API actually permits. What this controls is only
    # how often the scheduler looks for due legs.
    RAIL_POLLING_ENABLED: bool = True
    # How often the manager sweeps for due legs. Must be at least as frequent as
    # the shortest polling_interval_seconds any registered rail declares, or
    # that rail is effectively polled at the tick rate instead of its own.
    RAIL_POLLING_TICK_SECONDS: int = 5

    # ── Idempotency ───────────────────────────────────────────────────────────
    # Location of the GitOps-managed idempotency configuration (key-expiry.yaml).
    # None resolves to the deployed reference-data path, which is what every
    # environment uses; this override exists so tests and local experiments can point
    # at a fixture directory. The expiry DURATIONS deliberately do not live here —
    # they are GitOps data, and a window in Settings would be changed by editing a
    # deployment manifest rather than by a reviewed configuration commit.
    IDEMPOTENCY_CONFIG_DIR: str | None = None

    # Operational kill switch for the specification expiry sweep. The CADENCE is not here — it is
    # sweep_interval in key-expiry.yaml, alongside the windows it acts on. This flag is
    # for turning the job off in an environment, which is a deployment decision.
    IDEMPOTENCY_EXPIRY_SWEEP_ENABLED: bool = True
    # ── Idempotency Archival ──────────────────────────────────────────
    ARCHIVAL_ENABLED: bool = True
    ARCHIVAL_RETENTION_DAYS: int = 90       # records older than this are archived
    ARCHIVAL_BATCH_SIZE: int = 500          # max records per archival run
    ARCHIVAL_CRON_HOUR: int = 2             # nightly run hour (UTC), 0-23


    @property
    def onboarding_enabled_provider_names(self) -> tuple[str, ...]:
        """ONBOARDING_ENABLED_PROVIDERS parsed into names, blanks and dupes removed."""
        seen: dict[str, None] = {}
        for raw in self.ONBOARDING_ENABLED_PROVIDERS.split(","):
            name = raw.strip()
            if name:
                seen[name] = None
        return tuple(seen)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
