"""Request and response shapes for role management.

Separate from `schemas.py` so the user-management file does not grow a second
subject, and so the permission catalogue's shapes sit next to the role ones
that consume them.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.platform.authentication.models import UserRole
from app.platform.authorization.catalog import CATALOG, is_valid_permission

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class PermissionRef(BaseModel):
    """One (module, action) pair, validated against the catalogue.

    Validating here means an unknown pair is a 422 at the boundary rather than a
    row in `auth.role_permission` that no route will ever check — a permission
    nobody enforces looks granted in the UI and is worse than an error.
    """

    model_config = ConfigDict(extra="forbid")

    module: str = Field(max_length=50)
    action: str = Field(max_length=50)

    @field_validator("action")
    @classmethod
    def known_pair(cls, action: str, info) -> str:
        module = info.data.get("module")
        if module is not None and not is_valid_permission(module, action):
            raise ValueError(f"Unknown permission: {module}:{action}")
        return action


class RoleResponse(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    #: Set for the five roles that predate role management; NULL for custom
    #: ones. A caller can rely on this to know a role cannot be deleted.
    builtin_role: UserRole | None
    is_builtin: bool
    is_assignable: bool
    permissions: list[PermissionRef]
    #: How many accounts hold this role, counting both an explicit assignment
    #: and the legacy enum fallback — the number that makes a refused delete
    #: understandable.
    user_count: int
    created_at: datetime


class RoleListResponse(BaseModel):
    roles: list[RoleResponse]


class CreateRoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    permissions: list[PermissionRef] = Field(default_factory=list)

    @field_validator("slug")
    @classmethod
    def slug_shape(cls, v: str) -> str:
        if not SLUG_PATTERN.match(v):
            raise ValueError(
                "slug must be lowercase letters, digits and single hyphens (e.g. credit-reviewer)"
            )
        return v


class UpdateRoleRequest(BaseModel):
    """Every field optional. `permissions` replaces the whole set when present
    — a partial add/remove API would need its own ordering rules and would make
    "what does this role grant?" depend on request history rather than on one
    request body.

    `slug` is deliberately absent: it is the stable identifier other systems and
    tests refer to.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    permissions: list[PermissionRef] | None = None
    is_assignable: bool | None = None


# ── The catalogue itself ────────────────────────────────────────────────────


class ActionSpecResponse(BaseModel):
    key: str
    label: str
    description: str


class ModuleSpecResponse(BaseModel):
    key: str
    label: str
    description: str
    #: False means no route consults this module's permissions yet. A client
    #: showing these must say so — see `catalog.py`.
    enforced: bool
    actions: list[ActionSpecResponse]


class PermissionCatalogResponse(BaseModel):
    modules: list[ModuleSpecResponse]

    @classmethod
    def from_catalog(cls) -> PermissionCatalogResponse:
        return cls(
            modules=[
                ModuleSpecResponse(
                    key=module.key,
                    label=module.label,
                    description=module.description,
                    enforced=module.enforced,
                    actions=[
                        ActionSpecResponse(
                            key=action.key,
                            label=action.label,
                            description=action.description,
                        )
                        for action in module.actions
                    ],
                )
                for module in CATALOG
            ]
        )


class MyPermissionsResponse(BaseModel):
    """What the signed-in user may do, for a client deciding what to render.

    The role is included so a client can label it; the permission list is what
    it should actually branch on.
    """

    role: UserRole
    role_id: uuid.UUID | None
    role_name: str
    permissions: list[PermissionRef]
