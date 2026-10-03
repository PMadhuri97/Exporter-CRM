"""Turn legacy deal buyers into company records — **owner: Developer 2**
(allocation task 2.6, plan P4-6 and §17.2).

    python -m app.modules.onboarding.migrate_deal_buyers --dry-run
    python -m app.modules.onboarding.migrate_deal_buyers --apply --run-id 2026-10-03a
    python -m app.modules.onboarding.migrate_deal_buyers --validate
    python -m app.modules.onboarding.migrate_deal_buyers --rollback --run-id 2026-10-03a

``--rollback`` **writes nothing**: it reports what a run did and what undoing it
takes. §17.2's logical rollback turns out not to be available in the shipped schema —
both ``deal.buyer_company_id`` and ``verification_result.subject_company_id`` are
set-once and frozen by triggers, so neither can be set back to ``NULL``. Restoring the
``pg_dump`` is the only route back, which is why taking one is step zero and not a
precaution. See ``rollback`` for how this was found.

A command and not an Alembic revision, because §17.2 puts a **person** between
reading and writing: name-only duplicates are reported and confirmed by hand
(decision IQ-8), and a revision has nowhere to pause for that.

**Nothing here has been run against real data.** It is tested against a seeded
database covering §17.2's edge cases. Sizing a real run needs Developer 3's 3.2
reports, and the name-only duplicates need Compliance's review — so the intended
sequence is: ``pg_dump``, ``--dry-run``, read the report, confirm the duplicates,
``--apply``, ``--validate``.

How a buyer's identity is resolved (§17.2, in order of confidence)
------------------------------------------------------------------
#. **A PAN.** An Indian buyer whose ``tax_id`` is a PAN, or a GSTIN carrying one,
   joins the company holding that PAN. This is R1's case and it may well join an
   existing **seller** — which is the whole point of unifying the two.
#. **A registration number.** A foreign buyer joins the company with the same
   ``(country, normalised registration number)``, or shares one with another deal
   buyer carrying the same pair.
#. **Nothing shared** — a new ``NOT_IN_PIPELINE`` company.
#. **A matching name and no identifier** — reported as a possible duplicate and
   **never merged automatically**. A person confirms it, and the mapping is marked
   ``NAME_CONFIRMED`` so the record says a human decided.

Two refusals, both reported rather than worked around:

* a buyer resolving to **its own deal's seller** — a company does not sell to
  itself, and the row needs correcting by hand;
* a buyer whose identifiers **conflict** (a PAN naming one company, a registration
  number another) — picking one silently is the one outcome worth refusing.

What ``--apply`` writes, per §17.2
----------------------------------
``deal_buyer_company_map`` (one row per deal buyer, append-only, carrying the rule
and the run), the created companies (through ``CompanyDirectory.create_buyer_company``,
so they get ``DEAL_BUYER``, ``NOT_IN_PIPELINE``, ``created_via_deal_id`` and their
one ``pipeline`` history row), ``deal.buyer_company_id``, and
``verification_result.subject_company_id`` for the deal's BUYER results.

It does **not** touch ``deal_buyer`` rows, ``entity_type``, ``entity_reference``,
``subject_snapshot`` or any history row. Existing history stays on the seller's
timeline and reaches the buyer company by the read-side union task 2.7 added. The
``handover_snapshot`` of a handed-over deal was taken from the ``deal_buyer`` row
before this ever runs (P2-7), so what the lending team was given cannot change.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

# The onboarding package's API and application layers import each other, so whichever
# is imported *first* decides whether that resolves. Importing the API package here
# settles it before anything else does — needed only because this module is a command
# and so is the first thing Python loads. Every other caller arrives through the app.
import app.modules.onboarding.api  # noqa: F401  (import order, not an unused import)
from app.modules.onboarding.application.company_directory import CompanyDirectoryService
from app.modules.onboarding.domain.company_directory import BuyerCompanyDraft
from app.modules.onboarding.domain.company_identity import registration_key
from app.modules.onboarding.domain.company_names import name_key
from app.modules.onboarding.domain.entities.deal import Deal
from app.modules.onboarding.domain.entities.deal_buyer import DealBuyer
from app.modules.onboarding.domain.entities.deal_buyer_company_map import (
    BuyerMatchRule,
    DealBuyerCompanyMap,
)
from app.modules.onboarding.domain.entities.exporter_gstin import ExporterGstin
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
)
from app.modules.onboarding.domain.entities.verification_result import VerificationResult
from app.modules.onboarding.domain.tax_identifiers import GSTIN_RE, PAN_RE, embedded_pan
from app.platform.database import services as db_services

logger = structlog.get_logger(__name__)

SOURCE = "migration_p4_6_deal_buyers"

#: How many rows the report prints in full before summarising. The first run of this
#: printed 568 — see `Report.render`.
DEFAULT_ROWS_SHOWN = 20

#: How many candidate companies a single name-only match prints. More than a handful
#: means the name is not distinguishing anything, and the right next step is a query,
#: not a longer report line.
MAX_CANDIDATES_SHOWN = 5

#: A merge at or above this many deal buyers is called out for a human to look at.
LARGE_MERGE = 25


@dataclass
class _Resolution:
    """What one ``deal_buyer`` row resolved to, and why."""

    deal_buyer_id: uuid.UUID
    deal_id: uuid.UUID
    seller_company_id: uuid.UUID
    name: str
    country: str
    rule: BuyerMatchRule | None = None
    #: The company it joins, when an identifier found one.
    company_id: uuid.UUID | None = None
    #: Other deal buyers it shares an identity with — the logical merge.
    group_key: str | None = None
    #: Why it cannot proceed without a person. Empty means it can.
    problems: list[str] = field(default_factory=list)
    #: Companies a name-only match found, for a person to confirm or reject.
    name_candidates: list[uuid.UUID] = field(default_factory=list)
    pan: str | None = None
    registration_number: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None


@dataclass
class Report:
    """What a run did, or would do. Printed by ``--dry-run`` and ``--apply``."""

    resolutions: list[_Resolution] = field(default_factory=list)

    @property
    def ready(self) -> list[_Resolution]:
        return [r for r in self.resolutions if not r.problems and r.rule is not None]

    @property
    def needs_a_person(self) -> list[_Resolution]:
        return [r for r in self.resolutions if r.problems or r.rule is None]

    @property
    def groups(self) -> dict[str, list[_Resolution]]:
        """The logical merges: deal buyers sharing one identity."""
        grouped: dict[str, list[_Resolution]] = defaultdict(list)
        for r in self.ready:
            if r.group_key:
                grouped[r.group_key].append(r)
        return {k: v for k, v in grouped.items() if len(v) > 1}

    def render(self, *, show: int = DEFAULT_ROWS_SHOWN) -> str:
        """The operator's report.

        **Deliberately truncated.** The first run of this against a seeded database
        printed 568 problem rows, several listing 73 candidate company ids on one
        line — information nobody can act on, and a report nobody reads is worse than
        a short one. So: counts always, the first ``show`` rows in full, and
        ``--show-all`` when somebody really wants the lot.

        A merge larger than ``LARGE_MERGE`` is called out separately. Merging forty
        deal buyers into one company may be exactly right — a regular counterparty —
        but it is also what a too-loose identity rule looks like, and the difference
        is a judgement only a person can make.
        """
        lines = [
            "",
            "Buyer migration (P4-6) — report",
            "=" * 60,
            f"deal_buyer rows considered: {len(self.resolutions)}",
            f"  ready to migrate:         {len(self.ready)}",
            f"  need a person:            {len(self.needs_a_person)}",
        ]
        by_rule: dict[str, int] = defaultdict(int)
        for r in self.ready:
            by_rule[r.rule.value if r.rule else "?"] += 1
        for rule, count in sorted(by_rule.items()):
            lines.append(f"    {rule:<22} {count}")

        merges = self.groups
        if merges:
            companies = len(merges)
            rows = sum(len(v) for v in merges.values())
            lines += [
                "",
                f"Logical merges: {rows} deal buyers resolve to {companies} companies.",
            ]
            large = {k: v for k, v in merges.items() if len(v) >= LARGE_MERGE}
            if large:
                lines.append(
                    f"  {len(large)} of them merge {LARGE_MERGE}+ rows — worth a look "
                    "before --apply, since a regular counterparty and a too-loose "
                    "identity rule look the same from here:"
                )
                for key, group in sorted(large.items(), key=lambda kv: -len(kv[1])):
                    names = sorted({r.name for r in group})
                    shown = ", ".join(names[:3]) + (
                        f" (+{len(names) - 3} more names)" if len(names) > 3 else ""
                    )
                    lines.append(f"    {key}: {len(group)} rows — {shown}")
            for key, group in sorted(merges.items())[:show]:
                if key in large:
                    continue
                names = ", ".join(sorted({r.name for r in group}))
                lines.append(f"  {key}: {len(group)} rows — {names}")
            if len(merges) > show:
                lines.append(f"  … and {len(merges) - show} more merges")

        if self.needs_a_person:
            blocked = self.needs_a_person
            lines += [
                "",
                f"Needs a person before --apply: {len(blocked)} row(s).",
                "  --apply skips these; it does not guess.",
            ]
            by_problem: dict[str, int] = defaultdict(int)
            for r in blocked:
                for problem in r.problems or ["no rule matched"]:
                    by_problem[problem.split(":")[0]] += 1
            for problem, count in sorted(by_problem.items(), key=lambda kv: -kv[1]):
                lines.append(f"    {count:>6}  {problem}")

            lines.append("")
            for r in blocked[:show]:
                for problem in r.problems or ["no rule matched"]:
                    lines.append(f"  deal {r.deal_id} / buyer {r.deal_buyer_id}")
                    lines.append(f"    {problem}")
                # One line per candidate, never a comma-joined list: confirming a
                # duplicate means choosing *one* company, and a line that listed
                # seventy would read as confirming all of them.
                for candidate in r.name_candidates[:MAX_CANDIDATES_SHOWN]:
                    lines.append(
                        f"    --confirm-name {r.deal_buyer_id}={candidate}"
                    )
                extra = len(r.name_candidates) - MAX_CANDIDATES_SHOWN
                if extra > 0:
                    lines.append(
                        f"    … and {extra} more candidate(s); query "
                        "exporter_profile by name and country to see them all"
                    )
            if len(blocked) > show:
                lines.append(f"  … and {len(blocked) - show} more; --show-all lists every one")
        lines.append("")
        return "\n".join(lines)


# ── Resolution ────────────────────────────────────────────────────────────────


def _buyer_pan(buyer: DealBuyer) -> str | None:
    """The PAN a buyer's ``tax_id`` carries, if any (§17.2 step 2).

    ``tax_id`` is free text on a legacy row, so it may hold a PAN, a GSTIN, or
    something else entirely. A GSTIN carries its company's PAN in characters 3–12,
    which is the same rule the CRM already uses to match a company by GSTIN.
    """
    if (buyer.country or "").strip().upper() != "IN":
        return None
    value = (buyer.tax_id or "").strip().upper()
    if PAN_RE.match(value):
        return value
    if GSTIN_RE.match(value):
        return embedded_pan(value)
    return None


async def resolve(db: AsyncSession) -> Report:
    """Work out what every unmapped ``deal_buyer`` row is, without writing anything.

    Already-mapped rows are skipped, which is what makes a re-run a no-op.
    """
    mapped = set(await db.scalars(select(DealBuyerCompanyMap.deal_buyer_id)))
    rows = await db.execute(
        select(DealBuyer, Deal.company_id, Deal.id)
        .join(Deal, Deal.id == DealBuyer.deal_id)
        .order_by(DealBuyer.created_at, DealBuyer.id)
    )

    report = Report()
    #: Identity key -> the resolution that claimed it first, so later rows join it.
    claimed: dict[str, _Resolution] = {}

    for buyer, seller_company_id, deal_id in rows:
        if buyer.id in mapped:
            continue
        resolution = _Resolution(
            deal_buyer_id=buyer.id,
            deal_id=deal_id,
            seller_company_id=seller_company_id,
            name=buyer.name,
            country=(buyer.country or "").strip().upper(),
            pan=_buyer_pan(buyer),
            registration_number=(buyer.registration_number or "").strip() or None,
            contact_email=buyer.contact_email,
            contact_phone=buyer.contact_phone,
        )
        await _resolve_one(db, resolution, claimed)
        report.resolutions.append(resolution)

    return report


async def _resolve_one(
    db: AsyncSession, r: _Resolution, claimed: dict[str, _Resolution]
) -> None:
    found: dict[str, uuid.UUID] = {}

    # Step 2: a PAN, directly or through a GSTIN.
    if r.pan:
        holder = await db.scalar(
            select(ExporterProfile.customer_id).where(ExporterProfile.pan == r.pan)
        )
        if holder is None:
            # A company created from a GSTIN-only delivery holds the GSTIN but no PAN.
            holder = await db.scalar(
                select(ExporterGstin.customer_id).where(
                    ExporterGstin.gstin.like(f"__{r.pan}%"),
                    ExporterGstin.active.is_(True),
                )
            )
        if holder is not None:
            found["PAN"] = holder
        r.group_key = f"PAN:{r.pan}"
        r.rule = BuyerMatchRule.PAN

    # Step 3: a foreign registration number.
    if r.registration_number and r.country:
        key = registration_key(r.registration_number)
        holder = await db.scalar(
            select(ExporterProfile.customer_id).where(
                ExporterProfile.country == r.country,
                ExporterProfile.registration_number.isnot(None),
                text(
                    "upper(regexp_replace(exporter_profile.registration_number, "
                    "'[^A-Za-z0-9]', '', 'g')) = :key"
                ).bindparams(key=key),
            )
        )
        if holder is not None:
            found["registration number"] = holder
        if r.rule is None:
            r.group_key = f"REG:{r.country}:{key}"
            r.rule = BuyerMatchRule.REGISTRATION_NUMBER

    if len(set(found.values())) > 1:
        # Identifiers naming different companies. Picking one silently is the one
        # outcome worth refusing (IQ-8).
        named = ", ".join(f"{label} → {company}" for label, company in sorted(found.items()))
        r.problems.append(f"identifiers name different companies: {named}")
        return

    r.company_id = next(iter(found.values()), None)

    # An earlier row already claimed this identity: they are the same company.
    if r.company_id is None and r.group_key and r.group_key in claimed:
        first = claimed[r.group_key]
        r.company_id = first.company_id
        r.rule = first.rule
    elif r.group_key:
        claimed.setdefault(r.group_key, r)

    # Step 4: no identifier at all — a name match is a *possible* duplicate only.
    if r.rule is None:
        key = name_key(r.name)
        if key and r.country:
            rows = await db.execute(
                select(ExporterProfile.customer_id, ExporterProfile.name).where(
                    ExporterProfile.country == r.country,
                    ExporterProfile.name.isnot(None),
                )
            )
            r.name_candidates = sorted(
                (row.customer_id for row in rows if name_key(row.name) == key), key=str
            )
        if r.name_candidates:
            r.problems.append(
                f"{len(r.name_candidates)} company(ies) in {r.country} share this name "
                "and it carries no identifier: confirm or reject by hand (IQ-8)"
            )
            return
        r.rule = BuyerMatchRule.NEW
        r.group_key = f"NAME:{r.country}:{name_key(r.name)}"
        claimed.setdefault(r.group_key, r)

    # A buyer that resolves to its own deal's seller: refused (§17.2 step 5).
    if r.company_id is not None and r.company_id == r.seller_company_id:
        r.problems.append(
            f"resolves to the deal's own seller ({r.company_id}): a company does not "
            "sell to itself, so this row needs correcting by hand"
        )


# ── Apply ─────────────────────────────────────────────────────────────────────


async def apply(
    db: AsyncSession,
    report: Report,
    *,
    run_id: str,
    actor_id: str | None,
    confirmed: dict[uuid.UUID, uuid.UUID] | None = None,
) -> dict[str, int]:
    """Write everything §17.2 asks for, for the rows that are ready.

    ``confirmed`` carries a person's decisions about name-only duplicates:
    ``{deal_buyer_id: company_id}``. Those rows are mapped with
    ``NAME_CONFIRMED``, so the record says a human decided rather than a rule.

    Rows that still need a person are **skipped**, not guessed. The run is safe to
    repeat: every write is keyed on a mapping that does not yet exist.
    """
    confirmed = confirmed or {}
    counts = {"companies_created": 0, "mapped": 0, "deals_linked": 0, "results_linked": 0}
    directory = CompanyDirectoryService(db)
    #: group key -> the company the group resolved to, created at most once.
    created_for_group: dict[str, uuid.UUID] = {}

    for r in report.resolutions:
        company_id = confirmed.get(r.deal_buyer_id)
        rule = BuyerMatchRule.NAME_CONFIRMED if company_id else r.rule
        if company_id is None:
            if r.problems or r.rule is None:
                continue
            company_id = r.company_id
            if company_id is None and r.group_key:
                company_id = created_for_group.get(r.group_key)

        if company_id is None:
            company_id = await directory.create_buyer_company(
                BuyerCompanyDraft(
                    name=r.name,
                    country=r.country,
                    pan=r.pan,
                    registration_number=r.registration_number,
                    contact_email=r.contact_email,
                    contact_phone=r.contact_phone,
                    created_via_deal_id=r.deal_id,
                    source_ref=run_id,
                ),
                actor_id=actor_id,
            )
            counts["companies_created"] += 1
            if r.group_key:
                created_for_group[r.group_key] = company_id

        db.add(
            DealBuyerCompanyMap(
                deal_buyer_id=r.deal_buyer_id,
                company_id=company_id,
                match_rule=rule or BuyerMatchRule.NEW,
                matched_by=actor_id,
                run_id=run_id,
            )
        )
        counts["mapped"] += 1

        # `deal.buyer_company_id` is set-once, so only a deal that has none is
        # touched — which also makes a partially-finished run safe to repeat.
        linked = await db.execute(
            update(Deal)
            .where(Deal.id == r.deal_id, Deal.buyer_company_id.is_(None))
            .values(buyer_company_id=company_id)
        )
        counts["deals_linked"] += linked.rowcount or 0

        # The deal's BUYER results become the buyer company's. `entity_type`,
        # `entity_reference` and `subject_snapshot` are left exactly as they are
        # (§17.2): every read already prefers `subject_company_id` when it is set.
        results = await db.execute(
            update(VerificationResult)
            .where(
                VerificationResult.entity_type == VerificationEntityType.BUYER,
                VerificationResult.entity_reference == r.deal_buyer_id,
                VerificationResult.subject_company_id.is_(None),
            )
            .values(subject_company_id=company_id)
        )
        counts["results_linked"] += results.rowcount or 0

    await db.commit()
    logger.info("buyer_migration.applied", run_id=run_id, **counts)
    return counts


# ── Validation (§17.2) ────────────────────────────────────────────────────────

#: Every query must return 0. The names are what the operator reads, so they say
#: what is wrong rather than what was counted.
VALIDATION_QUERIES: tuple[tuple[str, str], ...] = (
    (
        "deals with a deal_buyer but no buyer_company_id",
        """
        SELECT count(*) FROM onboarding.deal d
        JOIN onboarding.deal_buyer b ON b.deal_id = d.id
        WHERE d.buyer_company_id IS NULL
        """,
    ),
    (
        "BUYER verification results with no subject_company_id",
        """
        SELECT count(*) FROM onboarding.verification_result r
        JOIN onboarding.deal_buyer b ON b.id = r.entity_reference
        WHERE r.entity_type = 'BUYER' AND r.subject_company_id IS NULL
        """,
    ),
    (
        "deals whose buyer company is their own seller",
        "SELECT count(*) FROM onboarding.deal WHERE buyer_company_id = company_id",
    ),
    (
        "deal_buyer rows with no mapping",
        """
        SELECT count(*) FROM onboarding.deal_buyer b
        LEFT JOIN onboarding.deal_buyer_company_map m ON m.deal_buyer_id = b.id
        WHERE m.deal_buyer_id IS NULL
        """,
    ),
    (
        "companies created by a run without exactly one pipeline history row",
        """
        SELECT count(*) FROM onboarding.exporter_profile p
        WHERE p.created_via = 'DEAL_BUYER'
          AND (
            SELECT count(*) FROM onboarding.exporter_lifecycle_history h
            WHERE h.customer_id = p.customer_id AND h.dimension = 'pipeline'
          ) <> 1
        """,
    ),
    (
        "HANDED_OVER deals without a handover snapshot",
        """
        SELECT count(*) FROM onboarding.deal
        WHERE stage = 'HANDED_OVER' AND handover_snapshot IS NULL
        """,
    ),
    (
        "migrated identifiers containing the mask character",
        """
        SELECT count(*) FROM onboarding.exporter_profile
        WHERE created_via = 'DEAL_BUYER'
          AND (coalesce(pan, '') LIKE '%•%'
               OR coalesce(registration_number, '') LIKE '%•%'
               OR coalesce(cin, '') LIKE '%•%'
               OR coalesce(iec, '') LIKE '%•%')
        """,
    ),
)


async def validate(db: AsyncSession) -> list[tuple[str, int]]:
    """Run §17.2's validation queries. Every count must be 0."""
    results: list[tuple[str, int]] = []
    for label, sql in VALIDATION_QUERIES:
        results.append((label, int(await db.scalar(text(sql)) or 0)))
    return results


async def rollback(db: AsyncSession, *, run_id: str) -> dict[str, int]:
    """Report what a run did and what it would take to undo it. **Writes nothing.**

    §17.2 describes a logical rollback — ``UPDATE deal SET buyer_company_id = NULL``
    and ``UPDATE verification_result SET subject_company_id = NULL`` — with the
    caveat that it *"needs the freeze trigger to allow NULL→value only, so do the
    rollback before enabling it, or restore"*.

    In the shipped schema **both** triggers are enabled:

    * ``trg_deal_buyer_company_set_once`` on ``deal.buyer_company_id``;
    * ``trg_verification_result_input_immutability`` on
      ``verification_result.subject_company_id``.

    So neither column can be set back to ``NULL``, and the logical rollback is not
    available. This was discovered by writing the test rather than by reading the
    plan, which is worth recording: an earlier version of this function attempted
    both updates and would have failed **partway through**, after clearing some
    results, leaving the operator unsure which half had happened.

    What this does instead is tell the truth: it counts what the run touched and
    prints the one route back, which is the ``pg_dump`` taken before it. That is why
    the dump is step zero and not a precaution.
    """
    mapped = list(
        await db.scalars(
            select(DealBuyerCompanyMap.deal_buyer_id).where(
                DealBuyerCompanyMap.run_id == run_id
            )
        )
    )
    if not mapped:
        return {"mapped": 0, "deals_linked": 0, "results_linked": 0, "companies_created": 0}

    deal_ids = list(
        await db.scalars(select(DealBuyer.deal_id).where(DealBuyer.id.in_(mapped)))
    )
    deals_linked = int(
        await db.scalar(
            select(func.count())
            .select_from(Deal)
            .where(Deal.id.in_(deal_ids), Deal.buyer_company_id.isnot(None))
        )
        or 0
    )
    results_linked = int(
        await db.scalar(
            select(func.count())
            .select_from(VerificationResult)
            .where(
                VerificationResult.entity_type == VerificationEntityType.BUYER,
                VerificationResult.entity_reference.in_(mapped),
                VerificationResult.subject_company_id.isnot(None),
            )
        )
        or 0
    )
    companies_created = int(
        await db.scalar(
            select(func.count(func.distinct(DealBuyerCompanyMap.company_id))).where(
                DealBuyerCompanyMap.run_id == run_id
            )
        )
        or 0
    )
    counts = {
        "mapped": len(mapped),
        "deals_linked": deals_linked,
        "results_linked": results_linked,
        "companies_created": companies_created,
    }
    logger.info("buyer_migration.rollback_report", run_id=run_id, **counts)
    return counts


# ── The command ───────────────────────────────────────────────────────────────


def _parse_confirmations(values: list[str] | None) -> dict[uuid.UUID, uuid.UUID]:
    """``--confirm-name <deal_buyer_id>=<company_id>``, repeatable.

    The dry-run report prints these lines ready to paste, so confirming a duplicate
    is a deliberate act naming both sides rather than a yes/no prompt nobody can
    audit afterwards.
    """
    confirmed: dict[uuid.UUID, uuid.UUID] = {}
    for value in values or []:
        left, _, right = value.partition("=")
        if not right:
            raise SystemExit(f"--confirm-name wants <deal_buyer_id>=<company_id>, got {value!r}")
        if "," in right:
            # Refused rather than taking the first: confirming a duplicate means
            # choosing **one** company, and accepting a list would let a pasted
            # report line look like a decision somebody made.
            raise SystemExit(
                f"--confirm-name takes one company id, got several: {right.strip()!r}"
            )
        confirmed[uuid.UUID(left.strip())] = uuid.UUID(right.strip())
    return confirmed


async def _main(args: argparse.Namespace) -> int:
    async with db_services.AsyncSessionLocal() as db:
        if args.validate:
            failures = 0
            print("\n§17.2 validation")
            print("=" * 60)
            for label, count in await validate(db):
                status = "OK  " if count == 0 else "FAIL"
                if count:
                    failures += 1
                print(f"{status} {count:>6}  {label}")
            print()
            return 1 if failures else 0

        if args.rollback:
            counts = await rollback(db, run_id=args.run_id)
            print(f"\nRun {args.run_id} — what it did")
            print("=" * 60)
            if not counts["mapped"]:
                print("Nothing: no mapping rows carry that run id.\n")
                return 0
            print(f"  deal buyers mapped:    {counts['mapped']}")
            print(f"  companies involved:    {counts['companies_created']}")
            print(f"  deals linked:          {counts['deals_linked']}")
            print(f"  results re-subjected:  {counts['results_linked']}")
            print(
                "\nThis command wrote nothing. §17.2's logical rollback is **not "
                "available**: both `deal.buyer_company_id` and\n"
                "`verification_result.subject_company_id` are set-once and frozen by "
                "triggers, so neither can be\nset back to NULL.\n\n"
                "To undo this run, restore the pg_dump taken before it. That is the "
                "only route, which is why\ntaking one is step zero.\n"
            )
            return 0

        report = await resolve(db)
        print(report.render(show=10**9 if args.show_all else DEFAULT_ROWS_SHOWN))

        if args.dry_run:
            print("Dry run: nothing was written.")
            if report.needs_a_person:
                print(
                    f"{len(report.needs_a_person)} row(s) need a person before --apply; "
                    "the lines above name them."
                )
            return 0

        counts = await apply(
            db,
            report,
            run_id=args.run_id,
            actor_id=args.actor or f"migration:{args.run_id}",
            confirmed=_parse_confirmations(args.confirm_name),
        )
        print(f"Applied run {args.run_id}: {counts}")
        skipped = len(report.needs_a_person) - len(_parse_confirmations(args.confirm_name))
        if skipped > 0:
            print(f"{skipped} row(s) were skipped and still need a person.")
        print("Now run --validate; every count must be 0.\n")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.modules.onboarding.migrate_deal_buyers",
        description=(
            "Turn legacy deal buyers into company records (P4-6). Take a pg_dump "
            "first, read the --dry-run report, confirm any name-only duplicates, "
            "then --apply and --validate."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="report, write nothing")
    mode.add_argument("--apply", action="store_true", help="write the migration")
    mode.add_argument("--validate", action="store_true", help="run §17.2's checks")
    mode.add_argument(
        "--rollback",
        action="store_true",
        help="report what a run did and what undoing it takes (writes nothing)",
    )
    parser.add_argument("--run-id", help="required for --apply and --rollback")
    parser.add_argument("--actor", help="who is running it; defaults to the run id")
    parser.add_argument(
        "--show-all",
        action="store_true",
        help="print every row rather than the first few of each kind",
    )
    parser.add_argument(
        "--confirm-name",
        action="append",
        metavar="BUYER_ID=COMPANY_ID",
        help="confirm a name-only duplicate, as the dry-run report prints it",
    )
    args = parser.parse_args()

    if (args.apply or args.rollback) and not args.run_id:
        parser.error("--run-id is required for --apply and --rollback")
    return asyncio.run(_main(args))


if __name__ == "__main__":  # pragma: no cover - the command's entry point
    raise SystemExit(main())
