"""authentication platform module baseline — schema `auth`

Squash of de21558136f4 — the module's only migration — expressed as the final
desired schema only. Nothing else in the chain ever touched these tables, so the
baseline is a straight relocation into a dedicated schema.

Everything is created inside the dedicated `auth` schema:

  auth.users          — platform operator / API principal.
  auth.refresh_tokens — issued refresh tokens, hashed.

`authentication` is a first-class platform module and owns its migrations here,
under `app/platform/authentication/migrations/`, not under `app/modules/` and not
in the runner's `migrations/versions/`. Its directory must be added to
`version_locations` in `alembic.ini` at cutover — it is not registered today.

THIS IS THE ONLY MODULE WITH NO EXTERNAL DEPENDENCY OF ANY KIND.
No cross-schema foreign key, no shared enum, no shared function, and — uniquely —
**no immutability trigger**, so it is the one table-owning module that does not
depend on `public.prevent_mutation()`. `auth` can be created and dropped in
complete isolation from every other schema.

Both tables are mutable by design: `users.is_active` and `users.role` are
administered over the account's life, and `refresh_tokens.revoked` /
`.revoked_at` are written on logout and rotation.

Column order reproduces the physical order in the pre-squash database. Both
tables put `id`, `created_at` and `updated_at` last, because the original
autogenerate emitted the AnerModel mixin columns after the domain columns. The
ORM declares them first; the database does not.

Constraint names reproduce what the pre-squash database holds. Neither table was
ever renamed, so PostgreSQL's auto-generated names and the explicit names below
are identical; they are spelled out only so the baseline states the full schema
rather than relying on generation rules.

Revision ID: auth_0001_baseline
Revises: a0b1c2d3e4f5
Create Date: 2026-08-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "auth_0001_baseline"
down_revision: str | None = "a0b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA = "auth"


# ── Enums ─────────────────────────────────────────────────────────────────────
# Values are the uppercase Python member names: the model uses a plain
# Enum(PyEnum, name=...), so SQLAlchemy persists `.name`.
user_role_enum = postgresql.ENUM(
    "ADMIN", "COMPLIANCE", "OPERATIONS", "API_USER",
    name="user_role_enum", schema=SCHEMA, create_type=False,
)

_ENUMS = (user_role_enum,)


def upgrade() -> None:
    bind = op.get_bind()

    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # Created explicitly up front rather than inline, so a second column adopting
    # this type later cannot trigger a duplicate CREATE TYPE.
    for pg_enum in _ENUMS:
        pg_enum.create(bind, checkfirst=False)

    # ── users ─────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("role", user_role_enum, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="users_pkey"),
        schema=SCHEMA,
    )
    # Uniqueness is carried by a unique index, not a table constraint — the model
    # declares unique=True together with index=True, which SQLAlchemy renders as a
    # single unique Index, and the source migration matched it.
    op.create_index(
        "ix_users_email", "users", ["email"], unique=True, schema=SCHEMA
    )

    # ── refresh_tokens ────────────────────────────────────────────────────────
    op.create_table(
        "refresh_tokens",
        sa.Column("user_id", sa.UUID(), nullable=False),
        # SHA-256 hex digest — the raw token is never stored.
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # CASCADE: a token has no meaning without its user, and tokens are not
        # financial records.
        sa.ForeignKeyConstraint(
            ["user_id"],
            [f"{SCHEMA}.users.id"],
            name="refresh_tokens_user_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="refresh_tokens_pkey"),
        sa.UniqueConstraint("token_hash", name="refresh_tokens_token_hash_key"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    # CASCADE reaches both tables, their keys, the unique index and the enum type
    # in one statement. Nothing outside this schema references it.
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
