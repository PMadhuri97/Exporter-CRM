"""Turn each GST branch's free-text address into a company address, and link it.

    python -m app.modules.onboarding.convert_gst_addresses --dry-run
    python -m app.modules.onboarding.convert_gst_addresses --apply --run-id 2026-10-14a
    python -m app.modules.onboarding.convert_gst_addresses --validate

Run it with ``LOG_LEVEL=WARNING DEBUG=false`` (``command_console``). The sequence is the
other data commands': ``pg_dump``, ``--dry-run``, read the report, ``--apply``,
``--validate``.

Why
---
A GST branch used to carry its registered address as free text
(``exporter_gstin.address``), beside a link to a structured company address
(``address_id``). The text is retired: the API no longer takes or serves it, and a later
migration drops the column. This command moves what is there into company addresses
first, so nothing typed in is lost.

What it writes
--------------
For every branch with text and no ``address_id``, one ``company_address`` through
``CompanyAddressService.add`` — the table's one writer, so each gets its ``address``
history row — and the branch is linked to it:

* ``address_type`` ``CORRESPONDENCE`` (decided 14 October 2026);
* ``line1`` the text, cut at 255 characters, the rest in ``line2``;
* ``state`` the branch's state from its GSTIN, ``country`` ``IN``;
* ``city`` ``Not recorded``: the text has no separate city, and the column requires
  one. A person corrects it on the company's Addresses section.

Branches of one company with the same text (compared ignoring case and repeated spaces)
share one address. Text longer than 510 characters does not fit two lines; it is
reported and left for a person.

The text itself is not cleared: the column goes with the later migration, which refuses
while any branch still has text and no address.

**Idempotent.** A converted branch has an address afterwards, so a second run finds
nothing to do. Each company is locked and its branches re-read first; a branch linked
since the report is skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# The onboarding package's API and application layers import each other, so whichever
# is imported first decides whether that resolves; a command is the first thing Python
# loads, so it settles it here (as `migrate_deal_buyers` does).
import app.modules.onboarding.api  # noqa: F401  (import order, not an unused import)
from app.modules.onboarding.application.company_address_service import CompanyAddressService
from app.modules.onboarding.command_console import prepare_console
from app.modules.onboarding.domain.entities.exporter_gstin import ExporterGstin
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.platform.database import services as db_services

ADDRESS_TYPE = "CORRESPONDENCE"
CITY_NOT_RECORDED = "Not recorded"
LINE_LENGTH = 255
DEFAULT_ROWS_SHOWN = 20


def text_key(value: str) -> str:
    """Case-folded, trimmed, inner whitespace collapsed."""
    return re.sub(r"\s+", " ", value.strip()).casefold()


def split_lines(value: str) -> tuple[str, str | None]:
    """The text as ``line1`` and ``line2``; at most 255 characters each."""
    text = re.sub(r"\s+", " ", value.strip())
    first, rest = text[:LINE_LENGTH], text[LINE_LENGTH:].strip()
    return first.strip(), rest or None


@dataclass
class Group:
    """Branches of one company sharing one address text: one address for all."""

    customer_id: uuid.UUID
    text: str
    state: str | None
    branch_ids: list[uuid.UUID] = field(default_factory=list)


@dataclass
class Report:
    groups: list[Group] = field(default_factory=list)
    #: ``(branch id, company id, length)`` of text too long for two lines.
    too_long: list[tuple[uuid.UUID, uuid.UUID, int]] = field(default_factory=list)

    @property
    def branches(self) -> int:
        return sum(len(group.branch_ids) for group in self.groups)

    def render(self, show: int = DEFAULT_ROWS_SHOWN) -> str:
        lines = ["", "GST branch address text -> company addresses", "=" * 60]
        lines.append(f"  branches to convert:            {self.branches}")
        lines.append(f"  addresses --apply would create: {len(self.groups)}")
        lines.append(f"  too long for two lines (left):  {len(self.too_long)}")
        if self.groups:
            lines.append("\nTo convert:")
            for group in self.groups[:show]:
                line1, line2 = split_lines(group.text)
                lines.append(
                    f"  company {group.customer_id}: {len(group.branch_ids)} branch(es) -> "
                    f"'{line1}'{' + line2' if line2 else ''} ({group.state or 'no state'})"
                )
            if len(self.groups) > show:
                lines.append(f"  ... and {len(self.groups) - show} more (--show-all)")
        if self.too_long:
            lines.append("\nToo long, for a person to enter by hand:")
            for branch_id, company_id, length in self.too_long[:show]:
                lines.append(f"  branch {branch_id} (company {company_id}): {length} characters")
        lines.append("")
        return "\n".join(lines)


def _unconverted():
    return select(
        ExporterGstin.id,
        ExporterGstin.customer_id,
        ExporterGstin.address,
        ExporterGstin.state_name,
    ).where(
        ExporterGstin.address.isnot(None),
        func.btrim(ExporterGstin.address) != "",
        ExporterGstin.address_id.is_(None),
    )


async def resolve(db: AsyncSession) -> Report:
    """What a run would do, writing nothing."""
    rows = (
        await db.execute(_unconverted().order_by(ExporterGstin.customer_id, ExporterGstin.gstin))
    ).all()
    report = Report()
    groups: dict[tuple[uuid.UUID, str], Group] = {}
    for branch_id, customer_id, text, state in rows:
        if len(re.sub(r"\s+", " ", text.strip())) > 2 * LINE_LENGTH:
            report.too_long.append((branch_id, customer_id, len(text)))
            continue
        key = (customer_id, text_key(text))
        if key not in groups:
            groups[key] = Group(customer_id, text, state)
            report.groups.append(groups[key])
        groups[key].branch_ids.append(branch_id)
    return report


async def apply(db: AsyncSession, report: Report, *, run_id: str, actor_id: str) -> dict[str, int]:
    """Create and link each group's address, one transaction per company."""
    service = CompanyAddressService(db)
    counts = {"addresses_created": 0, "branches_linked": 0, "skipped": 0}
    by_company: dict[uuid.UUID, list[Group]] = defaultdict(list)
    for group in report.groups:
        by_company[group.customer_id].append(group)

    for customer_id, groups in by_company.items():
        for group in groups:
            # Lock the company, then re-read the branches: one linked since the report
            # is left alone.
            await db.scalar(
                select(ExporterProfile.customer_id)
                .where(ExporterProfile.customer_id == customer_id)
                .with_for_update()
            )
            branches = list(
                await db.scalars(
                    select(ExporterGstin)
                    .where(
                        ExporterGstin.id.in_(group.branch_ids),
                        ExporterGstin.address_id.is_(None),
                    )
                    .order_by(ExporterGstin.gstin)
                    .execution_options(populate_existing=True)
                )
            )
            counts["skipped"] += len(group.branch_ids) - len(branches)
            if not branches:
                await db.rollback()
                continue
            line1, line2 = split_lines(group.text)
            address = await service.add(
                customer_id,
                fields={
                    "address_type": ADDRESS_TYPE,
                    "line1": line1,
                    "line2": line2,
                    "city": CITY_NOT_RECORDED,
                    "state": group.state,
                    "postal_code": None,
                    "country": "IN",
                },
                make_default=False,
                actor_id=actor_id,
                gst_registration_id=branches[0].id,
            )
            counts["addresses_created"] += 1
            counts["branches_linked"] += 1
            # The other branches with the same text share the address.
            for branch in branches[1:]:
                linked = await db.scalar(
                    select(ExporterGstin)
                    .where(ExporterGstin.id == branch.id, ExporterGstin.address_id.is_(None))
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if linked is None:
                    counts["skipped"] += 1
                    continue
                linked.address_id = address.id
                counts["branches_linked"] += 1
            await db.commit()
    return counts


async def validate(db: AsyncSession) -> list[tuple[str, int]]:
    """Checks that must all be 0 before the text column can be dropped."""
    left = await db.scalar(select(func.count()).select_from(_unconverted().subquery()))
    return [("GST branches with address text and no linked address", int(left or 0))]


async def _main(args: argparse.Namespace) -> int:
    async with db_services.AsyncSessionLocal() as db:
        if args.validate:
            failures = 0
            print("\nGST address validation")
            print("=" * 60)
            for label, count in await validate(db):
                failures += 1 if count else 0
                print(f"{'OK  ' if count == 0 else 'FAIL'} {count:>6}  {label}")
            print()
            return 1 if failures else 0

        report = await resolve(db)
        print(report.render(show=10**9 if args.show_all else DEFAULT_ROWS_SHOWN))
        if args.dry_run:
            print("Dry run: nothing was written.")
            return 0
        counts = await apply(
            db, report, run_id=args.run_id, actor_id=args.actor or f"convert:{args.run_id}"
        )
        print(f"Applied run {args.run_id}: {counts}")
        print("Now run --validate; every count must be 0.\n")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.modules.onboarding.convert_gst_addresses",
        description=(
            "Turn each GST branch's free-text address into a linked company address. "
            "Take a pg_dump first, read the --dry-run report, then --apply and --validate."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="report, write nothing")
    mode.add_argument("--apply", action="store_true", help="create and link the addresses")
    mode.add_argument("--validate", action="store_true", help="run the checks")
    parser.add_argument("--run-id", help="required for --apply")
    parser.add_argument("--actor", help="who is running it; defaults to the run id")
    parser.add_argument("--show-all", action="store_true", help="print every row")
    args = parser.parse_args()
    if args.apply and not args.run_id:
        parser.error("--run-id is required for --apply")
    prepare_console()
    return asyncio.run(_main(args))


if __name__ == "__main__":  # pragma: no cover - the command's entry point
    raise SystemExit(main())


__all__ = ["Report", "apply", "resolve", "split_lines", "validate"]
