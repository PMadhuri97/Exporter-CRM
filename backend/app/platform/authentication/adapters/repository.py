from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.platform.authentication.models import RefreshToken, User
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
