"""Typed client for PayPal Payouts API operations."""

from __future__ import annotations

from urllib.parse import quote

from app.integrations.paypal.approval import (
    HumanApprovalVerifier,
    SensitivePayPalAction,
    UnconfiguredHumanApprovalVerifier,
    require_human_approval,
)
from app.integrations.paypal.client import PayPalClient
from app.integrations.paypal.models import (
    CreatePayoutBatchRequest,
    HumanApproval,
    PayoutBatchDetailsResponse,
    PayoutBatchResponse,
    PayPalResourceId,
)


class PayoutsClient:
    """Create payout batches only after explicit human authorization."""

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

    async def create_payout_batch(
        self,
        request: CreatePayoutBatchRequest,
        *,
        approval: HumanApproval,
    ) -> PayoutBatchResponse:
        """Submit a payout batch with the PayPal batch idempotency key."""
        approval_record = require_human_approval(approval)
        await self._approval_verifier.verify(
            approval_record,
            action=SensitivePayPalAction.CREATE_PAYOUT_BATCH,
        )
        return await self._client.request(
            "POST",
            "/v1/payments/payouts",
            response_model=PayoutBatchResponse,
            body=request,
            idempotency_key=request.sender_batch_header.sender_batch_id,
        )

    async def get_payout_batch(
        self,
        payout_batch_id: PayPalResourceId,
    ) -> PayoutBatchDetailsResponse:
        """Fetch payout batch status and item results."""
        encoded_id = quote(payout_batch_id, safe="")
        return await self._client.request(
            "GET",
            f"/v1/payments/payouts/{encoded_id}",
            response_model=PayoutBatchDetailsResponse,
        )
