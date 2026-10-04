"""Turn legacy deal buyers into company records — **owner: Developer 2**
(allocation task 2.6, plan P4-6 and §17.2).

    LOG_LEVEL=WARNING DEBUG=false python -m app.modules.onboarding.migrate_deal_buyers --dry-run
    ... --apply --run-id 2026-10-03a [--confirm-name <deal_buyer_id>=<company_id> ...]
    ... --validate
    ... --rollback --run-id 2026-10-03a

Run it with ``LOG_LEVEL=WARNING DEBUG=false``: with the development settings the
engine echoes every statement and the report is lost in it (``command_console``).

``--rollback`` **writes nothing**: it reports what a run did and what undoing it
takes. §17.2's logical rollback turns out not to be available in the shipped schema —
both ``deal.buyer_company_id`` and ``verification_result.subject_company_id`` are
set-once and frozen by triggers, so neither can be set back to ``NULL``. Restoring the
``pg_dump`` is the only route back, which is why taking one is step zero and not a
precaution. See ``rollback`` for how this was found.

A command and not an Alembic revision, because §17.2 puts a **person** between
reading and writing: name-only duplicates are reported and confirmed by hand
(decision IQ-8), and a revision has nowhere to pause for that.

**Never run on a live database before its dry-run report has been read.** It is
tested against seeded databases covering §17.2's edge cases. The intended sequence
is: ``pg_dump``, ``--dry-run``, read the report, confirm what needs a person,
``--apply``, ``--validate``, and a second ``--apply`` that must create nothing.

How a buyer's identity is resolved (§17.2, in order of confidence)
------------------------------------------------------------------
#. **The row is already linked to a company**: its deal names a buyer company
   (task 2.4), or its BUYER results already have a ``subject_company_id`` (P4-5).
   Both are set once and frozen, so that company is the answer and the row can map
   nowhere else (``ALREADY_LINKED``). Its identifiers are still checked against the
   company; if any contradicts it — or the links contradict each other — the row
   needs a person and nothing is written for it.
#. **A PAN.** An Indian buyer whose ``tax_id`` is a PAN, or a GSTIN carrying one,
   joins the company holding that PAN. This is R1's case and it may well join an
   existing **seller** — which is the whole point of unifying the two. A PAN that
   only GSTINs carry, on **several** companies, is a ``CONFLICT`` for a person.
#. **A registration number.** A foreign buyer joins the company with the same
   ``(country, normalised registration number)``, or shares one with another deal
   buyer carrying the same pair. Rows sharing either identifier are one company.
   A number with fewer than ``MIN_REGISTRATION_KEY_LENGTH`` letters or digits (the
   ``X`` found on a scratch copy) is not an identity: it is reported, not used.
#. **Nothing shared** — a new ``NOT_IN_PIPELINE`` company, **one per row**.
#. **A matching name and no identifier** is never a merge (decision IQ-8). If a
   company of that name already exists, the row needs a person, who confirms one
   candidate with ``--confirm-name`` (mapped ``NAME_CONFIRMED``). Identifier-less
   buyers that share a name with *each other* are **kept separate**: each becomes
   its own company, and the report lists them for review.

Refusals, all reported rather than worked around:

* a buyer resolving to **its own deal's seller** — a company does not sell to
  itself, and the row needs correcting by hand;
* a buyer whose identifiers **conflict** (a PAN naming one company, a registration
  number another; one identifier naming several; either naming a company other
  than the one the row is already linked to; or rows linked to different companies
  sharing one identifier) — picking one silently is the one outcome worth refusing.

A person resolves a refusal with ``--confirm-name``, naming one of the candidates the
report prints. Every confirmation is checked **before anything is written**
(``check_confirmations``), so a bad one stops the run instead of half of it.

What ``--apply`` writes, per §17.2
----------------------------------
``deal_buyer_company_map`` (one row per deal buyer, append-only, carrying the rule
and the run), the created companies (through ``CompanyDirectory.create_buyer_company``,
so they get ``DEAL_BUYER``, ``NOT_IN_PIPELINE``, ``created_via_deal_id`` = the earliest
of their deals, the buyer's email and phone as a contact record, and one history row,
``company_created_from_deal_buyer``, with ``{run_id, deal_buyer_ids, deal_ids,
match_rule}``), ``deal.buyer_company_id``, and ``verification_result.subject_company_id``
for the deal's BUYER results.

It does **not** touch ``deal_buyer`` rows, ``entity_type``, ``entity_reference``,
``subject_snapshot`` or any existing history row. Existing history stays on the
seller's timeline and reaches the buyer company by the read-side union task 2.7
added. The ``handover_snapshot`` of a handed-over deal was taken from the
``deal_buyer`` row before this ever runs (P2-7), so what the lending team was given
cannot change.

Everything this command prints is ASCII, so a cp1252 console can show it (R-11).
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

# The onboarding package's API and application layers import each other, so whichever
# is imported *first* decides whether that resolves. Importing the API package here
# settles it before anything else does — needed only because this module is a command
# and so is the first thing Python loads. Every other caller arrives through the app.
import app.modules.onboarding.api  # noqa: F401  (import order, not an unused import)
from app.modules.onboarding.application.company_directory import (
    CompanyDirectoryService,
    buyer_contact,
)
from app.modules.onboarding.command_console import prepare_console
from app.modules.onboarding.domain.company_directory import BuyerCompanyDraft
from app.modules.onboarding.domain.company_identity import registration_key
from app.modules.onboarding.domain.company_names import name_key
from app.modules.onboarding.domain.entities.deal import Deal
from app.modules.onboarding.domain.entities.deal_buyer import DealBuyer
from app.modules.onboarding.domain.entities.deal_buyer_company_map import (
    BuyerMatchRule,
    DealBuyerCompanyMap,
)
from app.modules.onboarding.domain.entities.exporter_contact import ExporterContact
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

#: The event of the one history row a created company starts with (§17.2, "Creation").
CREATION_EVENT = "company_created_from_deal_buyer"

#: How many rows the report prints in full before summarising. The first run of this
#: printed 568 — see `Report.render`.
DEFAULT_ROWS_SHOWN = 20

#: How many candidate companies a single row prints. More than a handful means the
#: name is not distinguishing anything, and the right next step is a query, not a
#: longer report line.
MAX_CANDIDATES_SHOWN = 5

#: A merge at or above this many deal buyers is called out for a human to look at.
LARGE_MERGE = 25

#: The fewest letters and digits a registration number needs to identify a company
#: here (R-10). No format is documented for foreign registration numbers — they are
#: stored "as the registrar writes it" and compared alphanumerics-only
#: (``company-record.md``, ``registration_key``) — so this is not a format rule. It is
#: the narrowest one that stops a placeholder like ``X`` (11 rows on a scratch copy,
#: all grouped into one company) acting as an identity. Such a number is not matched,
#: not grouped and not stored on a created company, whose unique
#: ``(country, registration number)`` index it would otherwise claim; the legacy row
#: keeps it, and the report lists it for review.
MIN_REGISTRATION_KEY_LENGTH = 2


@dataclass(eq=False)
class _Group:
    """Deal buyers that share an identifier, and so are one company (§17.2 steps 2-3).

    ``claims`` are the existing companies something has said the group is: a company
    holding one of its identifiers, or a deal that already names its buyer company.
    None means the group becomes one new company, created once; one is the company;
    **more than one is contested** — deals, or a deal and an identifier, disagree about
    who this buyer is — and every member then needs a person (R-07, R-08).
    """

    key: str
    claims: set[uuid.UUID] = field(default_factory=set)
    members: list[_Resolution] = field(default_factory=list)

    @property
    def company_id(self) -> uuid.UUID | None:
        return next(iter(self.claims)) if len(self.claims) == 1 else None

    @property
    def contested(self) -> bool:
        return len(self.claims) > 1


@dataclass(eq=False)
class _Resolution:
    """What one ``deal_buyer`` row resolved to, and why."""

    deal_buyer_id: uuid.UUID
    deal_id: uuid.UUID
    seller_company_id: uuid.UUID
    name: str
    country: str
    deal_created_at: datetime | None = None
    #: The buyer company the deal already names (task 2.4). When set, it is the answer.
    deal_company_id: uuid.UUID | None = None
    #: The companies the row's BUYER results already name as their subject (P4-5).
    #: Set once and frozen, so they bind the row exactly as the deal's company does.
    result_subjects: set[uuid.UUID] = field(default_factory=set)
    rule: BuyerMatchRule | None = None
    #: The existing company it joins, when one was found.
    company_id: uuid.UUID | None = None
    #: The identity keys it carries (``PAN:...``, ``REG:<country>:...``).
    keys: list[str] = field(default_factory=list)
    #: The deal buyers it shares an identity with — the logical merge.
    group: _Group | None = None
    #: Why it cannot proceed without a person. Empty means it can.
    problems: list[str] = field(default_factory=list)
    #: Things worth a look that do not stop the row.
    notes: list[str] = field(default_factory=list)
    #: Companies a name-only match found.
    name_candidates: list[uuid.UUID] = field(default_factory=list)
    #: The companies a person may choose between with ``--confirm-name``. Never the
    #: deal's seller; only the deal's own buyer company when the deal names one.
    candidates: list[uuid.UUID] = field(default_factory=list)
    pan: str | None = None
    registration_number: str | None = None
    #: A registration number too short to identify anything, kept for the report.
    implausible_registration: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None

    @property
    def group_key(self) -> str | None:
        return self.group.key if self.group is not None else None

    @property
    def links(self) -> set[uuid.UUID]:
        """Every company this row is already, irreversibly, tied to: the deal's buyer
        company and its BUYER results' subjects. The row can map only to one of these."""
        deal = {self.deal_company_id} if self.deal_company_id is not None else set()
        return deal | self.result_subjects

    @property
    def target(self) -> uuid.UUID | None:
        """The existing company this row maps to, or ``None`` when its company is
        still to be created."""
        if self.company_id is not None:
            return self.company_id
        return self.group.company_id if self.group is not None else None


class ConfirmationError(Exception):
    """One or more ``--confirm-name`` lines cannot be applied. Raised before anything
    is written; ``errors`` names each."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


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

    @property
    def look_alikes(self) -> dict[tuple[str, str], list[_Resolution]]:
        """Identifier-less buyers sharing ``(country, normalised name)``: **kept
        separate** (IQ-8), each its own company, and listed for review."""
        grouped: dict[tuple[str, str], list[_Resolution]] = defaultdict(list)
        for r in self.ready:
            key = name_key(r.name)
            if r.rule is BuyerMatchRule.NEW and key:
                grouped[(r.country, key)].append(r)
        return {k: v for k, v in grouped.items() if len(v) > 1}

    @property
    def to_review(self) -> list[_Resolution]:
        """Ready rows carrying a note: they migrate, and a person should look."""
        return [r for r in self.ready if r.notes]

    def render(self, *, show: int = DEFAULT_ROWS_SHOWN) -> str:
        """The operator's report. ASCII only (R-11).

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
            "Buyer migration (P4-6) - report",
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
        new_companies = len(
            {r.group_key or str(r.deal_buyer_id) for r in self.ready if r.target is None}
        )
        lines.append(f"  companies --apply would create: {new_companies}")

        merges = self.groups
        if merges:
            companies = len(merges)
            rows = sum(len(v) for v in merges.values())
            lines += [
                "",
                f"Logical merges on a shared PAN or registration number: {rows} deal "
                f"buyers resolve to {companies} companies.",
            ]
            large = {k: v for k, v in merges.items() if len(v) >= LARGE_MERGE}
            if large:
                lines.append(
                    f"  {len(large)} of them merge {LARGE_MERGE}+ rows - worth a look "
                    "before --apply, since a regular counterparty and a too-loose "
                    "identity rule look the same from here:"
                )
                for key, group in sorted(large.items(), key=lambda kv: -len(kv[1])):
                    names = sorted({r.name for r in group})
                    shown = ", ".join(names[:3]) + (
                        f" (+{len(names) - 3} more names)" if len(names) > 3 else ""
                    )
                    lines.append(f"    {key}: {len(group)} rows - {shown}")
            for key, group in sorted(merges.items())[:show]:
                if key in large:
                    continue
                names = ", ".join(sorted({r.name for r in group}))
                lines.append(f"  {key}: {len(group)} rows - {names}")
            if len(merges) > show:
                lines.append(f"  ... and {len(merges) - show} more merges")

        look_alikes = self.look_alikes
        if look_alikes:
            rows = sum(len(v) for v in look_alikes.values())
            lines += [
                "",
                f"Kept separate - review (IQ-8): {rows} buyer(s) with no identifier share "
                f"a name in {len(look_alikes)} group(s).",
                "  A name is never a merge: each row becomes its own company. To merge a "
                "group instead,",
                "  a person decides which company it is first; once that company exists, "
                "the next",
                "  --dry-run lists it as a candidate and prints the --confirm-name lines.",
            ]
            ordered = sorted(look_alikes.items(), key=lambda kv: (-len(kv[1]), kv[0]))
            for (country, _key), group in ordered[:show]:
                lines.append(
                    f"  {country} {group[0].name!r}: {len(group)} rows -> {len(group)} "
                    "companies (kept separate - review)"
                )
                for r in group[:MAX_CANDIDATES_SHOWN]:
                    lines.append(f"    deal buyer {r.deal_buyer_id} (deal {r.deal_id})")
                if len(group) > MAX_CANDIDATES_SHOWN:
                    lines.append(
                        f"    ... and {len(group) - MAX_CANDIDATES_SHOWN} more; --show-all "
                        "does not list them, query deal_buyer by name and country"
                    )
            if len(look_alikes) > show:
                lines.append(f"  ... and {len(look_alikes) - show} more groups")

        review = self.to_review
        if review:
            lines += ["", f"Migrates, but review: {len(review)} row(s)."]
            for r in review[:show]:
                lines.append(f"  deal {r.deal_id} / buyer {r.deal_buyer_id}")
                lines += [f"    {note}" for note in r.notes]
            if len(review) > show:
                lines.append(f"  ... and {len(review) - show} more; --show-all lists every one")

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
                    by_problem[_category(problem)] += 1
            for problem, count in sorted(by_problem.items(), key=lambda kv: -kv[1]):
                lines.append(f"    {count:>6}  {problem}")

            lines.append("")
            for r in blocked[:show]:
                lines.append(f"  deal {r.deal_id} / buyer {r.deal_buyer_id}")
                for problem in r.problems or ["no rule matched"]:
                    lines.append(f"    {problem}")
                # One line per candidate, never a comma-joined list: confirming means
                # choosing *one* company, and a line that listed seventy would read as
                # confirming all of them.
                for candidate in r.candidates[:MAX_CANDIDATES_SHOWN]:
                    lines.append(f"    --confirm-name {r.deal_buyer_id}={candidate}")
                extra = len(r.candidates) - MAX_CANDIDATES_SHOWN
                if extra > 0:
                    lines.append(
                        f"    ... and {extra} more candidate(s); query "
                        "exporter_profile by name and country to see them all"
                    )
                if not r.candidates:
                    lines.append("    (no company can be confirmed: correct the row by hand)")
            if len(blocked) > show:
                lines.append(f"  ... and {len(blocked) - show} more; --show-all lists every one")
        lines.append("")
        return "\n".join(lines)


# ── Resolution ────────────────────────────────────────────────────────────────


def _buyer_pan(buyer: DealBuyer) -> str | None:
    """The PAN a buyer's ``tax_id`` carries, if any (§17.2 step 2).

    ``tax_id`` is free text on a legacy row, so it may hold a PAN, a GSTIN, or
    something else entirely. A GSTIN carries its company's PAN in characters 3-12,
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


def _category(problem: str) -> str:
    """What kind of problem a report line is, without the ids and counts in it, so
    the summary counts kinds rather than listing every row again."""
    prefix = "CONFLICT: " if problem.startswith("CONFLICT: ") else ""
    rest = problem[len(prefix):]
    for stop in (" (", ":"):
        rest = rest.split(stop, 1)[0]
    return prefix + rest.strip()


def _contested_problem(group: _Group) -> str:
    return (
        f"CONFLICT: buyers already linked to different companies share one identity "
        f"({group.key} -> {_ids(group.claims)}): a person decides each row"
    )


def _ids(companies: set[uuid.UUID] | list[uuid.UUID]) -> str:
    return ", ".join(sorted(str(c) for c in companies))


async def _pan_holders(db: AsyncSession, pan: str) -> set[uuid.UUID]:
    """Every company holding this PAN — on its record, or else on an active GSTIN.

    **All of them**, never the first: a PAN that only GSTINs carry can sit on several
    companies (shared GSTINs are legal, IQ-9), and choosing one would decide a buyer's
    identity by row order (R-08).
    """
    holders = set(
        await db.scalars(select(ExporterProfile.customer_id).where(ExporterProfile.pan == pan))
    )
    if holders:
        return holders
    # A company created from a GSTIN-only delivery holds the GSTIN but no PAN.
    return set(
        await db.scalars(
            select(ExporterGstin.customer_id)
            .where(
                ExporterGstin.gstin.like(f"__{pan}%"),
                ExporterGstin.active.is_(True),
            )
            .distinct()
        )
    )


async def _registration_holders(
    db: AsyncSession, country: str, key: str
) -> set[uuid.UUID]:
    """Every company in ``country`` whose registration number compares equal."""
    return set(
        await db.scalars(
            select(ExporterProfile.customer_id).where(
                ExporterProfile.country == country,
                ExporterProfile.registration_number.isnot(None),
                text(
                    "upper(regexp_replace(exporter_profile.registration_number, "
                    "'[^A-Za-z0-9]', '', 'g')) = :key"
                ).bindparams(key=key),
            )
        )
    )


async def resolve(db: AsyncSession) -> Report:
    """Work out what every unmapped ``deal_buyer`` row is, without writing anything.

    Already-mapped rows are skipped, which is what makes a re-run a no-op.

    Rows already linked to a company — their deal names one, or their BUYER results
    already name a subject — are resolved **first** (R-07), so an identity they carry
    points at that company before any other row claims it; the report keeps the
    original order.
    """
    mapped = set(await db.scalars(select(DealBuyerCompanyMap.deal_buyer_id)))
    subjects: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for buyer_id, subject_id in await db.execute(
        select(VerificationResult.entity_reference, VerificationResult.subject_company_id).where(
            VerificationResult.entity_type == VerificationEntityType.BUYER,
            VerificationResult.subject_company_id.isnot(None),
        )
    ):
        subjects[buyer_id].add(subject_id)

    rows = await db.execute(
        select(DealBuyer, Deal.company_id, Deal.id, Deal.buyer_company_id, Deal.created_at)
        .join(Deal, Deal.id == DealBuyer.deal_id)
        .order_by(DealBuyer.created_at, DealBuyer.id)
    )

    report = Report()
    for buyer, seller_company_id, deal_id, deal_company_id, deal_created_at in rows:
        if buyer.id in mapped:
            continue
        report.resolutions.append(
            _Resolution(
                deal_buyer_id=buyer.id,
                deal_id=deal_id,
                seller_company_id=seller_company_id,
                name=buyer.name,
                country=(buyer.country or "").strip().upper(),
                deal_created_at=deal_created_at,
                deal_company_id=deal_company_id,
                result_subjects=set(subjects.get(buyer.id, ())),
                pan=_buyer_pan(buyer),
                registration_number=(buyer.registration_number or "").strip() or None,
                contact_email=buyer.contact_email,
                contact_phone=buyer.contact_phone,
            )
        )

    #: Identity key -> the group that holds it, so later rows join it.
    claimed: dict[str, _Group] = {}
    await _seed_from_earlier_runs(db, claimed)
    for r in sorted(report.resolutions, key=lambda r: not r.links):
        await _resolve_one(db, r, claimed)

    # Rows already linked to a company may disagree about who one identifier is. Then
    # nobody sharing it is mapped by rule: picking one link for the rest would decide
    # an identity by row order (R-07, R-08).
    for group in {id(g): g for g in claimed.values()}.values():
        if not group.contested:
            continue
        for r in group.members:
            if r.problems:
                continue
            r.problems.append(_contested_problem(group))
            r.candidates = (
                sorted(r.links, key=str)
                if r.links
                else sorted(group.claims - {r.seller_company_id}, key=str)
            )

    # A group may learn its company from a later member, so the seller check runs once
    # every row has been placed (§17.2 step 5).
    for r in report.ready:
        if r.target is not None and r.target == r.seller_company_id:
            r.problems.append(
                f"resolves to the deal's own seller ({r.target}): a company does not "
                "sell to itself, so this row needs correcting by hand"
            )
    return report


async def _resolve_one(
    db: AsyncSession, r: _Resolution, claimed: dict[str, _Group]
) -> None:
    #: identifier label -> the companies it names.
    found: dict[str, set[uuid.UUID]] = {}

    # Step 2: a PAN, directly or through a GSTIN.
    if r.pan:
        holders = await _pan_holders(db, r.pan)
        if holders:
            found["PAN"] = holders
        r.rule = BuyerMatchRule.PAN

    # Step 3: a foreign registration number, when it can identify anything.
    if r.registration_number and r.country:
        key = registration_key(r.registration_number)
        if len(key) < MIN_REGISTRATION_KEY_LENGTH:
            r.implausible_registration = r.registration_number
            r.notes.append(
                f"registration number {r.registration_number!r} has fewer than "
                f"{MIN_REGISTRATION_KEY_LENGTH} letters or digits: not used to match or "
                "group, and not stored on a created company (kept separate - review)"
            )
            r.registration_number = None
        else:
            holders = await _registration_holders(db, r.country, key)
            if holders:
                found["registration number"] = holders
            if r.rule is None:
                r.rule = BuyerMatchRule.REGISTRATION_NUMBER
    r.keys = _identity_keys(r.country, r.pan, r.registration_number)

    named: set[uuid.UUID] = set().union(*found.values()) if found else set()
    groups = list({id(g): g for g in (claimed.get(k) for k in r.keys) if g}.values())

    if r.links:
        await _against_the_link(db, r, found, named, groups, claimed)
        return

    # One identifier naming several companies (R-08), or identifiers disagreeing.
    ambiguous = {label: holders for label, holders in found.items() if len(holders) > 1}
    for label, holders in sorted(ambiguous.items()):
        r.problems.append(
            f"CONFLICT: the {label} is held by several companies ({_ids(holders)}): "
            "a person chooses one with --confirm-name, or corrects the row"
        )
    group_companies: set[uuid.UUID] = set().union(*(g.claims for g in groups))
    contested = [g for g in groups if g.contested]
    if not ambiguous:
        if len(named) > 1:
            described = "; ".join(
                f"{label} -> {_ids(holders)}" for label, holders in sorted(found.items())
            )
            r.problems.append(f"CONFLICT: identifiers name different companies ({described})")
        elif contested:
            r.problems.append(_contested_problem(contested[0]))
        elif len(named | group_companies) > 1:
            r.problems.append(
                f"CONFLICT: its identifiers name another company than buyers sharing them "
                f"({_ids(named)} vs {_ids(group_companies)}): a person decides"
            )
    if not r.problems and len(groups) > 1:
        r.problems.append(
            "CONFLICT: shares one identifier with one group of buyers and another with a "
            "different group, so it would merge them; a person decides"
        )
    if r.problems:
        r.candidates = sorted(
            (named | group_companies) - {r.seller_company_id}, key=str
        )
        return

    company = next(iter(named | group_companies), None)
    r.company_id = company
    if r.keys:
        _join(r, groups[0] if groups else None, company, claimed)
        return

    # Step 4: no identifier at all — a name match is a *possible* duplicate only.
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
            f"name-only match: {len(r.name_candidates)} company(ies) in {r.country} share "
            "this name and it carries no identifier: confirm or reject by hand (IQ-8)"
        )
        r.candidates = [c for c in r.name_candidates if c != r.seller_company_id]
        return
    # No group: a name is never an identity (IQ-8), so a buyer that shares one with
    # another identifier-less buyer is still its own company. `Report.look_alikes`
    # lists them for review.
    r.rule = BuyerMatchRule.NEW


def _identity_keys(country: str, pan: str | None, registration_number: str | None) -> list[str]:
    """The identity keys a buyer carries: its PAN, and its registration number when
    that can identify anything (``MIN_REGISTRATION_KEY_LENGTH``)."""
    keys = [f"PAN:{pan}"] if pan else []
    if registration_number and country:
        key = registration_key(registration_number)
        if len(key) >= MIN_REGISTRATION_KEY_LENGTH:
            keys.append(f"REG:{country}:{key}")
    return keys


async def _seed_from_earlier_runs(db: AsyncSession, claimed: dict[str, _Group]) -> None:
    """What earlier runs decided is part of every identity.

    A mapped row is never resolved again, but its identifiers and the company it was
    mapped to still say who that identity is. Without them, a contested identity would
    stop looking contested the moment a person confirmed the rows that made it so, and
    the rows left over would be mapped by rule to whatever was left: a later run must
    reach the decision one run would have.
    """
    rows = await db.execute(
        select(DealBuyer, DealBuyerCompanyMap.company_id).join(
            DealBuyerCompanyMap, DealBuyerCompanyMap.deal_buyer_id == DealBuyer.id
        )
    )
    for buyer, company_id in rows:
        country = (buyer.country or "").strip().upper()
        keys = _identity_keys(country, _buyer_pan(buyer), buyer.registration_number)
        groups = list({id(g): g for g in (claimed.get(k) for k in keys) if g}.values())
        if not groups and keys:
            groups = [_Group(key=keys[0])]
        for group in groups:
            group.claims.add(company_id)
        for key in keys:
            claimed.setdefault(key, groups[0])


def _join(
    r: _Resolution,
    group: _Group | None,
    company: uuid.UUID | None,
    claimed: dict[str, _Group],
) -> None:
    """Put ``r`` in ``group`` (or a new one keyed on its first identifier) and claim
    every identifier it carries for that group."""
    if group is None:
        group = _Group(key=r.keys[0])
    if company is not None:
        group.claims.add(company)
    for key in r.keys:
        claimed.setdefault(key, group)
    group.members.append(r)
    r.group = group


async def _against_the_link(
    db: AsyncSession,
    r: _Resolution,
    found: dict[str, set[uuid.UUID]],
    named: set[uuid.UUID],
    groups: list[_Group],
    claimed: dict[str, _Group],
) -> None:
    """R-07: the row is already linked to a company — the deal names it (task 2.4),
    or the row's BUYER results already have it as their subject (P4-5). Both links
    are set once, so that is the only company this row can map to. It does unless
    something on the legacy row contradicts it, in which case a person looks and
    nothing is written for it."""
    links = r.links
    if len(links) > 1:
        # The deal and its results, or two results, already disagree. Both are
        # frozen, so no mapping can make them agree; only a correction by hand can.
        r.problems.append(
            f"CONFLICT: the deal and its BUYER results are already linked to different "
            f"companies ({_ids(links)}): set once, so this needs correcting by hand"
        )
        return
    [company_id] = links
    by_deal = r.deal_company_id is not None
    source = (
        "the deal already names its buyer company"
        if by_deal
        else "its BUYER results already name their subject company"
    )
    disagreements: list[str] = []

    for label, holders in sorted(found.items()):
        if company_id not in holders:
            disagreements.append(f"its {label} names {_ids(holders)}")

    company = (
        await db.execute(
            select(
                ExporterProfile.pan,
                ExporterProfile.country,
                ExporterProfile.registration_number,
            ).where(ExporterProfile.customer_id == company_id)
        )
    ).one_or_none()
    if company is not None:
        if r.pan and company.pan and company.pan != r.pan:
            disagreements.append("that company holds a different PAN")
        if (
            r.registration_number
            and company.registration_number
            and company.country == r.country
            and registration_key(company.registration_number)
            != registration_key(r.registration_number)
        ):
            disagreements.append("that company holds a different registration number")

    if disagreements:
        r.problems.append(
            f"CONFLICT: {source} ({company_id}), but "
            + "; ".join(disagreements)
            + ". That link is set once, so it is the only company that can be confirmed"
        )
        r.candidates = [company_id]
        return

    r.company_id = company_id
    if company_id not in named:
        r.rule = BuyerMatchRule.ALREADY_LINKED
    if not by_deal:
        r.notes.append(
            f"linked by its BUYER results' existing subject ({company_id}), which the "
            "deal does not name yet: --apply makes the deal name it too (review)"
        )
    if r.keys:
        _join(r, groups[0] if groups else None, company_id, claimed)
        # Every group its identifiers touch hears this link, so a row linked to another
        # company for any of them makes that identity contested.
        for group in groups[1:]:
            group.claims.add(company_id)


# ── Confirmations (R-09) ──────────────────────────────────────────────────────


async def check_confirmations(
    db: AsyncSession, report: Report, confirmed: dict[uuid.UUID, uuid.UUID]
) -> list[str]:
    """Why each ``--confirm-name`` cannot be applied; empty when all can.

    Run before **anything** is written. A confirmation is a person's decision about one
    row the report sent them, so it must name a row that needs one, a company that
    exists and was offered for that row, never the row's own seller, and the deal's
    buyer company when the deal already names one.
    """
    by_id = {r.deal_buyer_id: r for r in report.resolutions}
    errors: list[str] = []
    for buyer_id, company_id in confirmed.items():
        line = f"--confirm-name {buyer_id}={company_id}"
        r = by_id.get(buyer_id)
        if r is None:
            if await db.scalar(select(DealBuyer.id).where(DealBuyer.id == buyer_id)) is None:
                errors.append(f"{line}: no deal buyer has that id")
                continue
            mapping = await db.scalar(
                select(DealBuyerCompanyMap).where(DealBuyerCompanyMap.deal_buyer_id == buyer_id)
            )
            if mapping is not None:
                errors.append(
                    f"{line}: that deal buyer is already mapped (run {mapping.run_id}), "
                    "and a mapping never changes"
                )
            else:
                errors.append(f"{line}: that deal buyer is not in this run's report")
            continue
        exists = await db.scalar(
            select(ExporterProfile.customer_id).where(ExporterProfile.customer_id == company_id)
        )
        if exists is None:
            errors.append(f"{line}: no company has that id")
            continue
        if company_id == r.seller_company_id:
            errors.append(
                f"{line}: that company is deal {r.deal_id}'s own seller, and a company "
                "does not sell to itself"
            )
            continue
        if r.links and company_id not in r.links:
            errors.append(
                f"{line}: deal {r.deal_id}'s buyer is already linked to "
                f"{_ids(r.links)} (the deal or its BUYER results), which is set once; "
                "only that company can be confirmed"
            )
            continue
        if not (r.problems or r.rule is None):
            errors.append(
                f"{line}: that row does not need a person (it maps by "
                f"{r.rule.value if r.rule else '?'}); only rows under 'Needs a person' "
                "take a confirmation"
            )
            continue
        if company_id not in r.candidates:
            offered = _ids(r.candidates) or "none"
            errors.append(
                f"{line}: that company is not one the report offered for this row "
                f"(candidates: {offered})"
            )
    return errors


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

    ``confirmed`` carries a person's decisions: ``{deal_buyer_id: company_id}``, each
    naming one of the candidates the report offered. Those rows are mapped with
    ``NAME_CONFIRMED``, so the record says a human decided rather than a rule. They
    are all checked first (``check_confirmations``); one bad line raises
    ``ConfirmationError`` before anything is written.

    Rows that still need a person are **skipped**, not guessed. The run is safe to
    repeat: every write is keyed on a mapping that does not yet exist, and a company is
    created idempotently on its deal.

    Each deal's buyer company is read again, locked, just before its row is written.
    A deal that has named a different company since the report was built is skipped
    (``skipped_deal_changed``) rather than mapped against it (R-07).
    """
    confirmed = confirmed or {}
    errors = await check_confirmations(db, report, confirmed)
    if errors:
        raise ConfirmationError(errors)

    counts = {
        "companies_created": 0,
        "contacts_created": 0,
        "mapped": 0,
        "deals_linked": 0,
        "results_linked": 0,
        "skipped_deal_changed": 0,
    }
    directory = CompanyDirectoryService(db)
    ready = set(id(r) for r in report.ready)
    #: group key -> the company created for it, at most once.
    created_for_group: dict[str, uuid.UUID] = {}

    for r in report.resolutions:
        company_id = confirmed.get(r.deal_buyer_id)
        if company_id is not None:
            rule = BuyerMatchRule.NAME_CONFIRMED
        else:
            if id(r) not in ready:
                continue
            assert r.rule is not None
            rule = r.rule
            company_id = r.target
            if company_id is None and r.group_key:
                company_id = created_for_group.get(r.group_key)

        if not await _deal_still_agrees(db, r.deal_id, company_id):
            counts["skipped_deal_changed"] += 1
            continue

        if company_id is None:
            members = (
                [m for m in r.group.members if id(m) in ready and m.deal_buyer_id not in confirmed]
                if r.group is not None
                else [r]
            )
            company_id = await _create_company(
                directory, r, members, rule=rule, run_id=run_id, actor_id=actor_id
            )
            counts["companies_created"] += 1
            counts["contacts_created"] += await _add_member_contacts(
                db, company_id, r, members
            )
            if r.group_key:
                created_for_group[r.group_key] = company_id
            # Creating committed; the deal is read under a lock again before the link.
            if not await _deal_still_agrees(db, r.deal_id, company_id):
                counts["skipped_deal_changed"] += 1
                continue

        db.add(
            DealBuyerCompanyMap(
                deal_buyer_id=r.deal_buyer_id,
                company_id=company_id,
                match_rule=rule,
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

        # The deal's BUYER results become the buyer company's — the company the deal
        # names, which `_deal_still_agrees` has just confirmed. `entity_type`,
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


async def _deal_still_agrees(
    db: AsyncSession, deal_id: uuid.UUID, company_id: uuid.UUID | None
) -> bool:
    """Whether the deal, read now and locked, names no buyer company or this one.

    ``company_id`` is ``None`` for a row whose company is still to be created: then
    the deal must still name none."""
    current = await db.scalar(
        select(Deal.buyer_company_id).where(Deal.id == deal_id).with_for_update()
    )
    return current is None or current == company_id


async def _create_company(
    directory: CompanyDirectoryService,
    r: _Resolution,
    members: list[_Resolution],
    *,
    rule: BuyerMatchRule,
    run_id: str,
    actor_id: str | None,
) -> uuid.UUID:
    """Create the company ``r``'s group becomes, with §17.2's creation history row.

    ``created_via_deal_id`` is the earliest of the members' deals (§17.2), and the row
    names every member this run maps to it.
    """
    # `deal.created_at` is NOT NULL and read from one database, so every value carries
    # the same zone and its ISO text sorts in time order.
    earliest = min(members, key=lambda m: (str(m.deal_created_at), str(m.deal_id)))
    return await directory.create_buyer_company(
        BuyerCompanyDraft(
            name=r.name,
            country=r.country,
            pan=r.pan,
            registration_number=r.registration_number,
            contact_email=r.contact_email,
            contact_phone=r.contact_phone,
            created_via_deal_id=earliest.deal_id,
            source_ref=run_id,
        ),
        actor_id=actor_id,
        history_event_type=CREATION_EVENT,
        history_details={
            "run_id": run_id,
            "deal_buyer_ids": [str(m.deal_buyer_id) for m in members],
            "deal_ids": sorted({str(m.deal_id) for m in members}),
            "match_rule": rule.value,
        },
    )


def _contact_key(email: str | None, phone: str | None) -> tuple[str, str]:
    return ((email or "").strip().lower(), "".join((phone or "").split()))


async def _add_member_contacts(
    db: AsyncSession, company_id: uuid.UUID, creator: _Resolution, members: list[_Resolution]
) -> int:
    """The members' email and phone as contacts on the company just created, once per
    distinct pair. ``create_buyer_company`` already wrote the creating row's; the rest
    are added here, never twice — a repeated run finds them on the company.

    Returns how many buyer contacts the company has from this run's rows."""
    existing = {
        _contact_key(email, phone)
        for email, phone in await db.execute(
            select(ExporterContact.email, ExporterContact.phone).where(
                ExporterContact.customer_id == company_id
            )
        )
    }
    wanted = {_contact_key(creator.contact_email, creator.contact_phone)}
    for m in members:
        key = _contact_key(m.contact_email, m.contact_phone)
        if not any(key) or key in wanted:
            continue
        wanted.add(key)
        if key not in existing:
            db.add(
                buyer_contact(
                    company_id, name=creator.name, email=m.contact_email, phone=m.contact_phone
                )
            )
    return len({key for key in wanted if any(key)})


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
        # Only companies a run created: mapped by a run, on the deal the company was
        # created from, by a rule that creates. A company the row was already linked
        # to (ALREADY_LINKED) is not counted at all, and one brought into the pipeline
        # since is counted for its creation row alone, not its other pipeline rows.
        "companies a run created without exactly one creation history row",
        f"""
        SELECT count(*) FROM onboarding.exporter_profile p
        WHERE p.created_via = 'DEAL_BUYER'
          AND EXISTS (
            SELECT 1 FROM onboarding.deal_buyer_company_map m
            JOIN onboarding.deal_buyer b ON b.id = m.deal_buyer_id
            WHERE m.company_id = p.customer_id
              AND b.deal_id = p.created_via_deal_id
              AND m.match_rule <> 'ALREADY_LINKED'
          )
          AND (
            SELECT count(*) FROM onboarding.exporter_lifecycle_history h
            WHERE h.customer_id = p.customer_id AND h.event_type = '{CREATION_EVENT}'
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
    (
        # R-07: the map and the deal must agree on who the buyer is.
        "mapped deal buyers whose company is not the deal's buyer company",
        """
        SELECT count(*) FROM onboarding.deal_buyer_company_map m
        JOIN onboarding.deal_buyer b ON b.id = m.deal_buyer_id
        JOIN onboarding.deal d ON d.id = b.deal_id
        WHERE d.buyer_company_id IS NOT NULL AND d.buyer_company_id <> m.company_id
        """,
    ),
    (
        # R-07: a BUYER result belongs to the company the deal names, never another.
        "BUYER results whose subject is not the deal's buyer company",
        """
        SELECT count(*) FROM onboarding.verification_result r
        JOIN onboarding.deal_buyer b ON b.id = r.entity_reference
        JOIN onboarding.deal d ON d.id = b.deal_id
        WHERE r.entity_type = 'BUYER'
          AND r.subject_company_id IS NOT NULL
          AND d.buyer_company_id IS NOT NULL
          AND r.subject_company_id <> d.buyer_company_id
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
    caveat that it *"needs the freeze trigger to allow NULL->value only, so do the
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

    The dry-run report prints these lines ready to paste, so confirming is a
    deliberate act naming both sides rather than a yes/no prompt nobody can audit
    afterwards. Only the syntax is checked here; ``check_confirmations`` checks each
    against the report before anything is written.
    """
    confirmed: dict[uuid.UUID, uuid.UUID] = {}
    for value in values or []:
        left, _, right = value.partition("=")
        if not right:
            raise SystemExit(f"--confirm-name wants <deal_buyer_id>=<company_id>, got {value!r}")
        if "," in right:
            # Refused rather than taking the first: confirming means choosing **one**
            # company, and accepting a list would let a pasted report line look like a
            # decision somebody made.
            raise SystemExit(
                f"--confirm-name takes one company id, got several: {right.strip()!r}"
            )
        try:
            buyer_id, company_id = uuid.UUID(left.strip()), uuid.UUID(right.strip())
        except ValueError:
            raise SystemExit(f"--confirm-name wants two UUIDs, got {value!r}") from None
        if confirmed.get(buyer_id, company_id) != company_id:
            raise SystemExit(
                f"--confirm-name names deal buyer {buyer_id} twice, with different "
                "companies; a row maps to one"
            )
        confirmed[buyer_id] = company_id
    return confirmed


async def _main(args: argparse.Namespace) -> int:
    async with db_services.AsyncSessionLocal() as db:
        if args.validate:
            results = await validate(db)
            failures = 0
            print("\nP4-6 validation (plan section 17.2)")
            print("=" * 60)
            for label, count in results:
                status = "OK  " if count == 0 else "FAIL"
                if count:
                    failures += 1
                print(f"{status} {count:>6}  {label}")
            print()
            if failures:
                print(
                    f"VALIDATION FAILED: {failures} of {len(results)} checks are not 0. "
                    "Do not go on to P5-5 or P4-10 until every one is.\n"
                )
                return 1
            print(f"All {len(results)} checks are 0.\n")
            return 0

        if args.rollback:
            counts = await rollback(db, run_id=args.run_id)
            print(f"\nRun {args.run_id} - what it did")
            print("=" * 60)
            if not counts["mapped"]:
                print("Nothing: no mapping rows carry that run id.\n")
                return 0
            print(f"  deal buyers mapped:    {counts['mapped']}")
            print(f"  companies involved:    {counts['companies_created']}")
            print(f"  deals linked:          {counts['deals_linked']}")
            print(f"  results re-subjected:  {counts['results_linked']}")
            print(
                "\nThis command wrote nothing. The logical rollback in plan section 17.2 "
                "is NOT available:\nboth `deal.buyer_company_id` and "
                "`verification_result.subject_company_id` are set-once and\nfrozen by "
                "triggers, so neither can be set back to NULL.\n\n"
                "To undo this run, restore the pg_dump taken before it. That is the "
                "only route, which is why\ntaking one is step zero.\n"
            )
            return 0

        confirmations = _parse_confirmations(args.confirm_name)
        report = await resolve(db)
        print(report.render(show=10**9 if args.show_all else DEFAULT_ROWS_SHOWN))

        errors = await check_confirmations(db, report, confirmations)
        if errors:
            print("Refused: these confirmations cannot be applied, so nothing was written.")
            for error in errors:
                print(f"  {error}")
            print()
            return 2

        if args.dry_run:
            print("Dry run: nothing was written.")
            if report.needs_a_person:
                print(
                    f"{len(report.needs_a_person)} row(s) need a person before --apply; "
                    "the lines above name them."
                )
            if confirmations:
                print(f"{len(confirmations)} confirmation(s) checked: all can be applied.")
            return 0

        counts = await apply(
            db,
            report,
            run_id=args.run_id,
            actor_id=args.actor or f"migration:{args.run_id}",
            confirmed=confirmations,
        )
        print(f"Applied run {args.run_id}:")
        for name, count in counts.items():
            print(f"  {name:<22} {count}")
        skipped = len([r for r in report.needs_a_person if r.deal_buyer_id not in confirmations])
        if skipped:
            print(f"{skipped} row(s) were skipped and still need a person.")
        if counts["skipped_deal_changed"]:
            print(
                f"{counts['skipped_deal_changed']} row(s) were skipped because their deal "
                "named a buyer company after the report was built; run --dry-run again."
            )
        print("Now run --validate; every count must be 0.\n")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.modules.onboarding.migrate_deal_buyers",
        description=(
            "Turn legacy deal buyers into company records (P4-6). Take a pg_dump "
            "first, read the --dry-run report, confirm what needs a person, then "
            "--apply and --validate. Run with LOG_LEVEL=WARNING DEBUG=false."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="report, write nothing")
    mode.add_argument("--apply", action="store_true", help="write the migration")
    mode.add_argument("--validate", action="store_true", help="run plan section 17.2's checks")
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
        help="resolve a row that needs a person, as the dry-run report prints it",
    )
    args = parser.parse_args()

    if (args.apply or args.rollback) and not args.run_id:
        parser.error("--run-id is required for --apply and --rollback")
    prepare_console()
    return asyncio.run(_main(args))


if __name__ == "__main__":  # pragma: no cover - the command's entry point
    raise SystemExit(main())
