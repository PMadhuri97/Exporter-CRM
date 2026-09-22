"""
Workflow signal payloads.

`ApprovalSignalPayload` is the wire format the compliance module sends to the
settlement workflow when a maker or checker records a decision. Neither module owns
it: compliance constructs it, orchestration's workflow receives it. Leaving it in
`modules/orchestration/` forced compliance to import orchestration while orchestration
already imported compliance — a circular dependency between two business modules
(VERIFICATION_REPORT.md, HIGH-1).

It is the contract *between* them, so it lives in neither. Pure by construction: three
strings, no behaviour, no dependencies, JSON-serializable — as every Temporal payload
must be.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ApprovalSignalPayload:
    decision: str          # "APPROVED" or "REJECTED"
    approver_id: str
    notes: str = ""
