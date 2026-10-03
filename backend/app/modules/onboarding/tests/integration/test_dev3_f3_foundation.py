"""F3 — company identity, pipeline status and the published interfaces —
**owner: Developer 3** (allocation F3; plan P4-1, P4-3; migration 0032).

Three things are proved here:

1. the **migration**: the five columns, the two constraints, the ``DEAL_BUYER`` enum
   value, and that existing companies came through as ``IN_PIPELINE``;
2. ``CompanyDirectory``: ``create_buyer_company`` fully, and the ``match`` stub's
   honest limits (exact identifiers only, ``CONFLICT`` rather than a guess);
3. that Developer 2 can use the ``BranchFlagReader`` stub — it satisfies the Protocol
   their guard declared, which is F3's "done when".

The constraints go through **raw SQL**, because the point of a database constraint is
that it holds for a writer that never went through a service — and the buyer migration
(Developer 2's 2.6) writes these rows directly.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from sqlalchemy import select

from app.modules.onboarding.application.branch_flags import BranchFlagService
from app.modules.onboarding.application.company_directory import (
    CREATED_VIA_DEAL_BUYER,
    CompanyDirectoryService,
)
from app.modules.onboarding.domain.company_directory import (
    BuyerCompanyDraft,
    MatchKind,
)
from app.modules.onboarding.domain.entities.exporter_enums import (
    CompanyIdentityType,
    CompanyPipelineStatus,
    ExporterJourney,
    ExporterSource,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.handover_conditions import BranchFlagReader
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.platform.configuration.config import get_settings
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio


def _pan() -> str:
    """A PAN-shaped identifier nothing else uses.

    `uq_exporter_profile_pan` and `uq_exporter_profile_country_registration_number`
    are real constraints and this suite's database persists between runs, so a fixed
    value passes the first time and collides with its own previous run afterwards.
    Same shape as `test_crm_end_to_end.py`'s helper: five letters, four digits, one
    letter.
    """
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    return f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"


def _registration() -> str:
    """A registration number nothing else uses, for the same reason."""
    return f"REG-{uuid.uuid4().hex[:10].upper()}"


def _raw_sql():
    return psycopg2.connect(
        get_settings().DATABASE_SYNC_URL.replace("postgresql+psycopg2://", "postgresql://")
    )


async def _profile(company_id: uuid.UUID) -> ExporterProfile:
    async with db_services.AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(ExporterProfile).where(ExporterProfile.customer_id == company_id)
        )
    assert profile is not None
    return profile


# ── 1. The migration ─────────────────────────────────────────────────────────


async def test_an_existing_company_is_in_the_pipeline_with_no_identity_guessed():
    """0032's server default covers every existing row, and `identity_type` stays
    `NULL` unless a PAN made it inferable — guessing would make "unknown" unreadable.
    """
    company_id = await make_company()  # the fixture creates one without a PAN
    profile = await _profile(company_id)

    assert profile.pipeline_status is CompanyPipelineStatus.IN_PIPELINE
    assert profile.created_via is None
    assert profile.created_via_deal_id is None
    assert profile.registration_number is None


async def test_deal_buyer_is_a_source_a_company_can_be_created_with():
    """IQ-6. The value is on the existing enum, so this is really asking whether
    0032's `ALTER TYPE … ADD VALUE` landed."""
    assert ExporterSource.DEAL_BUYER.value == "DEAL_BUYER"
    connection = _raw_sql()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid"
                " WHERE t.typname = 'exporter_source_enum' AND e.enumlabel = 'DEAL_BUYER'"
            )
            assert cursor.fetchone() is not None
    finally:
        connection.close()


async def test_a_not_in_pipeline_company_cannot_have_started_its_journey():
    """`ck_exporter_profile_not_in_pipeline_start`, in the database because the buyer
    migration writes these rows directly — a buyer that leaked into the pipeline
    counts would be invisible until somebody noticed the numbers."""
    company_id = await make_company()

    connection = _raw_sql()
    try:
        with connection.cursor() as cursor:
            # PROSPECT and NOT_IN_PIPELINE together is the contradiction.
            with pytest.raises(psycopg2.errors.CheckViolation):
                cursor.execute(
                    "UPDATE onboarding.exporter_profile"
                    " SET pipeline_status = 'NOT_IN_PIPELINE', journey = 'PROSPECT'"
                    " WHERE customer_id = %s",
                    (str(company_id),),
                )
            connection.rollback()

            # LEAD with the untouched gauges is allowed.
            cursor.execute(
                "UPDATE onboarding.exporter_profile"
                " SET pipeline_status = 'NOT_IN_PIPELINE'"
                " WHERE customer_id = %s AND journey = 'LEAD'",
                (str(company_id),),
            )
            assert cursor.rowcount == 1
            connection.rollback()
    finally:
        connection.close()


async def test_one_company_per_country_and_normalised_registration_number():
    """`uq_exporter_profile_country_registration_number`. Normalised, so
    "KVK 1234-56" and "kvk123456" collide — which is the whole point of the rule."""
    first = await make_company()
    second = await make_company()

    connection = _raw_sql()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE onboarding.exporter_profile"
                " SET country = 'NL', registration_number = 'KVK 1234-56'"
                " WHERE customer_id = %s",
                (str(first),),
            )
            with pytest.raises(psycopg2.errors.UniqueViolation):
                cursor.execute(
                    "UPDATE onboarding.exporter_profile"
                    " SET country = 'NL', registration_number = 'kvk123456'"
                    " WHERE customer_id = %s",
                    (str(second),),
                )
            connection.rollback()

            # A different country is a different company, not a duplicate.
            cursor.execute(
                "UPDATE onboarding.exporter_profile"
                " SET country = 'NL', registration_number = 'KVK 1234-56'"
                " WHERE customer_id = %s",
                (str(first),),
            )
            cursor.execute(
                "UPDATE onboarding.exporter_profile"
                " SET country = 'DE', registration_number = 'kvk123456'"
                " WHERE customer_id = %s",
                (str(second),),
            )
            assert cursor.rowcount == 1
            connection.rollback()
    finally:
        connection.close()


# ── 2. CompanyDirectory ──────────────────────────────────────────────────────


async def test_create_buyer_company_makes_a_company_that_is_not_a_lead():
    """What Developer 2's buyer migration (2.6) calls. The company is real — it can be
    screened and cleared (Developer 1's P4-11) — but it is not in the pipeline, so it
    changes no LEAD count (plan §8, P4-2)."""
    deal_id = uuid.uuid4()
    registration = _registration()
    draft = BuyerCompanyDraft(
        name="Rotterdam Trading BV",
        country="nl",
        registration_number=registration,
        created_via_deal_id=deal_id,
        source_ref="run-1",
    )
    async with db_services.AsyncSessionLocal() as db:
        company_id = await CompanyDirectoryService(db).create_buyer_company(
            draft, actor_id="migration"
        )

    profile = await _profile(company_id)
    assert profile.name == "Rotterdam Trading BV"
    assert profile.country == "NL", "the country is upper-cased"
    assert profile.source is ExporterSource.DEAL_BUYER
    assert profile.pipeline_status is CompanyPipelineStatus.NOT_IN_PIPELINE
    assert profile.journey is ExporterJourney.LEAD, "not in the pipeline implies LEAD"
    assert profile.created_via == CREATED_VIA_DEAL_BUYER
    assert profile.created_via_deal_id == deal_id
    assert profile.registration_number == registration
    assert profile.identity_type is CompanyIdentityType.FOREIGN_REG


async def test_creating_the_same_deals_buyer_twice_creates_one_company():
    """P4-6's "re-run creates nothing". Keyed on the deal, which is the only stable
    thing a `deal_buyer` row has."""
    deal_id = uuid.uuid4()
    draft = BuyerCompanyDraft(name="Hanseatic GmbH", country="DE", created_via_deal_id=deal_id)

    async with db_services.AsyncSessionLocal() as db:
        first = await CompanyDirectoryService(db).create_buyer_company(draft, actor_id="m")
    async with db_services.AsyncSessionLocal() as db:
        second = await CompanyDirectoryService(db).create_buyer_company(draft, actor_id="m")

    assert first == second


async def test_a_buyer_with_a_pan_is_an_indian_company():
    """A buyer is "foreign by definition" on the old `deal_buyer` row, but a buyer
    *company* with a PAN is Indian however it reached us."""
    pan = _pan()
    async with db_services.AsyncSessionLocal() as db:
        company_id = await CompanyDirectoryService(db).create_buyer_company(
            BuyerCompanyDraft(
                name="Chennai Spice Exports",
                country="IN",
                pan=pan,
                created_via_deal_id=uuid.uuid4(),
            ),
            actor_id="m",
        )
    profile = await _profile(company_id)
    assert profile.identity_type is CompanyIdentityType.IN_PAN
    assert profile.pan == pan


async def test_a_buyer_with_neither_identifier_leaves_the_question_open():
    """IQ-7 excuses migrated buyers from needing a registration number, so the honest
    answer is `NULL` rather than FOREIGN_REG by elimination."""
    async with db_services.AsyncSessionLocal() as db:
        company_id = await CompanyDirectoryService(db).create_buyer_company(
            BuyerCompanyDraft(
                name="Gulf Fresh Foods LLC", country="AE", created_via_deal_id=uuid.uuid4()
            ),
            actor_id="m",
        )
    assert (await _profile(company_id)).identity_type is None


@pytest.mark.parametrize("bad", ["", "   "])
async def test_a_buyer_company_needs_a_name(bad: str):
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValueError, match="needs a name"):
            await CompanyDirectoryService(db).create_buyer_company(
                BuyerCompanyDraft(name=bad, country="NL"), actor_id="m"
            )


@pytest.mark.parametrize("bad", ["", "N", "NLD", "12"])
async def test_a_buyer_company_needs_a_two_letter_country(bad: str):
    async with db_services.AsyncSessionLocal() as db:
        with pytest.raises(ValueError, match="country"):
            await CompanyDirectoryService(db).create_buyer_company(
                BuyerCompanyDraft(name="Somebody BV", country=bad), actor_id="m"
            )


async def test_match_finds_a_company_by_its_exact_pan():
    pan = _pan()
    async with db_services.AsyncSessionLocal() as db:
        company_id = await CompanyDirectoryService(db).create_buyer_company(
            BuyerCompanyDraft(
                name="Mumbai Textiles", country="IN", pan=pan,
                created_via_deal_id=uuid.uuid4(),
            ),
            actor_id="m",
        )
    async with db_services.AsyncSessionLocal() as db:
        result = await CompanyDirectoryService(db).match(
            # Lower-cased, to prove the lookup normalises.
            name="anything at all", country="IN", pan=pan.lower()
        )
    assert result.kind is MatchKind.MATCHED
    assert result.company_id == company_id
    assert not result.needs_a_person


async def test_match_finds_a_company_by_its_normalised_registration_number():
    """The lookup normalises the same way the unique index does — otherwise it would
    report NEW for a number the insert then refuses as a duplicate."""
    bare = uuid.uuid4().hex[:8].upper()
    async with db_services.AsyncSessionLocal() as db:
        company_id = await CompanyDirectoryService(db).create_buyer_company(
            BuyerCompanyDraft(
                name="Antwerp Shipping NV", country="BE",
                registration_number=f"BE {bare[:4]}-{bare[4:]}",
                created_via_deal_id=uuid.uuid4(),
            ),
            actor_id="m",
        )
    async with db_services.AsyncSessionLocal() as db:
        result = await CompanyDirectoryService(db).match(
            # Punctuation and case stripped: the lookup must normalise the way the
            # unique index does, or it reports NEW for a number the insert refuses.
            name="Antwerp Shipping NV", country="be",
            registration_number=f"be{bare.lower()}",
        )
    assert (result.kind, result.company_id) == (MatchKind.MATCHED, company_id)


async def test_a_name_alone_is_never_a_match():
    """A name is evidence for a person to weigh, never an identity.

    This was the F3 stub's limit — a name alone returned ``NEW``. Task 3.10 added
    similarity, so the same name now comes back as ``POSSIBLE_DUPLICATE``: still not
    a match, still ``company_id is None``, but the candidate is named so somebody can
    check it rather than creating a second record for a company we already hold.
    What has **not** changed, and is what this test now guards, is that a name never
    produces ``MATCHED``.

    The similarity rule itself is ``test_dev3_company_match.py``'s subject.
    """
    async with db_services.AsyncSessionLocal() as db:
        company_id = await CompanyDirectoryService(db).create_buyer_company(
            BuyerCompanyDraft(
                name="Rotterdam Trading BV", country="NL", created_via_deal_id=uuid.uuid4()
            ),
            actor_id="m",
        )
    async with db_services.AsyncSessionLocal() as db:
        result = await CompanyDirectoryService(db).match(
            name="Rotterdam Trading BV", country="NL"
        )
    assert result.kind is MatchKind.POSSIBLE_DUPLICATE
    assert result.company_id is None
    assert result.needs_a_person is True
    assert company_id in result.candidates


async def test_an_unknown_name_is_still_new():
    async with db_services.AsyncSessionLocal() as db:
        result = await CompanyDirectoryService(db).match(
            name=f"Nobody At All {uuid.uuid4().hex[:12]}", country="NL"
        )
    assert result.kind is MatchKind.NEW
    assert result.company_id is None
    assert result.reason is None


async def test_match_reports_a_conflict_rather_than_picking_one():
    """Two identifiers naming different companies needs a person (IQ-8). Picking one
    would attach a deal to the wrong company silently, which is the one outcome worth
    refusing outright."""
    pan, registration = _pan(), _registration()
    async with db_services.AsyncSessionLocal() as db:
        with_pan = await CompanyDirectoryService(db).create_buyer_company(
            BuyerCompanyDraft(
                name="One Company", country="IN", pan=pan,
                created_via_deal_id=uuid.uuid4(),
            ),
            actor_id="m",
        )
    async with db_services.AsyncSessionLocal() as db:
        with_reg = await CompanyDirectoryService(db).create_buyer_company(
            BuyerCompanyDraft(
                name="Another Company", country="IN",
                registration_number=registration,
                created_via_deal_id=uuid.uuid4(),
            ),
            actor_id="m",
        )

    async with db_services.AsyncSessionLocal() as db:
        result = await CompanyDirectoryService(db).match(
            name="whichever", country="IN", pan=pan, registration_number=registration
        )
    assert result.kind is MatchKind.CONFLICT
    assert result.needs_a_person, "the buyer migration must stop and ask"
    assert set(result.candidates) == {with_pan, with_reg}
    assert "more than one company" in (result.reason or "")


# ── 3. Developer 2 can use the BranchFlagReader stub ─────────────────────────


async def test_the_branch_flag_stub_satisfies_developer_2s_protocol():
    """F3's "done when": Developer 2 can use this where their guard expects a
    `BranchFlagReader`. Structural, so neither lane imports the other's class."""
    async with db_services.AsyncSessionLocal() as db:
        reader = BranchFlagService(db)
        assert isinstance(reader, BranchFlagReader)
        assert await reader.is_flagged(uuid.uuid4()) == (False, None)
