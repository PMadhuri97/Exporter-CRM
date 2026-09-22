"""
Rail adapter data contracts.

These five types are the data half of the rails module's adapter port
(:mod:`app.modules.rails.domain.ports.RailAdapter`, ARCHITECTURE.md §2). The
port itself stays owned by the consuming module; its DTOs live here so a
vendor adapter in ``integrations/`` can construct them without importing
``modules/rails`` (the §2 rule this mirrors: see
``app.modules.onboarding.domain.ports_legacy`` for the same pattern applied
to the identity-provider port).

Fields are typed against the rail vocabulary enums in
:mod:`app.shared.enums.rails` rather than the raw ``str`` values a strict
reading of "shared is pure" might otherwise force — see that module's
docstring for why importing the module-owned enum definitions instead would
create a real circular import (not just a style violation): any import of
``app.modules.rails.*`` runs that package's ``__init__.py`` facade, which
imports this port's DTOs, which would import the enums right back.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.shared.enums.rails import (
    ConfirmationMechanism,
    FinalityType,
    RailLegStatus,
    RailStatus,
    RailType,
    SubmissionStatus,
)


class RailCapabilityDeclaration(BaseModel):
    """The capability declaration of a rail adapter."""

    model_config = ConfigDict(from_attributes=True)

    rail_id: str
    rail_name: str
    rail_type: RailType
    supported_send_assets: list[str]
    supported_receive_assets: list[str]
    supported_corridors: list[str]
    settlement_speed_minutes_p50: int
    settlement_speed_minutes_p99: int
    finality_type: FinalityType
    confirmation_mechanism: ConfirmationMechanism
    polling_interval_seconds: int | None = None
    #: Ceiling the Polling Manager holds itself to when calling this rail's
    #: status-enquiry API, in calls per second. ``None`` — the default — means
    #: the rail publishes no limit and polls are paced by
    #: ``polling_interval_seconds`` alone. Declared per rail because a limit is
    #: a property of one vendor's API, never of the platform: one global
    #: limiter would let a chatty rail starve a quiet one.
    polling_rate_limit_per_second: float | None = None
    max_transaction_amount_usd: int | None = None
    min_transaction_amount_usd: int | None = None
    fee_structure: dict[str, Any]
    requires_purpose_code: bool
    requires_beneficiary_bank_details: bool
    requires_sender_details: bool
    circuit_breaker_open_threshold: int = 5
    circuit_breaker_open_duration_seconds: int = 60
    status: RailStatus
    registered_at: datetime
    last_health_check_at: datetime | None = None


class LegSubmissionRequest(BaseModel):
    """The standardised request structure passed to the submission dispatcher."""

    model_config = ConfigDict(from_attributes=True)

    leg_id: uuid.UUID
    settlement_id: uuid.UUID
    rail_id: str
    idempotency_key: str
    correlation_id: str
    send_amount: int
    send_asset_code: str
    receive_amount: int
    receive_asset_code: str
    sender_details: dict[str, Any]
    beneficiary_details: dict[str, Any]
    purpose_code: str | None = None
    reference: str
    metadata: dict[str, Any]


class LegSubmissionResponse(BaseModel):
    """The standardised response structure returned by the submission dispatcher."""

    model_config = ConfigDict(from_attributes=True)

    leg_id: uuid.UUID
    rail_id: str
    submission_status: SubmissionStatus
    rail_reference: str
    estimated_settlement_at: datetime | None = None
    rejection_reason: str | None = None
    raw_rail_response: dict[str, Any]
    rail_called: bool = True
    outcome: str | None = None
    lease_generation: int = 1


class LegStatusUpdate(BaseModel):
    """The standardised status update that rail adapters push to the abstraction layer."""

    model_config = ConfigDict(from_attributes=True)

    leg_id: uuid.UUID
    rail_id: str
    rail_reference: str
    status: RailLegStatus
    settled_at: datetime | None = None
    failed_at: datetime | None = None
    failure_code: str | None = None
    failure_reason: str | None = None
    on_chain_tx_hash: str | None = None
    confirmations: int | None = None
    #: The rail's own unique id for this webhook delivery, when it carries one.
    #: Combined with ``rail_reference`` it is the idempotency key the webhook
    #: processor checks against ``leg_status_update_record``. ``None`` for poll
    #: results and on-chain events, which do not dedupe against each other.
    rail_event_id: str | None = None
    raw_rail_event: dict[str, Any]


class RailHealthStatus(BaseModel):
    """Structured health status returned by the rail adapter."""

    model_config = ConfigDict(from_attributes=True)

    status: RailStatus
    response_time_ms: int
    last_successful_transaction_at: datetime | None = None
    known_issues: str | None = None
