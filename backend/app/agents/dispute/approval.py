"""Persisted Decision verification for dispute evidence submission."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.paypal.approval import SensitivePayPalAction
from app.integrations.paypal.errors import PayPalApprovalRequiredError
from app.integrations.paypal.models import HumanApproval
from app.models.enums import DecisionStatus, UserRole, UserStatus
from app.repositories.dispute_defense import DisputeDefenseRepository


def _as_utc(value: datetime) -> datetime:
    """Normalize SQLite's naive datetime values to the model's UTC convention."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class PersistedDecisionApprovalVerifier:
    """Accept only the approved decision and active human reviewer in the database."""

    def __init__(
        self,
        repository: DisputeDefenseRepository,
        session: AsyncSession,
    ) -> None:
        self._repository = repository
        self._session = session

    async def verify(
        self,
        approval: HumanApproval,
        *,
        action: SensitivePayPalAction,
    ) -> None:
        if action is not SensitivePayPalAction.SUBMIT_DISPUTE_EVIDENCE:
            raise PayPalApprovalRequiredError(
                "This verifier only authorizes dispute evidence submission"
            )
        decision = await self._repository.get_decision(approval.decision_id)
        reviewer = await self._repository.get_user(approval.reviewer_user_id)
        authorized = not (
            decision is None
            or decision.status is not DecisionStatus.APPROVED
            or decision.action_type != "submit_evidence"
            or decision.dispute_id is None
            or decision.reviewed_by_user_id != approval.reviewer_user_id
            or decision.reviewed_at is None
            or _as_utc(decision.reviewed_at) != _as_utc(approval.approved_at)
            or reviewer is None
            or reviewer.status is not UserStatus.ACTIVE
            or reviewer.role
            not in {UserRole.ADMIN, UserRole.OPERATOR, UserRole.REVIEWER}
        )
        await self._session.rollback()
        if not authorized:
            raise PayPalApprovalRequiredError(
                "The persisted human approval does not authorize this submission"
            )
