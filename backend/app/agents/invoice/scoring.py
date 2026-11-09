"""Explainable invoice compliance rules and duplicate detection."""

from decimal import Decimal
from uuid import UUID

from app.models.enums import InvoiceStatus, VendorStatus
from app.schemas.commerce import InvoiceRead, VendorRead
from app.schemas.invoice_compliance import (
    InvoiceComplianceAssessment,
    InvoiceComplianceFinding,
    InvoiceRecommendation,
)


class InvoiceComplianceScorer:
    """Score record completeness; this is not a prediction of invoice validity."""

    def score(
        self,
        invoice: InvoiceRead,
        vendor: VendorRead,
        duplicate_invoice_ids: list[UUID],
    ) -> InvoiceComplianceAssessment:
        findings: list[InvoiceComplianceFinding] = []
        if duplicate_invoice_ids:
            findings.append(
                InvoiceComplianceFinding(
                    code="possible_duplicate",
                    severity="high",
                    message=(
                        f"Found {len(duplicate_invoice_ids)} invoice record(s) "
                        "with a matching normalized invoice number or strong "
                        "amount, currency, customer, and due-date fingerprint."
                    ),
                )
            )
        if vendor.status is not VendorStatus.ACTIVE:
            findings.append(
                InvoiceComplianceFinding(
                    code="vendor_not_active",
                    severity="high",
                    message="The invoice vendor is not active.",
                )
            )
        if invoice.status is InvoiceStatus.CANCELLED:
            findings.append(
                InvoiceComplianceFinding(
                    code="invoice_cancelled",
                    severity="high",
                    message="A cancelled invoice cannot be approved for processing.",
                )
            )
        if invoice.status in {InvoiceStatus.SENT, InvoiceStatus.OVERDUE}:
            if invoice.billing_email is None:
                findings.append(
                    InvoiceComplianceFinding(
                        code="missing_billing_email",
                        severity="medium",
                        message="A sent invoice has no recorded billing email.",
                    )
                )
            if invoice.due_at is None:
                findings.append(
                    InvoiceComplianceFinding(
                        code="missing_due_date",
                        severity="medium",
                        message="A sent or overdue invoice has no due date.",
                    )
                )
        if invoice.status is InvoiceStatus.PAID and invoice.transaction_id is None:
            findings.append(
                InvoiceComplianceFinding(
                    code="paid_without_transaction",
                    severity="medium",
                    message="The paid invoice is not linked to a transaction.",
                )
            )

        score = Decimal("1.000")
        for finding in findings:
            score -= {
                "high": Decimal("0.500"),
                "medium": Decimal("0.200"),
                "low": Decimal("0.100"),
            }[finding.severity]
        score = max(Decimal("0.000"), score).quantize(Decimal("0.001"))
        recommendation: InvoiceRecommendation = (
            "approve_invoice"
            if score >= Decimal("0.800") and not findings
            else "manual_review"
        )
        return InvoiceComplianceAssessment(
            invoice_id=invoice.id,
            score=score,
            duplicate_invoice_ids=duplicate_invoice_ids,
            findings=findings,
            recommendation=recommendation,
        )
