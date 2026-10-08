"""The permission catalogue: every module, every action, and what the five
built-in roles (and the two lead roles) start with.

This is the single definition of "what permissions exist". The database stores
which ones a role has been granted; it never defines the vocabulary, so a typo
in an API request is a 422 rather than a row nobody will ever check.

**Every module is enforced.** Each CRM route checks a permission
(`require_permission`), so what the Roles screen shows a role holding is what that
role can do. One action, `exporters:search_by_tax_id`, is declared but not consulted
(its note says why). The `enforced` flag stays in the model for a module added later, before
its routes move over; anything displaying the catalogue must surface it, since
presenting an unenforced checkbox as if it gated something would be a lie.

**The administrator runs the system, not the business.** ADMIN manages users, roles
and settings and may read companies, deals and documents to help people, but holds no
permission that creates, changes, decides or approves a business record, and never
sees full tax identifiers. Someone who does both jobs has two accounts.

**Senior work belongs to two lead roles**, seeded as ordinary, editable roles:
*Compliance lead* (Compliance plus assigning reviews and approving high-risk Clears)
and *Sales lead* (RM plus assigning relationship managers).

**`exporters:view_full_tax_id` is what unmasks tax identifiers**
(`can_reveal_identifiers`). COMPLIANCE holds it by default; OPERATIONS is masked on
every record, including the ones it is the relationship manager for — architecture
decision 12 settled the prototype that way.
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
        key="settings",
        label="System configuration",
        description="Qualification criteria and the documents a deal requires",
        enforced=True,
        actions=(
            ActionSpec(
                "manage", "Manage", "Change qualification criteria and required documents"
            ),
        ),
    ),
    ModuleSpec(
        key="exporters",
        label="Companies",
        description="Company records, contacts, activities, follow-ups and trade history",
        enforced=True,
        actions=(
            ActionSpec("view", "View", "See companies, contacts, activities and history"),
            ActionSpec("create", "Create", "Add companies, by hand or by bulk import"),
            ActionSpec(
                "edit",
                "Edit",
                "Change company details, contacts, activities, follow-ups and trade history",
            ),
            ActionSpec(
                "transition",
                "Move stage",
                "Bring a company into the pipeline, pause or end a relationship, start a "
                "background check or answer a request for more information",
            ),
            ActionSpec(
                "view_full_tax_id",
                "See full PAN / GSTIN",
                "View tax identifiers unmasked on every company",
            ),
            # Not consulted: the company list's exact PAN/GSTIN/IEC filters follow the
            # reveal rule (`exporters:view_full_tax_id`), since a hit answers "does
            # this company exist" however the row is masked.
            ActionSpec(
                "search_by_tax_id",
                "Search by full PAN",
                "Look a company up by its complete tax identifier",
                enforced=False,
            ),
            ActionSpec(
                "assign_rm",
                "Assign relationship managers",
                "Assign someone else as a company's RM, change or clear an RM, and "
                "reassign companies in bulk",
            ),
            ActionSpec(
                "partner_intake",
                "Partner intake",
                "Take in a company a partner (RXIL) has already qualified",
            ),
        ),
    ),
    ModuleSpec(
        key="deals",
        label="Deals",
        description="Deals, their buyers and their stages",
        enforced=True,
        actions=(
            ActionSpec("view", "View", "See deals"),
            ActionSpec("create", "Open", "Open a deal for a company"),
            ActionSpec(
                "edit",
                "Edit",
                "Move a deal, set its buyer and invoicing branch, record payment outcomes",
            ),
        ),
    ),
    ModuleSpec(
        key="documents",
        label="Documents",
        description="Company and deal paperwork",
        enforced=True,
        actions=(
            ActionSpec("view", "View", "See the document list and read documents on screen"),
            ActionSpec("upload", "Upload", "Add documents to a company or a deal"),
            ActionSpec("download", "Download", "Save a copy of a document"),
        ),
    ),
    ModuleSpec(
        key="qualification",
        label="Qualification",
        description="Whether a lead fits what we finance",
        enforced=True,
        actions=(
            ActionSpec(
                "record", "Record", "Record criterion results and the qualification outcome"
            ),
        ),
    ),
    ModuleSpec(
        key="verifications",
        label="Verifications",
        description="Background and vendor check results",
        enforced=True,
        actions=(
            ActionSpec("view", "View", "See verification results"),
            ActionSpec("create", "Record", "Record a check result"),
            ActionSpec("review", "Review", "Record a compliance reviewer's decision"),
        ),
    ),
    ModuleSpec(
        key="screening",
        label="Screening",
        description="The compliance screening checklist",
        enforced=True,
        actions=(
            ActionSpec("view", "View", "See the checklist and bank-activity findings"),
            ActionSpec("decide", "Decide", "Record a checklist decision"),
        ),
    ),
    ModuleSpec(
        key="compliance",
        label="Compliance work",
        description="Background checks: who reviews, decides and approves them",
        enforced=True,
        actions=(
            ActionSpec(
                "view", "View", "See background checks, their decisions, cycles and proposals"
            ),
            ActionSpec(
                "decide",
                "Decide",
                "Review a background check: claim it, record or propose decisions, start "
                "re-checks, flag GST branches",
            ),
            ActionSpec("approve", "Approve", "Approve or reject another officer's proposal"),
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
        enforced=True,
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


#: The day-to-day company work an RM does, which compliance does too.
_COMPANY_WORK: frozenset[tuple[str, str]] = _permissions_for(
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
)

#: What each built-in role is seeded with. Starting points, not guarantees: built-in
#: roles are editable by design, so a deployment can diverge from this table. The seed
#: migrations apply it once and never re-apply it.
BUILTIN_ROLE_PERMISSIONS: dict[UserRole, frozenset[tuple[str, str]]] = {
    # Runs the system — people, roles, settings, the audit trail — and reads the
    # business to help people with it. Never writes, decides or approves it.
    UserRole.ADMIN: _permissions_for(
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
    ),
    UserRole.COMPLIANCE: _COMPANY_WORK
    | _permissions_for(
        ("exporters", "view_full_tax_id"),
        ("exporters", "partner_intake"),
        ("documents", "download"),
        ("verifications", "create"),
        ("verifications", "review"),
        ("screening", "decide"),
        ("compliance", "decide"),
        ("compliance", "approve"),
        ("audit", "view"),
    ),
    # Relationship managers. Identifiers are masked for this role on every record
    # (decision 12 — there is no owner-scoped reveal); searching by a full PAN is a
    # separate permission and is granted outright.
    UserRole.OPERATIONS: _COMPANY_WORK,
    # "Read-only technical access. Tax IDs are always masked." Companies, deals and
    # documents; not the compliance surface.
    UserRole.DEVELOPER: _permissions_for(
        ("exporters", "view"),
        ("deals", "view"),
        ("documents", "view"),
    ),
    # "Reaches nothing in the CRM."
    UserRole.API_USER: frozenset(),
}

#: The two lead roles: ordinary, editable roles seeded beside the built-in ones, as
#: ``(slug, name, description, based on, extra grants)``. A lead keeps the enum role
#: they are based on (COMPLIANCE or OPERATIONS), which is what the compliance and RM
#: rules read; the role adds the senior permissions.
LEAD_ROLES: tuple[tuple[str, str, str, UserRole, frozenset[tuple[str, str]]], ...] = (
    (
        "compliance-lead",
        "Compliance lead",
        "Compliance, plus assigning reviews and approving high-risk Clears.",
        UserRole.COMPLIANCE,
        _permissions_for(("compliance", "assign"), ("compliance", "approve_high_risk")),
    ),
    (
        "sales-lead",
        "Sales lead",
        "Relationship manager, plus assigning and reassigning relationship managers.",
        UserRole.OPERATIONS,
        _permissions_for(("exporters", "assign_rm")),
    ),
)


def lead_role_permissions(slug: str) -> frozenset[tuple[str, str]]:
    """Everything a lead role is seeded with: its base role's grants plus its own."""
    for lead_slug, _name, _description, base, extra in LEAD_ROLES:
        if lead_slug == slug:
            return BUILTIN_ROLE_PERMISSIONS[base] | extra
    raise KeyError(slug)


BUILTIN_ROLE_METADATA: dict[UserRole, tuple[str, str, str]] = {
    UserRole.ADMIN: (
        "admin",
        "Administrator",
        "Users, roles and settings; reads the business but never changes it.",
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
