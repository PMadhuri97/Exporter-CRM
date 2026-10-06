"""Give every deal that has a buyer company a trade relationship.

    python -m app.modules.onboarding.backfill_trade_relationships --dry-run
    python -m app.modules.onboarding.backfill_trade_relationships --apply --run-id 2026-10-03a
    python -m app.modules.onboarding.backfill_trade_relationships --validate

Run it with ``LOG_LEVEL=WARNING DEBUG=false``: with the development settings the
engine echoes every statement and the report is lost in it. Its output is ASCII, so a
Windows console can show it (``command_console``).

**Run it only after the buyer migration (``migrate_deal_buyers``) has been applied.**
Before that, most deals have
no ``buyer_company_id`` and this would create relationships for the few that do and
report the rest as unmigrated, which is noise rather than a result. The dry run says
so out loud when it sees a large unmigrated remainder.

**Nothing here has been run against real data.** It is tested against a seeded
database. Like the buyer migration, the intended sequence is ``pg_dump``,
``--dry-run``, read the report, ``--apply``, ``--validate``.

No ``deal.relationship_id``, and why
------------------------------------
The original design said *"set ``deal.relationship_id`` (the terminal-deal trigger must allow this
one-time set, or the column is added to the trigger only after the backfill)"*. There
is **no such column**, and the backfill needs none: a relationship is keyed on the
ordered pair ``(seller_company_id, buyer_company_id)`` by
``uq_trade_relationship_pair``, and a deal already carries both sides —
``company_id`` and ``buyer_company_id``. So a deal's relationship is a lookup, not a
stored link, and ``relationship_for_pair`` is what the deal page asks.

That is worth stating plainly because it removes the whole difficulty the design
anticipated: nothing is written to ``deal``, so the terminal-deal freeze is never
involved, a handed-over deal needs no exception, and migration 0039's problem cannot
recur here. The cost is a join rather than a column, which for a page that already
loads the deal is nothing.

What it writes
--------------
``trade_relationship`` rows, through ``TradeHistoryService.get_or_create_relationship``
with ``source='backfill'`` and ``source_ref`` the run id — the same method the
deal path uses, so a backfilled relationship and one created by recording a buyer are
the same kind of row, built by the same code. Nothing else: no invoices (a deal having
had a buyer is not evidence that an invoice existed — an invoice is a fact about
money, and inventing one would put unproven numbers into trade history), no history
rows, no change to any deal.

**Idempotent.** ``get_or_create_relationship`` is insert-then-handle-the-race, so a
second run of this command writes nothing and reports every pair as already present.
There is no mapping table to consult and none is needed.

Which deals need it
-------------------
Only the ones linked **without** going through ``DealService.set_buyer_company``. That
method creates the relationship itself, in the same transaction (*every deal with a
buyer company has a relationship*), so every deal recorded
since 3.18 shipped already has one and this command reports it as already there.

What is left is exactly this command's subject: the deals the buyer migration linked, since
``migrate_deal_buyers`` writes ``deal.buyer_company_id`` with an ``UPDATE`` and creates
no relationship. Hence the ordering — the buyer migration, then this.

Which deals count
-----------------
Every deal with a ``buyer_company_id``, at any stage, including ``WITHDRAWN`` — the design's
wording, and the right reading: a relationship is *"these two companies have dealt with
each other"*, not *"these two companies completed a trade"*. What happened is carried
by the invoices and their outcomes, and a withdrawn deal contributes none. A pair whose
only deal was withdrawn therefore shows as a relationship with no invoices, which is
exactly true and is what the panel renders.

Two deals between the same pair produce **one** relationship. That is the point of the
pair being unique, and it is why the report counts pairs rather than deals.

Rollback
--------
``DELETE FROM onboarding.trade_relationship WHERE source = 'backfill' AND source_ref =
'<run id>'`` undoes a run exactly, provided it is done before anything records an
invoice against one of those relationships (``trade_invoice.relationship_id`` would
refuse the delete, and should). The command does not offer it as a flag: unlike the
buyer migration there is nothing frozen in the way, so a one-line ``DELETE`` an
operator can read is better than a mode they have to trust. ``--validate`` after the
delete shows the backfill undone.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

# Settles the API/application import cycle before anything else does; needed only
# because this module is a command. See `migrate_deal_buyers` for the same line.
import app.modules.onboarding.api  # noqa: F401  (import order, not an unused import)
from app.modules.onboarding.application.trade_history_service import (
    SOURCE_BACKFILL,
    TradeHistoryService,
)
from app.modules.onboarding.command_console import prepare_console
from app.modules.onboarding.domain.entities.deal import Deal
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.modules.onboarding.domain.entities.trade_relationship import TradeRelationship
from app.platform.database import services as db_services

logger = structlog.get_logger(__name__)

#: How many rows of each kind the report prints before summarising. The buyer
#: migration's lesson: a report that prints 568 rows is a report nobody reads.
DEFAULT_ROWS_SHOWN = 20

#: Above this share of deals still unmigrated, the dry run says the buyer migration looks unapplied
#: rather than letting the operator read a report about the remainder.
UNMIGRATED_WARNING_SHARE = 0.5


@dataclass(frozen=True)
class Pair:
    """One ordered pair of companies and the deals that put them together."""

    seller_company_id: uuid.UUID
    buyer_company_id: uuid.UUID
    deal_ids: tuple[uuid.UUID, ...]
    seller_name: str | None = None
    buyer_name: str | None = None
    exists: bool = False

    def label(self) -> str:
        seller = self.seller_name or str(self.seller_company_id)
        buyer = self.buyer_name or str(self.buyer_company_id)
        deals = f"{len(self.deal_ids)} deal" + ("s" if len(self.deal_ids) != 1 else "")
        return f"{seller} -> {buyer}  ({deals})"


@dataclass
class Report:
    """What a run would do. Built by `resolve`, printed by `render`, consumed by
    `apply` — the same shape as the buyer migration's, for the same reason: the thing
    the operator read is the thing that runs."""

    pairs: list[Pair] = field(default_factory=list)
    self_dealing: list[Pair] = field(default_factory=list)
    deals_with_a_buyer_company: int = 0
    deals_without_one: int = 0

    @property
    def to_create(self) -> list[Pair]:
        return [p for p in self.pairs if not p.exists]

    @property
    def already_there(self) -> list[Pair]:
        return [p for p in self.pairs if p.exists]

    @property
    def looks_unapplied(self) -> bool:
        """Whether the buyer migration looks unapplied, so the operator is told rather than handed a
        report about whichever deals happen to be linked already."""
        total = self.deals_with_a_buyer_company + self.deals_without_one
        if not total:
            return False
        return self.deals_without_one / total > UNMIGRATED_WARNING_SHARE

    def render(self, *, show: int = DEFAULT_ROWS_SHOWN) -> str:
        lines = ["", "Trade relationship backfill", "=" * 60]
        lines.append(f"deals with a buyer company:   {self.deals_with_a_buyer_company}")
        lines.append(f"deals with none:              {self.deals_without_one}")
        lines.append(f"company pairs:                {len(self.pairs)}")
        lines.append(f"  relationships to create:    {len(self.to_create)}")
        lines.append(f"  already there:              {len(self.already_there)}")
        if self.self_dealing:
            lines.append(f"  refused (seller = buyer):   {len(self.self_dealing)}")

        if self.looks_unapplied:
            lines += [
                "",
                "WARNING: most deals have no buyer company, so the buyer migration "
                "looks unapplied.",
                "  This backfill runs after the buyer migration; running it now "
                "covers only the few",
                "  deals already linked and the rest would need a second run. Apply "
                "the buyer migration first.",
            ]

        if self.to_create:
            lines += ["", f"To create ({len(self.to_create)}):"]
            lines += [f"  {p.label()}" for p in self.to_create[:show]]
            if len(self.to_create) > show:
                lines.append(f"  ... and {len(self.to_create) - show} more (--show-all)")

        if self.self_dealing:
            lines += [
                "",
                f"Refused - a company does not sell to itself ({len(self.self_dealing)}):",
            ]
            for pair in self.self_dealing[:show]:
                lines.append(f"  {pair.label()}")
                lines.append(f"    company {pair.seller_company_id}")
                lines.append(
                    "    deals: " + ", ".join(str(d) for d in pair.deal_ids[:5])
                )
            if len(self.self_dealing) > show:
                lines.append(f"  ... and {len(self.self_dealing) - show} more (--show-all)")
            lines += [
                "",
                "  These rows need correcting by hand: either the deal's buyer company "
                "is wrong, or two",
                "  records of one company were merged into one. The buyer migration "
                "reports the same",
                "  rows (plan section 17.2's 'deals whose buyer company is their own "
                "seller'), so "
                "this is the second",
                "  time they have been named.",
            ]

        lines.append("")
        return "\n".join(lines)


async def resolve(db: AsyncSession, *, only_deals: set[uuid.UUID] | None = None) -> Report:
    """Read what is there and decide what a run would create. **Writes nothing.**

    ``only_deals`` narrows it to named deals, which the tests use: the shared database
    holds other suites' deals, and a report about all of them says nothing about the
    rows a test created.
    """
    report = Report()

    report.deals_without_one = int(
        await db.scalar(
            select(func.count())
            .select_from(Deal)
            .where(Deal.buyer_company_id.is_(None))
        )
        or 0
    )

    query = select(Deal.id, Deal.company_id, Deal.buyer_company_id).where(
        Deal.buyer_company_id.isnot(None)
    )
    if only_deals is not None:
        query = query.where(Deal.id.in_(only_deals))
    rows = list(await db.execute(query))
    report.deals_with_a_buyer_company = len(rows)

    grouped: dict[tuple[uuid.UUID, uuid.UUID], list[uuid.UUID]] = defaultdict(list)
    for deal_id, seller_id, buyer_id in rows:
        grouped[(seller_id, buyer_id)].append(deal_id)

    # One query for every name rather than one per pair: a report on a few thousand
    # deals should not be a few thousand round trips.
    company_ids = {cid for pair in grouped for cid in pair}
    names: dict[uuid.UUID, str] = {}
    if company_ids:
        names = {
            cid: name
            for cid, name in await db.execute(
                select(ExporterProfile.customer_id, ExporterProfile.name).where(
                    ExporterProfile.customer_id.in_(company_ids)
                )
            )
        }

    existing = {
        (seller, buyer)
        for seller, buyer in await db.execute(
            select(
                TradeRelationship.seller_company_id, TradeRelationship.buyer_company_id
            ).where(
                TradeRelationship.seller_company_id.in_(
                    {seller for seller, _ in grouped}
                )
            )
        )
    }

    for (seller_id, buyer_id), deal_ids in sorted(
        grouped.items(), key=lambda item: len(item[1]), reverse=True
    ):
        pair = Pair(
            seller_company_id=seller_id,
            buyer_company_id=buyer_id,
            deal_ids=tuple(deal_ids),
            seller_name=names.get(seller_id),
            buyer_name=names.get(buyer_id),
            exists=(seller_id, buyer_id) in existing,
        )
        if seller_id == buyer_id:
            # `ck_trade_relationship_not_self` would refuse it and the service raises
            # before that. Reported, never skipped silently: the deal is wrong.
            report.self_dealing.append(pair)
        else:
            report.pairs.append(pair)

    logger.info(
        "trade_backfill.resolved",
        pairs=len(report.pairs),
        to_create=len(report.to_create),
        self_dealing=len(report.self_dealing),
    )
    return report


async def apply(
    db: AsyncSession, report: Report, *, run_id: str, actor_id: str
) -> dict[str, int]:
    """Create the relationships the report named.

    It goes through the service rather than inserting rows, so a backfilled
    relationship is indistinguishable from one the deal path created — same
    validation, same race handling, same columns. ``created`` comes from the database
    (``get_or_create_relationship``'s second return value), so a pair another process
    created a moment ago is counted as found rather than created.
    """
    counts = {"created": 0, "already_there": 0, "refused": len(report.self_dealing)}
    service = TradeHistoryService(db)

    for pair in report.pairs:
        _, created = await service.get_or_create_relationship(
            seller_company_id=pair.seller_company_id,
            buyer_company_id=pair.buyer_company_id,
            actor_id=actor_id,
            source=SOURCE_BACKFILL,
            source_ref=run_id,
        )
        counts["created" if created else "already_there"] += 1

    await db.commit()
    logger.info("trade_backfill.applied", run_id=run_id, **counts)
    return counts


# ── Validation ────────────────────────────────────────────────────────────────

#: Every query must return 0. The labels say what is wrong, not what was counted.
VALIDATION_QUERIES: tuple[tuple[str, str], ...] = (
    (
        "deals with a buyer company but no relationship for the pair",
        """
        SELECT count(*) FROM onboarding.deal d
        WHERE d.buyer_company_id IS NOT NULL
          AND d.buyer_company_id <> d.company_id
          AND NOT EXISTS (
            SELECT 1 FROM onboarding.trade_relationship r
            WHERE r.seller_company_id = d.company_id
              AND r.buyer_company_id = d.buyer_company_id
          )
        """,
    ),
    (
        "deals whose buyer company is their own seller",
        "SELECT count(*) FROM onboarding.deal WHERE buyer_company_id = company_id",
    ),
    (
        "relationships where seller and buyer are the same company",
        """
        SELECT count(*) FROM onboarding.trade_relationship
        WHERE seller_company_id = buyer_company_id
        """,
    ),
    (
        "duplicate relationships for one ordered pair",
        """
        SELECT coalesce(sum(n - 1), 0) FROM (
          SELECT count(*) AS n FROM onboarding.trade_relationship
          GROUP BY seller_company_id, buyer_company_id
        ) AS pairs
        """,
    ),
    (
        "relationships naming a company that does not exist",
        """
        SELECT count(*) FROM onboarding.trade_relationship r
        WHERE NOT EXISTS (
            SELECT 1 FROM onboarding.exporter_profile p
            WHERE p.customer_id = r.seller_company_id
          )
          OR NOT EXISTS (
            SELECT 1 FROM onboarding.exporter_profile p
            WHERE p.customer_id = r.buyer_company_id
          )
        """,
    ),
    (
        "invoices whose relationship is gone",
        """
        SELECT count(*) FROM onboarding.trade_invoice i
        WHERE NOT EXISTS (
            SELECT 1 FROM onboarding.trade_relationship r WHERE r.id = i.relationship_id
          )
        """,
    ),
)


async def validate(db: AsyncSession) -> list[tuple[str, int]]:
    """Run the checks and return ``(label, count)``. The caller decides what a
    non-zero count means — the tests assert the queries **run**, because this shared
    database is not a migrated environment."""
    return [
        (label, int(await db.scalar(text(sql)) or 0)) for label, sql in VALIDATION_QUERIES
    ]


async def report_run(db: AsyncSession, *, run_id: str) -> dict[str, int]:
    """What one run created, for an operator deciding whether to undo it.

    Reads only. The undo is the ``DELETE`` in this module's docstring, deliberately
    left as something the operator runs and can read.
    """
    created = int(
        await db.scalar(
            select(func.count())
            .select_from(TradeRelationship)
            .where(
                TradeRelationship.source == SOURCE_BACKFILL,
                TradeRelationship.source_ref == run_id,
            )
        )
        or 0
    )
    with_invoices = int(
        await db.scalar(
            text(
                """
                SELECT count(DISTINCT r.id) FROM onboarding.trade_relationship r
                JOIN onboarding.trade_invoice i ON i.relationship_id = r.id
                WHERE r.source = :source AND r.source_ref = :run_id
                """
            ).bindparams(source=SOURCE_BACKFILL, run_id=run_id)
        )
        or 0
    )
    counts = {"created": created, "with_invoices_since": with_invoices}
    logger.info("trade_backfill.run_report", run_id=run_id, **counts)
    return counts


# ── The command ───────────────────────────────────────────────────────────────


async def _main(args: argparse.Namespace) -> int:
    async with db_services.AsyncSessionLocal() as db:
        if args.validate:
            failures = 0
            print("\nP5-5 validation")
            print("=" * 60)
            for label, count in await validate(db):
                if count:
                    failures += 1
                print(f"{'OK  ' if count == 0 else 'FAIL'} {count:>6}  {label}")
            print()
            return 1 if failures else 0

        if args.report_run:
            counts = await report_run(db, run_id=args.run_id)
            print(f"\nRun {args.run_id}")
            print("=" * 60)
            print(f"  relationships created:        {counts['created']}")
            print(f"  of those, now with invoices:  {counts['with_invoices_since']}")
            print(
                "\nTo undo the run:\n"
                "  DELETE FROM onboarding.trade_relationship\n"
                f"   WHERE source = '{SOURCE_BACKFILL}' AND source_ref = '{args.run_id}';\n"
            )
            if counts["with_invoices_since"]:
                print(
                    f"  {counts['with_invoices_since']} relationship(s) now carry "
                    "invoices and the DELETE will refuse them.\n"
                    "  That is the foreign key doing its job: an invoice is a fact "
                    "about money and the\n"
                    "  relationship it belongs to cannot vanish under it. Decide what "
                    "those invoices are\n"
                    "  before undoing anything.\n"
                )
            return 0

        report = await resolve(db)
        print(report.render(show=10**9 if args.show_all else DEFAULT_ROWS_SHOWN))

        if args.dry_run:
            print("Dry run: nothing was written.")
            if report.self_dealing:
                print(
                    f"{len(report.self_dealing)} pair(s) are refused and need a person; "
                    "the lines above name them."
                )
            return 0

        counts = await apply(
            db, report, run_id=args.run_id, actor_id=args.actor or f"backfill:{args.run_id}"
        )
        print(f"Applied run {args.run_id}: {counts}")
        print("Now run --validate; every count must be 0.\n")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.modules.onboarding.backfill_trade_relationships",
        description=(
            "Create a trade relationship for every deal that has a buyer company. "
            "Run it only after the buyer migration has been applied. "
            "Take a pg_dump first, read the --dry-run report, then --apply and "
            "--validate."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="report, write nothing")
    mode.add_argument("--apply", action="store_true", help="create the relationships")
    mode.add_argument("--validate", action="store_true", help="run the backfill's checks")
    mode.add_argument(
        "--report-run",
        action="store_true",
        help="what one run created, and the DELETE that undoes it (writes nothing)",
    )
    parser.add_argument("--run-id", help="required for --apply and --report-run")
    parser.add_argument("--actor", help="who is running it; defaults to the run id")
    parser.add_argument(
        "--show-all", action="store_true", help="print every pair rather than the first few"
    )
    args = parser.parse_args()

    if (args.apply or args.report_run) and not args.run_id:
        parser.error("--run-id is required for --apply and --report-run")
    prepare_console()
    return asyncio.run(_main(args))


if __name__ == "__main__":  # pragma: no cover - the command's entry point
    raise SystemExit(main())
