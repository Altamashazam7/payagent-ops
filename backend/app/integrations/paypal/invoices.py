"""Typed client for PayPal Invoicing API operations."""

from __future__ import annotations

from urllib.parse import quote
from uuid import uuid4

from app.integrations.paypal.client import PayPalClient
from app.integrations.paypal.models import (
    CreateInvoiceRequest,
    InvoiceListResponse,
    InvoiceResponse,
    PayPalRequestId,
    PayPalResourceId,
)


class InvoicesClient:
    """Create, inspect, list, and send PayPal invoices."""

    def __init__(self, client: PayPalClient) -> None:
        self._client = client

    async def create_invoice(
        self,
        request: CreateInvoiceRequest,
        *,
        request_id: PayPalRequestId | None = None,
    ) -> InvoiceResponse:
        """Create an invoice with an idempotency key for safe retries."""
        return await self._client.request(
            "POST",
            "/v2/invoicing/invoices",
            response_model=InvoiceResponse,
            body=request,
            idempotency_key=request_id or str(uuid4()),
        )

    async def get_invoice(self, invoice_id: PayPalResourceId) -> InvoiceResponse:
        """Fetch one PayPal invoice."""
        encoded_id = quote(invoice_id, safe="")
        return await self._client.request(
            "GET",
            f"/v2/invoicing/invoices/{encoded_id}",
            response_model=InvoiceResponse,
        )

    async def list_invoices(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> InvoiceListResponse:
        """List invoices with bounded pagination."""
        if page < 1:
            raise ValueError("page must be positive")
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        return await self._client.request(
            "GET",
            "/v2/invoicing/invoices",
            response_model=InvoiceListResponse,
            params={"page": str(page), "page_size": str(page_size)},
        )

    async def send_invoice(
        self,
        invoice_id: PayPalResourceId,
        *,
        request_id: PayPalRequestId | None = None,
    ) -> InvoiceResponse:
        """Send an existing invoice with a stable idempotency key."""
        encoded_id = quote(invoice_id, safe="")
        return await self._client.request(
            "POST",
            f"/v2/invoicing/invoices/{encoded_id}/send",
            response_model=InvoiceResponse,
            idempotency_key=request_id or str(uuid4()),
        )
