"""Application service coordinating payout analysis and approved submission."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.payout.approval import PersistedPayoutApprovalVerifier
from app.agents.payout.narrative import (
    OpenAIPayoutNarrativeGenerator,
    PayoutNarrativeGenerator,
)
from app.agents.payout.scoring import SmartPayoutScorer
from app.core.settings import Settings
from app.core.types import JSONValue
from app.integrations.paypal import (
    CreatePayoutBatchRequest,
    HumanApproval,
    PayoutBatchId,
    PayoutsClient,
    PayPalClients,
    PayPalError,
    PayPalMoney,
    SensitivePayPalAction,
)
from app.integrations.paypal.models import (
    PayoutItem,
    PayoutSenderBatchHeader,
)
from app.models.audit_log import AuditLog
from app.models.decision import Decision
from app.models.enums import (
    AuditEntityType,
    DecisionStatus,
    PayoutRecipientType,
    PayoutStatus,
    UserRole,
    UserStatus,
    VendorStatus,
)
from app.models.payout import Payout
from app.repositories.smart_payout import (
    MAX_PAYOUT_HISTORY,
    PAYOUT_SUBMISSION_ATTEMPT_ACTION,
    SmartPayoutRepository,
)
from app.schemas.commerce import PayoutRead, UserRead, VendorRead
from app.schemas.smart_payout import (
    PayoutDecisionApproval,
    PayoutRiskAssessment,
    SmartPayoutResult,
)
from app.workflows.payout.graph import build_smart_payout_graph
from app.workflows.payout.state import SmartPayoutState

logger = logging.getLogger("payagent_ops")
STATE_ADAPTER = TypeAdapter(SmartPayoutState)
JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JSONValue])
RECIPIENT_TYPE_MAP: dict[
    PayoutRecipientType,
    Literal["EMAIL", "PHONE", "PAYPAL_ID"],
] = {
    PayoutRecipientType.EMAIL: "EMAIL",
    PayoutRecipientType.PHONE: "PHONE",
    PayoutRecipientType.PAYPAL_ID: "PAYPAL_ID",
}


class SmartPayoutService:
    """Recommend payouts and submit only after persisted human approval."""

    def __init__(
        self,
        session: AsyncSession,
        paypal_clients: PayPalClients,
        narrative_generator: PayoutNarrativeGenerator,
        *,
        scorer: SmartPayoutScorer | None = None,
    ) -> None:
        self._session = session
        self._paypal = paypal_clients
        self._repository = SmartPayoutRepository(session)
        self._narrative_generator = narrative_generator
        self._scorer = scorer or SmartPayoutScorer()
        self._approval_verifier = PersistedPayoutApprovalVerifier(
            self._repository,
            session,
        )
        self._payouts_client = PayoutsClient(
            paypal_clients.api,
            approval_verifier=self._approval_verifier,
        )
        self._workflow = build_smart_payout_graph(self)

    @classmethod
    def from_settings(
        cls,
        session: AsyncSession,
        paypal_clients: PayPalClients,
        settings: Settings,
    ) -> SmartPayoutService:
        """Create the configured async payout narrative generator."""
        return cls(
            session,
            paypal_clients,
            OpenAIPayoutNarrativeGenerator.from_settings(settings),
        )

    async def review(self, payout_id: UUID) -> SmartPayoutResult:
        """Assess one payout and persist a pending recommendation."""
        raw_state = await self._workflow.ainvoke({"requested_payout_id": payout_id})
        state = STATE_ADAPTER.validate_python(raw_state)
        return self._result(state, "awaiting_human_approval")

    async def approve_and_submit(
        self,
        approval: PayoutDecisionApproval,
    ) -> SmartPayoutResult:
        """Persist the human approval, then resume the PayPal submit path."""
        await self._approve_decision(approval)
        raw_state = await self._workflow.ainvoke(
            {"resume_decision_id": approval.decision_id}
        )
        state = STATE_ADAPTER.validate_python(raw_state)
        return self._result(state, "submitted")

    async def load_payout(self, _state: SmartPayoutState) -> SmartPayoutState:
        payout_id = _state.get("requested_payout_id")
        if payout_id is None:
            raise ValueError("A payout ID is required for analysis")
        case = await self._repository.get_context(payout_id)
        if case is None:
            await self._session.rollback()
            raise LookupError("Payout does not exist")
        payout, vendor, requester = case
        if payout.status is not PayoutStatus.PENDING_APPROVAL:
            await self._session.rollback()
            raise ValueError("Only pending payouts can be reviewed")
        payout_read = PayoutRead.model_validate(payout)
        vendor_read = VendorRead.model_validate(vendor)
        requester_read = UserRead.model_validate(requester)
        recent = await self._repository.list_recent_for_vendor(vendor.id)
        history_complete = len(recent) <= MAX_PAYOUT_HISTORY
        recent_reads = [
            PayoutRead.model_validate(item) for item in recent[:MAX_PAYOUT_HISTORY]
        ]
        await self._session.rollback()
        return {
            "payout": payout_read,
            "vendor": vendor_read,
            "requester": requester_read,
            "recent_payouts": recent_reads,
            "history_complete": history_complete,
        }

    async def assess_payout(
        self,
        state: SmartPayoutState,
    ) -> SmartPayoutState:
        assessment = self._scorer.score(
            state["payout"],
            state["vendor"],
            state["requester"],
            state.get("recent_payouts", []),
            history_complete=state.get("history_complete", True),
        )
        return {
            "assessment": assessment,
            "recommendation": assessment.recommendation,
        }

    async def generate_summary(
        self,
        state: SmartPayoutState,
    ) -> SmartPayoutState:
        narrative = await self._narrative_generator.generate(state["assessment"])
        if not narrative.strip() or len(narrative) > 5000:
            raise ValueError("Payout narrative generator returned invalid content")
        return {"narrative": narrative.strip()}

    async def persist_decision(
        self,
        state: SmartPayoutState,
    ) -> SmartPayoutState:
        payout = state["payout"]
        agent = await self._repository.get_or_create_agent(payout.vendor_id)
        assessment = state["assessment"]
        decision = Decision(
            vendor_id=payout.vendor_id,
            agent_id=agent.id,
            payout_id=payout.id,
            action_type=assessment.recommendation,
            recommendation=(
                "Payout is eligible for human approval"
                if assessment.recommendation == "create_payout_batch"
                else "Payout requires manual review; no PayPal submission is allowed"
            ),
            rationale=state["narrative"],
            confidence=assessment.eligibility_score,
            status=DecisionStatus.PENDING,
        )
        self._repository.add(decision)
        await self._session.flush()
        audit_payload = JSON_OBJECT_ADAPTER.validate_python(
            {
                "assessment": assessment.model_dump(mode="json"),
                "narrative": state["narrative"],
                "payout_updated_at": payout.updated_at.isoformat(),
                "recipient_configured": payout.paypal_receiver is not None,
                "recipient_type": (
                    payout.paypal_recipient_type.value
                    if payout.paypal_recipient_type is not None
                    else None
                ),
            }
        )
        self._repository.add(
            AuditLog(
                entity_type=AuditEntityType.DECISION,
                entity_id=decision.id,
                vendor_id=payout.vendor_id,
                agent_id=agent.id,
                action="smart_payout_assessed",
                after_state=audit_payload,
            )
        )
        await self._session.commit()
        logger.info(
            "Smart payout recommendation persisted",
            extra={
                "event": "smart_payout_assessed",
                "operation": "smart_payout",
                "agent_id": str(agent.id),
                "decision_id": str(decision.id),
                "payout_id": str(payout.id),
                "vendor_id": str(payout.vendor_id),
            },
        )
        return {"decision_id": decision.id, "agent_id": agent.id}

    async def await_human_approval(
        self,
        _state: SmartPayoutState,
    ) -> SmartPayoutState:
        return {"workflow_status": "awaiting_human_approval"}

    async def load_approved_payout(
        self,
        state: SmartPayoutState,
    ) -> SmartPayoutState:
        decision_id = state.get("resume_decision_id")
        if decision_id is None:
            raise ValueError("A decision ID is required to resume payout approval")
        decision = await self._repository.get_decision(decision_id)
        artifact = await self._repository.get_prepared_artifact(decision_id)
        if (
            decision is None
            or decision.status is not DecisionStatus.APPROVED
            or decision.action_type != "create_payout_batch"
            or decision.payout_id is None
            or decision.agent_id is None
            or decision.reviewed_by_user_id is None
            or decision.reviewed_at is None
            or artifact is None
            or artifact.after_state is None
        ):
            await self._session.rollback()
            raise ValueError("No approved smart payout decision can be resumed")
        approval_artifact = await self._repository.get_approval_artifact(
            decision.payout_id
        )
        if approval_artifact is None or approval_artifact.after_state is None:
            await self._session.rollback()
            raise ValueError("Persisted payout approval artifact is missing")
        case = await self._repository.get_context(decision.payout_id)
        if case is None:
            await self._session.rollback()
            raise LookupError("Approved payout no longer exists")
        payout, vendor, requester = case
        if (
            payout.status is not PayoutStatus.APPROVED
            or payout.approved_by_user_id != decision.reviewed_by_user_id
            or payout.approved_at is None
            or payout.paypal_receiver is None
            or payout.paypal_recipient_type is None
            or payout.paypal_batch_id is not None
            or vendor.status is not VendorStatus.ACTIVE
            or vendor.deleted_at is not None
            or not self._matches_artifact(
                payout.updated_at,
                "payout_updated_at",
                approval_artifact.after_state,
            )
        ):
            await self._session.rollback()
            raise ValueError("Payout is no longer eligible for submission")
        assessment = PayoutRiskAssessment.model_validate(
            artifact.after_state.get("assessment")
        )
        narrative = artifact.after_state.get("narrative")
        if assessment.recommendation != "create_payout_batch" or not isinstance(
            narrative, str
        ):
            await self._session.rollback()
            raise ValueError("Persisted payout review artifact is invalid")
        approval = HumanApproval(
            decision_id=decision.id,
            reviewer_user_id=decision.reviewed_by_user_id,
            approved_at=self._as_utc(decision.reviewed_at),
        )
        payout_read = PayoutRead.model_validate(payout)
        vendor_read = VendorRead.model_validate(vendor)
        requester_read = UserRead.model_validate(requester)
        decision_record_id = decision.id
        agent_id = decision.agent_id
        await self._session.rollback()
        await self._approval_verifier.verify(
            approval,
            action=SensitivePayPalAction.CREATE_PAYOUT_BATCH,
        )
        return {
            "decision_id": decision_record_id,
            "agent_id": agent_id,
            "payout": payout_read,
            "vendor": vendor_read,
            "requester": requester_read,
            "assessment": assessment,
            "narrative": narrative,
            "recommendation": assessment.recommendation,
            "approval": approval,
        }

    async def submit_payout(
        self,
        state: SmartPayoutState,
    ) -> SmartPayoutState:
        request = self._build_paypal_request(state["payout"])
        await self._claim_submission(state)
        try:
            response = await self._payouts_client.create_payout_batch(
                request,
                approval=state["approval"],
            )
        except PayPalError as exc:
            await self._record_submission_failure(state, type(exc).__name__)
            logger.error(
                "PayPal payout submission failed",
                extra={
                    "event": "smart_payout_submission_failed",
                    "provider": "paypal",
                    "operation": "payout_submission",
                    "agent_id": str(state.get("agent_id", "")),
                    "decision_id": str(state["decision_id"]),
                    "payout_id": str(state["payout"].id),
                    "vendor_id": str(state["payout"].vendor_id),
                },
            )
            raise

        payout = await self._session.get(Payout, state["payout"].id)
        if payout is None:
            raise LookupError("Submitted payout record disappeared")
        payout.paypal_batch_id = response.payout_batch_id
        payout.status = PayoutStatus.PROCESSING
        self._repository.add(
            AuditLog(
                entity_type=AuditEntityType.PAYOUT,
                entity_id=payout.id,
                vendor_id=payout.vendor_id,
                agent_id=state.get("agent_id"),
                action="payout_batch_submitted",
                after_state={
                    "paypal_batch_id": response.payout_batch_id,
                    "paypal_batch_status": response.batch_status,
                },
            )
        )
        await self._session.commit()
        logger.info(
            "Approved payout batch submitted to PayPal",
            extra={
                "event": "smart_payout_submitted",
                "provider": "paypal",
                "operation": "payout_submission",
                "agent_id": str(state.get("agent_id", "")),
                "decision_id": str(state["decision_id"]),
                "payout_id": str(payout.id),
                "vendor_id": str(payout.vendor_id),
            },
        )
        return {
            "workflow_status": "submitted",
            "paypal_batch_id": response.payout_batch_id,
            "paypal_batch_status": response.batch_status,
        }

    async def _approve_decision(self, approval: PayoutDecisionApproval) -> None:
        decision = await self._repository.get_decision(approval.decision_id, lock=True)
        reviewer = await self._repository.get_user(approval.reviewer_user_id)
        if (
            decision is None
            or decision.payout_id is None
            or decision.agent_id is None
            or decision.action_type != "create_payout_batch"
        ):
            await self._session.rollback()
            raise ValueError("Decision is not eligible for payout approval")
        case = await self._repository.get_context(decision.payout_id, lock=True)
        if case is None:
            await self._session.rollback()
            raise LookupError("Payout no longer exists")
        payout, vendor, _requester = case
        if (
            reviewer is None
            or reviewer.status is not UserStatus.ACTIVE
            or reviewer.deleted_at is not None
            or reviewer.role
            not in {UserRole.ADMIN, UserRole.OPERATOR, UserRole.REVIEWER}
        ):
            await self._session.rollback()
            raise ValueError("An active admin or operator must approve this payout")
        if decision.status is not DecisionStatus.PENDING:
            if await self._repository.has_submission_attempt(payout.id):
                await self._session.rollback()
                raise ValueError(
                    "Payout submission was already attempted; reconcile PayPal manually"
                )
            same_approval = (
                decision.status is DecisionStatus.APPROVED
                and decision.reviewed_by_user_id == reviewer.id
                and payout.status is PayoutStatus.APPROVED
                and payout.approved_by_user_id == reviewer.id
            )
            if same_approval:
                approval_artifact = await self._repository.get_approval_artifact(
                    payout.id
                )
                if (
                    approval_artifact is not None
                    and approval_artifact.after_state is not None
                    and self._matches_artifact(
                        payout.updated_at,
                        "payout_updated_at",
                        approval_artifact.after_state,
                    )
                ):
                    await self._session.rollback()
                    return
                await self._session.rollback()
                raise ValueError("Payout changed after human approval")
            await self._session.rollback()
            raise ValueError("Only pending payout decisions can be approved")
        if (
            vendor.status is not VendorStatus.ACTIVE
            or vendor.deleted_at is not None
            or payout.status is not PayoutStatus.PENDING_APPROVAL
            or payout.paypal_receiver is None
            or payout.paypal_recipient_type is None
        ):
            await self._session.rollback()
            raise ValueError("Payout is not currently eligible for approval")
        artifact = await self._repository.get_prepared_artifact(decision.id)
        if artifact is None or artifact.after_state is None:
            await self._session.rollback()
            raise ValueError("Payout assessment artifact is missing")
        assessment = PayoutRiskAssessment.model_validate(
            artifact.after_state.get("assessment")
        )
        if not self._matches_artifact(
            payout.updated_at,
            "payout_updated_at",
            artifact.after_state,
        ):
            await self._session.rollback()
            raise ValueError("Payout changed after assessment; run a fresh review")
        recent = await self._repository.list_recent_for_vendor(vendor.id)
        history_complete = len(recent) <= MAX_PAYOUT_HISTORY
        current_assessment = self._scorer.score(
            PayoutRead.model_validate(payout),
            VendorRead.model_validate(vendor),
            UserRead.model_validate(_requester),
            [PayoutRead.model_validate(item) for item in recent[:MAX_PAYOUT_HISTORY]],
            history_complete=history_complete,
        )
        if current_assessment != assessment:
            await self._session.rollback()
            raise ValueError("Payout risk changed after assessment; run a fresh review")
        approved_at = datetime.now(UTC)
        decision.status = DecisionStatus.APPROVED
        decision.reviewed_by_user_id = reviewer.id
        decision.reviewed_at = approved_at
        payout.status = PayoutStatus.APPROVED
        payout.approved_by_user_id = reviewer.id
        payout.approved_at = approved_at
        payout.updated_at = approved_at
        await self._session.flush()
        self._repository.add(
            AuditLog(
                entity_type=AuditEntityType.DECISION,
                entity_id=decision.id,
                vendor_id=payout.vendor_id,
                actor_user_id=reviewer.id,
                action="smart_payout_approved",
                after_state={"decision_status": DecisionStatus.APPROVED.value},
            )
        )
        self._repository.add(
            AuditLog(
                entity_type=AuditEntityType.PAYOUT,
                entity_id=payout.id,
                vendor_id=payout.vendor_id,
                actor_user_id=reviewer.id,
                action="payout_approved",
                after_state={
                    "payout_status": PayoutStatus.APPROVED.value,
                    "payout_updated_at": payout.updated_at.isoformat(),
                },
            )
        )
        await self._session.commit()
        logger.info(
            "Payout recommendation approved by human",
            extra={
                "event": "smart_payout_approved",
                "operation": "payout_approval",
                "agent_id": str(decision.agent_id),
                "decision_id": str(decision.id),
                "payout_id": str(payout.id),
                "reviewer_user_id": str(reviewer.id),
                "vendor_id": str(payout.vendor_id),
            },
        )

    async def _claim_submission(self, state: SmartPayoutState) -> None:
        decision = await self._repository.get_decision(state["decision_id"], lock=True)
        case = await self._repository.get_context(state["payout"].id, lock=True)
        if (
            decision is None
            or case is None
            or decision.status is not DecisionStatus.APPROVED
            or decision.action_type != "create_payout_batch"
            or decision.payout_id != case[0].id
            or case[0].status is not PayoutStatus.APPROVED
            or case[0].paypal_batch_id is not None
            or case[0].approved_by_user_id != decision.reviewed_by_user_id
            or case[1].status is not VendorStatus.ACTIVE
            or case[1].deleted_at is not None
            or not self._same_payout(case[0], state["payout"])
        ):
            await self._session.rollback()
            raise ValueError("Persisted human approval is required before payout")
        if await self._repository.has_submission_attempt(case[0].id):
            await self._session.rollback()
            raise ValueError(
                "Payout submission was already attempted; reconcile PayPal manually"
            )
        self._repository.add(
            AuditLog(
                entity_type=AuditEntityType.PAYOUT,
                entity_id=case[0].id,
                vendor_id=case[0].vendor_id,
                agent_id=decision.agent_id,
                action=PAYOUT_SUBMISSION_ATTEMPT_ACTION,
                request_id=str(case[0].id),
                after_state={"state": "started"},
            )
        )
        await self._session.commit()

    async def _record_submission_failure(
        self,
        state: SmartPayoutState,
        error_type: str,
    ) -> None:
        self._repository.add(
            AuditLog(
                entity_type=AuditEntityType.PAYOUT,
                entity_id=state["payout"].id,
                vendor_id=state["payout"].vendor_id,
                agent_id=state.get("agent_id"),
                action="payout_submission_failed",
                after_state={"error_type": error_type},
            )
        )
        await self._session.commit()

    @staticmethod
    def _build_paypal_request(payout: PayoutRead) -> CreatePayoutBatchRequest:
        if payout.paypal_receiver is None or payout.paypal_recipient_type is None:
            raise ValueError("A payout-specific PayPal recipient is required")
        sender_batch_id: PayoutBatchId = payout.id.hex[:30]
        return CreatePayoutBatchRequest(
            sender_batch_header=PayoutSenderBatchHeader(
                sender_batch_id=sender_batch_id,
                email_subject="Approved vendor payout",
                email_message="Your approved vendor payout is being processed.",
            ),
            items=[
                PayoutItem(
                    recipient_type=RECIPIENT_TYPE_MAP[payout.paypal_recipient_type],
                    amount=PayPalMoney(
                        currency_code=payout.currency,
                        value=payout.amount,
                    ),
                    receiver=payout.paypal_receiver,
                    sender_item_id=payout.id.hex,
                    note=payout.reference,
                )
            ],
        )

    def _result(
        self,
        state: SmartPayoutState,
        status: Literal["awaiting_human_approval", "submitted"],
    ) -> SmartPayoutResult:
        return SmartPayoutResult(
            payout_id=state["payout"].id,
            decision_id=state["decision_id"],
            recommendation=state["assessment"].recommendation,
            assessment=state["assessment"],
            narrative=state["narrative"],
            workflow_status=status,
            paypal_batch_id=state.get("paypal_batch_id"),
            paypal_batch_status=state.get("paypal_batch_status"),
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @classmethod
    def _matches_artifact(
        cls,
        value: datetime,
        key: str,
        artifact: dict[str, JSONValue],
    ) -> bool:
        raw_value = artifact.get(key)
        if not isinstance(raw_value, str):
            return False
        try:
            snapshot = datetime.fromisoformat(raw_value)
        except ValueError:
            return False
        return cls._as_utc(value) == cls._as_utc(snapshot)

    @classmethod
    def _same_payout(cls, current: Payout, snapshot: PayoutRead) -> bool:
        return (
            current.amount == snapshot.amount
            and current.currency == snapshot.currency
            and current.paypal_receiver == snapshot.paypal_receiver
            and current.paypal_recipient_type == snapshot.paypal_recipient_type
            and current.status is snapshot.status
            and current.approved_by_user_id == snapshot.approved_by_user_id
            and current.approved_at is not None
            and snapshot.approved_at is not None
            and cls._as_utc(current.approved_at) == cls._as_utc(snapshot.approved_at)
            and cls._as_utc(current.updated_at) == cls._as_utc(snapshot.updated_at)
        )
