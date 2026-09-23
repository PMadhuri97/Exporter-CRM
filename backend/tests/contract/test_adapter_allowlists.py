"""The two adapter registries' dotted-path allowlists must admit the same packages.

`kyb.domain.ports.ADAPTER_MODULE_ALLOWLIST` and
`onboarding.domain.workflow_dependencies.ADAPTER_MODULE_ALLOWLIST` are
deliberate copies — EXP-2 specifies the verification registry as a straight
copy of kyb's, and neither module may import the other's internals. Nothing but
this test stops one from being widened without the other.
"""

from __future__ import annotations

from app.modules.kyb.domain.ports import ADAPTER_MODULE_ALLOWLIST as KYB_ALLOWLIST
from app.modules.onboarding.domain.workflow_dependencies import (
    ADAPTER_MODULE_ALLOWLIST as VERIFICATION_ALLOWLIST,
)


def test_adapter_allowlists_have_not_drifted():
    assert set(KYB_ALLOWLIST) == set(VERIFICATION_ALLOWLIST)
