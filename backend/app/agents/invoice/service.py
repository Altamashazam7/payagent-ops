"""Application service coordinating invoice compliance and human review."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.invoice.narrative import (
    InvoiceNarrativeGenerator,
    OpenAIInvoiceNarrativeGenerator,
)
from app.agents.invoice.scoring import InvoiceComplianceScorer
from app.core.settings import Settings
from app.core.types import JSONValue
from app.models.audit_log import AuditLog
from app.models.decision import Decision
from app.models.enums import (
    AuditEntityType,
    DecisionStatus,
    UserRole,
    UserStatus,
)
from app.repositories.invoice_compliance import InvoiceComplianceRepository
from app.schemas.commerce import InvoiceRead, VendorRead
from app.schemas.invoice_compliance import (
    InvoiceComplianceAssessment,
    InvoiceComplianceResult,
    InvoiceDecisionReview,
)
from app.workflows.invoice.graph import build_invoice_compliance_graph
from app.workflows.invoice.state import InvoiceComplianceState

logger = logging.getLogger("payagent_ops")
STATE_ADAPTER = TypeAdapter(InvoiceComplianceState)
JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JSONValue])
INVOICE_ACTIONS = {"approve_invoice", "manual_review"}


class InvoiceComplianceService:
    """Create reviewable invoice findings; never send or modify an invoice."""

    def __init__(
        self,
        session: AsyncSession,
        narrative_generator: InvoiceNarrativeGenerator,
        *,
        scorer: InvoiceComplianceScorer | None = None,
    ) -> None:
        self._session = session
        self._repository = InvoiceComplianceRepository(session)
        self._narrative_generator = narrative_generator
        self._scorer = scorer or InvoiceComplianceScorer()
        self._workflow = build_invoice_compliance_graph(self)

    @classmethod
    def from_settings(
        cls,
        session: AsyncSession,
        settings: Settings,
    ) -> InvoiceComplianceService:
        """Create the configured async narrative generator."""
        return cls(session, OpenAIInvoiceNarrativeGenerator.from_settings(settings))

    async def review(self, invoice_id: UUID) -> InvoiceComplianceResult:
        """Assess an invoice, persist a pending decision, and stop for review."""
        raw_state = await self._workflow.ainvoke({"invoice_id": invoice_id})
        state = STATE_ADAPTER.validate_python(raw_state)
        return self._result(state, "awaiting_human_approval")

    async def review_decision(
        self,
        request: InvoiceDecisionReview,
    ) -> InvoiceComplianceResult:
        """Record an active human's approval or rejection of a recommendation."""
        decision = await self._repository.get_decision(request.decision_id, lock=True)
        reviewer = await self._repository.get_user(request.reviewer_user_id)
        if (
            decision is None
            or decision.invoice_id is None
            or decision.action_type not in INVOICE_ACTIONS
        ):
            await self._session.rollback()
            raise ValueError("Decision is not an invoice compliance recommendation")
        if (
            reviewer is None
            or reviewer.status is not UserStatus.ACTIVE
            or reviewer.role
            not in {UserRole.ADMIN, UserRole.OPERATOR, UserRole.REVIEWER}
            or reviewer.deleted_at is not None
        ):
            await self._session.rollback()
            raise ValueError("An active admin or operator must review this decision")
        artifact = await self._repository.get_prepared_artifact(decision.id)
        case = await self._repository.get_context(decision.invoice_id, lock=True)
        if (
            artifact is None
            or artifact.after_state is None
            or case is None
            or not self._matches_artifact(
                case[0].updated_at, "invoice_updated_at", artifact.after_state
            )
            or not self._matches_artifact(
                case[1].updated_at, "vendor_updated_at", artifact.after_state
            )
        ):
            await self._session.rollback()
            raise ValueError("Invoice changed after assessment; run a fresh review")
        assessment = InvoiceComplianceAssessment.model_validate(
            artifact.after_state.get("assessment")
        )
        current_duplicates = await self._repository.list_duplicate_candidates(case[0])
        if {item.id for item in current_duplicates} != set(
            assessment.duplicate_invoice_ids
        ):
            await self._session.rollback()
            raise ValueError("Invoice duplicates changed after assessment")
        target_status = (
            DecisionStatus.APPROVED if request.approve else DecisionStatus.REJECTED
        )
        if decision.status is not DecisionStatus.PENDING:
            is_same_review = (
                decision.status is target_status
                and decision.reviewed_by_user_id == reviewer.id
            )
            await self._session.rollback()
            if not is_same_review:
                raise ValueError("Decision has already been reviewed")
        else:
            decision.status = target_status
            decision.reviewed_by_user_id = reviewer.id
            decision.reviewed_at = datetime.now(UTC)
            self._repository.add(
                AuditLog(
                    entity_type=AuditEntityType.DECISION,
                    entity_id=decision.id,
                    vendor_id=decision.vendor_id,
                    actor_user_id=reviewer.id,
                    action=(
                        "invoice_compliance_approved"
                        if request.approve
                        else "invoice_compliance_rejected"
                    ),
                    after_state={"decision_status": target_status.value},
                )
            )
            await self._session.commit()
            logger.info(
                "Invoice compliance recommendation reviewed by human",
                extra={
                    "event": (
                        "invoice_compliance_approved"
                        if request.approve
                        else "invoice_compliance_rejected"
                    ),
                    "operation": "invoice_compliance_review",
                    "agent_id": str(decision.agent_id or ""),
                    "decision_id": str(decision.id),
                    "invoice_id": str(decision.invoice_id),
                    "reviewer_user_id": str(reviewer.id),
                    "vendor_id": str(decision.vendor_id),
                },
            )
        return await self._load_result(
            request.decision_id,
            "approved" if request.approve else "rejected",
        )

    async def load_invoice(
        self,
        state: InvoiceComplianceState,
    ) -> InvoiceComplianceState:
        invoice_id = state.get("invoice_id")
        if invoice_id is None:
            raise ValueError("An invoice ID is required for compliance review")
        case = await self._repository.get_context(invoice_id)
        if case is None:
            await self._session.rollback()
            raise LookupError("Invoice does not exist")
        invoice, vendor = case
        if vendor.deleted_at is not None:
            await self._session.rollback()
            raise ValueError("Soft-deleted vendors cannot enter invoice review")
        invoice_read = InvoiceRead.model_validate(invoice)
        vendor_read = VendorRead.model_validate(vendor)
        await self._session.rollback()
        return {"invoice": invoice_read, "vendor": vendor_read}

    async def find_duplicates(
        self,
        state: InvoiceComplianceState,
    ) -> InvoiceComplianceState:
        case = await self._repository.get_context(state["invoice"].id)
        if case is None:
            await self._session.rollback()
            raise LookupError("Invoice no longer exists")
        candidates = await self._repository.list_duplicate_candidates(case[0])
        ids = [candidate.id for candidate in candidates]
        await self._session.rollback()
        return {"duplicate_invoice_ids": ids}

    async def assess_invoice(
        self,
        state: InvoiceComplianceState,
    ) -> InvoiceComplianceState:
        return {
            "assessment": self._scorer.score(
                state["invoice"],
                state["vendor"],
                state.get("duplicate_invoice_ids", []),
            )
        }

    async def generate_summary(
        self,
        state: InvoiceComplianceState,
    ) -> InvoiceComplianceState:
        narrative = await self._narrative_generator.generate(
            state["invoice"],
            state["assessment"],
        )
        if not narrative.strip() or len(narrative) > 5000:
            raise ValueError("Invoice narrative generator returned invalid content")
        return {"narrative": narrative.strip()}

    async def persist_decision(
        self,
        state: InvoiceComplianceState,
    ) -> InvoiceComplianceState:
        invoice = state["invoice"]
        vendor = state["vendor"]
        current = await self._repository.get_context(invoice.id, lock=True)
        if (
            current is None
            or InvoiceRead.model_validate(current[0]) != invoice
            or VendorRead.model_validate(current[1]) != vendor
        ):
            await self._session.rollback()
            raise ValueError("Invoice or vendor changed during compliance review")
        current_duplicates = await self._repository.list_duplicate_candidates(
            current[0]
        )
        if {item.id for item in current_duplicates} != set(
            state.get("duplicate_invoice_ids", [])
        ):
            await self._session.rollback()
            raise ValueError("Invoice duplicates changed during compliance review")
        agent = await self._repository.get_or_create_agent(vendor.id)
        assessment = state["assessment"]
        decision = Decision(
            vendor_id=vendor.id,
            agent_id=agent.id,
            invoice_id=invoice.id,
            action_type=assessment.recommendation,
            recommendation=(
                "Invoice passed current compliance checks; human review required"
                if assessment.recommendation == "approve_invoice"
                else "Invoice has compliance findings requiring manual review"
            ),
            rationale=state["narrative"],
            confidence=assessment.score,
            status=DecisionStatus.PENDING,
        )
        self._repository.add(decision)
        await self._session.flush()
        after_state = JSON_OBJECT_ADAPTER.validate_python(
            {
                "assessment": assessment.model_dump(mode="json"),
                "narrative": state["narrative"],
                "invoice_updated_at": invoice.updated_at.isoformat(),
                "vendor_updated_at": vendor.updated_at.isoformat(),
            }
        )
        self._repository.add(
            AuditLog(
                entity_type=AuditEntityType.DECISION,
                entity_id=decision.id,
                vendor_id=vendor.id,
                agent_id=agent.id,
                action="invoice_compliance_assessed",
                after_state=after_state,
            )
        )
        await self._session.commit()
        logger.info(
            "Invoice compliance recommendation persisted",
            extra={
                "event": "invoice_compliance_assessed",
                "operation": "invoice_compliance",
                "agent_id": str(agent.id),
                "decision_id": str(decision.id),
                "invoice_id": str(invoice.id),
                "vendor_id": str(vendor.id),
            },
        )
        return {"decision_id": decision.id, "agent_id": agent.id}

    async def await_human_review(
        self,
        _state: InvoiceComplianceState,
    ) -> InvoiceComplianceState:
        return {"workflow_status": "awaiting_human_approval"}

    async def _load_result(
        self,
        decision_id: UUID,
        status: Literal["approved", "rejected"],
    ) -> InvoiceComplianceResult:
        decision = await self._repository.get_decision(decision_id)
        artifact = await self._repository.get_prepared_artifact(decision_id)
        if (
            decision is None
            or decision.invoice_id is None
            or artifact is None
            or artifact.after_state is None
        ):
            await self._session.rollback()
            raise LookupError("Invoice compliance review artifact is missing")
        assessment = InvoiceComplianceAssessment.model_validate(
            artifact.after_state.get("assessment")
        )
        narrative = artifact.after_state.get("narrative")
        if not isinstance(narrative, str):
            await self._session.rollback()
            raise TypeError("Invoice compliance narrative artifact is invalid")
        result = InvoiceComplianceResult(
            invoice_id=decision.invoice_id,
            decision_id=decision.id,
            recommendation=assessment.recommendation,
            assessment=assessment,
            narrative=narrative,
            workflow_status=status,  # validated by the result schema
        )
        await self._session.rollback()
        return result

    def _result(
        self,
        state: InvoiceComplianceState,
        status: Literal["awaiting_human_approval"],
    ) -> InvoiceComplianceResult:
        return InvoiceComplianceResult(
            invoice_id=state["invoice"].id,
            decision_id=state["decision_id"],
            recommendation=state["assessment"].recommendation,
            assessment=state["assessment"],
            narrative=state["narrative"],
            workflow_status=status,
        )

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

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
