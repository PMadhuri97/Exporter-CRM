from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import every model module so it registers with Base.metadata, and Base itself
# so that metadata is populated before autogenerate compares against it.
#
# "Every" includes platform capabilities that own a table, not just the modules:
# ledger.idempotency_record belongs to app.platform.idempotency, so importing the
# ledger entities does not register it. A model missing here is absent from
# Base.metadata while its table still sits in a schema include_object() reflects,
# and autogenerate then proposes dropping it.
import app.modules.audit.domain.entities.audit  # noqa: F401
import app.modules.cases.domain.entities  # noqa: F401
import app.modules.compliance.domain.entities.compliance  # noqa: F401
import app.modules.compliance.domain.entities.compliance_rule  # noqa: F401
import app.modules.compliance.domain.entities.registry  # noqa: F401
import app.modules.compliance.domain.entities.sector_registry  # noqa: F401
import app.modules.customers.domain.entities  # noqa: F401
import app.modules.fx.domain.entities.fx  # noqa: F401
import app.modules.gateway.domain.entities.gateway  # noqa: F401
import app.modules.ledger.domain.entities.ledger  # noqa: F401
import app.modules.notifications.domain.entities.notifications  # noqa: F401
import app.modules.onboarding.domain.entities  # noqa: F401
import app.modules.payments.domain.entities.payments  # noqa: F401
import app.modules.rails.domain.entities.rail_models  # noqa: F401
import app.modules.reconciliation.domain.entities.reconciliation  # noqa: F401
import app.modules.settlement.domain.entities.settlement  # noqa: F401
import app.modules.settlement.domain.entities.settlement_aggregate  # noqa: F401
import app.platform.authentication.models  # noqa: F401
import app.platform.idempotency.archive_models  # noqa: F401
import app.platform.idempotency.models  # noqa: F401
import app.platform.messaging.models  # noqa: F401
from app.platform.database.models import Base  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Every schema owned by a table-owning module. `public` is deliberately absent:
# it holds no application table after the baseline squash, only
# prevent_mutation() and alembic_version. Autogenerate reflects exactly these
# and nothing else, so an object in an unlisted schema is never proposed for
# deletion.
MODULE_SCHEMAS = frozenset({
    "audit",
    "auth",
    "cases",
    "compliance",
    "customers",
    "fx",
    "gateway",
    "ledger",
    "messaging",
    "notifications",
    "onboarding",
    "payments",
    "rails",
    "reconciliation",
    "settlement",
})


def include_object(obj, name, type_, reflected, compare_to):
    """Keep autogenerate inside the module schemas.

    Without this, include_schemas=True reflects every schema Postgres exposes
    and autogenerate proposes dropping anything it does not find in
    Base.metadata — including alembic_version and prevent_mutation().
    """
    if type_ == "table":
        if name == "alembic_version":
            return False
        return (obj.schema or "public") in MODULE_SCHEMAS
    return True


def get_url() -> str:
    from app.platform.configuration.config import settings
    return settings.DATABASE_SYNC_URL


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # Each module owns a schema now, so autogenerate has to look beyond
            # the default search_path or it sees an empty database and proposes
            # recreating all 37 tables.
            include_schemas=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
