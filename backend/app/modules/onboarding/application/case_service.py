"""
CaseService — creation and update of onboarding/KYC cases.

Creation:
  1. Resolve an existing case by either idempotency handle. If found, return it.
  2. Insert the case in `DRAFT`, inside a savepoint so a concurrent duplicate
     loses at the UNIQUE constraint rather than racing past the lookup.
  3. Attach the subject's `person_profile` and the case's `kyc_case`.
  4. Record an audit event.

Update writes an audit event too — "every create/update writes an audit event" is an
acceptance criterion, not a nicety.

`transition()` is **the only writer of case state anywhere in the platform**. It validates the move against the legal-transition table, then — and
only then — assigns `Case.state`, appends a `case_state_transition` row, and records
an audit event. An illegal move raises `IllegalTransitionError` (409) before anything
is assigned, so the case is not mutated.

**Not here yet.** No route resolution, no provider call of any kind,
and no provider-driven transition: a webhook still cannot move a case,
because nothing in this module calls `transition()` on a provider's behalf yet.
"""
from __future__ import annotations

import uuid

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import ActorType, AuditService
from app.modules.onboarding.api.schemas.case import (
    CaseResponse,
    CaseTransitionListResponse,
    CaseTransitionRequest,
    CaseTransitionResponse,
    CreateCaseRequest,
    UpdateCaseRequest,
)
from app.modules.onboarding.domain.entities.case import Case
from app.modules.onboarding.domain.entities.case_state_transition import CaseStateTransition
from app.modules.onboarding.domain.entities.enums import CaseState, TransitionSource
from app.modules.onboarding.domain.entities.kyc_case import KycCase
from app.modules.onboarding.domain.entities.person_profile import PersonProfile
from app.modules.onboarding.domain.policies.state_machine import (
    assert_legal,
    permit_state_write,
    resolve_correlation_id,
)
from app.modules.onboarding.infrastructure.repositories import (
    CaseRepository,
    CaseStateTransitionRepository,
    KycCaseRepository,
    PersonProfileRepository,
)
from app.shared.exceptions import NotFoundError

logger = structlog.get_logger(__name__)


class CaseService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._cases = CaseRepository(db)
        self._profiles = PersonProfileRepository(db)
        self._kyc_cases = KycCaseRepository(db)
        self._transitions = CaseStateTransitionRepository(db)
        self._audit = AuditService(db)

    # ── Create ────────────────────────────────────────────────────────────────

    async def create_case(
        self,
        request: CreateCaseRequest,
        *,
        idempotency_key: str,
        actor_id: uuid.UUID | None,
    ) -> tuple[CaseResponse, bool]:
        """
        Create a case, or return the one this request already created.

        Returns `(response, created)`. `created` is False on an idempotent replay,
        which the router turns into a `200` instead of a `201`.
        """
        existing = await self._resolve_existing(
            tenant_id=request.tenant_id,
            idempotency_key=idempotency_key,
            external_case_id=request.external_case_id,
        )
        if existing is not None:
            logger.info(
                "onboarding_case_create_replayed",
                case_id=str(existing.id),
                tenant_id=str(existing.tenant_id),
            )
            return CaseResponse.from_model(existing), False

        case = Case(
            idempotency_key=idempotency_key,
            external_case_id=request.external_case_id,
            tenant_id=request.tenant_id,
            cell_id=request.cell_id,
            country_code=request.country_code,
            case_type=request.case_type,
            subject_type=request.subject_type,
            product_context=request.product_context,
            policy_id=request.policy_id,
            state=CaseState.DRAFT,
        )

        try:
            # A savepoint, so that losing the UNIQUE race rolls back only this
            # INSERT and leaves the request's transaction usable.
            async with self._db.begin_nested():
                self._db.add(case)
                await self._db.flush()
        except IntegrityError:
            winner = await self._resolve_existing(
                tenant_id=request.tenant_id,
                idempotency_key=idempotency_key,
                external_case_id=request.external_case_id,
            )
            if winner is None:
                # The conflict was not one of the idempotency constraints.
                raise
            logger.info("onboarding_case_create_lost_race", case_id=str(winner.id))
            return CaseResponse.from_model(winner), False

        if request.profile is not None:
            await self._profiles.create(
                PersonProfile(case_id=case.id, **request.profile.model_dump())
            )

        await self._kyc_cases.create(
            KycCase(
                case_id=case.id,
                required_checks=[check.value for check in request.required_checks],
            )
        )

        await self._db.refresh(case, attribute_names=["profile", "kyc_case"])

        await self._audit.record(
            "onboarding.case.created",
            actor_id=actor_id,
            actor_type=ActorType.API_CLIENT,
            payload=self._audit_payload(case),
        )

        logger.info(
            "onboarding_case_created",
            case_id=str(case.id),
            tenant_id=str(case.tenant_id),
            case_type=case.case_type.value,
            state=case.state.value,
        )
        return CaseResponse.from_model(case), True

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_case(self, case_id: uuid.UUID) -> CaseResponse:
        case = await self._require_case(case_id)
        return CaseResponse.from_model(case)

    # ── Update ────────────────────────────────────────────────────────────────

    async def update_case(
        self,
        case_id: uuid.UUID,
        request: UpdateCaseRequest,
        *,
        actor_id: uuid.UUID | None,
    ) -> CaseResponse:
        """
        Update a case's opaque routing attributes.

        `state` is not reachable from here: `UpdateCaseRequest` cannot express it and
        `CaseRepository.update()` would reject it anyway.
        """
        case = await self._require_case(case_id)
        changes = request.model_dump(exclude_unset=True)

        if changes:
            before = {key: getattr(case, key) for key in changes}
            await self._cases.update(case, **changes)
            await self._db.refresh(case, attribute_names=["profile", "kyc_case"])
            await self._audit.record(
                "onboarding.case.updated",
                actor_id=actor_id,
                actor_type=ActorType.API_CLIENT,
                payload={**self._audit_payload(case), "changed": changes, "previous": before},
            )
            logger.info(
                "onboarding_case_updated",
                case_id=str(case.id),
                changed=sorted(changes),
            )

        return CaseResponse.from_model(case)

    # ── Transition — the only writer of case state ─────────────────

    async def transition(
        self,
        case_id: uuid.UUID,
        request: CaseTransitionRequest,
        *,
        actor_id: uuid.UUID | None,
    ) -> CaseResponse:
        """
        Move a case to `request.next_state`, or raise `IllegalTransitionError` (409).

        The order of operations is the acceptance criterion, not an implementation
        detail: validate, then assign, then append the transition row, then audit.
        Because validation precedes assignment, an illegal move leaves the case
        exactly as it was — there is nothing to roll back.

        All three writes share the request's transaction (`get_db` commits on
        success), so a case never advances without its transition row and its audit
        event.
        """
        case = await self._require_case(case_id)
        previous_state = case.state

        assert_legal(previous_state, request.next_state)

        actor_type = self._actor_type_for(request.source)
        # A system or provider-driven move has no human behind it (§4.11).
        recorded_actor_id = None if actor_type is ActorType.SYSTEM else actor_id
        correlation_id = resolve_correlation_id()

        # The one window in which `Case.state` may be assigned. Outside it the
        # `_guard_state_assignment` listener raises DirectStateAssignmentError.
        with permit_state_write():
            case.state = request.next_state
        await self._db.flush()

        await self._transitions.create(
            CaseStateTransition(
                case_id=case.id,
                previous_state=previous_state,
                next_state=request.next_state,
                source=request.source,
                actor_id=recorded_actor_id,
                actor_type=actor_type,
                reason=request.reason,
                correlation_id=correlation_id,
            )
        )

        await self._audit.record(
            "onboarding.case.state_changed",
            actor_id=recorded_actor_id,
            actor_type=actor_type,
            correlation_id=correlation_id,
            payload={
                **self._audit_payload(case),
                "previous_state": previous_state.value,
                "next_state": request.next_state.value,
                "source": request.source.value,
                "reason": request.reason,
            },
        )

        # A full refresh, not a partial one: the UPDATE fires `updated_at`'s
        # server-side `onupdate`, which expires the column, and the response reads it.
        await self._db.refresh(case)

        logger.info(
            "onboarding_case_state_changed",
            case_id=str(case.id),
            previous_state=previous_state.value,
            next_state=request.next_state.value,
            source=request.source.value,
            actor_type=actor_type.value,
        )
        return CaseResponse.from_model(case)

    async def list_transitions(self, case_id: uuid.UUID) -> CaseTransitionListResponse:
        """The case's append-only state history, oldest first."""
        await self._require_case(case_id)
        rows = await self._transitions.list_by_case(case_id)
        return CaseTransitionListResponse(
            case_id=case_id,
            transitions=[CaseTransitionResponse.model_validate(row) for row in rows],
            total=len(rows),
        )

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _actor_type_for(source: TransitionSource) -> ActorType:
        """
        Map the transition's *source* onto the audit store's *actor type*.

        They are different vocabularies answering different questions — "what kind of
        event caused this?" versus "who acted?" — and both are recorded. A provider
        callback is the platform acting on a provider's evidence, never the provider
        acting on the platform: it is a `SYSTEM` actor, and the fact that a provider
        prompted it is carried by `source`, not by the actor.
        """
        return {
            TransitionSource.USER_ACTION: ActorType.API_CLIENT,
            TransitionSource.ADMIN_OVERRIDE: ActorType.COMPLIANCE_OFFICER,
            TransitionSource.SYSTEM: ActorType.SYSTEM,
            TransitionSource.PROVIDER_CALLBACK: ActorType.SYSTEM,
        }[source]

    async def _resolve_existing(
        self,
        *,
        tenant_id: uuid.UUID,
        idempotency_key: str,
        external_case_id: str | None,
    ) -> Case | None:
        """
        Look up a case by either idempotency handle, in the order the backlog names
        them: "the same idempotency key / external id" both return the same record.
        """
        case = await self._cases.get_by_idempotency_key(tenant_id, idempotency_key)
        if case is not None:
            return case
        if external_case_id is not None:
            return await self._cases.get_by_external_case_id(tenant_id, external_case_id)
        return None

    async def _require_case(self, case_id: uuid.UUID) -> Case:
        case = await self._cases.get_by_id(case_id)
        if case is None:
            raise NotFoundError(f"Case {case_id} not found")
        return case

    @staticmethod
    def _audit_payload(case: Case) -> dict:
        """
        Identifiers and opaque routing keys only.

        No `person_profile` field ever appears here: `audit_events.payload` is
        queryable and long-lived, and §5.3 forbids PII in it.
        """
        return {
            "case_id": str(case.id),
            "tenant_id": str(case.tenant_id),
            "cell_id": case.cell_id,
            "country_code": case.country_code,
            "case_type": case.case_type.value,
            "subject_type": case.subject_type.value,
            "product_context": case.product_context,
            "policy_id": case.policy_id,
            "state": case.state.value,
            "external_case_id": case.external_case_id,
        }
