"""Async PayPal OAuth client-credentials token management."""

from __future__ import annotations

import asyncio
import logging
from time import monotonic

import httpx
from pydantic import ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.settings import Settings
from app.integrations.paypal.errors import (
    PayPalAPIError,
    PayPalAuthenticationError,
    PayPalConfigurationError,
    PayPalResponseError,
    PayPalTransientError,
    PayPalTransportError,
)
from app.integrations.paypal.models import OAuthTokenResponse, PayPalErrorResponse

logger = logging.getLogger("payagent_ops")
TOKEN_EXPIRY_SKEW_SECONDS = 60


class PayPalOAuthTokenManager:
    """Cache OAuth access tokens and serialize concurrent refresh attempts."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: Settings,
    ) -> None:
        self._http_client = http_client
        self._settings = settings
        self._access_token: str | None = None
        self._expires_at = 0.0
        self._refresh_lock = asyncio.Lock()

    async def get_access_token(self) -> str:
        """Return a cached token or fetch a fresh token from PayPal."""
        token = self._access_token
        if token is not None and monotonic() < self._expires_at:
            return token

        async with self._refresh_lock:
            token = self._access_token
            if token is not None and monotonic() < self._expires_at:
                return token

            client_id_secret = self._settings.paypal_client_id
            client_secret_secret = self._settings.paypal_client_secret
            client_id = (
                client_id_secret.get_secret_value()
                if client_id_secret is not None
                else ""
            )
            client_secret = (
                client_secret_secret.get_secret_value()
                if client_secret_secret is not None
                else ""
            )
            if not client_id or not client_secret:
                raise PayPalConfigurationError(
                    "PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET are required"
                )

            try:
                retrying = AsyncRetrying(
                    retry=retry_if_exception_type(
                        (httpx.TransportError, PayPalTransientError)
                    ),
                    stop=stop_after_attempt(self._settings.paypal_retry_attempts),
                    wait=wait_exponential(
                        multiplier=1,
                        min=self._settings.paypal_retry_min_wait_seconds,
                        max=self._settings.paypal_retry_max_wait_seconds,
                    ),
                    reraise=True,
                )
                response: OAuthTokenResponse = await retrying(
                    self._request_token,
                    client_id,
                    client_secret,
                )
            except httpx.TransportError as exc:
                logger.error(
                    "PayPal OAuth endpoint unavailable",
                    extra={
                        "event": "paypal_oauth_unavailable",
                        "provider": "paypal",
                        "operation": "oauth_token",
                    },
                )
                raise PayPalTransportError(
                    "PayPal OAuth endpoint is unavailable"
                ) from exc

            lifetime = max(
                response.expires_in - TOKEN_EXPIRY_SKEW_SECONDS,
                1,
            )
            self._access_token = response.access_token
            self._expires_at = monotonic() + lifetime
            logger.info(
                "PayPal OAuth token refreshed",
                extra={
                    "event": "paypal_oauth_token_refreshed",
                    "provider": "paypal",
                    "operation": "oauth_token",
                    "status_code": 200,
                },
            )
            return response.access_token

    async def invalidate(self) -> None:
        """Clear the cached token so the next request obtains a fresh one."""
        async with self._refresh_lock:
            self._access_token = None
            self._expires_at = 0.0

    async def _request_token(
        self,
        client_id: str,
        client_secret: str,
    ) -> OAuthTokenResponse:
        response = await self._http_client.post(
            "/v1/oauth2/token",
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
        )
        if response.status_code == 429 or response.status_code >= 500:
            raise self._api_error(response, transient=True)
        if not response.is_success:
            error = self._parse_error_response(response)
            raise PayPalAuthenticationError(
                code=error.name or error.error,
                message=error.message or error.error_description,
            )
        try:
            return OAuthTokenResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise PayPalResponseError(
                "PayPal returned an invalid OAuth token response"
            ) from exc

    @staticmethod
    def _parse_error_response(response: httpx.Response) -> PayPalErrorResponse:
        try:
            return PayPalErrorResponse.model_validate(response.json())
        except (ValueError, ValidationError):
            return PayPalErrorResponse()

    @classmethod
    def _api_error(
        cls,
        response: httpx.Response,
        *,
        transient: bool,
    ) -> PayPalAPIError:
        error = cls._parse_error_response(response)
        error_type = PayPalTransientError if transient else PayPalAPIError
        return error_type(
            status_code=response.status_code,
            name=error.name or error.error,
            message=error.message or error.error_description,
            debug_id=error.debug_id,
            details=tuple(error.details),
        )
