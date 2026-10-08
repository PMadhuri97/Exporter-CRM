"""The permission catalogue: every module, every action, and what the five
built-in roles start with.

This is the single definition of "what permissions exist". The database stores
which ones a role has been granted; it never defines the vocabulary, so a typo
in an API request is a 422 rather than a row nobody will ever check.

Two things to be honest about:

* **`enforced` marks whether a route actually consults the permission today.**
  `users`, `roles` and `compliance` do, and so does the one action of
  `exporters` that carries its own flag (`assign_rm`). The rest are declared and seeded to match
  section 3.7 of the architecture plan so that when a module's routes migrate
  off `require_role`, the behaviour they land on is already the behaviour they
  had. Anything reading this catalogue for display must surface that flag —
  presenting an unenforced checkbox as if it gated something would be a lie.
* **`exporters:view_full_tax_id` is granted to COMPLIANCE and ADMIN only**,
  matching today's masking rule: `can_reveal_identifiers` admits exactly those
  two roles and no other. OPERATIONS is masked on every record, including the
  ones it is the relationship manager for — architecture decision 12 settled the
  prototype that way, and ownership-scoped reveal waits until after it. Seeding
  OPERATIONS here would therefore widen a rule, not describe one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.platform.authentication.models import UserRole


@dataclass(frozen=True)
class ActionSpec:
    key: str
    label: str
    description: str
    #: Overrides the module's `enforced` for this one action: `True` for an action a
    #: route already consults although the rest of its module does not. `None`
    #: inherits the module's flag.
    enforced: bool | None = None

    def is_enforced(self, module: ModuleSpec) -> bool:
        return module.enforced if self.enforced is None else self.enforced


@dataclass(frozen=True)
class ModuleSpec:
    key: str
    label: str
    description: str
    #: False = declared and seeded, but no route consults it yet.
    enforced: bool
    actions: tuple[ActionSpec, ...] = field(default_factory=tuple)


CRUD = (
    ActionSpec("view", "View", "See the records"),
    ActionSpec("create", "Create", "Add new records"),
    ActionSpec("edit", "Edit", "Change existing records"),
    ActionSpec("delete", "Delete", "Remove records"),
)


CATALOG: tuple[ModuleSpec, ...] = (
    ModuleSpec(
        key="users",
        label="User management",
        description="Accounts that can sign in",
        enforced=True,
        actions=(
            ActionSpec("view", "View", "See the user list and individual accounts"),
            ActionSpec("create", "Create", "Create accounts and choose their role"),
            ActionSpec(
                "edit",
                "Edit",
                "Change a name, role or active status, and reset passwords",
            ),
        ),
    ),
    ModuleSpec(
        key="roles",
        label="Role management",
        description="Roles and the permissions they grant",
        enforced=True,
        actions=CRUD,
    ),
    ModuleSpec(
        key="exporters",
        label="Companies",
        description="Exporter profiles, contacts and activities",
        enforced=False,
        actions=(
            *CRUD[:3],
            ActionSpec("transition", "Move stage", "Change a company's lifecycle stage"),
            ActionSpec(
                "view_full_tax_id",
                "See full PAN / GSTIN",
                "View tax identifiers unmasked on every company",
            ),
            ActionSpec(
                "search_by_tax_id",
                "Search by full PAN",
                "Look a company up by its complete tax identifier",
            ),
            # Enforced although the rest of the module is not: the relationship
            # manager routes consult it (as "ADMIN or this permission").
            ActionSpec(
                "assign_rm",
                "Assign relationship managers",
                "Assign someone else as a company's RM, change or clear an RM, and "
                "reassign companies in bulk",
                enforced=True,
            ),
        ),
    ),
    ModuleSpec(
        key="verifications",
        label="Verifications",
        description="Background and vendor check results",
        enforced=False,
        actions=(
            ActionSpec("view", "View", "See verification results"),
            ActionSpec("create", "Trigger", "Run or record a verification"),
            ActionSpec("review", "Review", "Record a compliance reviewer's decision"),
        ),
    ),
    ModuleSpec(
        key="screening",
        label="Screening",
        description="The compliance screening checklist",
        enforced=False,
        actions=(
            ActionSpec("view", "View", "See the checklist"),
            ActionSpec("decide", "Decide", "Record a checklist decision"),
        ),
    ),
    ModuleSpec(
        key="compliance",
        label="Compliance work",
        description="Who reviews and approves background checks",
        enforced=True,
        actions=(
            ActionSpec(
                "assign",
                "Assign reviews",
                "Assign and reassign background-check reviewers, withdraw an absent "
                "proposer's proposal, and see everyone's reviews, overdue work and "
                "items needing attention",
            ),
            ActionSpec(
                "approve_high_risk",
                "Approve high-risk Clears",
                "Approve a CLEAR proposed with HIGH or CRITICAL risk",
            ),
        ),
    ),
    ModuleSpec(
        key="audit",
        label="Audit",
        description="Audit trails and workflow screens",
        enforced=False,
        actions=(ActionSpec("view", "View", "Read audit trails"),),
    ),
)

MODULES_BY_KEY = {module.key: module for module in CATALOG}


def is_valid_permission(module: str, action: str) -> bool:
    spec = MODULES_BY_KEY.get(module)
    if spec is None:
        return False
    return any(candidate.key == action for candidate in spec.actions)


def all_permissions() -> frozenset[tuple[str, str]]:
    return frozenset(
        (module.key, action.key) for module in CATALOG for action in module.actions
    )


def _permissions_for(*pairs: tuple[str, str]) -> frozenset[tuple[str, str]]:
    for module, action in pairs:
        assert is_valid_permission(module, action), f"not in catalogue: {module}:{action}"
    return frozenset(pairs)


#: What each built-in role is seeded with, transcribed from section 3.7 of the
#: architecture plan. These are starting points, not guarantees: built-in roles
#: are editable by design, so a deployment can diverge from this table. The
#: seed migration applies it once and never re-applies it.
BUILTIN_ROLE_PERMISSIONS: dict[UserRole, frozenset[tuple[str, str]]] = {
    # "Full access, including managing users and criteria."
    UserRole.ADMIN: all_permissions(),
    UserRole.COMPLIANCE: _permissions_for(
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
    ),
    UserRole.OPERATIONS: _permissions_for(
        ("exporters", "view"),
        ("exporters", "create"),
        ("exporters", "edit"),
        ("exporters", "transition"),
        # Identifiers are masked for this role on every record (decision 12 — there
        # is no owner-scoped reveal). Searching by a full PAN is a separate
        # permission and is granted outright per §3.7.
        ("exporters", "search_by_tax_id"),
        ("verifications", "view"),
        ("verifications", "create"),
        ("screening", "view"),
    ),
    # "Read-only technical access. Tax IDs are always masked."
    UserRole.DEVELOPER: _permissions_for(
        ("exporters", "view"),
        ("verifications", "view"),
        ("screening", "view"),
    ),
    # "Reaches nothing in the CRM."
    UserRole.API_USER: frozenset(),
}

BUILTIN_ROLE_METADATA: dict[UserRole, tuple[str, str, str]] = {
    UserRole.ADMIN: (
        "admin",
        "Administrator",
        "Full access, including user and role management.",
    ),
    UserRole.COMPLIANCE: (
        "compliance",
        "Compliance",
        "Compliance decisions, audit trails and unmasked tax identifiers.",
    ),
    UserRole.OPERATIONS: (
        # The slug stays `operations` and the enum member stays `OPERATIONS`: both
        # are written into rows already recorded. Only the display name changed
        # — the people in this role are relationship managers.
        "operations",
        "RM (Relationship Manager)",
        "Day-to-day CRM work: companies, contacts, activities and deals. "
        "Tax identifiers are always masked.",
    ),
    UserRole.DEVELOPER: (
        "developer",
        "Developer",
        "Read-only technical access. Tax identifiers are never revealed.",
    ),
    UserRole.API_USER: (
        "api-user",
        "API user",
        "External or system callers. Reaches nothing in the CRM.",
    ),
}
