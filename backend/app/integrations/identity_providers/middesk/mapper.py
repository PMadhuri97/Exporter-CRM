"""
Failure code and findings translation table for Middesk vendor adapter.

Maps Middesk specific status codes, registration statuses, and finding types
to platform canonical KYBVerificationResult data shapes via typed anti-corruption Pydantic models.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from app.integrations.identity_providers.middesk.models import MiddeskBusiness
from app.shared.contracts.kyb import KYBVerificationResult
from app.shared.enums.kyb import NormalisedResult

logger = structlog.get_logger(__name__)


def map_middesk_status(
    status: str | None,
    registration_status: str | None,
    findings: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
) -> NormalisedResult:
    """
    Map raw Middesk status strings to normalized platform NormalisedResult.
    """
    stat = (status or "").lower()
    reg_stat = (registration_status or "").lower()

    if stat == "not_found" or reg_stat == "not_found":
        return NormalisedResult.NOT_FOUND

    if stat in ("dissolved", "rejected", "revoked", "bankrupt") or reg_stat in ("dissolved", "revoked", "bankrupt"):
        return NormalisedResult.REJECTED

    if stat in ("pending", "processing", "in_progress", "in_review"):
        return NormalisedResult.PENDING

    if any(f.get("type") in ("lawsuit", "tax_lien", "regulatory_action") for f in findings):
        return NormalisedResult.REQUIRES_MANUAL_REVIEW

    if reg_stat in ("inactive", "suspended"):
        return NormalisedResult.REQUIRES_MANUAL_REVIEW

    if reg_stat in ("active", "good_standing") or stat in ("verified", "active", "completed"):
        return NormalisedResult.VERIFIED

    return NormalisedResult.REQUIRES_MANUAL_REVIEW


def map_to_kyb_verification_result(
    business_id: str,
    raw_payload: dict[str, Any],
    retrieved_at: datetime | None = None,
) -> KYBVerificationResult:
    """
    Construct canonical KYBVerificationResult from Middesk payload via typed MiddeskBusiness anti-corruption model.
    """
    try:
        model = MiddeskBusiness.model_validate(raw_payload)
    except Exception as exc:
        logger.warning(
            "middesk_anti_corruption_model_validation_failed",
            error=str(exc),
            business_id=business_id,
        )
        model = MiddeskBusiness(id=business_id, raw_payload=raw_payload)

    status = model.status or raw_payload.get("status")
    reg_status = model.registration_status or raw_payload.get("registration_status")

    raw_findings = model.findings or raw_payload.get("findings") or []
    findings_dicts: list[dict[str, Any]] = []
    for f in raw_findings:
        if isinstance(f, dict):
            findings_dicts.append(f)
        elif hasattr(f, "model_dump"):
            findings_dicts.append(f.model_dump())

    norm_res = map_middesk_status(status, reg_status, findings_dicts)

    discrepancies: list[str] = []
    if norm_res == NormalisedResult.NOT_FOUND:
        discrepancies.append("Entity not found in US Secretary of State filings")
    elif norm_res == NormalisedResult.REJECTED:
        discrepancies.append(f"Entity registration status is {reg_status or status}")
    elif norm_res == NormalisedResult.REQUIRES_MANUAL_REVIEW:
        for f in findings_dicts:
            if f.get("description"):
                discrepancies.append(str(f["description"]))
            elif f.get("type"):
                discrepancies.append(f"Adverse finding: {f['type']}")

    address = model.address or raw_payload.get("address")
    if not address and model.addresses:
        address = model.addresses[0]
    elif not address and raw_payload.get("addresses"):
        addrs = raw_payload["addresses"]
        if isinstance(addrs, list) and addrs:
            address = addrs[0]

    verified_address_str: str | None = None
    if isinstance(address, str):
        verified_address_str = address
    elif isinstance(address, dict):
        line1 = address.get("line1") or address.get("address_line1") or ""
        city = address.get("city") or ""
        state = address.get("state") or ""
        postal_code = address.get("postal_code") or address.get("zip") or ""
        parts = [p for p in [line1, city, state, postal_code] if p]
        verified_address_str = ", ".join(parts) if parts else str(address)
    elif hasattr(address, "line1"):
        line1 = getattr(address, "line1", None) or getattr(address, "address_line1", None) or ""
        city = getattr(address, "city", None) or ""
        state = getattr(address, "state", None) or ""
        postal_code = getattr(address, "postal_code", None) or getattr(address, "zip", None) or ""
        parts = [p for p in [line1, city, state, postal_code] if p]
        verified_address_str = ", ".join(parts) if parts else None

    legal_name = model.verified_legal_name or model.name or raw_payload.get("verified_legal_name") or raw_payload.get("name")
    reg_num = model.registration_number or model.tin or raw_payload.get("registration_number") or raw_payload.get("tin")
    target_id = business_id or model.id or "unknown"

    return KYBVerificationResult(
        vendor_id="middesk",
        vendor_reference=target_id,
        normalised_result=norm_res,
        verified_legal_name=legal_name,
        verified_registration_number=reg_num,
        verified_address=verified_address_str,
        discrepancies=discrepancies,
        raw_response_reference=f"middesk://business/{target_id}",
        retrieved_at=retrieved_at or datetime.now(UTC),
    )
