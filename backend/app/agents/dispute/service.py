"""Application service coordinating dispute evidence analysis and approval."""

import logging
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.dispute.approval import PersistedDecisionApprovalVerifier, _as_utc
from app.agents.dispute.narrative import (
    DisputeNarrativeGenerator,
    OpenAIDisputeNarrativeGenerator,
)
from app.agents.dispute.providers import (
    DisputeEvidenceProvider,
    RetryingDisputeEvidenceProvider,
)
from app.agents.dispute.scoring import DisputeSuccessScorer
from app.core.settings import Settings
from app.core.types import JSONValue
from app.integrations.paypal import (
    DisputeEvidence,
    DisputeEvidenceRequest,
    HumanApproval,
    PayPalClients,
    PayPalError,
    SensitivePayPalAction,
)
from app.integrations.paypal.disputes import DisputesClient
from app.models.audit_log import AuditLog
from app.models.decision import Decision
from app.models.enums import (
    AuditEntityType,
    DecisionStatus,
    DisputeStatus,
    UserRole,
    UserStatus,
    VendorStatus,
)
from app.repositories.dispute_defense import (
    SUBMISSION_ATTEMPT_ACTION,
    DisputeDefenseRepository,
)
from app.schemas.commerce import DisputeRead, TransactionRead, VendorRead
from app.schemas.dispute_defense import (
    CommunicationEvidenceRecord,
    DisputeDecisionApproval,
    DisputeDefenseResult,
    DisputeEventEnvelope,
    DisputeEvidencePackage,
    DisputeSuccessProbability,
    PayPalOrderSnapshot,
    ShippingEvidenceRecord,
)
from app.workflows.dispute.graph import build_dispute_defense_graph
from app.workflows.dispute.state import DisputeDefenseState

logger = logging.getLogger("payagent_ops")
JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JSONValue])
STATE_ADAPTER = TypeAdapter(DisputeDefenseState)
EVIDENCE_SUBMISSION_THRESHOLD = 0.650


class DisputeDefenseService:
    """Run analysis, persist recommendations, and submit only after human review."""

    def __init__(
        self,
        session: AsyncSession,
        paypal_clients: PayPalClients,
        evidence_provider: DisputeEvidenceProvider,
        narrative_generator: DisputeNarrativeGenerator,
        *,
        scorer: DisputeSuccessScorer | None = None,
    ) -> None:
        self._session = session
        self._paypal = paypal_clients
        self._evidence_provider = RetryingDisputeEvidenceProvider(evidence_provider)
        self._narrative_generator = narrative_generator
        self._scorer = scorer or DisputeSuccessScorer()
        self._repository = DisputeDefenseRepository(session)
        self._approval_verifier = PersistedDecisionApprovalVerifier(
            self._repository,
            session,
        )
        self._workflow = build_dispute_defense_graph(self)

    async def process_event(
        self,
        event: DisputeEventEnvelope,
    ) -> DisputeDefenseResult:
        """Verify and analyze a PayPal dispute event, then await human review."""
        state = await self._workflow.ainvoke({"event": event})
        return self._result(STATE_ADAPTER.validate_python(state))

    async def approve_and_submit(
        self,
        approval: DisputeDecisionApproval,
    ) -> DisputeDefenseResult:
        """Record an authenticated human decision and resume the submission graph."""
        await self._approve_decision(approval)
        state = await self._workflow.ainvoke(
            {"resume_decision_id": approval.decision_id}
        )
        return self._result(STATE_ADAPTER.validate_python(state))

    async def receive_dispute_event(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState:
        if state.get("resume_decision_id") is not None:
            return {}
        event = state.get("event")
        if event is None:
            raise ValueError("A verified event or decision ID is required")
        verification = await self._paypal.webhooks.verify(event.headers, event.event)
        if verification.verification_status != "SUCCESS":
            logger.warning(
                "Unverified PayPal dispute event rejected",
                extra={
                    "event": "dispute_event_rejected",
                    "provider": "paypal",
                    "operation": "dispute_webhook_verification",
                },
            )
            raise ValueError("PayPal dispute event signature verification failed")
        event_id = event.paypal_event_id()
        dispute_id = event.paypal_dispute_id()
        logger.info(
            "Verified PayPal dispute event received",
            extra={
                "event": "dispute_event_verified",
                "provider": "paypal",
                "operation": "dispute_defense",
                "dispute_id": dispute_id,
            },
        )
        return {
            "paypal_dispute_id": dispute_id,
            "paypal_event_id": event_id,
        }

    async def retrieve_local_context(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState:
        external_id = state["paypal_dispute_id"]
        case = await self._repository.get_case_by_external_id(external_id)
        if case is None:
            await self._session.rollback()
            raise LookupError("PayPal dispute is not mapped to a local dispute")
        dispute, transaction, vendor = case
        event_id = state["paypal_event_id"]
        if await self._repository.has_processed_event(dispute.id, event_id):
            await self._session.rollback()
            raise ValueError("PayPal dispute event has already been processed")
        if dispute.status not in {
            DisputeStatus.NEEDS_RESPONSE,
            DisputeStatus.UNDER_REVIEW,
        }:
            await self._session.rollback()
            raise ValueError("Resolved disputes cannot enter defense review")

        dispute_read = DisputeRead.model_validate(dispute)
        transaction_read = TransactionRead.model_validate(transaction)
        vendor_read = VendorRead.model_validate(vendor)
        if vendor_read.deleted_at is not None:
            await self._session.rollback()
            raise ValueError("Soft-deleted vendors cannot enter dispute defense")
        await self._session.rollback()
        return {
            "dispute": dispute_read,
            "transaction": transaction_read,
            "vendor": vendor_read,
        }

    async def retrieve_paypal_order(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState:
        transaction = state["transaction"]
        if transaction.paypal_order_id is None:
            return {"paypal_order": None}
        order = await self._paypal.orders.get_order(transaction.paypal_order_id)
        return {"paypal_order": PayPalOrderSnapshot.from_response(order)}

    async def retrieve_shipping_evidence(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState:
        records = await self._evidence_provider.get_shipping_evidence(
            state["vendor"],
            state["transaction"],
        )
        if len(records) > 50:
            raise ValueError("Shipping provider returned more than 50 records")
        return {"shipping_evidence": list(records)}

    async def retrieve_communication_history(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState:
        records = await self._evidence_provider.get_communication_history(
            state["vendor"],
            state["dispute"],
        )
        if len(records) > 50:
            raise ValueError("Communication provider returned more than 50 records")
        return {"communication_history": list(records)}

    async def build_evidence_package(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState:
        dispute = state["dispute"]
        transaction = state["transaction"]
        vendor = state["vendor"]
        order = state.get("paypal_order")
        shipping = state.get("shipping_evidence", [])
        communications = state.get("communication_history", [])
        order_matches = self._order_matches_transaction(
            order,
            transaction.amount,
            transaction.currency,
        )
        evidence = self._build_paypal_evidence(
            order,
            order_matches,
            shipping,
            communications,
        )
        request = DisputeEvidenceRequest(evidence=evidence) if evidence else None
        package = DisputeEvidencePackage(
            dispute_id=dispute.id,
            external_dispute_id=dispute.external_dispute_id,
            dispute_reason=dispute.reason,
            dispute_status=dispute.status,
            response_due_at=dispute.response_due_at,
            vendor_id=vendor.id,
            vendor_name=vendor.name,
            vendor_status=vendor.status,
            transaction_id=transaction.id,
            transaction_status=transaction.status,
            transaction_amount=transaction.amount,
            transaction_currency=transaction.currency,
            paypal_order=order,
            paypal_order_matches_transaction=order_matches,
            shipping_evidence=shipping,
            communication_history=communications,
            paypal_evidence_request=request,
        )
        return {"evidence_package": package, "evidence_request": request}

    async def generate_narrative(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState:
        package = state["evidence_package"]
        narrative = await self._narrative_generator.generate(package)
        if not narrative.strip() or len(narrative) > 5000:
            raise ValueError("Narrative generator returned invalid content")
        return {"narrative": narrative.strip()}

    async def calculate_success_probability(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState:
        return {"success_probability": self._scorer.score(state["evidence_package"])}

    async def recommend_action(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState:
        package = state["evidence_package"]
        probability = state["success_probability"]
        is_actionable = (
            package.paypal_order_matches_transaction
            and package.paypal_evidence_request is not None
            and package.vendor_status.value == "active"
            and probability.value >= EVIDENCE_SUBMISSION_THRESHOLD
        )
        recommendation = "submit_evidence" if is_actionable else "manual_review"
        request = state.get("evidence_request")
        narrative = state["narrative"]
        if recommendation == "submit_evidence" and request is not None:
            if len(request.evidence) >= 20:
                raise ValueError(
                    "No PayPal evidence item slot remains for the narrative"
                )
            request = request.model_copy(
                update={
                    "evidence": [
                        *request.evidence,
                        DisputeEvidence(
                            evidence_type="OTHER",
                            evidence_info={"role": "defense_narrative"},
                            notes=narrative,
                        ),
                    ]
                }
            )
            package = package.model_copy(update={"paypal_evidence_request": request})
        return {
            "recommendation": recommendation,
            "evidence_request": request,
            "evidence_package": package,
        }

    async def create_decision_record(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState:
        dispute = state["dispute"]
        vendor = state["vendor"]
        agent, _ = await self._repository.get_or_create_agent(vendor.id)
        decision = Decision(
            vendor_id=vendor.id,
            agent_id=agent.id,
            dispute_id=dispute.id,
            action_type=state["recommendation"],
            recommendation=(
                "Submit evidence for human review"
                if state["recommendation"] == "submit_evidence"
                else "Manual review required; evidence is insufficient for submission"
            ),
            rationale=state["narrative"],
            confidence=state["success_probability"].value,
            status=DecisionStatus.PENDING,
        )
        self._repository.add(decision)
        await self._session.flush()
        evidence_request = state.get("evidence_request")
        after_state = JSON_OBJECT_ADAPTER.validate_python(
            {
                "evidence_package": state["evidence_package"].model_dump(mode="json"),
                "evidence_request": (
                    evidence_request.model_dump(mode="json")
                    if evidence_request is not None
                    else None
                ),
                "success_probability": state["success_probability"].model_dump(
                    mode="json"
                ),
                "narrative": state["narrative"],
            }
        )
        self._repository.add(
            AuditLog(
                entity_type=AuditEntityType.DECISION,
                entity_id=decision.id,
                vendor_id=vendor.id,
                agent_id=agent.id,
                action="dispute_evidence_prepared",
                after_state=after_state,
            )
        )
        event_id = state["paypal_event_id"]
        self._repository.add(
            AuditLog(
                entity_type=AuditEntityType.DISPUTE,
                entity_id=dispute.id,
                vendor_id=vendor.id,
                agent_id=agent.id,
                action="dispute_event_processed",
                after_state={
                    "decision_id": str(decision.id),
                    "event_type": state["event"].event.event_type,
                },
                request_id=event_id,
            )
        )
        await self._session.commit()
        logger.info(
            "Dispute defense recommendation persisted for review",
            extra={
                "event": "dispute_recommendation_created",
                "operation": "dispute_defense",
                "agent_id": str(agent.id),
                "decision_id": str(decision.id),
                "dispute_id": str(dispute.id),
                "vendor_id": str(vendor.id),
            },
        )
        return {"decision_id": decision.id, "agent_id": agent.id}

    async def await_human_approval(
        self,
        _state: DisputeDefenseState,
    ) -> DisputeDefenseState:
        return {"workflow_status": "awaiting_human_approval"}

    async def load_approved_case(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState:
        decision_id = state["resume_decision_id"]
        decision = await self._repository.get_decision(decision_id)
        artifact = await self._repository.get_prepared_artifact(decision_id)
        if (
            decision is None
            or decision.status is not DecisionStatus.APPROVED
            or decision.action_type != "submit_evidence"
            or decision.dispute_id is None
            or decision.agent_id is None
            or decision.reviewed_by_user_id is None
            or decision.reviewed_at is None
            or artifact is None
            or artifact.after_state is None
        ):
            await self._session.rollback()
            raise ValueError("No approved, prepared dispute decision can be resumed")

        package = DisputeEvidencePackage.model_validate(
            artifact.after_state.get("evidence_package")
        )
        request = DisputeEvidenceRequest.model_validate(
            artifact.after_state.get("evidence_request")
        )
        case = await self._repository.get_case_by_external_id(
            package.external_dispute_id
        )
        if case is None or case[0].id != package.dispute_id:
            await self._session.rollback()
            raise LookupError("Prepared dispute no longer matches a local dispute")
        dispute_read = DisputeRead.model_validate(case[0])
        approval = HumanApproval(
            decision_id=decision.id,
            reviewer_user_id=decision.reviewed_by_user_id,
            approved_at=_as_utc(decision.reviewed_at),
        )
        decision_record_id = decision.id
        agent_id = decision.agent_id
        recommendation = decision.action_type
        narrative = decision.rationale or ""
        probability = DisputeSuccessProbability.model_validate(
            artifact.after_state.get("success_probability")
        )
        await self._session.rollback()
        await self._approval_verifier.verify(
            approval,
            action=SensitivePayPalAction.SUBMIT_DISPUTE_EVIDENCE,
        )
        return {
            "decision_id": decision_record_id,
            "agent_id": agent_id,
            "paypal_dispute_id": package.external_dispute_id,
            "dispute": dispute_read,
            "evidence_package": package,
            "evidence_request": request,
            "approval": approval,
            "recommendation": recommendation,
            "success_probability": probability,
            "narrative": narrative,
        }

    async def submit_evidence(
        self,
        state: DisputeDefenseState,
    ) -> DisputeDefenseState:
        decision_id = state["decision_id"]
        approval = state["approval"]
        evidence_request = state.get("evidence_request")
        if evidence_request is None:
            raise ValueError("Approved dispute evidence request is missing")
        await self._claim_submission(state)
        disputes_client = DisputesClient(
            self._paypal.api,
            approval_verifier=self._approval_verifier,
        )
        try:
            response = await disputes_client.provide_evidence(
                state["paypal_dispute_id"],
                evidence_request,
                approval=approval,
            )
        except PayPalError as exc:
            await self._record_submission_failure(state, type(exc).__name__)
            logger.error(
                "PayPal dispute evidence submission failed",
                extra={
                    "event": "dispute_evidence_submission_failed",
                    "provider": "paypal",
                    "operation": "dispute_evidence_submission",
                    "agent_id": str(state.get("agent_id", "")),
                    "decision_id": str(decision_id),
                    "dispute_id": state["paypal_dispute_id"],
                },
            )
            raise

        audit = AuditLog(
            entity_type=AuditEntityType.DECISION,
            entity_id=decision_id,
            vendor_id=state["dispute"].vendor_id,
            agent_id=state.get("agent_id"),
            action="dispute_evidence_submitted",
            after_state={"paypal_status": response.status},
        )
        self._repository.add(audit)
        await self._session.commit()
        logger.info(
            "PayPal dispute evidence submitted",
            extra={
                "event": "dispute_evidence_submitted",
                "provider": "paypal",
                "operation": "dispute_evidence_submission",
                "agent_id": str(state.get("agent_id", "")),
                "decision_id": str(decision_id),
                "dispute_id": state["paypal_dispute_id"],
            },
        )
        return {
            "workflow_status": "submitted",
            "paypal_submission_status": response.status,
        }

    async def _approve_decision(self, approval: DisputeDecisionApproval) -> None:
        decision = await self._repository.get_decision(approval.decision_id, lock=True)
        reviewer = await self._repository.get_user(approval.reviewer_user_id)
        if (
            decision is None
            or decision.action_type != "submit_evidence"
            or decision.dispute_id is None
        ):
            await self._session.rollback()
            raise ValueError("Decision is not eligible for dispute evidence approval")
        if (
            reviewer is None
            or reviewer.status is not UserStatus.ACTIVE
            or reviewer.role
            not in {UserRole.ADMIN, UserRole.OPERATOR, UserRole.REVIEWER}
        ):
            await self._session.rollback()
            raise ValueError("An active admin or operator must approve this decision")
        if decision.status is DecisionStatus.APPROVED:
            if decision.reviewed_by_user_id != reviewer.id:
                await self._session.rollback()
                raise ValueError("Decision was approved by a different reviewer")
            await self._session.rollback()
            return
        if decision.status is not DecisionStatus.PENDING:
            await self._session.rollback()
            raise ValueError("Only pending decisions can be approved")

        decision.status = DecisionStatus.APPROVED
        decision.reviewed_by_user_id = reviewer.id
        decision.reviewed_at = datetime.now(UTC)
        self._repository.add(
            AuditLog(
                entity_type=AuditEntityType.DECISION,
                entity_id=decision.id,
                vendor_id=decision.vendor_id,
                actor_user_id=reviewer.id,
                action="dispute_evidence_approved",
                after_state={"decision_status": DecisionStatus.APPROVED.value},
            )
        )
        await self._session.commit()

    async def _claim_submission(self, state: DisputeDefenseState) -> None:
        decision = await self._repository.get_decision(state["decision_id"], lock=True)
        if (
            decision is None
            or decision.status is not DecisionStatus.APPROVED
            or decision.action_type != "submit_evidence"
        ):
            await self._session.rollback()
            raise ValueError("Approved decision is required before submission")
        case = await self._repository.get_case_by_external_id(
            state["paypal_dispute_id"],
            lock=True,
        )
        if (
            case is None
            or case[0].id != decision.dispute_id
            or case[0].status
            not in {DisputeStatus.NEEDS_RESPONSE, DisputeStatus.UNDER_REVIEW}
            or case[2].status is not VendorStatus.ACTIVE
            or case[2].deleted_at is not None
        ):
            await self._session.rollback()
            raise ValueError("The dispute or vendor is no longer actionable")
        if await self._repository.has_submission_attempt(decision.id):
            await self._session.rollback()
            raise ValueError(
                "Submission was already attempted; reconcile the PayPal result manually"
            )
        self._repository.add(
            AuditLog(
                entity_type=AuditEntityType.DECISION,
                entity_id=decision.id,
                vendor_id=decision.vendor_id,
                agent_id=decision.agent_id,
                action=SUBMISSION_ATTEMPT_ACTION,
                after_state={"state": "started"},
            )
        )
        await self._session.commit()

    async def _record_submission_failure(
        self,
        state: DisputeDefenseState,
        error_type: str,
    ) -> None:
        self._repository.add(
            AuditLog(
                entity_type=AuditEntityType.DECISION,
                entity_id=state["decision_id"],
                vendor_id=state["dispute"].vendor_id,
                agent_id=state.get("agent_id"),
                action="dispute_evidence_submission_failed",
                after_state={"error_type": error_type},
            )
        )
        await self._session.commit()

    @staticmethod
    def _build_paypal_evidence(
        order: PayPalOrderSnapshot | None,
        order_matches_transaction: bool,
        shipping: list[ShippingEvidenceRecord],
        communications: list[CommunicationEvidenceRecord],
    ) -> list[DisputeEvidence]:
        evidence: list[DisputeEvidence] = []
        if order is not None and order_matches_transaction:
            evidence.append(
                DisputeEvidence(
                    evidence_type="OTHER",
                    evidence_info={
                        "order_id": order.id,
                        "order_status": order.status,
                        "intent": order.intent,
                    },
                    notes="PayPal order record",
                )
            )
        evidence.extend(
            DisputeEvidence(
                evidence_type="PROOF_OF_FULFILLMENT",
                evidence_info={
                    "tracking_number": item.tracking_number,
                    "carrier": item.carrier,
                    "delivery_status": item.delivery_status,
                    "delivered_at": (
                        item.delivered_at.isoformat()
                        if item.delivered_at is not None
                        else None
                    ),
                    "source_reference": item.source_reference,
                    "evidence_url": (
                        str(item.evidence_url)
                        if item.evidence_url is not None
                        else None
                    ),
                },
                notes=item.summary,
            )
            for item in shipping
        )
        evidence.extend(
            DisputeEvidence(
                evidence_type="OTHER",
                evidence_info={
                    "source_reference": item.source_reference,
                    "channel": item.channel,
                    "occurred_at": item.occurred_at.isoformat(),
                    "customer_acknowledged": item.customer_acknowledged,
                },
                notes=item.summary,
            )
            for item in communications
        )
        if len(evidence) > 19:
            raise ValueError("PayPal evidence package exceeds the 19 source-item limit")
        return evidence

    @staticmethod
    def _order_matches_transaction(
        order: PayPalOrderSnapshot | None,
        transaction_amount: Decimal,
        transaction_currency: str,
    ) -> bool:
        if order is None or order.status.upper() != "COMPLETED":
            return False
        matching_units = [
            unit.amount
            for unit in order.purchase_units
            if unit.amount is not None
            and unit.amount.currency_code == transaction_currency
        ]
        if any(amount.value == transaction_amount for amount in matching_units):
            return True
        all_units_have_same_currency = len(matching_units) == len(
            order.purchase_units
        ) and bool(matching_units)
        return (
            all_units_have_same_currency
            and sum(
                (amount.value for amount in matching_units),
                start=Decimal(0),
            )
            == transaction_amount
        )

    @staticmethod
    def _result(state: DisputeDefenseState) -> DisputeDefenseResult:
        package = state["evidence_package"]
        return DisputeDefenseResult.model_validate(
            {
                "workflow_status": state.get(
                    "workflow_status",
                    "awaiting_human_approval",
                ),
                "decision_id": state["decision_id"],
                "dispute_id": package.dispute_id,
                "recommendation": state["recommendation"],
                "success_probability": state["success_probability"],
                "narrative": state["narrative"],
                "paypal_submission_status": state.get("paypal_submission_status"),
            }
        )


def build_narrative_generator(settings: Settings) -> DisputeNarrativeGenerator:
    """Build the configured narrative provider without exposing API credentials."""
    return OpenAIDisputeNarrativeGenerator.from_settings(settings)
