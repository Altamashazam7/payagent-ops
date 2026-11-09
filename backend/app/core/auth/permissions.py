"""Role sets and dependencies for API-level authorization."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.core.auth.dependencies import get_current_user
from app.core.auth.jwt import UserContext
from app.models.enums import UserRole

REPORTING_ROLES = frozenset(UserRole)
COPILOT_ROLES = frozenset(
    {
        UserRole.ADMIN,
        UserRole.OPERATOR,
        UserRole.REVIEWER,
        UserRole.EXECUTIVE,
    }
)
APPROVER_ROLES = frozenset({UserRole.ADMIN, UserRole.OPERATOR, UserRole.REVIEWER})


def require_roles(*allowed_roles: UserRole) -> Callable[..., Awaitable[UserContext]]:
    """Build a FastAPI dependency that enforces one of the specified roles."""
    if not allowed_roles:
        raise ValueError("At least one role must be allowed")
    allowed = frozenset(allowed_roles)

    async def authorize(
        current_user: Annotated[UserContext, Depends(get_current_user)],
    ) -> UserContext:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your role does not allow this operation",
            )
        return current_user

    return authorize
