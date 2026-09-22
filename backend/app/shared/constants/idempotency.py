"""Identifiers shared by the idempotency violation writer and its readers.

The violation detector writes to ``audit.audit_events`` from ``app.platform``; the
audit query interface reads them back through an adapter in ``app.modules.audit``.
Neither may import the other's internals, and an agreement held in two string
literals is one that breaks silently — a reader filtering on a string the writer
stopped using returns an empty page, not an error. The string therefore lives here,
where both sides can import it.
"""

#: ``audit_events.event_type`` for an idempotency violation: a key that failed to
#: deduplicate and let an operation execute more than once. Not written for a
#: duplicate that was detected and short-circuited — that is the control working,
#: and it is recorded in ``ledger.duplicate_detection`` instead.
IDEMPOTENCY_VIOLATION_EVENT_TYPE = "idempotency.violation_detected"
