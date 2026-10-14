"""What counts as a reason for changing a live settings rule (``domain/change_reason.py``)."""

from __future__ import annotations

import pytest

from app.modules.onboarding.domain.change_reason import (
    MAX_LENGTH,
    change_reason_problem,
    clean_change_reason,
    require_change_reason,
)
from app.shared.exceptions import ValidationError


@pytest.mark.parametrize(
    "reason",
    [
        pytest.param("CHG-1042", id="jira-style-ticket"),
        pytest.param("chg-7", id="ticket-any-case"),
        pytest.param("CHG0031234", id="servicenow-style-ticket"),
        pytest.param("Per INC0012345", id="ticket-inside-text"),
        pytest.param("Raise turnover floor per credit committee", id="explanation"),
        pytest.param("  Lower   the   threshold for SMEs  ", id="explanation-with-spaces"),
    ],
)
def test_a_ticket_or_a_real_explanation_is_accepted(reason: str):
    assert change_reason_problem(reason) is None


@pytest.mark.parametrize(
    "reason",
    [
        pytest.param(None, id="none"),
        pytest.param("", id="empty"),
        pytest.param("     ", id="spaces"),
        pytest.param("test", id="one-word"),
        pytest.param("update rule", id="two-words"),
        pytest.param("a b c", id="three-words-too-short"),
        pytest.param("CHG", id="ticket-prefix-alone"),
        pytest.param("CHG 1042", id="ticket-split-by-a-space"),
        pytest.param("x" * (MAX_LENGTH + 1), id="too-long"),
    ],
)
def test_a_missing_or_vague_reason_is_refused(reason: str | None):
    assert change_reason_problem(reason) is not None


def test_the_stored_reason_is_trimmed_and_its_spaces_collapsed():
    assert clean_change_reason("  CHG-1042:\n  raise   the floor ") == "CHG-1042: raise the floor"
    assert require_change_reason("  CHG-1042  ") == "CHG-1042"


def test_requiring_a_reason_refuses_with_a_422():
    with pytest.raises(ValidationError) as caught:
        require_change_reason("test")
    assert caught.value.status_code == 422
    assert "ticket number" in caught.value.detail
