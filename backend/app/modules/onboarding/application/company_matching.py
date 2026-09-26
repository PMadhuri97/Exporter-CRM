"""``CompanyMatcher`` — is an incoming company one the CRM already has?
(L2-12, L2-13). **Owner: Developer 2.**

The one matching algorithm, used by RXIL intake and bulk import alike, built on
the company record's own identity rules (``docs/contracts/company-record.md``
§4). It never merges two companies and never writes anything: it classifies.

* **PAN decides.** PAN is unique across companies, so a company holding the
  incoming PAN — or, when none was given, the PAN every incoming GSTIN carries
  in characters 3–12 — *is* the incoming company: ``MATCHED``.
* **A match must not disagree.** If the matched company has a different CIN or
  IEC, or another company holds the incoming CIN or IEC, the identifiers point
  at different companies: ``CONFLICT``, with every company involved named.
* **GSTINs warn.** Another company holding an incoming GSTIN is a warning,
  never a refusal (decision 4), when a PAN settles which company this is.
* **Without a PAN to settle it, shared identifiers are only a resemblance.**
  A company sharing a GSTIN, IEC or CIN with no PAN confirming it is a
  ``POSSIBLE_DUPLICATE`` — for a person to decide, never merged. More than one
  such company is also ``AMBIGUOUS_MATCH``.
* Nothing shared: ``NEW``.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.domain.company_intake import (
    CompanyMatch,
    IntakeIdentity,
    MatchKind,
    Reason,
)
from app.modules.onboarding.infrastructure.repositories import ExporterProfileRepository


class CompanyMatcher:
    def __init__(self, db: AsyncSession) -> None:
        self._profiles = ExporterProfileRepository(db)

    async def match(self, identity: IntakeIdentity) -> CompanyMatch:
        pan = identity.matching_pan
        confirmed = await self._profiles.get_by_pan(pan) if pan is not None else None
        holders = await self._profiles.holders_of_identifiers(
            gstins=identity.gstins, iec=identity.iec, cin=identity.cin
        )

        if confirmed is not None:
            return self._confirmed(identity, confirmed, holders)
        if not holders:
            return CompanyMatch(MatchKind.NEW)

        profiles = {p.customer_id: p for p in await self._profiles.get_many(list(holders))}
        candidates = tuple(sorted(holders, key=str))
        by_iec_or_cin = [cid for cid, kinds in holders.items() if kinds & {"iec", "cin"}]

        if identity.pan is not None:
            clashing = [
                cid for cid in by_iec_or_cin
                if profiles[cid].pan is not None and profiles[cid].pan != identity.pan
            ]
            if clashing:
                return CompanyMatch(
                    MatchKind.CONFLICT,
                    candidates=candidates,
                    reasons=(
                        Reason(
                            "CONFLICTING_IDENTIFIERS",
                            "the IEC or CIN belongs to a company with a different PAN",
                        ),
                    ),
                )
            if not by_iec_or_cin:
                # Only GSTINs are shared, with companies that have no PAN, and
                # this company brings a PAN of its own: a warning, not a stop.
                return CompanyMatch(
                    MatchKind.NEW,
                    warnings=(_gstin_warning(candidates),),
                )

        reasons = [
            Reason(
                "POSSIBLE_DUPLICATE",
                "shares identifiers with an existing company, but no PAN confirms it "
                "is the same company",
            )
        ]
        if len(candidates) > 1:
            reasons.append(
                Reason("AMBIGUOUS_MATCH", f"{len(candidates)} existing companies share its identifiers")
            )
        return CompanyMatch(
            MatchKind.POSSIBLE_DUPLICATE, candidates=candidates, reasons=tuple(reasons)
        )

    def _confirmed(self, identity: IntakeIdentity, confirmed, holders) -> CompanyMatch:
        reasons: list[Reason] = []
        for field in ("iec", "cin"):
            mine, theirs = getattr(identity, field), getattr(confirmed, field)
            if mine is not None and theirs is not None and mine != theirs:
                reasons.append(
                    Reason(
                        "CONFLICTING_IDENTIFIERS",
                        f"the company with this PAN has a different {field.upper()}",
                    )
                )
        others = {cid: kinds for cid, kinds in holders.items() if cid != confirmed.customer_id}
        elsewhere = sorted({kind for kinds in others.values() for kind in kinds} & {"iec", "cin"})
        if elsewhere:
            reasons.append(
                Reason(
                    "CONFLICTING_IDENTIFIERS",
                    f"this {' and '.join(k.upper() for k in elsewhere)} belongs to another "
                    "company than this PAN",
                )
            )
        if reasons:
            return CompanyMatch(
                MatchKind.CONFLICT,
                candidates=(confirmed.customer_id, *sorted(others, key=str)),
                reasons=tuple(reasons),
            )
        warnings = (_gstin_warning(tuple(sorted(others, key=str))),) if others else ()
        return CompanyMatch(
            MatchKind.MATCHED, customer_id=confirmed.customer_id, warnings=warnings
        )


def _gstin_warning(holders) -> Reason:
    return Reason(
        "GSTIN_HELD_BY_OTHER_COMPANY",
        f"a GSTIN is also held by {len(holders)} other "
        f"compan{'y' if len(holders) == 1 else 'ies'}: {', '.join(str(h) for h in holders)}",
    )


__all__ = ["CompanyMatcher"]
