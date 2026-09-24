"""Document requirements API (B2) — read-only.

`DocumentRequirementsService` and its GitOps loader have been built, validated
and tested for some time, and were reachable from Python and from nothing else.
Onboarding could evaluate which documents a profile owes, and no caller outside
the test suite could ask. This router is that surface, and only that surface.

Deliberately read-only, and deliberately not a document API
-----------------------------------------------------------
Nothing in this checkout stores an uploaded document. There is an
`onboarding_document` table and an `OnboardingDocumentType` enum, but no upload
path, no object store, and no validation pipeline — that is a later phase. What
exists today is the *policy*: given a profile's attributes, which document types
are required, and for how long each stays valid once issued. So this endpoint
answers exactly that and claims nothing else. It reports no per-document status,
because there is no document to have one, and it accepts no writes.

Its value now is to the UI: an exporter's page can tell an operator what will be
asked for, before any of it can be uploaded, instead of showing an empty
documents panel that looks like a bug.

Why the profile arrives as query parameters
--------------------------------------------
The configuration matches on `entity_type`, `registration_country`,
`sector_code` and `corridor_intent`, and its conditional rules additionally test
`declared_monthly_volume_usd`. Three of those five live on `onboarding_request`,
not on `exporter_profile`, and one (`corridor_intent`) is a list there — so
there is no single persisted row this endpoint could key off by id and get all
five from. Taking them as an explicit profile description keeps the endpoint a
straight, cacheable function of the policy: the same inputs always produce the
same answer, and it stays usable for a profile that does not exist yet (an
operator asking "what would we need from a Singapore trust?").

Schemas are declared in this module rather than in `api/schemas/`
-----------------------------------------------------------------
Against the convention every other route group here follows. The reason is
concurrency, not preference: `api/schemas/` is being edited by two other people
this phase, and these three models are used by nothing but this file. Worth
folding into `api/schemas/document_requirements.py` once this phase's branches
are merged.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.modules.onboarding.domain.policies.document_requirements_service import (
    DocumentRequirementsService,
)
from app.modules.onboarding.infrastructure.document_requirements_loader import (
    load_document_requirements_service,
)
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import require_role

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/document-requirements", tags=["Document Requirements"])

#: Every internal staff role may read the policy. It is version-controlled
#: configuration, not customer data — there is no PII in a list of document
#: type names, so the narrower `_STAFF` gate the CRM's own reads use would be
#: gating the wrong thing. DEVELOPER is included for the same reason it can
#: read the CRM at all (masked), and `API_USER` is excluded because this is an
#: internal surface: external callers get the `gateway`, which is paused.
_READER = require_role(
    UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.ADMIN, UserRole.DEVELOPER
)


@lru_cache(maxsize=1)
def _service() -> DocumentRequirementsService:
    """The parsed, validated policy, read from disk once per process.

    The YAML is GitOps-managed: it changes by deploy, never at runtime, so
    re-reading and re-validating it on every request would buy nothing. A
    malformed file raises `DocumentRequirementsConfigurationError` on the first
    request rather than at import, which keeps a bad config from taking the
    whole app down at boot — it takes down this one endpoint, loudly.
    """
    return load_document_requirements_service()


class DocumentRequirementResponse(BaseModel):
    """One required document type, with its configured validity window."""

    model_config = ConfigDict(extra="forbid")

    document_type: str = Field(
        description="The document type key, as named in the GitOps policy."
    )
    max_age_days: int | None = Field(
        default=None,
        description=(
            "How old the document may be at the point it is accepted. "
            "`null` means it is accepted regardless of age."
        ),
    )
    validity_description: str | None = Field(
        default=None,
        description="The policy's own human-readable note about the window, if it has one.",
    )


class DocumentRequirementsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: str
    registration_country: str
    sector_code: str | None
    corridor_intent: str | None
    declared_monthly_volume_usd: int | None
    #: The policy file's own `version` string. Echoed back so a UI showing
    #: this list, and a compliance officer reading it later, can say which
    #: revision of the policy produced it.
    policy_version: str
    required_documents: list[DocumentRequirementResponse]
    total: int


def _validity_for(config: dict[str, Any], document_type: str) -> tuple[int | None, str | None]:
    """The configured window for one document type, or `(None, None)`.

    A type with no `validity_periods` entry is accepted regardless of age —
    the same reading `DocumentRequirementsService.validate_document_age` takes
    ("If no specific rule exists, assume unlimited validity"), kept consistent
    here rather than re-decided.
    """
    rule = config.get("validity_periods", {}).get(document_type) or {}
    if not isinstance(rule, dict):
        return None, None
    max_age = rule.get("max_age_days")
    description = rule.get("description")
    return (
        max_age if isinstance(max_age, int) else None,
        description if isinstance(description, str) else None,
    )


@router.get(
    "",
    response_model=DocumentRequirementsResponse,
    summary="Required documents for a profile",
    description=(
        "Evaluates the GitOps-managed document requirements policy for the profile "
        "described by the query parameters and returns the document types it "
        "requires, each with its configured validity window.\n\n"
        "Read-only, and about policy rather than about any particular customer: it "
        "reports what *will* be required, not what has been collected. No document "
        "storage exists in this build, so there is no per-document status to report "
        "and nothing here accepts an upload."
    ),
    responses={
        200: {"model": DocumentRequirementsResponse},
        401: {"description": "Unauthorized"},
        403: {
            "description": "OPERATIONS, COMPLIANCE, ADMIN or DEVELOPER role required"
        },
        422: {"description": "Invalid query parameters"},
        500: {"description": "The document requirements policy file is missing or malformed"},
    },
)
async def get_document_requirements(
    current_user: Annotated[User, Depends(_READER)],
    entity_type: Annotated[
        str,
        Query(
            min_length=1,
            max_length=64,
            description="Legal entity structure, e.g. `CORPORATION`. Matched case-insensitively.",
        ),
    ],
    registration_country: Annotated[
        str,
        Query(
            min_length=2,
            max_length=2,
            description="ISO 3166-1 alpha-2 country of registration, e.g. `IN`.",
        ),
    ],
    sector_code: Annotated[
        str | None,
        Query(
            max_length=64,
            description="FATF sector classification, e.g. `DNFBP`. Omit if not yet recorded.",
        ),
    ] = None,
    corridor_intent: Annotated[
        str | None,
        Query(
            max_length=64,
            description="Intended payment corridor, e.g. `US-IN`. Omit if not yet recorded.",
        ),
    ] = None,
    declared_monthly_volume_usd: Annotated[
        int | None,
        Query(
            ge=0,
            description=(
                "Declared monthly volume in USD. Some conditional rules test it; "
                "omit if not yet declared."
            ),
        ),
    ] = None,
) -> DocumentRequirementsResponse:
    service = _service()
    document_types = service.get_required_documents(
        entity_type=entity_type,
        registration_country=registration_country,
        sector_code=sector_code,
        corridor_intent=corridor_intent,
        declared_monthly_volume_usd=declared_monthly_volume_usd,
    )

    documents = [
        DocumentRequirementResponse(
            document_type=document_type,
            max_age_days=max_age,
            validity_description=description,
        )
        for document_type, (max_age, description) in (
            (dt, _validity_for(service.config, dt)) for dt in document_types
        )
    ]

    logger.info(
        "document_requirements.evaluated",
        entity_type=entity_type,
        registration_country=registration_country,
        sector_code=sector_code,
        corridor_intent=corridor_intent,
        required_document_count=len(documents),
        actor_id=str(current_user.id),
    )

    return DocumentRequirementsResponse(
        entity_type=entity_type,
        registration_country=registration_country,
        sector_code=sector_code,
        corridor_intent=corridor_intent,
        declared_monthly_volume_usd=declared_monthly_volume_usd,
        policy_version=str(service.config.get("version", "unknown")),
        required_documents=documents,
        total=len(documents),
    )


__all__ = [
    "DocumentRequirementResponse",
    "DocumentRequirementsResponse",
    "router",
]
