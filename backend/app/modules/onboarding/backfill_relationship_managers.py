"""Match each company's legacy free-text owner to a relationship manager user.

    python -m app.modules.onboarding.backfill_relationship_managers --dry-run
    python -m app.modules.onboarding.backfill_relationship_managers --apply --run-id 2026-10-08a
    python -m app.modules.onboarding.backfill_relationship_managers --validate

Run it with ``LOG_LEVEL=WARNING DEBUG=false`` (``command_console``). The sequence is the
other data commands': ``pg_dump``, ``--dry-run``, read the report, ``--apply``,
``--validate``.

What it matches
---------------
Companies whose legacy ``relationship_manager`` text is set and whose
``relationship_manager_user_id`` is not. The text is compared, **exactly** apart from
case and repeated spaces, with every account's ``full_name``. A company is matched only
when exactly one **active OPERATIONS** account carries that name. Everything else is
reported and left alone:

* **ambiguous** — two or more active RM accounts share the name;
* **not an RM** — the name belongs only to an ADMIN, COMPLIANCE or DEVELOPER account,
  or to a deactivated one: an RM is an active OPERATIONS user, and guessing otherwise
  would make someone an owner they never were;
* **no match** — nobody has that name.

No fuzzy matching: a wrong owner is worse than none, since an RM without the company
can claim it, while a wrong one has to be noticed first.

What it writes
--------------
For each match, ``relationship_manager_user_id`` through
``ExporterProfileService.set_relationship_manager`` — the column's one writer — with a
``relationship_manager`` history row whose source is
``backfill_relationship_managers`` and whose ``bulk_run_id`` is the run id. The legacy
text is left as it is. Each company is locked and re-read first: one that gained an RM
since the report is skipped.

**Idempotent.** A matched company has an RM afterwards, so a second run finds nothing
to do.

Rollback
--------
The history rows name the run, so a run is undone by clearing the RM on the companies
it set (``event_metadata->>'bulk_run_id' = '<run id>'``) — through the RM route, so that
the clearing is on the record too.
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

from app.modules.onboarding.application.exporter_profile_service import ExporterProfileService
from app.modules.onboarding.command_console import prepare_console
from app.modules.onboarding.domain.assignment import RM_ROLES
from app.modules.onboarding.domain.entities.exporter_profile import ExporterProfile
from app.platform.authentication.models import User
from app.platform.database import services as db_services

SOURCE = "backfill_relationship_managers"
REASON = "Matched from the company's legacy owner label"
DEFAULT_ROWS_SHOWN = 20


def normalise_name(value: str | None) -> str:
    """Case-folded, trimmed, inner whitespace collapsed."""
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


@dataclass
class Report:
    matched: list[tuple[uuid.UUID, str, uuid.UUID]] = field(default_factory=list)
    ambiguous: list[tuple[uuid.UUID, str, int]] = field(default_factory=list)
    not_an_rm: list[tuple[uuid.UUID, str, str]] = field(default_factory=list)
    no_match: list[tuple[uuid.UUID, str]] = field(default_factory=list)

    def render(self, show: int = DEFAULT_ROWS_SHOWN) -> str:
        lines = ["", "Legacy owner -> relationship manager", "=" * 60]
        lines.append(f"  matched to one active RM:        {len(self.matched)}")
        lines.append(f"  ambiguous (several active RMs):  {len(self.ambiguous)}")
        lines.append(f"  name is not an active RM's:     {len(self.not_an_rm)}")
        lines.append(f"  no account with that name:      {len(self.no_match)}")
        for title, rows in (
            ("Matched", [f"{c}  '{t}' -> {u}" for c, t, u in self.matched]),
            ("Ambiguous", [f"{c}  '{t}' ({n} active RMs)" for c, t, n in self.ambiguous]),
            ("Not an RM", [f"{c}  '{t}' ({why})" for c, t, why in self.not_an_rm]),
            ("No match", [f"{c}  '{t}'" for c, t in self.no_match]),
        ):
            if rows:
                lines.append(f"\n{title}:")
                lines += [f"  {row}" for row in rows[:show]]
                if len(rows) > show:
                    lines.append(f"  ... and {len(rows) - show} more (--show-all)")
        lines.append("")
        return "\n".join(lines)


async def resolve(db: AsyncSession) -> Report:
    """What a run would do, writing nothing."""
    companies = (
        await db.execute(
            select(ExporterProfile.customer_id, ExporterProfile.relationship_manager)
            .where(
                ExporterProfile.relationship_manager.isnot(None),
                func.btrim(ExporterProfile.relationship_manager) != "",
                ExporterProfile.relationship_manager_user_id.is_(None),
            )
            .order_by(ExporterProfile.customer_id)
        )
    ).all()
    users = (
        await db.execute(select(User.id, User.full_name, User.role, User.is_active))
    ).all()
    by_name: dict[str, list] = defaultdict(list)
    for user in users:
        if user.full_name:
            by_name[normalise_name(user.full_name)].append(user)

    report = Report()
    for company_id, text in companies:
        candidates = by_name.get(normalise_name(text), [])
        eligible = [u for u in candidates if u.is_active and u.role in RM_ROLES]
        if len(eligible) == 1:
            report.matched.append((company_id, text, eligible[0].id))
        elif len(eligible) > 1:
            report.ambiguous.append((company_id, text, len(eligible)))
        elif candidates:
            why = ", ".join(
                sorted(
                    {
                        f"{u.role.value}{'' if u.is_active else ' (deactivated)'}"
                        for u in candidates
                    }
                )
            )
            report.not_an_rm.append((company_id, text, why))
        else:
            report.no_match.append((company_id, text))
    return report


async def apply(db: AsyncSession, report: Report, *, run_id: str, actor_id: str) -> dict[str, int]:
    """Set each matched company's RM, one transaction per company."""
    service = ExporterProfileService(db)
    counts = {"set": 0, "skipped": 0}
    for company_id, _text, user_id in report.matched:
        profile = await db.scalar(
            select(ExporterProfile)
            .where(ExporterProfile.customer_id == company_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if profile is None or profile.relationship_manager_user_id is not None:
            counts["skipped"] += 1
            await db.rollback()
            continue
        await service.set_relationship_manager(
            profile,
            user_id=user_id,
            reason=REASON,
            actor_id=actor_id,
            actor_role=None,
            source=SOURCE,
            bulk_run_id=run_id,
            bypass_permission=True,
        )
        await db.commit()
        counts["set"] += 1
    return counts


async def validate(db: AsyncSession) -> list[tuple[str, int]]:
    """Checks that must all be 0 after a run."""
    rm_ids = select(ExporterProfile.relationship_manager_user_id).where(
        ExporterProfile.relationship_manager_user_id.isnot(None)
    )
    not_a_user = await db.scalar(
        select(func.count()).select_from(
            rm_ids.where(
                ExporterProfile.relationship_manager_user_id.notin_(select(User.id))
            ).subquery()
        )
    )
    not_operations = await db.scalar(
        select(func.count())
        .select_from(ExporterProfile)
        .join(User, User.id == ExporterProfile.relationship_manager_user_id)
        .where(User.role.notin_(list(RM_ROLES)))
    )
    return [
        ("companies whose RM is not a user", int(not_a_user or 0)),
        ("companies whose RM is not an RM (OPERATIONS) account", int(not_operations or 0)),
    ]


async def _main(args: argparse.Namespace) -> int:
    async with db_services.AsyncSessionLocal() as db:
        if args.validate:
            failures = 0
            print("\nRelationship manager validation")
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
            db, report, run_id=args.run_id, actor_id=args.actor or f"backfill:{args.run_id}"
        )
        print(f"Applied run {args.run_id}: {counts}")
        print("Now run --validate; every count must be 0.\n")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.modules.onboarding.backfill_relationship_managers",
        description=(
            "Match each company's legacy free-text owner to exactly one active RM user. "
            "Take a pg_dump first, read the --dry-run report, then --apply and --validate."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="report, write nothing")
    mode.add_argument("--apply", action="store_true", help="set the matched RMs")
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


__all__ = ["Report", "apply", "normalise_name", "resolve", "validate"]
