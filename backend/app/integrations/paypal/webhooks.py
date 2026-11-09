"""PayPal webhook signature verification client."""

from app.core.settings import Settings
from app.integrations.paypal.client import PayPalClient
from app.integrations.paypal.errors import PayPalConfigurationError
from app.integrations.paypal.models import (
    PayPalWebhookHeaders,
    VerifyWebhookSignatureRequest,
    WebhookEvent,
    WebhookVerificationResponse,
)


class WebhookVerificationClient:
    """Verify incoming webhook signatures through PayPal's verification API."""

    def __init__(self, client: PayPalClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    async def verify(
        self,
        headers: PayPalWebhookHeaders,
        event: WebhookEvent,
    ) -> WebhookVerificationResponse:
        """Return PayPal's verification result; callers must fail closed."""
        webhook_id = self._settings.paypal_webhook_id
        if not webhook_id:
            raise PayPalConfigurationError("PAYPAL_WEBHOOK_ID is required")
        request = VerifyWebhookSignatureRequest(
            auth_algo=headers.auth_algo,
            cert_url=headers.cert_url,
            transmission_id=headers.transmission_id,
            transmission_sig=headers.transmission_sig,
            transmission_time=headers.transmission_time,
            webhook_id=webhook_id,
            webhook_event=event,
        )
        return await self._client.request(
            "POST",
            "/v1/notifications/verify-webhook-signature",
            response_model=WebhookVerificationResponse,
            body=request,
            retry_safe=True,
        )
