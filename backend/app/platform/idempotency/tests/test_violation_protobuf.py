"""Unit tests for ViolationReport Protobuf schema (S4T2)."""


from app.platform.idempotency.proto import ViolationReport


def test_protobuf_violation_report_schema_fields():
    """Verify all 6 required fields exist and are typed accurately."""
    report = ViolationReport(
        key_value="idem-key-12345",
        scope="cust-scope-67890",
        operation_type="ledger_posting",
        execution_count=2,
        involved_object_ids=["tx-id-1", "tx-id-2"],
        correlation_id="corr-abc-xyz",
    )

    assert report.key_value == "idem-key-12345"
    assert report.scope == "cust-scope-67890"
    assert report.operation_type == "ledger_posting"
    assert report.execution_count == 2
    assert report.involved_object_ids == ["tx-id-1", "tx-id-2"]
    assert report.correlation_id == "corr-abc-xyz"


def test_protobuf_serialization_and_deserialization():
    """Verify strict binary serialization and deserialization roundtrip."""
    original = ViolationReport(
        key_value="settle-key-999",
        scope="cust-account-888",
        operation_type="settlement_creation",
        execution_count=3,
        involved_object_ids=["settlement-1", "settlement-2", "settlement-3"],
        correlation_id="trace-correlation-777",
    )

    data_bytes = original.SerializeToString()
    assert isinstance(data_bytes, bytes)
    assert len(data_bytes) > 0

    reconstructed = ViolationReport().ParseFromString(data_bytes)
    assert reconstructed.key_value == original.key_value
    assert reconstructed.scope == original.scope
    assert reconstructed.operation_type == original.operation_type
    assert reconstructed.execution_count == original.execution_count
    assert reconstructed.involved_object_ids == original.involved_object_ids
    assert reconstructed.correlation_id == original.correlation_id


def test_protobuf_dictionary_conversion():
    """Verify conversion to and from dict format for structured logging."""
    report = ViolationReport(
        key_value="rail-ref-001",
        scope="nium_usd_inr",
        operation_type="rail_submission",
        execution_count=2,
        involved_object_ids=["update-rec-1", "update-rec-2"],
        correlation_id="corr-rail-001",
    )

    data_dict = report.to_dict()
    assert data_dict["key_value"] == "rail-ref-001"
    assert data_dict["execution_count"] == 2

    from_dict_report = ViolationReport.from_dict(data_dict)
    assert from_dict_report.key_value == report.key_value
    assert from_dict_report.involved_object_ids == report.involved_object_ids
