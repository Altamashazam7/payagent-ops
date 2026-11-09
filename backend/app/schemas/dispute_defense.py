"""Validated contracts for dispute-defense agent inputs and evidence."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AnyUrl,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
)

from app.integrations.paypal.models import (
    DisputeEvidenceRequest,
    OrderResponse,
    PayPalMoney,
    PayPalResourceId,
    PayPalWebhookHeaders,
    WebhookEvent,
)
from app.models.enums import DisputeStatus, TransactionStatus, VendorStatus

EvidenceSummary = Annotated[str, Field(min_length=1, max_length=1000)]
PayPalEventId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._~-]+$",
    ),
]


class DisputeEventEnvelope(BaseModel):
    """Untrusted PayPal event and signature headers to verify before use."""

    model_config = ConfigDict(extra="forbid")

    headers: PayPalWebhookHeaders
    event: WebhookEvent

    def paypal_event_id(self) -> str:
        """Return a bounded event ID suitable for an audit request identifier."""
        return TypeAdapter(PayPalEventId).validate_python(self.event.id)

    def paypal_dispute_id(self) -> str:
        """Return the validated dispute ID from supported event resource shapes."""
        if self.event.event_type not in {
            "CUSTOMER.DISPUTE.CREATED",
            "CUSTOMER.DISPUTE.UPDATED",
        }:
            raise ValueError("Unsupported PayPal dispute event type")

        resource_id = self.event.resource.get("dispute_id")
        if resource_id is None:
            resource_id = self.event.resource.get("id")
        return TypeAdapter(PayPalResourceId).validate_python(resource_id)


class DisputeDecisionApproval(BaseModel):
    """Authenticated human approval request for a persisted decision."""

    model_config = ConfigDict(extra="forbid")

    decision_id: UUID
    reviewer_user_id: UUID


class ShippingEvidenceRecord(BaseModel):
    """Minimal, source-referenced shipping evidence from an injected provider."""

    model_config = ConfigDict(extra="forbid")

    source_reference: str = Field(min_length=1, max_length=256)
    tracking_number: str = Field(min_length=1, max_length=128)
    carrier: str | None = Field(default=None, max_length=64)
    delivery_status: Literal["delivered", "in_transit", "unknown"]
    delivered_at: AwareDatetime | None = None
    evidence_url: AnyUrl | None = None
    summary: EvidenceSummary


class CommunicationEvidenceRecord(BaseModel):
    """Redacted customer-communication metadata from an injected provider."""

    model_config = ConfigDict(extra="forbid")

    source_reference: str = Field(min_length=1, max_length=256)
    channel: Literal["email", "chat", "phone", "other"]
    occurred_at: AwareDatetime
    customer_acknowledged: bool = False
    summary: EvidenceSummary


class PayPalOrderPurchaseUnit(BaseModel):
    """Order unit fields needed to compare the provider order and transaction."""

    model_config = ConfigDict(extra="ignore")

    reference_id: str | None = None
    amount: PayPalMoney | None = None


class PayPalOrderSnapshot(BaseModel):
    """PII-minimized PayPal order details used by the evidence package."""

    model_config = ConfigDict(extra="ignore")

    id: str
    status: str
    intent: str | None = None
    purchase_units: list[PayPalOrderPurchaseUnit] = Field(default_factory=list)

    @classmethod
    def from_response(cls, response: OrderResponse) -> PayPalOrderSnapshot:
        """Keep only the order identifiers and purchase amounts needed for review."""
        units = [
            PayPalOrderPurchaseUnit.model_validate(unit)
            for unit in response.purchase_units
        ]
        return cls(
            id=response.id,
            status=response.status,
            intent=response.intent,
            purchase_units=units,
        )


class DisputeEvidencePackage(BaseModel):
    """Persistable, minimized evidence snapshot presented for human review."""

    model_config = ConfigDict(extra="forbid")

    dispute_id: UUID
    external_dispute_id: str
    dispute_reason: str
    dispute_status: DisputeStatus
    response_due_at: datetime | None
    vendor_id: UUID
    vendor_name: str
    vendor_status: VendorStatus
    transaction_id: UUID
    transaction_status: TransactionStatus
    transaction_amount: Decimal
    transaction_currency: str
    paypal_order: PayPalOrderSnapshot | None
    paypal_order_matches_transaction: bool
    shipping_evidence: list[ShippingEvidenceRecord] = Field(max_length=50)
    communication_history: list[CommunicationEvidenceRecord] = Field(max_length=50)
    paypal_evidence_request: DisputeEvidenceRequest | None


class DisputeSuccessProbability(BaseModel):
    """Transparent heuristic estimate; not a calibrated outcome prediction."""

    model_config = ConfigDict(extra="forbid")

    value: Decimal = Field(ge=0, le=1, max_digits=4, decimal_places=3)
    method: Literal["heuristic_not_calibrated"] = "heuristic_not_calibrated"
    basis: list[str] = Field(min_length=1, max_length=10)


class DisputeDefenseResult(BaseModel):
    """Workflow result returned while awaiting review or after submission."""

    model_config = ConfigDict(extra="forbid")

    workflow_status: Literal["awaiting_human_approval", "submitted"]
    decision_id: UUID
    dispute_id: UUID
    recommendation: Literal["submit_evidence", "manual_review"]
    success_probability: DisputeSuccessProbability
    narrative: str = Field(min_length=1, max_length=5000)
    paypal_submission_status: str | None = None
