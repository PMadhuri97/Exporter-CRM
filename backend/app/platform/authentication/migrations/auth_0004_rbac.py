"""Role and permission tables, seeded from the five built-in roles

Phase 2 of user management: roles become data an administrator can edit, rather
than five values hardcoded in an enum.

What this migration does *not* do is switch the 21 existing `require_role` call
sites over. Those keep reading `auth.users.role`, and every account keeps that
column, so this migration changes no access decision anywhere:
`resolve_permissions` falls back to the built-in role row matching the enum. The
only routes consulting permissions after this are user and role management
(`catalog.py`'s `enforced` flag records which).

Seeding is a data migration on purpose. The alternative — seeding at startup
from `BUILTIN_ROLE_PERMISSIONS` — would silently undo an administrator's edits
on every boot, and built-in roles are editable by decision.

The seed is transcribed from the catalogue rather than imported from it: a data
migration must keep applying the values that were true when it was written,
even after the catalogue gains a module. Importing application code into a
migration makes old history change meaning as that code evolves.

Revision ID: auth_0004_rbac
Revises: auth_0003_user_admin
Create Date: 2026-09-26
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "auth_0004_rbac"
down_revision: str | None = "auth_0003_user_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "auth"

# (builtin_role, slug, name, description)
BUILTIN_ROLES = [
    ("ADMIN", "admin", "Administrator", "Full access, including user and role management."),
    (
        "COMPLIANCE",
        "compliance",
        "Compliance",
        "Compliance decisions, audit trails and unmasked tax identifiers.",
    ),
    (
        "OPERATIONS",
        "operations",
        "Operations",
        "Day-to-day CRM work. Tax identifiers are masked unless you own the record.",
    ),
    (
        "DEVELOPER",
        "developer",
        "Developer",
        "Read-only technical access. Tax identifiers are never revealed.",
    ),
    (
        "API_USER",
        "api-user",
        "API user",
        "External or system callers. Reaches nothing in the CRM.",
    ),
]

_ALL = {
    "users": ["view", "create", "edit"],
    "roles": ["view", "create", "edit", "delete"],
    "exporters": [
        "view",
        "create",
        "edit",
        "transition",
        "view_full_tax_id",
        "search_by_tax_id",
    ],
    "verifications": ["view", "create", "review"],
    "screening": ["view", "decide"],
    "audit": ["view"],
}

# Transcribed from section 3.7 of the architecture plan. OPERATIONS gets
# search_by_tax_id but not view_full_tax_id: its reveal is scoped to records it
# owns, which a flat grant cannot express, so that check stays in application
# code and this grant stays narrow.
SEED: dict[str, list[tuple[str, str]]] = {
    "ADMIN": [(module, action) for module, actions in _ALL.items() for action in actions],
    "COMPLIANCE": [
        ("exporters", "view"),
        ("exporters", "create"),
        ("exporters", "edit"),
        ("exporters", "transition"),
        ("exporters", "view_full_tax_id"),
        ("exporters", "search_by_tax_id"),
        ("verifications", "view"),
        ("verifications", "create"),
        ("verifications", "review"),
        ("screening", "view"),
        ("screening", "decide"),
        ("audit", "view"),
    ],
    "OPERATIONS": [
        ("exporters", "view"),
        ("exporters", "create"),
        ("exporters", "edit"),
        ("exporters", "transition"),
        ("exporters", "search_by_tax_id"),
        ("verifications", "view"),
        ("verifications", "create"),
        ("screening", "view"),
    ],
    "DEVELOPER": [
        ("exporters", "view"),
        ("verifications", "view"),
        ("screening", "view"),
    ],
    "API_USER": [],
}


def upgrade() -> None:
    role_table = op.create_table(
        "role",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # create_type=False: user_role_enum already exists (auth_0001 created
        # it, auth_0002 added DEVELOPER). Letting SQLAlchemy emit CREATE TYPE
        # here would abort the migration.
        sa.Column(
            "builtin_role",
            postgresql.ENUM(name="user_role_enum", schema=SCHEMA, create_type=False),
            nullable=True,
        ),
        sa.Column(
            "is_assignable", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index("ix_role_slug", "role", ["slug"], unique=True, schema=SCHEMA)
    # Unique, but NULLs are distinct in Postgres, so any number of custom roles
    # coexist while each built-in value appears at most once.
    op.create_index(
        "ix_role_builtin_role", "role", ["builtin_role"], unique=True, schema=SCHEMA
    )

    permission_table = op.create_table(
        "role_permission",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module", sa.String(length=50), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["role_id"], [f"{SCHEMA}.role.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "role_id", "module", "action", name="uq_role_permission_role_module_action"
        ),
        schema=SCHEMA,
    )

    op.add_column(
        "users",
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_users_role_id_role",
        source_schema=SCHEMA,
        source_table="users",
        referent_schema=SCHEMA,
        referent_table="role",
        local_cols=["role_id"],
        remote_cols=["id"],
        # See the column comment on User.role_id: refuse to delete a role that
        # is still held rather than quietly demoting its holders.
        ondelete="RESTRICT",
    )

    role_ids = {builtin: uuid.uuid4() for builtin, *_ in BUILTIN_ROLES}
    op.bulk_insert(
        role_table,
        [
            {
                "id": role_ids[builtin],
                "slug": slug,
                "name": name,
                "description": description,
                "builtin_role": builtin,
                "is_assignable": True,
            }
            for builtin, slug, name, description in BUILTIN_ROLES
        ],
    )
    permissions = [
        {
            "id": uuid.uuid4(),
            "role_id": role_ids[builtin],
            "module": module,
            "action": action,
        }
        for builtin, pairs in SEED.items()
        for module, action in pairs
    ]
    if permissions:
        op.bulk_insert(permission_table, permissions)


def downgrade() -> None:
    op.drop_constraint("fk_users_role_id_role", "users", schema=SCHEMA, type_="foreignkey")
    op.drop_column("users", "role_id", schema=SCHEMA)
    op.drop_table("role_permission", schema=SCHEMA)
    op.drop_index("ix_role_builtin_role", table_name="role", schema=SCHEMA)
    op.drop_index("ix_role_slug", table_name="role", schema=SCHEMA)
    op.drop_table("role", schema=SCHEMA)
