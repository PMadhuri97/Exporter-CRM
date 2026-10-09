"""A company's relationship manager: one active RM user, set through one route.

What is proved here, against a real database and through the API:

* **Eligibility.** Only an active OPERATIONS user can be an RM; ADMIN, COMPLIANCE,
  DEVELOPER, a deactivated account and an unknown id are refused (422).
* **Who may change it.** An RM claims a company with no RM for themselves; naming
  someone else, changing or clearing an RM needs ``exporters:assign_rm`` (the Sales
  lead role) — the administrator holds it no more than anyone else, and a change or clear needs a reason. A stale screen is refused.
* **The record.** Every change is a ``relationship_manager`` history row with both ids,
  both names and the reason; the legacy free text can no longer be written.
* **Ownership grants nothing.** The RM still sees masked identifiers, and the list
  returns the same companies whether or not the reader owns them.
* **Bulk reassignment**, its dry run, a subset, a refused target and a company changed
  meanwhile; the list filters My companies, Unassigned and inactive RM.
* **The RM at the action.** Starting a check and a person's QUALIFIED need an RM on an
  in-pipeline company; a buyer-only company never does; nothing in the database
  requires one.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.domain.entities.exporter_enums import (
    CompanyPipelineStatus,
    ExporterJourney,
)
from app.modules.onboarding.domain.entities.exporter_lifecycle_history import (
    ExporterLifecycleHistory,
)
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.tests.fixtures.auth import (
    auth_header,
    deactivate,
    user_with_permissions,
    user_with_role,
)
from app.modules.onboarding.tests.fixtures.companies import make_company
from app.modules.onboarding.tests.integration._verification_support import BASE
from app.platform.authentication.models import UserRole
from app.platform.database import services as db_services

pytestmark = pytest.mark.asyncio

ASSIGN_RM = ("exporters", "assign_rm")


@pytest.fixture(scope="module")
async def people(client: AsyncClient) -> dict[str, tuple[str, str]]:
    """``name -> (user_id, token)``."""
    return {
        "rm": await user_with_role(client, UserRole.OPERATIONS, email_prefix="rm-a"),
        "rm2": await user_with_role(client, UserRole.OPERATIONS, email_prefix="rm-b"),
        "sales_lead": await user_with_permissions(
            client, UserRole.OPERATIONS, ASSIGN_RM, email_prefix="sales-lead"
        ),
        "compliance": await user_with_role(client, UserRole.COMPLIANCE, email_prefix="rm-co"),
        "admin": await user_with_role(client, UserRole.ADMIN, email_prefix="rm-admin"),
        "developer": await user_with_role(client, UserRole.DEVELOPER, email_prefix="rm-dev"),
    }


def _pan() -> str:
    import random
    import string

    letters = "".join(random.choice(string.ascii_uppercase) for _ in range(5))
    return f"{letters}{random.randint(0, 9999):04d}{random.choice(string.ascii_uppercase)}"


async def _create(client: AsyncClient, token: str, **extra) -> dict:
    pan = _pan()
    response = await client.post(
        f"{BASE}/exporters",
        json={
            "source": "SALES",
            "name": f"RM Co {uuid.uuid4().hex[:8]}",
            "country": "IN",
            "pan": pan,
            **extra,
        },
        headers={**auth_header(token), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _assign(client, token, company_id, user_id, *, seen=None, reason=None):
    return await client.post(
        f"{BASE}/exporters/{company_id}/relationship-manager",
        json={"user_id": user_id, "seen_user_id": seen, "reason": reason},
        headers=auth_header(token),
    )


async def _rm_rows(company_id: str) -> list[ExporterLifecycleHistory]:
    async with db_services.AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(ExporterLifecycleHistory)
                    .where(
                        ExporterLifecycleHistory.customer_id == uuid.UUID(company_id),
                        ExporterLifecycleHistory.dimension == "relationship_manager",
                    )
                    .order_by(ExporterLifecycleHistory.created_at)
                )
            ).all()
        )


# ── Eligibility and who may set it ──────────────────────────────────────────


async def test_an_rm_claims_an_unowned_company_and_it_is_on_the_record(client, people):
    rm_id, rm = people["rm"]
    company = await _create(client, rm)
    assert company["relationship_manager_user_id"] is None

    detail = (
        await client.get(f"{BASE}/exporters/{company['customer_id']}", headers=auth_header(rm))
    ).json()
    assert detail["relationship_manager_actions"] == ["CLAIM"]

    response = await _assign(client, rm, company["customer_id"], rm_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["relationship_manager_user_id"] == rm_id
    assert body["relationship_manager_name"]
    assert body["relationship_manager_actions"] == []  # a plain RM cannot change it now

    [row] = await _rm_rows(company["customer_id"])
    assert row.event_type == "relationship_manager_assigned"
    assert row.actor_id == rm_id
    assert row.event_metadata["from_user_id"] is None
    assert row.event_metadata["to_user_id"] == rm_id


async def test_a_plain_rm_cannot_name_someone_else_or_change_or_clear(client, people):
    rm_id, rm = people["rm"]
    rm2_id, rm2 = people["rm2"]
    company = await _create(client, rm)
    cid = company["customer_id"]
    assert (await _assign(client, rm, cid, rm2_id)).status_code == 403
    assert (await _assign(client, rm, cid, rm_id)).status_code == 200
    changed = await _assign(client, rm2, cid, rm2_id, seen=rm_id, reason="mine now")
    assert changed.status_code == 403
    assert changed.json()["error_code"] == "RELATIONSHIP_MANAGER_ASSIGN_NOT_ALLOWED"
    cleared = await _assign(client, rm, cid, None, seen=rm_id, reason="letting go")
    assert cleared.status_code == 403


async def test_compliance_cannot_claim_and_is_never_an_rm(client, people):
    compliance_id, compliance = people["compliance"]
    _, admin = people["sales_lead"]
    company = await _create(client, admin)
    cid = company["customer_id"]
    assert (await _assign(client, compliance, cid, compliance_id)).status_code == 403
    refused = await _assign(client, admin, cid, compliance_id)
    assert refused.status_code == 422
    assert refused.json()["error_code"] == "RELATIONSHIP_MANAGER_NOT_ELIGIBLE"


@pytest.mark.parametrize("who", ["admin", "developer", "compliance"])
async def test_only_an_operations_user_can_be_the_rm(client, people, who):
    _, admin = people["sales_lead"]
    target_id, _ = people[who]
    company = await _create(client, admin)
    response = await _assign(client, admin, company["customer_id"], target_id)
    assert response.status_code == 422, response.text


async def test_a_deactivated_or_unknown_user_cannot_be_the_rm(client, people):
    _, admin = people["sales_lead"]
    gone_id, _ = await user_with_role(client, UserRole.OPERATIONS, email_prefix="rm-gone")
    deactivate(gone_id)
    company = await _create(client, admin)
    assert (await _assign(client, admin, company["customer_id"], gone_id)).status_code == 422
    unknown = await _assign(client, admin, company["customer_id"], str(uuid.uuid4()))
    assert unknown.status_code == 422


async def test_a_sales_lead_changes_and_clears_with_a_reason_and_admin_cannot(client, people):
    rm_id, rm = people["rm"]
    rm2_id, _ = people["rm2"]
    _, lead = people["sales_lead"]
    _, admin = people["sales_lead"]
    company = await _create(client, rm)
    cid = company["customer_id"]
    _, real_admin = people["admin"]
    assert (await _assign(client, real_admin, cid, rm_id)).status_code == 403
    assert (await _assign(client, admin, cid, rm_id)).status_code == 200

    lead_view = (await client.get(f"{BASE}/exporters/{cid}", headers=auth_header(lead))).json()
    assert lead_view["relationship_manager_actions"] == ["CHANGE", "CLEAR"]

    no_reason = await _assign(client, lead, cid, rm2_id, seen=rm_id)
    assert no_reason.status_code == 422
    assert no_reason.json()["error_code"] == "RELATIONSHIP_MANAGER_REASON_REQUIRED"
    assert (await _assign(client, lead, cid, rm2_id, seen=rm_id, reason="territory")).status_code == 200
    stale = await _assign(client, admin, cid, None, seen=rm_id, reason="left")
    assert stale.status_code == 409
    assert stale.json()["error_code"] == "RELATIONSHIP_MANAGER_CHANGED"
    assert (await _assign(client, admin, cid, None, seen=rm2_id, reason="left")).status_code == 200

    rows = await _rm_rows(cid)
    assert [r.event_type for r in rows] == [
        "relationship_manager_assigned",
        "relationship_manager_reassigned",
        "relationship_manager_cleared",
    ]
    assert rows[1].reason == "territory"
    assert rows[1].event_metadata["from_user_id"] == rm_id
    assert rows[1].event_metadata["to_user_id"] == rm2_id
    assert rows[2].to_status == "UNASSIGNED"


async def test_the_same_rm_again_writes_nothing(client, people):
    rm_id, rm = people["rm"]
    company = await _create(client, rm)
    cid = company["customer_id"]
    await _assign(client, rm, cid, rm_id)
    again = await _assign(client, rm, cid, rm_id, seen=rm_id)
    assert again.status_code == 200
    assert len(await _rm_rows(cid)) == 1


async def test_an_rm_may_be_named_on_create(client, people):
    rm_id, rm = people["rm"]
    rm2_id, _ = people["rm2"]
    created = await _create(client, rm, relationship_manager_user_id=rm_id)
    assert created["relationship_manager_user_id"] == rm_id
    refused = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "name": "Not yours", "country": "IN",
              "relationship_manager_user_id": rm2_id},
        headers={**auth_header(rm), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert refused.status_code == 403


async def test_the_free_text_owner_can_no_longer_be_written(client, people):
    _, rm = people["rm"]
    company = await _create(client, rm)
    edit = await client.patch(
        f"{BASE}/exporters/{company['customer_id']}",
        json={"relationship_manager": "Someone"},
        headers=auth_header(rm),
    )
    assert edit.status_code == 422
    create = await client.post(
        f"{BASE}/exporters",
        json={"source": "SALES", "name": "X", "country": "IN", "relationship_manager": "Someone"},
        headers={**auth_header(rm), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert create.status_code == 422


# ── Ownership grants nothing ─────────────────────────────────────────────────


async def test_the_rm_still_sees_masked_identifiers_everywhere(client, people):
    rm_id, rm = people["rm"]
    company = await _create(client, rm, relationship_manager_user_id=rm_id)
    cid = company["customer_id"]
    pan = company["pan"]
    assert "•" in pan
    detail = (await client.get(f"{BASE}/exporters/{cid}", headers=auth_header(rm))).json()
    assert "•" in detail["pan"]
    listed = (
        await client.get(f"{BASE}/exporters?relationship_manager=me", headers=auth_header(rm))
    ).json()["profiles"]
    mine = next(p for p in listed if p["customer_id"] == cid)
    assert "•" in mine["pan"]


async def test_ownership_never_narrows_what_a_reader_sees(client, people):
    rm_id, rm = people["rm"]
    _, rm2 = people["rm2"]
    company = await _create(client, rm, relationship_manager_user_id=rm_id)
    name = company["name"]
    for token in (rm, rm2):
        found = (
            await client.get(f"{BASE}/exporters?name={name}", headers=auth_header(token))
        ).json()["profiles"]
        assert [p["customer_id"] for p in found] == [company["customer_id"]]
        detail = await client.get(f"{BASE}/exporters/{company['customer_id']}", headers=auth_header(token))
        assert detail.status_code == 200


# ── List filters and bulk reassignment ──────────────────────────────────────


async def test_my_companies_unassigned_and_inactive_rm_views(client, people):
    rm_id, rm = people["rm"]
    _, admin = people["sales_lead"]
    mine = await _create(client, rm, relationship_manager_user_id=rm_id)
    unowned = await _create(client, admin)
    leaver_id, _ = await user_with_role(client, UserRole.OPERATIONS, email_prefix="rm-leaver")
    left_behind = await _create(client, admin, relationship_manager_user_id=leaver_id)
    deactivate(leaver_id)

    async def ids(query: str, token: str) -> set[str]:
        response = await client.get(
            f"{BASE}/exporters?{query}&limit=200", headers=auth_header(token)
        )
        assert response.status_code == 200, response.text
        return {p["customer_id"] for p in response.json()["profiles"]}

    assert mine["customer_id"] in await ids("relationship_manager=me", rm)
    assert unowned["customer_id"] not in await ids("relationship_manager=me", rm)
    assert unowned["customer_id"] in await ids("relationship_manager=none", rm)
    assert mine["customer_id"] not in await ids("relationship_manager=none", rm)
    inactive = await ids("relationship_manager=inactive", admin)
    assert left_behind["customer_id"] in inactive
    assert mine["customer_id"] not in inactive
    listed = (
        await client.get(
            f"{BASE}/exporters?relationship_manager=inactive&limit=200", headers=auth_header(admin)
        )
    ).json()["profiles"]
    row = next(p for p in listed if p["customer_id"] == left_behind["customer_id"])
    assert row["relationship_manager_inactive"] is True
    bad = await client.get(f"{BASE}/exporters?relationship_manager=nobody", headers=auth_header(rm))
    assert bad.status_code == 422


async def test_bulk_reassign_moves_a_leavers_companies(client, people):
    _, admin = people["sales_lead"]
    rm2_id, _ = people["rm2"]
    leaver_id, _ = await user_with_role(client, UserRole.OPERATIONS, email_prefix="rm-bulk")
    companies = [
        (await _create(client, admin, relationship_manager_user_id=leaver_id))["customer_id"]
        for _ in range(3)
    ]

    async def reassign(token, **body):
        return await client.post(
            f"{BASE}/relationship-managers/reassign",
            json={"from_user_id": leaver_id, "to_user_id": rm2_id, "reason": "left", **body},
            headers=auth_header(token),
        )

    dry = await reassign(admin, dry_run=True)
    assert dry.status_code == 200, dry.text
    assert dry.json()["matched"] == 3 and dry.json()["moved"] == 0
    assert dry.json()["bulk_run_id"] is None
    async with db_services.AsyncSessionLocal() as db:
        still = await db.scalar(
            select(ExporterProfile.relationship_manager_user_id).where(
                ExporterProfile.customer_id == uuid.UUID(companies[0])
            )
        )
    assert str(still) == leaver_id

    subset = await reassign(admin, company_ids=[companies[0]])
    assert subset.json()["moved"] == 1

    # Someone changes one company meanwhile: the run skips it rather than overwrite.
    async with db_services.AsyncSessionLocal() as db:
        profile = (
            await db.execute(
                select(ExporterProfile)
                .where(ExporterProfile.customer_id == uuid.UUID(companies[1]))
                .with_for_update()
            )
        ).scalar_one()
        await ExporterProfileService(db).set_relationship_manager(
            profile, user_id=uuid.UUID(people["rm"][0]), reason="moved by hand",
            actor_id="x", actor_role=UserRole.OPERATIONS,
            actor_permissions=frozenset({ASSIGN_RM}), source="test",
        )
        await db.commit()

    run = await reassign(admin)
    body = run.json()
    assert body["moved"] == 1 and body["company_ids"] == [companies[2]]
    rows = await _rm_rows(companies[2])
    assert rows[-1].event_metadata["bulk_run_id"] == body["bulk_run_id"]
    assert rows[-1].reason == "left"

    left = (
        await client.get(
            f"{BASE}/exporters?relationship_manager={leaver_id}", headers=auth_header(admin)
        )
    ).json()["profiles"]
    assert left == []


async def test_bulk_reassign_needs_the_permission_a_reason_and_an_rm_target(client, people):
    rm_id, rm = people["rm"]
    rm2_id, _ = people["rm2"]
    _, lead = people["sales_lead"]
    compliance_id, _ = people["compliance"]
    body = {"from_user_id": rm_id, "to_user_id": rm2_id, "reason": "x", "dry_run": True}
    url = f"{BASE}/relationship-managers/reassign"
    assert (await client.post(url, json=body, headers=auth_header(rm))).status_code == 403
    assert (await client.post(url, json=body, headers=auth_header(lead))).status_code == 200
    blank = await client.post(url, json={**body, "reason": "  "}, headers=auth_header(lead))
    assert blank.status_code == 422
    wrong = await client.post(
        url, json={**body, "to_user_id": compliance_id}, headers=auth_header(lead)
    )
    assert wrong.status_code == 422


async def test_the_staff_picker_lists_active_people_by_role(client, people):
    _, rm = people["rm"]
    _, developer = people["developer"]
    gone_id, _ = await user_with_role(client, UserRole.OPERATIONS, email_prefix="rm-pick-gone")
    deactivate(gone_id)
    response = await client.get(f"{BASE}/staff?role=OPERATIONS", headers=auth_header(rm))
    assert response.status_code == 200
    staff = response.json()["staff"]
    ids = {s["id"] for s in staff}
    assert people["rm"][0] in ids and gone_id not in ids
    assert all(s["role"] == "OPERATIONS" for s in staff)
    assert all(set(s) == {"id", "name", "role", "companies", "open_reviews"} for s in staff)
    reviewers = (
        await client.get(f"{BASE}/staff?role=COMPLIANCE&role=ADMIN", headers=auth_header(rm))
    ).json()["staff"]
    # The administrator is neither an RM nor a reviewer, so a picker never lists one.
    assert {s["role"] for s in reviewers} <= {"COMPLIANCE"}
    assert (await client.get(f"{BASE}/staff", headers=auth_header(developer))).status_code == 403


# ── The RM at the action ─────────────────────────────────────────────────────


async def _start(client, token, company_id, **extra):
    return await client.post(
        f"{BASE}/exporters/{company_id}/background-check/decisions",
        json={"to_value": "IN_REVIEW", "from_value": "NOT_STARTED", **extra},
        headers=auth_header(token),
    )


async def test_a_lead_is_created_without_an_rm(client, people):
    _, rm = people["rm"]
    company = await _create(client, rm)
    assert company["journey"] == "LEAD"
    assert company["relationship_manager_user_id"] is None


async def test_starting_a_check_needs_an_rm(client, people):
    rm_id, rm = people["rm"]
    rm2_id, _ = people["rm2"]
    _, compliance = people["compliance"]
    _, admin = people["sales_lead"]
    company = await _create(client, admin)
    cid = company["customer_id"]

    standing = (
        await client.get(f"{BASE}/exporters/{cid}/background-check", headers=auth_header(rm))
    ).json()
    assert standing["relationship_manager_required"] is True

    refused = await _start(client, rm, cid)
    assert refused.status_code == 409
    assert refused.json()["error_code"] == "RELATIONSHIP_MANAGER_REQUIRED"
    # A compliance starter without exporters:assign_rm cannot name an RM.
    assert (await _start(client, compliance, cid, relationship_manager_user_id=rm_id)).status_code == 403
    # An RM may not name someone else; they may name themselves.
    assert (await _start(client, rm, cid, relationship_manager_user_id=rm2_id)).status_code == 403
    started = await _start(client, rm, cid, relationship_manager_user_id=rm_id)
    assert started.status_code == 201, started.text
    [row] = await _rm_rows(cid)
    assert row.event_metadata["to_user_id"] == rm_id


async def test_a_sales_lead_names_an_rm_when_starting(client, people):
    rm_id, _ = people["rm"]
    _, admin = people["sales_lead"]
    company = await _create(client, admin)
    started = await _start(client, admin, company["customer_id"], relationship_manager_user_id=rm_id)
    assert started.status_code == 201, started.text


async def test_qualified_needs_an_rm_and_an_rm_defaults_to_themselves(client, people):
    rm_id, rm = people["rm"]
    _, admin = people["sales_lead"]
    company = await _create(client, admin)
    cid = company["customer_id"]
    url = f"{BASE}/exporters/{cid}/qualification/outcome"
    refused = await client.post(url, json={"outcome": "QUALIFIED"}, headers=auth_header(rm))
    assert refused.status_code == 409
    assert refused.json()["error_code"] == "RELATIONSHIP_MANAGER_REQUIRED"
    ok = await client.post(
        url,
        json={"outcome": "QUALIFIED", "relationship_manager_user_id": rm_id},
        headers=auth_header(rm),
    )
    assert ok.status_code == 201, ok.text
    detail = (await client.get(f"{BASE}/exporters/{cid}", headers=auth_header(rm))).json()
    assert detail["journey"] == "PROSPECT"
    assert detail["relationship_manager_user_id"] == rm_id


async def test_not_qualified_needs_no_rm(client, people):
    _, rm = people["rm"]
    company = await _create(client, rm)
    reasons = (
        await client.get(f"{BASE}/qualification/reason-codes", headers=auth_header(rm))
    )
    codes = [c["code"] for c in reasons.json().get("reason_codes", [])] if reasons.status_code == 200 else []
    if not codes:
        pytest.skip("no reason codes seeded")
    code = next(c for c in codes if c != "other")
    response = await client.post(
        f"{BASE}/exporters/{company['customer_id']}/qualification/outcome",
        json={"outcome": "NOT_QUALIFIED", "reason_codes": [code]},
        headers=auth_header(rm),
    )
    assert response.status_code == 201, response.text


async def test_an_imported_prospect_without_an_rm_is_allowed_and_listed_unassigned(client, people):
    _, admin = people["sales_lead"]
    company_id = await make_company(relationship_manager=False)
    async with db_services.AsyncSessionLocal() as db:
        await db.execute(
            update(ExporterProfile)
            .where(ExporterProfile.customer_id == company_id)
            .values(journey=ExporterJourney.PROSPECT, name="Imported prospect")
        )
        await db.commit()
    listed = (
        await client.get(
            f"{BASE}/exporters?relationship_manager=none&journey=PROSPECT&limit=200",
            headers=auth_header(admin),
        )
    ).json()["profiles"]
    assert str(company_id) in {p["customer_id"] for p in listed}


async def test_a_buyer_only_company_is_never_blocked_by_having_no_rm(client, people):
    _, compliance = people["compliance"]
    company_id = await make_company(relationship_manager=False)
    async with db_services.AsyncSessionLocal() as db:
        await db.execute(
            update(ExporterProfile)
            .where(ExporterProfile.customer_id == company_id)
            .values(pipeline_status=CompanyPipelineStatus.NOT_IN_PIPELINE, name="Buyer only")
        )
        await db.commit()
    started = await _start(client, compliance, company_id)
    assert started.status_code == 201, started.text
    standing = (
        await client.get(
            f"{BASE}/exporters/{company_id}/background-check", headers=auth_header(compliance)
        )
    ).json()
    assert standing["relationship_manager_required"] is False


async def test_no_database_rule_requires_an_rm():
    company_id = await make_company(relationship_manager=False)
    async with db_services.AsyncSessionLocal() as db:
        await db.execute(
            update(ExporterProfile)
            .where(ExporterProfile.customer_id == company_id)
            .values(journey=ExporterJourney.PROSPECT)
        )
        await db.commit()
        assert (
            await db.scalar(
                select(ExporterProfile.relationship_manager_user_id).where(
                    ExporterProfile.customer_id == company_id
                )
            )
        ) is None


async def test_developer_sees_the_rm_history_but_cannot_assign(client, people):
    rm_id, rm = people["rm"]
    _, developer = people["developer"]
    company = await _create(client, rm, relationship_manager_user_id=rm_id)
    cid = company["customer_id"]
    assert (await _assign(client, developer, cid, None, seen=rm_id, reason="x")).status_code == 403
    detail = (await client.get(f"{BASE}/exporters/{cid}", headers=auth_header(developer))).json()
    assert detail["relationship_manager_actions"] == []
    history = await client.get(
        f"{BASE}/exporters/{cid}/history?dimension=relationship_manager",
        headers=auth_header(developer),
    )
    assert history.status_code == 200
