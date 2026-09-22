"""Structured purpose-code resolution failures.

Resolving a purpose code answers "what code does this corridor's regulator
require for this payment, on this date". Every way that can fail is one class
here, carrying an ``error_code`` and the lookup that failed rather than a
free-text message a caller would have to parse.

These inherit :class:`AnerBaseException`, so the handler registered in
``app/main.py`` renders them with their own status code. A bare ``Exception``
would fall through to the catch-all handler and surface as 500 — telling the
caller the platform broke when in fact their purpose code was rejected.

**Who is at fault decides the status code.** A code that does not exist, is
retired, or has no mapping on the corridor is the caller's input: 422, and the
caller fixes the request. An ambiguous mapping is *our* reference data being
wrong — the caller sent a perfectly good code — so it is a 500 that should page
whoever owns the GitOps seed files, not a validation message blaming the caller.
"""
from __future__ import annotations

from datetime import date

from app.shared.exceptions import AnerBaseException


class PurposeCodeError(AnerBaseException):
    """Base for every purpose-code resolution failure.

    Collects the lookup that failed into ``extensions`` so the API response and
    the log line both carry it without the caller parsing ``detail``. Dates are
    stringified here because ``extensions`` is serialised straight into the JSON
    body, and ``json.dumps`` cannot encode a ``date``.
    """

    error_code = "PURPOSE_CODE_ERROR"
    status_code = 422

    def __init__(
        self,
        detail: str,
        *,
        canonical_code: str | None = None,
        corridor_id: str | None = None,
        transaction_date: date | None = None,
        **extra: object,
    ) -> None:
        extensions: dict[str, object] = {
            "canonical_code": canonical_code,
            "corridor_id": corridor_id,
            "transaction_date": transaction_date.isoformat() if transaction_date else None,
            **extra,
        }
        super().__init__(
            detail=detail,
            error_code=self.error_code,
            status_code=self.status_code,
            extensions={k: v for k, v in extensions.items() if v is not None},
        )


class PurposeCodeInputError(PurposeCodeError):
    """A required lookup input was missing.

    Its own class because the alternative is worse: a null ``transaction_date``
    reaches the date comparison and raises ``TypeError``, which is a 500 for what
    is plainly a bad request.
    """

    error_code = "PURPOSE_CODE_INPUT_MISSING"
    status_code = 422


class PurposeCodeNotFoundError(PurposeCodeError):
    """No canonical code by that name exists in the registry."""

    error_code = "PURPOSE_CODE_NOT_FOUND"
    status_code = 422


class PurposeCodeNotEffectiveError(PurposeCodeError):
    """The canonical code exists but is outside its effectivity window.

    Distinct from not-found on purpose: the caller is using a code that was or
    will be real, so the fix is a different code or a corrected transaction date,
    not a typo hunt.
    """

    error_code = "PURPOSE_CODE_NOT_EFFECTIVE"
    status_code = 422


class PurposeCodeNotValidForCorridorError(PurposeCodeError):
    """The code is live, but this corridor has no mapping in force for it.

    Covers both "no mapping row at all" and "a mapping row outside its window".
    The two are deliberately indistinguishable to the caller — either way this
    corridor cannot carry this purpose today, and the remedy is a GitOps seed
    change rather than anything the caller can do differently.
    """

    error_code = "PURPOSE_CODE_NOT_VALID_FOR_CORRIDOR"
    status_code = 422


class AmbiguousPurposeCodeMappingError(PurposeCodeError):
    """More than one mapping is in force for the same code, corridor, and date.

    A 500, not a 422: the caller did nothing wrong. Two overlapping seed rows
    differ by ``external_code``, so ``uq_purpose_code_mapping`` permits them and
    nothing catches the overlap until a payment needs resolving. Guessing one
    would put an arbitrary regulatory code on a real payment, so this fails
    instead. ``external_codes`` names the conflicting rows for whoever fixes the
    seed data.
    """

    error_code = "PURPOSE_CODE_MAPPING_AMBIGUOUS"
    status_code = 500
