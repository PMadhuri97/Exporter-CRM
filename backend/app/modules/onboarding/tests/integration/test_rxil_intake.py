"""RXIL company intake (L2-12).

A company RXIL hands over is created or matched by the CRM's own identity
rules, becomes a PROSPECT through RXIL's own QUALIFIED outcome, and keeps
RXIL's results exactly as supplied — never recomputed from the CRM's criteria.

Each test mints its own PANs and GSTINs, so runs never collide.
"""

from __future__ import annotations

import ast
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.modules.onboarding.application.company_intake_service import PartnerIntakeService
from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.application.qualification_service import QualificationService
from app.modules.onboarding.domain.company_intake import PartnerCompanyIntake
from app.modules.onboarding.domain.entities.exporter_enums import (
    ExporterJourney,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.onboarding_request import OnboardingRequest
from app.modules.onboarding.domain.entities.qualification import (
    QualificationOutcome,
    QualificationResult,
)
from app.modules.onboarding.domain.entities.qualification_enums import (
    CriterionResultValue,
    DecidedByKind,
    QualificationOutcomeValue,
    QualificationSource,
    QualificationState,
)
from app.modules.onboarding.domain.qualification_views import ResultEntry
from app.modules.onboarding.exceptions import (
    IntakeNeedsReviewError,
    PartnerPackageInvalidError,
)
from app.modules.onboarding.infrastructure.rxil.company_package import (
    parse_rxil_company_package,
)
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"
MODULE = Path(__file__).resolve().parents[2]


def _pan() -> str:
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    return f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"


def _gstin(pan: str, state: str = "27") -> str:
    return f"{state}{pan}1Z5"


def _package(pan: str | None = None, *, package_id: str | None = None, **exporter) -> dict:
    pan = pan if pan is not None else _pan()
    body = {
        "exporter": {
            "legal_name": f"RXIL Exporter {uuid.uuid4().hex[:8]}",
            "country": "IN",
            "pan": pan,
            "gstins": [_gstin(pan)],
            **exporter,
        },
        "qualification": {
            "decision": "QUALIFIED",
            "method": "MANUAL",
            "note": "Filtered in by RXIL",
            "criteria": [
                {
                    "criterion": "revenue",
                    "result": "PASS",
                    "value": "12 USD",  # far below the CRM's own threshold, on purpose
                    "evidence": "RXIL credit file 2026-Q3",
                    "evidence_refs": [{"type": "partner_reference", "ref": "RXIL-DOC-77"}],
                    "reason": "RXIL assessment",
                    "confidence": 0.92,
                    "method": "AUTOMATED",
                },
                {"criterion": "export_history", "result": "PASS"},  # no evidence given
            ],
        },
    }
    if package_id is not None:
        body["package_id"] = package_id
    return body


async def _ingest(payload: dict, actor_id: str = "rxil-desk") :
    async with db_services.AsyncSessionLocal() as db:
        return await PartnerIntakeService(db).ingest(
            parse_rxil_company_package(payload), actor_id=actor_id
        )


async def _company(customer_id):
    async with db_services.AsyncSessionLocal() as db:
        return await ExporterProfileService(db)._require_profile(customer_id)


async def _counts(customer_id) -> tuple[int, int, int]:
    async with db_services.AsyncSessionLocal() as db:
        results = await db.scalar(
            select(func.count()).select_from(QualificationResult)
            .where(QualificationResult.customer_id == customer_id)
        )
        outcomes = await db.scalar(
            select(func.count()).select_from(QualificationOutcome)
            .where(QualificationOutcome.customer_id == customer_id)
        )
        _rows, history = await HistoryService(db).list_for_company(customer_id)
    return results, outcomes, history


async def _companies_with_pan(pan: str) -> int:
    async with db_services.AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count()).select_from(ExporterProfile).where(ExporterProfile.pan == pan)
        )


# ── A new company ─────────────────────────────────────────────────────────────


async def test_a_new_company_arrives_as_a_qualified_prospect():
    payload = _package()
    result = await _ingest(payload)
    assert (result.company, result.qualification, result.replayed) == ("created", "recorded", False)

    company = await _company(result.customer_id)
    assert company.name == payload["exporter"]["legal_name"]
    assert company.source is ExporterSource.RXIL
    assert company.journey is ExporterJourney.PROSPECT  # the journey
    assert company.qualification is QualificationState.QUALIFIED  # the gauge, not a journey stage
    assert company.pan == payload["exporter"]["pan"]


async def test_rxil_results_are_kept_exactly_as_supplied():
    payload = _package()
    result = await _ingest(payload, actor_id="rxil-desk-7")
    async with db_services.AsyncSessionLocal() as db:
        view = await QualificationService(db).get_qualification(result.customer_id)
    by_key = {r.criterion.key: r for r in view.results}

    revenue = by_key["revenue"]
    assert revenue.result is CriterionResultValue.PASS
    assert revenue.observed_value == "12 USD"
    assert revenue.evidence_note == "RXIL credit file 2026-Q3"
    assert revenue.evidence_refs == [{"type": "partner_reference", "ref": "RXIL-DOC-77"}]
    assert revenue.reason == "RXIL assessment"
    assert revenue.confidence == Decimal("0.920")
    assert revenue.decided_by_kind is DecidedByKind.AUTOMATED
    assert revenue.source is QualificationSource.RXIL
    assert revenue.recorded_by == "rxil-desk-7"  # who submitted it, from the session
    assert revenue.recorded_at is not None

    history = by_key["export_history"]
    assert history.decided_by_kind is DecidedByKind.MANUAL  # the package's own method
    assert "As supplied by RXIL" in history.evidence_note  # RXIL gave no evidence; said so

    [outcome] = view.outcomes
    assert outcome.outcome is QualificationOutcomeValue.QUALIFIED
    assert outcome.source is QualificationSource.RXIL
    assert outcome.decided_by is None  # RXIL decided, not a user
    assert outcome.note == "Filtered in by RXIL"


async def test_rxil_qualification_is_not_recomputed_locally():
    """Revenue of 12 USD fails the CRM's own threshold, and two required
    criteria have no result at all — the local suggestion would be
    NOT_QUALIFIED. RXIL said QUALIFIED; QUALIFIED it stays, and the outcome
    rests on RXIL's results only."""
    result = await _ingest(_package())
    async with db_services.AsyncSessionLocal() as db:
        view = await QualificationService(db).get_qualification(result.customer_id)
    [outcome] = view.outcomes
    assert view.suggested_outcome is QualificationOutcomeValue.NOT_QUALIFIED  # the CRM's own view
    assert outcome.outcome is QualificationOutcomeValue.QUALIFIED
    assert outcome.suggested_outcome is QualificationOutcomeValue.QUALIFIED  # RXIL's, stored as given
    assert set(outcome.result_ids) == {str(r.id) for r in view.results}


async def test_intake_writes_the_same_history_as_any_review():
    result = await _ingest(_package())
    async with db_services.AsyncSessionLocal() as db:
        rows, _ = await HistoryService(db).list_for_company(result.customer_id, limit=100)
    kinds = {(r.dimension, r.event_type) for r in rows}
    assert ("journey", "lifecycle_initial") in kinds  # created
    assert ("qualification", "qualification_result") in kinds
    assert ("qualification", "qualification_transition") in kinds
    assert ("journey", "lifecycle_transition") in kinds  # LEAD -> PROSPECT
    assert {r.actor_id for r in rows} == {"rxil-desk"}
    outcome_row = next(r for r in rows if r.event_type == "qualification_transition")
    assert outcome_row.event_metadata["source"] == "RXIL"


# ── Matching an existing company ──────────────────────────────────────────────


async def test_an_existing_company_is_matched_by_pan_not_duplicated():
    pan = _pan()
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES, name="Already Here Ltd", country="IN", pan=pan
        )
    result = await _ingest(_package(pan))
    assert (result.customer_id, result.company) == (customer_id, "matched")
    assert await _companies_with_pan(pan) == 1

    company = await _company(customer_id)
    assert company.name == "Already Here Ltd"  # the existing record is not overwritten
    assert company.source is ExporterSource.SALES
    assert (company.journey, company.qualification) == (
        ExporterJourney.PROSPECT, QualificationState.QUALIFIED,
    )


async def test_a_gstin_alone_matches_through_the_pan_it_carries():
    pan = _pan()
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES, name="Pan Holder", country="IN", pan=pan
        )
    payload = _package(pan)
    del payload["exporter"]["pan"]
    result = await _ingest(payload)
    assert result.customer_id == customer_id


async def test_a_gstin_only_delivery_is_found_again_when_repeated():
    """With no PAN the company is created with none — the PAN its GSTIN
    carries is never written into `pan` — so a repeated delivery must find it
    by the GSTIN, not refuse it as a possible duplicate of itself."""
    payload = _package()
    del payload["exporter"]["pan"]
    first = await _ingest(payload)
    counts = await _counts(first.customer_id)
    second = await _ingest(payload)
    assert (second.customer_id, second.company, second.qualification) == (
        first.customer_id, "matched", "already_qualified",
    )
    assert await _counts(first.customer_id) == counts


async def test_an_interrupted_gstin_only_intake_is_finished_by_the_next_delivery(monkeypatch):
    payload = _package()
    del payload["exporter"]["pan"]

    async def boom(*args, **kwargs):
        raise RuntimeError("decision write failed")

    with monkeypatch.context() as patch:
        patch.setattr(QualificationService, "record_partner_decision", boom)
        with pytest.raises(RuntimeError):
            await _ingest(payload)

    result = await _ingest(payload)
    assert (result.company, result.qualification) == ("matched", "recorded")
    company = await _company(result.customer_id)
    assert (company.pan, company.qualification) == (None, QualificationState.QUALIFIED)


async def test_rxil_supersedes_a_local_not_qualified_decision():
    pan = _pan()
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES, name="Rejected Once", country="IN", pan=pan
        )
    async with db_services.AsyncSessionLocal() as db:
        first = await QualificationService(db).record_outcome(
            customer_id, QualificationOutcomeValue.NOT_QUALIFIED,
            reason_codes=["revenue_below_threshold"], actor_id="rm-1",
        )
    await _ingest(_package(pan))
    async with db_services.AsyncSessionLocal() as db:
        view = await QualificationService(db).get_qualification(customer_id)
    assert view.state is QualificationState.QUALIFIED
    assert view.outcomes[0].supersedes_outcome_id == first.id
    assert first.id in {o.id for o in view.outcomes}  # the local decision is kept


async def test_an_already_qualified_company_is_left_alone():
    pan = _pan()
    customer_id = uuid.uuid4()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            customer_id, source=ExporterSource.SALES, name="Qualified Here", country="IN", pan=pan
        )
    async with db_services.AsyncSessionLocal() as db:
        await QualificationService(db).record_outcome(
            customer_id, QualificationOutcomeValue.QUALIFIED, actor_id="rm-1"
        )
    before = await _counts(customer_id)
    result = await _ingest(_package(pan))
    assert result.qualification == "already_qualified"
    assert await _counts(customer_id) == before  # no result, outcome or history added


# ── Repeated delivery ─────────────────────────────────────────────────────────


async def test_a_repeated_package_id_changes_nothing():
    payload = _package(package_id=f"RXIL-{uuid.uuid4().hex[:10]}")
    first = await _ingest(payload)
    counts = await _counts(first.customer_id)
    second = await _ingest(payload)
    assert (second.customer_id, second.replayed) == (first.customer_id, True)
    assert await _counts(first.customer_id) == counts
    assert await _companies_with_pan(payload["exporter"]["pan"]) == 1


async def test_a_repeated_delivery_without_an_id_is_also_harmless():
    payload = _package()
    first = await _ingest(payload)
    counts = await _counts(first.customer_id)
    second = await _ingest(payload)
    assert (second.customer_id, second.company, second.qualification) == (
        first.customer_id, "matched", "already_qualified",
    )
    assert await _counts(first.customer_id) == counts


async def test_an_interrupted_intake_is_finished_by_the_next_delivery(monkeypatch):
    """If recording the decision fails after the company was created, the
    company is a plain LEAD; delivering again completes it, once."""
    payload = _package()

    async def boom(*args, **kwargs):
        raise RuntimeError("decision write failed")

    monkeypatch.setattr(QualificationService, "record_partner_decision", boom)
    with pytest.raises(RuntimeError):
        await _ingest(payload)
    monkeypatch.undo()

    result = await _ingest(payload)
    assert (result.company, result.qualification) == ("matched", "recorded")
    company = await _company(result.customer_id)
    assert (company.journey, company.qualification) == (
        ExporterJourney.PROSPECT, QualificationState.QUALIFIED,
    )
    results, outcomes, _ = await _counts(result.customer_id)
    assert (results, outcomes) == (2, 1)


# ── Duplicate and conflicting identifiers ─────────────────────────────────────


async def test_identifiers_pointing_at_two_companies_are_refused_not_merged():
    pan_a, cin_b = _pan(), f"U17110MH2012PTC{uuid.uuid4().int % 10**6:06d}"
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            uuid.uuid4(), source=ExporterSource.SALES, name="A", country="IN", pan=pan_a
        )
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            uuid.uuid4(), source=ExporterSource.SALES, name="B", country="IN", pan=_pan(),
            cin=cin_b,
        )
    with pytest.raises(IntakeNeedsReviewError) as refused:
        await _ingest(_package(pan_a, cin=cin_b))
    assert refused.value.status_code == 409
    assert len(refused.value.extensions["candidates"]) == 2


async def test_a_resemblance_without_a_pan_is_refused_for_a_person():
    pan = _pan()
    gstin = _gstin(pan)
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            uuid.uuid4(), source=ExporterSource.SALES, name="No PAN Co", country="IN",
            gstins=[gstin],
        )
    payload = _package(pan)
    payload["exporter"]["iec"] = None
    # RXIL's PAN is new, but an existing company with no PAN holds an IEC it sends.
    iec = uuid.uuid4().hex[:10].upper()
    async with db_services.AsyncSessionLocal() as db:
        await ExporterProfileService(db).create_or_get_profile(
            uuid.uuid4(), source=ExporterSource.SALES, name="IEC Holder", country="IN", iec=iec
        )
    payload["exporter"]["iec"] = iec
    with pytest.raises(IntakeNeedsReviewError) as refused:
        await _ingest(payload)
    assert refused.value.extensions["reasons"][0]["code"] == "POSSIBLE_DUPLICATE"
    assert await _companies_with_pan(pan) == 0  # nothing created


@pytest.mark.parametrize(
    "change, code",
    [
        (lambda p: p["exporter"].update(pan="ABCDE12345"), "INVALID_PAN"),
        (lambda p: p["exporter"].update(gstins=[_gstin(_pan())]), "GSTIN_PAN_MISMATCH"),
        (lambda p: p["exporter"].pop("legal_name"), "MISSING_NAME"),
        (lambda p: p["qualification"]["criteria"][0].update(criterion="credit_score"),
         "UNKNOWN_CRITERION"),
        (lambda p: p["qualification"]["criteria"][0].update(result="MAYBE"), "INVALID_RESULT"),
        (lambda p: p.pop("qualification"), "MISSING_QUALIFICATION"),
    ],
)
async def test_an_unreadable_package_is_refused_with_every_reason(change, code):
    payload = _package()
    change(payload)
    with pytest.raises(PartnerPackageInvalidError) as refused:
        parse_rxil_company_package(payload)
    assert code in {r["code"] for r in refused.value.extensions["reasons"]}


async def test_a_package_without_a_tax_identifier_is_refused():
    payload = _package()
    payload["exporter"].pop("pan")
    payload["exporter"]["gstins"] = []
    with pytest.raises(PartnerPackageInvalidError):
        await _ingest(payload)


def _not_qualified(payload: dict) -> None:
    payload["qualification"]["decision"] = "NOT_QUALIFIED"


def _confidence_on_a_manual_result(payload: dict) -> None:
    payload["qualification"]["criteria"][0]["method"] = "MANUAL"


def _confidence_above_one(payload: dict) -> None:
    payload["qualification"]["criteria"][0]["confidence"] = 1.5


@pytest.mark.parametrize(
    "change",
    [_not_qualified, _confidence_on_a_manual_result, _confidence_above_one],
)
async def test_a_refused_decision_creates_no_company(change):
    """The package reads, but its decision breaks the qualification rules.
    The company is created in its own commit before the decision is recorded,
    so the decision is checked first: nothing is left behind — in particular
    no RXIL company stranded as a LEAD with no qualification."""
    from app.shared.exceptions import ValidationError

    payload = _package()
    change(payload)
    with pytest.raises(ValidationError):
        await _ingest(payload)
    assert await _companies_with_pan(payload["exporter"]["pan"]) == 0


async def test_a_refused_decision_leaves_a_matched_company_as_it_was():
    pan = _pan()
    async with db_services.AsyncSessionLocal() as db:
        existing, _ = await ExporterProfileService(db).create_or_get_profile(
            uuid.uuid4(), source=ExporterSource.SALES, name="Already here", country="IN", pan=pan
        )
    before = await _counts(existing.customer_id)
    payload = _package(pan)
    _not_qualified(payload)
    from app.shared.exceptions import ValidationError

    with pytest.raises(ValidationError):
        await _ingest(payload)
    company = await _company(existing.customer_id)
    assert (company.journey, company.qualification) == (
        ExporterJourney.LEAD, QualificationState.NOT_YET_REVIEWED,
    )
    assert await _counts(existing.customer_id) == before


# ── Isolation and dependencies ────────────────────────────────────────────────


async def test_the_parser_is_pure_and_returns_the_crm_contract():
    """No database, no session: the package becomes the CRM's own shape."""
    payload = _package(package_id="RXIL-XYZ")
    intake = parse_rxil_company_package(payload)
    assert isinstance(intake, PartnerCompanyIntake)
    assert intake.source is QualificationSource.RXIL
    assert intake.external_reference == "RXIL-XYZ"
    assert intake.identity.pan == payload["exporter"]["pan"]
    assert all(isinstance(r, ResultEntry) for r in intake.qualification.results)


def _imports(relative: str) -> set[str]:
    tree = ast.parse((MODULE / relative).read_text(encoding="utf-8"))
    return {
        node.module for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }


@pytest.mark.parametrize(
    "relative",
    [
        "application/company_intake_service.py",
        "application/company_matching.py",
        "application/qualification_service.py",
        "domain/company_intake.py",
    ],
)
async def test_nothing_past_the_adapter_knows_rxil_or_the_legacy_tables(relative: str):
    imported = _imports(relative)
    assert not any("rxil" in m for m in imported)
    assert not any("onboarding_request" in m or "screening" in m for m in imported)
    source = (MODULE / relative).read_text(encoding="utf-8")
    assert "background_check" not in source


async def test_intake_writes_nothing_to_onboarding_request():
    result = await _ingest(_package())
    async with db_services.AsyncSessionLocal() as db:
        rows = await db.scalar(
            select(func.count()).select_from(OnboardingRequest)
            .where(OnboardingRequest.customer_id == result.customer_id)
        )
    assert rows == 0


# ── Through the API ───────────────────────────────────────────────────────────


async def test_the_api_takes_the_actor_from_the_session_not_the_package(client: AsyncClient):
    user_id, token = await user_with_role(client, UserRole.ADMIN)
    payload = _package()
    payload["exporter"]["recorded_by"] = "someone-else"
    payload["qualification"]["decided_by"] = "someone-else"
    resp = await client.post(
        f"{BASE}/rxil/company-intake", json=payload, headers=auth_header(token)
    )
    assert resp.status_code == 201, resp.text
    customer_id = resp.json()["customer_id"]
    qualification = await client.get(
        f"{BASE}/exporters/{customer_id}/qualification", headers=auth_header(token)
    )
    body = qualification.json()
    assert {r["recorded_by"] for r in body["results"]} == {str(user_id)}
    assert body["outcomes"][0]["decided_by"] is None
    assert (body["state"], body["journey"]) == ("QUALIFIED", "PROSPECT")


@pytest.mark.parametrize(
    "role", [UserRole.DEVELOPER, UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.API_USER]
)
async def test_only_an_admin_can_take_in_a_company(client: AsyncClient, role: UserRole):
    """Intake records a decision as RXIL's — source, method and confidence the
    manual routes never let a person set — so only ADMIN may submit one by
    hand, and nothing is created for anyone else."""
    _, token = await user_with_role(client, role)
    payload = _package()
    resp = await client.post(
        f"{BASE}/rxil/company-intake", json=payload, headers=auth_header(token)
    )
    assert resp.status_code == 403
    assert await _companies_with_pan(payload["exporter"]["pan"]) == 0


async def test_an_invalid_package_is_a_422_listing_reasons(client: AsyncClient):
    _, token = await user_with_role(client, UserRole.ADMIN)
    payload = _package()
    payload["exporter"]["pan"] = "BAD"
    resp = await client.post(
        f"{BASE}/rxil/company-intake", json=payload, headers=auth_header(token)
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "PARTNER_PACKAGE_INVALID"
