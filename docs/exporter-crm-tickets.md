# Exporter CRM & Financing Intake — Build Tickets (Phase 1)

Two tickets covering the approved plan's points 1–3 (CRM fields, Contacts/Activities, the
generalized `VerificationAdapter` Protocol) plus point 4 (results storage) and the relevant slice
of point 7 (API). Each ticket is a complete vertical slice — schema, domain, application service,
API, tests — so it ships as one working, demoable unit rather than requiring the other ticket to
be "done" first. TICKET-2 only needs TICKET-1's `customer_id`/`Exporter` concept to exist in name,
not in full — it can start in parallel.

Naming convention: `EXP-1`, `EXP-2` (this repo's own tracking, not tied to the company's Jira).

---

## EXP-1 — Exporter CRM Profile, Contacts, and Activities

**Goal:** Give every `OnboardingRequest.customer_id` an enduring profile — the CRM fields, contact
people, and relationship history that don't belong to any single verification journey — and the
service/API surface to create, search, and maintain it.

### Schema
New file `app/modules/onboarding/domain/entities/exporter_profile.py` — `ExporterProfile`:
- `customer_id: UUID` (unique — one profile per enduring customer identity; not a FK to
  `OnboardingRequest` since a profile may exist before any onboarding journey starts, e.g. a Lead
  entered by Sales with nothing verified yet)
- `gstin: str | None`, `pan: str | None`, `iec: str | None` (India-specific identifiers; confirm
  against `OnboardingRequest.registration_number` whether that already serves as CIN-equivalent —
  if yes, don't duplicate it here)
- `source: Enum` — `MANUAL, SALES, REFERRAL, RXIL, PARTNER, API, BROKER, EVENT, EXISTING_CUSTOMER`
  (immutable once set — this is an audit-relevant fact, same DB-trigger pattern as
  `ComplianceCase.resolved_by`)
- `relationship_manager: str | None` (an actor identifier, same convention as `assigned_to`
  elsewhere in this codebase — plain string, not a FK to a user table)
- `lifecycle_status: Enum` — `LEAD, CONTACTED, DATA_COLLECTION, VERIFICATION_IN_PROGRESS,
  COMPLIANCE_REVIEW, ONBOARDED, FINANCING_ELIGIBLE, ACTIVE, SUSPENDED, OFFBOARDED` — a genuinely
  new, separate enum from `OnboardingRequestStatus` (that one tracks one verification pass; this
  tracks the whole relationship)
- `industry: str | None`, `export_markets: JSONB (list[str]) | None`,
  `products: JSONB (list[str]) | None`, `year_established: int | None`, `website: str | None`
- `date_added: DateTime(tz)` (immutable, server_default now)
- Standard `id`/`created_at`/`updated_at` via `AnerModel`

New file `app/modules/onboarding/domain/entities/exporter_contact.py` — `ExporterContact`:
- `customer_id: UUID` (FK'd to nothing formally — same bare-reference convention `cases` uses for
  cross-cutting identifiers; indexed)
- `name: str`, `role: str | None`, `email: str | None`, `phone: str | None`,
  `department: str | None`, `is_primary_contact: bool` (default false; a partial unique index
  ensures at most one primary contact per `customer_id`)

New file `app/modules/onboarding/domain/entities/exporter_activity.py` — `ExporterActivity`
(append-only — an activity log entry is never edited after the fact, same base as
`OnboardingEvent`):
- `customer_id: UUID` (indexed)
- `activity_type: Enum` — `CALL, MEETING, EMAIL, NOTE, TASK, FOLLOW_UP`
- `subject: str`, `notes: str | None`, `actor_id: str`, `occurred_at: DateTime(tz)`
- `due_at: DateTime(tz) | None` (for TASK/FOLLOW_UP types — nullable, meaningless for CALL/NOTE)

New migration `onboarding_0005_exporter_crm.py`, chaining onto the current head
(`onboarding_0004_screening_fix`). Constraints to add and verify with direct-SQL tests (the
established convention in this codebase — every constraint gets a test that violates it via raw
SQL, not just through the service layer): `source` immutable-once-set trigger; partial unique
index on `(customer_id) WHERE is_primary_contact = true` for `ExporterContact`; append-only
trigger on `ExporterActivity` (reject UPDATE/DELETE, same pattern as `OnboardingEvent`/
`CaseTimelineEvent`).

### Domain / Application
`app/modules/onboarding/application/exporter_profile_service.py` (new file, mirrors
`OnboardingRequestService`'s method-per-operation style):
- `create_or_get_profile(customer_id, *, source, ...) -> ExporterProfile` — idempotent create
  (use `app.platform.idempotency` if a caller-facing idempotency key is warranted, or a simple
  unique-constraint-catch if `customer_id` uniqueness is enough — decide based on whether this is
  ever called from an untrusted/retrying caller; RXIL ingestion in a later ticket will be, so lean
  toward idempotency-key support now rather than retrofitting)
- `update_profile(customer_id, **fields) -> ExporterProfile` (does not allow changing `source` —
  enforce at the service layer in addition to the DB trigger, so the error is a clean domain
  exception, not a raw DB error surfacing to a caller)
- `search_profiles(*, gstin=None, pan=None, iec=None, legal_name_contains=None, source=None,
  lifecycle_status=None, limit=50, offset=0) -> list[ExporterProfile]`
- `transition_lifecycle_status(customer_id, to_status, actor_id) -> ExporterProfile` — validate
  against a small permitted-transition table (follow `cases`' `PERMITTED_TRANSITIONS` pattern:
  a module-level frozenset of `(from, to)` pairs, not a free-for-all)
- `get_profile_detail(customer_id) -> ExporterProfileDetail` — the profile plus its contacts,
  recent activities, and linked `OnboardingRequest` history (query by `customer_id`, no new join
  table needed — confirmed in the plan that `OnboardingRequest.customer_id` already supports
  multiple historical rows)

`app/modules/onboarding/application/exporter_contact_activity_service.py` (new file):
- `add_contact(customer_id, *, name, role=None, email=None, phone=None, department=None,
  is_primary=False) -> ExporterContact` — setting `is_primary=True` demotes any existing primary
  contact for that `customer_id` (single service-layer transaction, not two separate calls a
  caller could race)
- `list_contacts(customer_id) -> list[ExporterContact]`
- `log_activity(customer_id, *, activity_type, subject, notes=None, actor_id, due_at=None) ->
  ExporterActivity`
- `list_activities(customer_id, *, activity_type=None, limit=50, offset=0) ->
  list[ExporterActivity]`

### API
New routes in `app/modules/onboarding/api/router.py` (or a new `api/exporter_router.py` included
alongside it if the existing file's size/conventions argue for a split — check its current length
and existing route-grouping style before deciding), following this file's existing
`Depends(get_current_active_user)` convention:
- `POST /onboarding/exporters` — create profile
- `GET /onboarding/exporters/{customer_id}` — profile detail (contacts, recent activities,
  onboarding history)
- `PATCH /onboarding/exporters/{customer_id}` — update profile fields
- `POST /onboarding/exporters/{customer_id}/transition` — lifecycle status transition
- `GET /onboarding/exporters` — search (query params: gstin, pan, iec, legal_name, source, status)
- `POST /onboarding/exporters/{customer_id}/contacts` — add contact
- `GET /onboarding/exporters/{customer_id}/contacts` — list contacts
- `POST /onboarding/exporters/{customer_id}/activities` — log activity
- `GET /onboarding/exporters/{customer_id}/activities` — list activities

### Acceptance criteria
- A profile can be created with `source=SALES`, then a later attempt to change `source` (via the
  service or via direct SQL) is rejected — both the service-layer guard and the DB trigger are
  independently verified by tests.
- Setting a second contact as primary for the same `customer_id` correctly demotes the first —
  never two primaries at once, verified by both a service-level test and a direct-SQL constraint
  test.
- An `ExporterActivity` row rejects UPDATE and DELETE via direct SQL.
- `search_profiles` matching by `gstin` returns the correct profile; matching by
  `legal_name_contains` does a case-insensitive partial match (confirm this needs its data pulled
  from the linked `OnboardingRequest.legal_name`, not a duplicated field on `ExporterProfile` —
  the plan says don't duplicate what `OnboardingRequest` already has, so `search_profiles` likely
  needs a join, not a flat query — implement accordingly, don't add a redundant `legal_name`
  column to `ExporterProfile` to make the query simpler).
- `transition_lifecycle_status` rejects an invalid transition (e.g. `LEAD` → `ACTIVE` directly)
  with a clear domain exception naming the current and attempted status.
- All new endpoints return 401/403 correctly for missing/wrong-role auth, matching this router's
  existing convention.
- Full existing suite still passes (`pytest app/modules -q --no-cov`, `pytest tests/contract -q
  --no-cov`) — zero regressions.
- Cross-module import grep: `onboarding` still only reaches `kyb`/`cases` via facades — this
  ticket shouldn't add any new cross-module import at all, since everything in it is
  self-contained to `onboarding`.

---

## EXP-2 — Generalized VerificationAdapter Protocol and Results Storage

**Goal:** One extensible mechanism to trigger and record *any* verification check (KYC for a
director, bank statement verification, shipping bill verification, or anything not yet
anticipated) without writing a new framework each time — generalizing `kyb`'s working
adapter/registry pattern rather than paralleling it.

### Schema
New file `app/modules/onboarding/domain/entities/verification_result.py` —
`VerificationResult` (the PRD's exact required field list):
- `verification_type: Enum` — `KYC, KYB, AML, CFT, SANCTIONS, PEP, ADVERSE_MEDIA,
  COMPANY_REGISTRY, UBO, GST, IEC, BANK_ACCOUNT, BUYER, INVOICE, INVOICE_DUPLICATION, SHIPMENT,
  VESSEL, INSURANCE` — deliberately a plain enum, not a free string, so `Alembic`/the DB constrain
  it, but designed to be extended additively (new members, new migration) as new check types show
  up — never a schema redesign
- `entity_type: Enum` — `EXPORTER, BUYER, DIRECTOR, INVOICE, VESSEL, SHIPMENT` (what kind of thing
  is being checked)
- `entity_reference: UUID` (bare reference to that entity's own id — no FK, since `entity_type`
  determines which table it points at and this codebase's convention for exactly this situation
  — see `ComplianceCase.customer_id/settlement_id/onboarding_id` — is a bare, documented UUID, not
  a polymorphic FK)
- `provider: str` (e.g. `"RXIL"`, `"Middesk"`, `"manual"` — free string, matches `CaseEvidenceItem
  .source_epic`'s convention exactly, for the same reason: the whole point is the rest of the app
  never special-cases which provider answered)
- `provider_reference: str | None`
- `status: Enum` — `PENDING, PASSED, FAILED, REVIEW`
- `risk_level: Enum | None` — `LOW, MEDIUM, HIGH` (nullable — not every check type produces one)
- `performed_at: DateTime(tz)`
- `valid_until: DateTime(tz) | None` (expiry, where applicable)
- `raw_result: JSONB` (the provider's original response, unmodified)
- `normalized_result: JSONB` (this platform's standardized shape — mirrors
  `KybVendorResult.normalised_result`'s intent but generalized past a single enum, since different
  verification types normalize to different shapes)
- `evidence_reference: str | None` (a pointer to stored evidence — document/report — not the
  document content itself, matching `OnboardingDocument.storage_path`'s convention)
- `reviewed_by: str | None`, `review_status: Enum | None` — `ACCEPTED, REJECTED, ESCALATED`

Also: `raw_result` is genuinely sensitive for some `verification_type`s (AML, sanctions, adverse
media results can contain PII) — follow the exact documented-gap convention already established
for `raw_vendor_response`/`tax_identification_number` (flagged as needing encryption-at-rest via
the platform KMS key, not actually enforced yet, same honest gap the rest of this codebase already
carries — don't invent new encryption machinery for this one table when nothing else in the
codebase has real KMS integration yet).

New migration `onboarding_0006_verification_result.py`, chaining onto `onboarding_0005`.
`KybVendorResult` is **left as-is, not migrated** — confirmed in the plan as an implementation-time
call, and the call for this ticket is: don't touch it. `kyb`'s existing path keeps writing to
`KybVendorResult` exactly as it does today; `VerificationResult` is additive, for everything
`KybVendorResult` doesn't cover. (Revisit consolidating them in a later ticket once the new table
has real usage to judge the migration cost against.)

### Domain
New Protocol + dataclasses in `app/modules/onboarding/domain/workflow_dependencies.py` (same file,
same one-Protocol-per-capability convention as the existing 9 — do not create a new `ports.py`
for this):
```python
@dataclass(frozen=True)
class VerificationRequest:
    verification_type: VerificationType
    entity_type: EntityType
    entity_reference: str
    payload: dict[str, Any] = field(default_factory=dict)   # type-specific input fields

@dataclass(frozen=True)
class VerificationOutcome:
    provider: str
    provider_reference: str | None
    status: VerificationStatus
    normalized_result: dict[str, Any]
    risk_level: RiskLevel | None = None
    valid_until: datetime | None = None

class VerificationAdapter(Protocol):
    def declare_capabilities(self) -> VerificationCapabilityDeclaration: ...
    def verify(self, request: VerificationRequest) -> VerificationOutcome: ...
    def get_verification_status(self, provider_reference: str) -> VerificationOutcome: ...
    def get_vendor_health(self) -> VendorHealthStatus: ...
```
Registry: generalize `kyb.domain.ports`'s `register_adapter`/`get_adapter` module-dict mechanism
into a new registry scoped to `VerificationAdapter` (a straight copy of the pattern, parameterized
by the new Protocol — this is the "reuse, don't parallel" instruction applied literally: same two
functions, same dict-backed registry shape, new type parameter).

One real adapter for this ticket: `ManualEntryAdapter` (`infrastructure/adapters/
manual_entry_adapter.py`) — satisfies `VerificationAdapter` by accepting a manually-supplied
result rather than calling any vendor, proving the Protocol end-to-end and satisfying the PRD's
explicit "manual verification entry" MVP requirement without needing a real vendor integration
yet.

### Application
`app/modules/onboarding/application/verification_service.py` (new file):
- `trigger_verification(verification_type, entity_type, entity_reference, *, provider="manual",
  payload=None, actor_id) -> VerificationResult` — looks up the adapter for `provider` via the
  registry, calls `.verify()`, persists a `VerificationResult` row from the returned
  `VerificationOutcome`
- `get_verification_status(provider_reference) -> VerificationResult` — polls via the adapter for
  async/pending checks, updates the stored row if the status has changed
- `list_verification_results(entity_type, entity_reference) -> list[VerificationResult]` — every
  check ever run against a given exporter/buyer/director/invoice/vessel
- `record_review(verification_result_id, *, reviewed_by, review_status) -> VerificationResult` —
  the human-review half of the PRD's "Reviewed By / Review Status" fields

### API
- `POST /onboarding/verifications` — trigger a check (`verification_type`, `entity_type`,
  `entity_reference`, `provider`, `payload`)
- `GET /onboarding/verifications/{id}` — single result detail
- `GET /onboarding/verifications?entity_type=...&entity_reference=...` — list results for an
  entity
- `POST /onboarding/verifications/{id}/review` — record a compliance reviewer's decision

### Acceptance criteria
- Triggering a `KYC` check against `entity_type=DIRECTOR` and a `BANK_ACCOUNT` check against
  `entity_type=EXPORTER` both route through the exact same `trigger_verification` call and the
  exact same registry lookup — no `if verification_type == ...` branching in the service layer.
  This is the single most important test in this ticket: it's the direct proof of "generalized,
  not hardcoded."
- `ManualEntryAdapter` round-trips a result end-to-end (trigger → stored `VerificationResult` →
  retrievable via `list_verification_results`).
- A `provider` string is never rewritten or defaulted away from what the adapter actually reports
  — a test asserting the PRD's explicit correctness example (a result recorded with
  `provider="RXIL"` is never observable as `provider="Internal"` anywhere in the read path) even
  though RXIL's own adapter isn't built until the next ticket — write this test against a fake
  adapter reporting `provider="RXIL"` now, so the guarantee exists before RXIL integration lands,
  not after.
- `record_review` correctly sets `reviewed_by`/`review_status` and does not allow reviewing a
  `VerificationResult` twice with conflicting outcomes without an explicit override path (decide:
  is `reviewed_by`/`review_status` immutable-once-set, same as `resolved_by` elsewhere in this
  codebase, or genuinely re-editable? Lean toward immutable-once-set for audit consistency with
  every other "who decided this" field in this codebase, flag if that turns out to be wrong for
  the real review workflow once it's built).
- Full existing suite still passes; cross-module import grep clean (this ticket also shouldn't
  need any new cross-module import — `kyb` stays untouched, `cases` isn't referenced yet since
  that wiring is a later ticket).

---

## Explicitly not in these two tickets

- Financing Opportunity, Buyer, Invoice, Shipment, Insurance entities — plan point 5, next ticket.
- RXIL's own adapter (`RxilAdapter` satisfying `VerificationAdapter` with a batch variant) — plan
  point 6, needs EXP-2 to exist first.
- Wrapping `kyb`'s Middesk/Trulioo adapters to also satisfy `VerificationAdapter` — explicitly
  deferred per the confirmed plan decision, not part of Phase 1 at all.
- Any change to `cases` (new `CaseType`/`ResolutionAction` members, `financing_opportunity_id`
  column) — needed only once Financing Opportunity exists.
