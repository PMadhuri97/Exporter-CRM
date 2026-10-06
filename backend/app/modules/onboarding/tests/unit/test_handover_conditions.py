"""The handover guard as a list of conditions.

No database and no service: ``domain/handover_conditions.py`` is pure, which is
the point of having lifted it out of ``DealService``. The conditions that need a
provider are driven by fakes here, so each rule is tested independently of its
real provider — "test against a fake, switch the real one on with no code change".

``test_handover.py`` keeps the same rules end to end against Postgres.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.modules.onboarding.domain.handover_conditions import (
    HandoverProviders,
    HandoverSubject,
    blocked_reason,
    buyer_compliance_passes,
    invoicing_branch_is_active,
    invoicing_branch_is_not_flagged,
    required_documents_are_present,
    seller_background_check_is_clear,
    seller_compliance_is_current,
    seller_is_a_customer,
    state_name,
)
from app.modules.onboarding.tests.fixtures.compliance import party_facts

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
_DEAL = uuid.UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
_SELLER = uuid.UUID("11111111-1111-4111-8111-111111111111")
_BUYER_COMPANY = uuid.UUID("22222222-2222-4222-8222-222222222222")
_LEGACY_BUYER = uuid.UUID("33333333-3333-4333-8333-333333333333")
_BRANCH = uuid.UUID("44444444-4444-4444-8444-444444444444")


def subject(**overrides) -> HandoverSubject:
    """A deal that satisfies the guard's first two conditions and nothing else, with every optional
    link absent — the shape of every deal in the database today."""
    fields = {
        "deal_id": _DEAL,
        "seller_company_id": _SELLER,
        "seller_journey": "CUSTOMER",
        "seller_background_check": "CLEAR",
        "buyer_company_id": None,
        "legacy_buyer_id": _LEGACY_BUYER,
        "seller_gst_registration_id": None,
        "now": _NOW,
    }
    return HandoverSubject(**{**fields, **overrides})


# Facts come from the compliance engine's own `party_facts(...)` fixture rather than a
# local stand-in: if its dataclass gains a field the guard should read, these tests move
# with it instead of silently testing a shape nobody ships.
_EXPIRY = datetime(2026, 9, 1, tzinfo=UTC)


class _Compliance:
    """A fake ``ComplianceFactsReader``, keyed by whatever it is asked about."""

    def __init__(self, *, company=None, legacy=None) -> None:
        self._company = company
        self._legacy = legacy

    async def for_company(self, company_id, now):  # noqa: ANN001 - test double
        assert now == _NOW, "every condition must share one `now`"
        return self._company

    async def for_legacy_buyer(self, deal_buyer_id, now):  # noqa: ANN001 - test double
        return self._legacy


class _Requirements:
    def __init__(self, *missing: str) -> None:
        self._missing = missing

    async def missing_for_deal(self, deal_id):  # noqa: ANN001 - test double
        return self._missing


class _Flags:
    def __init__(self, flagged: bool, state: str | None = None, *, active: bool = True) -> None:
        self._answer = (flagged, state)
        self._active = (active, state)

    async def is_flagged(self, gst_registration_id):  # noqa: ANN001 - test double
        return self._answer

    async def is_active(self, gst_registration_id):  # noqa: ANN001 - test double
        return self._active


# ── The first two conditions: a CUSTOMER with a CLEAR check ──────────────────


async def test_the_guard_passes_on_a_clear_customer():
    assert await seller_is_a_customer(subject(), HandoverProviders()) is None
    assert await seller_background_check_is_clear(subject(), HandoverProviders()) is None


@pytest.mark.parametrize("journey", ["LEAD", "PROSPECT"])
async def test_a_company_short_of_customer_is_named(journey: str):
    reason = await seller_is_a_customer(subject(seller_journey=journey), HandoverProviders())
    assert reason == f"the company is {journey}, not CUSTOMER"


@pytest.mark.parametrize("value", ["NOT_STARTED", "IN_REVIEW", "MORE_INFO", "FLAGGED", "ON_HOLD"])
async def test_not_clear_is_never_read_as_clear(value: str):
    """A company that has never been checked reads ``NOT_STARTED`` — a fact, not an
    absence."""
    reason = await seller_background_check_is_clear(
        subject(seller_background_check=value), HandoverProviders()
    )
    assert reason == f"the background check is {value}, not CLEAR"


# ── The default providers leave behaviour unchanged ──────────────────────────


async def test_the_null_providers_report_nothing():
    """The whole reason the guard could grow without changing behaviour: the four
    provider-backed conditions are inert while their null provider is injected."""
    providers = HandoverProviders()
    for condition in (
        required_documents_are_present,
        seller_compliance_is_current,
        buyer_compliance_passes,
        invoicing_branch_is_not_flagged,
        invoicing_branch_is_active,
    ):
        assert await condition(subject(), providers) is None, condition.__name__
        assert (
            await condition(subject(seller_gst_registration_id=_BRANCH), providers) is None
        ), condition.__name__

    assert await blocked_reason(subject(), providers) is None


async def test_no_facts_is_not_the_same_as_everything_passed():
    """`NoComplianceFacts` returns nothing, and the conditions skip. A reader that
    answered "PASSED" instead would silently let a deal through on a provider that
    does not exist, which is the one failure mode worth a test of its own."""
    silent = _Compliance(company=None, legacy=None)
    providers = HandoverProviders(compliance=silent)
    assert await seller_compliance_is_current(subject(), providers) is None
    assert await buyer_compliance_passes(subject(), providers) is None


# ── Each provider-backed rule, against its fake ──────────────────────────────


async def test_missing_required_documents_are_all_named(
):
    providers = HandoverProviders(
        required_documents=_Requirements("PRE_SHIPMENT", "BANKING")
    )
    assert (
        await required_documents_are_present(subject(), providers)
        == "missing required documents: PRE_SHIPMENT, BANKING"
    )


async def test_an_expired_seller_clear_blocks_and_names_the_date():
    """The date is named: "expired" with no date leaves the operator to go
    looking for when."""
    providers = HandoverProviders(
        compliance=_Compliance(
            company=party_facts(is_clear_current=False, clear_expires_at=_EXPIRY)
        )
    )
    assert (
        await seller_compliance_is_current(subject(), providers)
        == "the background check expired on 2026-09-01"
    )


async def test_a_seller_that_was_never_clear_is_not_reported_as_expired():
    """A company that is not CLEAR has no current Clear either, and condition 2
    already names that by value. Saying "expired" as well would tell an operator to
    renew a check that was never passed."""
    providers = HandoverProviders(
        compliance=_Compliance(company=party_facts(background_check="FLAGGED"))
    )
    assert await seller_compliance_is_current(subject(), providers) is None


async def test_a_failed_seller_sanctions_or_aml_blocks():
    """The seller's own failed screening stops its deals."""
    providers = HandoverProviders(
        compliance=_Compliance(company=party_facts(sanctions="FAILED", aml="FAILED"))
    )
    reason = await seller_compliance_is_current(subject(), providers)
    assert reason == (
        "the company's sanctions check has failed; the company's AML check has failed"
    )


async def test_the_buyer_must_have_passed_both_checks():
    """``PASSED``, not "not failed" — "we have not checked" and "clean"
    must not collapse into one outcome."""
    providers = HandoverProviders(
        compliance=_Compliance(legacy=party_facts(sanctions="MISSING", aml="PENDING"))
    )
    reason = await buyer_compliance_passes(subject(), providers)
    assert reason == (
        "the buyer's sanctions check is MISSING, not PASSED; "
        "the buyer's AML check is PENDING, not PASSED"
    )


async def test_a_buyer_company_is_read_as_a_company_and_a_legacy_buyer_as_a_buyer():
    """The one rule that makes the buyer migration a data migration rather than a behaviour
    change: whichever way the buyer is recorded, the same condition decides."""
    # A legacy deal: its facts come from `for_legacy_buyer`.
    legacy_only = _Compliance(company=party_facts(sanctions="FAILED"), legacy=party_facts())
    assert await buyer_compliance_passes(subject(), HandoverProviders(compliance=legacy_only)) is None

    # The same deal after the migration: its facts come from `for_company`.
    company_only = _Compliance(company=party_facts(sanctions="FAILED"), legacy=party_facts())
    reason = await buyer_compliance_passes(
        subject(buyer_company_id=_BUYER_COMPANY), HandoverProviders(compliance=company_only)
    )
    assert reason == "the buyer's sanctions check is FAILED, not PASSED"


async def test_a_flagged_invoicing_branch_blocks_and_names_the_state():
    providers = HandoverProviders(branch_flags=_Flags(True, "Maharashtra"))
    assert (
        await invoicing_branch_is_not_flagged(
            subject(seller_gst_registration_id=_BRANCH), providers
        )
        == "the invoicing branch Maharashtra is flagged"
    )


async def test_a_deal_with_no_branch_is_not_refused_by_the_branch_rule():
    """Whether a branch is *required* is the branch-recorded rule, not this one's."""
    providers = HandoverProviders(branch_flags=_Flags(True, "Maharashtra"))
    assert await invoicing_branch_is_not_flagged(subject(), providers) is None


async def test_a_deactivated_invoicing_branch_blocks_and_names_the_state():
    """Decided 4 October 2026: block, not warn."""
    providers = HandoverProviders(branch_flags=_Flags(False, "Karnataka", active=False))
    assert (
        await invoicing_branch_is_active(subject(seller_gst_registration_id=_BRANCH), providers)
        == "the invoicing branch Karnataka is deactivated"
    )


async def test_an_active_invoicing_branch_and_no_branch_pass_the_deactivation_rule():
    providers = HandoverProviders(branch_flags=_Flags(False, "Karnataka", active=True))
    recorded = subject(seller_gst_registration_id=_BRANCH)
    assert await invoicing_branch_is_active(recorded, providers) is None
    deactivated = HandoverProviders(branch_flags=_Flags(False, "Karnataka", active=False))
    assert await invoicing_branch_is_active(subject(), deactivated) is None


async def test_a_flagged_and_deactivated_branch_reports_both():
    providers = HandoverProviders(branch_flags=_Flags(True, "Gujarat", active=False))
    assert await blocked_reason(subject(seller_gst_registration_id=_BRANCH), providers) == (
        "the invoicing branch Gujarat is flagged; the invoicing branch Gujarat is deactivated"
    )


# ── Every unmet condition at once ────────────────────────────────────────────


async def test_the_guard_reports_every_unmet_condition_in_order():
    """The screen tells the whole story at once (contract §4.1): an operator must
    not have to fix one thing to discover the next."""
    providers = HandoverProviders(
        compliance=_Compliance(
            company=party_facts(is_clear_current=False, clear_expires_at=_EXPIRY),
            legacy=party_facts(aml="FAILED"),
        ),
        required_documents=_Requirements("PRE_SHIPMENT"),
        branch_flags=_Flags(True, "Gujarat", active=False),
    )
    reason = await blocked_reason(
        subject(
            seller_journey="PROSPECT",
            seller_background_check="FLAGGED",
            seller_gst_registration_id=_BRANCH,
        ),
        providers,
    )
    assert reason == (
        "the company is PROSPECT, not CUSTOMER; "
        "the background check is FLAGGED, not CLEAR; "
        "missing required documents: PRE_SHIPMENT; "
        "the background check expired on 2026-09-01; "
        "the buyer's AML check is FAILED, not PASSED; "
        "the invoicing branch Gujarat is flagged; "
        "the invoicing branch Gujarat is deactivated"
    )


# ── Reading another area's enums by name ─────────────────────────────────────


async def test_state_name_reads_a_str_and_an_enum_the_same():
    """Kept for `pipeline_status`, which really is an enum across the company-record seam —
    `CheckState` is a `Literal` of plain strings, so the compliance conditions
    compare values directly.

    ``async`` only because ``pytestmark`` marks this module; it awaits nothing.
    """
    import enum

    class CheckState(str, enum.Enum):
        PASSED = "PASSED"

    assert state_name("PASSED") == "PASSED"
    assert state_name(CheckState.PASSED) == "PASSED"
    assert state_name(None) is None
