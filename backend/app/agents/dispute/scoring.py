"""Explainable, conservative dispute evidence scoring."""

from decimal import Decimal

from app.models.enums import TransactionStatus, VendorStatus
from app.schemas.dispute_defense import (
    DisputeEvidencePackage,
    DisputeSuccessProbability,
)


class DisputeSuccessScorer:
    """Calculate an evidence-completeness heuristic, not a learned probability."""

    def score(self, package: DisputeEvidencePackage) -> DisputeSuccessProbability:
        score = Decimal("0.000")
        basis: list[str] = []

        if package.paypal_order_matches_transaction:
            score += Decimal("0.200")
            basis.append("PayPal order status and amount match the transaction")
        elif package.paypal_order is not None:
            basis.append("PayPal order does not match the transaction")
        else:
            basis.append("Related PayPal order is unavailable")

        if package.vendor_status is VendorStatus.ACTIVE:
            score += Decimal("0.050")
            basis.append("Vendor is active")
        else:
            basis.append("Vendor is not active")

        if package.transaction_status in {
            TransactionStatus.CAPTURED,
            TransactionStatus.PARTIALLY_REFUNDED,
        }:
            score += Decimal("0.100")
            basis.append("Transaction is captured")
        else:
            basis.append("Transaction is not captured")

        delivered_with_tracking = any(
            item.delivery_status == "delivered" and item.tracking_number
            for item in package.shipping_evidence
        )
        if delivered_with_tracking:
            score += Decimal("0.400")
            basis.append("Delivery confirmation and tracking are available")
        elif package.shipping_evidence:
            score += Decimal("0.100")
            basis.append("Shipping evidence exists without delivery confirmation")
        else:
            basis.append("No shipping evidence was found")

        if package.communication_history:
            score += Decimal("0.100")
            basis.append("Customer communication history is available")
        else:
            basis.append("No customer communication history was found")

        if any(item.customer_acknowledged for item in package.communication_history):
            score += Decimal("0.150")
            basis.append("A customer acknowledgment is documented")

        return DisputeSuccessProbability(
            value=min(score, Decimal("0.950")).quantize(Decimal("0.001")),
            basis=basis,
        )
