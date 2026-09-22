from app.modules.gateway.config import (
    VERSION_SEGMENT_PATTERN,
    is_supported_version,
    is_valid_correlation_id,
    supported_api_versions,
)


def test_v1_is_supported():
    assert is_supported_version("v1")


def test_v2_is_not_supported():
    assert not is_supported_version("v2")


def test_supported_api_versions_is_data_not_hardcoded_in_callers():
    assert supported_api_versions() == {"v1"}


def test_version_segment_pattern_matches_version_shaped_segments():
    assert VERSION_SEGMENT_PATTERN.match("v1")
    assert VERSION_SEGMENT_PATTERN.match("v42")


def test_version_segment_pattern_rejects_non_version_segments():
    assert not VERSION_SEGMENT_PATTERN.match("health")
    assert not VERSION_SEGMENT_PATTERN.match("api")
    assert not VERSION_SEGMENT_PATTERN.match("version1")


def test_valid_correlation_id_accepts_uuid_and_custom_trace_ids():
    assert is_valid_correlation_id("550e8400-e29b-41d4-a716-446655440000")
    assert is_valid_correlation_id("test-correlation-id-123")
    assert is_valid_correlation_id("trace.id_with-dots")


def test_valid_correlation_id_rejects_empty():
    assert not is_valid_correlation_id("")


def test_valid_correlation_id_rejects_whitespace_and_control_characters():
    assert not is_valid_correlation_id("has a space")
    assert not is_valid_correlation_id("has\nnewline")


def test_valid_correlation_id_rejects_oversized_values():
    assert not is_valid_correlation_id("a" * 129)
    assert is_valid_correlation_id("a" * 128)
