"""
Middesk API request and response data models.

Defines Pydantic anti-corruption models matching Middesk REST API schema:
  - Business creation and response (/v1/businesses)
  - Address, Person, Finding, Order sub-models
  - Webhook event payload validation
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MiddeskAddress(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    address_line1: str | None = None
    address_line2: str | None = None
    line1: str | None = None
    line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    zip: str | None = None
    country: str | None = "US"


class MiddeskPerson(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    email: str | None = None


class MiddeskFinding(BaseModel):
    """Adverse finding item (e.g. pending lawsuit, tax lien, regulatory action)."""
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str | None = None
    type: str | None = None  # e.g. "lawsuit", "tax_lien", "regulatory_action"
    severity: str | None = None  # e.g. "low", "medium", "high"
    description: str | None = None


class MiddeskOrder(BaseModel):
    """Verification order status on a Middesk business object."""
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str | None = None
    status: str | None = None  # "pending", "completed", "failed"
    product: str | None = None


class MiddeskBusiness(BaseModel):
    """Middesk Business object representation."""
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str = "unknown"
    name: str | None = None
    verified_legal_name: str | None = None
    tin: str | None = None
    entity_type: str | None = None
    status: str | None = None  # "active", "inactive", "dissolved", "not_found", "in_review"
    registration_status: str | None = None  # "active", "inactive", "dissolved", "good_standing"
    registration_number: str | None = None
    address: str | dict[str, Any] | MiddeskAddress | None = None
    addresses: tuple[dict[str, Any] | MiddeskAddress, ...] | list[Any] = ()
    people: tuple[MiddeskPerson, ...] | list[Any] = ()
    findings: tuple[dict[str, Any] | MiddeskFinding, ...] | list[Any] = ()
    orders: tuple[MiddeskOrder, ...] | list[Any] = ()
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class MiddeskWebhookPayload(BaseModel):
    """Inbound webhook event structure from Middesk."""
    model_config = ConfigDict(frozen=True, extra="ignore")

    event: str | None = None
    event_type: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
