from dataclasses import dataclass
from datetime import date

from app.modules.compliance.domain.policies.effectivity import is_effective_at
from app.modules.compliance.domain.ports import PurposeCodeRepository
from app.modules.compliance.exceptions import (
    AmbiguousPurposeCodeMappingError,
    PurposeCodeInputError,
    PurposeCodeNotEffectiveError,
    PurposeCodeNotFoundError,
    PurposeCodeNotValidForCorridorError,
)


@dataclass
class ExternalPurposeCodeResolution:
    external_code: str
    external_standard: str
    #: The standard revision the code was read from. Carried out of the registry
    #: rather than looked up later: a payment filed under one revision must stay
    #: attributable to it even after the regulator publishes the next one.
    external_standard_version: str


async def validate_purpose_code(
    canonical_code: str, corridor_id: str, transaction_date: date, repository: PurposeCodeRepository
) -> ExternalPurposeCodeResolution:
    """Resolve a canonical purpose code to the external code a corridor requires.

    Effectivity is evaluated against ``transaction_date``, never today: a payment
    backdated to before a regulator renumbered its codes must carry the code that
    was in force when the money moved, and a code retired last month must be
    rejected for a transaction dated today.

    Raises a :class:`PurposeCodeError` subclass for every rejection, each with its
    own ``error_code`` — see ``compliance/exceptions.py`` for which failures are
    the caller's and which are ours.
    """
    if not canonical_code or not corridor_id or transaction_date is None:
        # Guarded rather than left to fail downstream: a null transaction_date
        # reaches the date comparison in is_effective_at and raises TypeError,
        # which the catch-all handler renders as a 500.
        raise PurposeCodeInputError(
            "canonical_code, corridor_id and transaction_date are all required",
            canonical_code=canonical_code,
            corridor_id=corridor_id,
            transaction_date=transaction_date,
        )

    history = await repository.get_canonical_history(canonical_code)
    if not history:
        raise PurposeCodeNotFoundError(
            f"Canonical purpose code {canonical_code} is not in the registry",
            canonical_code=canonical_code,
            corridor_id=corridor_id,
            transaction_date=transaction_date,
        )

    # A code retired and later reinstated has more than one row, each with its
    # own window. ex_purpose_code_canonical_validity guarantees the windows
    # never overlap, so at most one can match — unlike corridor mappings,
    # there is no ambiguity case to guard here.
    canonical = next(
        (c for c in history if is_effective_at(c.effective_from, c.effective_to, transaction_date)),
        None,
    )
    if canonical is None:
        if len(history) == 1:
            # The common case: one window, so naming it directly is more useful
            # than a list of one.
            only = history[0]
            raise PurposeCodeNotEffectiveError(
                f"Canonical purpose code {canonical_code} is not effective on {transaction_date}",
                canonical_code=canonical_code,
                corridor_id=corridor_id,
                transaction_date=transaction_date,
                effective_from=only.effective_from.isoformat(),
                effective_to=only.effective_to.isoformat() if only.effective_to else None,
            )
        raise PurposeCodeNotEffectiveError(
            f"Canonical purpose code {canonical_code} is not effective on {transaction_date}",
            canonical_code=canonical_code,
            corridor_id=corridor_id,
            transaction_date=transaction_date,
            effective_windows=[
                {
                    "effective_from": c.effective_from.isoformat(),
                    "effective_to": c.effective_to.isoformat() if c.effective_to else None,
                }
                for c in history
            ],
        )

    mappings = await repository.get_corridor_mappings(
        canonical_code=canonical_code, corridor_id=corridor_id
    )
    effective_mappings = [
        m for m in mappings if is_effective_at(m.effective_from, m.effective_to, transaction_date)
    ]

    # No mapping row and a mapping row outside its window are the same answer to
    # the caller: this corridor cannot carry this purpose on this date.
    if not effective_mappings:
        raise PurposeCodeNotValidForCorridorError(
            f"Purpose code {canonical_code} has no mapping in force for corridor "
            f"{corridor_id} on {transaction_date}",
            canonical_code=canonical_code,
            corridor_id=corridor_id,
            transaction_date=transaction_date,
        )

    # Not dead code, despite ex_purpose_code_mapping_validity. That constraint
    # includes external_standard_version in its key, so it only forbids overlap
    # *within* one standard revision — two revisions, or two standards, may still
    # claim the same corridor on the same date and the database will accept both.
    # Guessing between them would put an arbitrary regulatory code on a payment.
    if len(effective_mappings) > 1:
        raise AmbiguousPurposeCodeMappingError(
            f"Purpose code {canonical_code} has {len(effective_mappings)} mappings in force "
            f"for corridor {corridor_id} on {transaction_date}",
            canonical_code=canonical_code,
            corridor_id=corridor_id,
            transaction_date=transaction_date,
            external_codes=sorted(m.external_code for m in effective_mappings),
            external_standard_versions=sorted(
                m.external_standard_version for m in effective_mappings
            ),
        )

    mapping = effective_mappings[0]

    return ExternalPurposeCodeResolution(
        external_code=mapping.external_code,
        external_standard=mapping.external_standard,
        external_standard_version=mapping.external_standard_version,
    )
