"""Centralized PayPal integration exceptions."""

from __future__ import annotations

from app.integrations.paypal.models import PayPalErrorDetail


class PayPalError(Exception):
    """Base exception for PayPal integration failures."""


class PayPalConfigurationError(PayPalError):
    """Raised when required environment configuration is missing or invalid."""


class PayPalApprovalRequiredError(PayPalError):
    """Raised when a sensitive PayPal action lacks a human-approval record."""


class PayPalAuthenticationError(PayPalError):
    """Raised when PayPal rejects OAuth client credentials."""

    def __init__(self, *, code: str | None, message: str | None) -> None:
        self.code = code
        self.message = message or "PayPal OAuth authentication failed"
        super().__init__(self.message)


class PayPalTransportError(PayPalError):
    """Raised when the PayPal endpoint cannot be reached after retries."""


class PayPalCircuitOpenError(PayPalError):
    """Raised while the PayPal circuit breaker is open."""

    def __init__(self, *, retry_after_seconds: float) -> None:
        self.retry_after_seconds = max(0.0, retry_after_seconds)
        super().__init__(
            f"PayPal circuit is open; retry after "
            f"{self.retry_after_seconds:.2f} seconds"
        )


class PayPalResponseError(PayPalError):
    """Raised when PayPal returns an invalid or unexpected response."""


class PayPalAPIError(PayPalError):
    """Raised for a non-success PayPal API response."""

    def __init__(
        self,
        *,
        status_code: int,
        name: str | None,
        message: str | None,
        debug_id: str | None,
        details: tuple[PayPalErrorDetail, ...] = (),
    ) -> None:
        self.status_code = status_code
        self.name = name
        self.message = message or "PayPal API request failed"
        self.debug_id = debug_id
        self.details = details
        super().__init__(self.message)


class PayPalTransientError(PayPalAPIError):
    """Raised for retryable rate-limit and server-side responses."""
