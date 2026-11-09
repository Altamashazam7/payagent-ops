"""Typed LangGraph state for payout assessment and approval resume."""

from typing import TypedDict
from uuid import UUID

from app.integrations.paypal.models import HumanApproval
from app.schemas.commerce import PayoutRead, UserRead, VendorRead
from app.schemas.smart_payout import PayoutRiskAssessment


class SmartPayoutState(TypedDict, total=False):
    """Data passed between payout analysis, approval, and submission nodes."""

    requested_payout_id: UUID
    resume_decision_id: UUID
    payout: PayoutRead
    vendor: VendorRead
    requester: UserRead
    recent_payouts: list[PayoutRead]
    history_complete: bool
    assessment: PayoutRiskAssessment
    narrative: str
    recommendation: str
    decision_id: UUID
    agent_id: UUID
    approval: HumanApproval
    workflow_status: str
    paypal_batch_id: str
    paypal_batch_status: str
