"""OnboardingRequestService — the S7T1 onboarding service API (Epic 4.1, S7).

**Naming.** ``backend/app/modules/onboarding/application/onboarding_service.py``
already defines a class named ``OnboardingService`` — pre-Epic-4.1 code for a
different case/KYC design (keyed off ``Customer`` / the legacy
``OnboardingStatus``, importing ``app.modules.audit``). That file is
deliberately left untouched (see the S7 build report for why). This class is
named ``OnboardingRequestService`` instead, both to avoid the name collision
and because it is, literally, the service for the ``OnboardingRequest``
aggregate the S1 schema defines.

**No Temporal workflow exists yet.** S3 (the Temporal workflow skeleton) is a
later Story and is not present in this codebase. Per the spec
(``Jira/4.1 B2B Onboarding Orchestration.docx``, S7T1), several of these
operations are documented as "sends a signal to the Temporal workflow" — this
class performs the equivalent direct, real data operation against the S1
schema instead, and each such method's docstring notes where a Temporal signal
would additionally be sent once S3 exists. Nothing here fakes a workflow to
call.

**Idempotency.** ``initiate_onboarding`` follows
``KybVendorRegistryService``'s pattern exactly: imperative
``register_key`` / ``complete_key`` calls from
``app.platform.idempotency.services``, with a hand-rolled
duplicate-lookup-by-cached-id (not the generic ``evaluate_duplicate_contract``
helper), so the method can keep returning the domain entity rather than a
serialised response. Unlike the KYB vendor registry, ``onboarding_request``
also carries its own DB-level uniqueness on ``(tenant_id, idempotency_key)``
(migration ``onboarding_0002_orchestration``), so — mirroring
``CaseService.create_case``'s belt-and-suspenders pattern — the insert also
runs inside a savepoint with an ``IntegrityError`` fallback that re-resolves
the existing row. Two independent duplicate defences, because both constraints
independently exist on this table.

**Field-level access control.** ``get_onboarding_detail`` restricts
``tax_identification_number`` and each UBO's ``identification_number`` to the
compliance officer role, per the doc's own access-control note. This is a
**new pattern in this codebase** — the only existing RBAC mechanism
(``app.platform.authorization.services.require_role``) gates a whole FastAPI
route before the service is ever invoked; nothing in this codebase redacts
individual fields inside a service response today. Since this Story is scoped
to application-layer logic with no router in front of it, the method takes an
explicit ``requesting_role: UserRole`` parameter and redacts internally. A
router wiring this up in a future Story should still call
``require_role(...)`` at the route boundary for the endpoint as a whole (e.g.
to keep the operation itself gated to authenticated staff), and additionally
pass the resolved role through to this method for the field-level decision —
the two checks answer different questions and neither replaces the other.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.application.onboarding_transition_service import (
    OnboardingTransitionService,
)
from app.modules.onboarding.domain.entities.kyb_vendor_result import KybVendorResult
from app.modules.onboarding.domain.entities.onboarding_document import OnboardingDocument
from app.modules.onboarding.domain.entities.onboarding_event import OnboardingEvent
from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest
from app.modules.onboarding.domain.entities.orchestration_enums import (
    OnboardingDocumentType,
    OnboardingEntityType,
    OnboardingRequestStatus,
    OnboardingValidationStatus,
    UboControlType,
    UboIdentificationType,
    UboKycResult,
    UboPepStatus,
)
from app.modules.onboarding.domain.entities.ubo_record import UboRecord
from app.modules.onboarding.domain.onboarding_request_views import (
    DocumentProgress,
    KybVendorResultView,
    OnboardingDetailView,
    OnboardingDocumentView,
    OnboardingEventView,
    OnboardingHistoryEntry,
    OnboardingStatusView,
    UboMappingProgress,
    UboRecordView,
)
from app.modules.onboarding.domain.policies.document_requirements_service import (
    DocumentRequirementsService,
)
from app.modules.onboarding.domain.policies.onboarding_next_action import (
    next_required_action,
)
from app.modules.onboarding.infrastructure.document_requirements_loader import (
    load_document_requirements_service,
)
from app.modules.onboarding.infrastructure.repositories import (
    KybVendorResultRepository,
    OnboardingDocumentRepository,
    OnboardingEventRepository,
    OnboardingRequestRepository,
    UboRecordRepository,
)
from app.platform.authentication.models import UserRole
from app.platform.idempotency.models import IdempotencyKeyType, RegistrationResultType
from app.platform.idempotency.services import complete_key, register_key
from app.shared.exceptions import NotFoundError, ValidationError

logger = structlog.get_logger(__name__)

#: Scope identifier for every idempotency record this service creates.
_SCOPE = "onboarding_request"
_OP_INITIATE = "initiate_onboarding"


class OnboardingRequestService:
    """Read/write access to `onboarding_request` and its child aggregates (S7T1)."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        document_requirements: DocumentRequirementsService | None = None,
    ) -> None:
        self._db = db
        self._requests = OnboardingRequestRepository(db)
        self._ubos = UboRecordRepository(db)
        self._documents = OnboardingDocumentRepository(db)
        self._events = OnboardingEventRepository(db)
        self._vendor_results = KybVendorResultRepository(db)
        # Lazy default: only touches the filesystem if the caller does not
        # inject a service (tests inject one built from an in-memory config).
        self._document_requirements = document_requirements

    def _doc_requirements(self) -> DocumentRequirementsService:
        if self._document_requirements is None:
            self._document_requirements = load_document_requirements_service()
        return self._document_requirements

    # ── Initiate ─────────────────────────────────────────────────────────────

    async def initiate_onboarding(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_type: OnboardingEntityType,
        legal_name: str,
        incorporation_country: str,
        initial_user_email: str,
        idempotency_key: str,
        registration_number: str | None = None,
        registered_address: dict | None = None,
        trading_name: str | None = None,
        tax_identification_number: str | None = None,
        incorporation_date: date | None = None,
        trading_address: dict | None = None,
        sector_code: str | None = None,
        corridor_intent: list[str] | None = None,
        declared_monthly_volume_usd: int | None = None,
        correlation_id: str | None = None,
        actor_id: str | None = None,
    ) -> tuple[OnboardingRequest, bool]:
        """Create an onboarding_request, or return the one this key already created.

        Returns ``(request, created)``. ``created`` is False on an idempotent
        replay. Per the doc: "Creates the onboarding_request record, starts
        the Temporal workflow, and returns the onboarding_id and customer_id"
        — the Temporal workflow does not exist yet (S3), so only the record is
        created; the returned `OnboardingRequest.id` / `.customer_id` are the
        onboarding_id / customer_id the doc names.

        `registration_number` / `registered_address` (judgment call —
        Exporter CRM piece 1). Both became nullable on the S1 schema in
        `onboarding_0007_reg_optional`, specifically so a Sales-sourced Lead
        can be created with nothing more than `legal_name` +
        `incorporation_country` — a cold Lead usually doesn't have a
        registration number or registered address on file yet. Both default
        to `None` here to match; `submit_entity_details` remains the one path
        that fills them in once known.

        `initial_user_email` — judgment call, deliberately left required
        (not loosened). `initial_user_id` (the column this populates, see
        below) is still `NOT NULL` on the S1 schema — this piece's confirmed
        scope is only `registration_number`/`registered_address`, not a third
        column. Making this parameter optional without also loosening
        `initial_user_id` would just move the failure from "caller must
        supply a value" (a clean signature error) to "the DB rejects a NULL
        insert" (a worse failure mode, surfacing as a raw `IntegrityError`
        instead of a validation error). It would also mean inventing a
        placeholder string for a NOT-NULL column to paper over a schema gap
        that wasn't part of this piece's confirmed change — worse than
        requiring the caller supply a real value. A bare Lead genuinely has
        no platform user yet, but it usually does have *some* reachable
        address (the Sales rep's own contact, a lead-intake mailbox, or
        whatever channel Sales captured) — the caller supplies that here.
        Fully supporting a Lead with no reachable address at all is a
        separate, future change (either loosening `initial_user_id` itself
        once S6T2's real user-provisioning path exists, or introducing a
        distinct "lead contact" concept apart from "initial platform user")
        and is out of scope for this piece.

        `initial_user_id` is `NOT NULL` on the S1 schema, but real user
        provisioning (S6T2, "the user provisioning activity stores the
        initial_user_id ... on the onboarding_request record") has not run at
        initiation time — it hasn't run at all, since S6 isn't in scope here.
        `initial_user_email` is stored as a placeholder in `initial_user_id`
        until a future Story's S6T2 implementation overwrites it with the
        actual provisioned user id.
        """
        reg_result = await register_key(
            session=self._db,
            key_value=idempotency_key,
            key_type=IdempotencyKeyType.CUSTOMER_KEY,
            scope_id=_SCOPE,
            operation_type=_OP_INITIATE,
            correlation_id=correlation_id,
            created_by=actor_id,
        )

        if reg_result.result == RegistrationResultType.DUPLICATE:
            cached = (
                reg_result.record.response_cache if reg_result.record is not None else None
            )
            if cached and cached.get("onboarding_request_id"):
                existing = await self._requests.get_by_id(
                    uuid.UUID(cached["onboarding_request_id"])
                )
                if existing is not None:
                    logger.info(
                        "onboarding_request.initiate.idempotent_replay",
                        onboarding_id=str(existing.id),
                        idempotency_key=idempotency_key,
                    )
                    return existing, False
            # Cache miss (e.g. the completing write crashed after `register_key`
            # but before `complete_key`): fall back to the DB-level unique
            # constraint's own row, if the insert actually landed.
            existing_by_key = await self._requests.get_by_tenant_and_idempotency_key(
                tenant_id, idempotency_key
            )
            if existing_by_key is not None:
                return existing_by_key, False

        now = datetime.now(UTC)
        request = OnboardingRequest(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            customer_id=uuid.uuid4(),
            status=OnboardingRequestStatus.DRAFT,
            entity_type=entity_type,
            legal_name=legal_name,
            trading_name=trading_name,
            registration_number=registration_number,
            tax_identification_number=tax_identification_number,
            incorporation_country=incorporation_country,
            incorporation_date=incorporation_date,
            registered_address=registered_address,
            trading_address=trading_address,
            industry_code=sector_code,
            declared_monthly_volume_usd=declared_monthly_volume_usd,
            corridor_intent=corridor_intent,
            initial_user_id=initial_user_email,
            initiated_at=now,
            last_activity_at=now,
            correlation_id=correlation_id,
        )

        try:
            async with self._db.begin_nested():
                self._db.add(request)
                await self._db.flush()
        except IntegrityError:
            winner = await self._requests.get_by_tenant_and_idempotency_key(
                tenant_id, idempotency_key
            )
            if winner is None:
                raise
            logger.info(
                "onboarding_request.initiate.lost_race", onboarding_id=str(winner.id)
            )
            return winner, False

        await self._events.create(
            OnboardingEvent(
                onboarding_request_id=request.id,
                event_type="state_transition",
                from_status=None,
                to_status=OnboardingRequestStatus.DRAFT.value,
                actor_id=actor_id,
                event_metadata={"trigger": "onboarding_initiated"},
            )
        )

        await complete_key(
            session=self._db,
            key_value=idempotency_key,
            scope_id=_SCOPE,
            terminal_status="completed",
            response_payload={"onboarding_request_id": str(request.id)},
        )
        await self._db.commit()
        await self._db.refresh(request)

        logger.info(
            "onboarding_request.initiate.ok",
            onboarding_id=str(request.id),
            customer_id=str(request.customer_id),
        )
        return request, True

    # ── Submit entity details ───────────────────────────────────────────────

    async def submit_entity_details(
        self,
        onboarding_id: uuid.UUID,
        *,
        trading_name: str | None = None,
        tax_identification_number: str | None = None,
        incorporation_date: date | None = None,
        trading_address: dict | None = None,
        sector_code: str | None = None,
        corridor_intent: list[str] | None = None,
        declared_monthly_volume_usd: int | None = None,
        actor_id: str | None = None,
    ) -> OnboardingRequest:
        """Update entity details not provided at initiation.

        "Customer submits entity details" is the DRAFT -> ENTITY_VERIFICATION_IN_PROGRESS
        trigger; this method requires the request to be in DRAFT and performs that
        transition. The transition itself — the status write and its
        ``onboarding_event`` row — is delegated to ``OnboardingTransitionService``
        (AL-672), the platform's single canonical writer of
        ``onboarding_request.status``; this method only owns the entity-detail
        field updates, which are not part of that service's contract.

        Would also send an `entity_details` signal to the Temporal workflow
        (S3) here, once it exists.
        """
        request = await self._require_request(onboarding_id)
        if request.status != OnboardingRequestStatus.DRAFT:
            raise ValidationError(
                f"submit_entity_details is only valid while onboarding {onboarding_id} "
                f"is in DRAFT status (current status: {request.status.value})"
            )

        updates: dict[str, object] = {
            "trading_name": trading_name,
            "tax_identification_number": tax_identification_number,
            "incorporation_date": incorporation_date,
            "trading_address": trading_address,
            "industry_code": sector_code,
            "corridor_intent": corridor_intent,
            "declared_monthly_volume_usd": declared_monthly_volume_usd,
        }
        changes = {key: value for key, value in updates.items() if value is not None}

        previous_status = request.status
        next_status = OnboardingRequestStatus.ENTITY_VERIFICATION_IN_PROGRESS

        for key, value in changes.items():
            setattr(request, key, value)
        request.last_activity_at = datetime.now(UTC)
        await self._db.flush()

        # OnboardingTransitionService both validates the move against the
        # canonical PERMITTED_TRANSITIONS table and commits it, together with
        # the field updates flushed above (same session, one transaction).
        await OnboardingTransitionService(self._db).transition(
            request.id,
            expected_status=previous_status,
            to_status=next_status,
            actor_id=actor_id,
            metadata={"trigger": "entity_details_submitted", "changed": sorted(changes)},
        )
        await self._db.refresh(request)

        logger.info(
            "onboarding_request.submit_entity_details.ok",
            onboarding_id=str(request.id),
            next_status=next_status.value,
        )
        return request

    # ── Submit document ──────────────────────────────────────────────────────

    async def submit_document(
        self,
        onboarding_id: uuid.UUID,
        *,
        document_type: OnboardingDocumentType,
        storage_path: str,
        file_name: str,
        mime_type: str,
        size_bytes: int,
        actor_id: str | None = None,
    ) -> OnboardingDocument:
        """Create an `onboarding_document` row and update document tracking.

        The doc's input is a single opaque `document_reference`; the actual S1
        schema (`onboarding_document`) instead stores `storage_path`,
        `file_name`, `mime_type` and `size_bytes` — this method's signature
        follows the real schema, not the doc's field name (see the S7 build
        report's field-naming reconciliation).

        "Update the request's document-tracking" is satisfied by
        `last_activity_at` plus the `document_received` event below;
        `get_onboarding_status` derives documents-received directly from the
        `onboarding_document` rows rather than from a separate JSON tracking
        column, because the S1 schema does not have one (the doc's
        `documents_received` JSON field on `onboarding_request` is not part of
        the implemented table).

        Would also send a `document_submitted` signal to the Temporal workflow
        (S3) here, once it exists.
        """
        request = await self._require_request(onboarding_id)

        document = OnboardingDocument(
            onboarding_request_id=request.id,
            document_type=document_type,
            storage_path=storage_path,
            file_name=file_name,
            mime_type=mime_type,
            size_bytes=size_bytes,
            validation_status=OnboardingValidationStatus.PENDING,
            submitted_at=datetime.now(UTC),
        )
        await self._documents.create(document)

        request.last_activity_at = datetime.now(UTC)
        await self._db.flush()

        await self._events.create(
            OnboardingEvent(
                onboarding_request_id=request.id,
                event_type="document_received",
                from_status=request.status.value,
                to_status=request.status.value,
                actor_id=actor_id,
                event_metadata={
                    "document_id": str(document.id),
                    "document_type": document_type.value,
                },
            )
        )
        await self._db.commit()
        await self._db.refresh(document)

        logger.info(
            "onboarding_request.submit_document.ok",
            onboarding_id=str(request.id),
            document_id=str(document.id),
            document_type=document_type.value,
        )
        return document

    # ── Submit UBO declaration ───────────────────────────────────────────────

    async def submit_ubo_declaration(
        self,
        onboarding_id: uuid.UUID,
        *,
        ubo_details: list[dict],
        actor_id: str | None = None,
    ) -> list[UboRecord]:
        """Create one `ubo_record` per entry in `ubo_details`.

        Each entry is a mapping with keys `first_name`, `last_name`,
        `control_type` (required — matches the NOT NULL column), and
        optionally `nationality`, `residence_country`, `ownership_percentage`,
        `identification_type`, `identification_number`, `kyc_result`
        (defaults to `NOT_STARTED`), `pep_status`.

        Would also signal the UBO mapping Temporal activity (S4T1) here, once
        it exists.
        """
        request = await self._require_request(onboarding_id)
        if not ubo_details:
            raise ValidationError("submit_ubo_declaration requires at least one UBO entry")

        created: list[UboRecord] = []
        for entry in ubo_details:
            control_type = entry["control_type"]
            if isinstance(control_type, str):
                control_type = UboControlType(control_type)

            identification_type = entry.get("identification_type")
            if isinstance(identification_type, str):
                identification_type = UboIdentificationType(identification_type)

            kyc_result = entry.get("kyc_result", UboKycResult.NOT_STARTED)
            if isinstance(kyc_result, str):
                kyc_result = UboKycResult(kyc_result)

            pep_status = entry.get("pep_status")
            if isinstance(pep_status, str):
                pep_status = UboPepStatus(pep_status)

            ubo = UboRecord(
                onboarding_request_id=request.id,
                first_name=entry["first_name"],
                last_name=entry["last_name"],
                nationality=entry.get("nationality"),
                residence_country=entry.get("residence_country"),
                control_type=control_type,
                ownership_percentage=entry.get("ownership_percentage"),
                identification_type=identification_type,
                identification_number=entry.get("identification_number"),
                kyc_result=kyc_result,
                pep_status=pep_status,
            )
            await self._ubos.create(ubo)
            created.append(ubo)

        request.last_activity_at = datetime.now(UTC)
        await self._db.flush()

        await self._events.create(
            OnboardingEvent(
                onboarding_request_id=request.id,
                event_type="ubo_identified",
                from_status=request.status.value,
                to_status=request.status.value,
                actor_id=actor_id,
                event_metadata={
                    "ubo_count": len(created),
                    "ubo_ids": [str(u.id) for u in created],
                },
            )
        )
        await self._db.commit()
        for ubo in created:
            await self._db.refresh(ubo)

        logger.info(
            "onboarding_request.submit_ubo_declaration.ok",
            onboarding_id=str(request.id),
            ubo_count=len(created),
        )
        return created

    # ── Get status ───────────────────────────────────────────────────────────

    async def get_onboarding_status(self, onboarding_id: uuid.UUID) -> OnboardingStatusView:
        """Current status, next required action, and document/UBO progress."""
        request = await self._require_request(onboarding_id)
        documents = await self._documents.list_by_onboarding_request(onboarding_id)
        ubos = await self._ubos.list_by_onboarding_request(onboarding_id)

        required = self._required_document_types(request)
        doc_progress = DocumentProgress(
            required_document_types=tuple(required),
            received=tuple(_document_view(d) for d in documents),
        )

        ubo_progress = UboMappingProgress(
            total_ubos=len(ubos),
            verified_count=sum(1 for u in ubos if u.kyc_result == UboKycResult.VERIFIED),
            pending_count=sum(1 for u in ubos if u.kyc_result == UboKycResult.PENDING),
            failed_count=sum(1 for u in ubos if u.kyc_result == UboKycResult.FAILED),
            not_started_count=sum(
                1 for u in ubos if u.kyc_result == UboKycResult.NOT_STARTED
            ),
        )

        pending_review_reason = None
        if request.status in (
            OnboardingRequestStatus.REJECTED,
            OnboardingRequestStatus.UNDER_REVIEW,
        ):
            pending_review_reason = request.rejection_reason

        return OnboardingStatusView(
            onboarding_id=request.id,
            customer_id=request.customer_id,
            status=request.status,
            next_required_action=next_required_action(request.status),
            documents=doc_progress,
            ubo_progress=ubo_progress,
            pending_review_reason=pending_review_reason,
        )

    def _required_document_types(self, request: OnboardingRequest) -> list[str]:
        corridor = request.corridor_intent[0] if request.corridor_intent else None
        raw = self._doc_requirements().get_required_documents(
            entity_type=request.entity_type.value,
            registration_country=request.incorporation_country,
            sector_code=request.industry_code,
            corridor_intent=corridor,
            declared_monthly_volume_usd=request.declared_monthly_volume_usd,
        )
        # The GitOps config's document type vocabulary is lower snake_case
        # ("certificate_of_incorporation"); OnboardingDocumentType values are
        # UPPER_SNAKE_CASE. Normalise so they compare equal to what
        # `onboarding_document.document_type` actually stores.
        return [doc_type.upper() for doc_type in raw]

    # ── Get detail ───────────────────────────────────────────────────────────

    async def get_onboarding_detail(
        self, onboarding_id: uuid.UUID, *, requesting_role: UserRole
    ) -> OnboardingDetailView:
        """Full onboarding_request record with related UBOs, documents, and events.

        Restricts `tax_identification_number` and each UBO's
        `identification_number` to `UserRole.COMPLIANCE` — see this module's
        docstring for why this is a new pattern, not an existing one.
        """
        request = await self._require_request(onboarding_id)
        ubos = await self._ubos.list_by_onboarding_request(onboarding_id)
        documents = await self._documents.list_by_onboarding_request(onboarding_id)
        events = await self._events.list_by_request(onboarding_id)
        vendor_results = await self._vendor_results.list_by_onboarding_request(onboarding_id)

        redact = requesting_role != UserRole.COMPLIANCE

        ubo_views = tuple(_ubo_view(u, redact=redact) for u in ubos)

        return OnboardingDetailView(
            onboarding_id=request.id,
            customer_id=request.customer_id,
            tenant_id=request.tenant_id,
            status=request.status,
            entity_type=request.entity_type,
            legal_name=request.legal_name,
            trading_name=request.trading_name,
            registration_number=request.registration_number,
            tax_identification_number=(
                None if redact else request.tax_identification_number
            ),
            incorporation_country=request.incorporation_country,
            incorporation_date=request.incorporation_date,
            registered_address=request.registered_address,
            trading_address=request.trading_address,
            industry_code=request.industry_code,
            declared_monthly_volume_usd=request.declared_monthly_volume_usd,
            corridor_intent=request.corridor_intent,
            screening_result=request.screening_result,
            ubo_mapping=request.ubo_mapping,
            screening_reference_id=request.screening_reference_id,
            risk_rating=request.risk_rating,
            risk_rating_factors=request.risk_rating_factors,
            compliance_approval_request_id=request.compliance_approval_request_id,
            compliance_decision=request.compliance_decision,
            rejection_category=request.rejection_category,
            rejection_reason=request.rejection_reason,
            account_ids=request.account_ids,
            initial_user_id=request.initial_user_id,
            initial_user_roles=request.initial_user_roles,
            correlation_id=request.correlation_id,
            initiated_at=request.initiated_at,
            completed_at=request.completed_at,
            last_activity_at=request.last_activity_at,
            ubo_records=ubo_views,
            documents=tuple(_document_view(d) for d in documents),
            events=tuple(_event_view(e) for e in events),
            vendor_results=tuple(_vendor_result_view(v) for v in vendor_results),
            sensitive_fields_redacted=redact,
        )

    # ── Get history ──────────────────────────────────────────────────────────

    async def get_onboarding_history(
        self, customer_id: uuid.UUID
    ) -> list[OnboardingHistoryEntry]:
        """All onboarding_request records for `customer_id`, reverse chronological."""
        requests = await self._requests.list_by_customer(customer_id)
        return [
            OnboardingHistoryEntry(
                onboarding_id=r.id,
                status=r.status,
                legal_name=r.legal_name,
                initiated_at=r.initiated_at,
                completed_at=r.completed_at,
                rejection_category=r.rejection_category,
            )
            for r in requests
        ]

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _require_request(self, onboarding_id: uuid.UUID) -> OnboardingRequest:
        request = await self._requests.get_by_id(onboarding_id)
        if request is None:
            raise NotFoundError(f"Onboarding request {onboarding_id} not found")
        return request


# ── View-model builders (module-level: shared with OnboardingQueryService) ───


def _document_view(document: OnboardingDocument) -> OnboardingDocumentView:
    return OnboardingDocumentView(
        id=document.id,
        onboarding_request_id=document.onboarding_request_id,
        document_type=document.document_type.value,
        file_name=document.file_name,
        validation_status=document.validation_status.value,
        rejection_reason=document.rejection_reason,
        submitted_at=document.submitted_at,
    )


def _event_view(event: OnboardingEvent) -> OnboardingEventView:
    return OnboardingEventView(
        id=event.id,
        onboarding_request_id=event.onboarding_request_id,
        event_type=event.event_type,
        from_status=event.from_status,
        to_status=event.to_status,
        actor_id=event.actor_id,
        event_metadata=event.event_metadata,
        created_at=event.created_at,
    )


def _vendor_result_view(result: KybVendorResult) -> KybVendorResultView:
    return KybVendorResultView(
        id=result.id,
        onboarding_request_id=result.onboarding_request_id,
        vendor_name=result.vendor_name,
        vendor_reference_id=result.vendor_reference_id,
        normalised_result=result.normalised_result.value,
        retrieved_at=result.retrieved_at,
    )


def _ubo_view(ubo: UboRecord, *, redact: bool) -> UboRecordView:
    return UboRecordView(
        id=ubo.id,
        onboarding_request_id=ubo.onboarding_request_id,
        first_name=ubo.first_name,
        last_name=ubo.last_name,
        nationality=ubo.nationality,
        residence_country=ubo.residence_country,
        control_type=ubo.control_type,
        ownership_percentage=ubo.ownership_percentage,
        identification_type=ubo.identification_type,
        identification_number=None if redact else ubo.identification_number,
        kyc_result=ubo.kyc_result,
        pep_status=ubo.pep_status,
        screening_reference_id=ubo.screening_reference_id,
    )


__all__ = ["OnboardingRequestService"]
