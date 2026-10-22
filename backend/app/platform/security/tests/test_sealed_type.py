"""`SealedString` and `SealedJSON`: seal on write, open on read, and compare against
every form a value can be stored in.

No database here: the bind and result processors are called directly, and the
comparisons are compiled and their parameters read back.
"""

from __future__ import annotations

import base64

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, select
from sqlalchemy.dialects import postgresql

from app.platform.configuration.config import get_settings
from app.platform.security.field_cipher import (
    FieldDecryptionError,
    deterministic_seals,
    encrypt_deterministic,
)
from app.platform.security.sealed_type import SealedJSON, SealedString, looks_sealed

KEY_A = base64.b64encode(b"a" * 32).decode()
KEY_B = base64.b64encode(b"b" * 32).decode()
PAN = "^[A-Z]{5}[0-9]{4}[A-Z]$"
DIALECT = postgresql.dialect()


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "FIELD_ENCRYPTION_KEYS", f"a:{KEY_A}")
    monkeypatch.setattr(get_settings(), "ENVIRONMENT", "production")


def _table() -> Table:
    return Table(
        "company",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("pan", SealedString("company.pan", pattern=PAN)),
        Column("city", SealedString("company.city")),
    )


def _params(statement) -> list[str]:
    (values,) = statement.compile(dialect=DIALECT).params.values()
    return values


# ── Writing and reading ──────────────────────────────────────────────────────


def test_a_well_formed_value_is_sealed_and_reads_back():
    sealed_type = SealedString("company.pan", pattern=PAN)
    stored = sealed_type.process_bind_param("ABCDE1234F", DIALECT)

    assert looks_sealed(stored)
    assert "ABCDE1234F" not in stored
    assert sealed_type.process_result_value(stored, DIALECT) == "ABCDE1234F"


def test_the_same_value_always_seals_the_same_way():
    """What a unique constraint and an equality lookup rely on."""
    sealed_type = SealedString("company.pan", pattern=PAN)
    assert sealed_type.process_bind_param("ABCDE1234F", DIALECT) == (
        sealed_type.process_bind_param("ABCDE1234F", DIALECT)
    )


def test_a_malformed_value_is_written_as_it_came_for_the_check_to_refuse():
    sealed_type = SealedString("company.pan", pattern=PAN)
    for bad in ("abcde1234f", "ABCDE 1234F", ""):
        assert sealed_type.process_bind_param(bad, DIALECT) == bad


def test_a_column_without_a_format_seals_everything_even_a_blank():
    """A NOT NULL address line may be blank; sealing it keeps it non-null."""
    sealed_type = SealedString("company.city")
    stored = sealed_type.process_bind_param("", DIALECT)
    assert looks_sealed(stored)
    assert sealed_type.process_result_value(stored, DIALECT) == ""


def test_none_stays_null_both_ways():
    sealed_type = SealedString("company.city")
    assert sealed_type.process_bind_param(None, DIALECT) is None
    assert sealed_type.process_result_value(None, DIALECT) is None


def test_a_row_written_before_sealing_reads_as_it_stands():
    assert SealedString("company.pan", pattern=PAN).process_result_value(
        "ABCDE1234F", DIALECT
    ) == ("ABCDE1234F")


def test_a_ciphertext_is_not_sealed_a_second_time():
    sealed_type = SealedString("company.pan", pattern=PAN)
    stored = sealed_type.process_bind_param("ABCDE1234F", DIALECT)
    assert sealed_type.process_bind_param(stored, DIALECT) == stored


def test_an_address_line_that_begins_like_a_ciphertext_is_still_sealed():
    """`d1.` alone is not the shape of a sealed value: free text can begin with it."""
    sealed_type = SealedString("company.city")
    assert not looks_sealed("d1. Block A")
    stored = sealed_type.process_bind_param("d1. Block A", DIALECT)
    assert stored != "d1. Block A"
    assert sealed_type.process_result_value(stored, DIALECT) == "d1. Block A"


def test_a_value_sealed_for_one_column_does_not_open_as_another():
    stored = SealedString("company.pan", pattern=PAN).process_bind_param("ABCDE1234F", DIALECT)
    with pytest.raises(FieldDecryptionError):
        SealedString("company.cin").process_result_value(stored, DIALECT)


# ── Comparing ───────────────────────────────────────────────────────────────


def test_equality_matches_the_plain_and_the_sealed_form():
    table = _table()
    forms = _params(select(table).where(table.c.pan == "ABCDE1234F"))
    assert forms == [
        "ABCDE1234F",
        encrypt_deterministic("ABCDE1234F", purpose="company.pan"),
    ]


def test_equality_with_a_malformed_value_only_looks_for_it_plain():
    """It can only have been stored plain, so that is the only form searched."""
    table = _table()
    assert _params(select(table).where(table.c.pan == "abc")) == ["abc"]


def test_membership_matches_every_form_of_every_value():
    table = _table()
    forms = _params(select(table).where(table.c.pan.in_(["ABCDE1234F", "FGHIJ5678K"])))
    assert len(forms) == 4
    assert {"ABCDE1234F", "FGHIJ5678K"} <= set(forms)


def test_inequality_excludes_every_form():
    table = _table()
    statement = select(table).where(table.c.pan != "ABCDE1234F")
    assert "NOT IN" in str(statement.compile(dialect=DIALECT))
    assert len(_params(statement)) == 2


def test_is_null_is_left_alone():
    table = _table()
    assert "IS NULL" in str(select(table).where(table.c.pan.is_(None)).compile(dialect=DIALECT))


def test_after_a_rotation_a_lookup_finds_rows_under_either_key(monkeypatch: pytest.MonkeyPatch):
    """The new key first, the old one still listed: a row sealed under the old key
    must not drop out of a lookup until it is re-sealed."""
    under_a = encrypt_deterministic("ABCDE1234F", purpose="company.pan")
    monkeypatch.setattr(get_settings(), "FIELD_ENCRYPTION_KEYS", f"b:{KEY_B},a:{KEY_A}")

    table = _table()
    forms = _params(select(table).where(table.c.pan == "ABCDE1234F"))

    assert under_a in forms
    assert forms[1] == deterministic_seals("ABCDE1234F", purpose="company.pan")[0]
    assert forms[1].startswith("d1.b.")


# ── Snapshots ───────────────────────────────────────────────────────────────


SNAPSHOT = SealedJSON("deal.handover_snapshot", paths=(("buyer", "tax_id"),), none_as_null=True)


def test_a_snapshot_seals_only_the_named_leaves_and_reads_back_whole():
    document = {"buyer": {"tax_id": "TAX-1", "name": "Acme"}, "terms": {"days": 30}}
    stored = SNAPSHOT.process_bind_param(document, DIALECT)

    assert looks_sealed(stored["buyer"]["tax_id"])
    assert stored["buyer"]["name"] == "Acme"
    assert stored["terms"] == {"days": 30}
    assert SNAPSHOT.process_result_value(stored, DIALECT) == document
    assert document["buyer"]["tax_id"] == "TAX-1", "the caller's dict is not changed"


def test_a_snapshot_seals_identically_every_time():
    """So re-sending an unchanged frozen snapshot is never an edit to the trigger."""
    document = {"buyer": {"tax_id": "TAX-1"}}
    assert SNAPSHOT.process_bind_param(document, DIALECT) == (
        SNAPSHOT.process_bind_param(document, DIALECT)
    )


def test_a_snapshot_written_before_sealing_or_without_the_leaf_reads_as_it_stands():
    assert SNAPSHOT.process_result_value({"buyer": {"tax_id": "TAX-1"}}, DIALECT) == {
        "buyer": {"tax_id": "TAX-1"}
    }
    assert SNAPSHOT.process_result_value({"buyer": None}, DIALECT) == {"buyer": None}
    assert SNAPSHOT.process_result_value(None, DIALECT) is None
