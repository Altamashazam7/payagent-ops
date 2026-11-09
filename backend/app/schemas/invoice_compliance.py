"""Validated assessment and approval schemas for invoice compliance review."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

InvoiceFindingSeverity = Literal["low", "medium", "high"]
InvoiceRecommendation = Literal["approve_invoice", "manual_review"]


class InvoiceComplianceFinding(BaseModel):
    """A rule-based invoice issue suitable for human review."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=80)
    severity: InvoiceFindingSeverity
    message: str = Field(min_length=1, max_length=500)


class InvoiceComplianceAssessment(BaseModel):
    """Explainable invoice checks; score is completeness, not a prediction."""

    model_config = ConfigDict(extra="forbid")

    invoice_id: UUID
    score: Decimal = Field(ge=0, le=1, max_digits=4, decimal_places=3)
    duplicate_invoice_ids: list[UUID] = Field(max_length=100)
    findings: list[InvoiceComplianceFinding] = Field(max_length=100)
    recommendation: InvoiceRecommendation


class InvoiceDecisionReview(BaseModel):
    """Authenticated reviewer action on a pending invoice recommendation."""

    model_config = ConfigDict(extra="forbid")

    decision_id: UUID
    reviewer_user_id: UUID
    approve: bool


class InvoiceComplianceResult(BaseModel):
    """Result of an invoice review or its human review transition."""

    model_config = ConfigDict(extra="forbid")

    invoice_id: UUID
    decision_id: UUID
    recommendation: InvoiceRecommendation
    assessment: InvoiceComplianceAssessment
    narrative: str = Field(min_length=1, max_length=5000)
    workflow_status: Literal["awaiting_human_approval", "approved", "rejected"]
