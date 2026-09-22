"""Trulioo KYB vendor adapter — Epic 4.1 / S2T2 (AL-669).

Implements the :class:`~app.modules.kyb.domain.ports.KYBAdapter` interface for
international entity verification.  Covers India (MCA/CIN + GST/GSTIN +
registered address) and all other international markets not served by Middesk.

Processing mode: **synchronous** — the Trulioo API returns a complete result
within the call.  ``get_verification_status`` raises ``NotImplementedError``
per the KYB interface specification v1.0 §2 for synchronous vendors.

India-specific logic:

* MCA registry check using the CIN (Corporate Identity Number).
* GST registration verification using the GSTIN.
* Registered-office address confirmation.
* CIN↔GSTIN cross-check: if both identifiers are provided, the adapter
  verifies they correspond to the same legal entity.  A mismatch triggers
  ``REQUIRES_MANUAL_REVIEW``.

Schema-change detection: the adapter validates that the Trulioo response
contains the expected top-level and datasource-level keys.  Unexpected
structure is logged as an operational alert (without raw PII) so the team
can update the mapping proactively.

All log events are PII-masked via :mod:`pii_masking`.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from app.integrations.kyb.trulioo.client import TruliooApiClient
from app.integrations.kyb.trulioo.exceptions import (
    TruliooApiError,
)
from app.integrations.kyb.trulioo.failure_codes import (
    is_known_record_status,
    translate_field_status,
    translate_record_status,
)
from app.integrations.kyb.trulioo.pii_masking import (
    mask_entity_for_logging,
    mask_value,
)
from app.modules.kyb.domain.ports import KYBAdapter
from app.shared.contracts.kyb import (
    EntityVerificationRequest,
    KYBVendorCapabilityDeclaration,
    KYBVerificationResult,
    VendorHealthStatus,
)
from app.shared.enums.kyb import (
    KYBVendorProcessingMode,
    NormalisedResult,
    VendorHealthStatusEnum,
)

logger = structlog.get_logger(__name__)

# ── Vendor metadata ──────────────────────────────────────────────────────────
VENDOR_ID = "trulioo"
VENDOR_NAME = "Trulioo GlobalGateway"

# Representative set of supported countries (non-US, international markets).
# The full Trulioo catalogue covers 195+ countries; this list contains the
# key markets for the Walk phase.  Maintained here rather than fetched at
# runtime so the adapter's capability declaration is deterministic.
SUPPORTED_COUNTRIES: list[str] = [
    "IN",  # India — primary market with MCA/GSTIN-specific logic
    "GB",  # United Kingdom
    "CA",  # Canada
    "AU",  # Australia
    "DE",  # Germany
    "FR",  # France
    "SG",  # Singapore
    "HK",  # Hong Kong
    "JP",  # Japan
    "BR",  # Brazil
    "AE",  # United Arab Emirates
    "NL",  # Netherlands
    "IE",  # Ireland
    "CH",  # Switzerland
    "NZ",  # New Zealand
    "ZA",  # South Africa
    "MX",  # Mexico
    "KR",  # South Korea
]

SUPPORTED_ENTITY_TYPES: list[str] = [
    "PRIVATE_LIMITED",
    "PUBLIC_LIMITED",
    "LLP",
    "PARTNERSHIP",
    "SOLE_PROPRIETORSHIP",
    "CORPORATION",
]

# ── Expected response schema keys (for schema-change detection) ──────────────
_EXPECTED_TOP_KEYS = {"TransactionID", "Record"}
_EXPECTED_RECORD_KEYS = {"TransactionRecordID", "RecordStatus", "DatasourceResults"}
_EXPECTED_DS_KEYS = {"DatasourceName", "DatasourceFields", "Errors"}


class TruliooAdapter(KYBAdapter):
    """KYB vendor adapter for Trulioo international entity verification.

    Parameters
    ----------
    client:
        An optional pre-configured :class:`TruliooApiClient`.  When ``None``
        (the default) a client is created from Settings.
    """

    def __init__(self, *, client: TruliooApiClient | None = None) -> None:
        self._client = client or TruliooApiClient()

    # ── KYBAdapter interface ─────────────────────────────────────────────────

    def declare_capabilities(self) -> KYBVendorCapabilityDeclaration:
        return KYBVendorCapabilityDeclaration(
            vendor_id=VENDOR_ID,
            vendor_name=VENDOR_NAME,
            supported_countries=SUPPORTED_COUNTRIES,
            supported_entity_types=SUPPORTED_ENTITY_TYPES,
            processing_mode=KYBVendorProcessingMode.SYNCHRONOUS,
        )

    def verify_entity(self, entity: EntityVerificationRequest) -> KYBVerificationResult:
        """Submit entity for verification via the Trulioo API.

        For Indian entities (``registration_country == "IN"``), additionally
        performs the CIN↔GSTIN cross-check when both identifiers are present.

        Returns a complete :class:`KYBVerificationResult` — the adapter is
        synchronous and never returns ``PENDING``.
        """
        masked = mask_entity_for_logging(
            legal_name=entity.legal_name,
            registration_number=entity.registration_number,
            tax_id=entity.tax_identification_number,
            address=entity.registered_address,
            country=entity.registration_country,
        )
        logger.info("trulioo_verify_entity_started", **masked)

        data_fields = self._build_data_fields(entity)

        try:
            raw_response = self._client.verify(entity.registration_country, data_fields)
        except TruliooApiError:
            logger.exception("trulioo_verify_entity_api_error", **masked)
            raise

        # ── Schema-change detection ──────────────────────────────────────────
        self._validate_response_schema(raw_response)

        # ── Extract result ───────────────────────────────────────────────────
        record = raw_response.get("Record", {})
        record_status = record.get("RecordStatus", "")
        transaction_id = raw_response.get("TransactionID", str(uuid.uuid4()))

        # Alert on unknown status codes
        if record_status and not is_known_record_status(record_status):
            logger.error(
                "trulioo_unknown_record_status",
                record_status=record_status,
                transaction_id=transaction_id,
                **masked,
            )

        normalised = translate_record_status(record_status)
        ds_results = record.get("DatasourceResults", [])

        # ── Extract verified fields and discrepancies ────────────────────────
        verified_legal_name: str | None = None
        verified_reg_number: str | None = None
        verified_address: str | None = None
        discrepancies: list[str] = []
        cin_legal_name: str | None = None
        gstin_legal_name: str | None = None

        for ds in ds_results:
            ds_name = ds.get("DatasourceName", "")
            fields = ds.get("DatasourceFields", [])

            for field in fields:
                field_name = field.get("FieldName", "")
                field_status = field.get("Status", "")
                field_result = translate_field_status(field_status)

                if field_name == "BusinessName":
                    if field_result == NormalisedResult.VERIFIED:
                        name_val = field.get("Value", "")
                        verified_legal_name = name_val
                        if "MCA" in ds_name.upper() or "Ministry" in ds_name:
                            cin_legal_name = name_val
                        elif "GST" in ds_name.upper():
                            gstin_legal_name = name_val
                    else:
                        discrepancies.append(
                            f"BusinessName {field_status} in {ds_name}"
                        )

                elif field_name == "BusinessRegistrationNumber":
                    if field_result == NormalisedResult.VERIFIED:
                        verified_reg_number = field.get("Value", entity.registration_number)
                    else:
                        discrepancies.append(
                            f"BusinessRegistrationNumber {field_status} in {ds_name}"
                        )

                elif field_name == "Address":
                    if field_result == NormalisedResult.VERIFIED:
                        verified_address = field.get("Value", entity.registered_address)
                    else:
                        discrepancies.append(
                            f"Address {field_status} in {ds_name}"
                        )

                elif field_name == "TaxIDNumber":
                    if field_result != NormalisedResult.VERIFIED:
                        discrepancies.append(
                            f"TaxIDNumber {field_status} in {ds_name}"
                        )

            # Collect errors from the datasource
            for err in ds.get("Errors", []):
                discrepancies.append(
                    f"DatasourceError in {ds_name}: {err.get('Message', 'unknown')}"
                )

        # ── India CIN↔GSTIN cross-check ──────────────────────────────────────
        if (
            entity.registration_country == "IN"
            and entity.tax_identification_number
            and normalised == NormalisedResult.VERIFIED
        ):
            cross_check = self._check_cin_gstin_consistency(
                cin_legal_name=cin_legal_name,
                gstin_legal_name=gstin_legal_name,
                cin=entity.registration_number,
                gstin=entity.tax_identification_number,
            )
            if not cross_check:
                normalised = NormalisedResult.REQUIRES_MANUAL_REVIEW
                discrepancies.append(
                    "CIN and GSTIN do not correspond to the same legal entity"
                )
                logger.warning(
                    "trulioo_cin_gstin_mismatch",
                    transaction_id=transaction_id,
                    cin=mask_value(entity.registration_number),
                    gstin=mask_value(entity.tax_identification_number),
                )

        result = KYBVerificationResult(
            vendor_id=VENDOR_ID,
            vendor_reference=transaction_id,
            normalised_result=normalised,
            verified_legal_name=verified_legal_name,
            verified_registration_number=verified_reg_number,
            verified_address=verified_address,
            discrepancies=discrepancies,
            raw_response_reference=f"trulioo:{transaction_id}",
            retrieved_at=datetime.now(UTC),
        )

        logger.info(
            "trulioo_verify_entity_completed",
            normalised_result=result.normalised_result.value,
            transaction_id=transaction_id,
            discrepancy_count=len(discrepancies),
            **masked,
        )

        return result

    def get_verification_status(self, vendor_reference: str) -> KYBVerificationResult:
        """Not applicable — Trulioo is a synchronous vendor.

        Per KYB interface specification v1.0 §2: synchronous vendors should
        return NOT_SUPPORTED since they return a complete result from
        ``verify_entity``.
        """
        return KYBVerificationResult(
            vendor_id=VENDOR_ID,
            vendor_reference=vendor_reference,
            normalised_result=NormalisedResult.NOT_SUPPORTED,
            discrepancies=[],
            raw_response_reference=f"trulioo:{vendor_reference}",
            retrieved_at=datetime.now(UTC),
        )

    def get_vendor_health(self) -> VendorHealthStatus:
        start = datetime.now(UTC)
        try:
            self._client.test_connection()
            elapsed_ms = int((datetime.now(UTC) - start).total_seconds() * 1000)
            return VendorHealthStatus(
                status=VendorHealthStatusEnum.HEALTHY,
                response_time_ms=elapsed_ms,
            )
        except TruliooApiError:
            elapsed_ms = int((datetime.now(UTC) - start).total_seconds() * 1000)
            logger.exception("trulioo_health_check_failed")
            return VendorHealthStatus(
                status=VendorHealthStatusEnum.DOWN,
                response_time_ms=elapsed_ms,
                known_issues="Trulioo API health check failed",
            )

    # ── Private helpers ──────────────────────────────────────────────────────

    def _build_data_fields(self, entity: EntityVerificationRequest) -> dict[str, Any]:
        """Construct the Trulioo ``DataFields`` payload for the entity's country.

        For Indian entities, includes CIN, GSTIN (if provided), business name,
        and registered address.  For other countries, includes the available
        standard fields.
        """
        fields: dict[str, Any] = {
            "BusinessName": entity.legal_name,
            "BusinessRegistrationNumber": entity.registration_number,
        }

        if entity.registered_address:
            fields["Address"] = entity.registered_address

        if entity.trading_name:
            fields["TradingName"] = entity.trading_name

        if entity.tax_identification_number:
            fields["TaxIDNumber"] = entity.tax_identification_number

        # India-specific: submit CIN and GSTIN as distinct verification fields
        if entity.registration_country == "IN":
            fields["CIN"] = entity.registration_number
            if entity.tax_identification_number:
                fields["GSTIN"] = entity.tax_identification_number

        return fields

    def _validate_response_schema(self, response: dict[str, Any]) -> None:
        """Alert on unexpected schema changes in the Trulioo response.

        Logs a warning (without any raw PII) when expected keys are missing.
        """
        top_missing = _EXPECTED_TOP_KEYS - set(response.keys())
        if top_missing:
            logger.error(
                "trulioo_schema_change_detected",
                level="top",
                missing_keys=sorted(top_missing),
                actual_keys=sorted(response.keys()),
            )

        record = response.get("Record")
        if isinstance(record, dict):
            record_missing = _EXPECTED_RECORD_KEYS - set(record.keys())
            if record_missing:
                logger.error(
                    "trulioo_schema_change_detected",
                    level="record",
                    missing_keys=sorted(record_missing),
                    actual_keys=sorted(record.keys()),
                )

            for ds in record.get("DatasourceResults", []):
                if isinstance(ds, dict):
                    ds_missing = _EXPECTED_DS_KEYS - set(ds.keys())
                    if ds_missing:
                        logger.error(
                            "trulioo_schema_change_detected",
                            level="datasource",
                            datasource_name=ds.get("DatasourceName", "unknown"),
                            missing_keys=sorted(ds_missing),
                        )

    @staticmethod
    def _check_cin_gstin_consistency(
        *,
        cin_legal_name: str | None,
        gstin_legal_name: str | None,
        cin: str,
        gstin: str,
    ) -> bool:
        """Return ``True`` if CIN and GSTIN are consistent.

        Checks two dimensions:

        1. **Registry name match**: if both MCA (CIN) and GST data sources
           returned a verified BusinessName, the names must match (case-
           insensitive, stripped).

        2. **Structural PAN check**: the GSTIN embeds a PAN at positions 2–12.
           If the company PAN derived from CIN records is ever available, this
           is where the structural cross-reference would be added.  For now, the
           name-based check is the primary mechanism.
        """
        if cin_legal_name and gstin_legal_name:
            return cin_legal_name.strip().upper() == gstin_legal_name.strip().upper()

        # If we only have one name (or neither), we cannot confirm a mismatch
        # from the data we have.  Return True (no evidence of mismatch).
        return True
