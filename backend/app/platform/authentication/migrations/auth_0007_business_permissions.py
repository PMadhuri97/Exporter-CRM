"""Every CRM route checks a permission; the administrator becomes read-only

Until now the CRM's routes checked the account's enum role, and most of the
permission catalogue was declared but consulted by nothing. The routes now check
permissions, so the grants below are what each role can actually do.

What changes:

1. **New permissions** for what the routes check and the old catalogue had no word
   for: ``settings:manage``, ``exporters:partner_intake``, ``deals:*``,
   ``documents:view/upload/download``, ``qualification:record`` and
   ``compliance:view/decide/approve``. Every role gets the ones its users need to keep
   doing what they did — including an edited built-in role and a custom role, which
   are given the new grants of the built-in role their holders are based on.
2. **The administrator stops working the business.** ADMIN keeps users, roles,
   settings and the audit trail, and may read companies, deals, documents and
   compliance work. It loses every grant that creates, changes, decides, approves or
   assigns, and the full tax identifier.
3. **Grants no route ever honoured are removed**, so the Roles screen says what a
   role can do: DEVELOPER's ``verifications:view`` and ``screening:view`` (the routes
   behind them never admitted DEVELOPER) and OPERATIONS's ``verifications:create``
   (recording a check result was always compliance's).
4. **Two lead roles** are created: *Compliance lead* and *Sales lead*.

Removals (2 and 3) are applied to a built-in role only while its grants are still
exactly what was seeded (auth_0004, auth_0006). A role an administrator has edited is
left with its removals undone and a warning in the migration output naming it, so a
deliberate edit is never silently overwritten.

Transcribed rather than imported from the catalogue, for the reason ``auth_0004_rbac``
gives.

Revision ID: auth_0007_business_permissions
Revises: auth_0006_assignment_perms
Create Date: 2026-10-08
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "auth_0007_business_permissions"
down_revision: str | None = "auth_0006_assignment_perms"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "auth"

Grant = tuple[str, str]

# ── What was seeded before this migration (auth_0004 + auth_0006) ───────────────
_OLD_ALL: frozenset[Grant] = frozenset(
    [("users", a) for a in ("view", "create", "edit")]
    + [("roles", a) for a in ("view", "create", "edit", "delete")]
    + [
        ("exporters", a)
        for a in ("view", "create", "edit", "transition", "view_full_tax_id", "search_by_tax_id")
    ]
    + [("verifications", a) for a in ("view", "create", "review")]
    + [("screening", "view"), ("screening", "decide"), ("audit", "view")]
)
OLD_SEED: dict[str, frozenset[Grant]] = {
    "ADMIN": _OLD_ALL
    | {("exporters", "assign_rm"), ("compliance", "assign"), ("compliance", "approve_high_risk")},
    "COMPLIANCE": frozenset(
        {
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
        }
    ),
    "OPERATIONS": frozenset(
        {
            ("exporters", "view"),
            ("exporters", "create"),
            ("exporters", "edit"),
            ("exporters", "transition"),
            ("exporters", "search_by_tax_id"),
            ("verifications", "view"),
            ("verifications", "create"),
            ("screening", "view"),
        }
    ),
    "DEVELOPER": frozenset(
        {("exporters", "view"), ("verifications", "view"), ("screening", "view")}
    ),
    "API_USER": frozenset(),
}

# ── What each built-in role holds after it ───────────────────────────────────────
_COMPANY_WORK: frozenset[Grant] = frozenset(
    {
        ("exporters", "view"),
        ("exporters", "create"),
        ("exporters", "edit"),
        ("exporters", "transition"),
        ("exporters", "search_by_tax_id"),
        ("deals", "view"),
        ("deals", "create"),
        ("deals", "edit"),
        ("documents", "view"),
        ("documents", "upload"),
        ("qualification", "record"),
        ("verifications", "view"),
        ("screening", "view"),
        ("compliance", "view"),
    }
)
NEW_SEED: dict[str, frozenset[Grant]] = {
    "ADMIN": frozenset(
        {
            ("users", "view"),
            ("users", "create"),
            ("users", "edit"),
            ("roles", "view"),
            ("roles", "create"),
            ("roles", "edit"),
            ("roles", "delete"),
            ("settings", "manage"),
            ("audit", "view"),
            ("exporters", "view"),
            ("deals", "view"),
            ("documents", "view"),
            ("verifications", "view"),
            ("screening", "view"),
            ("compliance", "view"),
        }
    ),
    "COMPLIANCE": _COMPANY_WORK
    | {
        ("exporters", "view_full_tax_id"),
        ("exporters", "partner_intake"),
        ("documents", "download"),
        ("verifications", "create"),
        ("verifications", "review"),
        ("screening", "decide"),
        ("compliance", "decide"),
        ("compliance", "approve"),
        ("audit", "view"),
    },
    "OPERATIONS": _COMPANY_WORK,
    "DEVELOPER": frozenset({("exporters", "view"), ("deals", "view"), ("documents", "view")}),
    "API_USER": frozenset(),
}

#: Permissions that did not exist before this migration.
NEW_ACTIONS: frozenset[Grant] = frozenset(
    {
        ("settings", "manage"),
        ("exporters", "partner_intake"),
        ("deals", "view"),
        ("deals", "create"),
        ("deals", "edit"),
        ("documents", "view"),
        ("documents", "upload"),
        ("documents", "download"),
        ("qualification", "record"),
        ("compliance", "view"),
        ("compliance", "decide"),
        ("compliance", "approve"),
    }
)

# (slug, name, description, based on, extra grants)
LEAD_ROLES = (
    (
        "compliance-lead",
        "Compliance lead",
        "Compliance, plus assigning reviews and approving high-risk Clears.",
        "COMPLIANCE",
        frozenset({("compliance", "assign"), ("compliance", "approve_high_risk")}),
    ),
    (
        "sales-lead",
        "Sales lead",
        "Relationship manager, plus assigning and reassigning relationship managers.",
        "OPERATIONS",
        frozenset({("exporters", "assign_rm")}),
    ),
)

_ADMIN_DESCRIPTION_OLD = "Full access, including user and role management."
_ADMIN_DESCRIPTION_NEW = "Users, roles and settings; reads the business but never changes it."


def _grants(conn, role_id) -> frozenset[Grant]:
    rows = conn.execute(
        sa.text(f"SELECT module, action FROM {SCHEMA}.role_permission WHERE role_id = :id"),
        {"id": role_id},
    )
    return frozenset((module, action) for module, action in rows)


def _add(conn, role_id, grants) -> None:
    for module, action in sorted(grants):
        conn.execute(
            sa.text(
                f"INSERT INTO {SCHEMA}.role_permission (id, role_id, module, action) "
                "VALUES (:id, :role_id, :module, :action) "
                "ON CONFLICT ON CONSTRAINT uq_role_permission_role_module_action DO NOTHING"
            ),
            {"id": uuid.uuid4(), "role_id": role_id, "module": module, "action": action},
        )


def _remove(conn, role_id, grants) -> None:
    for module, action in sorted(grants):
        conn.execute(
            sa.text(
                f"DELETE FROM {SCHEMA}.role_permission "
                "WHERE role_id = :role_id AND module = :module AND action = :action"
            ),
            {"role_id": role_id, "module": module, "action": action},
        )


def upgrade() -> None:
    conn = op.get_bind()
    builtins = conn.execute(
        sa.text(f"SELECT id, builtin_role, slug FROM {SCHEMA}.role WHERE builtin_role IS NOT NULL")
    ).all()
    for role_id, builtin, slug in builtins:
        builtin = str(builtin)
        if builtin not in NEW_SEED:
            continue
        current = _grants(conn, role_id)
        new = NEW_SEED[builtin]
        if current == OLD_SEED[builtin]:
            _add(conn, role_id, new - current)
            _remove(conn, role_id, current - new)
        else:
            # Edited by an administrator: add what the routes now need, take nothing away.
            _add(conn, role_id, new & NEW_ACTIONS)
            removable = (current & OLD_SEED[builtin]) - new
            if removable:
                print(
                    f"auth_0007: role '{slug}' was edited, so these grants were kept and "
                    f"should be reviewed: {sorted(removable)}"
                )

    conn.execute(
        sa.text(
            f"UPDATE {SCHEMA}.role SET description = :new "
            "WHERE builtin_role = 'ADMIN' AND description = :old"
        ),
        {"new": _ADMIN_DESCRIPTION_NEW, "old": _ADMIN_DESCRIPTION_OLD},
    )

    # Custom roles: the new grants of the built-in role their holders are based on.
    customs = conn.execute(
        sa.text(f"SELECT id, slug FROM {SCHEMA}.role WHERE builtin_role IS NULL")
    ).all()
    for role_id, slug in customs:
        bases = {
            str(row[0])
            for row in conn.execute(
                sa.text(f"SELECT DISTINCT role FROM {SCHEMA}.users WHERE role_id = :id"),
                {"id": role_id},
            )
        }
        for base in bases & set(NEW_SEED):
            _add(conn, role_id, NEW_SEED[base] & NEW_ACTIONS)
        if not bases:
            print(
                f"auth_0007: custom role '{slug}' has no holders; give it the deals, "
                "documents, qualification and compliance permissions it needs in Settings."
            )

    for slug, name, description, base, extra in LEAD_ROLES:
        exists = conn.execute(
            sa.text(f"SELECT 1 FROM {SCHEMA}.role WHERE slug = :slug"), {"slug": slug}
        ).first()
        if exists:
            print(f"auth_0007: a role '{slug}' already exists; the lead role was not created.")
            continue
        role_id = uuid.uuid4()
        conn.execute(
            sa.text(
                f"INSERT INTO {SCHEMA}.role (id, slug, name, description, builtin_role, "
                "is_assignable) VALUES (:id, :slug, :name, :description, NULL, true)"
            ),
            {"id": role_id, "slug": slug, "name": name, "description": description},
        )
        _add(conn, role_id, NEW_SEED[base] | extra)


def downgrade() -> None:
    conn = op.get_bind()
    for slug, *_ in LEAD_ROLES:
        role = conn.execute(
            sa.text(f"SELECT id FROM {SCHEMA}.role WHERE slug = :slug"), {"slug": slug}
        ).first()
        if role is None:
            continue
        # Holders go back to their built-in role (role_id NULL reads the enum's row).
        conn.execute(
            sa.text(f"UPDATE {SCHEMA}.users SET role_id = NULL WHERE role_id = :id"),
            {"id": role[0]},
        )
        conn.execute(sa.text(f"DELETE FROM {SCHEMA}.role WHERE id = :id"), {"id": role[0]})

    for module, action in sorted(NEW_ACTIONS):
        conn.execute(
            sa.text(
                f"DELETE FROM {SCHEMA}.role_permission WHERE module = :module AND action = :action"
            ),
            {"module": module, "action": action},
        )
    builtins = conn.execute(
        sa.text(f"SELECT id, builtin_role FROM {SCHEMA}.role WHERE builtin_role IS NOT NULL")
    ).all()
    for role_id, builtin in builtins:
        builtin = str(builtin)
        if builtin in OLD_SEED:
            _add(conn, role_id, OLD_SEED[builtin])
    conn.execute(
        sa.text(
            f"UPDATE {SCHEMA}.role SET description = :old "
            "WHERE builtin_role = 'ADMIN' AND description = :new"
        ),
        {"new": _ADMIN_DESCRIPTION_NEW, "old": _ADMIN_DESCRIPTION_OLD},
    )
