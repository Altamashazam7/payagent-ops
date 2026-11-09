"""Validated risk and approval schemas for smart payout operations."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PayoutRecommendation = Literal["create_payout_batch", "manual_review"]
PayoutFindingSeverity = Literal["low", "medium", "high"]


class PayoutRiskFinding(BaseModel):
    """A transparent payout eligibility or anomaly finding."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=80)
    severity: PayoutFindingSeverity
    message: str = Field(min_length=1, max_length=500)


class PayoutRiskAssessment(BaseModel):
    """Rule-based payout eligibility assessment, not an automatic authorization."""

    model_config = ConfigDict(extra="forbid")

    payout_id: UUID
    eligibility_score: Decimal = Field(ge=0, le=1, max_digits=4, decimal_places=3)
    historical_sample_count: int = Field(ge=0)
    findings: list[PayoutRiskFinding] = Field(max_length=100)
    recommendation: PayoutRecommendation


class PayoutDecisionApproval(BaseModel):
    """Authenticated human approval of one payout batch decision."""

    model_config = ConfigDict(extra="forbid")

    decision_id: UUID
    reviewer_user_id: UUID


class SmartPayoutResult(BaseModel):
    """Result of a payout analysis or approval-gated submission."""

    model_config = ConfigDict(extra="forbid")

    payout_id: UUID
    decision_id: UUID
    recommendation: PayoutRecommendation
    assessment: PayoutRiskAssessment
    narrative: str = Field(min_length=1, max_length=5000)
    workflow_status: Literal[
        "awaiting_human_approval",
        "submitted",
        "rejected",
    ]
    paypal_batch_id: str | None = None
    paypal_batch_status: str | None = None
