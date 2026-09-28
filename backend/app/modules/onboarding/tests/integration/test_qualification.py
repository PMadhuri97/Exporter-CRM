"""Qualification — criteria, results, outcomes, re-review (L2-09, L2-10).

Criteria are global settings and append-only, so these tests never version
the seeded criteria (that would change every other test's suggestion). Tests
that exercise versioning use their own throwaway keys, created not required
and left inactive, so they cannot affect anything else.

Database-level rules are checked with direct SQL (migration register §2);
everything else through the service or the API, as a person would.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import psycopg2
import psycopg2.errors
import pytest
from httpx import AsyncClient

from app.modules.onboarding.application.history_service import HistoryService
from app.modules.onboarding.application.qualification_service import (
    QUALIFICATION_RESULT_EVENT,
    QualificationService,
)
from app.modules.onboarding.domain.entities.exporter_enums import ExporterJourney
from app.modules.onboarding.domain.entities.qualification_enums import (
    CriterionKind,
    CriterionResultValue,
    DecidedByKind,
    QualificationOutcomeValue,
    QualificationSource,
    QualificationState,
)
from app.modules.onboarding.domain.qualification_views import (
    CriterionDefinition,
    EvidenceRef,
    ResultEntry,
)
from app.modules.onboarding.exceptions import (
    QualificationClosedError,
    QualificationCriterionChangedError,
    QualificationCriterionExistsError,
)
from app.modules.onboarding.infrastructure.repositories.qualification_repository import (
    QualificationRepository,
)
from app.modules.onboarding.tests.fixtures.auth import auth_header, user_with_role
from app.modules.onboarding.tests.fixtures.companies import insert_company, make_company
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"
REQUIRED = ("revenue", "years_in_business", "export_history", "export_licence")
Q = QualificationOutcomeValue


def _connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


def _pass(key: str, **extra) -> ResultEntry:
    return ResultEntry(
        criterion_key=key,
        result=CriterionResultValue.PASS,
        evidence_note=f"checked {key}",
        **extra,
    )


def _fail(key: str) -> ResultEntry:
    return ResultEntry(
        criterion_key=key, result=CriterionResultValue.FAIL, evidence_note=f"checked {key}"
    )


async def _results(customer_id, entries, **kwargs):
    async with db_services.AsyncSessionLocal() as db:
        return await QualificationService(db).record_results(
            customer_id, entries, actor_id=kwargs.pop("actor_id", "rm-1"), **kwargs
        )


async def _outcome(customer_id, outcome, **kwargs):
    async with db_services.AsyncSessionLocal() as db:
        return await QualificationService(db).record_outcome(
            customer_id, outcome, actor_id=kwargs.pop("actor_id", "rm-1"), **kwargs
        )


async def _view(customer_id):
    async with db_services.AsyncSessionLocal() as db:
        return await QualificationService(db).get_qualification(customer_id)


async def _history(customer_id, dimension):
    async with db_services.AsyncSessionLocal() as db:
        rows, _ = await HistoryService(db).list_for_company(
            customer_id, dimension=dimension, limit=100
        )
    return list(rows)


def _throwaway_key() -> str:
    return f"test_{uuid.uuid4().hex[:12]}"


@pytest.fixture(scope="module")
async def users(client: AsyncClient) -> dict[UserRole, tuple[str, str]]:
    return {role: await user_with_role(client, role) for role in UserRole}


# ── Criteria: settings, versioned, ADMIN-managed ──────────────────────────────


async def test_the_seven_initial_criteria_are_seeded_as_settings():
    async with db_services.AsyncSessionLocal() as db:
        versions = {
            c.key: c
            for c in await QualificationService(db).list_criteria()
            if not c.key.startswith("test_")
        }
    assert set(versions) >= {
        "revenue", "years_in_business", "export_history", "export_licence",
        "industry", "geography", "deal_size",
    }
    revenue = versions["revenue"]
    assert (revenue.kind, revenue.comparison.value, revenue.threshold, revenue.unit) == (
        CriterionKind.NUMBER_THRESHOLD, "AT_LEAST", Decimal("100000000.0000"), "USD",
    )
    assert versions["industry"].allowed_values
    assert all(versions[key].required for key in REQUIRED)


async def test_a_new_version_leaves_the_old_one_exactly_as_it_was():
    key = _throwaway_key()
    async with db_services.AsyncSessionLocal() as db:
        v1 = await QualificationService(db).create_criterion(
            key,
            CriterionDefinition(label="Throwaway", kind=CriterionKind.YES_NO, required=False),
            actor_id="admin-1",
        )
    v1_snapshot = (v1.id, v1.label, v1.kind, v1.required, v1.active, v1.created_at)

    async with db_services.AsyncSessionLocal() as db:
        v2 = await QualificationService(db).add_version(
            key,
            CriterionDefinition(
                label="Throwaway, renamed", kind=CriterionKind.YES_NO, required=False,
                active=False,
            ),
            actor_id="admin-2",
        )
    assert (v2.version, v2.active, v2.created_by) == (2, False, "admin-2")

    async with db_services.AsyncSessionLocal() as db:
        service = QualificationService(db)
        versions = await service.list_versions(key)
        current = {c.key: c for c in await service.list_criteria()}
    assert [v.version for v in versions] == [1, 2]
    first = versions[0]
    assert (first.id, first.label, first.kind, first.required, first.active, first.created_at) == (
        v1_snapshot
    )
    assert current[key].version == 2


def _inactive_yes_no(label: str) -> CriterionDefinition:
    return CriterionDefinition(label=label, kind=CriterionKind.YES_NO, required=False, active=False)


async def test_two_admins_creating_one_key_get_a_409_not_a_500(monkeypatch):
    """The second ADMIN read "no such key" before the first one's insert
    committed; the insert then collides on (key, version). That is the
    "already exists" refusal, not an unhandled IntegrityError."""
    key = _throwaway_key()
    async with db_services.AsyncSessionLocal() as db:
        await QualificationService(db).create_criterion(
            key, _inactive_yes_no("First"), actor_id="admin-1"
        )

    async def not_there_yet(self, key):  # the second ADMIN's stale read
        return None

    monkeypatch.setattr(QualificationRepository, "latest_version", not_there_yet)
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(QualificationCriterionExistsError):
            await QualificationService(db).create_criterion(
                key, _inactive_yes_no("Second"), actor_id="admin-2"
            )


async def test_two_admins_versioning_at_once_get_a_409_and_nothing_is_saved(monkeypatch):
    """Both read version 1 as current; the first adds version 2. The second,
    made against a version that is no longer current, is refused — not retried
    as version 3, and not a 500."""
    key = _throwaway_key()
    async with db_services.AsyncSessionLocal() as db:
        v1 = await QualificationService(db).create_criterion(
            key, _inactive_yes_no("Original"), actor_id="admin-1"
        )
    async with db_services.AsyncSessionLocal() as db:
        await QualificationService(db).add_version(
            key, _inactive_yes_no("First change"), actor_id="admin-1"
        )

    async def still_version_one(self, key):  # the second ADMIN's stale read
        return v1

    monkeypatch.setattr(QualificationRepository, "latest_version", still_version_one)
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(QualificationCriterionChangedError):
            await QualificationService(db).add_version(
                key, _inactive_yes_no("Second change"), actor_id="admin-2"
            )
    monkeypatch.undo()

    async with db_services.AsyncSessionLocal() as db:
        versions = await QualificationService(db).list_versions(key)
    assert [(v.version, v.label) for v in versions] == [(1, "Original"), (2, "First change")]


async def test_the_database_refuses_to_change_or_delete_a_criterion_version():
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for statement in (
                "UPDATE onboarding.qualification_criterion SET threshold = 1 WHERE key = 'revenue'",
                "DELETE FROM onboarding.qualification_criterion WHERE key = 'revenue'",
            ):
                with pytest.raises(psycopg2.errors.RaiseException):
                    cur.execute(statement)
                conn.rollback()
    finally:
        conn.close()


@pytest.mark.parametrize(
    "definition",
    [
        {"label": "X", "kind": "NUMBER_THRESHOLD", "required": False},  # no threshold
        {"label": "X", "kind": "YES_NO", "required": False, "threshold": 5},
        {"label": "X", "kind": "ALLOWED_VALUES", "required": False, "allowed_values": []},
        {"label": "X", "kind": "ALLOWED_VALUES", "required": False, "allowed_values": ["a", "a"]},
        {"label": " ", "kind": "YES_NO", "required": False},
    ],
)
async def test_a_criterion_of_the_wrong_shape_is_refused(
    client: AsyncClient, users, definition: dict
):
    _, token = users[UserRole.ADMIN]
    resp = await client.post(
        f"{BASE}/qualification/criteria",
        json={"key": _throwaway_key(), **definition},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize(
    "role", [UserRole.OPERATIONS, UserRole.COMPLIANCE, UserRole.DEVELOPER, UserRole.API_USER]
)
async def test_only_admin_manages_criteria(client: AsyncClient, users, role: UserRole):
    _, token = users[role]
    created = await client.post(
        f"{BASE}/qualification/criteria",
        json={"key": _throwaway_key(), "label": "X", "kind": "YES_NO", "required": False},
        headers=auth_header(token),
    )
    versioned = await client.post(
        f"{BASE}/qualification/criteria/revenue/versions",
        json={"label": "X", "kind": "YES_NO", "required": False},
        headers=auth_header(token),
    )
    assert (created.status_code, versioned.status_code) == (403, 403)


async def test_admin_creates_and_versions_through_the_api(client: AsyncClient, users):
    admin_id, token = users[UserRole.ADMIN]
    key = _throwaway_key()
    created = await client.post(
        f"{BASE}/qualification/criteria",
        json={"key": key, "label": "Throwaway", "kind": "NUMBER_THRESHOLD", "required": False,
              "comparison": "AT_LEAST", "threshold": 10, "unit": "USD"},
        headers=auth_header(token),
    )
    assert created.status_code == 201, created.text
    assert (created.json()["version"], created.json()["created_by"]) == (1, str(admin_id))

    again = await client.post(
        f"{BASE}/qualification/criteria",
        json={"key": key, "label": "Dup", "kind": "YES_NO", "required": False},
        headers=auth_header(token),
    )
    assert again.status_code == 409

    versioned = await client.post(
        f"{BASE}/qualification/criteria/{key}/versions",
        json={"label": "Throwaway", "kind": "NUMBER_THRESHOLD", "required": False,
              "comparison": "AT_LEAST", "threshold": 20, "unit": "USD", "active": False},
        headers=auth_header(token),
    )
    assert versioned.status_code == 201, versioned.text
    history = await client.get(
        f"{BASE}/qualification/criteria/{key}/versions",
        headers=auth_header(users[UserRole.DEVELOPER][1]),
    )
    assert [(c["version"], c["threshold"]) for c in history.json()["criteria"]] == [
        (1, 10.0), (2, 20.0),
    ]


# ── Results: append-only evidence ─────────────────────────────────────────────


async def test_a_result_keeps_everything_it_was_recorded_with():
    customer_id = await make_company()
    [row] = await _results(
        customer_id,
        [
            ResultEntry(
                criterion_key="revenue",
                result=CriterionResultValue.PASS,
                observed_value="120000000 USD",
                evidence_note="FY25 audited accounts",
                evidence_refs=(EvidenceRef(type="url", ref="https://example.com/fy25.pdf"),),
                reason="Comfortably above threshold",
            )
        ],
        actor_id="rm-42",
    )
    assert row.criterion.key == "revenue"
    assert row.criterion.version >= 1
    assert (row.result, row.source, row.decided_by_kind) == (
        CriterionResultValue.PASS, QualificationSource.MANUAL, DecidedByKind.MANUAL,
    )
    assert row.evidence_note == "FY25 audited accounts"
    assert row.evidence_refs == [{"type": "url", "ref": "https://example.com/fy25.pdf"}]
    assert row.reason == "Comfortably above threshold"
    assert row.recorded_by == "rm-42"
    assert row.recorded_at is not None
    assert row.confidence is None


async def test_an_automated_result_carries_its_confidence():
    customer_id = await make_company()
    [row] = await _results(
        customer_id,
        [_pass("years_in_business", confidence=Decimal("0.875"))],
        actor_id=None,
        source=QualificationSource.AUTOMATED,
        decided_by_kind=DecidedByKind.AUTOMATED,
    )
    assert (row.source, row.decided_by_kind, row.confidence) == (
        QualificationSource.AUTOMATED, DecidedByKind.AUTOMATED, Decimal("0.875"),
    )
    assert row.recorded_by is None


@pytest.mark.parametrize(
    "entry, kwargs",
    [
        (ResultEntry(criterion_key="revenue", result=CriterionResultValue.PASS), {}),  # evidence
        (_pass("revenue", confidence=Decimal("0.5")), {}),  # manual cannot have confidence
        (
            _pass("revenue", confidence=Decimal("1.5")),
            {"decided_by_kind": DecidedByKind.AUTOMATED},
        ),
        (_pass("no_such_criterion"), {}),
        (
            ResultEntry(
                criterion_key="revenue", result=CriterionResultValue.FAIL,
                evidence_refs=(EvidenceRef(type="fax", ref="x"),),
            ),
            {},
        ),
    ],
)
async def test_a_bad_result_is_refused_and_writes_nothing(entry, kwargs):
    customer_id = await make_company()
    with pytest.raises(ValidationError):
        await _results(customer_id, [entry], **kwargs)
    assert (await _view(customer_id)).results == ()
    assert await _history(customer_id, "qualification") == []


async def test_an_unknown_result_needs_no_evidence():
    customer_id = await make_company()
    [row] = await _results(
        customer_id,
        [ResultEntry(criterion_key="deal_size", result=CriterionResultValue.UNKNOWN)],
    )
    assert row.result is CriterionResultValue.UNKNOWN


async def test_rechecking_adds_a_result_and_the_first_is_untouched():
    customer_id = await make_company()
    [first] = await _results(customer_id, [_fail("revenue")])
    first_snapshot = (first.id, first.result, first.evidence_note, first.recorded_at)
    [second] = await _results(customer_id, [_pass("revenue")])

    view = await _view(customer_id)
    assert [r.id for r in view.results] == [second.id, first.id]  # newest first
    kept = next(r for r in view.results if r.id == first.id)
    assert (kept.id, kept.result, kept.evidence_note, kept.recorded_at) == first_snapshot
    revenue = next(s for s in view.standings if s.criterion.key == "revenue")
    assert revenue.latest_result.id == second.id


async def test_the_database_refuses_to_change_or_delete_a_result():
    customer_id = await make_company()
    [row] = await _results(customer_id, [_pass("revenue")])
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for statement in (
                "UPDATE onboarding.qualification_result SET result = 'FAIL' WHERE id = %s",
                "DELETE FROM onboarding.qualification_result WHERE id = %s",
            ):
                with pytest.raises(psycopg2.errors.RaiseException):
                    cur.execute(statement, (str(row.id),))
                conn.rollback()
    finally:
        conn.close()


@pytest.mark.parametrize(
    "columns, values",
    [
        ("result, source, decided_by_kind", "'PASS', 'MANUAL', 'MANUAL'"),  # no evidence
        (
            "result, source, decided_by_kind, evidence_note, confidence",
            "'PASS', 'MANUAL', 'MANUAL', 'x', 0.5",  # manual with confidence
        ),
    ],
)
async def test_the_database_enforces_the_result_rules(columns: str, values: str):
    conn = _connect()
    try:
        with conn.cursor() as cur:
            company_id = insert_company(cur)
            cur.execute(
                "SELECT id FROM onboarding.qualification_criterion "
                "WHERE key = 'revenue' ORDER BY version DESC LIMIT 1"
            )
            (criterion_id,) = cur.fetchone()
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    f"INSERT INTO onboarding.qualification_result "
                    f"(id, customer_id, criterion_id, {columns}) "
                    f"VALUES (%s, %s, %s, {values})",
                    (str(uuid.uuid4()), str(company_id), str(criterion_id)),
                )
    finally:
        conn.rollback()
        conn.close()


async def test_each_result_is_in_the_history_log():
    customer_id = await make_company()
    rows = await _results(customer_id, [_pass("revenue"), _fail("export_history")])
    history = await _history(customer_id, "qualification")
    assert {h.to_status for h in history} == {"PASS", "FAIL"}
    for h in history:
        assert h.event_type == QUALIFICATION_RESULT_EVENT
        assert h.actor_id == "rm-1"
        assert h.event_metadata["result_id"] in {str(r.id) for r in rows}
        assert h.event_metadata["criterion_key"] in {"revenue", "export_history"}


async def test_results_never_move_the_gauge():
    customer_id = await make_company()
    await _results(customer_id, [_pass(key) for key in REQUIRED])
    view = await _view(customer_id)
    assert view.state is QualificationState.NOT_YET_REVIEWED
    assert view.suggested_outcome is Q.QUALIFIED  # suggested, not decided


# ── Suggestion versus decision ────────────────────────────────────────────────


async def test_the_suggestion_is_qualified_only_when_every_required_criterion_passes():
    customer_id = await make_company()
    await _results(customer_id, [_pass(key) for key in REQUIRED[:-1]])
    assert (await _view(customer_id)).suggested_outcome is Q.NOT_QUALIFIED
    await _results(customer_id, [_pass(REQUIRED[-1])])
    assert (await _view(customer_id)).suggested_outcome is Q.QUALIFIED
    await _results(customer_id, [_fail("revenue")])
    assert (await _view(customer_id)).suggested_outcome is Q.NOT_QUALIFIED


async def test_a_person_may_decide_against_the_suggestion_and_both_are_kept():
    customer_id = await make_company()
    await _results(customer_id, [_fail("revenue")])
    outcome = await _outcome(customer_id, Q.QUALIFIED, note="Revenue restated upward")
    assert outcome.outcome is Q.QUALIFIED
    assert outcome.suggested_outcome is Q.NOT_QUALIFIED


async def test_the_outcome_records_the_results_it_rested_on():
    customer_id = await make_company()
    rows = await _results(customer_id, [_fail("revenue"), _pass("export_history")])
    outcome = await _outcome(customer_id, Q.NOT_QUALIFIED, reason_codes=["revenue_below_threshold"])
    assert set(outcome.result_ids) == {str(r.id) for r in rows}

    # A later result does not change what that decision rested on.
    [later] = await _results(customer_id, [_pass("revenue")])
    [kept] = [o for o in (await _view(customer_id)).outcomes if o.id == outcome.id]
    assert set(kept.result_ids) == {str(r.id) for r in rows}
    assert str(later.id) not in kept.result_ids


# ── Outcomes and the journey ──────────────────────────────────────────────────


async def test_every_new_company_starts_not_yet_reviewed_and_a_lead():
    customer_id = await make_company()
    view = await _view(customer_id)
    assert (view.state, view.journey) == (QualificationState.NOT_YET_REVIEWED, ExporterJourney.LEAD)
    assert view.outcomes == ()


async def test_qualified_moves_a_lead_to_prospect_and_no_further():
    customer_id = await make_company()
    await _results(customer_id, [_pass(key) for key in REQUIRED])
    await _outcome(customer_id, Q.QUALIFIED, actor_id="rm-7")

    view = await _view(customer_id)
    assert view.state is QualificationState.QUALIFIED
    assert view.journey is ExporterJourney.PROSPECT  # never CUSTOMER from qualification

    [journey_row] = await _history(customer_id, "journey")
    assert (journey_row.from_status, journey_row.to_status) == ("LEAD", "PROSPECT")
    assert journey_row.event_type == "lifecycle_transition"  # history contract §3
    assert journey_row.event_metadata["terminal"] is False
    assert journey_row.actor_id == "rm-7"


async def test_not_qualified_needs_a_reason_code_and_stays_a_lead():
    customer_id = await make_company()
    with pytest.raises(ValidationError):
        await _outcome(customer_id, Q.NOT_QUALIFIED)
    with pytest.raises(ValidationError):
        await _outcome(customer_id, Q.NOT_QUALIFIED, reason_codes=["not_a_real_code"])
    with pytest.raises(ValidationError):
        await _outcome(customer_id, Q.NOT_QUALIFIED, reason_codes=["other"])  # needs a note
    assert (await _view(customer_id)).outcomes == ()

    outcome = await _outcome(
        customer_id, Q.NOT_QUALIFIED,
        reason_codes=["revenue_below_threshold"], note="Revenue is $40M",
    )
    view = await _view(customer_id)
    assert (view.state, view.journey) == (QualificationState.NOT_QUALIFIED, ExporterJourney.LEAD)
    assert outcome.reason_codes == ["revenue_below_threshold"]

    [row] = await _history(customer_id, "qualification")
    assert (row.from_status, row.to_status) == ("NOT_YET_REVIEWED", "NOT_QUALIFIED")
    assert row.reason == "Revenue is $40M"
    assert row.event_metadata["reason_codes"] == ["revenue_below_threshold"]
    assert await _history(customer_id, "journey") == []


async def test_a_re_review_adds_new_records_and_keeps_the_old_ones():
    customer_id = await make_company()
    [old_result] = await _results(customer_id, [_fail("revenue")])
    first = await _outcome(customer_id, Q.NOT_QUALIFIED, reason_codes=["revenue_below_threshold"])
    first_snapshot = (first.id, first.outcome, first.reason_codes, first.decided_at)

    new_results = await _results(customer_id, [_pass(key) for key in REQUIRED])
    second = await _outcome(customer_id, Q.QUALIFIED, note="Re-review after FY26 accounts")
    assert second.supersedes_outcome_id == first.id
    assert set(second.result_ids) == {str(r.id) for r in new_results}

    view = await _view(customer_id)
    assert [o.id for o in view.outcomes] == [second.id, first.id]
    kept = next(o for o in view.outcomes if o.id == first.id)
    assert (kept.id, kept.outcome, kept.reason_codes, kept.decided_at) == first_snapshot
    assert old_result.id in {r.id for r in view.results}
    assert (view.state, view.journey) == (QualificationState.QUALIFIED, ExporterJourney.PROSPECT)

    moves = [
        (h.from_status, h.to_status)
        for h in await _history(customer_id, "qualification")
        if h.event_type != QUALIFICATION_RESULT_EVENT
    ]
    assert set(moves) == {("NOT_YET_REVIEWED", "NOT_QUALIFIED"), ("NOT_QUALIFIED", "QUALIFIED")}


async def test_qualified_is_final():
    customer_id = await make_company()
    await _outcome(customer_id, Q.QUALIFIED)
    with pytest.raises(QualificationClosedError):
        await _outcome(customer_id, Q.NOT_QUALIFIED, reason_codes=["other"], note="x")
    with pytest.raises(QualificationClosedError):
        await _results(customer_id, [_pass("revenue")])


async def test_the_outcome_gauge_and_journey_commit_together_or_not_at_all(monkeypatch):
    """If the journey's history row cannot be written, the outcome, the gauge
    and the journey all roll back."""
    customer_id = await make_company()
    real_record = HistoryService.record

    async def failing_journey_record(self, *args, **kwargs):
        if kwargs.get("dimension") == "journey":
            raise RuntimeError("history write failed")
        return await real_record(self, *args, **kwargs)

    monkeypatch.setattr(HistoryService, "record", failing_journey_record)
    with pytest.raises(RuntimeError):
        await _outcome(customer_id, Q.QUALIFIED)
    monkeypatch.undo()

    view = await _view(customer_id)
    assert (view.state, view.journey, view.outcomes) == (
        QualificationState.NOT_YET_REVIEWED, ExporterJourney.LEAD, (),
    )
    assert await _history(customer_id, "qualification") == []


async def test_the_database_keeps_one_outcome_chain_per_company():
    """No second first outcome, and no outcome superseded twice."""
    customer_id = await make_company()
    first = await _outcome(customer_id, Q.NOT_QUALIFIED, reason_codes=["other"], note="x")
    insert = (
        "INSERT INTO onboarding.qualification_outcome "
        "(id, customer_id, outcome, reason_codes, suggested_outcome, source, decided_by_kind, "
        " supersedes_outcome_id) "
        "VALUES (%s, %s, 'NOT_QUALIFIED', '[\"other\"]', 'NOT_QUALIFIED', 'MANUAL', 'MANUAL', %s)"
    )
    conn = _connect()
    try:
        with conn.cursor() as cur:
            with pytest.raises(psycopg2.errors.UniqueViolation):
                cur.execute(insert, (str(uuid.uuid4()), str(customer_id), None))
            conn.rollback()
            cur.execute(insert, (str(uuid.uuid4()), str(customer_id), str(first.id)))
            with pytest.raises(psycopg2.errors.UniqueViolation):
                cur.execute(insert, (str(uuid.uuid4()), str(customer_id), str(first.id)))
    finally:
        conn.rollback()
        conn.close()


async def test_the_database_refuses_not_qualified_without_a_reason_code():
    conn = _connect()
    try:
        with conn.cursor() as cur:
            company_id = insert_company(cur)
            with pytest.raises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "INSERT INTO onboarding.qualification_outcome "
                    "(id, customer_id, outcome, suggested_outcome, source, decided_by_kind) "
                    "VALUES (%s, %s, 'NOT_QUALIFIED', 'NOT_QUALIFIED', 'MANUAL', 'MANUAL')",
                    (str(uuid.uuid4()), str(company_id)),
                )
    finally:
        conn.rollback()
        conn.close()


async def test_qualification_is_not_the_screening_checklist():
    """Separate tables, separate values."""
    screening = {"NEEDS_REVIEW", "PASSED", "FAILED", "EXEMPT"}
    assert not screening & {v.value for v in CriterionResultValue}
    assert not screening & {v.value for v in QualificationState}


# ── Through the API ───────────────────────────────────────────────────────────


async def test_staff_record_results_and_an_outcome_as_themselves(client: AsyncClient, users):
    user_id, token = users[UserRole.OPERATIONS]
    customer_id = await make_company()
    results = await client.post(
        f"{BASE}/exporters/{customer_id}/qualification/results",
        json={"results": [
            {"criterion_key": key, "result": "PASS", "evidence_note": "checked"}
            for key in REQUIRED
        ]},
        headers=auth_header(token),
    )
    assert results.status_code == 201, results.text
    body = results.json()
    assert body["suggested_outcome"] == "QUALIFIED"
    assert body["state"] == "NOT_YET_REVIEWED"
    assert {r["recorded_by"] for r in body["results"]} == {str(user_id)}
    assert {r["source"] for r in body["results"]} == {"MANUAL"}

    outcome = await client.post(
        f"{BASE}/exporters/{customer_id}/qualification/outcome",
        json={"outcome": "QUALIFIED"},
        headers=auth_header(token),
    )
    assert outcome.status_code == 201, outcome.text
    decided = outcome.json()
    assert (decided["state"], decided["journey"]) == ("QUALIFIED", "PROSPECT")
    assert decided["outcomes"][0]["decided_by"] == str(user_id)

    detail = await client.get(f"{BASE}/exporters/{customer_id}", headers=auth_header(token))
    assert (detail.json()["journey"], detail.json()["qualification"]) == ("PROSPECT", "QUALIFIED")


@pytest.mark.parametrize(
    "extra",
    [
        {"recorded_by": "someone-else"},
        {"source": "RXIL"},
        {"decided_by_kind": "AUTOMATED"},
        {"confidence": 0.9},
    ],
)
async def test_a_request_cannot_claim_who_or_what_recorded_a_result(
    client: AsyncClient, users, extra: dict
):
    _, token = users[UserRole.OPERATIONS]
    customer_id = await make_company()
    resp = await client.post(
        f"{BASE}/exporters/{customer_id}/qualification/results",
        json={"results": [{"criterion_key": "revenue", "result": "UNKNOWN", **extra}]},
        headers=auth_header(token),
    )
    assert resp.status_code == 422


async def test_an_outcome_request_cannot_name_its_decider(client: AsyncClient, users):
    _, token = users[UserRole.OPERATIONS]
    customer_id = await make_company()
    resp = await client.post(
        f"{BASE}/exporters/{customer_id}/qualification/outcome",
        json={"outcome": "QUALIFIED", "decided_by": "someone-else"},
        headers=auth_header(token),
    )
    assert resp.status_code == 422


async def test_a_not_qualified_outcome_without_a_reason_is_a_422(client: AsyncClient, users):
    _, token = users[UserRole.COMPLIANCE]
    customer_id = await make_company()
    resp = await client.post(
        f"{BASE}/exporters/{customer_id}/qualification/outcome",
        json={"outcome": "NOT_QUALIFIED"},
        headers=auth_header(token),
    )
    assert resp.status_code == 422, resp.text


async def test_a_developer_reads_but_cannot_record(client: AsyncClient, users):
    _, token = users[UserRole.DEVELOPER]
    customer_id = await make_company()
    read = await client.get(
        f"{BASE}/exporters/{customer_id}/qualification", headers=auth_header(token)
    )
    assert read.status_code == 200
    write = await client.post(
        f"{BASE}/exporters/{customer_id}/qualification/outcome",
        json={"outcome": "QUALIFIED"},
        headers=auth_header(token),
    )
    assert write.status_code == 403


async def test_qualification_for_an_unknown_company_is_a_404(client: AsyncClient, users):
    _, token = users[UserRole.OPERATIONS]
    resp = await client.get(
        f"{BASE}/exporters/{uuid.uuid4()}/qualification", headers=auth_header(token)
    )
    assert resp.status_code == 404


async def test_the_company_list_filters_by_journey_and_qualification(client: AsyncClient, users):
    _, token = users[UserRole.OPERATIONS]
    customer_id = await make_company()
    await _outcome(customer_id, Q.QUALIFIED)
    resp = await client.get(
        f"{BASE}/exporters",
        params={"journey": "PROSPECT", "qualification": "QUALIFIED", "limit": 200},
        headers=auth_header(token),
    )
    assert str(customer_id) in {p["customer_id"] for p in resp.json()["profiles"]}
    leads = await client.get(
        f"{BASE}/exporters", params={"journey": "LEAD", "limit": 200}, headers=auth_header(token)
    )
    assert str(customer_id) not in {p["customer_id"] for p in leads.json()["profiles"]}


async def test_the_journey_cannot_be_set_through_the_edit_route(client: AsyncClient, users):
    _, token = users[UserRole.ADMIN]
    customer_id = await make_company()
    for field, value in (("journey", "CUSTOMER"), ("qualification", "QUALIFIED")):
        resp = await client.patch(
            f"{BASE}/exporters/{customer_id}", json={field: value}, headers=auth_header(token)
        )
        assert resp.status_code == 422
