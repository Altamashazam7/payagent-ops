"""Asynchronous OIDC JWKS lookup and strict JWT verification."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from time import monotonic
from typing import Literal
from uuid import UUID

import httpx
import jwt
from jwt import PyJWK
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.settings import Settings
from app.models.enums import UserRole

logger = logging.getLogger("payagent_ops")
SUPPORTED_JWT_ALGORITHM = "RS256"


class JWTAuthenticationError(Exception):
    """A JWT failed signature, issuer, audience, claim, or expiry validation."""


class OIDCConfigurationError(Exception):
    """OIDC verifier settings are incomplete or invalid."""


class OIDCProviderUnavailableError(Exception):
    """The configured OIDC JWKS endpoint could not be reached or parsed."""


@dataclass(frozen=True, slots=True)
class UserContext:
    """Authenticated identity and authorization claims from a verified token."""

    sub: UUID
    email: str
    tenant_id: UUID
    role: UserRole


class _OIDCClaims(BaseModel):
    model_config = ConfigDict(extra="allow")

    sub: UUID
    email: str = Field(
        min_length=3,
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    tenant_id: UUID
    role: UserRole
    exp: int
    iat: int


class _RSAJWK(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kid: str = Field(min_length=1, max_length=256)
    kty: Literal["RSA"]
    use: Literal["sig"] | None = None
    alg: Literal["RS256"] | None = None
    n: str = Field(min_length=1)
    e: str = Field(min_length=1)


class _JWKSResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    keys: list[_RSAJWK] = Field(min_length=1, max_length=100)


class OIDCJWTVerifier:
    """Verify access tokens using cached RSA keys from the configured OIDC issuer."""

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._issuer = settings.oidc_issuer
        self._audience = settings.oidc_audience
        self._jwks_url = settings.oidc_jwks_url
        self._cache_seconds = settings.oidc_jwks_cache_seconds
        self._clock_skew_seconds = settings.oidc_clock_skew_seconds
        self._http_client = http_client
        self._keys: dict[str, PyJWK] = {}
        self._loaded_at = 0.0
        self._refresh_lock = asyncio.Lock()

    async def verify(self, token: str) -> UserContext:
        """Validate a bearer token and return only its required trusted claims."""
        if not self._issuer or not self._audience or not self._jwks_url:
            raise OIDCConfigurationError("OIDC verifier is not configured")
        if not token or len(token) > 16_384:
            raise JWTAuthenticationError("Bearer token is invalid")

        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise JWTAuthenticationError("Bearer token is invalid") from exc

        key_id = header.get("kid")
        if header.get("alg") != SUPPORTED_JWT_ALGORITHM or not isinstance(key_id, str):
            raise JWTAuthenticationError("Bearer token uses an unsupported key")

        signing_key = await self._get_signing_key(key_id)
        try:
            raw_claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=[SUPPORTED_JWT_ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._clock_skew_seconds,
                options={
                    "require": ["exp", "iat", "sub", "email", "tenant_id", "role"],
                },
            )
            claims = _OIDCClaims.model_validate(raw_claims)
        except (jwt.InvalidTokenError, ValidationError, TypeError, ValueError) as exc:
            raise JWTAuthenticationError("Bearer token claims are invalid") from exc

        return UserContext(
            sub=claims.sub,
            email=claims.email.casefold(),
            tenant_id=claims.tenant_id,
            role=claims.role,
        )

    async def _get_signing_key(self, key_id: str) -> PyJWK:
        if monotonic() - self._loaded_at >= self._cache_seconds:
            await self._refresh_keys()
        key = self._keys.get(key_id)
        if key is None:
            await self._refresh_keys(force=True)
            key = self._keys.get(key_id)
        if key is None:
            raise JWTAuthenticationError("Bearer token signing key is unknown")
        return key

    async def _refresh_keys(self, *, force: bool = False) -> None:
        async with self._refresh_lock:
            if not force and monotonic() - self._loaded_at < self._cache_seconds:
                return
            jwks_url = self._jwks_url
            if jwks_url is None:
                raise OIDCConfigurationError("OIDC_JWKS_URL is not configured")
            try:
                response = await self._http_client.get(jwks_url)
                response.raise_for_status()
                jwks = _JWKSResponse.model_validate(response.json())
                keys: dict[str, PyJWK] = {}
                for jwk in jwks.keys:
                    if jwk.use not in (None, "sig") or jwk.alg not in (
                        None,
                        SUPPORTED_JWT_ALGORITHM,
                    ):
                        continue
                    if jwk.kid in keys:
                        raise OIDCProviderUnavailableError(
                            "OIDC JWKS contains duplicate key identifiers"
                        )
                    keys[jwk.kid] = PyJWK.from_dict(
                        jwk.model_dump(exclude_none=True),
                        algorithm=SUPPORTED_JWT_ALGORITHM,
                    )
                if not keys:
                    raise OIDCProviderUnavailableError(
                        "OIDC JWKS has no supported signing keys"
                    )
            except OIDCProviderUnavailableError:
                raise
            except (
                httpx.HTTPError,
                ValidationError,
                jwt.PyJWTError,
                ValueError,
            ) as exc:
                logger.warning(
                    "OIDC signing keys could not be refreshed",
                    extra={
                        "event": "oidc_jwks_refresh_failed",
                        "dependency": "oidc_provider",
                    },
                )
                raise OIDCProviderUnavailableError(
                    "OIDC signing keys are unavailable"
                ) from exc
            self._keys = keys
            self._loaded_at = monotonic()
