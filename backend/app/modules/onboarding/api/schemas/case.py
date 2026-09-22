"""
Request/response schemas for the case management API.

`CheckType` and `SubjectType` are imported from the provider contract
(`providers/dto.py`) rather than redefined. That is the one import the backlog
explicitly permits into core code — "core workflow imports only the provider
contract" — and it keeps a single definition of what a check is.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.audit import ActorType
from app.modules.onboarding.domain.dto import CheckType, SubjectType
from app.modules.onboarding.domain.entities.enums import CaseState, CaseType, TransitionSource


class PersonProfileInput(BaseModel):
    """Subject identity attributes. **PII** — never log an instance of this."""

    model_config = ConfigDict(extra="forbid")

    first_name: str | None = Field(default=None, max_length=255, repr=False)
    last_name: str | None = Field(default=None, max_length=255, repr=False)
    date_of_birth: date | None = Field(default=None, repr=False)
    nationality: str | None = Field(default=None, min_length=2, max_length=2)
    residence_country: str | None = Field(default=None, min_length=2, max_length=2)
    email: str | None = Field(default=None, max_length=255, repr=False)
    phone: str | None = Field(default=None, max_length=32, repr=False)


class PersonProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    first_name: str | None
    last_name: str | None
    date_of_birth: date | None
    nationality: str | None
    residence_country: str | None
    email: str | None
    phone: str | None


class CreateCaseRequest(BaseModel):
    """
    Create an onboarding case. The case is always created in `DRAFT`.

    The caller supplies neither `state` nor `provider_route_id`: the first is owned
    by the state machine and the second by the route resolver.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: uuid.UUID
    country_code: str = Field(min_length=2, max_length=2)
    case_type: CaseType
    subject_type: SubjectType

    cell_id: str | None = Field(default=None, max_length=64)
    product_context: str | None = Field(default=None, max_length=64)
    policy_id: str | None = Field(default=None, max_length=64)

    # A second idempotency handle. If the caller has its own id for this case, the
    # same id must never create a second case.
    external_case_id: str | None = Field(default=None, max_length=255)

    profile: PersonProfileInput | None = None
    required_checks: list[CheckType] = Field(default_factory=list)

    @field_validator("country_code")
    @classmethod
    def _upper_country(cls, v: str) -> str:
        return v.upper()


class UpdateCaseRequest(BaseModel):
    """
    Update the mutable, opaque routing attributes of a case.

    `state`, `tenant_id`, `country_code`, `case_type` and `subject_type` are not
    updatable: the first is the state machine's, and the rest define which case
    this *is*. Changing them would silently re-target a case mid-flight.
    """

    model_config = ConfigDict(extra="forbid")

    cell_id: str | None = Field(default=None, max_length=64)
    product_context: str | None = Field(default=None, max_length=64)
    policy_id: str | None = Field(default=None, max_length=64)


class CaseTransitionRequest(BaseModel):
    """
    Ask the state machine to move a case.

    The caller names the *destination* and *why*; it never names the previous state.
    The machine reads that from the case itself, so two racing callers cannot both
    believe they moved the case out of the same state.
    """

    model_config = ConfigDict(extra="forbid")

    next_state: CaseState
    source: TransitionSource
    reason: str | None = Field(default=None, max_length=1000)


class CaseTransitionResponse(BaseModel):
    """One row of the case's append-only state history."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_id: uuid.UUID
    previous_state: CaseState | None
    next_state: CaseState
    source: TransitionSource
    actor_id: uuid.UUID | None
    actor_type: ActorType
    reason: str | None
    correlation_id: uuid.UUID | None
    created_at: datetime


class CaseTransitionListResponse(BaseModel):
    case_id: uuid.UUID
    transitions: list[CaseTransitionResponse]
    total: int


class CaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    cell_id: str | None
    country_code: str
    case_type: CaseType
    subject_type: SubjectType
    product_context: str | None
    policy_id: str | None
    provider_route_id: uuid.UUID | None
    state: CaseState
    external_case_id: str | None
    idempotency_key: str
    required_checks: list[str] = Field(default_factory=list)
    profile: PersonProfileResponse | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, case) -> CaseResponse:
        return cls(
            id=case.id,
            tenant_id=case.tenant_id,
            cell_id=case.cell_id,
            country_code=case.country_code,
            case_type=case.case_type,
            subject_type=case.subject_type,
            product_context=case.product_context,
            policy_id=case.policy_id,
            provider_route_id=case.provider_route_id,
            state=case.state,
            external_case_id=case.external_case_id,
            idempotency_key=case.idempotency_key,
            required_checks=list(case.kyc_case.required_checks) if case.kyc_case else [],
            profile=(
                PersonProfileResponse.model_validate(case.profile) if case.profile else None
            ),
            created_at=case.created_at,
            updated_at=case.updated_at,
        )
