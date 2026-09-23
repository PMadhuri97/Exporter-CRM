"""Re-export of the shared role-granting test helpers — see
`app.platform.authentication.testing`."""

from app.platform.authentication.testing import (
    auth_header,
    token_with_role,
    user_with_role,
)

__all__ = ["auth_header", "token_with_role", "user_with_role"]
