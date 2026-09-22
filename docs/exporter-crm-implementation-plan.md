# Exporter CRM & Financing Intake Module — Implementation Plan (v2: reuse-first)

## Context

The user supplied a PRD ("Exporter CRM & Financing Intake Module") describing a CRM for exporters
that converges two intake channels — manually-sourced exporters (financier runs KYB/KYC/AML
through external vendors) and RXIL-originated exporters (RXIL already performed KYC/KYB/AML/CFT/
invoice-duplication/vessel-tracking/e-bill-of-lading/buyer-rating/insurance checks upstream, to be
*ingested, never recreated*) — into one common structure: a canonical Exporter profile, a generic
verification-result model, and a Financing Opportunity a Credit Approver reviews and decides on.

**Revision note:** the first version of this plan proposed a new `exporters` module with parallel
entities (`Exporter`, `VerificationResult`, a new `VerificationProvider` protocol). The user
explicitly rejected that direction: the goal is to **reuse the existing onboarding
module's schema, services, and adapter pattern directly** — extend what's already built (S1
schema, `kyb`'s adapter/registry pattern, AL-672's Temporal workflow dependency Protocols, `cases`
for review) rather than build a second, parallel system next to it. Whatever check a user wants to
trigger — KYC for a director/CEO, KYB for the business, bank-statement verification, shipping-bill
verification, or anything else — should route through one generalized version of the mechanism
that already works for KYB today, not a bespoke new framework.

## Architecture: extend `onboarding` in place

**No new module.** Everything below is added to `app/modules/onboarding/`, reusing its existing
schema and patterns:

1. **Exporter identity = `OnboardingRequest.customer_id`.** This column already exists and already
   supports multiple historical rows per customer (the partial-unique constraint only restricts
   `status='ACTIVE'`, not history) — so "one exporter, multiple verification journeys over time" is
   already schema-legal today, no new join table needed. CRM/profile fields that don't belong to a
   single verification pass (GSTIN, PAN, IEC — `registration_number` already covers CIN-equivalent,
   confirm exact mapping during implementation — source channel, relationship manager, lifecycle
   status distinct from `OnboardingRequestStatus`) go on a new, lightweight entity keyed by
   `customer_id`, living in `onboarding/domain/entities/` alongside everything else — not a
   separate module, not a separate schema.

2. **Contacts and Activities** — new entities in `onboarding/domain/entities/`, FK'd to
   `customer_id` (not to a specific `OnboardingRequest`, since a relationship's contacts/activity
   history spans every journey that customer ever goes through).

3. **Generalize the adapter pattern, don't parallel it.** `kyb.KYBAdapter` (declare_capabilities /
   verify_entity / get_verification_status / get_vendor_health) is real and working for business
   verification. Rather than building a separate framework for every other check type (director
   KYC, bank statement verification, shipping bill verification, buyer verification, whatever comes
   next), generalize the *same shape* into one Protocol parameterized by check type, added to
   `onboarding/domain/workflow_dependencies.py` alongside the existing 9 Protocols (`EntityVerifier`,
   `Screener`, `RiskRater`, etc. — same file, same one-Protocol-per-capability convention already
   established there):
   ```python
   class VerificationAdapter(Protocol):
       def declare_capabilities(self) -> VerificationCapabilityDeclaration: ...
       def verify(self, request: VerificationRequest) -> VerificationResult: ...
       def get_verification_status(self, vendor_reference: str) -> VerificationResult: ...
       def get_vendor_health(self) -> VendorHealthStatus: ...
   ```
   `VerificationRequest`/`VerificationResult` carry a `verification_type` (KYC, KYB, AML, CFT,
   SANCTIONS, PEP, ADVERSE_MEDIA, BANK_ACCOUNT, BUYER, SHIPPING_BILL, INVOICE_DUPLICATION, VESSEL,
   INSURANCE, ...) and an `entity_reference` (which business/director/buyer/shipment/invoice the
   check is against) — this is the "can be anything, whatever necessary" mechanism: **new check
   types are new enum members and new adapters registered against the same registry, not new
   frameworks.** Reuse `kyb`'s `register_adapter`/`get_adapter` registry mechanism (generalized to
   this new Protocol) rather than inventing a second registry.
   - `kyb.KYBAdapter`/`MiddeskAdapter`/Trulioo stay exactly as they are — the existing KYB path
     keeps working unmodified. Whether they get wrapped to also satisfy the new generalized
     Protocol, or stay a separate special case forever, is an implementation-time call, not a
     blocking decision — lean toward wrapping them once the generalized Protocol exists, since
     "one path, not two" is the whole point of this revision.

4. **Verification results storage** — generalize `KybVendorResult`'s shape (vendor_name,
   vendor_reference_id, normalised_result, raw_vendor_response, retrieved_at) into a new,
   broader table in `onboarding` covering any verification type against any entity reference
   (adds `verification_type`, `entity_type`/`entity_reference`, `risk_level`, `valid_until`,
   `reviewed_by`, `review_status` — the PRD's required field list) rather than keeping KYB
   permanently siloed in its own narrow table. `KybVendorResult` itself can either be migrated into
   this broader table or left as-is with the new table used for everything else — implementation-
   time call based on how disruptive migrating existing KYB data/tests turns out to be.

5. **Financing Opportunity + Credit Review** — new entities in `onboarding`
   (`FinancingOpportunity`, `Buyer`, `Invoice`, `Shipment`, `Insurance`), reusing `cases` for review
   exactly as already built: `FinancingOpportunityService.create_opportunity(...)` always opens a
   `ComplianceCase` (additive `CaseType` members `FINANCING_INTAKE`/`FINANCING_REVIEW`, following
   the exact precedent of the existing `ONBOARDING_INTAKE`/`ONBOARDING_REVIEW` pair), and credit
   decisions call `cases.CaseLifecycleService.propose_resolution`/`decide_resolution` directly
   (reusing the maker-checker stand-in verbatim, including the "checker ≠ maker" guard) — this part
   of the original plan is unchanged, since it was already "reuse `cases`," not "build parallel
   infrastructure."

6. **RXIL ingestion** — one payload → many `VerificationResult` rows via the generalized adapter
   from point 3 (a `RxilAdapter` satisfying `VerificationAdapter`, with a `verify_batch()` add-on
   since RXIL hands over many check types in one package, unlike Middesk/Trulioo's one-call-one-
   result shape). Match-or-create the exporter by `customer_id` using strong identifiers
   (GSTIN/PAN/IEC/CIN) before falling back to name matching; ambiguous matches go to a `cases`
   entry (new `EXPORTER_DUPLICATE_REVIEW` case type) for manual resolution.

7. **API layer** — built alongside the domain work (confirmed earlier: pull it forward, don't
   defer). Thin `onboarding/api/` additions for the new capabilities — exporter profile CRUD/
   search, contacts/activities, triggering a verification check, RXIL ingestion endpoint, financing
   opportunity creation, Credit Review Workspace view, credit decision actions — wired into
   `app/main.py` the same way the module's existing (legacy) router already is.

## What this avoids versus the rejected v1

- No new module, no new import-linter contract, no new facade to maintain.
- No second adapter framework sitting next to `kyb`'s working one — one generalized Protocol,
  reusing the same registry mechanism.
- No duplicate storage of fields `OnboardingRequest` already has (legal_name, registered_address,
  entity_type, etc.) — the new CRM entity only carries what's genuinely new (GSTIN/PAN/IEC, source,
  relationship manager, contacts, activities), keyed by the `customer_id` that already ties
  multiple journeys together.

## Critical files

- `app/modules/onboarding/domain/entities/onboarding_request.py` — the entity everything keys off
  of via `customer_id`; not modified in shape, just referenced.
- `app/modules/onboarding/domain/workflow_dependencies.py` — where the new `VerificationAdapter`
  Protocol and its result dataclasses get added, following the exact style of the existing 9.
- `app/modules/kyb/domain/ports.py` + `app/modules/kyb/infrastructure/adapters/middesk_adapter.py`
  — the registry/adapter pattern to generalize, not replace.
- `app/modules/onboarding/domain/entities/kyb_vendor_result.py` — the shape to generalize into the
  new broader verification-results table.
- `app/modules/cases/domain/entities/enums.py` and `compliance_case.py` — additive `CaseType`/
  `ResolutionAction` members and a new `financing_opportunity_id` bare-UUID column, same pattern as
  the existing `onboarding_id`/`settlement_id`/`ONBOARDING_INTAKE` precedents.
- `app/modules/onboarding/application/onboarding_request_service.py` /
  `onboarding_query_service.py` — where new exporter/contact/activity/financing-opportunity
  application methods get added, matching this file's existing method-per-operation style.
- `app/modules/onboarding/api/router.py` — where new endpoints get added; check this file's
  existing route/auth-dependency conventions before adding new ones.

## Verification approach

- Every new DB constraint gets a direct-SQL violation test (established convention throughout this
  project).
- The generalized `VerificationAdapter` registry gets a test proving both a KYB check and at least
  one new check type (e.g. bank-statement verification) route through the same registry mechanism
  without special-casing.
- RXIL ingestion: a test proving a `provider="RXIL"` result is never relabeled "Internal," and a
  re-sent RXIL payload for the same exporter attaches to the existing customer rather than
  duplicating it.
- Run the full existing suite (`pytest app/modules -q --no-cov`, `pytest tests/contract -q
  --no-cov`) after every additive schema change to confirm zero regressions.
- Grep for cross-module imports after each step — `onboarding` should still only reach `kyb` and
  `cases` via their facades, same discipline as everywhere else in this project.
