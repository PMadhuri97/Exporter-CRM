"""Screening decides nothing; the rule registry does.

``ComplianceService.run_screening`` used to answer two compliance questions in
Python — whether a sector designation obliged enhanced due diligence, and
whether an amount was large enough to review. Both duplicated a seeded rule.
These tests prove the duplicates are gone by changing *only configuration* and
watching the screening outcome change with it.

That is the assertion that matters. A test that merely checks EDD still fires
would pass equally well against the hardcoded version; a test that lowers a
threshold in YAML and sees a previously-clean payment sent for review can only
pass if the registry is genuinely in charge.

Requires PostgreSQL with migrations applied.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.compliance.domain.entities.compliance_rule import ComplianceRule
from app.modules.compliance.infrastructure.compliance_rule_seed_loader import (
    SEED_DATA_DIR as REAL_RULE_SEED_DIR,
)
from app.modules.compliance.infrastructure.compliance_rule_seed_loader import (
    load_compliance_rules,
)
from app.modules.compliance.tests.integration.test_compliance import (
    _create_customer_sync,
    _payment_payload,
    _register_login,
)
from app.platform.database import services as database

DNFBP_RULE = "DNFBP_EDD_REQUIRED"
LARGE_VALUE_RULE = "LARGE_VALUE_REVIEW"

#: The shipped threshold: USD 50,000.00 in minor units.
SHIPPED_THRESHOLD = 5_000_000

#: Comfortably under it, so nothing value-based fires by default.
ORDINARY_AMOUNT = "10000.00"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def screening_users(client: AsyncClient) -> dict:
    _user_id, token = await _register_login(client, role="COMPLIANCE")
    return {"token": token}


@pytest.fixture(scope="module")
def ordinary_parties() -> dict:
    """Two verified, low-risk customers with no sector designation."""
    return {
        "sender_id": _create_customer_sync(entity_name=f"Clean Sender {uuid.uuid4()}"),
        "beneficiary_id": _create_customer_sync(
            entity_name=f"Clean Beneficiary {uuid.uuid4()}", entity_type="SUPPLIER"
        ),
    }


@pytest.fixture(scope="module")
def designated_parties() -> dict:
    """A sender whose sector the registry designates DNFBP."""
    return {
        "sender_id": _create_customer_sync(
            entity_name=f"Diamond House {uuid.uuid4()}",
            sector_classification="PRECIOUS_STONES_TRADE",
        ),
        "beneficiary_id": _create_customer_sync(
            entity_name=f"Clean Beneficiary {uuid.uuid4()}", entity_type="SUPPLIER"
        ),
    }


async def _create_transaction_for(
    client: AsyncClient, token: str, parties: dict, amount: str
) -> str:
    """As ``test_compliance._create_transaction``, but with the amount varied.

    Written here rather than by widening the shared helper, so that changing the
    amount for this suite cannot alter what every other screening test sends.
    """
    payload = _payment_payload(parties["sender_id"], parties["beneficiary_id"])
    payload["amount"] = amount

    resp = await client.post(
        "/api/v1/payments",
        json=payload,
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 202, f"Payment creation failed: {resp.text}"
    return resp.json()["transaction_id"]


async def _screen(client: AsyncClient, token: str, parties: dict, amount: str) -> dict:
    tx_id = await _create_transaction_for(client, token, parties, amount)
    resp = await client.post(
        f"/api/v1/compliance/screen/{tx_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _screening_of(body: dict, screening_type: str) -> dict | None:
    """The screening record of this type, or None. For absence assertions."""
    for record in body["screenings"]:
        if record["screening_type"] == screening_type:
            return record
    return None


def _require_screening(body: dict, screening_type: str) -> dict:
    """The screening record of this type, which must exist.

    A missing record means screening did not run the branch under test, and
    that should fail as a named absence rather than as an obscure error from
    subscripting None.
    """
    record = _screening_of(body, screening_type)
    assert record is not None, (
        f"no {screening_type} screening record; got "
        f"{[r['screening_type'] for r in body['screenings']]}"
    )
    return record


async def _reload_rules(seed_dir) -> None:
    async with database.AsyncSessionLocal() as session:
        await load_compliance_rules(session, seed_dir)


@pytest_asyncio.fixture(loop_scope="function")
async def restored_registry():
    """Put the shipped GitOps rules back, whatever the test did to them."""
    try:
        yield
    finally:
        await _reload_rules(REAL_RULE_SEED_DIR)


# ── the shipped registry produces the shipped behaviour ───────────────────────


async def test_the_shipped_rules_are_loaded(client: AsyncClient):
    """The premise. Screening now reads this table, so an empty one would make
    every assertion below vacuous."""
    async with database.AsyncSessionLocal() as session:
        rule_ids = (await session.execute(select(ComplianceRule.rule_id))).scalars().all()

    assert DNFBP_RULE in rule_ids
    assert LARGE_VALUE_RULE in rule_ids


async def test_a_designated_sector_triggers_edd_through_the_registry(
    client: AsyncClient, screening_users: dict, designated_parties: dict
):
    """PART 5 / DNFBP. The obligation and the rule that imposed it."""
    body = await _screen(
        client, screening_users["token"], designated_parties, ORDINARY_AMOUNT
    )

    assert body["edd_required"] is True

    dnfbp = _require_screening(body, "DNFBP")
    # The rule id proves the decision came from the registry rather than from a
    # label comparison in Python.
    assert DNFBP_RULE in dnfbp["result_payload"]["rule_ids"]


async def test_a_standard_sector_does_not_trigger_edd(
    client: AsyncClient, screening_users: dict, ordinary_parties: dict
):
    """PART 5 / standard sector."""
    body = await _screen(client, screening_users["token"], ordinary_parties, ORDINARY_AMOUNT)

    assert body["edd_required"] is False
    assert _screening_of(body, "DNFBP") is None


async def test_an_ordinary_amount_is_not_sent_for_value_review(
    client: AsyncClient, screening_users: dict, ordinary_parties: dict
):
    """PART 5 / below threshold. USD 10,000.00 against a USD 50,000.00 rule."""
    body = await _screen(client, screening_users["token"], ordinary_parties, ORDINARY_AMOUNT)

    aml = _require_screening(body, "AML_RISK")
    assert aml["result_payload"]["manual_review"] is False
    assert aml["result_payload"]["rule_ids"] == []


async def test_a_large_amount_is_sent_for_value_review(
    client: AsyncClient, screening_users: dict, ordinary_parties: dict
):
    """PART 5 / large value. Exactly at the shipped threshold."""
    body = await _screen(client, screening_users["token"], ordinary_parties, "50000.00")

    aml = _require_screening(body, "AML_RISK")
    assert aml["result_payload"]["manual_review"] is True
    assert aml["result_payload"]["rule_ids"] == [LARGE_VALUE_RULE]


# ── the assertion that only a registry-driven path can pass ───────────────────


async def test_lowering_the_threshold_in_configuration_changes_the_decision(
    client: AsyncClient,
    screening_users: dict,
    ordinary_parties: dict,
    restored_registry,
    tmp_path,
):
    """PART 5 / configuration-driven.

    The same USD 10,000.00 payment that passed above is now reviewed, because a
    YAML file says the threshold is USD 5,000.00. No screening code is touched
    between the two runs — only the seeded rule.

    Against the previous implementation this could not pass: the threshold was
    ``amount >= Decimal("50000")`` in ``score_aml_risk`` and no amount of
    configuration would move it.
    """
    (tmp_path / "compliance-rules.yaml").write_text(
        """
- rule_id: LOWERED_VALUE_REVIEW
  description: "A deliberately low threshold, to prove configuration decides"
  amount_threshold: 500000
  amount_threshold_currency: USD
  required_action: manual_review
  action_reason: "Transaction value above the lowered review threshold."
  effective_from: 2024-01-01
"""
    )
    await _reload_rules(tmp_path)

    body = await _screen(client, screening_users["token"], ordinary_parties, ORDINARY_AMOUNT)

    aml = _require_screening(body, "AML_RISK")
    assert aml["result_payload"]["manual_review"] is True
    assert aml["result_payload"]["rule_ids"] == ["LOWERED_VALUE_REVIEW"]
    assert aml["result_payload"]["reasons"] == [
        "Transaction value above the lowered review threshold."
    ]


async def test_retiring_the_dnfbp_rule_stops_the_edd_obligation(
    client: AsyncClient,
    screening_users: dict,
    designated_parties: dict,
    restored_registry,
    tmp_path,
):
    """The converse, and the stronger proof.

    The sector is still designated DNFBP by the sector registry — S0T2 is
    untouched. Only the *rule* is gone, and with it the obligation. A hardcoded
    ``classification_label == "DNFBP"`` would still fire here.
    """
    (tmp_path / "compliance-rules.yaml").write_text(
        """
- rule_id: UNRELATED_RULE
  description: "A registry with no due-diligence rule in it"
  corridor_match: NO_SUCH_CORRIDOR
  required_action: enhanced_monitoring
  action_reason: "Never matches anything in this suite."
  effective_from: 2024-01-01
"""
    )
    await _reload_rules(tmp_path)

    body = await _screen(
        client, screening_users["token"], designated_parties, ORDINARY_AMOUNT
    )

    assert body["edd_required"] is False
    assert _screening_of(body, "DNFBP") is None


# ── behaviour that must survive the change ────────────────────────────────────


async def test_an_elevated_customer_rating_still_reviews_without_any_rule(
    client: AsyncClient, screening_users: dict, restored_registry, tmp_path
):
    """RiskRating is deliberately *not* in the registry.

    With a registry that imposes nothing, a high-risk counterparty must still be
    sent for review — that decision belongs to ``score_aml_risk`` and stays
    there, because the rule engine has no fact for a customer's rating.
    """
    (tmp_path / "compliance-rules.yaml").write_text(
        """
- rule_id: UNRELATED_RULE
  description: "A registry that imposes nothing on this payment"
  corridor_match: NO_SUCH_CORRIDOR
  required_action: enhanced_monitoring
  action_reason: "Never matches anything in this suite."
  effective_from: 2024-01-01
"""
    )
    await _reload_rules(tmp_path)

    parties = {
        "sender_id": _create_customer_sync(
            entity_name=f"High Risk {uuid.uuid4()}", risk_rating="HIGH"
        ),
        "beneficiary_id": _create_customer_sync(
            entity_name=f"Clean Beneficiary {uuid.uuid4()}", entity_type="SUPPLIER"
        ),
    }

    body = await _screen(client, screening_users["token"], parties, ORDINARY_AMOUNT)

    aml = _require_screening(body, "AML_RISK")
    assert aml["result_payload"]["manual_review"] is True
    assert "Customer risk rating is HIGH" in aml["result_payload"]["reasons"]
    # The registry contributed nothing; the rating alone did it.
    assert aml["result_payload"]["rule_ids"] == []


async def test_sanctions_screening_is_unaffected(
    client: AsyncClient, screening_users: dict
):
    """The sanctions path never consulted the registry and still does not."""
    parties = {
        "sender_id": _create_customer_sync(entity_name="Terror Finance LLC"),
        "beneficiary_id": _create_customer_sync(
            entity_name=f"Clean Beneficiary {uuid.uuid4()}", entity_type="SUPPLIER"
        ),
    }

    body = await _screen(client, screening_users["token"], parties, ORDINARY_AMOUNT)

    assert body["transaction_status"] == "BLOCKED"
