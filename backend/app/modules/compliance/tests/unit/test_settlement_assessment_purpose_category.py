"""The purpose *category* the S0T3 entry point hands to the rule engine.

AL-442 replaced ``PurposeCodeRepository.get_canonical`` with
``get_canonical_history`` — a canonical code may now hold several
non-overlapping validity windows, so "the" canonical row no longer exists
independently of a date. The entry point kept calling the removed method, which
raised ``AttributeError`` at runtime; these tests pin the replacement.

What is being asserted is narrow and deliberate: the row whose window covers
``as_of_date`` is the one whose category reaches ``ComplianceFacts``. Not
today's row — re-running an assessment must not change what a payment was
obliged to do when the money moved.

``evaluate_settlement_compliance`` is stubbed out so the facts are observed
directly. Whether a rule then fires on that category is the rule engine's
business and is covered in test_compliance_rule_evaluation.py; duplicating it
here would only make these tests fail for reasons unrelated to the lookup.
"""

from __future__ import annotations

from datetime import date
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.compliance.application import settlement_assessment
from app.modules.compliance.application.settlement_assessment import (
    evaluate_compliance_rules,
)
from app.modules.compliance.domain.entities.registry import (
    PurposeCategory,
    PurposeCodeCanonical,
)
from app.modules.compliance.domain.jurisdiction import (
    JurisdictionType,
    ResolvingJurisdiction,
)
from app.modules.compliance.domain.ports import ResolvedSectorClassification
from app.modules.compliance.tests.unit.test_purpose_code_validation import (
    FakePurposeCodeRepository,
    _mapping,
)

CORRIDOR = "US_IN"
CODE = "TRADE_GOODS_IMPORT"

#: The date under assessment. Every window below is positioned relative to this
#: so that "active", "future" and "expired" are unambiguous.
AS_OF = date(2026, 8, 12)

#: Every repository the entry point would build from a session is replaced, so
#: nothing ever touches this. Cast rather than annotated because passing None is
#: the point: if a future change starts using the session before the swap, this
#: fails loudly here instead of silently opening a connection in a unit test.
NO_SESSION = cast(AsyncSession, None)


def _canonical(
    category: PurposeCategory,
    effective_from: date,
    effective_to: date | None = None,
) -> PurposeCodeCanonical:
    """A canonical row that is never persisted.

    Category varies per row on purpose: it is the field these tests read back,
    so each window is identifiable by the category it carries.
    """
    return PurposeCodeCanonical(
        canonical_code=CODE,
        description=CODE,
        category=category,
        effective_from=effective_from,
        effective_to=effective_to,
    )


#: A mapping in force for the whole period these tests span, so the corridor
#: lookup never becomes the reason a case fails.
LIVE_MAPPING = _mapping(
    canonical_code=CODE,
    corridor_id=CORRIDOR,
    external_code="P0102",
    effective_from=date(2020, 1, 1),
)


class _StubClassificationLookup:
    """S0T2's answer, held constant. These tests are about the purpose lookup."""

    async def resolve(self, sector_code, corridor_id, country_jurisdiction, as_of_date):
        return ResolvedSectorClassification(
            risk_tier="standard",
            classification_label=None,
            resolving_jurisdiction=ResolvingJurisdiction(
                type=JurisdictionType.FRAMEWORK, value="FATF"
            ),
            found=True,
        )


class _StubAuditSink:
    async def record_threshold_rate_unavailable(self, **kwargs) -> None:
        return None


@pytest.fixture
def captured_facts(monkeypatch):
    """The ComplianceFacts the entry point builds, without evaluating any rule."""
    captured = {}

    async def _capture(facts, repository, rate_provider, **kwargs):
        captured["facts"] = facts
        return None

    monkeypatch.setattr(settlement_assessment, "evaluate_settlement_compliance", _capture)
    return captured


def _use_repository(monkeypatch, repo) -> None:
    """Point the entry point at an in-memory registry.

    The entry point builds its own SQLAlchemy repository from the session, so
    the class is swapped rather than an argument passed — no session is opened
    and no database is touched.
    """
    monkeypatch.setattr(
        settlement_assessment, "SQLAlchemyPurposeCodeRepository", lambda session: repo
    )


async def _resolve_category(monkeypatch, captured_facts, repo) -> str | None:
    _use_repository(monkeypatch, repo)

    await evaluate_compliance_rules(
        session=NO_SESSION,
        sector_code="ANY_SECTOR",
        purpose_code=CODE,
        corridor_id=CORRIDOR,
        send_amount=100_00,
        send_currency="USD",
        as_of_date=AS_OF,
        classification_lookup=_StubClassificationLookup(),
        audit_sink=_StubAuditSink(),
    )

    return captured_facts["facts"].purpose_code


# ── the regression itself ─────────────────────────────────────────────────────


async def test_the_entry_point_no_longer_calls_the_removed_get_canonical():
    """AL-442 removed the method; nothing may depend on it again.

    Asserted against the protocol rather than the SQLAlchemy class so that an
    adapter re-adding the method locally still fails here.
    """
    from app.modules.compliance.domain.ports import PurposeCodeRepository

    assert not hasattr(PurposeCodeRepository, "get_canonical")
    assert hasattr(PurposeCodeRepository, "get_canonical_history")


# ── which window wins ─────────────────────────────────────────────────────────


async def test_the_version_in_force_on_the_as_of_date_supplies_the_category(
    monkeypatch, captured_facts
):
    repo = FakePurposeCodeRepository(
        [_canonical(PurposeCategory.TRADE, date(2024, 1, 1))], [LIVE_MAPPING]
    )

    assert await _resolve_category(monkeypatch, captured_facts, repo) == "trade"


async def test_a_version_that_has_not_started_yet_is_ignored(monkeypatch, captured_facts):
    """A recategorisation published for next year must not reach a payment made
    today, even though its row is already in the registry."""
    repo = FakePurposeCodeRepository(
        [
            _canonical(PurposeCategory.TRADE, date(2024, 1, 1), date(2027, 1, 1)),
            _canonical(PurposeCategory.INVESTMENT, date(2027, 1, 1)),
        ],
        [LIVE_MAPPING],
    )

    assert await _resolve_category(monkeypatch, captured_facts, repo) == "trade"


async def test_an_expired_version_is_ignored(monkeypatch, captured_facts):
    """The mirror image: the superseded window must not win once it has closed."""
    repo = FakePurposeCodeRepository(
        [
            _canonical(PurposeCategory.SERVICES, date(2020, 1, 1), date(2025, 1, 1)),
            _canonical(PurposeCategory.TRADE, date(2025, 1, 1)),
        ],
        [LIVE_MAPPING],
    )

    assert await _resolve_category(monkeypatch, captured_facts, repo) == "trade"


async def test_a_retired_then_reinstated_code_selects_the_reinstated_window(
    monkeypatch, captured_facts
):
    """The case that motivated get_canonical_history.

    Two rows with a genuine three-year gap between them, and ``as_of_date``
    inside the reinstated window. The old single-row API had no way to express
    this — whichever row it returned was a guess.
    """
    repo = FakePurposeCodeRepository(
        [
            _canonical(PurposeCategory.SERVICES, date(2020, 1, 1), date(2023, 1, 1)),
            _canonical(PurposeCategory.PERSONAL, date(2026, 1, 1)),
        ],
        [LIVE_MAPPING],
    )

    assert await _resolve_category(monkeypatch, captured_facts, repo) == "personal"


async def test_a_date_inside_the_retirement_gap_is_covered_by_no_window(
    monkeypatch, captured_facts
):
    """Half-open windows, checked at the boundary the gap creates.

    ``validate_purpose_code`` rejects this case before the category is read, so
    it is asserted through the same resolution the entry point performs rather
    than through the entry point itself.
    """
    from app.modules.compliance.domain.policies.effectivity import is_effective_at

    history = [
        _canonical(PurposeCategory.SERVICES, date(2020, 1, 1), date(2023, 1, 1)),
        _canonical(PurposeCategory.PERSONAL, date(2026, 1, 1)),
    ]

    covering = [
        c for c in history if is_effective_at(c.effective_from, c.effective_to, date(2024, 6, 1))
    ]

    assert covering == []


async def test_no_effective_version_leaves_the_category_unset(monkeypatch, captured_facts):
    """The defensive branch.

    ``validate_purpose_code`` runs first and rejects a code with no window
    covering the date, so this is unreachable through the public path today. It
    is pinned anyway: the fallback must be ``None`` — an absent category matches
    no rule — and never an ``AttributeError`` on ``None.category``, which is the
    shape of failure this whole file exists to prevent.
    """

    async def _skip_validation(*args, **kwargs):
        return None

    monkeypatch.setattr(settlement_assessment, "validate_purpose_code", _skip_validation)

    repo = FakePurposeCodeRepository(
        [_canonical(PurposeCategory.TRADE, date(2020, 1, 1), date(2023, 1, 1))], [LIVE_MAPPING]
    )

    assert await _resolve_category(monkeypatch, captured_facts, repo) is None


async def test_an_unknown_code_leaves_the_category_unset(monkeypatch, captured_facts):
    """Empty history, same contract: no category rather than an exception."""

    async def _skip_validation(*args, **kwargs):
        return None

    monkeypatch.setattr(settlement_assessment, "validate_purpose_code", _skip_validation)

    assert await _resolve_category(monkeypatch, captured_facts, FakePurposeCodeRepository()) is None


# ── the category is what rules are written against ────────────────────────────


async def test_the_category_is_passed_not_the_canonical_code(monkeypatch, captured_facts):
    """Rules match on the category vocabulary, so the canonical code must not
    leak into the facts in its place."""
    repo = FakePurposeCodeRepository(
        [_canonical(PurposeCategory.SERVICES, date(2024, 1, 1))], [LIVE_MAPPING]
    )

    category = await _resolve_category(monkeypatch, captured_facts, repo)

    assert category == "services"
    assert category != CODE


async def test_the_as_of_date_reaches_the_facts_unchanged(monkeypatch, captured_facts):
    """Effectivity downstream is judged on the same date this lookup used."""
    repo = FakePurposeCodeRepository(
        [_canonical(PurposeCategory.TRADE, date(2024, 1, 1))], [LIVE_MAPPING]
    )
    _use_repository(monkeypatch, repo)

    await evaluate_compliance_rules(
        session=NO_SESSION,
        sector_code="ANY_SECTOR",
        purpose_code=CODE,
        corridor_id=CORRIDOR,
        send_amount=100_00,
        send_currency="USD",
        as_of_date=AS_OF,
        classification_lookup=_StubClassificationLookup(),
        audit_sink=_StubAuditSink(),
    )

    assert captured_facts["facts"].as_of_date == AS_OF
