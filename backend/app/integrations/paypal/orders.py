"""Typed client for PayPal Orders API operations."""

from __future__ import annotations

from urllib.parse import quote
from uuid import uuid4

from app.integrations.paypal.approval import (
    HumanApprovalVerifier,
    SensitivePayPalAction,
    UnconfiguredHumanApprovalVerifier,
    require_human_approval,
)
from app.integrations.paypal.client import PayPalClient
from app.integrations.paypal.models import (
    CreateOrderRequest,
    HumanApproval,
    OrderResponse,
    PayPalRequestId,
    PayPalResourceId,
)


class OrdersClient:
    """Create, inspect, and capture PayPal orders."""

    def __init__(
        self,
        client: PayPalClient,
        approval_verifier: HumanApprovalVerifier | None = None,
    ) -> None:
        self._client = client
        self._approval_verifier = (
            approval_verifier
            if approval_verifier is not None
            else UnconfiguredHumanApprovalVerifier()
        )

    async def create_order(
        self,
        request: CreateOrderRequest,
        *,
        request_id: PayPalRequestId | None = None,
    ) -> OrderResponse:
        """Create an order with a stable idempotency key for safe retries."""
        key = request_id or str(uuid4())
        return await self._client.request(
            "POST",
            "/v2/checkout/orders",
            response_model=OrderResponse,
            body=request,
            idempotency_key=key,
        )

    async def get_order(self, order_id: PayPalResourceId) -> OrderResponse:
        """Fetch one order without exposing arbitrary request paths."""
        encoded_id = quote(order_id, safe="")
        return await self._client.request(
            "GET",
            f"/v2/checkout/orders/{encoded_id}",
            response_model=OrderResponse,
        )

    async def capture_order(
        self,
        order_id: PayPalResourceId,
        *,
        approval: HumanApproval,
        request_id: PayPalRequestId | None = None,
    ) -> OrderResponse:
        """Capture an order only when the caller supplies human approval."""
        approval_record = require_human_approval(approval)
        await self._approval_verifier.verify(
            approval_record,
            action=SensitivePayPalAction.CAPTURE_ORDER,
        )
        encoded_id = quote(order_id, safe="")
        return await self._client.request(
            "POST",
            f"/v2/checkout/orders/{encoded_id}/capture",
            response_model=OrderResponse,
            idempotency_key=request_id or str(uuid4()),
        )
