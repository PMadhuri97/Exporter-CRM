"""Storage implementations — **owner: Developer 3B** (L3-07, L3-08).

Replaces the empty ``app/integrations/object_storage`` scaffold (audit note E34):
one storage implementation, behind ``onboarding/domain/storage.py``'s port, in the
module that owns the documents it stores.

``LocalDiskStorage`` is the prototype's only implementation. An S3 one (Object
Lock, KMS — decision D8, gate §7.6) lands here beside it, satisfying the same
port, and local disk stays for development and tests.
"""

from app.modules.onboarding.infrastructure.storage.local_disk import (
    LocalDiskStorage,
    sign_key,
    verify_signed_key,
)
from app.modules.onboarding.infrastructure.storage.passthrough_scanner import (
    PASS_THROUGH_SCANNER_NAME,
    PassThroughScanner,
)

__all__ = [
    "PASS_THROUGH_SCANNER_NAME",
    "LocalDiskStorage",
    "PassThroughScanner",
    "sign_key",
    "verify_signed_key",
]
