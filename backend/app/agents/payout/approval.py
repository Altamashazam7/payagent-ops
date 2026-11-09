"""Persisted decision verifier for sensitive payout batch submission."""

from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.paypal.approval import SensitivePayPalAction
from app.integrations.paypal.errors import PayPalApprovalRequiredError
from app.integrations.paypal.models import HumanApproval
from app.models.enums import (
    DecisionStatus,
    PayoutStatus,
    UserRole,
    UserStatus,
    VendorStatus,
)
from app.repositories.smart_payout import SmartPayoutRepository


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class PersistedPayoutApprovalVerifier:
    """Authorize only the matching active human and approved payout decision."""

    def __init__(
        self,
        repository: SmartPayoutRepository,
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
        if action is not SensitivePayPalAction.CREATE_PAYOUT_BATCH:
            raise PayPalApprovalRequiredError(
                "This verifier only authorizes payout batch creation"
            )
        decision = await self._repository.get_decision(approval.decision_id)
        reviewer = await self._repository.get_user(approval.reviewer_user_id)
        if decision is None or decision.payout_id is None:
            await self._session.rollback()
            raise PayPalApprovalRequiredError(
                "The persisted decision does not authorize a payout"
            )
        case = await self._repository.get_context(decision.payout_id)
        approval_artifact = await self._repository.get_approval_artifact(
            decision.payout_id
        )
        payout = case[0] if case is not None else None
        vendor = case[1] if case is not None else None
        authorized = not (
            decision.status is not DecisionStatus.APPROVED
            or decision.action_type != "create_payout_batch"
            or decision.reviewed_by_user_id != approval.reviewer_user_id
            or decision.reviewed_at is None
            or _as_utc(decision.reviewed_at) != _as_utc(approval.approved_at)
            or reviewer is None
            or reviewer.status is not UserStatus.ACTIVE
            or reviewer.deleted_at is not None
            or reviewer.role
            not in {UserRole.ADMIN, UserRole.OPERATOR, UserRole.REVIEWER}
            or payout is None
            or payout.status is not PayoutStatus.APPROVED
            or payout.approved_by_user_id != approval.reviewer_user_id
            or payout.approved_at is None
            or _as_utc(payout.approved_at) != _as_utc(approval.approved_at)
            or vendor is None
            or vendor.status is not VendorStatus.ACTIVE
            or vendor.deleted_at is not None
            or approval_artifact is None
            or approval_artifact.after_state is None
            or not self._matches_artifact(
                payout.updated_at,
                approval_artifact.after_state,
            )
        )
        await self._session.rollback()
        if not authorized:
            raise PayPalApprovalRequiredError(
                "The persisted human approval does not authorize this payout"
            )

    @staticmethod
    def _matches_artifact(
        updated_at: datetime,
        artifact: Mapping[str, object],
    ) -> bool:
        raw_value = artifact.get("payout_updated_at")
        if not isinstance(raw_value, str):
            return False
        try:
            snapshot = datetime.fromisoformat(raw_value)
        except ValueError:
            return False
        return _as_utc(updated_at) == _as_utc(snapshot)
