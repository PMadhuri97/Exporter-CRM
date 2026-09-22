# onboarding

Business domain. Public facade is `__init__.py` — the only import surface for other modules (ARCHITECTURE.md §6).

---

## Onboarding workflow

`OnboardingWorkflow` ([`workflows/onboarding_workflow.py`](workflows/onboarding_workflow.py))
drives one `onboarding_request` from `DRAFT` to `ACTIVE` on Temporal. The workflow decides
what happens next and does nothing else: every status change and every call to another
capability is a Temporal activity ([`application/activities.py`](application/activities.py)).

The legacy identity-provider foundation (registration and the inbound Sumsub webhook, the
KYC `Case` state machine in `domain/state_machine.py`) is separate and not part of this
workflow.

### Steps

| # | Step | Activity | Outcome |
|---|---|---|---|
| 1 | Entity verification | `verify_onboarding_entity` | Verified continues. Rejected / not found → `REJECTED` (`KYB_FAILURE`). Pending or needs review → waits for `kyb_result_received` |
| 2 | UBO mapping | `identify_onboarding_ubo_owners`, then `map_onboarding_ubo_owner` per owner | |
| 3 | Document collection | `check_onboarding_documents` | Waits on `document_submitted` until complete; the only step with an inactivity timeout |
| 4 | Screening | `screen_onboarding_request` | Hard block → `REJECTED` (`SCREENING_BLOCK`) |
| 5 | Risk rating | `rate_onboarding_risk` | |
| 6 | Compliance approval | `request_onboarding_compliance_approval` | Immediate decision, or waits for `compliance_decision_received`. Rejection → `REJECTED` (`COMPLIANCE_REJECTION`) |
| 7–8 | Account creation, user provisioning | `create_onboarding_accounts`, `provision_onboarding_initial_user` | → `ACTIVE` |
| 9 | Completion notification | `notify_onboarding_completed` | Sent once the request is `ACTIVE` |

### Lifecycle

The permitted transitions live in
[`domain/policies/onboarding_request_transitions.py`](domain/policies/onboarding_request_transitions.py):

```
DRAFT → ENTITY_VERIFICATION_IN_PROGRESS → (UNDER_REVIEW →) ENTITY_VERIFIED
      → UBO_MAPPING_IN_PROGRESS → UBO_MAPPING_COMPLETE
      → DOCUMENT_COLLECTION_IN_PROGRESS → DOCUMENT_COLLECTION_COMPLETE
      → SCREENING_IN_PROGRESS → SCREENING_COMPLETE
      → RISK_RATING_IN_PROGRESS → RISK_RATED
      → PENDING_COMPLIANCE_APPROVAL → APPROVED
      → ACCOUNT_CREATION_IN_PROGRESS → ACTIVE
```

`REJECTED` is reachable from the steps that can reject; `ABANDONED` only from document
collection. `ACTIVE`, `REJECTED` and `ABANDONED` are terminal. The graph is acyclic, and a
unit test keeps it that way — transition idempotency depends on it (below).

### Transitions and events

`OnboardingTransitionService` is the only writer of `onboarding_request.status`. In one
transaction it applies a conditional `UPDATE … WHERE status = :expected_status` and inserts
the `onboarding_event`; any failure rolls back both. Called again for a transition that
already committed (a retried activity whose acknowledgement was lost), it returns the
original event instead of writing a second one. Because the lifecycle is acyclic, the
`from → to` edge identifies that event.

### Retries

Activities retry with exponential backoff (coefficient 2.0), using
`TEMPORAL_MAX_RETRY_ATTEMPTS` and `TEMPORAL_RETRY_INITIAL_INTERVAL_SECONDS`. Business
outcomes — a KYB rejection, a screening hard block, a declined approval — are returned as
data and never retried. Deterministic errors (`OnboardingTransitionNotPermittedError`,
`OnboardingStatusConflictError`, `OnboardingRequestNotFoundError`,
`OnboardingDependencyUnavailableError`) are non-retryable. An activity that exhausts its
retries fails the execution, leaving the request in the status it had reached.

### Resuming

Every execution starts by loading the request's persisted status and transitions
(`load_onboarding_progress`) and continues from there (`RESUME_STEP_BY_STATUS`):

- a completed status (e.g. `ENTITY_VERIFIED`) continues at the next step;
- an in-progress status re-runs its own step — dependencies are idempotent per request, and
  a step does not re-apply a transition the request already holds;
- a terminal request is returned as it is; nothing runs.

So a failed execution can be started again under the same workflow id
(`onboarding-<request id>`) and picks up where the request stands, without repeating
events. `onboarding_detail` still lists every event, including those earlier executions
recorded. When resuming in document collection, the inactivity period is counted from the
resume.

### Signals

| Signal | Payload | Accepted when |
|---|---|---|
| `document_submitted` | `DocumentSubmitted` (request id, document id, type) | Names this request and the onboarding has not ended. A repeated document id is ignored. Documents sent before collection starts are held and counted when it does |
| `kyb_result_received` | `KybResultReceived` (request id, vendor id, vendor reference, outcome) | Names this request and the active submission. An early result is held until the submission is known |
| `compliance_decision_received` | `ComplianceDecisionReceived` (request id, approval request id, decision) | Names this request and the active approval request. An early decision is held; once decided, later ones are ignored |

### Queries

- `current_status` — status, who the onboarding is waiting on (`platform`,
  `entity_verification_provider`, `manual_review`, `customer`, `compliance`, or none once
  ended) and, when waiting on the customer, `submit_documents` with the missing document
  types.
- `onboarding_detail` — references and outcomes (verification reference, UBO owner
  references, document ids, screening/risk/approval references and results, account ids,
  user reference), the inactivity deadline while waiting on the customer, and every
  recorded transition with its event id.

### Inactivity timeout

While waiting on the customer for documents, no customer action for
`ONBOARDING_INACTIVITY_TIMEOUT_DAYS` (default **30**) moves the request to `ABANDONED`.
Each document submission restarts the period and is stamped on `last_activity_at`. Waiting
on the verification provider, manual review or compliance is not customer inactivity.

### Data kept out of Temporal history

Workflow input, activity inputs and results, signal payloads and query results hold only
ids, references, status values and enum values — never the onboarding record (names,
registration or tax numbers, addresses). A compliance decision travels as the decision and
the approval request id only: the free-text reason stays with compliance, and
`request_onboarding_compliance_approval` drops it before its result enters history.

### Dependencies

The capabilities the workflow orchestrates are narrow contracts in
[`domain/workflow_dependencies.py`](domain/workflow_dependencies.py), one `Protocol` per
capability, keyed by onboarding request id and idempotent per request. None has a real
implementation yet: the worker is built with
[`infrastructure/adapters/unavailable_workflow_dependencies.py`](infrastructure/adapters/unavailable_workflow_dependencies.py),
where every call raises the non-retryable `OnboardingDependencyUnavailableError`, so an
onboarding stops visibly at the first unimplemented step and is never approved by default.
Replace that set in `bootstrap.run_worker` as implementations arrive.

Tests use the deterministic stubs in
[`tests/fixtures/workflow_dependency_stubs.py`](tests/fixtures/workflow_dependency_stubs.py).

### Starting a workflow

`application/onboarding_workflow_service.start_onboarding_workflow(request_id)` reads the
settings, passes them in as workflow input (the workflow never reads configuration) and
starts the workflow on `TEMPORAL_TASK_QUEUE`. A second start for a running request returns
the same workflow id.

### Tests

```bash
pytest app/modules/onboarding --no-cov
```

Workflow tests run against Temporal's time-skipping test server and a real PostgreSQL. The
Temporal server-restart suite starts and stops a local dev server ten times and is opt-in:

```bash
RUN_RESILIENCE_TESTS=1 pytest app/modules/onboarding/tests/integration/test_onboarding_workflow_recovery.py --no-cov
```
