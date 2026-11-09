"""Pydantic v2 input and ORM response schemas for commerce entities."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.core.types import JSONValue
from app.models.enums import (
    AgentStatus,
    AuditEntityType,
    DecisionStatus,
    DisputeStatus,
    InvoiceStatus,
    PayoutRecipientType,
    PayoutStatus,
    TransactionStatus,
    UserRole,
    UserStatus,
    VendorStatus,
)

EmailAddress = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]


def _normalize_currency(value: object) -> object:
    if isinstance(value, str):
        return value.strip().upper()
    return value


CurrencyCode = Annotated[
    str,
    BeforeValidator(_normalize_currency),
    StringConstraints(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    ),
]
PositiveAmount = Annotated[
    Decimal,
    Field(gt=0, max_digits=19, decimal_places=4),
]
Confidence = Annotated[
    Decimal,
    Field(ge=0, le=1, max_digits=4, decimal_places=3),
]


def _validate_paypal_payout_recipient(
    receiver: str | None,
    recipient_type: PayoutRecipientType | None,
) -> None:
    if (receiver is None) != (recipient_type is None):
        raise ValueError("PayPal receiver and recipient type must be provided together")
    if receiver is None:
        return
    if recipient_type is PayoutRecipientType.EMAIL:
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", receiver):
            raise ValueError("PayPal email recipient is invalid")
    elif recipient_type is PayoutRecipientType.PHONE:
        if not re.fullmatch(r"\+[1-9]\d{6,14}", receiver):
            raise ValueError("PayPal phone recipient must use E.164 format")
    elif not re.fullmatch(r"[A-Za-z0-9._~-]+", receiver):
        raise ValueError("PayPal ID recipient contains unsupported characters")


class DomainInputSchema(BaseModel):
    """Strict, whitespace-normalized input accepted by domain services."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DomainReadSchema(BaseModel):
    """ORM-backed response contract shared by commerce entities."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    created_at: datetime
    updated_at: datetime


class UserCreate(DomainInputSchema):
    email: EmailAddress
    display_name: str = Field(min_length=1, max_length=160)
    role: UserRole = UserRole.OPERATOR


class UserRead(DomainReadSchema):
    email: EmailAddress
    display_name: str
    role: UserRole
    status: UserStatus
    deleted_at: datetime | None
    deleted_by_user_id: UUID | None


class VendorCreate(DomainInputSchema):
    owner_user_id: UUID
    name: str = Field(min_length=1, max_length=160)
    paypal_merchant_id: str | None = Field(default=None, max_length=128)


class VendorRead(DomainReadSchema):
    owner_user_id: UUID
    name: str
    paypal_merchant_id: str | None
    status: VendorStatus
    deleted_at: datetime | None
    deleted_by_user_id: UUID | None


class TransactionCreate(DomainInputSchema):
    vendor_id: UUID
    created_by_user_id: UUID | None = None
    paypal_transaction_id: str | None = Field(default=None, max_length=128)
    paypal_order_id: str | None = Field(default=None, max_length=128)
    paypal_capture_id: str | None = Field(default=None, max_length=128)
    amount: PositiveAmount
    currency: CurrencyCode
    status: TransactionStatus = TransactionStatus.PENDING
    description: str | None = Field(default=None, max_length=500)
    occurred_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))


class TransactionRead(DomainReadSchema):
    vendor_id: UUID
    created_by_user_id: UUID | None
    paypal_transaction_id: str | None
    paypal_order_id: str | None
    paypal_capture_id: str | None
    amount: Decimal
    currency: CurrencyCode
    status: TransactionStatus
    description: str | None
    occurred_at: datetime


class DisputeCreate(DomainInputSchema):
    vendor_id: UUID
    transaction_id: UUID
    created_by_user_id: UUID | None = None
    external_dispute_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=120)
    amount: PositiveAmount
    currency: CurrencyCode
    response_due_at: AwareDatetime | None = None
    opened_at: AwareDatetime | None = None
    evidence_reference: str | None = Field(default=None, max_length=512)


class DisputeRead(DomainReadSchema):
    vendor_id: UUID
    transaction_id: UUID
    created_by_user_id: UUID | None
    external_dispute_id: str
    reason: str
    amount: Decimal
    currency: CurrencyCode
    status: DisputeStatus
    response_due_at: datetime | None
    opened_at: datetime
    resolved_at: datetime | None
    evidence_reference: str | None


class InvoiceCreate(DomainInputSchema):
    vendor_id: UUID
    transaction_id: UUID | None = None
    created_by_user_id: UUID | None = None
    invoice_number: str = Field(min_length=1, max_length=64)
    amount: PositiveAmount
    currency: CurrencyCode
    due_at: AwareDatetime | None = None
    description: str | None = Field(default=None, max_length=1000)
    billing_email: EmailAddress | None = None


class InvoiceRead(DomainReadSchema):
    vendor_id: UUID
    transaction_id: UUID | None
    created_by_user_id: UUID | None
    invoice_number: str
    amount: Decimal
    currency: CurrencyCode
    status: InvoiceStatus
    due_at: datetime | None
    paid_at: datetime | None
    description: str | None
    billing_email: EmailAddress | None


class PayoutCreate(DomainInputSchema):
    vendor_id: UUID
    requested_by_user_id: UUID
    amount: PositiveAmount
    currency: CurrencyCode
    reference: str | None = Field(default=None, max_length=256)
    paypal_receiver: str | None = Field(default=None, min_length=1, max_length=127)
    paypal_recipient_type: PayoutRecipientType | None = None

    @model_validator(mode="after")
    def validate_paypal_recipient(self) -> PayoutCreate:
        _validate_paypal_payout_recipient(
            self.paypal_receiver,
            self.paypal_recipient_type,
        )
        return self


class PayoutRead(DomainReadSchema):
    vendor_id: UUID
    requested_by_user_id: UUID
    approved_by_user_id: UUID | None
    paypal_batch_id: str | None
    amount: Decimal
    currency: CurrencyCode
    status: PayoutStatus
    approved_at: datetime | None
    paid_at: datetime | None
    reference: str | None
    paypal_receiver: str | None
    paypal_recipient_type: PayoutRecipientType | None

    @model_validator(mode="after")
    def validate_paypal_recipient(self) -> PayoutRead:
        _validate_paypal_payout_recipient(
            self.paypal_receiver,
            self.paypal_recipient_type,
        )
        return self


class AgentCreate(DomainInputSchema):
    vendor_id: UUID | None = None
    created_by_user_id: UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    agent_type: str = Field(min_length=1, max_length=80)
    model_name: str | None = Field(default=None, max_length=120)


class AgentRead(DomainReadSchema):
    vendor_id: UUID | None
    created_by_user_id: UUID | None
    name: str
    agent_type: str
    model_name: str | None
    status: AgentStatus
    deleted_at: datetime | None
    deleted_by_user_id: UUID | None


class DecisionCreate(DomainInputSchema):
    vendor_id: UUID
    agent_id: UUID | None = None
    transaction_id: UUID | None = None
    dispute_id: UUID | None = None
    invoice_id: UUID | None = None
    payout_id: UUID | None = None
    action_type: str = Field(min_length=1, max_length=100)
    recommendation: str = Field(min_length=1)
    rationale: str | None = None
    confidence: Confidence | None = None

    @model_validator(mode="after")
    def validate_single_subject(self) -> DecisionCreate:
        subjects = (
            self.transaction_id,
            self.dispute_id,
            self.invoice_id,
            self.payout_id,
        )
        if sum(subject is not None for subject in subjects) != 1:
            raise ValueError("A decision must reference exactly one commerce record")
        return self


class DecisionRead(DomainReadSchema):
    vendor_id: UUID
    agent_id: UUID | None
    reviewed_by_user_id: UUID | None
    transaction_id: UUID | None
    dispute_id: UUID | None
    invoice_id: UUID | None
    payout_id: UUID | None
    action_type: str
    recommendation: str
    rationale: str | None
    confidence: Decimal | None
    status: DecisionStatus
    reviewed_at: datetime | None


class AuditLogCreate(DomainInputSchema):
    entity_type: AuditEntityType
    entity_id: UUID
    vendor_id: UUID | None = None
    actor_user_id: UUID | None = None
    agent_id: UUID | None = None
    action: str = Field(min_length=1, max_length=120)
    before_state: dict[str, JSONValue] | None = None
    after_state: dict[str, JSONValue] | None = None
    request_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_single_actor(self) -> AuditLogCreate:
        if self.actor_user_id is not None and self.agent_id is not None:
            raise ValueError("An audit event cannot have both a user and agent actor")
        return self


class AuditLogRead(DomainReadSchema):
    entity_type: AuditEntityType
    entity_id: UUID
    vendor_id: UUID | None
    actor_user_id: UUID | None
    agent_id: UUID | None
    action: str
    before_state: dict[str, JSONValue] | None
    after_state: dict[str, JSONValue] | None
    request_id: str | None
