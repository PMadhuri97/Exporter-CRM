from app.integrations.kyb.trulioo.failure_codes import (
    is_known_field_status,
    is_known_record_status,
    translate_field_status,
    translate_record_status,
)
from app.shared.enums.kyb import NormalisedResult


class TestFailureCodeTranslation:
    def test_all_record_statuses_mapped(self) -> None:
        assert translate_record_status("match") == NormalisedResult.VERIFIED
        assert translate_record_status("nomatch") == NormalisedResult.REJECTED
        assert translate_record_status("missing") == NormalisedResult.NOT_FOUND
        assert translate_record_status("datasourceerror") == NormalisedResult.REQUIRES_MANUAL_REVIEW

    def test_unknown_record_status_falls_back(self) -> None:
        result = translate_record_status("some_new_trulioo_code")
        assert result == NormalisedResult.REQUIRES_MANUAL_REVIEW

    def test_field_status_mapping(self) -> None:
        assert translate_field_status("match") == NormalisedResult.VERIFIED
        assert translate_field_status("nomatch") == NormalisedResult.REJECTED

    def test_case_insensitive(self) -> None:
        assert translate_record_status("MATCH") == NormalisedResult.VERIFIED
        assert translate_record_status("  Match  ") == NormalisedResult.VERIFIED

    def test_is_known_helpers(self) -> None:
        assert is_known_record_status("match") is True
        assert is_known_record_status("unknown_xyz") is False
        assert is_known_field_status("nomatch") is True
        assert is_known_field_status("banana") is False
