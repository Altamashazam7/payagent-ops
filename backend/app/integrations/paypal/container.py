"""Dependency-injection composition for PayPal API clients."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.settings import Settings
from app.integrations.paypal.approval import HumanApprovalVerifier
from app.integrations.paypal.auth import PayPalOAuthTokenManager
from app.integrations.paypal.circuit_breaker import CircuitBreaker
from app.integrations.paypal.client import PayPalClient
from app.integrations.paypal.disputes import DisputesClient
from app.integrations.paypal.invoices import InvoicesClient
from app.integrations.paypal.orders import OrdersClient
from app.integrations.paypal.payouts import PayoutsClient
from app.integrations.paypal.webhooks import WebhookVerificationClient


@dataclass(slots=True)
class PayPalClients:
    """Shared API clients built around one authenticated HTTP transport."""

    api: PayPalClient
    orders: OrdersClient
    disputes: DisputesClient
    invoices: InvoicesClient
    payouts: PayoutsClient
    webhooks: WebhookVerificationClient

    async def aclose(self) -> None:
        """Release the shared transport when the composition owns it."""
        await self.api.aclose()


def create_paypal_clients(
    settings: Settings,
    *,
    http_client: httpx.AsyncClient | None = None,
    token_manager: PayPalOAuthTokenManager | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    approval_verifier: HumanApprovalVerifier | None = None,
) -> PayPalClients:
    """Create the shared transport and injectable API-specific clients."""
    api = PayPalClient(
        settings,
        http_client=http_client,
        token_manager=token_manager,
        circuit_breaker=circuit_breaker,
    )
    return PayPalClients(
        api=api,
        orders=OrdersClient(api, approval_verifier),
        disputes=DisputesClient(api, approval_verifier),
        invoices=InvoicesClient(api),
        payouts=PayoutsClient(api, approval_verifier),
        webhooks=WebhookVerificationClient(api, settings),
    )
