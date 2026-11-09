"""Typed LangGraph state for invoice assessment and human review."""

from typing import TypedDict
from uuid import UUID

from app.schemas.commerce import InvoiceRead, VendorRead
from app.schemas.invoice_compliance import InvoiceComplianceAssessment


class InvoiceComplianceState(TypedDict, total=False):
    """Data passed between invoice review nodes."""

    invoice_id: UUID
    invoice: InvoiceRead
    vendor: VendorRead
    duplicate_invoice_ids: list[UUID]
    assessment: InvoiceComplianceAssessment
    narrative: str
    decision_id: UUID
    agent_id: UUID
    workflow_status: str
