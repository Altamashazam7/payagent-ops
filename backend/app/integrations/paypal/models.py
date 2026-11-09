"""Typed request and response models for PayPal REST APIs."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AnyUrl,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.core.types import JSONValue

PayPalResourceId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._~-]+$",
    ),
]
PayPalRequestId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=38,
        pattern=r"^[A-Za-z0-9._~-]+$",
    ),
]
PayPalEmailAddress = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]
PayoutBatchId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=30,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]
PositiveMoneyValue = Annotated[
    Decimal,
    Field(gt=0, max_digits=19, decimal_places=4),
]


class PayPalRequestModel(BaseModel):
    """Request payload with PayPal snake-case JSON names and strict fields."""

    model_config = ConfigDict(extra="forbid")


class PayPalResponseModel(BaseModel):
    """Response payload tolerant of additive fields from PayPal."""

    model_config = ConfigDict(extra="allow")


class OAuthTokenResponse(PayPalResponseModel):
    access_token: str = Field(min_length=1)
    token_type: str = Field(min_length=1)
    expires_in: int = Field(gt=0)
    scope: str | None = None


class PayPalLink(PayPalResponseModel):
    href: AnyUrl
    rel: str
    method: str | None = None


class PayPalMoney(PayPalRequestModel):
    currency_code: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    value: PositiveMoneyValue


class HumanApproval(PayPalRequestModel):
    """Explicit persisted human-approval reference required for sensitive calls."""

    reviewer_user_id: UUID
    decision_id: UUID
    approved_at: AwareDatetime


class OrderPurchaseUnit(PayPalRequestModel):
    reference_id: str | None = Field(default=None, max_length=256)
    amount: PayPalMoney
    description: str | None = Field(default=None, max_length=127)
    custom_id: str | None = Field(default=None, max_length=127)
    invoice_id: str | None = Field(default=None, max_length=127)


class CreateOrderRequest(PayPalRequestModel):
    intent: Literal["CAPTURE", "AUTHORIZE"]
    purchase_units: list[OrderPurchaseUnit] = Field(min_length=1, max_length=10)


class OrderResponse(PayPalResponseModel):
    id: PayPalResourceId
    status: str
    intent: str | None = None
    purchase_units: list[dict[str, JSONValue]] = Field(default_factory=list)
    links: list[PayPalLink] = Field(default_factory=list)


class DisputeEvidence(PayPalRequestModel):
    evidence_type: str = Field(min_length=1, max_length=100)
    evidence_info: dict[str, JSONValue] | None = None
    notes: str | None = Field(default=None, max_length=2000)


class DisputeEvidenceRequest(PayPalRequestModel):
    evidence: list[DisputeEvidence] = Field(min_length=1, max_length=20)


class DisputeResponse(PayPalResponseModel):
    dispute_id: PayPalResourceId
    status: str
    reason: str | None = None
    dispute_amount: PayPalMoney | None = None
    links: list[PayPalLink] = Field(default_factory=list)


class DisputeListResponse(PayPalResponseModel):
    items: list[DisputeResponse] = Field(default_factory=list)
    links: list[PayPalLink] = Field(default_factory=list)
    total_items: int | None = Field(default=None, ge=0)
    total_pages: int | None = Field(default=None, ge=0)


class InvoiceDetail(PayPalRequestModel):
    invoice_number: str = Field(min_length=1, max_length=25)
    currency_code: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    note: str | None = Field(default=None, max_length=4000)
    terms_and_conditions: str | None = Field(default=None, max_length=4000)


class InvoiceItem(PayPalRequestModel):
    name: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=4)
    unit_amount: PayPalMoney
    description: str | None = Field(default=None, max_length=1000)


class InvoiceBillingInfo(PayPalRequestModel):
    email_address: PayPalEmailAddress
    given_name: str | None = Field(default=None, max_length=140)
    surname: str | None = Field(default=None, max_length=140)


class InvoiceRecipient(PayPalRequestModel):
    billing_info: InvoiceBillingInfo


class CreateInvoiceRequest(PayPalRequestModel):
    detail: InvoiceDetail
    primary_recipients: list[InvoiceRecipient] = Field(min_length=1, max_length=100)
    items: list[InvoiceItem] = Field(min_length=1, max_length=1000)


class InvoiceResponse(PayPalResponseModel):
    id: PayPalResourceId
    status: str
    detail: dict[str, JSONValue] | None = None
    links: list[PayPalLink] = Field(default_factory=list)


class InvoiceListResponse(PayPalResponseModel):
    items: list[InvoiceResponse] = Field(default_factory=list)
    links: list[PayPalLink] = Field(default_factory=list)
    total_items: int | None = Field(default=None, ge=0)
    total_pages: int | None = Field(default=None, ge=0)


class PayoutSenderBatchHeader(PayPalRequestModel):
    sender_batch_id: PayoutBatchId
    email_subject: str = Field(min_length=1, max_length=255)
    email_message: str | None = Field(default=None, max_length=1000)


class PayoutItem(PayPalRequestModel):
    recipient_type: Literal["EMAIL", "PHONE", "PAYPAL_ID"]
    amount: PayPalMoney
    receiver: str = Field(min_length=1, max_length=127)
    sender_item_id: str = Field(min_length=1, max_length=50)
    note: str | None = Field(default=None, max_length=1000)


class CreatePayoutBatchRequest(PayPalRequestModel):
    sender_batch_header: PayoutSenderBatchHeader
    items: list[PayoutItem] = Field(min_length=1, max_length=15000)


class PayoutBatchResponse(PayPalResponseModel):
    payout_batch_id: PayPalResourceId
    batch_status: str
    links: list[PayPalLink] = Field(default_factory=list)


class PayoutItemResponse(PayPalResponseModel):
    payout_item_id: PayPalResourceId
    transaction_status: str


class PayoutBatchDetailsResponse(PayPalResponseModel):
    batch_header: dict[str, JSONValue]
    items: list[PayoutItemResponse] = Field(default_factory=list)
    links: list[PayPalLink] = Field(default_factory=list)


class WebhookEvent(PayPalResponseModel):
    id: str
    event_type: str
    resource_type: str
    create_time: AwareDatetime | None = None
    resource: dict[str, JSONValue]


class PayPalWebhookHeaders(PayPalRequestModel):
    auth_algo: str = Field(min_length=1, max_length=128)
    cert_url: AnyUrl
    transmission_id: str = Field(min_length=1, max_length=128)
    transmission_sig: str = Field(min_length=1, max_length=4096)
    transmission_time: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def require_https_certificate_url(self) -> PayPalWebhookHeaders:
        if self.cert_url.scheme != "https":
            raise ValueError("PayPal certificate URL must use HTTPS")
        hostname = self.cert_url.host
        if hostname is None or not (
            hostname == "paypal.com" or hostname.endswith(".paypal.com")
        ):
            raise ValueError("PayPal certificate URL must use a PayPal domain")
        return self

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> PayPalWebhookHeaders:
        normalized = {key.lower(): value for key, value in headers.items()}
        header_names = {
            "auth_algo": "paypal-auth-algo",
            "cert_url": "paypal-cert-url",
            "transmission_id": "paypal-transmission-id",
            "transmission_sig": "paypal-transmission-sig",
            "transmission_time": "paypal-transmission-time",
        }
        missing = [name for name in header_names.values() if name not in normalized]
        if missing:
            raise ValueError(f"Missing PayPal webhook headers: {', '.join(missing)}")
        return cls.model_validate(
            {field: normalized[header] for field, header in header_names.items()}
        )


class VerifyWebhookSignatureRequest(PayPalRequestModel):
    auth_algo: str
    cert_url: AnyUrl
    transmission_id: str
    transmission_sig: str
    transmission_time: str
    webhook_id: str
    webhook_event: WebhookEvent


class WebhookVerificationResponse(PayPalResponseModel):
    verification_status: Literal["SUCCESS", "FAILURE"]


class PayPalErrorDetail(PayPalResponseModel):
    field: str | None = None
    value: str | None = None
    issue: str | None = None
    description: str | None = None


class PayPalErrorResponse(PayPalResponseModel):
    name: str | None = None
    error: str | None = None
    message: str | None = None
    error_description: str | None = None
    debug_id: str | None = None
    details: list[PayPalErrorDetail] = Field(default_factory=list)
