"""No CRM read serves a raw identifier to OPERATIONS or DEVELOPER (architecture
decision 12).

Every other masking test in this repository names the route it tests. That is the
right way to test a rule and the wrong way to test a *surface*: the hole this sweep
exists for is a route nobody thought to name. So this one is built the other way
round — it reads the mounted routes out of the OpenAPI document, calls **every CRM
`GET`** as OPERATIONS and as DEVELOPER, and asserts the response text does not contain
any of the identifiers the fixture world was built with.

Three properties make it worth more than the sum of the targeted tests:

#. **A new route is swept automatically.** Adding a `GET` under `/onboarding` puts it
   in this sweep with no edit here — and if its path parameter is one this module
   cannot fill, the test fails and says so, rather than quietly skipping it. A route
   cannot be added that nobody checked.
#. **It looks for the raw value anywhere in the body**, not at a field it expects. A
   PAN leaking through a `detail` string, an error message, an audit payload or a
   nested snapshot is caught the same way as one on the field it belongs to. That is
   the class of bug the per-route tests cannot see, because they assert on the fields
   they know about.
#. **The expected refusals are asserted both ways.** A route that starts answering
   DEVELOPER, or stops answering OPERATIONS, fails here — both are decisions somebody
   should have made deliberately.

What is *not* claimed: this proves no **raw** identifier is served. It does not prove
each field is masked in the right shape — `mask_identifier` has its own tests — nor
that COMPLIANCE still sees the real values, which `test_route_authorization.py` holds.
The anti-vacuity check below is what stops the sweep from passing because it saw
nothing: every secret must be found in its masked form somewhere.

The world is built once per module through the API, as a user would build it, because
a fixture written straight to the database can carry a shape the service would never
produce, and then the sweep is testing a situation that cannot happen.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.modules.onboarding.api.schemas.masking import (
    mask_email,
    mask_identifier,
    mask_phone,
)
from app.modules.onboarding.tests.fixtures.auth import auth_header, token_with_role
from app.platform.authentication.models import UserRole

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/onboarding"
PREFIX = f"{BASE}/"
#: The OpenAPI document the application serves. Read over HTTP through the `client`
#: fixture rather than from `app.main`: a module never imports the delivery layer
#: (`importlinter.ini`, "modules never import the delivery layer"), its tests included.
OPENAPI = "/api/v1/openapi.json"
PDF = b"%PDF-1.4 sweep"

#: The roles this sweep covers. Both see masked values: architecture decision 12 removed
#: OPERATIONS' ownership exception, and DEVELOPER is kept out of the raw data
#: altogether. COMPLIANCE and ADMIN are deliberately **not** swept — they are allowed
#: the raw values, so sweeping them would assert the opposite of the rule.
MASKED_ROLES = (UserRole.OPERATIONS, UserRole.DEVELOPER)


# ── The world ─────────────────────────────────────────────────────────────────


@dataclass
class World:
    """Ids for the path parameters, and the secrets that must never come back raw."""

    ids: dict[str, str] = field(default_factory=dict)
    #: label → the raw value written. The label is what a failure prints.
    secrets: dict[str, str] = field(default_factory=dict)
    #: label → the form a masked response may carry.
    masked: dict[str, str] = field(default_factory=dict)
    #: The buyer company. Every `{customer_id}` / `{company_id}` route is swept twice,
    #: once for each company, because the two hold different secrets — the Indian
    #: seller's PAN, GSTIN, IEC and CIN, and the foreign buyer's registration number.
    #: Sweeping only the seller left the registration number's masking resting on the
    #: buyer happening to be on the first page of the unfiltered listing.
    buyer_company_id: str = ""

    def as_subject(self, company_id: str) -> dict[str, str]:
        """This world's ids with one company substituted as the subject."""
        return {**self.ids, "customer_id": company_id, "company_id": company_id}

    def subjects(self) -> list[str]:
        return [self.ids["customer_id"], self.buyer_company_id]


def _pan() -> str:
    """A unique PAN — five letters, four digits, a letter — so a leak can only have
    come from this test's own row."""
    letters = "".join(chr(65 + b % 26) for b in uuid.uuid4().bytes[:6])
    return f"{letters[:5]}{uuid.uuid4().int % 10**4:04d}{letters[5]}"


@pytest.fixture(scope="module")
async def storage_root() -> AsyncIterator[None]:
    """Uploads go to a directory of this module's own.

    Set on `os.environ` rather than through `monkeypatch`, which is function-scoped:
    the world is built once, and the upload in it has to land somewhere that outlives
    the first test. `storage/config.py` reads the variable per call, which is what
    makes this work.
    """
    previous = os.environ.get("STORAGE_LOCAL_ROOT")
    with tempfile.TemporaryDirectory() as directory:
        os.environ["STORAGE_LOCAL_ROOT"] = str(Path(directory) / "storage")
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("STORAGE_LOCAL_ROOT", None)
            else:
                os.environ["STORAGE_LOCAL_ROOT"] = previous


@pytest.fixture(scope="module")
async def tokens(client: AsyncClient) -> dict[UserRole, str]:
    return {role: await token_with_role(client, role) for role in UserRole}


@pytest.fixture(scope="module")
async def world(
    client: AsyncClient, tokens: dict[UserRole, str], storage_root: None
) -> World:
    """One company carrying every identifier the sweep looks for, plus the rows the
    parameterised routes need: a deal, a buyer company, a document, a trade
    relationship with an invoice and an outcome, a verification result, a background
    check decision and a case.

    Built as COMPLIANCE, which may see and write the raw values — the sweep then reads
    the same rows as the two roles that may not.
    """
    ops = tokens[UserRole.OPERATIONS]
    compliance = tokens[UserRole.COMPLIANCE]
    world = World()

    async def ok(method: str, path: str, token: str, **kwargs) -> dict:
        headers = {**auth_header(token), **kwargs.pop("headers", {})}
        resp = await client.request(method, f"{BASE}{path}", headers=headers, **kwargs)
        assert resp.status_code in (200, 201, 202), f"{method} {path}: {resp.text}"
        return resp.json()

    pan = _pan()
    secrets = {
        "PAN": pan,
        "GSTIN": f"27{pan}1Z5",
        "IEC": uuid.uuid4().hex[:10].upper(),
        "CIN": f"U51909MH2019PTC{uuid.uuid4().int % 1000000:06d}",
        "contact email": f"sweep.{uuid.uuid4().hex[:8]}@acme-sweep.example",
        "contact phone": f"+9198{uuid.uuid4().int % 100000000:08d}",
    }

    seller = await ok(
        "POST",
        "/exporters",
        compliance,
        json={
            "source": "SALES",
            # Deliberately **not** built from the PAN. The first run of this sweep
            # named the company `Sweep Exports <pan>` and the sweep caught it on four
            # routes: a company's name is not masked and never will be, so a PAN in a
            # name is a real leak — of the fixture's own making. Worth recording,
            # because it is the sweep working.
            "name": f"Sweep Exports {uuid.uuid4().hex[:8].upper()}",
            "country": "IN",
            "pan": secrets["PAN"],
            "gstins": [secrets["GSTIN"]],
            "iec": secrets["IEC"],
            "cin": secrets["CIN"],
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    company_id = seller["customer_id"]
    world.ids["customer_id"] = company_id
    world.ids["company_id"] = company_id

    # The swept OPERATIONS user is the seller's relationship manager: ownership grants
    # nothing, so every read must still come back masked for them.
    me = await client.get("/api/v1/auth/me", headers=auth_header(ops))
    assert me.status_code == 200, me.text
    await ok(
        "POST",
        f"/exporters/{company_id}/relationship-manager",
        ops,
        json={"user_id": me.json()["id"], "seen_user_id": None},
    )

    # A foreign buyer, whose registration number is the sixth secret: it is masked
    # like a CIN, because it names the company in its registrar's index.
    registration_number = f"KVK-{uuid.uuid4().hex[:8].upper()}"
    secrets["registration number"] = registration_number
    buyer = await ok(
        "POST",
        "/exporters",
        compliance,
        json={
            "source": "SALES",
            "name": f"Sweep Trading BV {uuid.uuid4().hex[:6]}",
            "country": "NL",
            "registration_number": registration_number,
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    buyer_company_id = buyer["customer_id"]

    await ok(
        "POST",
        f"/exporters/{company_id}/contacts",
        compliance,
        json={
            "name": "Priya Sweep",
            "email": secrets["contact email"],
            "phone": secrets["contact phone"],
        },
    )
    await ok(
        "POST",
        f"/exporters/{company_id}/qualification/outcome",
        ops,
        json={"outcome": "QUALIFIED", "note": "Qualified for the sweep."},
    )

    deal = await ok(
        "POST", f"/exporters/{company_id}/deals", ops, json={"reference": "Sweep shipment"}
    )
    world.ids["deal_id"] = deal["id"]
    # A buyer **company**, which also creates the pair's trade relationship (3.18).
    await ok(
        "PUT",
        f"/deals/{deal['id']}/buyer",
        ops,
        json={"buyer_company_id": buyer_company_id},
    )

    document = await ok(
        "POST",
        f"/deals/{deal['id']}/documents",
        ops,
        data={
            "category": "PRE_SHIPMENT",
            "document_type": "proforma_invoice",
            "source": "EXPORTER_UPLOAD",
        },
        files={"file": ("proforma_invoice.pdf", PDF, "application/pdf")},
    )
    world.ids["document_id"] = document["id"]

    relationships = await ok(
        "GET", f"/exporters/{company_id}/trade-relationships", compliance
    )
    [relationship] = relationships["relationships"]
    world.ids["relationship_id"] = relationship["id"]
    invoice = await ok(
        "POST",
        f"/trade-relationships/{relationship['id']}/invoices",
        ops,
        json={
            "invoice_number": f"SWEEP-{uuid.uuid4().hex[:6].upper()}",
            "invoice_date": "2026-03-10",
            "amount": "18400.00",
            "currency": "USD",
        },
    )
    world.ids["invoice_id"] = invoice["id"]
    await ok(
        "POST",
        f"/trade-invoices/{invoice['id']}/outcomes",
        ops,
        json={
            "payment_status": "PAID",
            "amount_paid": "18400.00",
            "proof_status": "PROVEN",
            "evidence_note": "Bank advice seen.",
        },
    )

    verification = await ok(
        "POST",
        "/verifications",
        compliance,
        json={
            "verification_type": "KYB",
            "entity_type": "EXPORTER",
            "entity_reference": company_id,
            "payload": {"status": "PASSED"},
            "evidence_note": "Checked for the sweep.",
        },
    )
    world.ids["verification_result_id"] = verification["id"]

    # IN_REVIEW rather than CLEAR: the three terminal values are proposed and need a
    # second officer (maker-checker), and this sweep needs a decision id, not a
    # verdict.
    decision = await ok(
        "POST",
        f"/exporters/{company_id}/background-check/decisions",
        compliance,
        json={"to_value": "IN_REVIEW", "reason": "Opened for the sweep."},
    )
    world.ids["decision_id"] = decision["id"]

    review = await ok("GET", f"/exporters/{company_id}/screening-review", compliance)
    # The catalogue, not `items`: `items` holds the answers, and there are none until
    # one is recorded — which the next call does, so the item-history route has a row
    # to serve rather than an empty list.
    item_key = review["catalogue"][0]["key"]
    world.ids["item_key"] = item_key
    await ok(
        "PUT",
        f"/exporters/{company_id}/screening-review/{item_key}",
        compliance,
        json={"status": "PASSED"},
    )
    criteria = await ok("GET", "/qualification/criteria", compliance)
    world.ids["key"] = criteria["criteria"][0]["key"]

    case = await ok(
        "POST",
        "/cases",
        compliance,
        json={
            "tenant_id": str(uuid.uuid4()),
            "country_code": "IN",
            "case_type": "KYC",
            "subject_type": "INDIVIDUAL",
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    world.ids["case_id"] = case["id"]

    # Edits, so history holds identifier *changes* and not only creations. A
    # GET-only sweep never saw that the registration number was written to history in
    # full; the old value of each edit is a secret too, because history keeps it.
    new_registration = f"KVK-{uuid.uuid4().hex[:8].upper()}"
    await ok(
        "PATCH",
        f"/exporters/{buyer_company_id}",
        compliance,
        json={"registration_number": new_registration},
    )
    secrets["registration number before its edit"] = secrets["registration number"]
    secrets["registration number"] = new_registration
    new_iec = uuid.uuid4().hex[:10].upper()
    await ok("PATCH", f"/exporters/{company_id}", compliance, json={"iec": new_iec})
    secrets["IEC before its edit"] = secrets["IEC"]
    secrets["IEC"] = new_iec

    world.buyer_company_id = buyer_company_id
    world.secrets = secrets
    world.masked = {
        label: mask_email(value)
        if label == "contact email"
        else mask_phone(value)
        if label == "contact phone"
        else mask_identifier(value)
        for label, value in secrets.items()
    }
    return world


# ── What the sweep expects ────────────────────────────────────────────────────

#: CRM `GET`s that refuse one of the swept roles, and which.
#:
#: Asserted in **both** directions, so a route that starts answering a role fails here
#: as loudly as one that starts refusing it. `test_route_authorization.py` and the
#: contract coverage table own *who* may call what; this table is what the sweep
#: observes, and the two disagreeing is a signal rather than duplication.
#:
#: Two of these rows were written by running the sweep rather than by reading the
#: routers, which is the honest way to build such a table: the background-check
#: proposal queue turns out to be closed to OPERATIONS as well, and the import
#: template to DEVELOPER. Neither was obvious from the task's wording.
DEV = UserRole.DEVELOPER
OPS = UserRole.OPERATIONS
BOTH = frozenset({OPS, DEV})

EXPECTED_REFUSALS: dict[str, frozenset[UserRole]] = {
    # The compliance surface is closed to DEVELOPER entirely — not masked, closed.
    # A screening answer or a check result is a judgement about a company, and masking
    # its identifiers would not make it a developer's to read.
    f"{BASE}/verifications": frozenset({DEV}),
    f"{BASE}/verifications/{{verification_result_id}}": frozenset({DEV}),
    f"{BASE}/exporters/{{customer_id}}/screening-review": frozenset({DEV}),
    f"{BASE}/exporters/{{customer_id}}/screening-review/{{item_key}}/history": frozenset({DEV}),
    f"{BASE}/exporters/{{customer_id}}/bank-activity": frozenset({DEV}),
    f"{BASE}/exporters/{{company_id}}/background-check": frozenset({DEV}),
    f"{BASE}/exporters/{{company_id}}/background-check/cycles": frozenset({DEV}),
    f"{BASE}/exporters/{{company_id}}/background-check/decisions": frozenset({DEV}),
    f"{BASE}/exporters/{{company_id}}/background-check/decisions/{{decision_id}}/evidence": frozenset({DEV}),
    f"{BASE}/exporters/{{company_id}}/background-check/proposals": frozenset({DEV}),
    f"{BASE}/background-check/due": frozenset({DEV}),
    # The maker-checker queue, readable only by the people who can act on it: a
    # proposal is a pending compliance judgement, and OPERATIONS is neither the maker
    # nor the checker.
    f"{BASE}/background-check/proposals": BOTH,
    # A document's content is a saved copy: `documents:download` (COMPLIANCE). Everyone
    # else reads the document on screen through `/documents/{id}/preview`.
    f"{BASE}/documents/content": BOTH,
    # The bank-account queue is for those who propose or approve accounts, and the
    # possible group members name beneficial owners: neither is DEVELOPER's.
    f"{BASE}/bank-accounts/pending": frozenset({DEV}),
    f"{BASE}/exporters/{{company_id}}/group/suggestions": frozenset({DEV}),
    # Who is working on what. The review worklists are compliance's; the information
    # requests, badge counts, recent decisions and the staff picker are every staff
    # user's — and none of them DEVELOPER's.
    f"{BASE}/background-check/reviews": BOTH,
    f"{BASE}/background-check/info-requests": frozenset({DEV}),
    f"{BASE}/background-check/recent-decisions": frozenset({DEV}),
    f"{BASE}/worklist/counts": frozenset({DEV}),
    f"{BASE}/staff": frozenset({DEV}),
    # The bulk importer is a staff tool. DEVELOPER may read the CRM, masked; the
    # template is the first step of creating companies, which is not reading.
    f"{BASE}/imports/companies/template": frozenset({DEV}),
    # The legacy KYC/onboarding surface, STAFF-only since before the CRM existed.
    f"{BASE}/cases/{{case_id}}": frozenset({DEV}),
    f"{BASE}/cases/{{case_id}}/transitions": frozenset({DEV}),
    f"{BASE}/{{customer_id}}/sdk-token": frozenset({DEV}),
    f"{BASE}/{{customer_id}}/status": frozenset({DEV}),
}

#: Routes the sweep cannot call, each with the reason. Anything else that cannot be
#: filled fails the test — that is what makes a new route impossible to miss.
UNSWEPT: dict[str, str] = {
    # Signature-authenticated, not role-gated: it is reached by minting a download
    # link, and it serves file bytes rather than a JSON body. The identifiers it could
    # leak are inside the exporter's own document, which masking does not touch.
    f"{BASE}/documents/content": "signature-authenticated byte stream, no role gate",
    # Answers from the legacy `onboarding_request` table. A CRM company has no row
    # there, so both roles get a 404 whose body is a message about a missing request —
    # swept for leaks below all the same, just not expected to answer.
    f"{BASE}/{{customer_id}}/sdk-token": "no onboarding_request row for a CRM company",
    f"{BASE}/{{customer_id}}/status": "no onboarding_request row for a CRM company",
}

@pytest.fixture(scope="module")
async def crm_gets(client: AsyncClient) -> list[str]:
    """Every mounted `GET` under the CRM prefix, from the served OpenAPI document."""
    resp = await client.get(OPENAPI)
    assert resp.status_code == 200, f"{OPENAPI} answered {resp.status_code}"
    return sorted(
        path
        for path, operations in resp.json()["paths"].items()
        if path.startswith(PREFIX) and "get" in operations
    )


def _fill(path: str, ids: dict[str, str]) -> str | None:
    """Substitute ids for the path parameters, or `None` if one of them is a parameter
    the world does not hold."""
    out = path
    while "{" in out:
        head, _, rest = out.partition("{")
        name, _, tail = rest.partition("}")
        if name not in ids:
            return None
        out = head + ids[name] + tail
    return out


def _query_for(path: str, company_id: str) -> dict[str, str]:
    if path == f"{BASE}/verifications":
        # Its two required parameters. Pointed at the company being swept, so the
        # listing is this test's own results rather than whatever the page holds.
        return {"entity_type": "EXPORTER", "entity_reference": company_id}
    return {}


# ── The sweep ─────────────────────────────────────────────────────────────────


async def test_every_crm_get_is_either_swept_or_declared_unsweepable(crm_gets: list[str]):
    """The guard that makes the sweep automatic.

    A new `GET` whose path parameter this module cannot fill fails here, naming the
    parameter. The fix is to build that row in `world` — or, if it genuinely cannot be
    reached, to add it to `UNSWEPT` with a reason. Either way somebody decides.

    It runs without the `world` fixture, against a world holding every parameter name
    rather than real ids, because what it checks is the parameter *names* — and a
    failure should not depend on a database. Reading the served document needs none.
    """
    known = World(
        ids={
            name: "x"
            for name in (
                "customer_id",
                "company_id",
                "deal_id",
                "document_id",
                "relationship_id",
                "invoice_id",
                "verification_result_id",
                "decision_id",
                "item_key",
                "key",
                "case_id",
            )
        }
    )
    unfillable = [
        path
        for path in crm_gets
        if path not in UNSWEPT and _fill(path, known.ids) is None
    ]
    assert not unfillable, (
        "These CRM GETs have a path parameter the masking sweep cannot fill. Build the "
        "row in `world` and add the parameter above, or add the route to `UNSWEPT` with "
        "a reason:\n  " + "\n  ".join(unfillable)
    )


async def test_the_unswept_table_names_only_routes_that_exist(crm_gets: list[str]):
    """So the exclusions cannot rot into exclusions of nothing."""
    stale = sorted(set(UNSWEPT) - set(crm_gets))
    assert not stale, "Declared unsweepable but not mounted:\n  " + "\n  ".join(stale)


async def test_every_refused_route_is_mounted(crm_gets: list[str]):
    stale = sorted(set(EXPECTED_REFUSALS) - set(crm_gets))
    assert not stale, "Declared as refusing a role but not mounted:\n  " + "\n  ".join(
        stale
    )


@pytest.mark.parametrize("role", MASKED_ROLES)
async def test_no_crm_read_serves_a_raw_identifier(
    client: AsyncClient,
    tokens: dict[UserRole, str],
    world: World,
    crm_gets: list[str],
    role: UserRole,
):
    """The sweep itself: every CRM `GET`, and not one raw identifier in any body.

    The whole response **text** is searched, not a field: that is the point. A PAN in
    an error message, in a nested snapshot, in an audit payload or in a field added
    after this test was written is caught the same way as one on the field it belongs
    to, and none of those is a place a per-route test would look.

    Bodies are searched whatever the status code. A 404 or a 403 that echoed an
    identifier back would be a leak as surely as a 200 — and a message built from the
    request is exactly where that happens.
    """
    leaks: list[str] = []
    for company_id in world.subjects():
        ids = world.as_subject(company_id)
        for path in crm_gets:
            filled = _fill(path, ids)
            if filled is None:
                # Declared in `UNSWEPT`; the guard above proves it was declared on
                # purpose and not forgotten.
                continue
            resp = await client.request(
                "GET",
                filled,
                headers=auth_header(tokens[role]),
                params=_query_for(path, company_id),
            )
            body = resp.text
            for label, value in world.secrets.items():
                if value in body:
                    leaks.append(
                        f"{path} ({resp.status_code}) carries the raw {label}"
                    )

    assert not leaks, f"{role.value} was served raw identifiers:\n  " + "\n  ".join(leaks)


@pytest.mark.parametrize("role", MASKED_ROLES)
async def test_the_sweep_actually_read_the_data_it_claims_to_have_checked(
    client: AsyncClient,
    tokens: dict[UserRole, str],
    world: World,
    crm_gets: list[str],
    role: UserRole,
):
    """The anti-vacuity check, and the reason this file is worth trusting.

    A sweep that found nothing would pass. So every secret must be found in its
    **masked** form in at least one response — which proves the sweep read the rows
    that hold it, with the masking applied, rather than passing on a wall of 404s.

    DEVELOPER included: the compliance surface is closed to them, not the company
    record, so they still see the company, its contacts, its branches and its deals —
    masked.
    """
    found: dict[str, str] = {}
    for company_id in world.subjects():
        ids = world.as_subject(company_id)
        for path in crm_gets:
            filled = _fill(path, ids)
            if filled is None:
                continue
            resp = await client.request(
                "GET",
                filled,
                headers=auth_header(tokens[role]),
                params=_query_for(path, company_id),
            )
            if resp.status_code != 200:
                continue
            for label, masked in world.masked.items():
                if masked and masked in resp.text:
                    found.setdefault(label, path)

    missing = sorted(set(world.masked) - set(found))
    assert not missing, (
        f"The sweep never saw these masked, so it proved nothing about them for "
        f"{role.value}: {missing}. Either a route stopped serving them or the world "
        "stopped carrying them."
    )


@pytest.mark.parametrize("role", MASKED_ROLES)
async def test_the_reads_that_are_expected_to_answer_do(
    client: AsyncClient,
    tokens: dict[UserRole, str],
    world: World,
    crm_gets: list[str],
    role: UserRole,
):
    """Both directions of the refusal table.

    A route that begins answering a role it is declared to refuse, or stops answering
    one it is not, fails here — each is a decision somebody should have made on
    purpose. Without this, a route gated shut by accident would quietly make the sweep
    above pass more easily, which is the failure mode of every sweep.
    """
    wrong: list[str] = []
    # The seller only: whether a route answers a role is a question about the route,
    # not about which company it is pointed at, and asking twice would report every
    # disagreement twice.
    for path in crm_gets:
        filled = _fill(path, world.ids)
        if filled is None:
            continue
        resp = await client.request(
            "GET",
            filled,
            headers=auth_header(tokens[role]),
            params=_query_for(path, world.ids["customer_id"]),
        )
        refused = resp.status_code == 403
        should_refuse = role in EXPECTED_REFUSALS.get(path, frozenset())
        if refused and not should_refuse:
            wrong.append(f"{path} refused {role.value} (403), which is not declared")
        elif should_refuse and not refused:
            wrong.append(
                f"{path} answered {role.value} with {resp.status_code}; "
                "it is declared as refused"
            )
        elif not refused and path not in UNSWEPT and resp.status_code != 200:
            wrong.append(f"{path} answered {resp.status_code}, so it was not really swept")

    assert not wrong, "\n  " + "\n  ".join(wrong)
