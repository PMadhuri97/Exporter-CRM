"""Check cycles — the model, the cycle-scoped seam, starting a Re-KYC / Re-KYB, and
the reads that serve them.

* ``check_cycle`` is append-only and one-numbered-per-company at the database;
* the migration's cycle-1 backfill inserts only, and leaves legacy rows untouched;
* new inputs and decisions are stamped with the current cycle;
* the background check decides on the current cycle only: a company in cycle 2 with
  no cycle-2 answers cannot be cleared, a placeholder left in cycle 1 no longer blocks,
  and the compliance facts follow the cycle;
* a new cycle starts from every allowed state, reopens a ``CLEAR`` company in the same
  transaction, is refused on ``FLAGGED``/``ON_HOLD`` and on an empty cycle, and two
  simultaneous starts make **one** cycle.
"""

from __future__ import annotations

import asyncio
import uuid

import psycopg2
import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from app.modules.onboarding.application.background_check_service import BackgroundCheckService
from app.modules.onboarding.application.compliance_facts import ComplianceFactsService
from app.modules.onboarding.domain.background_check_views import (
    CLEAR_SCREENING_ANSWERED,
    CURRENT_CLEAR_RULES,
)
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.modules.onboarding.domain.entities.check_cycle import CheckCycleKind
from app.modules.onboarding.domain.entities.orchestration_enums import VerificationType
from app.modules.onboarding.exceptions import (
    BackgroundCheckPrerequisitesUnmetError,
    CheckCycleEmptyError,
    CheckCycleNotAllowedError,
    CheckCycleRoleNotAllowedError,
)
from app.modules.onboarding.migrations import onboarding_0025_check_cycle as migration
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.modules.onboarding.tests.fixtures.companies import insert_company, make_company
from app.modules.onboarding.tests.fixtures.compliance import approve_as, record_required_checks
from app.modules.onboarding.tests.integration._compliance_support import (
    CHECKER,
    MAKER,
    answer_screening,
    clear,
    cleared_company,
    flag,
    gauge,
    inputs,
    move,
    start_cycle,
    start_review,
)
from app.modules.onboarding.tests.integration._verification_support import (
    BASE,
    exporter_result,
    history_rows,
    insert_result,
    pg,
)
from app.platform.authentication.models import UserRole
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services
from app.shared import clock
from app.shared.exceptions import ValidationError

pytestmark = pytest.mark.asyncio

_State = BackgroundCheckState


@pytest.fixture(scope="module")
async def tokens(client: AsyncClient) -> dict[UserRole, str]:
    return {role: await token_with_role(client, role) for role in UserRole}


def _cycles(cursor, company_id) -> list[tuple]:
    cursor.execute(
        "SELECT id, number, kind, reason, source, rules_version FROM onboarding.check_cycle "
        "WHERE company_id = %s ORDER BY number",
        (str(company_id),),
    )
    return cursor.fetchall()


# ── The table ────────────────────────────────────────────────────────────────


def _insert_cycle(cursor, company_id, number=1, kind="INITIAL", reason=None) -> str:
    cycle_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO onboarding.check_cycle (id, company_id, number, kind, reason, started_at, "
        " created_by, source) VALUES (%s, %s, %s, %s, %s, now(), 'sql', 'TEST')",
        (cycle_id, str(company_id), number, kind, reason),
    )
    return cycle_id


async def test_a_cycle_can_be_neither_updated_nor_deleted():
    with pg() as cursor:
        company_id = insert_company(cursor)
        cycle_id = _insert_cycle(cursor, company_id)
        with pytest.raises(psycopg2.errors.RaiseException):
            cursor.execute(
                "UPDATE onboarding.check_cycle SET reason = 'changed' WHERE id = %s", (cycle_id,)
            )
        with pytest.raises(psycopg2.errors.RaiseException):
            cursor.execute("DELETE FROM onboarding.check_cycle WHERE id = %s", (cycle_id,))


@pytest.mark.parametrize(
    ("number", "kind", "reason", "constraint"),
    [
        (0, "RE_KYC", "why", "ck_check_cycle_number_positive"),
        (1, "RE_KYC", "why", "ck_check_cycle_initial_first"),
        (2, "INITIAL", "why", "ck_check_cycle_initial_first"),
        (2, "RE_KYC", None, "ck_check_cycle_reason"),
        (2, "RE_KYC", "   ", "ck_check_cycle_reason"),
        (2, "SOMETHING", "why", "ck_check_cycle_kind"),
    ],
)
async def test_the_database_refuses_a_malformed_cycle(number, kind, reason, constraint):
    with pg() as cursor:
        company_id = insert_company(cursor)
        with pytest.raises(psycopg2.errors.CheckViolation) as caught:
            _insert_cycle(cursor, company_id, number=number, kind=kind, reason=reason)
        assert caught.value.diag.constraint_name == constraint


async def test_a_company_has_one_cycle_per_number():
    with pg() as cursor:
        company_id = insert_company(cursor)
        _insert_cycle(cursor, company_id)
        with pytest.raises(psycopg2.errors.UniqueViolation) as caught:
            _insert_cycle(cursor, company_id)
        assert caught.value.diag.constraint_name == "uq_check_cycle_company_number"


async def test_a_screening_row_or_decision_cannot_name_another_companys_cycle():
    with pg() as cursor:
        company_id, other = insert_company(cursor), insert_company(cursor)
        foreign_cycle = _insert_cycle(cursor, other)
        with pytest.raises(psycopg2.errors.ForeignKeyViolation) as caught:
            cursor.execute(
                "INSERT INTO onboarding.screening_review_item (id, customer_id, item_key, status, "
                " cycle_id) VALUES (%s, %s, 'address-physical', 'PASSED', %s)",
                (str(uuid.uuid4()), str(company_id), foreign_cycle),
            )
        assert caught.value.diag.constraint_name == "fk_screening_review_item_cycle"
        with pytest.raises(psycopg2.errors.ForeignKeyViolation) as caught:
            cursor.execute(
                "INSERT INTO onboarding.background_check_decision (id, company_id, from_value, "
                " to_value, decided_by, decided_by_kind, source, cycle_id) VALUES "
                " (%s, %s, 'NOT_STARTED', 'IN_REVIEW', 'x', 'MANUAL', 'MANUAL', %s)",
                (str(uuid.uuid4()), str(company_id), foreign_cycle),
            )
        assert caught.value.diag.constraint_name == "fk_background_check_decision_cycle"


async def test_a_results_cycle_is_frozen_once_set():
    with pg() as cursor:
        company_id = insert_company(cursor)
        first, second = _insert_cycle(cursor, company_id), _insert_cycle(
            cursor, company_id, number=2, kind="RE_KYC", reason="r"
        )
        result_id = insert_result(cursor, entity_type="EXPORTER", entity_reference=company_id)
        cursor.execute(
            "UPDATE onboarding.verification_result SET cycle_id = %s WHERE id = %s",
            (first, str(result_id)),
        )
        with pytest.raises(psycopg2.errors.RaiseException, match="immutable once set"):
            cursor.execute(
                "UPDATE onboarding.verification_result SET cycle_id = %s WHERE id = %s",
                (second, str(result_id)),
            )


async def test_the_backfill_inserts_cycle_1_at_the_earliest_input_and_touches_no_input():
    """The migration's own statement, run again on a fixture company whose inputs predate
    cycles: one cycle 1, dated at the earliest input; the inputs keep `cycle_id NULL`."""
    with pg() as cursor:
        company_id = insert_company(cursor)
        cursor.execute(
            "INSERT INTO onboarding.screening_review_item (id, customer_id, item_key, status, "
            " created_at) VALUES (%s, %s, 'website-reviewed', 'PASSED', "
            " '2026-05-01T10:00:00+00:00')",
            (str(uuid.uuid4()), str(company_id)),
        )
        # performed now(), so later than the screening answer: the answer is earliest.
        result_id = insert_result(cursor, entity_type="EXPORTER", entity_reference=company_id)
        # A company with no input gets no cycle.
        idle = insert_company(cursor)

    engine = sa.create_engine(get_settings().DATABASE_SYNC_URL)
    try:
        for _ in range(2):  # idempotent
            with engine.begin() as connection:
                connection.execute(
                    sa.text(migration.BACKFILL_INITIAL_CYCLES_SQL).bindparams(
                        actor=migration.MIGRATION_ACTOR, source_ref=migration.revision
                    )
                )
    finally:
        engine.dispose()

    with pg() as cursor:
        cycles = _cycles(cursor, company_id)
        assert [(c[1], c[2], c[4]) for c in cycles] == [(1, "INITIAL", "MIGRATION")]
        cursor.execute(
            "SELECT started_at, created_by, source_ref FROM onboarding.check_cycle "
            "WHERE company_id = %s", (str(company_id),),
        )
        started_at, created_by, source_ref = cursor.fetchone()
        assert started_at.isoformat() == "2026-05-01T10:00:00+00:00"
        assert created_by == "migration:onboarding_0025_check_cycle"
        assert source_ref == "onboarding_0025_check_cycle"
        cursor.execute(
            "SELECT count(*) FROM onboarding.screening_review_item "
            "WHERE customer_id = %s AND cycle_id IS NULL", (str(company_id),),
        )
        assert cursor.fetchone() == (1,)
        cursor.execute(
            "SELECT cycle_id FROM onboarding.verification_result WHERE id = %s", (str(result_id),)
        )
        assert cursor.fetchone() == (None,)
        assert _cycles(cursor, idle) == []


# ── New rows carry their cycle ───────────────────────────────────────────────


async def test_the_first_input_creates_cycle_1_and_everything_after_shares_it():
    company_id = await make_company()
    [answer] = await answer_screening(company_id, keys=("address-physical",))
    result = await exporter_result(company_id)
    await start_review(company_id)
    with pg() as cursor:
        cycles = _cycles(cursor, company_id)
        assert [(c[1], c[2], c[4]) for c in cycles] == [(1, "INITIAL", "FIRST_INPUT")]
        cycle_1 = uuid.UUID(cycles[0][0])
        cursor.execute(
            "SELECT cycle_id, rules_version FROM onboarding.background_check_decision "
            "WHERE company_id = %s", (str(company_id),),
        )
        [(decision_cycle, rules_version)] = cursor.fetchall()
    assert answer.cycle_id == result.cycle_id == uuid.UUID(decision_cycle) == cycle_1
    assert rules_version == CURRENT_CLEAR_RULES


async def test_a_buyer_check_has_no_cycle():
    from app.modules.onboarding.application.verification_service import VerificationService
    from app.modules.onboarding.domain.entities.orchestration_enums import (
        VerificationEntityType,
    )
    from app.modules.onboarding.tests.integration._verification_support import NOTE, deal_buyer

    _company, _deal, buyer_id = await deal_buyer()
    async with db_services.AsyncSessionLocal() as db:
        result = await VerificationService(db).trigger_verification(
            VerificationType.AML, VerificationEntityType.BUYER, buyer_id,
            payload={"status": "PASSED"}, actor_id="tester", evidence=NOTE,
        )
    assert result.cycle_id is None


# ── Starting a cycle ─────────────────────────────────────────────────────────


async def test_a_re_kyc_on_a_clear_company_reopens_it_in_the_same_transaction():
    company_id = await cleared_company(await make_company())
    started = await start_cycle(company_id, kind=CheckCycleKind.RE_KYC, reason="Annual review")

    assert (started.cycle.number, started.cycle.kind) == (2, "RE_KYC")
    assert started.cycle.rules_version == CURRENT_CLEAR_RULES
    assert started.previous_cycle.number == 1
    assert await gauge(company_id) is _State.IN_REVIEW
    reopen = started.reopen
    assert reopen is not None
    assert (reopen.from_value, reopen.to_value) == (_State.CLEAR, _State.IN_REVIEW)
    assert reopen.reason == "Re-KYC: Annual review"
    assert reopen.cycle_id == started.cycle.id
    assert reopen.evidence == ()  # the new cycle has nothing in it yet
    assert started.cycle.source_ref == str(reopen.id)

    with pg() as cursor:
        [row] = history_rows(cursor, company_id, dimension="check_cycle")
        event_type, from_value, to_value, actor, reason, _deal, details = row
        assert (event_type, from_value, to_value, actor, reason) == (
            "check_cycle_started", "1", "2", MAKER.user_id, "Annual review",
        )
        assert details["cycle_id"] == str(started.cycle.id)
        assert details["kind"] == "RE_KYC"
        assert details["reopen_decision_id"] == str(reopen.id)
        reopen_rows = [
            r for r in history_rows(cursor, company_id, dimension="background_check")
            if r[1] == "CLEAR"
        ]
        assert [r[2] for r in reopen_rows] == ["IN_REVIEW"]


@pytest.mark.parametrize("state", [_State.NOT_STARTED, _State.IN_REVIEW, _State.MORE_INFO])
async def test_a_cycle_starts_without_a_gauge_move_from(state):
    company_id = await make_company()
    await answer_screening(company_id, keys=("address-physical",))
    if state is not _State.NOT_STARTED:
        await start_review(company_id)
    if state is _State.MORE_INFO:
        await move(company_id, _State.MORE_INFO)
    started = await start_cycle(company_id, kind=CheckCycleKind.RE_KYB, reason="Ownership change")
    assert started.reopen is None
    assert started.cycle.number == 2 and started.cycle.kind == "RE_KYB"
    assert await gauge(company_id) is state


@pytest.mark.parametrize("state", [_State.FLAGGED, _State.ON_HOLD])
async def test_a_flagged_or_held_company_is_reassessed_first(state):
    company_id = await make_company()
    await answer_screening(company_id, keys=("address-physical",))
    await start_review(company_id)
    await flag(company_id)
    if state is _State.ON_HOLD:
        await flag(company_id, _State.ON_HOLD)
    with pytest.raises(CheckCycleNotAllowedError):
        await start_cycle(company_id)
    with pg() as cursor:
        assert [c[1] for c in _cycles(cursor, company_id)] == [1]


async def test_an_empty_cycle_cannot_be_followed_by_another():
    company_id = await make_company()
    with pytest.raises(CheckCycleEmptyError):
        await start_cycle(company_id)  # no input at all: cycle 1 is empty
    await answer_screening(company_id, keys=("address-physical",))
    await start_cycle(company_id)
    with pytest.raises(CheckCycleEmptyError) as caught:
        await start_cycle(company_id)  # cycle 2 has nothing in it yet
    assert caught.value.status_code == 409
    with pg() as cursor:
        assert [c[1] for c in _cycles(cursor, company_id)] == [1, 2]


async def test_only_compliance_and_admin_start_a_cycle_and_only_the_offered_kinds():
    company_id = await make_company()
    await answer_screening(company_id, keys=("address-physical",))
    with pytest.raises(CheckCycleRoleNotAllowedError):
        await start_cycle(company_id, role=UserRole.OPERATIONS)
    with pytest.raises(ValidationError):
        await start_cycle(company_id, kind=CheckCycleKind.FULL)
    with pytest.raises(ValidationError):
        await start_cycle(company_id, reason="   ")
    await start_cycle(company_id, role=UserRole.ADMIN)


async def test_two_starts_at_the_same_moment_make_one_cycle():
    company_id = await cleared_company(await make_company())

    async def attempt():
        try:
            return await start_cycle(company_id)
        except CheckCycleEmptyError as error:
            return error

    outcomes = await asyncio.gather(attempt(), attempt())
    started = [o for o in outcomes if not isinstance(o, Exception)]
    refused = [o for o in outcomes if isinstance(o, CheckCycleEmptyError)]
    assert len(started) == 1 and len(refused) == 1
    with pg() as cursor:
        assert [c[1] for c in _cycles(cursor, company_id)] == [1, 2]
        assert len(history_rows(cursor, company_id, dimension="check_cycle")) == 1


# ── The check decides on the current cycle ───────────────────────────────────


async def test_a_company_in_cycle_2_with_no_cycle_2_answers_cannot_be_cleared():
    company_id = await cleared_company(await make_company())  # 7 PASSED in cycle 1
    started = await start_cycle(company_id)

    now = await inputs(company_id)
    assert now.current_cycle_id == started.cycle.id
    assert all(item.status is None for item in now.screening_items)
    assert now.verifications == ()

    with pytest.raises(BackgroundCheckPrerequisitesUnmetError) as caught:
        await clear(company_id)
    # Rule B is scoped to the cycle too: cycle 1's KYB/AML/sanctions do not carry over.
    assert {
        CLEAR_SCREENING_ANSWERED, "kyb_passed", "aml_passed", "sanctions_passed"
    } <= set(caught.value.extensions["unmet"])

    # Answer again in cycle 2, and it clears; the earlier cycle's answers are untouched.
    answers = await answer_screening(company_id)
    assert {answer.cycle_id for answer in answers} == {started.cycle.id}
    checks = await record_required_checks(company_id)
    assert {check.cycle_id for check in checks} == {started.cycle.id}
    decision = await clear(company_id)
    assert decision.cycle_id == started.cycle.id
    assert await gauge(company_id) is _State.CLEAR


async def test_a_placeholder_left_in_cycle_1_no_longer_blocks_in_cycle_2():
    company_id = await make_company()
    await answer_screening(company_id)
    await record_required_checks(company_id)
    await start_review(company_id)
    with pg() as cursor:  # a legacy placeholder: no provider ever ran it, no cycle
        insert_result(
            cursor, entity_type="EXPORTER", entity_reference=company_id,
            status="PENDING", normalized_result={"stub": True},
        )
    with pytest.raises(BackgroundCheckPrerequisitesUnmetError):
        await clear(company_id)  # cycle 1: the placeholder blocks

    await start_cycle(company_id)
    await answer_screening(company_id)
    await record_required_checks(company_id)
    await clear(company_id)
    assert await gauge(company_id) is _State.CLEAR


async def test_the_compliance_facts_follow_the_current_cycle():
    company_id = await cleared_company(await make_company())
    await exporter_result(company_id, verification_type=VerificationType.SANCTIONS)
    await exporter_result(company_id, verification_type=VerificationType.AML, status="FAILED")

    async def facts():
        async with db_services.AsyncSessionLocal() as db:
            return await ComplianceFactsService(db).for_company(company_id, clock.now())

    before = await facts()
    assert (before.sanctions, before.aml) == ("PASSED", "FAILED")
    await start_cycle(company_id)
    after = await facts()
    assert (after.sanctions, after.aml) == ("MISSING", "MISSING")
    assert after.background_check == "IN_REVIEW" and not after.is_clear


async def test_a_legacy_row_counts_as_cycle_1():
    """A result recorded before cycles (NULL) is an input of cycle 1, and is reported
    with cycle 1's id."""
    company_id = await make_company()
    with pg() as cursor:
        legacy = insert_result(
            cursor, entity_type="EXPORTER", entity_reference=company_id, status="PASSED"
        )
    await answer_screening(company_id, keys=("address-physical",))  # creates cycle 1
    now = await inputs(company_id)
    [result] = now.verifications
    assert result.verification_result_id == legacy
    assert result.cycle_id == now.current_cycle_id is not None


# ── What is served ───────────────────────────────────────────────────────────


async def test_the_standing_serves_the_cycle_and_the_actions_this_caller_may_take(
    client: AsyncClient, tokens
):
    company_id = await cleared_company(await make_company())
    url = f"{BASE}/exporters/{company_id}/background-check"

    compliance = (await client.get(url, headers=auth_header(tokens[UserRole.COMPLIANCE]))).json()
    assert compliance["current_cycle"]["number"] == 1
    assert compliance["current_cycle"]["is_current"] is True
    assert compliance["allowed_cycle_actions"] == [
        {"kind": "RE_KYC", "reason_required": True, "reopens": True},
        {"kind": "RE_KYB", "reason_required": True, "reopens": True},
    ]
    assert compliance["compliance"]["is_clear_current"] is True

    operations = (await client.get(url, headers=auth_header(tokens[UserRole.OPERATIONS]))).json()
    assert operations["allowed_cycle_actions"] == []

    started = await client.post(
        f"{url}/cycles",
        json={"kind": "RE_KYB", "reason": "New director"},
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert started.status_code == 201, started.text
    body = started.json()
    assert body["cycle"]["number"] == 2 and body["cycle"]["kind"] == "RE_KYB"
    assert body["reopen_decision"]["reason"] == "Re-KYB: New director"
    assert body["reopen_decision"]["cycle_number"] == 2

    after = (await client.get(url, headers=auth_header(tokens[UserRole.COMPLIANCE]))).json()
    assert after["value"] == "IN_REVIEW"
    assert after["current_cycle"]["number"] == 2
    assert after["allowed_cycle_actions"] == []  # cycle 2 is still empty

    listing = await client.get(f"{url}/cycles", headers=auth_header(tokens[UserRole.OPERATIONS]))
    assert listing.status_code == 200
    cycles = listing.json()
    assert [c["number"] for c in cycles["cycles"]] == [1, 2]
    assert [c["is_current"] for c in cycles["cycles"]] == [False, True]
    assert cycles["current_cycle_id"] == body["cycle"]["id"]

    decisions = await client.get(
        f"{url}/decisions", headers=auth_header(tokens[UserRole.OPERATIONS])
    )
    assert [d["cycle_number"] for d in decisions.json()["decisions"]] == [2, 1, 1]


async def test_the_api_refuses_operations_and_an_empty_or_flagged_start(client, tokens):
    company_id = await make_company()
    url = f"{BASE}/exporters/{company_id}/background-check/cycles"
    body = {"kind": "RE_KYC", "reason": "why"}
    assert (await client.post(url, json=body, headers=auth_header(tokens[UserRole.OPERATIONS]))
            ).status_code == 403
    empty = await client.post(url, json=body, headers=auth_header(tokens[UserRole.COMPLIANCE]))
    assert (empty.status_code, empty.json()["error_code"]) == (409, "CHECK_CYCLE_EMPTY")
    bad = await client.post(
        url, json={"kind": "FULL", "reason": "x"}, headers=auth_header(tokens[UserRole.ADMIN])
    )
    assert bad.status_code == 422
    unknown = await client.post(
        f"{BASE}/exporters/{uuid.uuid4()}/background-check/cycles", json=body,
        headers=auth_header(tokens[UserRole.ADMIN]),
    )
    assert unknown.status_code == 404


async def test_the_checklist_is_read_per_cycle_and_only_the_current_one_is_editable(
    client, tokens
):
    company_id = await cleared_company(await make_company())
    first_listing = await client.get(
        f"{BASE}/exporters/{company_id}/screening-review",
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    cycle_1 = first_listing.json()["cycle"]["id"]
    started = await start_cycle(company_id)

    current = (await client.get(
        f"{BASE}/exporters/{company_id}/screening-review",
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )).json()
    assert current["cycle"]["id"] == str(started.cycle.id)
    assert current["cycle"]["is_current"] is True
    assert current["items"] == []
    assert current["capabilities"]["can_record_decision"] is True

    earlier = (await client.get(
        f"{BASE}/exporters/{company_id}/screening-review",
        params={"cycle_id": cycle_1},
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )).json()
    assert earlier["cycle"]["is_current"] is False
    assert earlier["capabilities"]["can_record_decision"] is False
    assert len(earlier["items"]) == 7
    assert {item["cycle_id"] for item in earlier["items"]} == {cycle_1}

    foreign = await client.get(
        f"{BASE}/exporters/{company_id}/screening-review",
        params={"cycle_id": str(uuid.uuid4())},
        headers=auth_header(tokens[UserRole.COMPLIANCE]),
    )
    assert foreign.status_code == 404
    assert foreign.json()["error_code"] == "CHECK_CYCLE_NOT_FOUND"


async def test_verification_results_are_served_with_their_cycle(client, tokens):
    company_id = await make_company()
    with pg() as cursor:
        legacy = insert_result(
            cursor, entity_type="EXPORTER", entity_reference=company_id, status="PASSED"
        )
    recorded = await exporter_result(company_id)
    listing = await client.get(
        f"{BASE}/verifications",
        params={"entity_type": "EXPORTER", "entity_reference": str(company_id)},
        headers=auth_header(tokens[UserRole.OPERATIONS]),
    )
    by_id = {row["id"]: row["cycle_id"] for row in listing.json()["results"]}
    # The legacy row reads as cycle 1 — the cycle the new result created.
    assert by_id[str(legacy)] == by_id[str(recorded.id)] == str(recorded.cycle_id)


@pytest.mark.parametrize("role", [UserRole.DEVELOPER, UserRole.API_USER])
async def test_the_cycle_routes_are_refused_to_developer(client, tokens, role):
    company_id = await make_company()
    url = f"{BASE}/exporters/{company_id}/background-check/cycles"
    assert (await client.get(url, headers=auth_header(tokens[role]))).status_code == 403
    assert (await client.post(
        url, json={"kind": "RE_KYC", "reason": "x"}, headers=auth_header(tokens[role])
    )).status_code == 403


async def test_the_cycle_shapes_carry_no_identifier_for_operations(client, tokens):
    company_id = await cleared_company(await make_company())
    await start_cycle(company_id)
    for path in ("/background-check", "/background-check/cycles", "/screening-review"):
        resp = await client.get(
            f"{BASE}/exporters/{company_id}{path}", headers=auth_header(tokens[UserRole.OPERATIONS])
        )
        assert resp.status_code == 200, path
        for forbidden in ('"pan"', '"gstin"', '"iec"', '"cin"', '"tax_id"', "contact_email"):
            assert forbidden not in resp.text, (path, forbidden)


async def test_approval_helpers_still_clear_across_cycles():
    """`approve_as` proposes and approves in any cycle."""
    company_id = await cleared_company(await make_company())
    started = await start_cycle(company_id)
    await answer_screening(company_id)
    await record_required_checks(company_id)
    view = await approve_as(CHECKER, company_id, maker=MAKER, risk=BackgroundCheckRisk.MEDIUM)
    assert view.to_value is _State.CLEAR
    assert (view.decided_by, view.approved_by) == (MAKER.user_id, CHECKER.user_id)
    assert view.cycle_id == started.cycle.id


async def test_start_cycle_is_one_transaction():
    """A refusal after the lock leaves nothing behind — not even an implicit cycle 1."""
    company_id = await make_company()
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(CheckCycleEmptyError):
            await BackgroundCheckService(db).start_cycle(
                company_id, kind=CheckCycleKind.RE_KYC, reason="r",
                actor_id=MAKER.user_id, actor_role=UserRole.COMPLIANCE,
            )
    with pg() as cursor:
        assert _cycles(cursor, company_id) == []
