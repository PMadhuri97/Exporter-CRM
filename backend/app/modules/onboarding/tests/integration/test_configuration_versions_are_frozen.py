"""Direct-SQL proof that an old version of a payment term or a sanctions list is fixed.

Migration ``onboarding_0055_config_freeze``: a deal keeps the term it was agreed on and
a sanctions run the list versions it screened, so a version, once written, may only be
superseded (``is_current`` flipped to false), never rewritten.
"""

from __future__ import annotations

import uuid

import psycopg2.errors
import pytest

from app.modules.onboarding.tests.integration._verification_support import pg

pytestmark = pytest.mark.asyncio


def _code() -> str:
    return "TEST_" + uuid.uuid4().hex[:12].upper()


def _payment_term(cur) -> uuid.UUID:
    term_id = uuid.uuid4()
    cur.execute(
        "INSERT INTO onboarding.payment_term (id, code, version, label, kind, days) "
        "VALUES (%s, %s, 1, 'Usance 90', 'LC_USANCE', 90)",
        (str(term_id), _code()),
    )
    return term_id


def _sanctions_list(cur) -> uuid.UUID:
    list_id = uuid.uuid4()
    cur.execute(
        "INSERT INTO onboarding.sanctions_list (id, code, version, name, list_version_date) "
        "VALUES (%s, %s, 1, 'Test list', current_date)",
        (str(list_id), _code()),
    )
    return list_id


@pytest.mark.parametrize(
    ("column", "value"),
    [("label", "Usance 120"), ("kind", "DA"), ("days", 120), ("active", False), ("version", 2)],
)
async def test_a_payment_term_version_cannot_be_rewritten(column, value):
    with pg() as cur:
        term_id = _payment_term(cur)
        with pytest.raises(psycopg2.errors.RaiseException, match=f"Column {column} is immutable"):
            cur.execute(
                f"UPDATE onboarding.payment_term SET {column} = %s WHERE id = %s",
                (value, str(term_id)),
            )


async def test_a_payment_term_version_can_still_be_superseded():
    with pg() as cur:
        term_id = _payment_term(cur)
        cur.execute(
            "UPDATE onboarding.payment_term SET is_current = false WHERE id = %s", (str(term_id),)
        )
        cur.execute("SELECT is_current FROM onboarding.payment_term WHERE id = %s", (str(term_id),))
        assert cur.fetchone() == (False,)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("name", "Renamed list"),
        ("mandatory", True),
        ("active", False),
        ("list_version_date", "2020-01-01"),
    ],
)
async def test_a_sanctions_list_version_cannot_be_rewritten(column, value):
    with pg() as cur:
        list_id = _sanctions_list(cur)
        with pytest.raises(psycopg2.errors.RaiseException, match=f"Column {column} is immutable"):
            cur.execute(
                f"UPDATE onboarding.sanctions_list SET {column} = %s WHERE id = %s",
                (value, str(list_id)),
            )


async def test_a_sanctions_list_version_can_still_be_superseded():
    with pg() as cur:
        list_id = _sanctions_list(cur)
        cur.execute(
            "UPDATE onboarding.sanctions_list SET is_current = false WHERE id = %s", (str(list_id),)
        )
        cur.execute("SELECT is_current FROM onboarding.sanctions_list WHERE id = %s", (str(list_id),))
        assert cur.fetchone() == (False,)
