# customers

Business domain. Public facade is `__init__.py` — the only import surface for other modules (ARCHITECTURE.md §6).

Owns the `customers` PostgreSQL schema: the counterparty registry, its payout
destinations, and the ongoing due diligence programme that keeps the registry
honest after onboarding.

## Boundary with `onboarding`

`onboarding` owns the first time — the onboarding journey, initial KYB and UBO
verification, initial screening, initial risk rating, and the decision to accept
or reject. This module owns every time after: when to look again, the events
that force an unscheduled look, and the consequences of what is found.

A platform that verifies at onboarding and never again is compliant on day one
and progressively less so every day after. That gap is what these tables close.

Re-verification is not a second KYB integration. It invokes the existing
verification services and compares the result against a recorded baseline; the
comparison is the output, not the facts.

## Tables

### Review lifecycle (`customers_0002_review_lifecycle`)

| Table | Holds |
|---|---|
| `review_schedule` | when each customer is next due, one live schedule per customer |
| `review_trigger_definition` | configured events that cause an unscheduled review |
| `customer_review` | one review, scheduled or triggered |
| `customer_baseline_snapshot` | immutable point-in-time record of a verified state |
| `detected_change` | one difference between baseline and current |

### Status and entitlements (`customers_0003_entitlements`)

| Table | Holds |
|---|---|
| `customer_status_history` | every change to a customer's standing, in order |
| `customer_entitlement` | what a customer is permitted to do |
| `re_attestation_request` | where a customer must confirm or update what they declared |

## Invariants enforced below the application

**A review with no baseline is not a review.** `customer_review.baseline_snapshot_ref`
is a foreign key, not merely `NOT NULL` — a ref pointing at no snapshot is worth
no more than a null one. Reviews compare against a snapshot rather than the live
customer record, because the live record moves for reasons that are not findings
and comparing against it would report an operator's typo correction as a change.

**Consequential decisions carry dual authorisation.** Suspension, restriction,
referral to offboarding, and reinstatement each require a non-null
`approval_request_id`, checked by the database rather than only by the service
that writes the row.

**Completion is a compliance record.** A completed review needs an outcome and a
rationale of at least 50 characters after trimming. A one-word rationale, and
fifty spaces, are both rejected.

**Evidence is append-only.** `customer_baseline_snapshot`, `detected_change` and
`customer_status_history` reject UPDATE and DELETE outright. Current status is
the latest row, not a column an operator can overwrite.

**The review risk ladder is its own type.** `review_risk_rating_enum` ends in
`PROHIBITED`; the onboarding-era `risk_rating_enum` in the same schema ends in
`ENHANCED`. Sharing one type would let either context store a band it cannot act
on.

## Known gaps

**Assessment and notification writes.** The append-only guarantee means
`detected_change.accepted` / `assessor_note` / `customer_response`, and
`customer_status_history.effective_until` / `customer_notified_at` /
`notification_ref`, are written when the row is inserted rather than edited in
afterwards. The supersede-on-assess write path is `AL-737`.

**PII at rest.** `customer_baseline_snapshot.directors` and
`beneficial_owners` hold personal data. No field-level encryption layer or KMS
provider exists in the platform yet, so the columns are unencrypted; this is a
platform gap, not a decision taken here.

**No read-only role.** This module has no `customers_ro` role or query service
yet (ARCHITECTURE.md constraints #10 and #15). It needs one before any read path
ships.

## Migration ids

Revision ids are capped at 32 characters by `alembic_version.version_num`, and
`rails_0002_blockchain_submission` already sits exactly at the limit. A longer id
applies every DDL statement and then fails on the stamp write, rolling the whole
upgrade back with an error that names a varchar width and no table.
`tests/contract/test_migration_discovery.py` enforces the cap.
