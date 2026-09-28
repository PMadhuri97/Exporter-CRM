"""Repository for ``verification_review`` — **owner: Developer 4B** (§5.1).

Append-only: ``AppendOnlyRepository`` exposes no ``update`` and no ``delete``, and the
table refuses both at the database. A changed verdict is a new row that supersedes the
current one.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.entities.verification_review import VerificationReview
from app.platform.database.adapters.repository import AppendOnlyRepository


def order_chain(reviews: Iterable[VerificationReview]) -> tuple[VerificationReview, ...]:
    """One result's reviews as a chain, first review first, chain head last.

    Follows ``supersedes_review_id`` from the review that supersedes nothing. The
    database guarantees one first review and at most one successor per review, so the
    walk is unambiguous; anything not reachable from the first review (which the
    constraints make impossible) is left out rather than guessed at.
    """
    by_predecessor: dict[uuid.UUID | None, VerificationReview] = {
        review.supersedes_review_id: review for review in reviews
    }
    chain: list[VerificationReview] = []
    current = by_predecessor.get(None)
    while current is not None:
        chain.append(current)
        current = by_predecessor.get(current.id)
    return tuple(chain)


class VerificationReviewRepository(AppendOnlyRepository[VerificationReview]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(VerificationReview, session)

    async def chain_for(self, verification_result_id: uuid.UUID) -> tuple[VerificationReview, ...]:
        """One result's review chain, first to current."""
        chains = await self.chains_for((verification_result_id,))
        return chains.get(verification_result_id, ())

    async def chains_for(
        self, verification_result_ids: Iterable[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[VerificationReview, ...]]:
        """Review chains for several results in one statement; results with no review
        are absent from the mapping."""
        ids = set(verification_result_ids)
        if not ids:
            return {}
        rows = (
            await self.session.execute(
                select(VerificationReview).where(
                    VerificationReview.verification_result_id.in_(ids)
                )
            )
        ).scalars().all()
        grouped: dict[uuid.UUID, list[VerificationReview]] = {}
        for row in rows:
            grouped.setdefault(row.verification_result_id, []).append(row)
        return {result_id: order_chain(reviews) for result_id, reviews in grouped.items()}


__all__ = ["VerificationReviewRepository", "order_chain"]
