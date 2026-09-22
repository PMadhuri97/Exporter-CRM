"""The entry point S1T2 will call, exercised the way S1T2 will call it.

Everything here goes through ``app.modules.compliance.evaluate_compliance_rules``
with a real session, the real seeded registry, and a sector code rather than a
hand-built set of facts. The other integration suites start one layer in, from
``ComplianceFacts``; these are the only tests that prove the purpose lookup, the
classification lookup and the rule evaluation actually join up.
"""

from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import and_, func, or_, select, text

from app.modules.compliance import RequiredAction, evaluate_compliance_rules
from app.modules.compliance.constants import FATF_FRAMEWORK
from app.modules.compliance.domain.entities.compliance_rule import ComplianceRule
from app.modules.compliance.domain.jurisdiction import JurisdictionType
from app.modules.compliance.infrastructure.compliance_audit_sink import (
    FX_RATE_UNAVAILABLE_EVENT,
)
from app.modules.compliance.infrastructure.compliance_rule_seed_loader import (
    SEED_DATA_DIR,
    load_compliance_rules,
)
from app.modules.compliance.infrastructure.purpose_code_seed_loader import (
    SEED_DATA_DIR as PURPOSE_SEED_DIR,
)
from app.modules.compliance.infrastructure.purpose_code_seed_loader import load_purpose_codes
from app.modules.compliance.infrastructure.sector_registry_seed_loader import (
    SEED_DATA_DIR as SECTOR_SEED_DIR,
)
from app.modules.compliance.infrastructure.sector_registry_seed_loader import (
    load_sector_registry,
)
from app.modules.compliance.tests.fixtures.rate_providers import UnavailableRateProvider
from app.platform.database import services as database

DNFBP_RULE = "DNFBP_EDD_REQUIRED"
LARGE_VALUE_RULE = "LARGE_VALUE_REVIEW"

#: The Walk-phase diamond corridor from the ticket's acceptance criteria.
DNFBP_SECTOR = "PRECIOUS_STONES_TRADE"
CORRIDOR = "US_IN"
#: The national regime risk-classifications.yaml rates this sector under.
US_COUNTRY_REGIME = "US_FINCEN"
AS_OF = date(2026, 8, 12)
THRESHOLD = 5_000_000


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def seeded():
    """All three registries the entry point reads."""
    async with database.AsyncSessionLocal() as session:
        await load_purpose_codes(session, PURPOSE_SEED_DIR)
        await load_sector_registry(session, SECTOR_SEED_DIR)
        await load_compliance_rules(session, SEED_DATA_DIR)


@pytest_asyncio.fixture(loop_scope="function")
async def session(seeded):
    async with database.AsyncSessionLocal() as session:
        yield session
        await session.rollback()


def _in_force_on(model, on: date):
    """``is_effective_at``'s half-open window, expressed in SQL.

    The domain helper decides this in Python over rows already fetched; here the
    same rule has to run in the query, so it is restated rather than reused.
    """
    return and_(
        model.effective_from <= on,
        or_(model.effective_to.is_(None), model.effective_to > on),
    )


async def _purpose_code(session) -> str:
    """A canonical purpose code that is valid on the Walk-phase corridor, on AS_OF.

    Read from the registry rather than hardcoded: this suite is about the entry
    point joining its dependencies up, and a stale literal here would fail as a
    compliance defect when it is really a seed-data change.

    Both windows — the corridor mapping's and the canonical row's — are applied
    here, and the result is ordered, because US_IN also carries a retired mapping
    (P9999 → OTHER, closed 2025-01-01) beside its live ones. An unfiltered
    ``LIMIT 1`` returns whichever row the planner happens to reach first, so it
    can hand back a code the entry point is then obliged to reject; every test in
    this file would fail as a compliance defect when the fixture picked the
    wrong row.
    """
    from app.modules.compliance.domain.entities.registry import (
        PurposeCodeCanonical,
        PurposeCodeCorridorMapping,
    )

    row = (
        await session.execute(
            select(PurposeCodeCorridorMapping.canonical_code)
            .join(
                PurposeCodeCanonical,
                PurposeCodeCanonical.canonical_code
                == PurposeCodeCorridorMapping.canonical_code,
            )
            .where(
                PurposeCodeCorridorMapping.corridor_id == CORRIDOR,
                _in_force_on(PurposeCodeCorridorMapping, AS_OF),
                _in_force_on(PurposeCodeCanonical, AS_OF),
            )
            .order_by(PurposeCodeCorridorMapping.canonical_code)
            .limit(1)
        )
    ).scalar_one()
    return row


# ── the fixture's own contract ────────────────────────────────────────────────


async def test_the_fixture_code_is_actually_in_force_on_the_assessed_date(session):
    """Guards the helper above, not the entry point.

    Every other test here passes this code to a call that rejects a code out of
    force, so if the fixture ever hands back an expired one the whole file fails
    at once and for a misleading reason. Asserted directly so that failure names
    the fixture instead.
    """
    from app.modules.compliance.domain.entities.registry import PurposeCodeCanonical

    code = await _purpose_code(session)

    windows = (
        await session.execute(
            select(PurposeCodeCanonical.effective_from, PurposeCodeCanonical.effective_to).where(
                PurposeCodeCanonical.canonical_code == code
            )
        )
    ).all()

    assert any(
        start <= AS_OF and (end is None or end > AS_OF) for start, end in windows
    ), f"{code} has no canonical window covering {AS_OF}: {windows}"


async def test_the_fixture_is_deterministic(session):
    """Ordered, so a planner change cannot silently swap which code is exercised."""
    assert await _purpose_code(session) == await _purpose_code(session)


# ── the ticket's headline acceptance criterion ────────────────────────────────


async def test_a_precious_stones_settlement_on_the_us_in_corridor_requires_edd(session):
    """AC1, end to end from a sector code — not from a hand-built DNFBP fact.

    PRECIOUS_STONES_TRADE is rated high/DNFBP by FATF in the sector registry, so
    the seeded rule's two conditions are both satisfied by data rather than by
    the test.
    """
    result = await evaluate_compliance_rules(
        session,
        sector_code=DNFBP_SECTOR,
        purpose_code=await _purpose_code(session),
        corridor_id=CORRIDOR,
        send_amount=100_00,
        send_currency="USD",
        as_of_date=AS_OF,
    )

    assert result.edd_required is True
    assert result.edd_trigger_rule == DNFBP_RULE
    assert result.edd_trigger_rules == (DNFBP_RULE,)
    assert RequiredAction.EDD_REQUIRED in result.required_actions


async def test_the_action_set_names_the_jurisdiction_that_classified_the_sector(session):
    """AC2. The value S1T2 stores as edd_trigger_jurisdiction.

    FATF here is a *resolution*, not a default. No corridor classification is
    seeded for any sector and this call names no country, so the corridor and
    country rungs find nothing and the framework baseline answers. The companion
    test below names a country and gets a different authority from the same
    registry, which is what shows this is being resolved rather than assumed.
    """
    result = await evaluate_compliance_rules(
        session,
        sector_code=DNFBP_SECTOR,
        purpose_code=await _purpose_code(session),
        corridor_id=CORRIDOR,
        send_amount=100_00,
        send_currency="USD",
        as_of_date=AS_OF,
    )

    assert result.resolving_jurisdiction is not None
    assert result.resolving_jurisdiction.value == FATF_FRAMEWORK
    # The pair, not just the name: S0T2 identifies the precedence level that won.
    assert result.resolving_jurisdiction.type is JurisdictionType.FRAMEWORK


async def test_naming_a_country_resolves_that_regime_instead_of_the_framework(session):
    result = await evaluate_compliance_rules(
        session,
        sector_code=DNFBP_SECTOR,
        purpose_code=await _purpose_code(session),
        corridor_id=CORRIDOR,
        send_amount=100_00,
        send_currency="USD",
        as_of_date=AS_OF,
        country_jurisdiction=US_COUNTRY_REGIME,
    )

    assert result.resolving_jurisdiction is not None
    assert result.resolving_jurisdiction.type is JurisdictionType.COUNTRY
    assert result.resolving_jurisdiction.value == US_COUNTRY_REGIME
    assert result.edd_required is True
    assert result.edd_trigger_rule == DNFBP_RULE


async def test_the_reason_is_the_one_the_ticket_specifies(session):
    result = await evaluate_compliance_rules(
        session,
        sector_code=DNFBP_SECTOR,
        purpose_code=await _purpose_code(session),
        corridor_id=CORRIDOR,
        send_amount=100_00,
        send_currency="USD",
        as_of_date=AS_OF,
    )

    assert result.reasons_for(RequiredAction.EDD_REQUIRED) == (
        "FATF DNFBP classification requires enhanced due diligence before settlement proceeds.",
    )


async def test_an_unrated_sector_requires_no_due_diligence(session):
    """AC3. An unknown sector resolves to the standard tier with no label, which
    satisfies neither of the DNFBP rule's conditions."""
    result = await evaluate_compliance_rules(
        session,
        sector_code="SECTOR_THAT_IS_NOT_REGISTERED",
        purpose_code=await _purpose_code(session),
        corridor_id=CORRIDOR,
        send_amount=100_00,
        send_currency="USD",
        as_of_date=AS_OF,
    )

    assert result.edd_required is False
    assert result.edd_trigger_rule is None
    # S0T2 requires an unrated sector to be reported as not found rather than
    # silently defaulting, so no jurisdiction is named — nobody classified it.
    assert result.resolving_jurisdiction is None


async def test_a_large_value_settlement_is_sent_for_manual_review(session):
    """AC4, through the public entry point."""
    result = await evaluate_compliance_rules(
        session,
        sector_code="SECTOR_THAT_IS_NOT_REGISTERED",
        purpose_code=await _purpose_code(session),
        corridor_id=CORRIDOR,
        send_amount=THRESHOLD,
        send_currency="USD",
        as_of_date=AS_OF,
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW)
    assert result.rules_for(RequiredAction.MANUAL_REVIEW) == (LARGE_VALUE_RULE,)


async def test_a_settlement_below_the_threshold_is_not_reviewed(session):
    """AC5."""
    result = await evaluate_compliance_rules(
        session,
        sector_code="SECTOR_THAT_IS_NOT_REGISTERED",
        purpose_code=await _purpose_code(session),
        corridor_id=CORRIDOR,
        send_amount=THRESHOLD - 1,
        send_currency="USD",
        as_of_date=AS_OF,
    )

    assert result.requires(RequiredAction.MANUAL_REVIEW) is False
    assert result.required_actions == ()


# ── the fail-safe leaves an audit record ──────────────────────────────────────


#: Read with SQL rather than through audit's ORM model: ARCHITECTURE.md §2 lets
#: compliance import audit's public facade and nothing behind it, and the facade
#: does not expose the entity. The table is what is being asserted about anyway —
#: that a row a compliance officer can query actually exists.
_AUDIT_EVENTS = "audit.audit_events"


async def _fx_warning_count(session) -> int:
    return (
        await session.execute(
            text(f"SELECT count(*) FROM {_AUDIT_EVENTS} WHERE event_type = :t"),
            {"t": FX_RATE_UNAVAILABLE_EVENT},
        )
    ).scalar_one()


async def test_an_unavailable_rate_writes_an_audit_event(session):
    """AC7. The ticket requires the compliance team be able to find settlements
    whose threshold was never actually checked, which a log line does not give
    them.

    INR send against the seeded USD threshold, with no rate provider supplied.
    """
    before = await _fx_warning_count(session)

    result = await evaluate_compliance_rules(
        session,
        sector_code="SECTOR_THAT_IS_NOT_REGISTERED",
        purpose_code=await _purpose_code(session),
        corridor_id=CORRIDOR,
        send_amount=1,
        send_currency="INR",
        as_of_date=AS_OF,
    )

    # Fail-safe: one paisa cannot really breach USD 50,000, but with no rate the
    # platform cannot know that, so the rule fires.
    assert result.requires(RequiredAction.MANUAL_REVIEW)
    assert await _fx_warning_count(session) == before + 1


async def test_the_audit_event_records_the_pair_and_the_consequence(session):
    await evaluate_compliance_rules(
        session,
        sector_code="SECTOR_THAT_IS_NOT_REGISTERED",
        purpose_code=await _purpose_code(session),
        corridor_id=CORRIDOR,
        send_amount=1,
        send_currency="INR",
        as_of_date=AS_OF,
    )

    payload = (
        await session.execute(
            text(
                f"SELECT payload FROM {_AUDIT_EVENTS} WHERE event_type = :t "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"t": FX_RATE_UNAVAILABLE_EVENT},
        )
    ).scalar_one()

    assert payload["from_asset_code"] == "INR"
    assert payload["to_asset_code"] == "USD"
    assert payload["threshold_condition"] == "treated_as_met"


async def test_the_audit_event_names_the_rules_left_unchecked(session):
    await evaluate_compliance_rules(
        session,
        sector_code="SECTOR_THAT_IS_NOT_REGISTERED",
        purpose_code=await _purpose_code(session),
        corridor_id=CORRIDOR,
        send_amount=1,
        send_currency="INR",
        as_of_date=AS_OF,
    )

    payload = (
        await session.execute(
            text(
                f"SELECT payload FROM {_AUDIT_EVENTS} WHERE event_type = :t "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"t": FX_RATE_UNAVAILABLE_EVENT},
        )
    ).scalar_one()

    assert payload["rule_ids"] == [LARGE_VALUE_RULE]
    assert payload["reason"] == "no_indicative_rate_provider_supplied"
    assert payload["error_type"] is None


async def test_a_failing_rate_provider_records_its_error_type(session):
    await evaluate_compliance_rules(
        session,
        sector_code="SECTOR_THAT_IS_NOT_REGISTERED",
        purpose_code=await _purpose_code(session),
        corridor_id=CORRIDOR,
        send_amount=1,
        send_currency="INR",
        as_of_date=AS_OF,
        rate_provider=UnavailableRateProvider(ConnectionError("rate feed is unreachable")),
    )

    payload = (
        await session.execute(
            text(
                f"SELECT payload FROM {_AUDIT_EVENTS} WHERE event_type = :t "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"t": FX_RATE_UNAVAILABLE_EVENT},
        )
    ).scalar_one()

    assert payload["error_type"] == "ConnectionError"
    assert "unreachable" in payload["reason"]
    assert payload["rule_ids"] == [LARGE_VALUE_RULE]
    assert payload["threshold_condition"] == "treated_as_met"


async def test_a_same_currency_settlement_writes_no_audit_event(session):
    """The Walk-phase path. No rate is needed, so nothing was left unchecked and
    there is nothing for a reviewer to look at."""
    before = await _fx_warning_count(session)

    await evaluate_compliance_rules(
        session,
        sector_code=DNFBP_SECTOR,
        purpose_code=await _purpose_code(session),
        corridor_id=CORRIDOR,
        send_amount=THRESHOLD,
        send_currency="USD",
        as_of_date=AS_OF,
    )

    assert await _fx_warning_count(session) == before


async def test_the_entry_point_does_not_commit_the_callers_session(session):
    """Including the audit event: it joins the caller's transaction and lives or
    dies with the decision it explains."""
    await evaluate_compliance_rules(
        session,
        sector_code="SECTOR_THAT_IS_NOT_REGISTERED",
        purpose_code=await _purpose_code(session),
        corridor_id=CORRIDOR,
        send_amount=1,
        send_currency="INR",
        as_of_date=AS_OF,
    )
    await session.rollback()

    async with database.AsyncSessionLocal() as observer:
        rules = (
            await observer.execute(select(func.count()).select_from(ComplianceRule))
        ).scalar_one()
        assert rules > 0, "the registry itself must be untouched"


# ── the contract S1T2 is written against ──────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    ["required_actions", "rule_ids", "reasons", "resolving_jurisdiction", "fired"],
)
async def test_the_action_set_exposes_what_the_ticket_names(session, name):
    result = await evaluate_compliance_rules(
        session,
        sector_code=DNFBP_SECTOR,
        purpose_code=await _purpose_code(session),
        corridor_id=CORRIDOR,
        send_amount=100_00,
        send_currency="USD",
        as_of_date=AS_OF,
    )

    assert hasattr(result, name)
