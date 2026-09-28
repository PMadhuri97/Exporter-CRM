"""Role and permission tables.

These live in the `auth` schema beside `auth.users` (which carries the
`role_id` foreign key), but in the `authorization` package rather than
`authentication`: authenticating is proving who you are, authorizing is
deciding what you may do, and the permission catalogue belongs to the latter.

Model shape, and why:

* **A permission row means "granted".** There is no `granted` boolean, because
  a row that says `granted=false` and a missing row mean the same thing to
  every caller, and two representations of one fact eventually disagree. The
  full grid the UI renders comes from the static catalogue in `catalog.py`, not
  from the table.
* **`builtin_role` links a row to the legacy `UserRole` enum.** The five roles
  that existed before this table still have to resolve for the 21 `require_role`
  call sites that have not migrated yet, so each one keeps a row whose
  `builtin_role` names it. A custom role has `builtin_role = NULL`.
* Built-in roles' *permissions* are editable (a deliberate decision), but the
  rows themselves cannot be deleted — deleting one would leave users whose
  legacy enum value no longer resolves to anything.
"""

import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.platform.authentication.models import SCHEMA, UserRole
from app.platform.database.models import AnerModel


class Role(AnerModel):
    __tablename__ = "role"
    __table_args__ = (
        Index("ix_role_slug", "slug", unique=True),
        # One row per legacy enum value, at most. Partial-free unique index:
        # Postgres treats NULLs as distinct, so any number of custom roles
        # (builtin_role IS NULL) coexist while each built-in stays unique.
        Index("ix_role_builtin_role", "builtin_role", unique=True),
        {"schema": SCHEMA},
    )

    #: Stable machine name (`admin`, `credit-reviewer`). What API callers and
    #: tests refer to, so renaming a role's display name breaks nothing.
    slug: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Set for the five roles that predate this table; NULL for custom roles.
    builtin_role: Mapped[UserRole | None] = mapped_column(
        Enum(UserRole, name="user_role_enum", schema=SCHEMA, create_type=False),
        nullable=True,
    )
    #: Custom roles are assignable only once the routes they would gate have
    #: migrated off `require_role`; until then this flag keeps an unfinished
    #: role out of the assignment picker without deleting it.
    is_assignable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def is_builtin(self) -> bool:
        return self.builtin_role is not None


class RolePermission(AnerModel):
    """One granted (module, action) pair.

    `action` is an open string rather than an enum so the catalogue can express
    capabilities that are not CRUD — `view_full_tax_id` and `search_by_tax_id`
    from section 3.7 of the architecture plan are permissions in exactly the
    same sense as `edit`, and forcing them into a four-value enum would mean
    inventing a second mechanism for them. Valid pairs are validated against
    `catalog.py` at the API boundary, not by the database.
    """

    __tablename__ = "role_permission"
    __table_args__ = (
        UniqueConstraint(
            "role_id", "module", "action", name="uq_role_permission_role_module_action"
        ),
        {"schema": SCHEMA},
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.role.id", ondelete="CASCADE"),
        nullable=False,
    )
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)

    role: Mapped["Role"] = relationship(back_populates="permissions")
