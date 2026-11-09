"""Conservative, explainable payout eligibility and anomaly rules."""

from collections.abc import Sequence
from decimal import Decimal
from statistics import median

from app.models.enums import PayoutStatus, UserRole, UserStatus, VendorStatus
from app.schemas.commerce import PayoutRead, UserRead, VendorRead
from app.schemas.smart_payout import PayoutRiskAssessment, PayoutRiskFinding

ACTIVE_DUPLICATE_STATUSES = {
    PayoutStatus.PENDING_APPROVAL,
    PayoutStatus.APPROVED,
    PayoutStatus.PROCESSING,
    PayoutStatus.PAID,
}


class SmartPayoutScorer:
    """Flag duplicate and outlier payouts; never authorize financial execution."""

    def score(
        self,
        payout: PayoutRead,
        vendor: VendorRead,
        requester: UserRead,
        recent_payouts: Sequence[PayoutRead],
        *,
        history_complete: bool = True,
    ) -> PayoutRiskAssessment:
        findings: list[PayoutRiskFinding] = []
        hard_blocker = False
        if vendor.status is not VendorStatus.ACTIVE or vendor.deleted_at is not None:
            findings.append(
                PayoutRiskFinding(
                    code="vendor_not_active",
                    severity="high",
                    message="The payout vendor is not active.",
                )
            )
            hard_blocker = True
        if payout.paypal_receiver is None or payout.paypal_recipient_type is None:
            findings.append(
                PayoutRiskFinding(
                    code="recipient_missing",
                    severity="high",
                    message="A payout-specific PayPal recipient is required.",
                )
            )
            hard_blocker = True
        if payout.paypal_batch_id is not None:
            findings.append(
                PayoutRiskFinding(
                    code="already_has_paypal_batch",
                    severity="high",
                    message="The payout is already associated with a PayPal batch.",
                )
            )
            hard_blocker = True
        if (
            requester.status is not UserStatus.ACTIVE
            or requester.deleted_at is not None
            or requester.role not in {UserRole.ADMIN, UserRole.OPERATOR}
        ):
            findings.append(
                PayoutRiskFinding(
                    code="requester_not_authorized",
                    severity="high",
                    message="The payout requester is not an active operator.",
                )
            )
            hard_blocker = True

        duplicates = [
            item
            for item in recent_payouts
            if item.id != payout.id
            and item.status in ACTIVE_DUPLICATE_STATUSES
            and item.amount == payout.amount
            and item.currency == payout.currency
            and item.paypal_receiver == payout.paypal_receiver
            and item.paypal_recipient_type == payout.paypal_recipient_type
        ]
        if duplicates:
            findings.append(
                PayoutRiskFinding(
                    code="possible_duplicate",
                    severity="high",
                    message=(
                        "Another active or settled payout has the same recipient, "
                        "amount, and currency."
                    ),
                )
            )
            hard_blocker = True

        historical = [
            item.amount
            for item in recent_payouts
            if item.id != payout.id
            and item.status is PayoutStatus.PAID
            and item.currency == payout.currency
        ]
        if len(historical) >= 3:
            typical_amount = Decimal(str(median(historical)))
            if typical_amount > 0 and payout.amount > typical_amount * 3:
                findings.append(
                    PayoutRiskFinding(
                        code="amount_outlier",
                        severity="high",
                        message=(
                            "The payout exceeds three times the median of recent "
                            "settled payouts in the same currency."
                        ),
                    )
                )
                hard_blocker = True
            else:
                findings.append(
                    PayoutRiskFinding(
                        code="amount_within_history",
                        severity="low",
                        message=(
                            "The payout is within three times the recent settled "
                            "median for this currency."
                        ),
                    )
                )
        if not history_complete:
            findings.append(
                PayoutRiskFinding(
                    code="history_limit_exceeded",
                    severity="high",
                    message=(
                        "The payout history exceeds the safe assessment window; "
                        "manual review is required."
                    ),
                )
            )
            hard_blocker = True
        else:
            findings.append(
                PayoutRiskFinding(
                    code="limited_history",
                    severity="medium",
                    message=(
                        "Fewer than three recent settled payouts are available "
                        "for amount anomaly comparison."
                    ),
                )
            )

        score = Decimal("0.950")
        if hard_blocker:
            score = Decimal("0.000")
        elif len(historical) < 3:
            score -= Decimal("0.200")
        elif any(item.code == "amount_within_history" for item in findings):
            score += Decimal("0.050")
        score = max(Decimal("0.000"), min(score, Decimal("1.000"))).quantize(
            Decimal("0.001")
        )
        return PayoutRiskAssessment(
            payout_id=payout.id,
            eligibility_score=score,
            historical_sample_count=len(historical),
            findings=findings,
            recommendation=(
                "create_payout_batch" if not hard_blocker else "manual_review"
            ),
        )
