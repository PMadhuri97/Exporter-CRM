"""`_validate_type_pair` — the verification_type / entity_type table.

Pure logic, no database: the service-level check that an uninterpretable pair
is rejected before any adapter runs lives in
`tests/integration/test_exp2_verification_service.py`.
"""

from __future__ import annotations

import pytest

from app.modules.onboarding.application.verification_service import (
    _VALID_ENTITY_TYPES_FOR_CHECK,
    _validate_type_pair,
)
from app.modules.onboarding.domain.entities.orchestration_enums import (
    VerificationEntityType,
    VerificationType,
)
from app.shared.exceptions import ValidationError

# ── verification_type / entity_type cross-validation ─────────────────────────
#
# `VerificationType` and `VerificationEntityType` are independent axes that
# share four member *names* (BUYER, INVOICE, VESSEL, SHIPMENT) with different
# meanings — on one a kind of check, on the other a kind of subject. Nothing
# validated the pair, so `verification_type=VESSEL, entity_type=EXPORTER` and
# `verification_type=VESSEL, entity_type=DIRECTOR` were equally acceptable and
# persisted as rows no reader could interpret.


def test_every_check_type_has_a_permitted_subject_set():
    """The table is exhaustive over `VerificationType`.

    A member with no entry would raise `KeyError` from whichever request first
    used it, rather than being rejected cleanly — the service module has an
    import-time guard for exactly this, and this pins the same property.
    """
    assert set(_VALID_ENTITY_TYPES_FOR_CHECK) == set(VerificationType)
    assert all(subjects for subjects in _VALID_ENTITY_TYPES_FOR_CHECK.values())


@pytest.mark.parametrize(
    ("verification_type", "entity_type"),
    [
        # Every pair the rest of this suite actually exercises, so the
        # validation can never silently break an existing flow.
        (VerificationType.KYC, VerificationEntityType.DIRECTOR),
        (VerificationType.AML, VerificationEntityType.DIRECTOR),
        (VerificationType.AML, VerificationEntityType.EXPORTER),
        (VerificationType.BANK_ACCOUNT, VerificationEntityType.EXPORTER),
        (VerificationType.BUYER, VerificationEntityType.BUYER),
        (VerificationType.GST, VerificationEntityType.EXPORTER),
        (VerificationType.INVOICE_DUPLICATION, VerificationEntityType.INVOICE),
        (VerificationType.KYB, VerificationEntityType.EXPORTER),
        # Deliberately permissive: a trade-object check billed against the
        # exporter is how these are commissioned in practice.
        (VerificationType.VESSEL, VerificationEntityType.EXPORTER),
        (VerificationType.SHIPMENT, VerificationEntityType.INVOICE),
    ],
)
def test_validate_type_pair_accepts_legitimate_combinations(
    verification_type, entity_type
):
    _validate_type_pair(verification_type, entity_type)


@pytest.mark.parametrize(
    ("verification_type", "entity_type"),
    [
        # The four colliding names, each paired with a subject that makes the
        # collision visible: these read as plausible until you notice the name
        # means something different on each enum.
        (VerificationType.VESSEL, VerificationEntityType.DIRECTOR),
        (VerificationType.INVOICE, VerificationEntityType.VESSEL),
        (VerificationType.BUYER, VerificationEntityType.SHIPMENT),
        (VerificationType.SHIPMENT, VerificationEntityType.DIRECTOR),
        # A statutory lookup against a trade object rather than an org.
        (VerificationType.GST, VerificationEntityType.SHIPMENT),
        (VerificationType.IEC, VerificationEntityType.INVOICE),
        # An identity check against a thing rather than a person.
        (VerificationType.KYC, VerificationEntityType.VESSEL),
        (VerificationType.KYC, VerificationEntityType.EXPORTER),
    ],
)
def test_validate_type_pair_rejects_uninterpretable_combinations(
    verification_type, entity_type
):
    with pytest.raises(ValidationError) as excinfo:
        _validate_type_pair(verification_type, entity_type)
    # The message names both halves and lists what would have been valid, so
    # the caller can correct the request without reading the table.
    message = str(excinfo.value)
    assert verification_type.value in message
    assert entity_type.value in message
