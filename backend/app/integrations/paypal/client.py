"""Shared async HTTP client with OAuth, retries, logging, and circuit protection."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    retry_never,
    stop_after_attempt,
    wait_exponential,
)

from app.core.settings import Settings
from app.integrations.paypal.auth import PayPalOAuthTokenManager
from app.integrations.paypal.circuit_breaker import CircuitBreaker
from app.integrations.paypal.errors import (
    PayPalAPIError,
    PayPalError,
    PayPalResponseError,
    PayPalTransientError,
    PayPalTransportError,
)
from app.integrations.paypal.models import PayPalErrorResponse

logger = logging.getLogger("payagent_ops")
ResponseT = TypeVar("ResponseT", bound=BaseModel)
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{1,38}$")


class PayPalClient:
    """Make authenticated PayPal requests using an injectable async transport."""

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
        token_manager: PayPalOAuthTokenManager | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self._settings = settings
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(
            base_url=settings.paypal_api_base_url,
            timeout=httpx.Timeout(settings.paypal_timeout_seconds),
        )
        self._token_manager = token_manager or PayPalOAuthTokenManager(
            self._http_client,
            settings,
        )
        self._circuit_breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=settings.paypal_circuit_breaker_failure_threshold,
            reset_timeout=settings.paypal_circuit_breaker_reset_seconds,
        )

    async def aclose(self) -> None:
        """Close the HTTP transport only when this client created it."""
        if self._owns_http_client:
            await self._http_client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        response_model: type[ResponseT],
        body: BaseModel | None = None,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
        retry_safe: bool = False,
    ) -> ResponseT:
        """Send a typed request and convert transport/API failures consistently."""
        self._validate_path(path)
        http_method = method.strip().upper()
        if http_method not in {
            "DELETE",
            "GET",
            "HEAD",
            "OPTIONS",
            "PATCH",
            "POST",
            "PUT",
        }:
            raise ValueError("Unsupported HTTP method")
        if idempotency_key is not None and not IDEMPOTENCY_KEY_PATTERN.fullmatch(
            idempotency_key
        ):
            raise ValueError("idempotency_key must use 1-38 safe PayPal characters")
        if headers is not None and any(
            name.lower() == "authorization" for name in headers
        ):
            raise ValueError("Authorization is managed by PayPalClient")

        operation = self._operation(path)
        await self._circuit_breaker.before_call()
        try:
            access_token = await self._token_manager.get_access_token()
            request_headers = self._build_headers(
                access_token,
                headers,
                idempotency_key,
            )
            retry_enabled = (
                retry_safe
                or http_method in {"GET", "HEAD", "OPTIONS"}
                or idempotency_key is not None
            )
            retrying = AsyncRetrying(
                retry=(
                    retry_if_exception_type(
                        (httpx.TransportError, PayPalTransientError)
                    )
                    if retry_enabled
                    else retry_never
                ),
                stop=stop_after_attempt(self._settings.paypal_retry_attempts),
                wait=wait_exponential(
                    multiplier=1,
                    min=self._settings.paypal_retry_min_wait_seconds,
                    max=self._settings.paypal_retry_max_wait_seconds,
                ),
                reraise=True,
            )
            response: httpx.Response = await retrying(
                self._send,
                http_method,
                path,
                request_headers,
                body,
                params,
            )
        except asyncio.CancelledError:
            await self._circuit_breaker.record_failure()
            raise
        except PayPalTransientError as exc:
            await self._circuit_breaker.record_failure()
            self._log_failure(
                operation=operation,
                http_method=http_method,
                status_code=exc.status_code,
                error_code=exc.name,
            )
            raise
        except PayPalTransportError:
            await self._circuit_breaker.record_failure()
            logger.error(
                "PayPal transport failed",
                extra={
                    "event": "paypal_transport_failed",
                    "provider": "paypal",
                    "operation": operation,
                    "http_method": http_method,
                },
            )
            raise
        except httpx.TransportError as exc:
            await self._circuit_breaker.record_failure()
            logger.error(
                "PayPal transport failed",
                extra={
                    "event": "paypal_transport_failed",
                    "provider": "paypal",
                    "operation": operation,
                    "http_method": http_method,
                },
            )
            raise PayPalTransportError(
                "PayPal request failed after retry attempts"
            ) from exc
        except PayPalAPIError as exc:
            await self._circuit_breaker.record_success()
            self._log_failure(
                operation=operation,
                http_method=http_method,
                status_code=exc.status_code,
                error_code=exc.name,
            )
            raise
        except PayPalError:
            await self._circuit_breaker.record_success()
            raise

        await self._circuit_breaker.record_success()
        logger.info(
            "PayPal request completed",
            extra={
                "event": "paypal_request_completed",
                "provider": "paypal",
                "operation": operation,
                "http_method": http_method,
                "status_code": response.status_code,
            },
        )
        try:
            return response_model.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise PayPalResponseError("PayPal returned an invalid response") from exc

    async def _send(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: BaseModel | None,
        params: Mapping[str, str] | None,
    ) -> httpx.Response:
        response = await self._http_client.request(
            method,
            path,
            headers=headers,
            json=(
                body.model_dump(mode="json", by_alias=True, exclude_none=True)
                if body is not None
                else None
            ),
            params=params,
        )
        if not response.is_success:
            error = self._parse_error_response(response)
            error_type = (
                PayPalTransientError
                if response.status_code in {408, 429} or response.status_code >= 500
                else PayPalAPIError
            )
            raise error_type(
                status_code=response.status_code,
                name=error.name or error.error,
                message=error.message or error.error_description,
                debug_id=error.debug_id,
                details=tuple(error.details),
            )
        return response

    @staticmethod
    def _parse_error_response(response: httpx.Response) -> PayPalErrorResponse:
        try:
            return PayPalErrorResponse.model_validate(response.json())
        except (ValueError, ValidationError):
            return PayPalErrorResponse()

    @staticmethod
    def _build_headers(
        access_token: str,
        headers: Mapping[str, str] | None,
        idempotency_key: str | None,
    ) -> dict[str, str]:
        result = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        if headers is not None:
            for name, value in headers.items():
                if name.lower() == "authorization":
                    raise ValueError("Authorization is managed by PayPalClient")
                result[name] = value
        if idempotency_key is not None:
            result["PayPal-Request-Id"] = idempotency_key
        return result

    @staticmethod
    def _validate_path(path: str) -> None:
        if (
            not path.startswith("/")
            or path.startswith("//")
            or "://" in path
            or "?" in path
            or "#" in path
            or "//" in path
            or "\r" in path
            or "\n" in path
            or any(segment in {".", ".."} for segment in path.split("/"))
        ):
            raise ValueError("PayPal request path must be a safe absolute API path")

    @staticmethod
    def _operation(path: str) -> str:
        parts = path.split("?", maxsplit=1)[0].strip("/").split("/")
        return ".".join(parts[:3])

    @staticmethod
    def _log_failure(
        *,
        operation: str,
        http_method: str,
        status_code: int,
        error_code: str | None,
    ) -> None:
        logger.warning(
            "PayPal API request failed",
            extra={
                "event": "paypal_api_failed",
                "provider": "paypal",
                "operation": operation,
                "http_method": http_method,
                "status_code": status_code,
                "error_code": error_code or "unknown",
            },
        )
