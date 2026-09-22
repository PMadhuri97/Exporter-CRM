"""ANER-4.3-S3T2: pins `PERMITTED_TRANSITIONS` to the exact 10-edge subset of
the Jira doc's "Permitted transitions" table this build implements — see
`case_lifecycle_service.py`'s module docstring for which 5 rows of the doc's
full 15-row table were deliberately left out and why. Pure/unit: checking a
plain data structure, not exercising the database.
"""
from __future__ import annotations

from app.modules.cases.application.case_lifecycle_service import PERMITTED_TRANSITIONS
from app.modules.cases.domain.entities.enums import CaseStatus

EXPECTED = frozenset(
    {
        (CaseStatus.OPEN, CaseStatus.ASSIGNED),
        (CaseStatus.ASSIGNED, CaseStatus.UNDER_INVESTIGATION),
        (CaseStatus.UNDER_INVESTIGATION, CaseStatus.PENDING_EXTERNAL),
        (CaseStatus.PENDING_EXTERNAL, CaseStatus.UNDER_INVESTIGATION),
        (CaseStatus.UNDER_INVESTIGATION, CaseStatus.PENDING_APPROVAL),
        (CaseStatus.PENDING_APPROVAL, CaseStatus.RESOLVED),
        (CaseStatus.PENDING_APPROVAL, CaseStatus.UNDER_INVESTIGATION),
        (CaseStatus.UNDER_INVESTIGATION, CaseStatus.CLOSED_WITHOUT_ACTION),
        (CaseStatus.UNDER_INVESTIGATION, CaseStatus.ESCALATED),
        (CaseStatus.ESCALATED, CaseStatus.UNDER_INVESTIGATION),
    }
)


def test_permitted_transitions_matches_the_expected_ten_edges():
    assert PERMITTED_TRANSITIONS == EXPECTED


def test_no_outbound_edge_exists_from_either_terminal_status():
    froms = {edge[0] for edge in PERMITTED_TRANSITIONS}
    assert CaseStatus.RESOLVED not in froms
    assert CaseStatus.CLOSED_WITHOUT_ACTION not in froms


def test_out_of_scope_edges_from_the_docs_full_table_are_absent():
    """These 5 rows exist in the Jira doc's table but belong to other,
    not-yet-built stories — see the module docstring."""
    out_of_scope = {
        (CaseStatus.UNDER_INVESTIGATION, CaseStatus.RESOLVED),  # S4T1/T3/T4 direct resolve
        (CaseStatus.ESCALATED, CaseStatus.RESOLVED),  # S4T1/T3/T4 direct resolve
        (CaseStatus.OPEN, CaseStatus.ESCALATED),  # S5T2 SLA auto-escalation
        (CaseStatus.ASSIGNED, CaseStatus.ESCALATED),  # S5T2 SLA auto-escalation
    }
    assert out_of_scope.isdisjoint(PERMITTED_TRANSITIONS)
