"""Direct-SQL tests for ``onboarding_0015_bg_check`` — Developer 4A, phase 4A-2.

Every constraint and trigger the migration adds is attacked here through ``psycopg2``,
bypassing the ORM, so each test proves the **database** refuses the write
(migration register §2; ``docs/contracts/background-check.md`` §5.3, §6).

What is deliberately **not** here: the ``upgrade -> downgrade -> upgrade`` round trip.
Running Alembic inside the suite would drop the tables out from under every other test,
the reason ``test_0013_shared_history_schema.py`` gives. It is run as a command at the
phase gate and recorded in ``docs/dev4/4a-task.md``.
"""

from __future__ import annotations

import itertools
import pathlib
import uuid
from contextlib import contextmanager

import psycopg2
import psycopg2.errors
import psycopg2.extras
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.modules.onboarding.domain.entities.background_check_decision import LEGAL_MOVES
from app.modules.onboarding.domain.entities.background_check_enums import (
    BackgroundCheckRisk,
    BackgroundCheckState,
)
from app.modules.onboarding.tests.fixtures.companies import insert_company
from app.platform.configuration.config import get_settings

BACKEND = pathlib.Path(__file__).resolve().parents[5]
REVISION = "onboarding_0015_bg_check"
SCHEMA = "onboarding"

VALUES = [state.value for state in BackgroundCheckState]


def _connect():
    url = get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    return psycopg2.connect(url)


def _decide(
    cursor,
    company_id: uuid.UUID,
    from_value: str,
    to_value: str,
    *,
    supersedes: uuid.UUID | None = None,
    reason: str | None = "because",
    risk: str | None = None,
    decided_by: str | None = "compliance-user",
    decided_by_kind: str = "MANUAL",
) -> uuid.UUID:
    decision_id = uuid.uuid4()
    cursor.execute(
        f"INSERT INTO {SCHEMA}.background_check_decision "
        "(id, company_id, from_value, to_value, decided_by, decided_by_kind, source, reason,"
        " risk_rating, supersedes_decision_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'MANUAL', %s, %s, %s)",
        (
            str(decision_id),
            str(company_id),
            from_value,
            to_value,
            decided_by,
            decided_by_kind,
            reason,
            risk,
            str(supersedes) if supersedes else None,
        ),
    )
    return decision_id


def _started(cursor) -> tuple[uuid.UUID, uuid.UUID]:
    """A company and its first decision, `NOT_STARTED -> IN_REVIEW`."""
    company_id = insert_company(cursor)
    return company_id, _decide(cursor, company_id, "NOT_STARTED", "IN_REVIEW", reason=None)


def _document(cursor, company_id: uuid.UUID) -> uuid.UUID:
    document_id = uuid.uuid4()
    cursor.execute(
        f"INSERT INTO {SCHEMA}.crm_document"
        " (id, company_id, category, document_type, source, file_name, content_type,"
        "  size_bytes, uploaded_at, scan_status, storage_key)"
        " VALUES (%s, %s, 'OTHER', 'other', 'INTERNAL', 'x.pdf', 'application/pdf',"
        "  1, now(), 'PENDING_SCAN', %s)",
        (str(document_id), str(company_id), f"test/company/x/internal/{uuid.uuid4()}.pdf"),
    )
    return document_id


def _verification_result(cursor, company_id: uuid.UUID) -> uuid.UUID:
    result_id = uuid.uuid4()
    cursor.execute(
        f"INSERT INTO {SCHEMA}.verification_result"
        " (id, verification_type, entity_type, entity_reference, provider, status,"
        "  performed_at, raw_result, normalized_result)"
        " VALUES (%s, 'BANK_ACCOUNT', 'EXPORTER', %s, 'manual', 'PASSED', now(), %s, %s)",
        (
            str(result_id),
            str(company_id),
            psycopg2.extras.Json({}),
            psycopg2.extras.Json({}),
        ),
    )
    return result_id


def _screening_row(cursor, company_id: uuid.UUID) -> uuid.UUID:
    row_id = uuid.uuid4()
    cursor.execute(
        f"INSERT INTO {SCHEMA}.screening_review_item (id, customer_id, item_key, status)"
        " VALUES (%s, %s, 'website-reviewed', 'PASSED')",
        (str(row_id), str(company_id)),
    )
    return row_id


def _pin(cursor, decision_id: uuid.UUID, kind: str, **ids: uuid.UUID | None) -> uuid.UUID:
    evidence_id = uuid.uuid4()
    columns = [
        "crm_document_id",
        "verification_result_id",
        "verification_review_id",
        "screening_review_item_id",
    ]
    cursor.execute(
        f"INSERT INTO {SCHEMA}.background_check_evidence"
        f" (id, decision_id, kind, {', '.join(columns)})"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            str(evidence_id),
            str(decision_id),
            kind,
            *(str(ids[c]) if ids.get(c) else None for c in columns),
        ),
    )
    return evidence_id


@contextmanager
def _refused(error: type[Exception], constraint: str | None = None):
    """The database raises `error` — and, when given, names `constraint` as the cause,
    so a test cannot pass on some other constraint firing first."""
    with pytest.raises(error) as caught:
        yield caught
    if constraint is not None:
        assert caught.value.diag.constraint_name == constraint


# ── The migration's place in the chain ───────────────────────────────────────


def _script() -> ScriptDirectory:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    return ScriptDirectory.from_config(cfg)


def test_0015_parents_onto_0019_and_the_chain_has_one_head():
    """One head; a revision id inside the 32-character `version_num`; the parent the
    task fixes. Developer 4B's 0021 starts from the same head, so whichever merges
    second re-parents — this test names the parent that must change."""
    script = _script()
    heads = script.get_heads()
    assert heads == [REVISION]
    assert script.get_revision(REVISION).down_revision == "onboarding_0019_documents"
    assert len(REVISION) <= 32


def test_the_database_is_at_0015():
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        assert REVISION in {row[0] for row in cur.fetchall()}


@pytest.mark.parametrize(
    ("type_name", "expected"),
    [
        ("background_check_enum", VALUES),
        ("background_check_risk_enum", ["LOW", "MEDIUM", "HIGH", "CRITICAL"]),
        ("background_check_decided_by_kind_enum", ["MANUAL", "AUTOMATED"]),
        ("background_check_decision_source_enum", ["MANUAL", "RXIL"]),
        (
            "background_check_evidence_kind_enum",
            ["DOCUMENT", "VERIFICATION_RESULT", "SCREENING_ITEM"],
        ),
    ],
)
def test_each_enum_type_has_exactly_the_contract_values(type_name, expected):
    """Read back from the catalogue, so a value added to Python and not Postgres fails."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid"
            " JOIN pg_namespace n ON n.oid = t.typnamespace"
            " WHERE n.nspname = %s AND t.typname = %s ORDER BY e.enumsortorder",
            (SCHEMA, type_name),
        )
        assert [row[0] for row in cur.fetchall()] == expected


def test_the_risk_column_uses_dev4as_own_type_not_the_verification_enum():
    """D13: `background_check_risk_enum`, never Developer 4B's `verification_risk_level_enum`."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT udt_name FROM information_schema.columns"
            " WHERE table_schema = %s AND table_name = 'background_check_decision'"
            " AND column_name = 'risk_rating'",
            (SCHEMA,),
        )
        assert cur.fetchone() == ("background_check_risk_enum",)
    assert [risk.value for risk in BackgroundCheckRisk] == ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def test_the_company_record_gains_no_risk_column():
    """D5 is open: risk lives on the decision, not on `exporter_profile`."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = %s AND table_name = 'exporter_profile'"
            " AND column_name ILIKE '%%risk%%'",
            (SCHEMA,),
        )
        assert cur.fetchall() == []


# ── exporter_profile.background_check ────────────────────────────────────────


def test_a_new_company_starts_not_started():
    with _connect() as conn, conn.cursor() as cur:
        company_id = insert_company(cur)
        cur.execute(
            f"SELECT background_check FROM {SCHEMA}.exporter_profile WHERE customer_id = %s",
            (str(company_id),),
        )
        assert cur.fetchone() == ("NOT_STARTED",)


def test_the_gauge_cannot_be_null():
    with _connect() as conn, conn.cursor() as cur:
        company_id = insert_company(cur)
        with _refused(psycopg2.errors.NotNullViolation):
            cur.execute(
                f"UPDATE {SCHEMA}.exporter_profile SET background_check = NULL"
                " WHERE customer_id = %s",
                (str(company_id),),
            )


def test_the_gauge_refuses_a_value_outside_the_six():
    with _connect() as conn, conn.cursor() as cur:
        company_id = insert_company(cur)
        with _refused(psycopg2.errors.InvalidTextRepresentation):
            cur.execute(
                f"UPDATE {SCHEMA}.exporter_profile SET background_check = 'APPROVED'"
                " WHERE customer_id = %s",
                (str(company_id),),
            )


# ── Decisions: the move table ────────────────────────────────────────────────


_ALL_PAIRS = list(itertools.product(VALUES, VALUES))


@pytest.mark.parametrize(
    ("from_value", "to_value"), _ALL_PAIRS, ids=[f"{a}->{b}" for a, b in _ALL_PAIRS]
)
def test_the_database_admits_exactly_the_nine_moves(from_value, to_value):
    """All 36 pairs. An illegal one fails `ck_background_check_decision_move` itself.

    A legal one passes that check and every other: a start is accepted outright, and
    a later move — given a predecessor that does not exist — is stopped only by the
    chain foreign key, which runs after the checks.
    """
    legal = (BackgroundCheckState(from_value), BackgroundCheckState(to_value)) in LEGAL_MOVES
    with _connect() as conn, conn.cursor() as cur:
        company_id = insert_company(cur)
        is_start = from_value == "NOT_STARTED"
        attempt = dict(
            supersedes=None if is_start else uuid.uuid4(),
            reason="because",
            # Risk only where it is allowed, so a legal move is stopped by nothing but
            # the chain FK below.
            risk="LOW" if to_value == "CLEAR" else None,
        )
        if not legal:
            with _refused(psycopg2.errors.CheckViolation, "ck_background_check_decision_move"):
                _decide(cur, company_id, from_value, to_value, **attempt)
        elif is_start:
            _decide(cur, company_id, from_value, to_value, **attempt)
        else:
            with _refused(
                psycopg2.errors.ForeignKeyViolation, "fk_background_check_decision_supersedes"
            ):
                _decide(cur, company_id, from_value, to_value, **attempt)
        conn.rollback()


def test_clear_to_flagged_is_refused():
    """Architecture §4.2: new information about a cleared company goes through a reopen."""
    with _connect() as conn, conn.cursor() as cur:
        company_id, start = _started(cur)
        clear = _decide(cur, company_id, "IN_REVIEW", "CLEAR", supersedes=start, risk="LOW")
        with _refused(psycopg2.errors.CheckViolation, "ck_background_check_decision_move"):
            _decide(cur, company_id, "CLEAR", "FLAGGED", supersedes=clear)


def test_a_whole_legal_chain_is_accepted():
    """Every §3 move once, each superseding the last, through reopen and reassessment."""
    with _connect() as conn, conn.cursor() as cur:
        company_id, head = _started(cur)
        for from_value, to_value, risk in [
            ("IN_REVIEW", "MORE_INFO", None),
            ("MORE_INFO", "IN_REVIEW", None),
            ("IN_REVIEW", "FLAGGED", None),
            ("FLAGGED", "ON_HOLD", None),
            ("ON_HOLD", "IN_REVIEW", None),
            ("IN_REVIEW", "FLAGGED", None),
            ("FLAGGED", "IN_REVIEW", None),
            ("IN_REVIEW", "CLEAR", "CRITICAL"),
            ("CLEAR", "IN_REVIEW", None),
        ]:
            head = _decide(cur, company_id, from_value, to_value, supersedes=head, risk=risk)
        cur.execute(
            f"SELECT count(*) FROM {SCHEMA}.background_check_decision WHERE company_id = %s",
            (str(company_id),),
        )
        assert cur.fetchone() == (10,)


# ── Decisions: reasons, risk, actor ──────────────────────────────────────────


@pytest.mark.parametrize("reason", [None, "", "   "])
@pytest.mark.parametrize(
    ("from_value", "to_value"),
    [
        ("IN_REVIEW", "CLEAR"),
        ("IN_REVIEW", "MORE_INFO"),
        ("MORE_INFO", "IN_REVIEW"),
        ("IN_REVIEW", "FLAGGED"),
        ("FLAGGED", "ON_HOLD"),
        ("FLAGGED", "IN_REVIEW"),
        ("ON_HOLD", "IN_REVIEW"),
        ("CLEAR", "IN_REVIEW"),
    ],
)
def test_every_move_but_the_start_needs_text(from_value, to_value, reason):
    """Contract §4 — including `CLEAR` and `MORE_INFO -> IN_REVIEW`, the two rows
    `history-row.md` §4 omits (D14). The check runs before the chain FK, so a
    predecessor that does not exist does not mask it."""
    with _connect() as conn, conn.cursor() as cur:
        company_id = insert_company(cur)
        with _refused(psycopg2.errors.CheckViolation, "ck_background_check_decision_reason"):
            _decide(
                cur, company_id, from_value, to_value,
                supersedes=uuid.uuid4(), reason=reason, risk="LOW",
            )


def test_the_start_needs_no_text():
    with _connect() as conn, conn.cursor() as cur:
        _started(cur)


def test_clear_without_a_risk_rating_is_refused():
    with _connect() as conn, conn.cursor() as cur:
        company_id, start = _started(cur)
        with _refused(psycopg2.errors.CheckViolation, "ck_background_check_decision_clear_risk"):
            _decide(cur, company_id, "IN_REVIEW", "CLEAR", supersedes=start, risk=None)


@pytest.mark.parametrize("risk", ["LOW", "MEDIUM", "HIGH", "CRITICAL"])
def test_clear_accepts_each_risk_on_the_scale(risk):
    with _connect() as conn, conn.cursor() as cur:
        company_id, start = _started(cur)
        _decide(cur, company_id, "IN_REVIEW", "CLEAR", supersedes=start, risk=risk)


@pytest.mark.parametrize("risk", ["PROHIBITED", "SEVERE", "low", "REVIEW"])
def test_a_risk_outside_the_scale_is_refused(risk):
    """"Prohibited" is an outcome (`FLAGGED`), never a risk (decision 6)."""
    with _connect() as conn, conn.cursor() as cur:
        company_id, start = _started(cur)
        with _refused(psycopg2.errors.InvalidTextRepresentation):
            _decide(cur, company_id, "IN_REVIEW", "CLEAR", supersedes=start, risk=risk)


@pytest.mark.parametrize(
    ("from_value", "to_value"),
    [
        (from_value.value, to_value.value)
        for from_value, to_value in LEGAL_MOVES
        if to_value is not BackgroundCheckState.CLEAR
    ],
)
def test_risk_on_a_non_clear_decision_is_refused(from_value, to_value):
    """Risk is compliance's rating at the moment of clearing (contract §7), so every
    other move — an OPERATIONS start included — is refused one. Without this the reader
    would report whatever rating any move carried as the company's."""
    with _connect() as conn, conn.cursor() as cur:
        company_id = insert_company(cur)
        is_start = from_value == "NOT_STARTED"
        with _refused(
            psycopg2.errors.CheckViolation, "ck_background_check_decision_risk_only_on_clear"
        ):
            _decide(
                cur, company_id, from_value, to_value,
                supersedes=None if is_start else uuid.uuid4(),
                reason="because", risk="HIGH",
            )


def test_a_non_clear_decision_without_risk_is_accepted():
    with _connect() as conn, conn.cursor() as cur:
        company_id, start = _started(cur)
        flagged = _decide(cur, company_id, "IN_REVIEW", "FLAGGED", supersedes=start, risk=None)
        _decide(cur, company_id, "FLAGGED", "ON_HOLD", supersedes=flagged, risk=None)


@pytest.mark.parametrize("decided_by", [None, "", "  "])
def test_a_manual_decision_names_who_made_it(decided_by):
    with _connect() as conn, conn.cursor() as cur:
        company_id = insert_company(cur)
        with _refused(psycopg2.errors.CheckViolation, "ck_background_check_decision_decided_by"):
            _decide(cur, company_id, "NOT_STARTED", "IN_REVIEW", decided_by=decided_by)


def test_an_automated_decision_may_have_no_person():
    """Reserved for the blocked RXIL start (D12); the shape allows it, nothing writes it."""
    with _connect() as conn, conn.cursor() as cur:
        company_id = insert_company(cur)
        _decide(
            cur, company_id, "NOT_STARTED", "IN_REVIEW",
            decided_by=None, decided_by_kind="AUTOMATED",
        )


def test_decided_at_is_server_time():
    with _connect() as conn, conn.cursor() as cur:
        company_id, start = _started(cur)
        cur.execute(
            f"SELECT decided_at BETWEEN now() AND clock_timestamp(), details"
            f" FROM {SCHEMA}.background_check_decision WHERE id = %s",
            (str(start),),
        )
        assert cur.fetchone() == (True, {})


def test_decided_at_follows_the_chain_not_the_transaction_start():
    """`clock_timestamp()`, not `now()`: a move that waited on the company lock is
    inserted after its predecessor, so it must not sort before it. Two decisions in one
    transaction stand in for that here — under `now()` they would tie."""
    with _connect() as conn, conn.cursor() as cur:
        company_id, start = _started(cur)
        second = _decide(cur, company_id, "IN_REVIEW", "FLAGGED", supersedes=start)
        cur.execute(
            f"SELECT (SELECT decided_at FROM {SCHEMA}.background_check_decision WHERE id = %s)"
            f" > (SELECT decided_at FROM {SCHEMA}.background_check_decision WHERE id = %s)",
            (str(second), str(start)),
        )
        assert cur.fetchone() == (True,)


# ── Decisions: the supersedes chain ──────────────────────────────────────────


def test_the_start_cannot_name_a_predecessor():
    with _connect() as conn, conn.cursor() as cur:
        company_id, start = _started(cur)
        other = insert_company(cur)
        with _refused(psycopg2.errors.CheckViolation, "ck_background_check_decision_first"):
            _decide(cur, other, "NOT_STARTED", "IN_REVIEW", supersedes=start)


def test_a_later_decision_must_name_its_predecessor():
    with _connect() as conn, conn.cursor() as cur:
        company_id, _ = _started(cur)
        with _refused(psycopg2.errors.CheckViolation, "ck_background_check_decision_first"):
            _decide(cur, company_id, "IN_REVIEW", "FLAGGED", supersedes=None)


def test_a_company_has_one_chain():
    with _connect() as conn, conn.cursor() as cur:
        company_id, _ = _started(cur)
        with _refused(
            psycopg2.errors.UniqueViolation, "uq_background_check_decision_first_per_company"
        ):
            _decide(cur, company_id, "NOT_STARTED", "IN_REVIEW", reason=None)


def test_a_decision_cannot_be_superseded_twice():
    """Two concurrent moves from the same head: the second is refused, not forked."""
    with _connect() as conn, conn.cursor() as cur:
        company_id, start = _started(cur)
        _decide(cur, company_id, "IN_REVIEW", "FLAGGED", supersedes=start)
        with _refused(psycopg2.errors.UniqueViolation, "uq_background_check_decision_supersedes"):
            _decide(cur, company_id, "IN_REVIEW", "MORE_INFO", supersedes=start)


def test_a_decision_cannot_supersede_another_companys_decision():
    with _connect() as conn, conn.cursor() as cur:
        _, their_start = _started(cur)
        ours = insert_company(cur)
        with _refused(
            psycopg2.errors.ForeignKeyViolation, "fk_background_check_decision_supersedes"
        ):
            _decide(cur, ours, "IN_REVIEW", "FLAGGED", supersedes=their_start)


def test_a_move_must_start_where_its_predecessor_ended():
    """The predecessor ended at `IN_REVIEW`; a move claiming to leave `FLAGGED` is refused."""
    with _connect() as conn, conn.cursor() as cur:
        company_id, start = _started(cur)
        with _refused(
            psycopg2.errors.ForeignKeyViolation, "fk_background_check_decision_supersedes"
        ):
            _decide(cur, company_id, "FLAGGED", "ON_HOLD", supersedes=start)


# ── Decisions: locked ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE {schema}.background_check_decision SET reason = 'edited' WHERE id = %s",
        "UPDATE {schema}.background_check_decision SET to_value = 'CLEAR' WHERE id = %s",
        "DELETE FROM {schema}.background_check_decision WHERE id = %s",
    ],
    ids=["update-reason", "update-outcome", "delete"],
)
def test_a_decision_cannot_be_updated_or_deleted(statement):
    with _connect() as conn, conn.cursor() as cur:
        _, start = _started(cur)
        conn.commit()
        with pytest.raises(psycopg2.errors.RaiseException):
            cur.execute(statement.format(schema=SCHEMA), (str(start),))
        conn.rollback()
        cur.execute(
            f"SELECT reason, to_value FROM {SCHEMA}.background_check_decision WHERE id = %s",
            (str(start),),
        )
        assert cur.fetchone() == (None, "IN_REVIEW")


def test_a_company_with_decisions_cannot_be_deleted():
    with _connect() as conn, conn.cursor() as cur:
        company_id, _ = _started(cur)
        with _refused(
            psycopg2.errors.ForeignKeyViolation, "fk_background_check_decision_company_id"
        ):
            cur.execute(
                f"DELETE FROM {SCHEMA}.exporter_profile WHERE customer_id = %s",
                (str(company_id),),
            )


def test_a_decision_for_a_ghost_company_is_refused():
    with _connect() as conn, conn.cursor() as cur:
        with _refused(
            psycopg2.errors.ForeignKeyViolation, "fk_background_check_decision_company_id"
        ):
            _decide(cur, uuid.uuid4(), "NOT_STARTED", "IN_REVIEW")


# ── Evidence ─────────────────────────────────────────────────────────────────


def test_each_kind_pins_its_own_row():
    with _connect() as conn, conn.cursor() as cur:
        company_id, start = _started(cur)
        _pin(cur, start, "DOCUMENT", crm_document_id=_document(cur, company_id))
        _pin(
            cur, start, "VERIFICATION_RESULT",
            verification_result_id=_verification_result(cur, company_id),
            # Bare uuid: Developer 4B's review table is not referenced (contract §6.1).
            verification_review_id=uuid.uuid4(),
        )
        _pin(cur, start, "SCREENING_ITEM", screening_review_item_id=_screening_row(cur, company_id))
        cur.execute(
            f"SELECT kind FROM {SCHEMA}.background_check_evidence WHERE decision_id = %s"
            " ORDER BY kind",
            (str(start),),
        )
        assert [row[0] for row in cur.fetchall()] == [
            "DOCUMENT",
            "VERIFICATION_RESULT",
            "SCREENING_ITEM",
        ]


def test_the_review_id_has_no_foreign_key():
    """Contract §6.1: nothing in 0015 references Developer 4B's schema-to-be."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT kcu.column_name FROM information_schema.table_constraints tc"
            " JOIN information_schema.key_column_usage kcu"
            "   ON kcu.constraint_name = tc.constraint_name"
            "  AND kcu.table_schema = tc.table_schema"
            " WHERE tc.table_schema = %s AND tc.table_name = 'background_check_evidence'"
            "   AND tc.constraint_type = 'FOREIGN KEY'",
            (SCHEMA,),
        )
        assert {row[0] for row in cur.fetchall()} == {
            "decision_id",
            "crm_document_id",
            "verification_result_id",
            "screening_review_item_id",
        }


@pytest.mark.parametrize(
    ("kind", "columns"),
    [
        ("DOCUMENT", {}),
        ("DOCUMENT", {"crm_document_id": "doc", "verification_result_id": "result"}),
        ("DOCUMENT", {"crm_document_id": "doc", "verification_review_id": "review"}),
        ("VERIFICATION_RESULT", {}),
        ("VERIFICATION_RESULT", {"verification_review_id": "review"}),
        ("VERIFICATION_RESULT", {"verification_result_id": "result", "crm_document_id": "doc"}),
        ("SCREENING_ITEM", {}),
        ("SCREENING_ITEM", {"screening_review_item_id": "row", "verification_review_id": "review"}),
    ],
    ids=lambda value: value if isinstance(value, str) else "+".join(value) or "nothing",
)
def test_a_row_must_set_exactly_the_columns_of_its_kind(kind, columns):
    with _connect() as conn, conn.cursor() as cur:
        company_id, start = _started(cur)
        real = {
            "doc": _document(cur, company_id),
            "result": _verification_result(cur, company_id),
            "row": _screening_row(cur, company_id),
            "review": uuid.uuid4(),
        }
        with _refused(psycopg2.errors.CheckViolation, "ck_background_check_evidence_kind"):
            _pin(cur, start, kind, **{column: real[key] for column, key in columns.items()})


@pytest.mark.parametrize(
    ("kind", "column", "constraint"),
    [
        ("DOCUMENT", "crm_document_id", "fk_background_check_evidence_crm_document_id"),
        (
            "VERIFICATION_RESULT",
            "verification_result_id",
            "fk_background_check_evidence_verification_result_id",
        ),
        (
            "SCREENING_ITEM",
            "screening_review_item_id",
            "fk_background_check_evidence_screening_review_item_id",
        ),
    ],
)
def test_evidence_must_name_a_row_that_exists(kind, column, constraint):
    with _connect() as conn, conn.cursor() as cur:
        _, start = _started(cur)
        with _refused(psycopg2.errors.ForeignKeyViolation, constraint):
            _pin(cur, start, kind, **{column: uuid.uuid4()})


def test_evidence_must_belong_to_a_real_decision():
    with _connect() as conn, conn.cursor() as cur:
        company_id = insert_company(cur)
        with _refused(
            psycopg2.errors.ForeignKeyViolation, "fk_background_check_evidence_decision_id"
        ):
            _pin(cur, uuid.uuid4(), "DOCUMENT", crm_document_id=_document(cur, company_id))


@pytest.mark.parametrize(
    ("kind", "column", "maker", "constraint"),
    [
        ("DOCUMENT", "crm_document_id", _document, "uq_background_check_evidence_document"),
        (
            "VERIFICATION_RESULT",
            "verification_result_id",
            _verification_result,
            "uq_background_check_evidence_verification",
        ),
        (
            "SCREENING_ITEM",
            "screening_review_item_id",
            _screening_row,
            "uq_background_check_evidence_screening",
        ),
    ],
)
def test_an_item_is_pinned_once_per_decision(kind, column, maker, constraint):
    with _connect() as conn, conn.cursor() as cur:
        company_id, start = _started(cur)
        item = maker(cur, company_id)
        _pin(cur, start, kind, **{column: item})
        with _refused(psycopg2.errors.UniqueViolation, constraint):
            _pin(cur, start, kind, **{column: item})


def test_the_same_item_may_be_pinned_by_several_decisions():
    """A later decision relying on the same document pins it again in its own snapshot."""
    with _connect() as conn, conn.cursor() as cur:
        company_id, start = _started(cur)
        flagged = _decide(cur, company_id, "IN_REVIEW", "FLAGGED", supersedes=start)
        document_id = _document(cur, company_id)
        _pin(cur, start, "DOCUMENT", crm_document_id=document_id)
        _pin(cur, flagged, "DOCUMENT", crm_document_id=document_id)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE {schema}.background_check_evidence SET verification_review_id = gen_random_uuid()"
        " WHERE id = %s",
        "DELETE FROM {schema}.background_check_evidence WHERE id = %s",
    ],
    ids=["update", "delete"],
)
def test_evidence_cannot_be_updated_or_deleted(statement):
    with _connect() as conn, conn.cursor() as cur:
        company_id, start = _started(cur)
        evidence = _pin(cur, start, "DOCUMENT", crm_document_id=_document(cur, company_id))
        conn.commit()
        with pytest.raises(psycopg2.errors.RaiseException):
            cur.execute(statement.format(schema=SCHEMA), (str(evidence),))
        conn.rollback()


def test_every_foreign_key_on_both_tables_restricts():
    """No cascade path anywhere: a delete elsewhere can never take a decision or its
    evidence with it."""
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT conname, confdeltype FROM pg_constraint"
            " WHERE conrelid IN (%s::regclass, %s::regclass) AND contype = 'f'",
            (f"{SCHEMA}.background_check_decision", f"{SCHEMA}.background_check_evidence"),
        )
        # `r` = RESTRICT, for every foreign key on both tables.
        assert {deltype for _, deltype in cur.fetchall()} == {"r"}


@pytest.mark.parametrize(
    ("maker", "kind", "column", "table", "key"),
    [
        (_document, "DOCUMENT", "crm_document_id", "crm_document", "id"),
        (
            _verification_result,
            "VERIFICATION_RESULT",
            "verification_result_id",
            "verification_result",
            "id",
        ),
    ],
)
def test_pinned_evidence_cannot_be_deleted_from_under_a_decision(maker, kind, column, table, key):
    """`RESTRICT`: a later clean-up cannot silently change what a decision rested on.
    (Screening rows are append-only already; their table refuses every delete.)"""
    with _connect() as conn, conn.cursor() as cur:
        company_id, start = _started(cur)
        item = maker(cur, company_id)
        _pin(cur, start, kind, **{column: item})
        with _refused(psycopg2.errors.ForeignKeyViolation):
            cur.execute(f"DELETE FROM {SCHEMA}.{table} WHERE {key} = %s", (str(item),))


# ── Indexes and triggers ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("table", "index"),
    [
        ("exporter_profile", "ix_exporter_profile_background_check"),
        ("background_check_decision", "ix_background_check_decision_company_recent"),
        ("background_check_decision", "uq_background_check_decision_first_per_company"),
        ("background_check_decision", "uq_background_check_decision_supersedes"),
        ("background_check_decision", "uq_background_check_decision_chain_key"),
        ("background_check_evidence", "uq_background_check_evidence_document"),
        ("background_check_evidence", "uq_background_check_evidence_verification"),
        ("background_check_evidence", "uq_background_check_evidence_screening"),
        ("background_check_evidence", "ix_background_check_evidence_crm_document_id"),
        ("background_check_evidence", "ix_background_check_evidence_verification_result_id"),
        ("background_check_evidence", "ix_background_check_evidence_screening_review_item_id"),
    ],
)
def test_the_index_exists(table, index):
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM pg_indexes WHERE schemaname = %s AND tablename = %s AND indexname = %s",
            (SCHEMA, table, index),
        )
        assert cur.fetchone() == (1,)


@pytest.mark.parametrize(
    ("table", "trigger"),
    [
        ("background_check_decision", "trg_background_check_decision_append_only"),
        ("background_check_evidence", "trg_background_check_evidence_append_only"),
    ],
)
def test_the_shared_append_only_guard_is_attached(table, trigger):
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT p.proname FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid"
            " WHERE t.tgrelid = %s::regclass AND t.tgname = %s",
            (f"{SCHEMA}.{table}", trigger),
        )
        assert cur.fetchone() == ("prevent_mutation",)
