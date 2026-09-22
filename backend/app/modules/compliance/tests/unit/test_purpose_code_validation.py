"""``validate_purpose_code`` against an in-memory repository — no database.

The rules this function encodes (canonical effectivity gates the corridor lookup,
an inactive mapping is indistinguishable from a missing one, two live mappings
are an error rather than a coin flip) are pure logic. Driving them through
Postgres, as the integration suite does, proves the wiring but makes each branch
cost a seed reload; here every branch is one dictionary.

The fake satisfies :class:`PurposeCodeRepository`, so a change to the protocol
that this fake does not follow shows up as a failure here.
"""
from datetime import date

import pytest

from app.modules.compliance.application.validation import (
    AmbiguousPurposeCodeMappingError,
    PurposeCodeInputError,
    PurposeCodeNotEffectiveError,
    PurposeCodeNotFoundError,
    PurposeCodeNotValidForCorridorError,
    validate_purpose_code,
)
from app.modules.compliance.domain.entities.registry import (
    PurposeCategory,
    PurposeCodeCanonical,
    PurposeCodeCorridorMapping,
)
from app.modules.compliance.domain.ports import PurposeCodeRepository


def _canonical(
    canonical_code: str,
    effective_from: date,
    effective_to: date | None = None,
) -> PurposeCodeCanonical:
    """A canonical row that is never persisted.

    The mapped class is used rather than a look-alike so the fake genuinely
    satisfies the protocol's declared return types; a stand-in would type-check
    only because nothing was checking it. A model that is never added to a
    session is a plain object — no session, no database.
    """
    return PurposeCodeCanonical(
        canonical_code=canonical_code,
        description=canonical_code,
        category=PurposeCategory.OTHER,
        effective_from=effective_from,
        effective_to=effective_to,
    )


V2024 = "RBI Purpose Code Master Circular 2024"
V2025 = "RBI Purpose Code Master Circular 2025"


def _mapping(
    canonical_code: str,
    corridor_id: str,
    external_code: str,
    effective_from: date,
    effective_to: date | None = None,
    external_standard: str = "RBI",
    external_standard_version: str = V2024,
) -> PurposeCodeCorridorMapping:
    return PurposeCodeCorridorMapping(
        canonical_code=canonical_code,
        corridor_id=corridor_id,
        external_standard=external_standard,
        external_standard_version=external_standard_version,
        external_code=external_code,
        effective_from=effective_from,
        effective_to=effective_to,
    )


class FakePurposeCodeRepository(PurposeCodeRepository):
    """In-memory PurposeCodeRepository.

    Filtering by effectivity is deliberately absent: the real SQLAlchemy
    repository returns every row for the code (or mapping) and leaves the date
    decision to the application layer. A fake that pre-filtered would hide the
    very branch these tests exist to cover — including the regression this file
    guards against, where a retired-then-reinstated canonical_code has two rows
    and picking the wrong one silently rejects or misresolves a valid lookup.
    """

    def __init__(
        self,
        canonicals: list[PurposeCodeCanonical] | None = None,
        mappings: list[PurposeCodeCorridorMapping] | None = None,
    ):
        self._canonicals = list(canonicals or [])
        self._mappings = list(mappings or [])

    async def get_canonical_history(self, canonical_code: str) -> list[PurposeCodeCanonical]:
        return sorted(
            (c for c in self._canonicals if c.canonical_code == canonical_code),
            key=lambda c: c.effective_from,
        )

    async def get_corridor_mappings(
        self, canonical_code: str, corridor_id: str
    ) -> list[PurposeCodeCorridorMapping]:
        return [
            m
            for m in self._mappings
            if m.canonical_code == canonical_code and m.corridor_id == corridor_id
        ]

    async def get_mappings(
        self, corridor_id: str, external_code: str
    ) -> list[PurposeCodeCorridorMapping]:
        return [
            m
            for m in self._mappings
            if m.corridor_id == corridor_id and m.external_code == external_code
        ]


TRADE = _canonical("TRADE_GOODS_IMPORT", date(2020, 1, 1))

US_IN_CURRENT = _mapping(
    canonical_code="TRADE_GOODS_IMPORT",
    corridor_id="US_IN",
    external_code="P0102",
    effective_from=date(2024, 1, 1),
)

US_IN_SUPERSEDED = _mapping(
    canonical_code="TRADE_GOODS_IMPORT",
    corridor_id="US_IN",
    external_code="P0102_OLD",
    effective_from=date(2020, 1, 1),
    effective_to=date(2024, 1, 1),
)


async def test_resolves_to_the_external_code_for_the_corridor():
    repo = FakePurposeCodeRepository([TRADE], [US_IN_CURRENT])

    result = await validate_purpose_code(
        canonical_code="TRADE_GOODS_IMPORT",
        corridor_id="US_IN",
        transaction_date=date(2024, 6, 1),
        repository=repo,
    )

    assert result.external_code == "P0102"
    assert result.external_standard == "RBI"
    assert result.external_standard_version == V2024


async def test_unknown_canonical_code_is_rejected():
    repo = FakePurposeCodeRepository([TRADE], [US_IN_CURRENT])

    with pytest.raises(PurposeCodeNotFoundError):
        await validate_purpose_code(
            canonical_code="NO_SUCH_CODE",
            corridor_id="US_IN",
            transaction_date=date(2024, 6, 1),
            repository=repo,
        )


async def test_canonical_code_not_yet_in_force_is_rejected():
    repo = FakePurposeCodeRepository(
        [_canonical("FUTURE_CODE", date(2025, 1, 1))],
        [
            _mapping(
                canonical_code="FUTURE_CODE",
                corridor_id="US_IN",
                external_code="F100",
                effective_from=date(2025, 1, 1),
            )
        ],
    )

    with pytest.raises(PurposeCodeNotEffectiveError):
        await validate_purpose_code(
            canonical_code="FUTURE_CODE",
            corridor_id="US_IN",
            transaction_date=date(2024, 12, 31),
            repository=repo,
        )


async def test_retired_canonical_code_is_rejected():
    repo = FakePurposeCodeRepository(
        [_canonical("RETIRED_CODE", date(2023, 1, 1), date(2024, 1, 1))],
        [
            _mapping(
                canonical_code="RETIRED_CODE",
                corridor_id="US_IN",
                external_code="P9999",
                effective_from=date(2023, 1, 1),
            )
        ],
    )

    with pytest.raises(PurposeCodeNotEffectiveError):
        await validate_purpose_code(
            canonical_code="RETIRED_CODE",
            corridor_id="US_IN",
            transaction_date=date(2024, 6, 1),
            repository=repo,
        )


async def test_canonical_effectivity_is_checked_before_the_corridor():
    """A retired code asked for on an unmapped corridor reports the retirement,
    not the missing mapping. The order matters to the caller: one means "stop
    using this code", the other means "this corridor needs a mapping"."""
    repo = FakePurposeCodeRepository(
        [_canonical("RETIRED_CODE", date(2023, 1, 1), date(2024, 1, 1))],
        [],
    )

    with pytest.raises(PurposeCodeNotEffectiveError):
        await validate_purpose_code(
            canonical_code="RETIRED_CODE",
            corridor_id="UNMAPPED",
            transaction_date=date(2024, 6, 1),
            repository=repo,
        )


async def test_canonical_code_with_no_mapping_for_the_corridor_is_rejected():
    """The code is live, but nobody has told us what to call it on this rail."""
    repo = FakePurposeCodeRepository([TRADE], [US_IN_CURRENT])

    with pytest.raises(PurposeCodeNotValidForCorridorError):
        await validate_purpose_code(
            canonical_code="TRADE_GOODS_IMPORT",
            corridor_id="EUR_IN",
            transaction_date=date(2024, 6, 1),
            repository=repo,
        )


async def test_mapping_outside_its_window_is_treated_as_absent():
    """Distinct from the case above: a mapping row exists for this corridor, it
    is simply not in force on the transaction date. Both surface as the same
    error, and this test pins that — a caller cannot act differently on them."""
    repo = FakePurposeCodeRepository([TRADE], [US_IN_SUPERSEDED])

    with pytest.raises(PurposeCodeNotValidForCorridorError):
        await validate_purpose_code(
            canonical_code="TRADE_GOODS_IMPORT",
            corridor_id="US_IN",
            transaction_date=date(2024, 6, 1),
            repository=repo,
        )


async def test_backdated_transaction_resolves_to_the_mapping_in_force_then():
    """Both mappings are returned by the repository; the date picks one. A
    payment dated before the RBI code changed must still carry the old code."""
    repo = FakePurposeCodeRepository([TRADE], [US_IN_SUPERSEDED, US_IN_CURRENT])

    result = await validate_purpose_code(
        canonical_code="TRADE_GOODS_IMPORT",
        corridor_id="US_IN",
        transaction_date=date(2023, 6, 1),
        repository=repo,
    )

    assert result.external_code == "P0102_OLD"


async def test_successor_mapping_takes_over_on_the_changeover_date():
    """The old window ends and the new one begins on 2024-01-01. Exactly one is
    in force that day — proof the two windows abut instead of overlapping."""
    repo = FakePurposeCodeRepository([TRADE], [US_IN_SUPERSEDED, US_IN_CURRENT])

    result = await validate_purpose_code(
        canonical_code="TRADE_GOODS_IMPORT",
        corridor_id="US_IN",
        transaction_date=date(2024, 1, 1),
        repository=repo,
    )

    assert result.external_code == "P0102"


async def test_open_ended_mapping_still_resolves_far_in_the_future():
    repo = FakePurposeCodeRepository([TRADE], [US_IN_CURRENT])

    result = await validate_purpose_code(
        canonical_code="TRADE_GOODS_IMPORT",
        corridor_id="US_IN",
        transaction_date=date(2099, 1, 1),
        repository=repo,
    )

    assert result.external_code == "P0102"


async def test_two_mappings_in_force_at_once_is_an_error_not_a_guess():
    """Overlapping windows are a seed-data defect. Picking either code would put
    a wrong purpose code on a real payment, so the ambiguity is raised instead.
    The DB unique constraint cannot catch this: the rows differ by external_code,
    which is part of the key."""
    repo = FakePurposeCodeRepository(
        [_canonical("AMBIGUOUS_CODE", date(2024, 1, 1))],
        [
            _mapping(
                canonical_code="AMBIGUOUS_CODE",
                corridor_id="US_IN",
                external_code="A1",
                effective_from=date(2024, 1, 1),
            ),
            _mapping(
                canonical_code="AMBIGUOUS_CODE",
                corridor_id="US_IN",
                external_code="A2",
                effective_from=date(2024, 1, 1),
            ),
        ],
    )

    with pytest.raises(AmbiguousPurposeCodeMappingError):
        await validate_purpose_code(
            canonical_code="AMBIGUOUS_CODE",
            corridor_id="US_IN",
            transaction_date=date(2024, 6, 1),
            repository=repo,
        )


async def test_expired_sibling_does_not_make_a_live_mapping_ambiguous():
    """Guards the boundary of the rule above: the ambiguity check counts only
    mappings in force, so a superseded row must not trip it."""
    repo = FakePurposeCodeRepository([TRADE], [US_IN_SUPERSEDED, US_IN_CURRENT])

    result = await validate_purpose_code(
        canonical_code="TRADE_GOODS_IMPORT",
        corridor_id="US_IN",
        transaction_date=date(2024, 6, 1),
        repository=repo,
    )

    assert result.external_code == "P0102"


async def test_missing_canonical_code_is_rejected():
    repo = FakePurposeCodeRepository([TRADE], [US_IN_CURRENT])

    with pytest.raises(PurposeCodeInputError):
        await validate_purpose_code(
            canonical_code=None,  # type: ignore[arg-type]
            corridor_id="US_IN",
            transaction_date=date(2024, 6, 1),
            repository=repo,
        )


async def test_missing_corridor_id_is_rejected():
    repo = FakePurposeCodeRepository([TRADE], [US_IN_CURRENT])

    with pytest.raises(PurposeCodeInputError):
        await validate_purpose_code(
            canonical_code="TRADE_GOODS_IMPORT",
            corridor_id=None,  # type: ignore[arg-type]
            transaction_date=date(2024, 6, 1),
            repository=repo,
        )


async def test_missing_transaction_date_is_rejected():
    """Without the input guard this is a TypeError from the date comparison —
    a 500 for what is plainly a malformed request."""
    repo = FakePurposeCodeRepository([TRADE], [US_IN_CURRENT])

    with pytest.raises(PurposeCodeInputError):
        await validate_purpose_code(
            canonical_code="TRADE_GOODS_IMPORT",
            corridor_id="US_IN",
            transaction_date=None,  # type: ignore[arg-type]
            repository=repo,
        )


# ── The errors are structured, not just typed ────────────────────────────────

async def test_rejections_carry_an_error_code_and_a_caller_fault_status():
    """Every caller-input rejection must render as a 422 with its own code.

    Inheriting AnerBaseException is what routes these through the structured
    handler; a bare Exception would hit the catch-all and surface as a 500,
    telling the caller the platform broke when their code was simply rejected.
    """
    repo = FakePurposeCodeRepository(
        [_canonical("RETIRED_CODE", date(2023, 1, 1), date(2024, 1, 1)), TRADE],
        [US_IN_CURRENT],
    )

    cases = [
        (PurposeCodeInputError, "PURPOSE_CODE_INPUT_MISSING", None, "US_IN"),
        (PurposeCodeNotFoundError, "PURPOSE_CODE_NOT_FOUND", "NO_SUCH_CODE", "US_IN"),
        (PurposeCodeNotEffectiveError, "PURPOSE_CODE_NOT_EFFECTIVE", "RETIRED_CODE", "US_IN"),
        (
            PurposeCodeNotValidForCorridorError,
            "PURPOSE_CODE_NOT_VALID_FOR_CORRIDOR",
            "TRADE_GOODS_IMPORT",
            "EUR_IN",
        ),
    ]

    for expected_type, expected_code, canonical_code, corridor_id in cases:
        with pytest.raises(expected_type) as exc:
            await validate_purpose_code(
                canonical_code=canonical_code,  # type: ignore[arg-type]
                corridor_id=corridor_id,
                transaction_date=date(2024, 6, 1),
                repository=repo,
            )

        assert exc.value.error_code == expected_code
        assert exc.value.status_code == 422
        assert exc.value.detail


async def test_ambiguous_mapping_is_our_fault_not_the_callers():
    """Overlapping seed rows are a reference-data defect. A 422 would tell the
    caller to fix a request that was already correct, so this is a 500 — and it
    names the conflicting codes for whoever repairs the GitOps files."""
    repo = FakePurposeCodeRepository(
        [_canonical("AMBIGUOUS_CODE", date(2024, 1, 1))],
        [
            _mapping(
                canonical_code="AMBIGUOUS_CODE",
                corridor_id="US_IN",
                external_code="A1",
                effective_from=date(2024, 1, 1),
            ),
            _mapping(
                canonical_code="AMBIGUOUS_CODE",
                corridor_id="US_IN",
                external_code="A2",
                effective_from=date(2024, 1, 1),
            ),
        ],
    )

    with pytest.raises(AmbiguousPurposeCodeMappingError) as exc:
        await validate_purpose_code(
            canonical_code="AMBIGUOUS_CODE",
            corridor_id="US_IN",
            transaction_date=date(2024, 6, 1),
            repository=repo,
        )

    assert exc.value.status_code == 500
    assert exc.value.error_code == "PURPOSE_CODE_MAPPING_AMBIGUOUS"
    assert exc.value.extensions["external_codes"] == ["A1", "A2"]


async def test_rejections_carry_the_failed_lookup_as_json_safe_context():
    """extensions is serialised straight into the response body, so a raw date
    object here would raise TypeError inside the error handler — turning a clean
    422 into a 500 at the last step."""
    import json

    repo = FakePurposeCodeRepository([TRADE], [US_IN_CURRENT])

    with pytest.raises(PurposeCodeNotValidForCorridorError) as exc:
        await validate_purpose_code(
            canonical_code="TRADE_GOODS_IMPORT",
            corridor_id="EUR_IN",
            transaction_date=date(2024, 6, 1),
            repository=repo,
        )

    assert exc.value.extensions["canonical_code"] == "TRADE_GOODS_IMPORT"
    assert exc.value.extensions["corridor_id"] == "EUR_IN"
    assert exc.value.extensions["transaction_date"] == "2024-06-01"
    json.dumps(exc.value.extensions)


async def test_effectivity_rejection_reports_the_window_it_failed():
    """The caller cannot fix a date they cannot see."""
    repo = FakePurposeCodeRepository(
        [_canonical("RETIRED_CODE", date(2023, 1, 1), date(2024, 1, 1))], []
    )

    with pytest.raises(PurposeCodeNotEffectiveError) as exc:
        await validate_purpose_code(
            canonical_code="RETIRED_CODE",
            corridor_id="US_IN",
            transaction_date=date(2024, 6, 1),
            repository=repo,
        )

    assert exc.value.extensions["effective_from"] == "2023-01-01"
    assert exc.value.extensions["effective_to"] == "2024-01-01"


async def test_open_ended_code_omits_the_empty_end_of_window():
    """None is dropped from extensions rather than serialised as null — an
    open-ended code has no end date, and reporting one would be a lie."""
    repo = FakePurposeCodeRepository([TRADE], [])

    with pytest.raises(PurposeCodeNotValidForCorridorError) as exc:
        await validate_purpose_code(
            canonical_code="TRADE_GOODS_IMPORT",
            corridor_id="US_IN",
            transaction_date=date(2024, 6, 1),
            repository=repo,
        )

    assert "effective_to" not in exc.value.extensions


# ── Standard revisions ───────────────────────────────────────────────────────

TRADE_V2024 = _mapping(
    canonical_code="TRADE_GOODS_IMPORT",
    corridor_id="US_IN",
    external_code="P0102",
    effective_from=date(2024, 1, 1),
    effective_to=date(2025, 1, 1),
    external_standard_version=V2024,
)

TRADE_V2025 = _mapping(
    canonical_code="TRADE_GOODS_IMPORT",
    corridor_id="US_IN",
    external_code="P0103",
    effective_from=date(2025, 1, 1),
    external_standard_version=V2025,
)


async def test_transaction_before_the_revision_gets_the_old_code_and_version():
    """A payment dated under the 2024 circular must stay filed under it, code and
    citation together — the pair is what makes the filing explicable later."""
    repo = FakePurposeCodeRepository([TRADE], [TRADE_V2024, TRADE_V2025])

    result = await validate_purpose_code(
        canonical_code="TRADE_GOODS_IMPORT",
        corridor_id="US_IN",
        transaction_date=date(2024, 6, 1),
        repository=repo,
    )

    assert result.external_code == "P0102"
    assert result.external_standard_version == V2024


async def test_transaction_after_the_revision_gets_the_new_code_and_version():
    repo = FakePurposeCodeRepository([TRADE], [TRADE_V2024, TRADE_V2025])

    result = await validate_purpose_code(
        canonical_code="TRADE_GOODS_IMPORT",
        corridor_id="US_IN",
        transaction_date=date(2025, 6, 1),
        repository=repo,
    )

    assert result.external_code == "P0103"
    assert result.external_standard_version == V2025


async def test_the_revision_boundary_belongs_to_the_new_version():
    """2025-01-01 both ends the old window and starts the new one. Exactly one
    mapping is in force that day — if both were, this would raise instead."""
    repo = FakePurposeCodeRepository([TRADE], [TRADE_V2024, TRADE_V2025])

    result = await validate_purpose_code(
        canonical_code="TRADE_GOODS_IMPORT",
        corridor_id="US_IN",
        transaction_date=date(2025, 1, 1),
        repository=repo,
    )

    assert result.external_standard_version == V2025


async def test_overlapping_revisions_are_ambiguous_rather_than_a_guess():
    """The database permits this: external_standard_version is part of the
    exclusion key, so two revisions may cover the same corridor and date. The
    application is the only thing that catches it, which is why the check stays.
    """
    overlapping = _mapping(
        canonical_code="TRADE_GOODS_IMPORT",
        corridor_id="US_IN",
        external_code="P0104",
        effective_from=date(2024, 1, 1),
        external_standard_version=V2025,
    )
    repo = FakePurposeCodeRepository([TRADE], [US_IN_CURRENT, overlapping])

    with pytest.raises(AmbiguousPurposeCodeMappingError) as exc:
        await validate_purpose_code(
            canonical_code="TRADE_GOODS_IMPORT",
            corridor_id="US_IN",
            transaction_date=date(2024, 6, 1),
            repository=repo,
        )

    assert exc.value.extensions["external_standard_versions"] == [V2024, V2025]


# ── Canonical codes with a history (retired, then reinstated) ────────────────
#
# ex_purpose_code_canonical_validity permits a second row for one canonical_code
# once the first row's window has closed. The repository has to return every
# such row and let validate_purpose_code pick the one whose window covers
# transaction_date — a lookup that grabs "whichever row comes back first" would
# silently reject a date that a later or earlier window actually covers, or
# resolve against the wrong window's category/description.

RETIRED_WINDOW = _canonical("REINSTATED_CODE", date(2020, 1, 1), date(2022, 1, 1))
REINSTATED_WINDOW = _canonical("REINSTATED_CODE", date(2024, 1, 1), None)

REINSTATED_MAPPING = _mapping(
    canonical_code="REINSTATED_CODE",
    corridor_id="US_IN",
    external_code="R100",
    effective_from=date(2020, 1, 1),
)


async def test_a_transaction_in_the_reinstated_window_resolves():
    """The regression this suite exists to catch: a naive lookup could return
    the 2020-2022 row for a 2024 transaction_date and wrongly reject it as not
    effective, even though the code is live again under the second row."""
    repo = FakePurposeCodeRepository([RETIRED_WINDOW, REINSTATED_WINDOW], [REINSTATED_MAPPING])

    result = await validate_purpose_code(
        canonical_code="REINSTATED_CODE",
        corridor_id="US_IN",
        transaction_date=date(2024, 6, 1),
        repository=repo,
    )

    assert result.external_code == "R100"


async def test_a_transaction_in_the_original_window_still_resolves():
    """The mirror case: a lookup that always preferred the newest row would
    wrongly reject a genuinely historical transaction from the first window."""
    repo = FakePurposeCodeRepository([RETIRED_WINDOW, REINSTATED_WINDOW], [REINSTATED_MAPPING])

    result = await validate_purpose_code(
        canonical_code="REINSTATED_CODE",
        corridor_id="US_IN",
        transaction_date=date(2021, 6, 1),
        repository=repo,
    )

    assert result.external_code == "R100"


async def test_a_transaction_in_the_gap_between_windows_is_rejected():
    """2022-2024 is retired: covered by neither row. Confirms the fix does not
    overcorrect into treating the code as always effective once it has ever
    existed."""
    repo = FakePurposeCodeRepository([RETIRED_WINDOW, REINSTATED_WINDOW], [REINSTATED_MAPPING])

    with pytest.raises(PurposeCodeNotEffectiveError) as exc:
        await validate_purpose_code(
            canonical_code="REINSTATED_CODE",
            corridor_id="US_IN",
            transaction_date=date(2023, 1, 1),
            repository=repo,
        )

    # No single window to blame — both are reported so the caller can see the
    # code's whole history rather than being told about a window that was
    # never in force on the requested date.
    assert exc.value.extensions["effective_windows"] == [
        {"effective_from": "2020-01-01", "effective_to": "2022-01-01"},
        {"effective_from": "2024-01-01", "effective_to": None},
    ]
    assert "effective_from" not in exc.value.extensions
    assert "effective_to" not in exc.value.extensions


async def test_a_transaction_before_the_first_window_is_rejected():
    """Also outside both windows, at the other edge — must not be confused with
    the reinstated window just because a row exists somewhere in the future."""
    repo = FakePurposeCodeRepository([RETIRED_WINDOW, REINSTATED_WINDOW], [REINSTATED_MAPPING])

    with pytest.raises(PurposeCodeNotEffectiveError) as exc:
        await validate_purpose_code(
            canonical_code="REINSTATED_CODE",
            corridor_id="US_IN",
            transaction_date=date(2019, 1, 1),
            repository=repo,
        )

    assert len(exc.value.extensions["effective_windows"]) == 2


async def test_reinstated_code_history_order_does_not_affect_resolution():
    """The repository is not required to return rows in any particular order;
    validate_purpose_code must find the covering window regardless."""
    repo = FakePurposeCodeRepository([REINSTATED_WINDOW, RETIRED_WINDOW], [REINSTATED_MAPPING])

    result = await validate_purpose_code(
        canonical_code="REINSTATED_CODE",
        corridor_id="US_IN",
        transaction_date=date(2021, 6, 1),
        repository=repo,
    )

    assert result.external_code == "R100"
