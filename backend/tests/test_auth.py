"""OIDC JWT verification and role authorization tests."""

import base64
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr, ValidationError

from app.core.auth.jwt import (
    JWTAuthenticationError,
    OIDCJWTVerifier,
    OIDCProviderUnavailableError,
)
from app.core.settings import Settings
from app.models.enums import UserRole

KEY_ID = "test-key-1"
ISSUER = "https://identity.example.test/"
AUDIENCE = "payagent-ops-api"


def _b64url(value: int) -> str:
    byte_count = (value.bit_length() + 7) // 8
    encoded = base64.urlsafe_b64encode(value.to_bytes(byte_count, "big"))
    return encoded.rstrip(b"=").decode("ascii")


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url=SecretStr("sqlite+aiosqlite:///:memory:"),
        oidc_issuer=ISSUER,
        oidc_audience=AUDIENCE,
        oidc_jwks_url=f"{ISSUER}.well-known/jwks.json",
        oidc_jwks_cache_seconds=30,
    )


def _claims(
    *,
    audience: str = AUDIENCE,
    role: UserRole = UserRole.REVIEWER,
    expires_at: datetime | None = None,
) -> dict[str, str | int]:
    now = datetime.now(UTC)
    return {
        "iss": ISSUER,
        "aud": audience,
        "sub": str(uuid4()),
        "email": "reviewer@example.test",
        "tenant_id": str(uuid4()),
        "role": role.value,
        "iat": int(now.timestamp()),
        "exp": int((expires_at or now + timedelta(minutes=5)).timestamp()),
    }


def _jwks(private_key: rsa.RSAPrivateKey) -> dict[str, list[dict[str, str]]]:
    public_key = private_key.public_key().public_numbers()
    return {
        "keys": [
            {
                "kid": KEY_ID,
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "n": _b64url(public_key.n),
                "e": _b64url(public_key.e),
            }
        ]
    }


def _token(
    private_key: rsa.RSAPrivateKey,
    claims: dict[str, str | int],
) -> str:
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": KEY_ID},
    )


async def test_oidc_verifier_validates_signature_and_injects_required_claims() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks = _jwks(private_key)
    requests = 0

    def handle(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json=jwks)

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handle),
        follow_redirects=False,
    )
    verifier = OIDCJWTVerifier(_settings(), http_client)
    token = _token(private_key, _claims(role=UserRole.REVIEWER))
    try:
        user = await verifier.verify(token)
        cached_user = await verifier.verify(token)
    finally:
        await http_client.aclose()

    assert user.sub
    assert user.email == "reviewer@example.test"
    assert user.tenant_id
    assert user.role is UserRole.REVIEWER
    assert cached_user == user
    assert requests == 1


@pytest.mark.parametrize(
    "claims",
    [
        _claims(audience="another-api"),
        _claims(expires_at=datetime.now(UTC) - timedelta(minutes=1)),
        {key: value for key, value in _claims().items() if key != "tenant_id"},
    ],
)
async def test_oidc_verifier_rejects_invalid_audience_expiry_and_missing_claims(
    claims: dict[str, str | int],
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=_jwks(private_key))
        )
    )
    verifier = OIDCJWTVerifier(_settings(), http_client)
    try:
        with pytest.raises(JWTAuthenticationError):
            await verifier.verify(_token(private_key, claims))
    finally:
        await http_client.aclose()


async def test_oidc_verifier_rejects_unknown_signing_key() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        _claims(),
        private_key,
        algorithm="RS256",
        headers={"kid": "unknown-key"},
    )
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=_jwks(private_key))
        )
    )
    verifier = OIDCJWTVerifier(_settings(), http_client)
    try:
        with pytest.raises(JWTAuthenticationError, match="unknown"):
            await verifier.verify(token)
    finally:
        await http_client.aclose()


async def test_oidc_verifier_reports_jwks_outage_without_accepting_token() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _token(private_key, _claims())
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(503, json={"error": "unavailable"})
        )
    )
    verifier = OIDCJWTVerifier(_settings(), http_client)
    try:
        with pytest.raises(OIDCProviderUnavailableError):
            await verifier.verify(token)
    finally:
        await http_client.aclose()


def test_settings_require_complete_https_oidc_configuration() -> None:
    with pytest.raises(ValidationError, match="configured together"):
        Settings(
            environment="test",
            database_url=SecretStr("sqlite+aiosqlite:///:memory:"),
            oidc_issuer=ISSUER,
        )

    with pytest.raises(ValidationError, match="must use HTTPS"):
        Settings(
            environment="test",
            database_url=SecretStr("sqlite+aiosqlite:///:memory:"),
            oidc_issuer="http://identity.example.test/",
            oidc_audience=AUDIENCE,
            oidc_jwks_url="https://identity.example.test/.well-known/jwks.json",
        )
