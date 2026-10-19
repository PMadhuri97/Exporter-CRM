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
        pytest.param("CHG-1042: raise the turnover floor", id="jira-style-ticket"),
        pytest.param("CHG0031234 — lower the threshold for SMEs", id="servicenow-style-ticket"),
        pytest.param("JIRA-381 - retire DA 120 days", id="dash-separator"),
        pytest.param("INC0012345 replaced by ADVANCE_50", id="space-separator"),
        pytest.param("  CHG-7:   lower   the   threshold  ", id="extra-spaces"),
    ],
)
def test_a_ticket_and_a_real_explanation_are_accepted(reason: str):
    assert change_reason_problem(reason) is None


@pytest.mark.parametrize(
    "reason",
    [
        pytest.param(None, id="none"),
        pytest.param("", id="empty"),
        pytest.param("     ", id="spaces"),
        pytest.param("CHG-1042", id="ticket-alone"),
        pytest.param("chg-7: retire the old term", id="ticket-in-lower-case"),
        pytest.param("Per INC0012345 retire the term", id="ticket-not-first"),
        pytest.param("Raise turnover floor per credit committee", id="explanation-alone"),
        pytest.param("CHG 1042: raise the floor", id="ticket-split-by-a-space"),
        pytest.param("CHG1042: raise the floor", id="too-few-digits-without-a-dash"),
        pytest.param("CHG-٤٢: raise the floor", id="non-ascii-digits"),
        pytest.param("CHG-7: update", id="one-word"),
        pytest.param("CHG-7: a b c d e f", id="no-real-words"),
        pytest.param("CHG-7: ✓✓✓ ✓✓✓ ✓✓✓", id="symbols"),
        pytest.param("CHG-7: éé çç", id="too-short"),
        pytest.param("CHG-1: " + "x" * MAX_LENGTH, id="too-long"),
    ],
)
def test_a_missing_or_vague_reason_is_refused(reason: str | None):
    assert change_reason_problem(reason) is not None


def test_the_stored_reason_is_trimmed_and_its_spaces_collapsed():
    assert clean_change_reason("  CHG-1042:\n  raise   the floor ") == "CHG-1042: raise the floor"
    assert require_change_reason("  CHG-1042:  raise the floor ") == "CHG-1042: raise the floor"


def test_requiring_a_reason_refuses_with_a_422():
    with pytest.raises(ValidationError) as caught:
        require_change_reason("test")
    assert caught.value.status_code == 422
    assert "ticket number" in caught.value.detail
