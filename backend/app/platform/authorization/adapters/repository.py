from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.platform.authentication.models import User, UserRole
from app.platform.authorization.models import Role, RolePermission
from app.platform.database.adapters.repository import BaseRepository


class RoleRepository(BaseRepository[Role]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Role, session)

    async def get_by_id(self, role_id: uuid.UUID) -> Role | None:
        result = await self.session.execute(
            select(Role).where(Role.id == role_id).options(selectinload(Role.permissions))
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Role | None:
        result = await self.session.execute(
            select(Role).where(Role.slug == slug).options(selectinload(Role.permissions))
        )
        return result.scalar_one_or_none()

    async def get_builtin(self, builtin_role: UserRole) -> Role | None:
        """The built-in row for a legacy enum value — the row `resolve_permissions`
        reads for an account with no `role_id`."""
        result = await self.session.execute(
            select(Role).where(Role.builtin_role == builtin_role)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Role]:
        """Built-in roles first, then custom ones alphabetically — the order an
        administrator expects, with the five familiar rows at the top."""
        result = await self.session.execute(
            select(Role)
            .options(selectinload(Role.permissions))
            .order_by(Role.builtin_role.is_(None), Role.name)
        )
        return list(result.scalars().all())

    async def user_counts(self) -> dict[uuid.UUID, int]:
        """Holders per role, counting both routes to holding one.

        A user holds a role either explicitly (`users.role_id`) or implicitly,
        by carrying the legacy enum value that a built-in role maps to. Counting
        only the explicit column would report 0 for every built-in role while
        every account in the deployment actually holds one.
        """
        result = await self.session.execute(
            select(Role.id, func.count(User.id))
            .outerjoin(
                User,
                or_(
                    User.role_id == Role.id,
                    # Enum fallback: only when no explicit role is assigned,
                    # mirroring resolve_permissions' precedence exactly.
                    (User.role_id.is_(None)) & (User.role == Role.builtin_role),
                ),
            )
            .group_by(Role.id)
        )
        return {role_id: count for role_id, count in result.all()}

    async def count_active_holders_of(
        self, module: str, action: str, *, excluding: uuid.UUID | None = None
    ) -> int:
        """Active accounts that are granted one permission, by either route.

        Mirrors `resolve_permissions`' precedence: an explicit `users.role_id`
        wins, and the legacy enum applies only when it is NULL. Used to refuse a
        change that would leave nobody able to manage roles — see the caller.
        """
        criterion = or_(
            User.role_id == Role.id,
            (User.role_id.is_(None)) & (User.role == Role.builtin_role),
        )
        filters = [
            User.is_active.is_(True),
            RolePermission.module == module,
            RolePermission.action == action,
        ]
        if excluding is not None:
            filters.append(User.id != excluding)

        total = await self.session.scalar(
            select(func.count(func.distinct(User.id)))
            .select_from(User)
            .join(Role, criterion)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .where(*filters)
        )
        return int(total or 0)

    async def grants(self, role_id: uuid.UUID, module: str, action: str) -> bool:
        """Whether one role grants one permission."""
        total = await self.session.scalar(
            select(func.count())
            .select_from(RolePermission)
            .where(
                RolePermission.role_id == role_id,
                RolePermission.module == module,
                RolePermission.action == action,
            )
        )
        return bool(total)

    async def builtin_grants(self, builtin_role, module: str, action: str) -> bool:
        """Whether the built-in role for a legacy enum value grants a permission."""
        total = await self.session.scalar(
            select(func.count())
            .select_from(RolePermission)
            .join(Role, Role.id == RolePermission.role_id)
            .where(
                Role.builtin_role == builtin_role,
                RolePermission.module == module,
                RolePermission.action == action,
            )
        )
        return bool(total)

    async def replace_permissions(
        self, role: Role, pairs: set[tuple[str, str]]
    ) -> Role:
        """Make the role's grants exactly `pairs`.

        Computed as a diff rather than delete-all-then-insert so that unchanged
        rows keep their identity and `created_at` — an audit of "when was this
        granted?" survives an unrelated edit to the same role.
        """
        current = {(p.module, p.action): p for p in role.permissions}
        for key, permission in current.items():
            if key not in pairs:
                await self.session.delete(permission)
        for module, action in pairs - set(current):
            self.session.add(
                RolePermission(role_id=role.id, module=module, action=action)
            )
        await self.session.flush()
        await self.session.refresh(role, attribute_names=["permissions"])
        return role
