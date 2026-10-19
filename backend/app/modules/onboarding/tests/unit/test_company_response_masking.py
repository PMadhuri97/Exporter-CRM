"""What a company response carries, per the viewer's permissions.

Two separate permissions decide two separate things: `exporters:view_full_tax_id`
unmasks the tax identifiers, and `compliance:view` carries the background-check state.
They are independent, so every combination has to be checked — a role holding one and
not the other is ordinary, not a contradiction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.modules.onboarding.api.schemas.exporter import ExporterProfileListItemResponse
from app.modules.onboarding.domain.entities.background_check_enums import BackgroundCheckState
from app.platform.authentication.models import User, UserRole
from app.platform.authorization.services import remember_permissions

REVEAL = ("exporters", "view_full_tax_id")
COMPLIANCE_VIEW = ("compliance", "view")


def _viewer(*permissions: tuple[str, str]) -> User:
    user = User(
        id=uuid.uuid4(),
        email="viewer@aner.example",
        full_name="A Viewer",
        role=UserRole.OPERATIONS,
        is_active=True,
    )
    remember_permissions(user, frozenset(permissions))
    return user


def _row() -> ExporterProfileListItemResponse:
    now = datetime.now(UTC)
    return ExporterProfileListItemResponse.model_validate(
        {
            "customer_id": uuid.uuid4(),
            "name": "Acme Exports",
            "country": "IN",
            "gstins": ["27ABCDE1234F1Z5"],
            "cin": None,
            "pan": "ABCDE1234F",
            "iec": "1234567890",
            "source": "MANUAL",
            "relationship_manager": None,
            "relationship_manager_user_id": None,
            "journey": "LEAD",
            "qualification": "NOT_YET_REVIEWED",
            "marker": "NONE",
            "marker_reason": None,
            "industry": None,
            "background_check": BackgroundCheckState.FLAGGED,
            "year_established": None,
            "registration_number": None,
            "identity_type": None,
            "pipeline_status": "IN_PIPELINE",
            "date_added": now,
            "created_at": now,
            "updated_at": now,
        }
    )


@pytest.mark.parametrize(
    ("permissions", "sees_pan", "sees_check"),
    [
        pytest.param((), False, False, id="neither"),
        pytest.param((COMPLIANCE_VIEW,), False, True, id="compliance-view-only"),
        # The case this file exists for: unmasking tax identifiers said nothing about
        # compliance work, but the state was carried anyway because the identifier
        # check returned before the blanking ran.
        pytest.param((REVEAL,), True, False, id="tax-ids-without-compliance"),
        pytest.param((REVEAL, COMPLIANCE_VIEW), True, True, id="both"),
    ],
)
def test_each_permission_decides_only_its_own_field(
    permissions: tuple[tuple[str, str], ...], sees_pan: bool, sees_check: bool
) -> None:
    masked = _row().masked_for(_viewer(*permissions))

    assert (masked.pan == "ABCDE1234F") is sees_pan
    if not sees_pan:
        assert masked.pan is not None and masked.pan.endswith("234F")
    assert (masked.background_check is BackgroundCheckState.FLAGGED) is sees_check
    if not sees_check:
        assert masked.background_check is None


def test_masking_does_not_change_the_row_it_was_given() -> None:
    """`masked_for` returns a copy. A caller holding the original must not find the
    identifiers it was given replaced by bullets."""
    row = _row()
    row.masked_for(_viewer())
    assert row.pan == "ABCDE1234F"
    assert row.background_check is BackgroundCheckState.FLAGGED
