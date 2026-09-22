"""
What the onboarding workflow writes into Temporal history.

History is durable orchestration state, kept for as long as the execution is
retained. These tests run real executions and decode every payload recorded in
their history — workflow input and result, signal payloads, activity inputs and
results, query results are not part of history and are covered elsewhere — to
check that orchestration data is there and that sensitive data is not: no
free-text compliance reason, and nothing from the onboarding record.
"""
from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from typing import Any

from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingComplianceDecision,
    OnboardingDocumentType,
    OnboardingRejectionCategory,
)
from app.modules.onboarding.tests.fixtures.onboarding_requests import (
    SEEDED_LEGAL_NAME,
    SEEDED_REGISTRATION_NUMBER,
    SEEDED_TAX_IDENTIFICATION_NUMBER,
    read_onboarding_request,
)
from app.modules.onboarding.tests.fixtures.onboarding_workflow import (
    no_documents_required,
    onboarding_workflow,
    wait_until_status,
)
from app.modules.onboarding.tests.fixtures.workflow_dependency_stubs import (
    StubComplianceApprover,
    StubDocumentChecklist,
    stub_dependencies,
)
from app.modules.onboarding.workflows.onboarding_workflow import OnboardingWorkflow

REVIEWER_TEXT = "Reviewer free text: director linked to adverse media, see case notes"

SENSITIVE_RECORD_VALUES = (
    SEEDED_LEGAL_NAME,
    SEEDED_REGISTRATION_NUMBER,
    SEEDED_TAX_IDENTIFICATION_NUMBER,
    "Fixture Street",
    "fixture-initial-user",
)


def _payload_texts(node: Any) -> Iterator[str]:
    """Every payload body in a history's JSON form, decoded."""
    if isinstance(node, dict):
        if "data" in node and "metadata" in node and isinstance(node["data"], str):
            yield base64.b64decode(node["data"]).decode("utf-8", "replace")
        for value in node.values():
            yield from _payload_texts(value)
    elif isinstance(node, list):
        for item in node:
            yield from _payload_texts(item)


async def _history_payloads(handle) -> str:
    history = await handle.fetch_history()
    decoded = list(_payload_texts(json.loads(history.to_json())))
    assert decoded, "no payloads found in history"
    return "\n".join(decoded)


def _assert_no_sensitive_values(payloads: str) -> None:
    assert REVIEWER_TEXT not in payloads
    for value in SENSITIVE_RECORD_VALUES:
        assert value not in payloads, value


async def test_immediate_compliance_rejection_keeps_the_reason_out_of_history():
    """The compliance dependency returns its reason with the decision; only the
    decision and the approval request id may reach history."""
    approver = StubComplianceApprover(
        decision=OnboardingComplianceDecision.REJECTED, reason=REVIEWER_TEXT
    )
    deps = stub_dependencies(document_checklist=no_documents_required(), compliance_approver=approver)

    async with onboarding_workflow(deps) as (_, handle, request_id):
        result = await handle.result()
        payloads = await _history_payloads(handle)

    assert (result.final_status, result.rejection_category) == ("REJECTED", "COMPLIANCE_REJECTION")
    # Orchestration data is recorded...
    assert f"stub-approval:{request_id}" in payloads
    assert '"decision": "REJECTED"' in payloads or '"decision":"REJECTED"' in payloads
    assert "COMPLIANCE_REJECTION" in payloads
    # ...the reason and the onboarding record are not.
    _assert_no_sensitive_values(payloads)

    request = await read_onboarding_request(request_id)
    assert request.rejection_category == OnboardingRejectionCategory.COMPLIANCE_REJECTION


async def test_signalled_compliance_rejection_keeps_the_reason_out_of_history():
    checklist = StubDocumentChecklist(required=(OnboardingDocumentType.LICENCE,))
    approver = StubComplianceApprover(decision=None)
    deps = stub_dependencies(document_checklist=checklist, compliance_approver=approver)

    async with onboarding_workflow(deps) as (_, handle, request_id):
        rid = str(request_id)
        await wait_until_status(handle, "waiting on customer", lambda s: s["waiting_on"] == "customer")
        licence = checklist.submission(rid, OnboardingDocumentType.LICENCE)
        checklist.record(licence)
        await handle.signal(OnboardingWorkflow.document_submitted, licence)

        await wait_until_status(handle, "waiting on compliance", lambda s: s["waiting_on"] == "compliance")
        await handle.signal(
            OnboardingWorkflow.compliance_decision_received,
            approver.decision_for(rid, OnboardingComplianceDecision.REJECTED),
        )
        result = await handle.result()
        payloads = await _history_payloads(handle)

    assert (result.final_status, result.rejection_category) == ("REJECTED", "COMPLIANCE_REJECTION")
    assert f"stub-approval:{rid}" in payloads
    assert licence.document_id in payloads
    assert "COMPLIANCE_REJECTION" in payloads
    _assert_no_sensitive_values(payloads)


async def test_decision_signal_with_unexpected_text_does_not_retain_it_in_workflow_state():
    """A sender that still attaches a reason has put it in the signal it sent — that
    is the sender's doing and outside the workflow's control. The workflow must not
    carry it any further: not into its state, its activities or its queries."""
    approver = StubComplianceApprover(decision=None)
    deps = stub_dependencies(document_checklist=no_documents_required(), compliance_approver=approver)

    async with onboarding_workflow(deps) as (_, handle, request_id):
        rid = str(request_id)
        await wait_until_status(handle, "waiting on compliance", lambda s: s["waiting_on"] == "compliance")
        await handle.signal(
            "compliance_decision_received",
            {
                "onboarding_request_id": rid,
                "approval_request_id": approver.approval_request_id_for(rid),
                "decision": "REJECTED",
                "reason": REVIEWER_TEXT,
            },
        )
        result = await handle.result()
        detail = await handle.query("onboarding_detail")
        status = await handle.query("current_status")
        history = await handle.fetch_history()

    assert (result.final_status, result.rejection_category) == ("REJECTED", "COMPLIANCE_REJECTION")
    assert REVIEWER_TEXT not in json.dumps(detail) + json.dumps(status)

    # Only the signal as sent contains it; nothing the workflow produced does.
    carried_on = []
    for event in history.events:
        if event.HasField("workflow_execution_signaled_event_attributes"):
            continue
        text = "\n".join(_payload_texts(json.loads(_event_json(event))))
        if REVIEWER_TEXT in text:
            carried_on.append(event.event_type)
    assert carried_on == []
    assert (await read_onboarding_request(request_id)).rejection_reason is None


def _event_json(event) -> str:
    from google.protobuf.json_format import MessageToJson

    return MessageToJson(event)


async def test_approved_compliance_still_reaches_account_creation_and_active():
    approver = StubComplianceApprover(decision=OnboardingComplianceDecision.APPROVED)
    deps = stub_dependencies(document_checklist=no_documents_required(), compliance_approver=approver)

    async with onboarding_workflow(deps) as (_, handle, request_id):
        result = await handle.result()
        payloads = await _history_payloads(handle)

    assert result.final_status == "ACTIVE"
    assert deps.account_creator.calls == [("create_accounts", str(request_id))]
    _assert_no_sensitive_values(payloads)
