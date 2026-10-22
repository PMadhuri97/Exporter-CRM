"""Column types that seal a value on its way into the database and open it on the way
out, so the rest of the application only ever handles plain text.

``SealedString`` is a ``varchar`` holding an AES-SIV ciphertext (``encrypt_deterministic``).
``SealedJSON`` is a JSONB document with chosen string leaves sealed the same way. Both
leave every read path alone: an ORM attribute reads back as the plain value, so masking,
format checks in the services and the history log's masking all see what they always
saw.

Why deterministic
-----------------
These columns are compared: a unique constraint (``uq_exporter_profile_pan``), a lookup
(``?gstin=``), a duplicate warning. SIV gives one value one ciphertext under one key, so
all three keep working against the stored text. The cost, which is deliberate, is that
two rows holding the same value are visibly the same in a dump.

Rows written before a column was sealed
---------------------------------------
**Existing values are not re-written.** A column holds plain text for old rows and a
ciphertext for anything written since, told apart by shape (:func:`looks_sealed`). So a
comparison has to find both, and the comparator below turns

    pan = 'ABCDE1234F'

into

    pan IN ('ABCDE1234F', 'd1.<current key>.…', 'd1.<older key>.…')

— the plain spelling for an old row, and the value sealed under every configured key for
a new one (a rotation leaves rows under the previous key until they are re-sealed). The
same goes for ``!=`` and ``in_()``. A unique constraint cannot do the same: an old plain
PAN and a new sealed copy of it are different strings, and only the services' own
duplicate checks, which go through this comparator, stand between them.

A value that fails the column's format
--------------------------------------
``pattern`` is the column's format rule (``PAN_RE`` for a PAN). A value that does not
match it is **not sealed**: it is written as it came, so the column's check constraint —
``pan IS NULL OR pan ~ '<pattern>' OR pan LIKE 'd1.%'`` — refuses it exactly as it did
before the column was sealed. A malformed value therefore fails the same way, at the
same point, with the same error, whichever writer it came from; only a well-formed one
is ever encrypted.

What this does not cover
------------------------
Raw SQL. ``text("... WHERE pan = :pan")`` and ``LIKE`` patterns never pass through the
type, so they compare against ciphertext and find nothing. Every such query on a sealed
column has to be written through the ORM column or rewritten.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from sqlalchemy import String, Text, type_coerce
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import operators
from sqlalchemy.types import TypeDecorator

from app.platform.security.field_cipher import (
    decrypt_deterministic,
    deterministic_seals,
    encrypt_deterministic,
)

#: How wide a sealed identifier column is. A ciphertext is a ``d1.<key id>.`` prefix
#: and the base64 of a 16-byte SIV tag plus the value's UTF-8 bytes: about
#: ``1.33 × (bytes + 16) + 10`` characters, so 255 holds a value of up to ~165 bytes —
#: every identifier here (a 100-character tax id seals to 164). Free text, where a
#: 255-character line in Devanagari is 765 bytes, is ``text`` instead (``length=None``).
SEALED_WIDTH = 255

#: The whole shape of an ``encrypt_deterministic`` value. Stricter than the ``d1.``
#: prefix ``is_deterministic_ciphertext`` checks, because these columns hold free text —
#: an address line can begin ``d1.`` — and only a value with no space, a key id and a
#: base64 body is taken for a ciphertext.
_SEALED = re.compile(r"^d1\.[^.\s]+\.[A-Za-z0-9+/]+={0,2}$")

#: The same shape as a Postgres regex, for the check constraints that accept a sealed
#: value alongside a well-formed plain one (migration ``onboarding_0064``).
SEALED_SQL = r"^d1\.[^.[:space:]]+\.[A-Za-z0-9+/]+={0,2}$"


def looks_sealed(value: str | None) -> bool:
    """Whether ``value`` is an ``encrypt_deterministic`` ciphertext rather than a
    plain value written before its column was sealed."""
    return bool(value) and _SEALED.match(value) is not None


class SealedString(TypeDecorator):
    """A ``varchar(length)`` — ``text`` when ``length`` is ``None`` — whose values are
    sealed with AES-SIV for ``purpose``.

    ``purpose`` is bound into each ciphertext (``"<table>.<column>"``), so a value cannot
    be copied into another column and read there. ``pattern``, when given, is the
    column's format rule; see the module docstring for what happens to a value that
    fails it.
    """

    impl = String(SEALED_WIDTH)
    cache_ok = True

    def __init__(
        self, purpose: str, pattern: str | None = None, length: int | None = SEALED_WIDTH
    ) -> None:
        super().__init__()
        self.impl = String(length) if length is not None else Text()
        self.length = length
        self.purpose = purpose
        self.pattern = pattern
        self._format = re.compile(pattern) if pattern is not None else None

    def sealable(self, value: str) -> bool:
        """Whether ``value`` is sealed when written (it is well formed, or the column has
        no format)."""
        return self._format is None or self._format.match(value) is not None

    def stored_forms(self, value: str) -> list[str]:
        """Every string the column can hold for ``value``: as written before sealing, and
        sealed under each configured key."""
        if not self.sealable(value):
            return [value]
        return [value, *deterministic_seals(value, purpose=self.purpose)]

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        # Already a ciphertext: copied from another row of this column. Sealing it again
        # would store a ciphertext of a ciphertext.
        if looks_sealed(value) or not self.sealable(value):
            return value
        return encrypt_deterministic(value, purpose=self.purpose)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None or not looks_sealed(value):
            return value
        return decrypt_deterministic(value, purpose=self.purpose)

    class Comparator(TypeDecorator.Comparator, String.comparator_factory):  # type: ignore[misc,name-defined]
        """Equality and membership against every form a value can be stored in."""

        def operate(self, op: Any, *other: Any, **kwargs: Any) -> Any:
            sealed_type = self.expr.type
            if op in (operators.eq, operators.ne) and len(other) == 1 and isinstance(other[0], str):
                forms = sealed_type.stored_forms(other[0])
                return self._as_text(forms, negate=op is operators.ne)
            if (
                op in (operators.in_op, operators.not_in_op)
                and len(other) == 1
                and isinstance(other[0], list | tuple | set | frozenset)
                and all(isinstance(item, str) for item in other[0])
            ):
                forms = [form for item in other[0] for form in sealed_type.stored_forms(item)]
                return self._as_text(forms, negate=op is operators.not_in_op)
            return super().operate(op, *other, **kwargs)

        def _as_text(self, forms: list[str], *, negate: bool) -> Any:
            # Compared as plain text: through this type again, each form would be sealed
            # a second time on its way to the database.
            column = type_coerce(self.expr, String())
            unique = list(dict.fromkeys(forms))
            return column.not_in(unique) if negate else column.in_(unique)

    comparator_factory = Comparator  # type: ignore[assignment]


class SealedJSON(TypeDecorator):
    """A JSONB document whose string leaves at ``paths`` are sealed with AES-SIV.

    For the snapshots that copy a buyer's identifiers out of their columns
    (``deal.handover_snapshot``, ``verification_result.subject_snapshot``): sealing the
    columns and not the copies would leave the same values in plain text one table over.

    Deterministic for the reason a frozen snapshot needs: the same document always
    writes the same bytes, so re-sending an unchanged snapshot can never look like an
    edit to ``trg_deal_terminal_freeze``. A snapshot written before this type is read as
    it stands, its leaves opened only where they are ciphertexts.
    """

    impl = JSONB
    cache_ok = True

    def __init__(
        self,
        purpose: str,
        paths: tuple[tuple[str, ...], ...],
        none_as_null: bool = False,
    ) -> None:
        # `none_as_null` is the column's own, passed through to JSONB unchanged.
        super().__init__(none_as_null=none_as_null)
        self.purpose = purpose
        self.paths = paths
        self.none_as_null = none_as_null

    def _leaf_purpose(self, path: tuple[str, ...]) -> str:
        return f"{self.purpose}.{'.'.join(path)}"

    def _transform(self, document: Any, *, seal: bool) -> Any:
        if not isinstance(document, dict):
            return document
        document = copy.deepcopy(document)
        for path in self.paths:
            parent: Any = document
            for key in path[:-1]:
                parent = parent.get(key) if isinstance(parent, dict) else None
            leaf = path[-1]
            if not isinstance(parent, dict) or not isinstance(parent.get(leaf), str):
                continue
            value = parent[leaf]
            if seal and not looks_sealed(value):
                parent[leaf] = encrypt_deterministic(value, purpose=self._leaf_purpose(path))
            elif not seal and looks_sealed(value):
                parent[leaf] = decrypt_deterministic(value, purpose=self._leaf_purpose(path))
        return document

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        return self._transform(value, seal=True)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        return self._transform(value, seal=False)


__all__ = ["SEALED_SQL", "SEALED_WIDTH", "SealedJSON", "SealedString", "looks_sealed"]
