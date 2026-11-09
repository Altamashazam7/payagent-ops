"""PayPal REST API integration clients and typed contracts."""

from app.integrations.paypal.approval import (
    HumanApprovalVerifier,
    SensitivePayPalAction,
    UnconfiguredHumanApprovalVerifier,
)
from app.integrations.paypal.auth import PayPalOAuthTokenManager
from app.integrations.paypal.circuit_breaker import CircuitBreaker, CircuitState
from app.integrations.paypal.client import PayPalClient
from app.integrations.paypal.container import PayPalClients, create_paypal_clients
from app.integrations.paypal.disputes import DisputeListQuery, DisputesClient
from app.integrations.paypal.errors import (
    PayPalAPIError,
    PayPalApprovalRequiredError,
    PayPalAuthenticationError,
    PayPalCircuitOpenError,
    PayPalConfigurationError,
    PayPalError,
    PayPalResponseError,
    PayPalTransientError,
    PayPalTransportError,
)
from app.integrations.paypal.invoices import InvoicesClient
from app.integrations.paypal.models import (
    CreateInvoiceRequest,
    CreateOrderRequest,
    CreatePayoutBatchRequest,
    DisputeEvidence,
    DisputeEvidenceRequest,
    HumanApproval,
    InvoiceResponse,
    OrderResponse,
    PayoutBatchId,
    PayoutBatchResponse,
    PayPalEmailAddress,
    PayPalMoney,
    PayPalRequestId,
    PayPalResourceId,
    PayPalWebhookHeaders,
    WebhookEvent,
    WebhookVerificationResponse,
)
from app.integrations.paypal.orders import OrdersClient
from app.integrations.paypal.payouts import PayoutsClient
from app.integrations.paypal.webhooks import WebhookVerificationClient

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "CreateInvoiceRequest",
    "CreateOrderRequest",
    "CreatePayoutBatchRequest",
    "DisputeEvidence",
    "DisputeEvidenceRequest",
    "DisputeListQuery",
    "DisputesClient",
    "HumanApproval",
    "HumanApprovalVerifier",
    "InvoiceResponse",
    "InvoicesClient",
    "OrderResponse",
    "OrdersClient",
    "PayPalAPIError",
    "PayPalApprovalRequiredError",
    "PayPalAuthenticationError",
    "PayPalCircuitOpenError",
    "PayPalClient",
    "PayPalClients",
    "PayPalConfigurationError",
    "PayPalEmailAddress",
    "PayPalError",
    "PayPalMoney",
    "PayPalOAuthTokenManager",
    "PayPalRequestId",
    "PayPalResourceId",
    "PayPalResponseError",
    "PayPalTransientError",
    "PayPalTransportError",
    "PayPalWebhookHeaders",
    "PayoutBatchId",
    "PayoutBatchResponse",
    "PayoutsClient",
    "SensitivePayPalAction",
    "UnconfiguredHumanApprovalVerifier",
    "WebhookEvent",
    "WebhookVerificationClient",
    "WebhookVerificationResponse",
    "create_paypal_clients",
]
