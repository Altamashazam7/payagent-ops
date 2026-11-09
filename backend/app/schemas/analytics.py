"""Typed response and query contracts for dashboards and commerce workspaces."""

from datetime import date, datetime
from decimal import Decimal
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    AuditEntityType,
    DisputeStatus,
    InvoiceStatus,
    PayoutStatus,
)

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Bounded, offset-based page of typed records."""

    model_config = ConfigDict(extra="forbid")

    items: list[T]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class AmountByCurrency(BaseModel):
    """An amount bucket that must not be summed across currency codes."""

    model_config = ConfigDict(extra="forbid")

    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    amount: Decimal
    count: int = Field(ge=0)


class RevenueMetric(BaseModel):
    """Gross captured volume before refunds for one currency."""

    model_config = ConfigDict(extra="forbid")

    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    gross_volume: Decimal
    previous_gross_volume: Decimal
    transaction_count: int = Field(ge=0)
    average_ticket: Decimal
    change_percent: Decimal | None


class DisputeMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open_count: int = Field(ge=0)
    due_soon_count: int = Field(ge=0)
    overdue_count: int = Field(ge=0)
    open_exposure: list[AmountByCurrency]
    win_rate: Decimal | None = Field(default=None, ge=0, le=100)
    opened_last_30_days: int = Field(ge=0)
    opened_previous_30_days: int = Field(ge=0)


class InvoiceMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outstanding_count: int = Field(ge=0)
    overdue_count: int = Field(ge=0)
    outstanding_amount: list[AmountByCurrency]
    overdue_amount: list[AmountByCurrency]


class PayoutMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pending_approval_count: int = Field(ge=0)
    pending_approval_amount: list[AmountByCurrency]
    in_flight_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)


class RiskMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overdue_disputes: int = Field(ge=0)
    pending_decisions: int = Field(ge=0)
    manual_review_decisions: int = Field(ge=0)
    overdue_invoices: int = Field(ge=0)
    failed_payouts: int = Field(ge=0)


class VendorMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    active: int = Field(ge=0)
    pending: int = Field(ge=0)
    suspended: int = Field(ge=0)
    closed: int = Field(ge=0)


class AgentMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    active: int = Field(ge=0)
    paused: int = Field(ge=0)
    pending_decisions: int = Field(ge=0)


class DashboardSummary(BaseModel):
    """Tenant-scoped executive metrics for the trailing thirty-day period."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    period_start: datetime
    period_end: datetime
    revenue: list[RevenueMetric]
    disputes: DisputeMetrics
    invoices: InvoiceMetrics
    payouts: PayoutMetrics
    risk: RiskMetrics
    vendors: VendorMetrics
    agents: AgentMetrics


class RevenueTrendPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: date
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    gross_volume: Decimal
    transaction_count: int = Field(ge=0)


class DisputeTrendPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: date
    opened_count: int = Field(ge=0)


class DashboardTrends(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(ge=7, le=90)
    revenue: list[RevenueTrendPoint]
    disputes: list[DisputeTrendPoint]


class DisputeRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    vendor_id: UUID
    vendor_name: str
    transaction_id: UUID
    external_dispute_id: str
    reason: str
    status: DisputeStatus
    amount: Decimal
    currency: str
    response_due_at: datetime | None
    opened_at: datetime
    created_at: datetime
    updated_at: datetime


class InvoiceRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    vendor_id: UUID
    vendor_name: str
    invoice_number: str
    status: InvoiceStatus
    amount: Decimal
    currency: str
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PayoutRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    vendor_id: UUID
    vendor_name: str
    status: PayoutStatus
    amount: Decimal
    currency: str
    reference: str | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ActivityRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    vendor_id: UUID
    entity_type: AuditEntityType
    entity_id: UUID
    action: str
    actor_type: Literal["user", "agent", "system"]
    actor_name: str | None
    created_at: datetime


InsightCategory = Literal[
    "revenue_leakage",
    "dispute_trends",
    "vendor_performance",
    "cost_insights",
    "recommendation",
]
InsightSeverity = Literal["critical", "warning", "info"]


class ExecutiveInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: InsightCategory
    severity: InsightSeverity
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=1000)
    recommendation: str = Field(min_length=1, max_length=1000)
    evidence: list[str] = Field(min_length=1, max_length=10)


class CopilotOverview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    insights: list[ExecutiveInsight] = Field(max_length=100)


class CopilotQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=3, max_length=1000)


class CopilotAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=5000)
    generated_at: datetime
    sources: list[str] = Field(min_length=1, max_length=20)
