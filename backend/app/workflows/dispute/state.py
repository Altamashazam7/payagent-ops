"""Typed LangGraph state for dispute-defense analysis and approval resume."""

from typing import TypedDict
from uuid import UUID

from app.integrations.paypal.models import DisputeEvidenceRequest, HumanApproval
from app.schemas.commerce import DisputeRead, TransactionRead, VendorRead
from app.schemas.dispute_defense import (
    CommunicationEvidenceRecord,
    DisputeEventEnvelope,
    DisputeEvidencePackage,
    DisputeSuccessProbability,
    PayPalOrderSnapshot,
    ShippingEvidenceRecord,
)


class DisputeDefenseState(TypedDict, total=False):
    """State carried between event intake, review persistence, and resume."""

    event: DisputeEventEnvelope
    paypal_event_id: str
    resume_decision_id: UUID
    paypal_dispute_id: str
    dispute: DisputeRead
    transaction: TransactionRead
    vendor: VendorRead
    paypal_order: PayPalOrderSnapshot | None
    shipping_evidence: list[ShippingEvidenceRecord]
    communication_history: list[CommunicationEvidenceRecord]
    evidence_package: DisputeEvidencePackage
    evidence_request: DisputeEvidenceRequest | None
    narrative: str
    success_probability: DisputeSuccessProbability
    recommendation: str
    decision_id: UUID
    agent_id: UUID
    approval: HumanApproval
    workflow_status: str
    paypal_submission_status: str
