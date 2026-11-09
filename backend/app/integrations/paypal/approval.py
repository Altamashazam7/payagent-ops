"""Runtime safeguards for PayPal operations requiring human authorization."""

import logging
from enum import StrEnum
from typing import Protocol

from app.integrations.paypal.errors import PayPalApprovalRequiredError
from app.integrations.paypal.models import HumanApproval

logger = logging.getLogger("payagent_ops")


class SensitivePayPalAction(StrEnum):
    CAPTURE_ORDER = "capture_order"
    SUBMIT_DISPUTE_EVIDENCE = "submit_dispute_evidence"
    CREATE_PAYOUT_BATCH = "create_payout_batch"


class HumanApprovalVerifier(Protocol):
    """Application service contract for validating persisted human decisions."""

    async def verify(
        self,
        approval: HumanApproval,
        *,
        action: SensitivePayPalAction,
    ) -> None:
        """Raise PayPalApprovalRequiredError unless the persisted decision permits it."""


class UnconfiguredHumanApprovalVerifier:
    """Fail closed until an application service supplies persisted verification."""

    async def verify(
        self,
        approval: HumanApproval,
        *,
        action: SensitivePayPalAction,
    ) -> None:
        require_human_approval(approval)
        logger.warning(
            "Sensitive PayPal operation blocked",
            extra={
                "event": "paypal_action_blocked",
                "provider": "paypal",
                "operation": action.value,
            },
        )
        raise PayPalApprovalRequiredError(
            "No persisted human-approval verifier is configured; "
            "this PayPal operation is disabled"
        )


def require_human_approval(approval: object) -> HumanApproval:
    """Reject missing or incorrectly typed approval evidence."""
    if not isinstance(approval, HumanApproval):
        raise PayPalApprovalRequiredError(
            "A recorded human approval is required for this PayPal action"
        )
    return approval
