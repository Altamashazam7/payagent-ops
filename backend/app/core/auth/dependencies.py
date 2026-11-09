"""FastAPI dependencies for OIDC user context injection."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.jwt import (
    JWTAuthenticationError,
    OIDCConfigurationError,
    OIDCJWTVerifier,
    OIDCProviderUnavailableError,
    UserContext,
)
from app.db.dependencies import get_session
from app.models.enums import UserStatus
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_jwt_verifier(request: Request) -> OIDCJWTVerifier:
    """Resolve the application-scoped OIDC verifier."""
    verifier = getattr(request.app.state, "jwt_verifier", None)
    if not isinstance(verifier, OIDCJWTVerifier):
        raise TypeError("OIDC JWT verifier is not configured")
    return verifier


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    verifier: Annotated[OIDCJWTVerifier, Depends(get_jwt_verifier)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserContext:
    """Verify the bearer token and bind its claims to active local accounts."""
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer authentication is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        context = await verifier.verify(credentials.credentials)
    except JWTAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token is invalid",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except OIDCConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC authentication is not configured",
        ) from exc
    except OIDCProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC authentication provider is unavailable",
        ) from exc

    user = await session.get(User, context.sub)
    tenant = await session.get(User, context.tenant_id)
    if (
        user is None
        or user.deleted_at is not None
        or user.status is not UserStatus.ACTIVE
        or user.email.casefold() != context.email
        or user.role is not context.role
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer identity is not an active local user",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if (
        tenant is None
        or tenant.deleted_at is not None
        or tenant.status is not UserStatus.ACTIVE
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The requested tenant is unavailable",
        )
    return context
