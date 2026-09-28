from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.platform.authentication.models import RefreshToken, User, UserRole
from app.platform.database.adapters.repository import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(User, session)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def email_exists(self, email: str) -> bool:
        return await self.get_by_email(email) is not None

    async def search(
        self,
        *,
        query: str | None = None,
        role: UserRole | None = None,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[User], int]:
        """Administrator user list: filter, then page. Returns the page plus
        the total matching count, so the caller can render "showing 1-50 of N"
        without a second round trip.

        `query` matches email or full name, case-insensitively, as a partial
        match — an administrator looking someone up types a fragment, not an
        exact address.
        """
        filters = []
        if query:
            pattern = f"%{query.strip()}%"
            filters.append(
                or_(User.email.ilike(pattern), User.full_name.ilike(pattern))
            )
        if role is not None:
            filters.append(User.role == role)
        if is_active is not None:
            filters.append(User.is_active.is_(is_active))

        total = await self.session.scalar(
            select(func.count()).select_from(User).where(*filters)
        )
        result = await self.session.execute(
            select(User)
            .where(*filters)
            .order_by(User.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), int(total or 0)



class RefreshTokenRepository(BaseRepository[RefreshToken]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(RefreshToken, session)

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        result = await self.session.execute(
            select(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .options(selectinload(RefreshToken.user))
        )
        return result.scalar_one_or_none()

    async def get_for_user(
        self, token_id: uuid.UUID, user_id: uuid.UUID
    ) -> RefreshToken | None:
        """Fetch one session, scoped to its owner. The user_id is part of the
        lookup rather than checked afterwards, so one user can never revoke
        another's session by guessing an id."""
        result = await self.session.execute(
            select(RefreshToken).where(
                RefreshToken.id == token_id,
                RefreshToken.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_active_for_user(self, user_id: uuid.UUID) -> list[RefreshToken]:
        """Unrevoked, unexpired sessions, newest first.

        Expired-but-unrevoked rows are filtered out here rather than shown as
        "active": they cannot be exchanged any more, so listing them would
        overstate where the account is signed in.
        """
        result = await self.session.execute(
            select(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked.is_(False),
                RefreshToken.expires_at > datetime.now(tz=UTC),
            )
            .order_by(RefreshToken.created_at.desc())
        )
        return list(result.scalars().all())

    async def revoke(self, token: RefreshToken) -> RefreshToken:
        token.revoked = True
        token.revoked_at = datetime.now(tz=UTC)
        await self.session.flush()
        return token

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        result = await self.session.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked.is_(False),
            )
        )
        for token in result.scalars().all():
            token.revoked = True
            token.revoked_at = datetime.now(tz=UTC)
        await self.session.flush()
