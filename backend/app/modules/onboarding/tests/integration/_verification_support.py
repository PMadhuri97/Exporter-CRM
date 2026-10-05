"""Shared scaffolding for the verification and screening integration tests.
Not a test module (no ``test_`` prefix, so pytest does not collect it).

Real Postgres, no per-test rollback: every helper mints its own company, deal or
buyer, the convention the rest of the onboarding suite follows.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg2
import psycopg2.extras

from app.modules.onboarding.application.deal_service import DealService
from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationType,
)
from app.modules.onboarding.domain.entities.verification_result import VerificationResult
from app.modules.onboarding.domain.verification_evidence import VerificationEvidence
from app.modules.onboarding.tests.fixtures.companies import make_prospect
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services

BASE = "/api/v1/onboarding"
NOTE = VerificationEvidence(note="Checked against the registry extract.")


@contextmanager
def pg() -> Iterator[Any]:
    """A committed-per-statement psycopg2 cursor for direct-SQL tests."""
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    conn = psycopg2.connect(url)
    conn.autocommit = True
    try:
        with conn.cursor() as cursor:
            yield cursor
    finally:
        conn.close()


async def open_deal(company_id: uuid.UUID, reference: str = "Rotterdam shipment") -> uuid.UUID:
    async with db_services.AsyncSessionLocal() as db:
        deal = await DealService(db).open_deal(company_id, reference=reference, actor_id="tester")
    return deal.id


async def set_buyer(deal_id: uuid.UUID, **fields: Any) -> uuid.UUID:
    values = {"name": "Rotterdam Trading BV", "country": "NL", **fields}
    async with db_services.AsyncSessionLocal() as db:
        view = await DealService(db).set_buyer(deal_id, actor_id="tester", **values)
    return view.buyer.id


async def deal_buyer(**fields: Any) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A fresh prospect, a deal on it and its buyer: ``(company_id, deal_id, buyer_id)``.

    A prospect, because a deal cannot be opened on a ``LEAD``."""
    company_id = await make_prospect()
    deal_id = await open_deal(company_id)
    buyer_id = await set_buyer(deal_id, **fields)
    return company_id, deal_id, buyer_id


def insert_document(
    cursor: Any,
    *,
    company_id: uuid.UUID | None = None,
    deal_id: uuid.UUID | None = None,
    scan_status: str = "AVAILABLE",
) -> uuid.UUID:
    """A ``crm_document`` row owned by a company or a deal, ``AVAILABLE`` unless told
    otherwise. The file itself is never read by these tests, so no object is stored."""
    document_id = uuid.uuid4()
    cursor.execute(
        "INSERT INTO onboarding.crm_document (id, company_id, deal_id, category, document_type, "
        " source, file_name, content_type, size_bytes, uploaded_at, scan_status, storage_key) "
        "VALUES (%s, %s, %s, 'COMPLIANCE_SCREENING', 'bank_letter', 'INTERNAL', 'letter.pdf', "
        " 'application/pdf', 10, now(), %s, %s)",
        (
            str(document_id),
            str(company_id) if company_id else None,
            str(deal_id) if deal_id else None,
            scan_status,
            f"test/l4b/{document_id}.pdf",
        ),
    )
    return document_id


def insert_result(
    cursor: Any,
    *,
    entity_type: str = "DIRECTOR",
    entity_reference: uuid.UUID | None = None,
    status: str = "REVIEW",
    provider: str = "manual",
    provider_reference: str | None = None,
    normalized_result: dict | None = None,
) -> uuid.UUID:
    result_id = uuid.uuid4()
    cursor.execute(
        "INSERT INTO onboarding.verification_result (id, verification_type, entity_type, "
        " entity_reference, provider, provider_reference, status, performed_at, raw_result, "
        " normalized_result) VALUES (%s, 'KYC', %s, %s, %s, %s, %s, now(), '{}'::jsonb, %s)",
        (
            str(result_id),
            entity_type,
            str(entity_reference or uuid.uuid4()),
            provider,
            provider_reference,
            status,
            psycopg2.extras.Json(normalized_result or {}),
        ),
    )
    return result_id


def insert_review(
    cursor: Any,
    result_id: uuid.UUID,
    *,
    supersedes: uuid.UUID | None = None,
    note: str | None = None,
    status: str = "ACCEPTED",
) -> uuid.UUID:
    review_id = uuid.uuid4()
    cursor.execute(
        "INSERT INTO onboarding.verification_review (id, verification_result_id, review_status, "
        " reviewed_by, note, supersedes_review_id) VALUES (%s, %s, %s, 'sql', %s, %s)",
        (str(review_id), str(result_id), status, note, str(supersedes) if supersedes else None),
    )
    return review_id


async def exporter_result(
    company_id: uuid.UUID,
    *,
    status: str = "PASSED",
    evidence: VerificationEvidence | None = NOTE,
    verification_type: VerificationType = VerificationType.KYB,
    provider_reference: str | None = None,
) -> VerificationResult:
    payload: dict[str, Any] = {"status": status}
    if provider_reference:
        payload["provider_reference"] = provider_reference
    async with db_services.AsyncSessionLocal() as db:
        return await VerificationService(db).trigger_verification(
            verification_type,
            VerificationEntityType.EXPORTER,
            company_id,
            provider="manual",
            payload=payload,
            actor_id="tester",
            evidence=evidence,
        )


def history_rows(cursor: Any, company_id: uuid.UUID, dimension: str = "verification") -> list:
    cursor.execute(
        "SELECT event_type, from_status, to_status, actor_id, reason, deal_id, event_metadata "
        "FROM onboarding.exporter_lifecycle_history WHERE customer_id = %s AND dimension = %s "
        "ORDER BY created_at, id",
        (str(company_id), dimension),
    )
    return cursor.fetchall()


__all__ = [
    "BASE",
    "NOTE",
    "deal_buyer",
    "exporter_result",
    "history_rows",
    "insert_document",
    "insert_result",
    "insert_review",
    "open_deal",
    "pg",
    "set_buyer",
]
