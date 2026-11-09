"""Persistence operations for dispute-defense decisions and audit records."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.audit_log import AuditLog
from app.models.decision import Decision
from app.models.dispute import Dispute
from app.models.enums import (
    AgentStatus,
    AuditEntityType,
)
from app.models.transaction import Transaction
from app.models.user import User
from app.models.vendor import Vendor

AGENT_NAME = "Dispute Defense Agent"
AGENT_TYPE = "dispute_defense"
SUBMISSION_ATTEMPT_ACTION = "dispute_evidence_submission_started"


class AmbiguousDisputeError(LookupError):
    """Raised when a PayPal dispute ID matches multiple local vendors."""


class DisputeDefenseRepository:
    """Stage/query domain entities while leaving transaction control to services."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_case_by_external_id(
        self,
        external_dispute_id: str,
        *,
        lock: bool = False,
    ) -> tuple[Dispute, Transaction, Vendor] | None:
        statement = select(Dispute).where(
            Dispute.external_dispute_id == external_dispute_id
        )
        if lock:
            statement = statement.with_for_update()
        result = await self._session.execute(statement.limit(2))
        disputes = list(result.scalars().all())
        if len(disputes) > 1:
            raise AmbiguousDisputeError(
                "PayPal dispute ID maps to multiple local vendors"
            )
        if not disputes:
            return None

        dispute = disputes[0]
        transaction = await self._session.get(Transaction, dispute.transaction_id)
        vendor = await self._session.get(Vendor, dispute.vendor_id)
        if transaction is None or vendor is None:
            raise LookupError("Dispute transaction or vendor record is missing")
        if transaction.vendor_id != vendor.id:
            raise ValueError("Dispute transaction crosses vendor boundaries")
        return dispute, transaction, vendor

    async def has_processed_event(self, dispute_id: UUID, event_id: str) -> bool:
        result = await self._session.execute(
            select(AuditLog.id)
            .where(
                AuditLog.entity_type == AuditEntityType.DISPUTE,
                AuditLog.entity_id == dispute_id,
                AuditLog.action == "dispute_event_processed",
                AuditLog.request_id == event_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def get_or_create_agent(self, vendor_id: UUID) -> tuple[Agent, bool]:
        vendor_result = await self._session.execute(
            select(Vendor.id).where(Vendor.id == vendor_id).with_for_update()
        )
        if vendor_result.scalar_one_or_none() is None:
            raise LookupError("Vendor does not exist")
        result = await self._session.execute(
            select(Agent).where(
                Agent.vendor_id == vendor_id,
                Agent.name == AGENT_NAME,
                Agent.deleted_at.is_(None),
            )
        )
        agent = result.scalar_one_or_none()
        if agent is not None:
            if agent.status is not AgentStatus.ACTIVE:
                raise ValueError("Dispute defense agent is not active")
            return agent, False

        agent = Agent(
            vendor_id=vendor_id,
            name=AGENT_NAME,
            agent_type=AGENT_TYPE,
            status=AgentStatus.ACTIVE,
        )
        self._session.add(agent)
        await self._session.flush()
        self._session.add(
            AuditLog(
                entity_type=AuditEntityType.AGENT,
                entity_id=agent.id,
                vendor_id=vendor_id,
                agent_id=agent.id,
                action="dispute_defense_agent_registered",
                after_state={"status": AgentStatus.ACTIVE.value},
            )
        )
        return agent, True

    async def get_decision(
        self,
        decision_id: UUID,
        *,
        lock: bool = False,
    ) -> Decision | None:
        statement = select(Decision).where(Decision.id == decision_id)
        if lock:
            statement = statement.with_for_update()
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_user(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_prepared_artifact(self, decision_id: UUID) -> AuditLog | None:
        result = await self._session.execute(
            select(AuditLog)
            .where(
                AuditLog.entity_type == AuditEntityType.DECISION,
                AuditLog.entity_id == decision_id,
                AuditLog.action == "dispute_evidence_prepared",
            )
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def has_submission_attempt(self, decision_id: UUID) -> bool:
        result = await self._session.execute(
            select(AuditLog.id)
            .where(
                AuditLog.entity_type == AuditEntityType.DECISION,
                AuditLog.entity_id == decision_id,
                AuditLog.action == SUBMISSION_ATTEMPT_ACTION,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    def add(self, entity: Agent | AuditLog | Decision) -> None:
        """Stage a workflow entity without committing its caller's transaction."""
        self._session.add(entity)
