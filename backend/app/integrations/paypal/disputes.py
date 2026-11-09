"""Typed client for PayPal Disputes API operations."""

from __future__ import annotations

from urllib.parse import quote

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.integrations.paypal.approval import (
    HumanApprovalVerifier,
    SensitivePayPalAction,
    UnconfiguredHumanApprovalVerifier,
    require_human_approval,
)
from app.integrations.paypal.client import PayPalClient
from app.integrations.paypal.models import (
    DisputeEvidenceRequest,
    DisputeListResponse,
    DisputeResponse,
    HumanApproval,
    PayPalResourceId,
)


class DisputeListQuery(BaseModel):
    """Validated filter parameters for PayPal dispute listing."""

    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1, le=500)
    page_size: int = Field(default=10, ge=1, le=50)
    start_time: AwareDatetime | None = None
    end_time: AwareDatetime | None = None
    dispute_state: str | None = Field(default=None, min_length=1, max_length=64)

    def to_query_params(self) -> dict[str, str]:
        params = {
            "page": str(self.page),
            "page_size": str(self.page_size),
        }
        if self.start_time is not None:
            params["start_time"] = self.start_time.isoformat()
        if self.end_time is not None:
            params["end_time"] = self.end_time.isoformat()
        if self.dispute_state is not None:
            params["dispute_state"] = self.dispute_state
        return params


class DisputesClient:
    """Read disputes and submit evidence with explicit human authorization."""

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

    async def get_dispute(self, dispute_id: PayPalResourceId) -> DisputeResponse:
        """Fetch dispute details."""
        encoded_id = quote(dispute_id, safe="")
        return await self._client.request(
            "GET",
            f"/v1/customer/disputes/{encoded_id}",
            response_model=DisputeResponse,
        )

    async def list_disputes(
        self,
        query: DisputeListQuery | None = None,
    ) -> DisputeListResponse:
        """List disputes using bounded, validated query parameters."""
        return await self._client.request(
            "GET",
            "/v1/customer/disputes",
            response_model=DisputeListResponse,
            params=(query or DisputeListQuery()).to_query_params(),
        )

    async def provide_evidence(
        self,
        dispute_id: PayPalResourceId,
        request: DisputeEvidenceRequest,
        *,
        approval: HumanApproval,
    ) -> DisputeResponse:
        """Submit dispute evidence only with explicit human approval."""
        approval_record = require_human_approval(approval)
        await self._approval_verifier.verify(
            approval_record,
            action=SensitivePayPalAction.SUBMIT_DISPUTE_EVIDENCE,
        )
        encoded_id = quote(dispute_id, safe="")
        return await self._client.request(
            "POST",
            f"/v1/customer/disputes/{encoded_id}/provide-evidence",
            response_model=DisputeResponse,
            body=request,
        )
