"""The ``change_reason`` every request that changes a live settings rule must carry.

The rule itself is ``domain/change_reason.py``; this type applies it at the edge, so a
missing or vague reason is a 422 on the ``change_reason`` field before any service runs,
and the value that reaches the service is already trimmed. The services check it again —
they are the authority, and not every caller comes through a request.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, Field
from pydantic_core import PydanticCustomError

from app.modules.onboarding.domain.change_reason import (
    MAX_LENGTH,
    change_reason_problem,
    clean_change_reason,
)


def _valid_change_reason(value: str) -> str:
    problem = change_reason_problem(value)
    if problem is not None:
        # A custom error, so the message reaches the form as written — a plain
        # ValueError would arrive prefixed "Value error, ".
        raise PydanticCustomError("change_reason", problem)
    return clean_change_reason(value)


ChangeReason = Annotated[
    str,
    Field(
        # Room for surrounding whitespace; the cleaned value is held to MAX_LENGTH.
        max_length=MAX_LENGTH * 2,
        description=(
            "Why this change is being made: a ticket number (e.g. CHG-1042) or an "
            "explanation of at least three words. Required; kept on the version this "
            "request writes."
        ),
        examples=["CHG-1042: raise the turnover floor agreed by credit committee"],
    ),
    AfterValidator(_valid_change_reason),
]

__all__ = ["ChangeReason"]
