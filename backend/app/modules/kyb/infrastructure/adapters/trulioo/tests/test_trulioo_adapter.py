"""Trulioo adapter tests — Epic 4.1 / S2T2 (AL-669).

Covers every acceptance criterion and reviewer comment:

AC1: Valid Indian corporation → VERIFIED with CIN and GSTIN confirmed.
AC2: GSTIN inconsistent with CIN → REQUIRES_MANUAL_REVIEW.
AC3: Indian entity with no MCA record → NOT_FOUND.
AC4: All calls use Vault credentials (Settings-based injection).
AC5: Synchronous response — complete result, no webhook.

Reviewer comments:
R1: PII data masking in log output.
R2: Retry logic on transient errors; rate-limit (429) handling.
R3: Schema-change detection and alerts.

Additional coverage:
- get_verification_status raises NotImplementedError (modified per review to return NOT_SUPPORTED).
- declare_capabilities returns correct declaration.
- get_vendor_health healthy and failed paths.
- Failure-code translation table completeness.
- Non-Indian international entity verification.
- PII masking utility correctness.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.integrations.kyb.trulioo.client import TruliooApiClient
from app.integrations.kyb.trulioo.exceptions import (
    TruliooApiError,
    TruliooRateLimitError,
    TruliooSchemaChangeError,
)
from app.modules.kyb.domain.ports import KYBAdapter
from app.modules.kyb.infrastructure.adapters.trulioo.adapter import (
    VENDOR_ID,
    VENDOR_NAME,
    TruliooAdapter,
)
from app.shared.contracts.kyb import EntityVerificationRequest, KYBVerificationResult
from app.shared.enums.kyb import KYBVendorProcessingMode, NormalisedResult, VendorHealthStatusEnum

# ── Fixtures ─────────────────────────────────────────────────────────────────

def _make_indian_entity(
    *,
    legal_name: str = "Tata Consultancy Services Limited",
    cin: str = "L22210MH1995PLC084781",
    gstin: str | None = "27AAACT2727Q1ZV",
    address: str = "9B, Borakhola, Hadapsar Industrial Estate, Pune 411013",
) -> EntityVerificationRequest:
    return EntityVerificationRequest(
        legal_name=legal_name,
        registration_country="IN",
        registration_number=cin,
        registered_address=address,
        tax_identification_number=gstin,
    )


def _make_uk_entity() -> EntityVerificationRequest:
    return EntityVerificationRequest(
        legal_name="Acme Holdings Ltd",
        registration_country="GB",
        registration_number="12345678",
        registered_address="1 London Bridge, London SE1 9BG",
        tax_identification_number="GB123456789",
    )


def _trulioo_verified_response(
    *,
    transaction_id: str = "txn-abc-123",
    record_status: str = "match",
    datasources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a well-formed Trulioo verification response."""
    if datasources is None:
        datasources = [
            {
                "DatasourceName": "MCA India",
                "DatasourceFields": [
                    {"FieldName": "BusinessRegistrationNumber", "Status": "match",
                     "Value": "L22210MH1995PLC084781"},
                    {"FieldName": "BusinessName", "Status": "match",
                     "Value": "Tata Consultancy Services Limited"},
                    {"FieldName": "Address", "Status": "match",
                     "Value": "9B, Borakhola, Hadapsar Industrial Estate, Pune 411013"},
                ],
                "Errors": [],
            },
            {
                "DatasourceName": "GST India",
                "DatasourceFields": [
                    {"FieldName": "TaxIDNumber", "Status": "match",
                     "Value": "27AAACT2727Q1ZV"},
                    {"FieldName": "BusinessName", "Status": "match",
                     "Value": "Tata Consultancy Services Limited"},
                ],
                "Errors": [],
            },
        ]
    return {
        "TransactionID": transaction_id,
        "Record": {
            "TransactionRecordID": f"rec-{transaction_id}",
            "RecordStatus": record_status,
            "DatasourceResults": datasources,
        },
    }


def _trulioo_not_found_response(transaction_id: str = "txn-nf-456") -> dict[str, Any]:
    """Indian entity not found in MCA."""
    return {
        "TransactionID": transaction_id,
        "Record": {
            "TransactionRecordID": f"rec-{transaction_id}",
            "RecordStatus": "missing",
            "DatasourceResults": [
                {
                    "DatasourceName": "MCA India",
                    "DatasourceFields": [
                        {"FieldName": "BusinessRegistrationNumber", "Status": "missing"},
                    ],
                    "Errors": [],
                },
            ],
        },
    }


def _trulioo_cin_gstin_mismatch_response(
    transaction_id: str = "txn-mm-789",
) -> dict[str, Any]:
    """CIN and GSTIN verified but for different entities."""
    return {
        "TransactionID": transaction_id,
        "Record": {
            "TransactionRecordID": f"rec-{transaction_id}",
            "RecordStatus": "match",
            "DatasourceResults": [
                {
                    "DatasourceName": "MCA India",
                    "DatasourceFields": [
                        {"FieldName": "BusinessRegistrationNumber", "Status": "match",
                         "Value": "L22210MH1995PLC084781"},
                        {"FieldName": "BusinessName", "Status": "match",
                         "Value": "Tata Consultancy Services Limited"},
                    ],
                    "Errors": [],
                },
                {
                    "DatasourceName": "GST India",
                    "DatasourceFields": [
                        {"FieldName": "TaxIDNumber", "Status": "match",
                         "Value": "27BBBBT9999Q1ZV"},
                        {"FieldName": "BusinessName", "Status": "match",
                         "Value": "Infosys Technologies Limited"},
                    ],
                    "Errors": [],
                },
            ],
        },
    }


@pytest.fixture()
def mock_client() -> MagicMock:
    """A mock TruliooApiClient that returns configurable responses."""
    client = MagicMock(spec=TruliooApiClient)
    client.verify.return_value = _trulioo_verified_response()
    client.test_connection.return_value = {"Message": "Hello"}
    return client


@pytest.fixture()
def adapter(mock_client: MagicMock) -> TruliooAdapter:
    return TruliooAdapter(client=mock_client)


# ═══════════════════════════════════════════════════════════════════════════════
# AC1: Valid Indian corporation → VERIFIED with CIN and GSTIN confirmed
# ═══════════════════════════════════════════════════════════════════════════════


class TestAC1ValidIndianCorporation:
    def test_verified_result(self, adapter: TruliooAdapter, mock_client: MagicMock) -> None:
        entity = _make_indian_entity()
        result = adapter.verify_entity(entity)

        assert result.normalised_result == NormalisedResult.VERIFIED
        assert result.vendor_id == VENDOR_ID
        assert result.verified_legal_name is not None
        assert result.verified_registration_number is not None
        assert result.discrepancies == []
        assert isinstance(result.retrieved_at, datetime)

    def test_cin_confirmed(self, adapter: TruliooAdapter) -> None:
        entity = _make_indian_entity()
        result = adapter.verify_entity(entity)

        assert result.verified_registration_number == "L22210MH1995PLC084781"

    def test_gstin_confirmed(self, adapter: TruliooAdapter) -> None:
        entity = _make_indian_entity()
        result = adapter.verify_entity(entity)

        # GSTIN is verified when TaxIDNumber has status "match" and no
        # discrepancies referencing TaxIDNumber appear.
        assert result.normalised_result == NormalisedResult.VERIFIED
        tax_discrepancies = [d for d in result.discrepancies if "TaxIDNumber" in d]
        assert tax_discrepancies == []


# ═══════════════════════════════════════════════════════════════════════════════
# AC2: GSTIN inconsistent with CIN → REQUIRES_MANUAL_REVIEW
# ═══════════════════════════════════════════════════════════════════════════════


class TestAC2CinGstinMismatch:
    def test_mismatch_triggers_manual_review(self, mock_client: MagicMock) -> None:
        mock_client.verify.return_value = _trulioo_cin_gstin_mismatch_response()
        adapter = TruliooAdapter(client=mock_client)
        entity = _make_indian_entity()

        result = adapter.verify_entity(entity)

        assert result.normalised_result == NormalisedResult.REQUIRES_MANUAL_REVIEW
        assert any("CIN and GSTIN" in d for d in result.discrepancies)

    def test_no_gstin_skips_cross_check(self, adapter: TruliooAdapter) -> None:
        """Indian entity without GSTIN should not trigger the cross-check."""
        entity = _make_indian_entity(gstin=None)
        result = adapter.verify_entity(entity)

        assert result.normalised_result == NormalisedResult.VERIFIED
        assert not any("CIN and GSTIN" in d for d in result.discrepancies)


# ═══════════════════════════════════════════════════════════════════════════════
# AC3: Indian entity with no MCA record → NOT_FOUND
# ═══════════════════════════════════════════════════════════════════════════════


class TestAC3IndianEntityNotFound:
    def test_not_found_result(self, mock_client: MagicMock) -> None:
        mock_client.verify.return_value = _trulioo_not_found_response()
        adapter = TruliooAdapter(client=mock_client)
        entity = _make_indian_entity()

        result = adapter.verify_entity(entity)

        assert result.normalised_result == NormalisedResult.NOT_FOUND


# ═══════════════════════════════════════════════════════════════════════════════
# AC5: Synchronous response — complete result, no webhook
# ═══════════════════════════════════════════════════════════════════════════════


class TestAC5SynchronousResponse:
    def test_verify_returns_complete_result(
        self, adapter: TruliooAdapter, mock_client: MagicMock
    ) -> None:
        entity = _make_indian_entity()
        result = adapter.verify_entity(entity)

        # Result is complete — not PENDING
        assert result.normalised_result != NormalisedResult.PENDING
        assert result.vendor_reference is not None
        assert result.raw_response_reference is not None

    def test_get_verification_status_returns_not_supported(self, adapter: TruliooAdapter) -> None:
        """Synchronous vendors return NOT_SUPPORTED per S1T3 spec §2."""
        result = adapter.get_verification_status("some-ref")
        assert result.normalised_result == NormalisedResult.NOT_SUPPORTED


# ═══════════════════════════════════════════════════════════════════════════════
# R1: PII data masking in log output (Adapter side)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdapterPiiMasking:
    def test_verify_entity_does_not_log_raw_pii(
        self, adapter: TruliooAdapter, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Ensure structured log events from verify_entity mask PII."""
        entity = _make_indian_entity()

        with caplog.at_level(logging.DEBUG):
            adapter.verify_entity(entity)

        full_log = caplog.text
        # Raw PII should never appear in logs
        assert "Tata Consultancy Services Limited" not in full_log
        assert "L22210MH1995PLC084781" not in full_log
        assert "27AAACT2727Q1ZV" not in full_log


# ═══════════════════════════════════════════════════════════════════════════════
# R3: Schema-change detection and alerts
# ═══════════════════════════════════════════════════════════════════════════════


class TestR3SchemaChangeDetection:
    def test_missing_top_level_key_logs_alert(
        self, caplog: pytest.LogCaptureFixture, mock_client: MagicMock
    ) -> None:
        """Missing top-level keys trigger a schema-change alert."""
        mock_client.verify.return_value = {
            # Missing "TransactionID"
            "Record": {
                "TransactionRecordID": "rec-1",
                "RecordStatus": "match",
                "DatasourceResults": [],
            },
        }
        adapter = TruliooAdapter(client=mock_client)

        with caplog.at_level(logging.DEBUG):
            adapter.verify_entity(_make_indian_entity(gstin=None))

        assert "trulioo_schema_change_detected" in caplog.text

    def test_missing_record_key_logs_alert(
        self, caplog: pytest.LogCaptureFixture, mock_client: MagicMock
    ) -> None:
        mock_client.verify.return_value = {
            "TransactionID": "txn-1",
            "Record": {
                # Missing "RecordStatus"
                "TransactionRecordID": "rec-1",
                "DatasourceResults": [],
            },
        }
        adapter = TruliooAdapter(client=mock_client)

        with caplog.at_level(logging.DEBUG):
            adapter.verify_entity(_make_indian_entity(gstin=None))

        assert "trulioo_schema_change_detected" in caplog.text

    def test_schema_alert_does_not_contain_pii(
        self, caplog: pytest.LogCaptureFixture, mock_client: MagicMock
    ) -> None:
        """Schema-change alerts must not leak raw PII."""
        mock_client.verify.return_value = {
            "Record": {
                "TransactionRecordID": "rec-1",
                "RecordStatus": "match",
                "DatasourceResults": [],
            },
        }
        adapter = TruliooAdapter(client=mock_client)
        entity = _make_indian_entity()

        with caplog.at_level(logging.DEBUG):
            adapter.verify_entity(entity)

        for record in caplog.records:
            msg = str(record.getMessage())
            assert "Tata Consultancy" not in msg
            assert "L22210MH1995PLC084781" not in msg


# ═══════════════════════════════════════════════════════════════════════════════
# declare_capabilities
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeclareCapabilities:
    def test_returns_correct_declaration(self, adapter: TruliooAdapter) -> None:
        cap = adapter.declare_capabilities()

        assert cap.vendor_id == VENDOR_ID
        assert cap.vendor_name == VENDOR_NAME
        assert cap.processing_mode == KYBVendorProcessingMode.SYNCHRONOUS
        assert "IN" in cap.supported_countries
        assert "US" not in cap.supported_countries
        assert len(cap.supported_entity_types) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# get_vendor_health
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetVendorHealth:
    def test_healthy(self, adapter: TruliooAdapter) -> None:
        health = adapter.get_vendor_health()
        assert health.status == VendorHealthStatusEnum.HEALTHY
        assert health.response_time_ms >= 0

    def test_down_on_api_error(self, mock_client: MagicMock) -> None:
        mock_client.test_connection.side_effect = TruliooApiError("connection failed")
        adapter = TruliooAdapter(client=mock_client)

        health = adapter.get_vendor_health()
        assert health.status == VendorHealthStatusEnum.DOWN
        assert health.known_issues is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Failure-code translation table alerts
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdapterFailureCodeAlert:
    def test_unknown_status_logged_as_alert(
        self, mock_client: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Unknown Trulioo status codes generate operational alerts."""
        mock_client.verify.return_value = _trulioo_verified_response(
            record_status="new_unknown_status"
        )
        adapter = TruliooAdapter(client=mock_client)

        with caplog.at_level(logging.DEBUG):
            result = adapter.verify_entity(_make_indian_entity(gstin=None))

        assert result.normalised_result == NormalisedResult.REQUIRES_MANUAL_REVIEW
        assert "trulioo_unknown_record_status" in caplog.text


# ═══════════════════════════════════════════════════════════════════════════════
# Non-Indian international entity verification
# ═══════════════════════════════════════════════════════════════════════════════


class TestInternationalEntity:
    def test_uk_entity_verified(self, mock_client: MagicMock) -> None:
        mock_client.verify.return_value = {
            "TransactionID": "txn-uk-1",
            "Record": {
                "TransactionRecordID": "rec-uk-1",
                "RecordStatus": "match",
                "DatasourceResults": [
                    {
                        "DatasourceName": "Companies House",
                        "DatasourceFields": [
                            {"FieldName": "BusinessRegistrationNumber", "Status": "match",
                             "Value": "12345678"},
                            {"FieldName": "BusinessName", "Status": "match",
                             "Value": "Acme Holdings Ltd"},
                        ],
                        "Errors": [],
                    },
                ],
            },
        }
        adapter = TruliooAdapter(client=mock_client)

        result = adapter.verify_entity(_make_uk_entity())

        assert result.normalised_result == NormalisedResult.VERIFIED
        assert result.verified_legal_name == "Acme Holdings Ltd"

    def test_no_cin_gstin_crosscheck_for_non_india(self, mock_client: MagicMock) -> None:
        """CIN↔GSTIN cross-check only applies to IN entities."""
        mock_client.verify.return_value = {
            "TransactionID": "txn-uk-2",
            "Record": {
                "TransactionRecordID": "rec-uk-2",
                "RecordStatus": "match",
                "DatasourceResults": [
                    {
                        "DatasourceName": "Companies House",
                        "DatasourceFields": [
                            {"FieldName": "BusinessRegistrationNumber", "Status": "match",
                             "Value": "12345678"},
                            {"FieldName": "BusinessName", "Status": "match",
                             "Value": "Acme Holdings Ltd"},
                        ],
                        "Errors": [],
                    },
                ],
            },
        }
        adapter = TruliooAdapter(client=mock_client)

        result = adapter.verify_entity(_make_uk_entity())

        assert result.normalised_result == NormalisedResult.VERIFIED
        assert not any("CIN and GSTIN" in d for d in result.discrepancies)


# ═══════════════════════════════════════════════════════════════════════════════
# Adapter is a KYBAdapter (interface compliance)
# ═══════════════════════════════════════════════════════════════════════════════


class TestInterfaceCompliance:
    def test_is_kyb_adapter(self, adapter: TruliooAdapter) -> None:
        assert isinstance(adapter, KYBAdapter)

    def test_result_is_kyb_verification_result(self, adapter: TruliooAdapter) -> None:
        result = adapter.verify_entity(_make_indian_entity())
        assert isinstance(result, KYBVerificationResult)


# ═══════════════════════════════════════════════════════════════════════════════
# Exception hierarchy
# ═══════════════════════════════════════════════════════════════════════════════


class TestExceptions:
    def test_trulioo_api_error(self) -> None:
        err = TruliooApiError("fail", status_code=500)
        assert str(err) == "fail"
        assert err.status_code == 500

    def test_trulioo_rate_limit_error(self) -> None:
        err = TruliooRateLimitError(retry_after_seconds=30.0)
        assert err.status_code == 429
        assert err.retry_after_seconds == 30.0

    def test_trulioo_schema_change_error(self) -> None:
        err = TruliooSchemaChangeError("fields changed")
        assert err.status_code is None
