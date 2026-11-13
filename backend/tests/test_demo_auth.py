"""Development-only demo executive authentication tests."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.dependencies import get_current_user
from app.core.auth.jwt import OIDCJWTVerifier, UserContext
from app.core.settings import Settings
from app.demo_data.identity import (
    DEMO_AUTH_BEARER_TOKEN,
    DEMO_EXECUTIVE_EMAIL,
    DEMO_EXECUTIVE_ID,
    DEMO_OWNER_ID,
)
from app.models.enums import UserRole, UserStatus
from app.models.user import User


def _demo_users() -> dict[UUID, User]:
    owner = User(
        id=DEMO_OWNER_ID,
        email="demo-owner@payagent.invalid",
        display_name="PayAgent Demo Operator",
        role=UserRole.ADMIN,
        status=UserStatus.ACTIVE,
        deleted_at=None,
    )
    executive = User(
        id=DEMO_EXECUTIVE_ID,
        email=DEMO_EXECUTIVE_EMAIL,
        display_name="PayAgent Demo Executive",
        role=UserRole.EXECUTIVE,
        status=UserStatus.ACTIVE,
        deleted_at=None,
    )
    return {owner.id: owner, executive.id: executive}


@pytest.mark.asyncio
async def test_demo_bearer_authenticates_active_executive_in_development() -> None:
    settings = Settings(
        environment="development",
        demo_auth_enabled=True,
        database_url=SecretStr("sqlite+aiosqlite:///:memory:"),
    )
    users = _demo_users()
    session = cast(
        AsyncSession,
        SimpleNamespace(
            get=AsyncMock(side_effect=lambda _model, user_id: users.get(user_id))
        ),
    )
    async with httpx.AsyncClient() as http_client:
        verifier = OIDCJWTVerifier(settings, http_client)
        context = await get_current_user(
            credentials=HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials=DEMO_AUTH_BEARER_TOKEN,
            ),
            verifier=verifier,
            session=session,
            settings=settings,
        )

    assert context == UserContext(
        sub=DEMO_EXECUTIVE_ID,
        email=DEMO_EXECUTIVE_EMAIL,
        tenant_id=DEMO_OWNER_ID,
        role=UserRole.EXECUTIVE,
    )


@pytest.mark.asyncio
async def test_demo_bearer_is_not_accepted_when_disabled() -> None:
    settings = Settings(
        environment="test",
        database_url=SecretStr("sqlite+aiosqlite:///:memory:"),
    )
    async with httpx.AsyncClient() as http_client:
        verifier = OIDCJWTVerifier(settings, http_client)
        with pytest.raises(HTTPException) as error:
            await get_current_user(
                credentials=HTTPAuthorizationCredentials(
                    scheme="Bearer",
                    credentials=DEMO_AUTH_BEARER_TOKEN,
                ),
                verifier=verifier,
                session=cast(AsyncSession, object()),
                settings=settings,
            )

    assert error.value.status_code == 503
    assert error.value.detail == "OIDC authentication is not configured"
